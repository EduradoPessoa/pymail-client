# 03 — Modelo de Dados

**Projeto:** PyMail Client
**Versão desta spec:** 1.0 · **Data:** 2026-09-25
**Documentos correlatos:** `01-requisitos.md` · `02-arquitetura.md` (ADR-005, ADR-006) · `../plans/fase1.md`

---

## 1. Princípios de persistência

1. **O banco é cache, exceto pelo que o usuário escreveu.** Mensagens, corpos e índice podem ser apagados e reconstruídos a partir do servidor a qualquer momento. Rascunhos e a fila de envio (`outbox`) são dados do usuário e não podem ser perdidos (RF-SET-05, RNF-REL-01).
2. **Nenhum segredo no banco.** Senhas e tokens vivem exclusivamente no keyring do sistema operacional (RNF-SEC-01). O banco guarda apenas o identificador da conta no keyring.
3. **Afinidade de thread governa o schema.** Toda conexão usa os mesmos PRAGMAs, e nenhuma transação atravessa I/O de rede (ADR-006).
4. **Semântica declarada no banco onde for barata.** `CHECK`, `FOREIGN KEY` e índices parciais custam pouco e eliminam categorias inteiras de estado inválido que, de outra forma, só apareceriam como bug de interface.

**Localização.** `QStandardPaths.AppDataLocation` — diretório `0700`; arquivos `0600`. Ver `02-arquitetura.md` §8.1.

---

## 2. PRAGMAs e concorrência

Aplicados em **toda** conexão, imediatamente após abri-la:

```sql
PRAGMA journal_mode = WAL;        -- leitores concorrentes com um escritor
PRAGMA foreign_keys = ON;         -- ON DELETE CASCADE depende disto
PRAGMA busy_timeout = 5000;       -- 5 s antes de desistir de um lock
PRAGMA synchronous = NORMAL;      -- correto e seguro em WAL; não é NORMAL no modo rollback
PRAGMA temp_store = MEMORY;
PRAGMA cache_size = -8000;        -- ~8 MB de page cache por conexão
```

Três observações que a implementação precisa respeitar:

- **`foreign_keys` é por conexão**, não persistido no arquivo. Esquecer de aplicá-lo transforma `ON DELETE CASCADE` em decoração e deixa órfãos ao remover uma conta — exatamente o que CA-RF-ACC-05-1 verifica.
- **`journal_mode = WAL` é persistido** no arquivo, mas não custa reaplicá-lo.
- **`synchronous = NORMAL` só é seguro porque o modo é WAL.** Em `journal_mode=DELETE`, ele arrisca corrupção em queda de energia.

**Regra da transação curta.** Nenhuma transação permanece aberta através de uma chamada de rede. O padrão obrigatório é: buscar no servidor → fechar a rede → abrir transação → gravar → confirmar. Isso é o que impede que um servidor IMAP lento bloqueie o banco para as demais contas (ADR-006).

**Conexão por thread.** `storage.py` mantém um `threading.local()` com uma `sqlite3.Connection` própria por thread. Objetos `sqlite3.Connection` não são seguros entre threads e não podem ser compartilhados, mesmo com `check_same_thread=False`.

**Escrita concorrente.** WAL admite um escritor por vez. Como as escritas são curtas (inserir um lote de cabeçalhos, gravar um corpo), o `busy_timeout` de 5 s resolve a disputa sem retry explícito na grande maioria dos casos. `SQLITE_BUSY` que persista gera nova tentativa limitada, com registro, e nunca uma exceção que chegue à interface como erro fatal.

---

## 3. DDL da versão 1

Script completo e normativo. É o conteúdo da migração `001_initial`.

```sql
-- ─────────────────────────── Controle de versão ───────────────────────────
CREATE TABLE schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

-- ──────────────────────────────── Contas ──────────────────────────────────
-- Sem senha, sem token: a credencial vive no keyring sob a chave
--   service = "pymail-client", username = <email>
-- para OAuth2 [F2]: username = <email>#oauth
CREATE TABLE accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT    NOT NULL,
    display_name        TEXT    NOT NULL DEFAULT '',
    protocol            TEXT    NOT NULL DEFAULT 'imap'
                                CHECK (protocol IN ('imap', 'pop3')),
    auth_type           TEXT    NOT NULL DEFAULT 'password'
                                CHECK (auth_type IN ('password', 'oauth2')),
    username            TEXT    NOT NULL,
    incoming_host       TEXT    NOT NULL,
    incoming_port       INTEGER NOT NULL,
    incoming_security   TEXT    NOT NULL DEFAULT 'ssl'
                                CHECK (incoming_security IN ('ssl', 'starttls', 'none')),
    outgoing_host       TEXT    NOT NULL,
    outgoing_port       INTEGER NOT NULL,
    outgoing_security   TEXT    NOT NULL DEFAULT 'starttls'
                                CHECK (outgoing_security IN ('ssl', 'starttls', 'none')),
    -- Exceção explícita e registrada do RF-SND-07. Padrão: 0 (recusar).
    allow_insecure_outgoing INTEGER NOT NULL DEFAULT 0,
    is_enabled          INTEGER NOT NULL DEFAULT 1,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    UNIQUE (email)
);

-- ──────────────────────────────── Pastas ──────────────────────────────────
CREATE TABLE folders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    remote_name   TEXT    NOT NULL,
    display_name  TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'custom'
                          CHECK (kind IN ('inbox','sent','drafts','trash',
                                          'archive','spam','custom')),
    delimiter     TEXT    NOT NULL DEFAULT '/',
    uidvalidity   INTEGER NOT NULL DEFAULT 0,
    uidnext       INTEGER NOT NULL DEFAULT 1,
    unread_count  INTEGER NOT NULL DEFAULT 0,
    is_selectable INTEGER NOT NULL DEFAULT 1,
    last_sync_at  INTEGER,
    UNIQUE (account_id, remote_name)
);
CREATE INDEX idx_folders_account_kind ON folders(account_id, kind);

-- ─────────────────────────────── Mensagens ────────────────────────────────
-- Apenas cabeçalhos na sincronização inicial (RF-MSG-01).
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    folder_id       INTEGER NOT NULL REFERENCES folders(id)  ON DELETE CASCADE,
    remote_id       TEXT    NOT NULL,          -- UID (IMAP) / identificador (POP3 [F2])
    message_id      TEXT,
    in_reply_to     TEXT,
    references_hdr  TEXT,
    thread_id       TEXT,                      -- reservado para RF-RD-10 [F2]
    subject         TEXT    NOT NULL DEFAULT '',
    from_name       TEXT    NOT NULL DEFAULT '',
    from_addr       TEXT    NOT NULL DEFAULT '',   -- sempre minúsculo
    to_addrs        TEXT    NOT NULL DEFAULT '[]', -- JSON: ["a@x", "b@y"]
    cc_addrs        TEXT    NOT NULL DEFAULT '[]',
    date_utc        INTEGER NOT NULL,              -- epoch UTC
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    has_attachments INTEGER NOT NULL DEFAULT 0,
    is_read         INTEGER NOT NULL DEFAULT 0,
    is_flagged      INTEGER NOT NULL DEFAULT 0,
    is_answered     INTEGER NOT NULL DEFAULT 0,
    is_draft        INTEGER NOT NULL DEFAULT 0,
    body_state      TEXT    NOT NULL DEFAULT 'headers'
                            CHECK (body_state IN ('headers','cached','evicted','failed')),
    body_fetched_at INTEGER,
    snoozed_until   INTEGER,                       -- reservado para RF-ORG-07 [F2]
    -- Operação otimista pendente (RF-MSG-09), ex.: 'move:12' | 'flags:seen' | NULL
    pending_op      TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    UNIQUE (folder_id, remote_id)
);

-- Ordenação da lista de mensagens: o caso de uso mais frequente do aplicativo.
CREATE INDEX idx_messages_folder_date   ON messages(folder_id, date_utc DESC);
-- Contador de não lidos por conta (caixa unificada [F2] já se beneficia).
CREATE INDEX idx_messages_account_unread ON messages(account_id, is_read, date_utc DESC);
-- Encadeamento e deduplicação por Message-ID.
CREATE INDEX idx_messages_message_id    ON messages(message_id) WHERE message_id IS NOT NULL;
-- Pré-busca e despejo (RF-MSG-03, RF-MSG-06): só interessa o que NÃO está em cache.
CREATE INDEX idx_messages_body_pending  ON messages(body_state, date_utc DESC)
    WHERE body_state <> 'cached';
-- Reapresentação de snooze [F2].
CREATE INDEX idx_messages_snooze        ON messages(snoozed_until)
    WHERE snoozed_until IS NOT NULL;
-- Fila de operações otimistas ainda não confirmadas pelo servidor.
CREATE INDEX idx_messages_pending_op    ON messages(pending_op) WHERE pending_op IS NOT NULL;

-- ───────────────────────────────── Corpos ─────────────────────────────────
-- html_raw NÃO é armazenado de propósito: ver §6.3.
CREATE TABLE bodies (
    message_rowid     INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    text_plain        TEXT,
    html_sanitized    TEXT,
    sanitizer_version INTEGER NOT NULL DEFAULT 1,
    size_bytes        INTEGER NOT NULL DEFAULT 0,   -- soma dos campos TEXT gravados
    fetched_at        INTEGER NOT NULL,
    last_access_at    INTEGER NOT NULL              -- base do despejo LRU
);
CREATE INDEX idx_bodies_lru ON bodies(last_access_at);

-- ─────────────────────────────── Anexos ───────────────────────────────────
-- Fase 1: apenas metadados. Conteúdo só sob demanda (RF-MSG-07).
CREATE TABLE attachments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    message_rowid  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    part_id        TEXT    NOT NULL,
    filename       TEXT    NOT NULL DEFAULT '',
    mime_type      TEXT    NOT NULL DEFAULT 'application/octet-stream',
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    content_id     TEXT,
    is_inline      INTEGER NOT NULL DEFAULT 0,
    cache_state    TEXT    NOT NULL DEFAULT 'meta'
                           CHECK (cache_state IN ('meta','cached','failed')),
    cache_path     TEXT,
    UNIQUE (message_rowid, part_id)
);
CREATE INDEX idx_attachments_message ON attachments(message_rowid);

-- ──────────────── Permissão de imagens por remetente (RF-RD-03) ───────────
CREATE TABLE sender_image_policy (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    from_addr  TEXT    NOT NULL,           -- minúsculo
    allowed_at INTEGER NOT NULL,
    UNIQUE (account_id, from_addr)
);

-- ─────────────────── Fila de saída e Undo Send (RF-SND-03) ────────────────
-- ON DELETE SET NULL: remover a conta não pode destruir o rascunho do usuário.
CREATE TABLE outbox (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    message_id       TEXT    NOT NULL,        -- gerado na criação, estável
    to_addrs         TEXT    NOT NULL DEFAULT '[]',
    cc_addrs         TEXT    NOT NULL DEFAULT '[]',
    bcc_addrs        TEXT    NOT NULL DEFAULT '[]',
    subject          TEXT    NOT NULL DEFAULT '',
    body_text        TEXT    NOT NULL DEFAULT '',
    body_html        TEXT,
    in_reply_to      TEXT,
    references_hdr   TEXT,
    attachment_paths TEXT    NOT NULL DEFAULT '[]',
    state            TEXT    NOT NULL DEFAULT 'draft'
                             CHECK (state IN ('draft','queued','sending',
                                              'sent','failed','canceled')),
    send_at          INTEGER,                 -- epoch: fim da janela de undo
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    smtp_response    TEXT,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);
-- O agendador consulta apenas o que está vencendo (RF-SND-03).
CREATE INDEX idx_outbox_due ON outbox(send_at) WHERE state = 'queued';

-- ─────────────── Operações otimistas pendentes (RF-MSG-09) ────────────────
CREATE TABLE pending_ops (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    folder_id  INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    op_type    TEXT    NOT NULL CHECK (op_type IN ('move','flags','delete')),
    remote_ids TEXT    NOT NULL DEFAULT '[]',   -- JSON: ["12","13"]
    payload    TEXT    NOT NULL DEFAULT '{}',   -- ex.: {"destination":"Archive"}
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX idx_pending_ops_account ON pending_ops(account_id, created_at);

-- ─────────────────────────── Busca full-text (FTS5) ───────────────────────
-- rowid = messages.id. Tokenizador insensível a acentos (CA-RF-SRCH-01-1)
-- e índices de prefixo de 2 e 3 caracteres para busca enquanto se digita.
CREATE VIRTUAL TABLE messages_fts USING fts5(
    subject,
    sender,
    recipients,
    body,
    tokenize = "unicode61 remove_diacritics 2",
    prefix   = '2 3'
);
```

### 3.1 Diagrama de relacionamentos

```text
accounts 1───N folders 1───N messages 1───1 bodies
    │                              │
    │                              └──N attachments
    ├──N sender_image_policy
    ├──N pending_ops
    └──N outbox            (ON DELETE SET NULL: preserva o rascunho do usuário)

messages.id ═══ messages_fts.rowid      (mantido explicitamente — ADR-005)
```

---

## 4. Mapeamento requisito → estrutura de dados

| Requisito | Onde vive | Observação |
|---|---|---|
| RF-ACC-01, RF-ACC-02 | `accounts` | `UNIQUE(email)`; multi-conta desde a v1 |
| RF-ACC-04 | `accounts.auth_type` | O valor é interpretado pelo `AuthProvider`, não pelo banco |
| RF-ACC-05 | `ON DELETE CASCADE` em todas as tabelas filhas | Depende de `foreign_keys=ON` **por conexão** |
| RF-ACC-06 [F2] | `accounts.auth_type = 'oauth2'` | Nenhuma coluna nova necessária |
| RF-MSG-01 | `messages` sem `bodies` | Cabeçalhos existem sem corpo por construção |
| RF-MSG-02 | `bodies` + `messages.body_state` | Transição `headers → cached` |
| RF-MSG-04 | `folders.uidvalidity`, `folders.uidnext` | Mudança de `uidvalidity` dispara `invalidate_folder` |
| RF-MSG-06 | `bodies.last_access_at` + `size_bytes` | Base do LRU em dois níveis (§6) |
| RF-MSG-07 | `attachments.cache_state` | `meta` → `cached` só sob demanda |
| RF-MSG-09 | `messages.pending_op` + `pending_ops` | Estado visível antes da confirmação do servidor |
| RF-MSG-11 [F2] | `messages.date_utc` + despejo por idade | Reutiliza o mecanismo de §6 |
| RF-RD-03 | `sender_image_policy` | Granularidade por conta **e** remetente |
| RF-SND-03 | `outbox.state`, `outbox.send_at` | `queued` + `send_at` futuro = janela de undo |
| RF-SND-04 | `outbox` persistido, `ON DELETE SET NULL` | Sobrevive a reinício e a exclusão de conta |
| RF-SRCH-01 | `messages_fts` | `remove_diacritics 2` |
| RF-SRCH-03 | Índices parciais de `messages` | Filtros combinam FTS5 com predicados SQL |
| RF-SRCH-04 | Transação única em `store_body` | ADR-005 |
| RF-ORG-07 [F2] | `messages.snoozed_until` | Coluna já reservada: sem migração destrutiva |
| RF-RD-10 [F2] | `messages.thread_id` | Idem |
| RF-SET-03 | `schema_migrations` | §8 |
| RNF-SEC-01 | Ausência deliberada de coluna de senha | Verificável por inspeção do schema |

---

## 5. Índice de busca (FTS5)

### 5.1 Por que manutenção explícita, sem gatilhos

Conforme ADR-005, o índice é mantido em Python, **dentro da mesma transação** que grava o corpo. Isso torna `store_body` o único ponto do sistema que escreve em `bodies` e em `messages_fts`, e é verificável por teste de rollback (CA-RF-SRCH-04-1).

### 5.2 Escrita do índice

```python
def store_body(self, message_rowid: int, raw: RawMessage,
               sanitized_html: str, text_plain: str) -> None:
    """Grava corpo e índice na MESMA transação (ADR-005, RF-SRCH-04)."""
    now = int(time.time())
    row = self._fetch_message_header_for_index(message_rowid)  # subject, from, recipients

    with self._write_transaction() as conn:          # BEGIN IMMEDIATE … COMMIT
        conn.execute(
            """
            INSERT INTO bodies (message_rowid, text_plain, html_sanitized,
                                sanitizer_version, size_bytes, fetched_at, last_access_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_rowid) DO UPDATE SET
                text_plain = excluded.text_plain,
                html_sanitized = excluded.html_sanitized,
                sanitizer_version = excluded.sanitizer_version,
                size_bytes = excluded.size_bytes,
                last_access_at = excluded.last_access_at
            """,
            (message_rowid, text_plain, sanitized_html, SANITIZER_VERSION,
             len(text_plain or "") + len(sanitized_html or ""), now, now),
        )
        # rowid explícito = messages.id: permite DELETE/UPDATE por rowid depois.
        conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (message_rowid,))
        conn.execute(
            """
            INSERT INTO messages_fts (rowid, subject, sender, recipients, body)
            VALUES (?, ?, ?, ?, ?)
            """,
            (message_rowid, row["subject"], row["from_name"] + " " + row["from_addr"],
             row["recipients"], text_plain or ""),
        )
        conn.execute(
            "UPDATE messages SET body_state = 'cached', body_fetched_at = ?,"
            " updated_at = ? WHERE id = ?",
            (now, now, message_rowid),
        )
```

### 5.3 Consulta segura — o usuário nunca escreve sintaxe FTS5

O `MATCH` do FTS5 tem sintaxe própria. Passar a entrada do usuário direto para ele produz erros de sintaxe (`"`, `AND`, `NEAR(`, `col:valor`) — e, pior, permite que uma consulta malformada derrube a busca com exceção (CA-RF-SRCH-05-1).

```python
def build_match_query(user_input: str) -> str | None:
    """Converte texto livre em consulta FTS5 segura, ou None se não houver termos.

    Cada termo vira uma frase entre aspas (aspas internas duplicadas), com
    prefixo no último termo para a busca enquanto se digita (RF-SRCH-02).
    Operadores do FTS5 digitados pelo usuário são tratados como texto literal.
    """
    terms = [t for t in re.split(r"\s+", user_input.strip()) if t]
    if not terms:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    return " ".join(quoted[:-1] + [quoted[-1] + "*"])
```

| Entrada do usuário | Consulta gerada | Resultado |
|---|---|---|
| `acao` | `"acao"*` | Encontra `Ação`, `ações`, `acao` |
| `nota fiscal` | `"nota" "fiscal"*` | Ambos os termos, o último por prefixo |
| `"` | `""""*` | Tratado como literal, sem erro |
| `NEAR(` | `"NEAR("*` | Tratado como literal, sem erro |
| `col:valor` | `"col:valor"*` | Tratado como literal, sem erro |
| `-excluir` | `"-excluir"*` | Tratado como literal, sem erro |
| `   ` | `None` | Busca vazia: lista normal, sem consulta |

### 5.4 Consulta de busca

```sql
-- Ordenação cronológica é a convenção de cliente de e-mail; bm25 fica como opção.
SELECT m.id, m.subject, m.from_name, m.from_addr, m.date_utc,
       m.is_read, m.has_attachments, f.display_name AS folder_name
FROM messages_fts
JOIN messages m ON m.id = messages_fts.rowid
JOIN folders  f ON f.id = m.folder_id
WHERE messages_fts MATCH :match
  AND (:account_id IS NULL OR m.account_id = :account_id)
  AND (:folder_id  IS NULL OR m.folder_id  = :folder_id)
  AND (:since      IS NULL OR m.date_utc  >= :since)
  AND (:unread_only = 0    OR m.is_read    = 0)
  AND (:with_attach = 0    OR m.has_attachments = 1)
  AND (:from_addr   IS NULL OR m.from_addr = :from_addr)
ORDER BY m.date_utc DESC
LIMIT :limit;
```

Para ordenar por relevância, troca-se o `ORDER BY` por `ORDER BY bm25(messages_fts, 2.0, 1.0, 0.5, 1.0)`, ponderando assunto acima de corpo. As duas ordenações são expostas na interface (RF-SRCH-03).

### 5.5 Consistência do índice

Verificação executável a qualquer momento, e usada no teste de CA-RF-SRCH-04-1:

```sql
-- Deve retornar 0 em operação normal.
SELECT
  (SELECT COUNT(*) FROM bodies b
   WHERE NOT EXISTS (SELECT 1 FROM messages_fts f WHERE f.rowid = b.message_rowid))
+ (SELECT COUNT(*) FROM messages_fts f
   WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.id = f.rowid))
AS inconsistencias;
```

---

## 6. Política de cache e despejo

### 6.1 O que ocupa espaço, com números

Premissa: 5.000 mensagens, corpo de texto plano médio de 2 KB, HTML sanitizado médio de 8 KB.

| Estrutura | Tamanho estimado | Natureza |
|---|---|---|
| `messages` (5.000 cabeçalhos) | ≈ 2,5 MB | Pequeno; **nunca despejado** |
| `bodies.text_plain` | ≈ 10 MB | Médio |
| `messages_fts` (texto + índice invertido) | ≈ 12–15 MB | Médio; a busca depende dele |
| `bodies.html_sanitized` | ≈ 40 MB | **Grande**; alvo principal do despejo |
| `attachments` (metadados apenas) | < 1 MB | Irrelevante |

Isto fundamenta CA-RF-MSG-01-2: a sincronização inicial de 5.000 cabeçalhos fica bem abaixo de 5 MB.

### 6.2 Por que o índice NÃO é despejado junto com o corpo

O FTS5 comum armazena sua própria cópia do texto indexado. Isso poderia parecer desperdício, mas é justamente o que permite uma propriedade valiosa: **despejar o corpo em cache sem quebrar a busca**. O usuário continua encontrando a mensagem; apenas o texto não é exibido instantaneamente até ser rebuscado no servidor. Se o índice fosse apagado junto, a busca passaria a mentir por omissão — resultado muito pior que gastar 12 MB com o índice.

### 6.3 Por que o HTML original não é armazenado

Não há coluna para o HTML cru. Guardá-lo dobraria o armazenamento para atender um caso raro: re-sanitizar quando a versão do sanitizador muda. A política adotada é registrar `bodies.sanitizer_version` e, quando `SANITIZER_VERSION` aumentar, marcar os corpos afetados como `body_state = 'headers'` para rebuscar sob demanda. Os links originais não se perdem nesse processo, porque a reescrita de recursos remotos preserva a URL em atributos `data-*` dentro do HTML sanitizado (`05-seguranca-privacidade.md` §4).

### 6.4 Despejo em dois níveis

```python
def evict_bodies_lru(self, target_bytes: int) -> int:
    """Reduz o cache até ficar abaixo de target_bytes. Nunca toca em cabeçalhos,
    nunca remove linhas de messages_fts, nunca toca em outbox ou rascunhos."""

    # Nível 1 — o HTML sanitizado é o campo grande e o mais barato de rebuscar.
    # Zera html_sanitized e marca 'evicted'; texto plano e índice permanecem.
    # Nível 2 — só sob pressão severa: apaga a linha de bodies inteira
    # (inclusive text_plain). A entrada do FTS5 PERMANECE, para que a busca
    # continue encontrando a mensagem.
    ...
```

| Nível | O que é liberado | O que se preserva | Impacto para o usuário |
|---|---|---|---|
| 1 | `bodies.html_sanitized` | `text_plain`, índice FTS5, cabeçalhos | Abre a mensagem, rebusca o HTML (~1 s); busca intacta |
| 2 | Linha de `bodies` inteira | Índice FTS5, cabeçalhos | Encontra na busca, mas precisa rebuscar para ler; busca intacta |

Limite padrão: 500 MB, configurável (RF-MSG-06, RF-SET-02). O despejo roda no `TaskPool`, nunca na thread da GUI, e é acionado após a gravação de um corpo que faça o total ultrapassar o limite.

---

## 7. Reservas para a fase 2, já na migração v1

Quatro decisões evitam migrações destrutivas depois:

1. **`messages.snoozed_until`** — o Snooze (RF-ORG-07) vira consulta e temporizador, sem alterar o schema.
2. **`messages.thread_id`** — o agrupamento em conversas (RF-RD-10) vira preenchimento de coluna.
3. **`accounts.protocol`** aceita `'pop3'` desde já — o POP3 (RF-ACC-07) entra sem migração.
4. **`accounts.auth_type`** aceita `'oauth2'` desde já — idem para RF-ACC-06.

Custo hoje: quatro colunas e um `CHECK` mais permissivo. Custo evitado: quatro migrações de tabela grande, cada uma com risco de perda de dados.

---

## 8. Migrações e recuperação

### 8.1 Mecanismo

`schema_migrations` é a autoridade sobre a versão, e a versão corrente é `MAX(version)` (a v1 termina em 1). Cada migração é uma função que recebe a conexão e roda **dentro de uma única transação** — o SQLite torna DDL transacional, o que faz uma migração falha reverter por completo em vez de deixar o banco pela metade.

```python
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_001_initial}

def migrate(self) -> int:
    current = self._current_version()
    newest = max(MIGRATIONS)
    if current > newest:
        # Banco de uma versão mais nova do aplicativo: recusar, jamais adivinhar.
        raise StorageError(
            f"Banco na versão {current}, aplicativo suporta até {newest}. "
            "Atualize o PyMail Client."
        )
    for version in range(current + 1, newest + 1):
        with self._write_transaction() as conn:
            MIGRATIONS[version](conn)
            conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                         (version, int(time.time())))
    return newest
```

Duas regras obrigatórias:

- **Antes de qualquer migração que reconstrua tabela** (padrão `CREATE new` → `INSERT SELECT` → `DROP old` → `RENAME`), `PRAGMA foreign_keys` deve ser desligado e religado ao final. Com a checagem ativa, o `DROP` dispara os `CASCADE` e apaga dados do usuário — um modo de falha silencioso e devastador.
- **Nunca aplicar migração sem `integrity_check` prévio.** Migrar um banco já corrompido propaga a corrupção.

### 8.2 Recuperação de banco corrompido (RF-SET-05)

Ordem obrigatória, porque a prioridade é o dado do usuário:

1. Na inicialização, `PRAGMA quick_check` (mais rápido que `integrity_check`; completo apenas sob suspeita).
2. Se falhar, **antes de qualquer reparo**, tentar exportar `outbox` e os rascunhos para um arquivo `outbox-recuperado-<timestamp>.json` no diretório de dados. Se a leitura também falhar, registrar o fato no log e informar o usuário — não fingir sucesso.
3. Renomear o banco e os arquivos `-wal`/`-shm` para `pymail.db.corrompido-<timestamp>` em vez de apagar. Nunca destruir a evidência.
4. Criar um banco novo, aplicar as migrações e ressincronizar a partir do servidor — o cache é descartável por definição (RNF-REL-02).
5. Notificar o usuário em linguagem clara: o que aconteceu, onde está o arquivo exportado e que a sincronização vai reconstruir o restante.

### 8.3 Testes obrigatórios

- Migração de um banco vazio até a versão corrente, em uma transação.
- Abrir banco em versão superior → `StorageError` com mensagem clara, sem escrita alguma (CA-RF-SET-03-1).
- Migração que falha no meio deixa o banco exatamente na versão anterior, íntegro.
- `quick_check` em banco truncado retorna falha e dispara o caminho de §8.2 (CA-RF-SET-05-1).
- Reconstrução de tabela com dados preserva as contagens de linhas antes e depois.

---

## 9. Consultas de referência

As consultas abaixo são normativas: definem o comportamento esperado da lista, dos contadores e do despejo.

```sql
-- Página da lista de mensagens de uma pasta (RF-UI-05: paginação para virtualização)
SELECT m.id, m.remote_id, m.subject, m.from_name, m.from_addr, m.date_utc,
       m.is_read, m.is_flagged, m.has_attachments, m.body_state
FROM messages m
WHERE m.folder_id = :folder_id
  AND (:snooze_cutoff IS NULL
       OR m.snoozed_until IS NULL
       OR m.snoozed_until <= :now)          -- [F2] snooze esconde da caixa de entrada
ORDER BY m.date_utc DESC
LIMIT :limit OFFSET :offset;

-- Contadores por pasta, para a barra lateral (RF-UI-10)
SELECT f.id, f.display_name, f.kind,
       COUNT(m.id)                                        AS total,
       SUM(CASE WHEN m.is_read = 0 THEN 1 ELSE 0 END)     AS nao_lidos
FROM folders f
LEFT JOIN messages m ON m.folder_id = f.id
WHERE f.account_id = :account_id
GROUP BY f.id;

-- Mensagens vencidas da fila de envio (RF-SND-03), executada a cada segundo
SELECT id, account_id, message_id, to_addrs, subject, attempts
FROM outbox
WHERE state = 'queued' AND send_at <= :now
ORDER BY send_at;

-- Candidatos à pré-busca, mais recentes primeiro (RF-MSG-03)
SELECT id, remote_id FROM messages
WHERE folder_id = :folder_id AND body_state = 'headers'
ORDER BY date_utc DESC
LIMIT :n;

-- Total ocupado pelo cache de corpos, para decidir o despejo (RF-MSG-06)
SELECT COALESCE(SUM(size_bytes), 0) FROM bodies;

-- Vítimas do despejo de nível 1, menos usadas recentemente primeiro
SELECT message_rowid, size_bytes FROM bodies
WHERE html_sanitized IS NOT NULL
ORDER BY last_access_at ASC
LIMIT :n;
```
