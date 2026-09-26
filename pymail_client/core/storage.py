"""Fachada de armazenamento SQLite (02-arquitetura.md §5.4, ADR-006).

* Conexão por thread via `threading.local()` — `sqlite3.Connection` não é
  seguro entre threads.
* PRAGMAs aplicados em **toda** conexão, na ordem de `03-modelo-de-dados.md` §2.
* Migrações transacionais: o SQLite torna DDL transacional, e um rollback
  reverte tudo (§8.1).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path

from pymail_client.core.errors import StorageError
from pymail_client.core.models import (
    AccountConfig,
    AttachmentMeta,
    Draft,
    FolderRecord,
    FolderStatus,
    HeaderEnvelope,
    MessageFilters,
    MessageRow,
    OutgoingRow,
    RawMessage,
    RemoteFolder,
)

__all__ = ["SCHEMA_VERSION", "MIGRATIONS", "Storage"]

#: Versão corrente do schema (03-modelo-de-dados.md §8.1).
SCHEMA_VERSION: int = 1

#: PRAGMAs aplicados em toda conexão, na ordem exata de 03-modelo-de-dados.md §2.
_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 5000;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA cache_size = -8000;",
)

#: DDL literal e normativo de 03-modelo-de-dados.md §3.
_DDL_V1: str = """
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
"""


def _migrate_001_initial(conn: sqlite3.Connection) -> None:
    """Migration 001: schema inicial. DDL literal de 03-modelo-de-dados.md §3.

    Executa cada declaração individualmente (não `executescript`) porque
    `executescript` cometeria a transição atual, quebrando o rollback
    transacional exigido por §8.1. Como DDL é transacional no SQLite, cada
    `execute()` individual fica dentro da transação iniciada pelo caller.
    """
    for stmt in _DDL_V1.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


#: Tabela de migrações: versão → função (03-modelo-de-dados.md §8.1).
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_001_initial,
}


class Storage:
    """Fachada de armazenamento SQLite.

    Uma conexão por thread (`threading.local`), PRAGMAs fixos em toda conexão,
    e migrações transacionais. Veja o contrato completo em `02-arquitetura.md`
    §5.4.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        connection_hook: Callable[[sqlite3.Connection], None] | None = None,
    ) -> None:
        """Abre (preguiçosamente) o banco em `db_path`.

        `connection_hook` é API EXCLUSIVA DE TESTE (02-arquitetura.md §5.4, C7):
        recebe cada conexão recém-aberta, **antes** dos PRAGMAs, para que testes
        de atomicidade instalem `sqlite3.Connection.set_authorizer` ou façam
        asserções sobre a conexão. Em produção é sempre `None`.
        """
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._connection_hook = connection_hook

    # ── Conexão por thread ──────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Conexão da thread atual, criada sob demanda com os PRAGMAs de §2.

        `foreign_keys` é por conexão — aplicar em **toda** conexão, não apenas
        na primeira, é o que faz `ON DELETE CASCADE` realmente funcionar
        (03-modelo-de-dados.md §2, CA-RF-ACC-05-1).
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path))
            if self._connection_hook is not None:
                self._connection_hook(conn)
            for pragma in _PRAGMAS:
                conn.execute(pragma)
            self._local.conn = conn
        return conn

    def close_thread_connection(self) -> None:
        """Encerra e limpa a conexão da thread atual."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            del self._local.conn

    # ── Transações ──────────────────────────────────────────────────────

    @contextmanager
    def _write_transaction(self):
        """Transação de escrita curta (ADR-006, 03-modelo-de-dados.md §2).

        `BEGIN IMMEDIATE` adquire um *reserved lock* na abertura: se outro
        escritor estiver ativo, a conexão espera pelo `busy_timeout` de 5 s
        antes de levantar `SQLITE_BUSY`, em vez de falhar no primeiro `INSERT`.
        Commit/rollback explícitos garantem que DDL e DML rollam juntos.
        """
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── Leitura de metadados ────────────────────────────────────────────

    def _current_version(self) -> int:
        """Versão atual do banco (0 se nunca migrado)."""
        conn = self._conn()
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return row[0] if row[0] is not None else 0
        except sqlite3.OperationalError:
            # Tabela não existe → banco nunca foi migrado.
            return 0

    def integrity_check(self) -> bool:
        """`PRAGMA integrity_check` — True quando o banco está íntegro."""
        conn = self._conn()
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return row is not None and row[0] == "ok"

    # ── Migrações ───────────────────────────────────────────────────────

    def migrate(self) -> int:
        """Executa migrações até a versão corrente, retornando-a.

        Implementa 03-modelo-de-dados.md §8.1. É idempotente: chamar duas
        vezes não altera nada. Versão do banco superior à suportada é
        recusada com `StorageError` — nunca adivinhamos para cima (CA-RF-SET-03-1).
        """
        current = self._current_version()
        newest = max(MIGRATIONS)
        if current > newest:
            raise StorageError(
                f"Banco na versão {current}, aplicativo suporta até {newest}. "
                "Atualize o PyMail Client."
            )
        for version in range(current + 1, newest + 1):
            with self._write_transaction() as conn:
                MIGRATIONS[version](conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, int(time.time())),
                )
        return newest

    # ── Stubs do contrato (implementados em T-03 em diante) ─────────────

    def upsert_account(self, account: AccountConfig) -> int: ...
    def list_accounts(self) -> Sequence[AccountConfig]: ...
    def delete_account(self, account_id: int) -> None: ...
    def upsert_folder(self, account_id: int, folder: RemoteFolder, status: FolderStatus) -> int: ...
    def list_folders(self, account_id: int) -> Sequence[FolderRecord]: ...
    def insert_headers(
        self, account_id: int, folder_id: int, envelopes: Sequence[HeaderEnvelope]
    ) -> int: ...
    def store_body(
        self, message_rowid: int, raw: RawMessage, sanitized_html: str, text_plain: str
    ) -> None: ...
    def last_known_uid(self, folder_id: int) -> int: ...
    def invalidate_folder(self, folder_id: int) -> None: ...
    def list_messages(
        self, folder_id: int, *, offset: int, limit: int, filters: MessageFilters | None = None
    ) -> Sequence[MessageRow]: ...
    def search(
        self, query: str, filters: MessageFilters | None = None, limit: int = 200
    ) -> Sequence[MessageRow]: ...
    def store_attachment_meta(
        self, message_rowid: int, metas: Sequence[AttachmentMeta]
    ) -> None: ...
    def is_sender_allowed(self, account_id: int, from_addr: str) -> bool: ...
    def allow_sender_images(self, account_id: int, from_addr: str) -> None: ...
    def enqueue_outgoing(self, draft: Draft) -> int: ...
    def due_outgoing(self, now: float) -> Sequence[OutgoingRow]: ...
    def mark_outgoing(self, outbox_id: int, state: str, error: str | None = None) -> None: ...
    def evict_bodies_lru(self, target_bytes: int) -> int: ...
