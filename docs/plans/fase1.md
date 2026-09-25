# PyMail Client — Plano de Implementação da Fase 1

> **Para quem for executar:** SKILL OBRIGATÓRIA: use `executing-plans` para implementar este plano tarefa por tarefa. Em cada tarefa, use `test-driven-development` e siga a skill `verification-before-completion` antes de afirmar que algo está pronto. Para executar com subagentes independentes, use `subagent-driven-development`.

**Objetivo:** entregar um cliente de e-mail desktop utilizável no fim da fase 1 — contas IMAP múltiplas, listagem por cabeçalhos, leitura sanitizada com rastreamento bloqueado, busca local instantânea e envio SMTP com Undo Send — sobre a arquitetura e o modelo de dados já especificados.

**Arquitetura:** bibliotecas síncronas da biblioteca padrão (`imaplib`/`smtplib`) com **uma thread dedicada e uma conexão por conta** (ADR-001), um `QThreadPool` para trabalho sem estado compartilhado, SQLite com WAL e uma conexão por thread (ADR-006), e renderização em `QWebEngineView` com JavaScript desabilitado mais um interceptor de rede (ADR-003). A interface conversa com o núcleo apenas por sinais Qt e apenas através dos contratos de `core/network/base.py`, `core/auth.py` e da fachada `Storage`.

**Tech Stack:** Python 3.11+, PySide6 (Essentials + Addons), `nh3`, `tinycss2`, `keyring`, `sqlite3` com FTS5, `pytest` + `pytest-qt`, `ruff`.

**Documentos de origem (leia antes de começar):** `docs/spec/01-requisitos.md`, `docs/spec/02-arquitetura.md`, `docs/spec/03-modelo-de-dados.md`, `docs/spec/04-ui-ux.md`, `docs/spec/05-seguranca-privacidade.md`, `docs/spec/06-estrategia-de-testes.md`.

---

## Como usar este plano

- Cada tarefa é **uma unidade de trabalho verificável**, com caminhos de arquivo exatos, o teste que deve falhar primeiro e o comando que comprova o resultado.
- A ordem importa. Tarefas de `M0` a `M2` constroem a fundação; a partir de `M3` há paralelismo possível, indicado em cada tarefa.
- **Marcos (M):** `M0` fundação · `M1` persistência e busca · `M2` rede e sincronização · `M3` leitura e privacidade · `M4` organização e envio · `M5` interface completa · `M6` robustez e entrega.
- **Regra de ouro:** nenhuma tarefa é considerada concluída sem o teste especificado passando. Se o teste não pode ser escrito, o requisito está mal definido — volte à spec em vez de improvisar.
- Convenção de idioma: **código, identificadores, nomes de arquivo e mensagens de commit em inglês**; documentação e comentários de explicação em português.

### Preparação do ambiente (uma vez)

```powershell
cd E:\DEV-NOVO\mail-project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

O `pyproject.toml` é criado na tarefa `T-01`. Até lá, nenhuma dependência do projeto deve ser instalada.

### Verificação rápida ao fim de cada tarefa

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

---

## M0 — Fundação

### T-01 — Esqueleto do projeto, configuração e dependências

**Arquivos:**
- Criar: `pyproject.toml`
- Criar: `pymail_client/__init__.py`
- Criar: `pymail_client/config.py`
- Criar: `tests/__init__.py`, `tests/conftest.py`
- Criar: `pymail_client/core/__init__.py`, `pymail_client/ui/__init__.py`
- Requisitos: RF-SET-01, RF-SET-02, RNF-COMP-02, RNF-MAINT-02

**Passo 1 — escrever o teste que falha**

`tests/test_config.py`:

```python
from pathlib import Path
import pytest
from pymail_client.config import AppConfig, load_config, save_config


def test_defaults_match_spec(tmp_path: Path) -> None:
    cfg = AppConfig()
    assert cfg.undo_send_delay_s == 10          # RF-SET-02
    assert cfg.poll_interval_s == 60            # RF-MSG-05
    assert cfg.body_cache_limit_bytes == 500 * 1024 * 1024   # RF-MSG-06
    assert cfg.mark_read_delay_ms == 1500       # RF-RD-09
    assert cfg.search_debounce_ms == 250        # RF-SRCH-02
    assert cfg.use_idle is True                 # RF-SET-02
    assert cfg.theme == "system"                # RF-UI-06


@pytest.mark.parametrize("value", [4, 31, 0, -5])
def test_undo_delay_out_of_range_rejected(value: int) -> None:
    """RF-SND-03: a janela é configurável entre 5 e 30 segundos."""
    with pytest.raises(ValueError):
        AppConfig(undo_send_delay_s=value)


def test_roundtrip_preserves_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_config(AppConfig(undo_send_delay_s=20), path)
    assert load_config(path).undo_send_delay_s == 20


def test_missing_file_yields_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nao-existe.toml") == AppConfig()
```

**Passo 2 — rodar e verificar que falha**

```powershell
python -m pytest tests/test_config.py -v
```

Esperado: `ModuleNotFoundError: No module named 'pymail_client'`.

**Passo 3 — implementar**

`pyproject.toml` (trecho essencial; complete com metadados do pacote):

```toml
[project]
name = "pymail-client"
requires-python = ">=3.11"
dependencies = [
    "PySide6>=6.6",
    "nh3>=0.2",
    "tinycss2>=1.2",
    "keyring>=24",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-qt>=4.4", "pytest-cov>=5", "pytest-timeout>=2.3", "ruff>=0.6", "mypy>=1.11"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: requer servidor real (Docker); pulado quando indisponível",
    "slow: execução longa; excluído do ciclo curto",
]
```

`pymail_client/config.py` — `AppConfig` é uma dataclass congelada com `to_toml`/`from_toml`, validação em `__post_init__` (faixa de 5 a 30 s para `undo_send_delay_s`, conforme RF-SND-03), e caminhos resolvidos com `QStandardPaths` conforme `02-arquitetura.md` §8.1. `load_config` devolve os padrões se o arquivo não existir ou estiver ilegível, sem lançar exceção.

**Passo 4 — rodar e verificar que passa**

```powershell
python -m pytest tests/test_config.py -v
```

Esperado: 7 passed.

**Passo 5 — commit**

```powershell
git add pyproject.toml pymail_client/ tests/
git commit -m "feat(config): project skeleton, AppConfig with validated defaults"
```

---

### T-02 — Schema do banco, PRAGMAs e migrações

**Arquivos:**
- Criar: `pymail_client/core/errors.py`
- Criar: `pymail_client/core/models.py`
- Criar: `pymail_client/core/storage.py`
- Criar: `tests/test_storage_migrations.py`
- Criar: `scripts/make_golden_db.py`, `tests/fixtures/db/v1_golden.db` (banco de referência da versão 1, **versionado em git**, usado para provar que uma migração preserva dados reais e não apenas um banco recém-criado — ver `06-estrategia-de-testes.md`)
- Requisitos: RF-SET-03, RF-ACC-02, RNF-SEC-05 · CA-RF-SET-03-1

**Passo 1 — escrever o teste que falha**

`tests/test_storage_migrations.py`:

```python
import sqlite3
from pathlib import Path
import pytest
from pymail_client.core.errors import StorageError
from pymail_client.core.storage import Storage, SCHEMA_VERSION


def test_fresh_database_migrates_to_current_version(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "pymail.db")
    assert storage.migrate() == SCHEMA_VERSION
    assert storage.migrate() == SCHEMA_VERSION       # idempotente


def test_foreign_keys_are_enabled_per_connection(tmp_path: Path) -> None:
    """Sem isso, ON DELETE CASCADE vira decoração e CA-RF-ACC-05-1 falha."""
    storage = Storage(tmp_path / "pymail.db")
    storage.migrate()
    assert storage._conn().execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert storage._conn().execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_newer_database_version_is_refused_without_writing(tmp_path: Path) -> None:
    """CA-RF-SET-03-1: recusar é obrigatório; adivinhar corrompe dados."""
    path = tmp_path / "pymail.db"
    storage = Storage(path)
    storage.migrate()
    storage._conn().execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION + 5, 0),
    )
    storage._conn().commit()
    storage.close_thread_connection()

    with pytest.raises(StorageError, match="versão"):
        Storage(path).migrate()


def test_failed_migration_rolls_back_entirely(tmp_path: Path, monkeypatch) -> None:
    """Migration é transacional: falha no meio deixa a versão anterior intacta."""
    path = tmp_path / "pymail.db"
    Storage(path).migrate()
    ...
```

**Passo 2 — rodar e verificar que falha**

```powershell
python -m pytest tests/test_storage_migrations.py -v
```

Esperado: falha por `ModuleNotFoundError: pymail_client.core.storage`.

**Passo 3 — implementar**

`core/storage.py` contém o DDL **literal** de `03-modelo-de-dados.md` §3 na migração `_migrate_001_initial`, o runner `migrate()` de §8.1, e um `_conn()` que abre a conexão por thread (`threading.local()`) aplicando os PRAGMAs de §2 na ordem exata ali listada. `core/errors.py` define a taxonomia de `02-arquitetura.md` §7. `core/models.py` define as dataclasses **congeladas** do domínio (elas atravessam sinais entre threads; mutabilidade aqui é bug).

Restrições que a implementação deve respeitar:
- `PRAGMA foreign_keys = ON` em **toda** conexão, não apenas na primeira.
- `PRAGMA busy_timeout = 5000`.
- Migração que reconstrua tabela deve desligar `foreign_keys` antes e religar depois, senão o `DROP` dispara `CASCADE` e apaga dados do usuário.

**Passo 4 — rodar e verificar que passa**

```powershell
python -m pytest tests/test_storage_migrations.py -v
python -m pytest tests/test_storage_migrations.py::test_newer_database_version_is_refused_without_writing -v
```

Esperado: todos passam; o segundo comprova CA-RF-SET-03-1.

**Passo 5 — commit**

```powershell
git add pymail_client/core/ tests/test_storage_migrations.py
git commit -m "feat(storage): schema v1, per-thread connections, transactional migrations"
```

---

### T-03 — Provedor de autenticação e credenciais no keyring

**Arquivos:**
- Criar: `pymail_client/core/auth.py`
- Criar: `pymail_client/core/security.py` (parte de keyring)
- Criar: `tests/fakes/fake_keyring.py`
- Criar: `tests/test_auth.py`
- Requisitos: RF-ACC-01, RF-ACC-04, RNF-SEC-01 · CA-RF-ACC-04-1, CA-RNF-SEC-01-1

**Passo 1 — escrever o teste que falha**

`tests/test_auth.py`:

```python
from pathlib import Path
import pytest
from pymail_client.core.auth import (AuthProvider, PasswordAuth, get_provider,
                                     register_provider, AccountConfig)
from pymail_client.core.security import get_credential, set_credential, delete_credential


def test_credential_never_reaches_database_or_config(tmp_path: Path, fake_keyring) -> None:
    """CA-RNF-SEC-01-1: a senha não existe em banco, config nem log."""
    from pymail_client.core.storage import Storage

    secret = "senha-super-secreta-42"
    storage = Storage(tmp_path / "pymail.db")
    storage.migrate()
    account_id = storage.upsert_account(AccountConfig(email="a@exemplo.com", ...))
    set_credential("a@exemplo.com", secret)

    raw = (tmp_path / "pymail.db").read_bytes()
    assert secret.encode() not in raw
    for path in tmp_path.rglob("*.toml"):
        assert secret not in path.read_text(encoding="utf-8")


def test_register_provider_needs_no_ui_or_storage_change() -> None:
    """CA-RF-ACC-04-1: é esta indireção que torna a fase 2 aditiva."""

    class FakeOAuthProvider(AuthProvider):
        name = "oauth2-fake"

        def authenticate(self, account, *, interactive: bool):
            return AuthResult(username=account.username, secret=None,
                              access_token="tok", expires_at=None)

        def can_renew_silently(self) -> bool:
            return True

        def invalidate(self) -> None:
            ...

    register_provider(FakeOAuthProvider)
    assert isinstance(get_provider("oauth2-fake"), FakeOAuthProvider)


def test_password_auth_reads_only_from_keyring(...) -> None: ...


def test_account_deletion_removes_credential(...) -> None:
    """CA-RF-ACC-05-1 (parte de credencial)."""
```

**Passo 2 — rodar e verificar que falha**

```powershell
python -m pytest tests/test_auth.py -v
```

Esperado: falha por módulo inexistente.

**Passo 3 — implementar**

`core/auth.py` segue **literalmente** o contrato de `02-arquitetura.md` §5.2: `AuthResult`, `AuthProvider` (ABC), `PasswordAuth`, `register_provider`, `get_provider`. `core/security.py` implementa `set_credential`/`get_credential`/`delete_credential` sobre `keyring` com `service="pymail-client"` e `username=<email>` (chave definida em `03-modelo-de-dados.md` §3).

Comportamento obrigatório quando o keyring do sistema está indisponível (`keyring.errors.NoKeyringError`): **nunca** cair para arquivo em texto claro. Oferecer credencial apenas em memória pela sessão, com aviso explícito ao usuário, conforme `05-seguranca-privacidade.md` §2.

**Passo 4 — rodar e verificar que passa**

```powershell
python -m pytest tests/test_auth.py -v
```

**Passo 5 — commit**

```powershell
git add pymail_client/core/auth.py pymail_client/core/security.py tests/
git commit -m "feat(auth): pluggable AuthProvider and keyring-only credential storage"
```

---

### T-04 — Teste de conexão e verificação de TLS ao cadastrar conta

**Arquivos:**
- Criar: `pymail_client/core/network/base.py`
- Criar: `pymail_client/core/network/imap_client.py` (somente `connect`/`close` por enquanto)
- Criar: `tests/fakes/imap_server.py`
- Criar: `tests/test_imap_connect.py`
- Requisitos: RF-ACC-03, RNF-SEC-02 · CA-RF-ACC-03-1, CA-RNF-SEC-02-1

**Passo 1 — escrever o teste que falha**

```python
def test_error_kinds_are_distinguished(imap_server_factory) -> None:
    """CA-RF-ACC-03-1: DNS, recusa de conexão e credencial inválida são distintos."""
    with pytest.raises(NetworkError, match="resolver"):
        ImapClient(host="host-que-nao-existe.invalid", ...).connect()

    server = imap_server_factory(refuse_login=True)
    with pytest.raises(AuthError):
        ImapClient(host="127.0.0.1", port=server.port, ...).connect()


def test_self_signed_certificate_is_a_hard_failure(tls_server_selfsigned) -> None:
    """CA-RNF-SEC-02-1: nunca degradar para texto claro em silêncio."""
    with pytest.raises(TLSError):
        ImapClient(host="127.0.0.1", port=tls_server_selfsigned.port, ...).connect()


def test_plaintext_connection_is_refused_by_default(...) -> None:
    with pytest.raises(TLSError):
        ImapClient(host="127.0.0.1", port=plain_server.port,
                   security="none", allow_insecure=False).connect()
```

**Passo 2 — rodar e verificar que falha**

```powershell
python -m pytest tests/test_imap_connect.py -v
```

**Passo 3 — implementar**

`core/network/base.py` recebe o protocolo `IncomingMailClient` **na íntegra**, exatamente como em `02-arquitetura.md` §5.1, junto com `RemoteFolder`, `FolderStatus`, `HeaderEnvelope`, `RawMessage`, `AttachmentMeta`. Comece pelo protocolo completo mesmo que a implementação chegue por partes: é o contrato que a fase 2 herda.

`tests/fakes/imap_server.py` implementa um servidor `ThreadingTCPServer` que fala o subconjunto necessário de IMAP e **registra todos os comandos recebidos** em `server.commands`. Esse registro é o que torna verificáveis T-10, T-11, T-17 e T-28 — construa-o com cuidado, expondo `server.commands` como lista de tuplas `(tag, verb, args)`. Ele precisa suportar: `CAPABILITY` (configurável, para testar ausência de `MOVE` e de `IDLE`), `LOGIN` (com recusa configurável), `LIST`, `SELECT`, `UID FETCH`, `UID STORE`, `UID SEARCH`, `NOOP`, `LOGOUT`.

`ImapClient.connect()` deve converter falhas em `NetworkError`, `AuthError` ou `TLSError` de `core/errors.py`, nunca vazar `socket.gaierror` ou `imaplib.IMAP4.error` para a interface (ver `02-arquitetura.md` §7).

**Passo 4 — rodar e verificar que passa**

```powershell
python -m pytest tests/test_imap_connect.py -v
```

**Passo 5 — commit**

```powershell
git add pymail_client/core/network/ tests/fakes/ tests/test_imap_connect.py
git commit -m "feat(imap): connection with typed errors and hard TLS validation"
```

---

## M1 — Persistência e busca

### T-05 — Sanitização de HTML e regras de privacidade

Esta é a tarefa mais importante do projeto: é a proposta de valor do produto. Faça-a com calma.

**Arquivos:**
- Criar: `pymail_client/core/security.py` (parte de sanitização)
- Criar: `tests/test_security_sanitize.py`
- Criar: `tests/fixtures/eml/malicious/*.eml`
- Requisitos: RF-RD-01, RF-RD-04, RF-RD-05, RNF-SEC-03, RNF-PRIV-03 · CA-RF-RD-01-1, CA-RF-RD-04-1

**Passo 1 — confirmar as dependências antes de escrever código que dependa delas**

```powershell
python -m pip install nh3 tinycss2
python -c "import nh3, tinycss2; print(nh3.clean('<b>x</b><script>bad()</script>', tags={'b'}))"
```

Esperado: instalação sem compilação (há *wheels* para Windows/Linux/macOS) e impressão de `<b>x</b>`.

**Se isto falhar em alguma plataforma alvo, pare e volte à spec** (ADR-004 registra a alternativa: `bleach` congelado). Não prossiga com uma dependência que não instala.

**Passo 2 — criar o corpus hostil primeiro**

Uma fixture por caso, em `tests/fixtures/eml/malicious/`, cada uma contendo exatamente o ataque do nome do arquivo: `script_inline.eml`, `javascript_href.eml`, `onerror_img.eml`, `iframe.eml`, `object_embed.eml`, `form_phishing.eml`, `css_expression.eml`, `css_remote_import.eml`, `base_href_hijack.eml`, `tracking_pixel_1x1.eml`, `tracking_pixel_css_hidden.eml`, `remote_images_20.eml`, `link_text_mismatch.eml`, `tracking_params.eml`, `malformed_html.eml`.

Estas fixtures são versionadas e escritas à mão, com cuidado. Elas não podem ser "inventadas na hora" dentro do teste — é o corpus que evolui junto com o sanitizador.

**Passo 3 — escrever o teste que falha**

`tests/test_security_sanitize.py`:

```python
import pytest
from pymail_client.core.security import (SANITIZER_VERSION, sanitize_html,
                                         restore_remote_resources)

FORBIDDEN = ["<script", "<iframe", "<object", "<embed", "<form",
             "javascript:", "onerror=", "onload=", "expression("]


@pytest.mark.parametrize("name", [
    "script_inline", "javascript_href", "onerror_img", "iframe",
    "object_embed", "form_phishing", "css_expression", "css_remote_import",
    "base_href_hijack",
])
def test_forbidden_constructs_never_survive(name: str, load_eml) -> None:
    """CA-RF-RD-01-1: o teste falha se QUALQUER construção proibida sobreviver."""
    result = sanitize_html(load_eml(name).html)
    lowered = result.lower()
    for token in FORBIDDEN:
        assert token not in lowered, f"{token!r} sobreviveu em {name}"


def test_tracking_pixel_is_removed_irreversibly(load_eml) -> None:
    """CA-RF-RD-04-1: nem depois de autorizar imagens do remetente."""
    sanitized = sanitize_html(load_eml("tracking_pixel_1x1").html)
    assert "data-pymail-src" not in sanitized or "pixel" not in sanitized.lower()
    restored = restore_remote_resources(sanitized)
    assert "rastreador.example.com" not in restored


def test_remote_images_are_rewritten_and_not_restored_without_consent(load_eml) -> None:
    """RF-RD-03: sem consentimento, nenhum src remoto existe no HTML."""
    sanitized = sanitize_html(load_eml("remote_images_20").html)
    assert 'src="http' not in sanitized
    assert sanitized.count("data-pymail-src") >= 20

    restored = restore_remote_resources(sanitized)
    assert restored.count('src="http') >= 20


def test_csp_meta_is_injected(load_eml) -> None:
    result = sanitize_html(load_eml("script_inline").html)
    assert "Content-Security-Policy" in result


def test_tracking_params_are_stripped_from_links(load_eml) -> None:
    result = sanitize_html(load_eml("tracking_params").html)
    for param in ("utm_source", "utm_campaign", "fbclid", "gclid", "mc_eid"):
        assert param not in result


def test_malformed_html_never_raises_and_never_falls_back_to_raw(load_eml) -> None:
    """Fail-safe: se a reescrita falhar, o chamador recebe texto plano, nunca HTML cru."""
    ...
```

**Passo 4 — rodar e verificar que falha**

```powershell
python -m pytest tests/test_security_sanitize.py -v
```

Esperado: falha por `ImportError: cannot import name 'sanitize_html'`.

**Passo 5 — implementar o pipeline na ordem exata**

A ordem é normativa (`05-seguranca-privacidade.md` §4). Uma ordem errada reintroduz conteúdo removido.

```python
def sanitize_html(raw_html: str) -> str:
    """Pipeline de sanitização. Ordem normativa — não reordene sem atualizar a spec."""
    try:
        # 1. Reescrita de privacidade (parser HTML real, nunca regex):
        #    a) remove pixels de rastreamento IRREVERSIVELMENTE
        #    b) move src/srcset/background remotos para data-pymail-src
        #    c) limpa parâmetros de rastreamento de <a href>
        #    d) filtra o atributo style por allowlist de propriedades CSS (tinycss2)
        rewritten = _rewrite_privacy(raw_html)
    except Exception:
        # Fail-safe (05-seguranca-privacidade.md §4): nunca renderizar HTML cru.
        return ""

    # 2. Allowlist estrutural (nh3): remove script/iframe/object/embed/form/on*/javascript:
    cleaned = nh3.clean(
        rewritten,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )

    # 3. Defesa em profundidade: CSP restritiva injetada no documento final.
    return _inject_csp(cleaned)


def restore_remote_resources(sanitized_html: str) -> str:
    """Reaplica as URLs originais preservadas em data-pymail-src (RF-RD-03).

    Não ressuscita pixels de rastreamento: eles foram removidos por completo
    no passo 1a, não guardados em atributo nenhum.
    """
    ...
```

`_rewrite_privacy` usa uma subclasse de `html.parser.HTMLParser` que reconstrói a saída, com `handle_starttag`, `handle_startendtag` e `handle_endtag`. Ela precisa: descartar o elemento inteiro quando for pixel de rastreamento (heurísticas em `05-seguranca-privacidade.md` §5), reescrever `src`/`srcset`/`background` para `data-pymail-src`, e limpar a query de `a href`.

**Passo 6 — rodar até tudo passar, incluindo o corpus completo**

```powershell
python -m pytest tests/test_security_sanitize.py -v
```

Esperado: todos os casos parametrizados passam. Se algum `FORBIDDEN` sobreviver, o sanitizador está errado — **não** relaxe o teste.

**Passo 7 — commit**

```python
git add pymail_client/core/security.py tests/
git commit -m "feat(security): allowlist HTML sanitizer with irreversible tracker removal"
```

---

### T-06 — Derivação de texto plano

**Arquivos:**
- Modificar: `pymail_client/core/security.py`
- Criar: `tests/test_plain_text.py`
- Requisitos: RF-RD-02

**Passo 1 — escrever o teste que falha**

```python
def test_html_to_text_plain_removes_markup_and_keeps_text() -> None:
    assert html_to_text_plain("<p>Olá <b>mundo</b></p>") == "Olá mundo"


def test_block_elements_become_line_breaks() -> None:
    assert "\n" in html_to_text_plain("<div>linha 1</div><div>linha 2</div>")


def test_entities_are_decoded() -> None:
    assert html_to_text_plain("<p>A&ccedil;&atilde;o &amp; caf&eacute;</p>") == "Ação & café"


def test_script_and_style_content_is_discarded() -> None:
    text = html_to_text_plain("<style>p{color:red}</style><p>visível</p><script>x()</script>")
    assert text.strip() == "visível"
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_plain_text.py -v`

**Passo 3 — implementar** `html_to_text_plain` sobre `HTMLParser`, com normalização de espaços em branco. Este texto alimenta a pré-visualização da lista (RF-UI-11) e o índice de busca (RF-SRCH-01).

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_plain_text.py -v`

**Passo 5 — commit:** `git commit -am "feat(security): derive plain text from sanitized HTML"`

---

### T-07 — Interceptor de privacidade e perfil do motor de renderização

**Arquivos:**
- Criar: `pymail_client/ui/net_interceptor.py`
- Criar: `tests/fakes/request_recorder.py`
- Criar: `tests/test_privacy_interceptor.py`
- Requisitos: RF-RD-03, RF-RD-06, RNF-PRIV-01 · CA-RF-RD-03-1, CA-RF-RD-06-1, CA-RNF-PRIV-01-1

**Passo 1 — verificar o requisito de inicialização antes de escrever o teste**

`02-arquitetura.md` §5.5 registra que `AA_ShareOpenGLContexts` e a ordem de import de `QtWebEngineWidgets` são exigidos em **algumas** combinações de Qt/plataforma. Confirme na versão de Qt efetivamente instalada, com um script mínimo que abra um `QWebEngineView` vazio em `QT_QPA_PLATFORM=offscreen`. Registre o resultado num comentário em `ui/net_interceptor.py`. Não assuma.

**Passo 2 — escrever o teste que falha**

```python
def test_every_request_attempt_is_recorded_even_when_blocked(recorder) -> None:
    """É o registro das TENTATIVAS que torna CA-RNF-PRIV-01-1 verificável."""
    interceptor = PrivacyInterceptor(allow_remote_images=lambda: False, recorder=recorder)
    interceptor._decide(url="https://rastreador.example.com/p.gif", resource_type="image")
    assert recorder.attempts == ["https://rastreador.example.com/p.gif"]
    assert recorder.blocked == ["https://rastreador.example.com/p.gif"]


@pytest.mark.parametrize("resource_type", ["stylesheet", "script", "xhr", "font", "media"])
def test_non_image_resources_are_always_denied(recorder, resource_type: str) -> None:
    """Mesmo com imagens autorizadas, CSS remoto e beacons continuam bloqueados."""
    interceptor = PrivacyInterceptor(allow_remote_images=lambda: True, recorder=recorder)
    assert interceptor._decide(url="https://x.example.com/a", resource_type=resource_type) is False


def test_image_denied_by_default_and_allowed_with_consent(recorder) -> None:
    allowed = {"v": False}
    interceptor = PrivacyInterceptor(allow_remote_images=lambda: allowed["v"], recorder=recorder)
    assert interceptor._decide(url="https://x/a.png", resource_type="image") is False
    allowed["v"] = True
    assert interceptor._decide(url="https://x/a.png", resource_type="image") is True
```

**Passo 3 — rodar e verificar que falha:** `python -m pytest tests/test_privacy_interceptor.py -v`

**Passo 4 — implementar**

A decisão é extraída para um método puro `_decide(url, resource_type) -> bool`, justamente para ser testável sem instanciar `QWebEngineView` — `interceptRequest` apenas converte os tipos do Qt e delega. `RequestRecorder` acumula `attempts`, `allowed` e `blocked` em listas, para que a asserção seja sobre tentativas, não sobre o HTML resultante.

A configuração de `QWebEngineProfile` e `QWebEngineSettings` segue **literalmente** `02-arquitetura.md` §5.5, com a matriz de decisão por tipo de recurso de `05-seguranca-privacidade.md` §7.

**Passo 5 — rodar e verificar que passa:** `python -m pytest tests/test_privacy_interceptor.py -v`

**Passo 6 — commit:** `git commit -am "feat(privacy): network interceptor as primary tracking defence"`

---

### T-08 — Índice FTS5 e atomicidade corpo+índice

**Arquivos:**
- Modificar: `pymail_client/core/storage.py`
- Criar: `tests/test_storage_search.py`
- Requisitos: RF-SRCH-01, RF-SRCH-04, RF-SRCH-05 · CA-RF-SRCH-01-1, CA-RF-SRCH-04-1, CA-RF-SRCH-05-1

**Passo 1 — escrever o teste que falha**

```python
@pytest.mark.parametrize("query,needle", [
    ("acao", "Ação"), ("ACAO", "ação"), ("servico", "serviço"),
    ("coracao", "coração"), ("SAO PAULO", "São Paulo"),
])
def test_search_is_accent_insensitive(storage_with_messages, query, needle) -> None:
    """CA-RF-SRCH-01-1: remove_diacritics 2 + unicode61."""
    results = storage_with_messages.search(query)
    assert any(needle in r.subject or needle in r.preview for r in results)


def test_store_body_is_atomic_with_index(storage, monkeypatch) -> None:
    """CA-RF-SRCH-04-1: nunca corpo sem índice, nunca índice sem corpo."""
    # Injeta falha na inserção do FTS e verifica rollback completo.
    ...


def test_index_consistency_query_returns_zero(storage_with_messages) -> None:
    assert storage_with_messages.index_inconsistencies() == 0


@pytest.mark.parametrize("raw", ['"', "AND", "*", "NEAR(", "col:valor", "-excluir", "   "])
def test_user_input_never_raises_fts_syntax_error(storage_with_messages, raw) -> None:
    """CA-RF-SRCH-05-1: entrada livre é texto literal, nunca sintaxe FTS5."""
    storage_with_messages.search(raw)      # não deve lançar
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_storage_search.py -v`

**Passo 3 — implementar**

`store_body` conforme `03-modelo-de-dados.md` §5.2 — gravação de `bodies` e de `messages_fts` na **mesma** transação, com `rowid = messages.id` explícito. `build_match_query` conforme §5.3. `search` conforme §5.4, com filtros de RF-SRCH-03. `index_inconsistencies` conforme §5.5.

Confirme o tokenizador diretamente, porque é fácil errar em silêncio:

```powershell
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(x, tokenize=\"unicode61 remove_diacritics 2\")'); c.execute(\"INSERT INTO t VALUES ('Ação')\"); print(c.execute(\"SELECT * FROM t WHERE t MATCH 'acao'\").fetchall())"
```

Esperado: uma linha. Se vier vazio, o tokenizador está errado.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_storage_search.py -v`

**Passo 5 — commit:** `git commit -am "feat(search): FTS5 index kept atomic with body storage"`

---

### T-09 — Despejo de cache em dois níveis

**Arquivos:**
- Modificar: `pymail_client/core/storage.py`
- Criar: `tests/test_storage_eviction.py`
- Requisitos: RF-MSG-06 · CA-RF-MSG-06-1

**Passo 1 — escrever o teste que falha**

```python
def test_level1_eviction_frees_html_but_keeps_search_working(storage_with_cached_bodies) -> None:
    """CA-RF-MSG-06-1: cabeçalho e busca sobrevivem; só o HTML é liberado."""
    storage = storage_with_cached_bodies
    storage.evict_bodies_lru(target_bytes=1)

    row = storage.get_message_by_subject("Ação necessária")
    assert row is not None                                  # cabeçalho preservado
    assert storage.get_body(row.id).html_sanitized is None  # liberado
    assert storage.search("acao")                           # busca continua funcionando


def test_eviction_never_touches_outbox_or_drafts(storage_with_pending_outbox) -> None:
    storage_with_pending_outbox.evict_bodies_lru(target_bytes=0)
    assert len(storage_with_pending_outbox.due_outgoing(now=10**12)) == 1


def test_eviction_respects_lru_order(storage_with_cached_bodies) -> None:
    """Os menos recentemente usados saem primeiro."""
    ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_storage_eviction.py -v`

**Passo 3 — implementar** `evict_bodies_lru` conforme `03-modelo-de-dados.md` §6.4. Nível 1 zera `html_sanitized` e marca `body_state='evicted'`; nível 2 apaga a linha de `bodies`, **mantendo a entrada do FTS5**. A consulta de candidatos é a de §9.

A ordem de despejo é o ponto sutil: despejar a entrada do FTS5 junto com o corpo quebraria a busca silenciosamente, o que é pior do que gastar espaço com o índice (§6.2).

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_storage_eviction.py -v`

**Passo 5 — commit:** `git commit -am "feat(storage): two-tier LRU body eviction preserving search"`

---

## M2 — Rede e sincronização

### T-10 — Sincronização de cabeçalhos (headers-first)

**Arquivos:**
- Modificar: `pymail_client/core/network/imap_client.py`, `pymail_client/core/storage.py`
- Criar: `tests/test_sync_headers.py`
- Requisitos: RF-MSG-01 · CA-RF-MSG-01-1, CA-RF-MSG-01-2

**Passo 1 — escrever o teste que falha**

```python
@pytest.mark.slow
def test_initial_sync_downloads_no_body(imap_server_with_5000) -> None:
    """CA-RF-MSG-01-1: ZERO comandos FETCH de corpo. É o teste central de desempenho."""
    client = ImapClient(...)
    client.connect()
    folder = client.select_folder("INBOX")
    for batch in iter_header_batches(client, start_uid=1, batch_size=200):
        storage.insert_headers(account_id, folder_id, batch)

    body_fetches = [c for c in imap_server_with_5000.commands
                    if c.verb == "UID" and "FETCH" in c.args and _is_body_fetch(c)]
    assert body_fetches == []


def test_header_sync_keeps_database_under_5mb(imap_server_with_5000, tmp_path) -> None:
    """CA-RF-MSG-01-2."""
    ...
    assert (tmp_path / "pymail.db").stat().st_size < 5 * 1024 * 1024
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_sync_headers.py -v`

**Passo 3 — implementar** `fetch_headers` com `UID FETCH <range> (ENVELOPE BODYSTRUCTURE FLAGS INTERNALDATE RFC822.SIZE)` — os itens exatos importam: `BODYSTRUCTURE` traz `has_attachments` sem baixar nada, e `RFC822.SIZE` traz o tamanho. `insert_headers` grava o lote em **uma** transação.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_sync_headers.py -v`

**Passo 5 — commit:** `git commit -am "feat(sync): headers-first initial synchronization"`

---

### T-11 — Sincronização incremental e UIDVALIDITY

**Arquivos:**
- Modificar: `pymail_client/core/network/imap_client.py`, `pymail_client/core/storage.py`
- Criar: `tests/test_sync_incremental.py`
- Requisitos: RF-MSG-01, RF-MSG-04 · CA-RF-MSG-04-1

**Passo 1 — escrever o teste que falha**

```python
def test_uidvalidity_change_invalidates_folder_without_duplicates(sync_fixture) -> None:
    """CA-RF-MSG-04-1."""
    sync_fixture.sync()                            # 100 mensagens
    assert sync_fixture.storage.count_messages() == 100

    sync_fixture.server.set_uidvalidity(999)       # servidor reinicializado
    sync_fixture.sync()

    assert sync_fixture.storage.count_messages() == 100     # não 200
    assert sync_fixture.storage.get_folder_uidvalidity() == 999


def test_incremental_sync_only_fetches_new_uids(sync_fixture) -> None:
    sync_fixture.sync()
    before = len(sync_fixture.server.commands)
    sync_fixture.server.append_messages(3)
    sync_fixture.sync()
    new_fetches = sync_fixture.server.commands[before:]
    assert all("1:100" not in str(c.args) for c in new_fetches)
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_sync_incremental.py -v`

**Passo 3 — implementar** sincronização a partir de `folders.uidnext`, e `invalidate_folder` conforme `03-modelo-de-dados.md` (§4, RF-MSG-04).

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_sync_incremental.py -v`

**Passo 5 — commit:** `git commit -am "feat(sync): incremental sync with UIDVALIDITY invalidation"`

---

### T-12 — Corpo sob demanda e marcação de leitura

**Arquivos:**
- Modificar: `pymail_client/core/network/imap_client.py`, `pymail_client/core/storage.py`
- Criar: `tests/test_body_on_demand.py`
- Requisitos: RF-MSG-02, RF-RD-09, RNF-PERF-03 · CA-RF-MSG-02-1

**Passo 1 — escrever o teste que falha**

```python
def test_opening_message_fetches_exactly_one_body(sync_fixture) -> None:
    """CA-RF-MSG-02-1."""
    sync_fixture.sync()
    mark = len(sync_fixture.server.commands)
    target = sync_fixture.storage.list_messages(folder_id, offset=0, limit=1)[0]

    fetch_and_store_body(sync_fixture.client, sync_fixture.storage, target.id)

    body_fetches = _body_fetches(sync_fixture.server.commands[mark:])
    assert len(body_fetches) == 1
    assert target.remote_id in body_fetches[0].args


def test_cached_message_is_served_without_network(sync_fixture) -> None:
    """RNF-PERF-03: menos de 150 ms, sem rede."""
    ...
    assert len(_body_fetches(sync_fixture.server.commands[mark:])) == 0
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_body_on_demand.py -v`

**Passo 3 — implementar** `fetch_body(remote_id)` com `UID FETCH <uid> (BODY.PEEK[])` — **`BODY.PEEK[]` e não `BODY[]`**, porque `BODY[]` marca a mensagem como lida no servidor como efeito colateral do download, e RF-RD-09 exige controlar *quando* isso acontece.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_body_on_demand.py -v`

**Passo 5 — commit:** `git commit -am "feat(sync): on-demand body fetch with BODY.PEEK"`

---

### T-13 — Pré-busca oportunista cancelável

**Arquivos:**
- Criar: `pymail_client/core/prefetch.py`
- Criar: `tests/test_prefetch.py`
- Requisitos: RF-MSG-03

**Passo 1 — escrever o teste que falha**

```python
def test_prefetch_schedules_next_five_messages(monkeypatch) -> None:
    scheduler = PrefetchScheduler(client, storage, count=5)
    scheduler.schedule_after(message_id=42)
    assert scheduler.pending_remote_ids() == [...]     # os 5 seguintes (RF-MSG-03)


def test_navigation_cancels_pending_prefetch() -> None:
    """Navegar rápido não pode acumular requisições obsoletas."""
    ...


def test_prefetch_never_raises_on_network_failure() -> None:
    """Pré-busca é oportunista: falhar em silêncio é o comportamento correto."""
    ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_prefetch.py -v`

**Passo 3 — implementar** com `CancellationToken` (`02-arquitetura.md` §5.3), rodando em prioridade baixa no `TaskPool`.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_prefetch.py -v`

**Passo 5 — commit:** `git commit -am "feat(sync): cancellable opportunistic prefetch"`

---

### T-14 — IDLE com queda para polling

**Arquivos:**
- Modificar: `pymail_client/core/network/imap_client.py`
- Criar: `tests/test_idle.py`
- Requisitos: RF-MSG-05

**Passo 1 — escrever o teste que falha**

```python
def test_idle_used_when_capability_present(imap_server_idle_capable) -> None:
    client = ImapClient(...)
    client.connect()
    client.wait_for_changes(timeout_s=0.5)
    assert any(c.verb == "IDLE" for c in imap_server_idle_capable.commands)


def test_falls_back_to_noop_polling_when_idle_refused(imap_server_without_idle) -> None:
    """Nem todo servidor suporta IDLE; a queda não pode ser um erro para o usuário."""
    client = ImapClient(...)
    client.connect()
    client.wait_for_changes(timeout_s=0.5)
    assert not any(c.verb == "IDLE" for c in imap_server_without_idle.commands)
    assert any(c.verb == "NOOP" for c in imap_server_without_idle.commands)
    assert client.supports("IDLE") is False


def test_new_message_detected_within_5_seconds(imap_server_idle_capable) -> None:
    """Critério de RF-MSG-05 com IDLE disponível."""
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_idle.py -v`

**Passo 3 — implementar**

`imaplib` não expõe IDLE. A implementação manual: emitir `IDLE`, ler respostas não solicitadas até receber `+ idling`, aguardar com `select()` no socket e um *timeout*, então emitir `DONE` e processar os `EXISTS`/`RECENT` recebidos. Após qualquer erro ou `timeout`, cair para `NOOP` + `UID SEARCH UID <last+1>:*` no intervalo configurado e marcar a capacidade como indisponível **naquela sessão**, para não repetir a falha a cada ciclo.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_idle.py -v`

**Passo 5 — commit:** `git commit -am "feat(imap): manual IDLE with NOOP polling fallback"`

### T-15 — Recuo exponencial, estado offline e erros não modais

**Arquivos:**
- Criar: `pymail_client/core/retry.py`
- Criar: `pymail_client/ui/components/toasts.py`
- Criar: `tests/test_retry.py`
- Requisitos: RF-MSG-08, RF-UI-08 · CA-RF-MSG-08-1

**Passo 1 — escrever o teste que falha**

```python
def test_backoff_schedule_is_exponential_with_cap() -> None:
    assert [backoff_delay(n) for n in range(6)] == [1, 2, 4, 8, 16, 32]
    assert backoff_delay(50) == 300          # teto de 5 minutos (02-arquitetura.md §7)


def test_network_drop_does_not_lose_sync_progress(sync_fixture) -> None:
    """CA-RF-MSG-08-1: queda no meio não corrompe nem perde o que já veio."""
    sync_fixture.server.fail_after_n_commands(5)
    sync_fixture.sync_expecting_partial()
    partial = sync_fixture.storage.count_messages()
    assert 0 < partial < 5000

    sync_fixture.server.recover()
    sync_fixture.sync()
    assert sync_fixture.storage.count_messages() == 5000      # conclui, sem duplicatas


def test_network_failure_never_shows_a_modal_dialog(qtbot) -> None:
    """RF-UI-08: erro de rede não interrompe o trabalho do usuário."""
    ...
    assert not any(isinstance(w, QMessageBox) for w in QApplication.topLevelWidgets())
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_retry.py -v`

**Passo 3 — implementar** `backoff_delay` puro e testável, o estado `offline` no `AccountWorker` (sinal `state_changed`), e o componente de aviso não modal. Nenhum `QMessageBox` para falha de rede — o critério é explícito.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_retry.py -v`

**Passo 5 — commit:** `git commit -am "feat(resilience): exponential backoff and non-modal network errors"`

---

### T-16 — Operações otimistas com fila persistente

**Arquivos:**
- Criar: `pymail_client/core/optimistic.py`
- Criar: `tests/test_optimistic.py`
- Requisitos: RF-MSG-09, RNF-USA-02 · CA-RF-MSG-09-1

**Passo 1 — escrever o teste que falha**

```python
def test_archive_with_network_down_moves_ui_and_queues_op(optimistic_fixture) -> None:
    """CA-RF-MSG-09-1."""
    optimistic_fixture.server.set_offline()
    result = optimistic_fixture.archive(message_id=7)

    assert result.visible_immediately is True          # a UI não espera a rede
    assert optimistic_fixture.storage.get_pending_op(7) is not None
    assert optimistic_fixture.storage.get_message(7).folder_id == archive_folder_id


def test_queued_op_executes_when_connection_returns(optimistic_fixture) -> None:
    optimistic_fixture.server.set_offline()
    optimistic_fixture.archive(message_id=7)
    optimistic_fixture.server.set_online()
    optimistic_fixture.worker.drain_pending_ops()
    assert any(c.verb == "UID" and "MOVE" in c.args for c in optimistic_fixture.server.commands)


def test_permanent_failure_reverts_with_explicit_notice(optimistic_fixture) -> None:
    """Reversão silenciosa é proibida: o usuário precisa saber."""
    optimistic_fixture.server.reject_move_permanently()
    notice = optimistic_fixture.worker.drain_pending_ops()
    assert notice.reverted is True and notice.reason
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_optimistic.py -v`

**Passo 3 — implementar** sobre `pending_ops` e `messages.pending_op` (`03-modelo-de-dados.md` §3). A fila é **persistida**, portanto sobrevive a reinício; a drenagem acontece na thread da conta.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_optimistic.py -v`

**Passo 5 — commit:** `git commit -am "feat(optimistic): persistent pending-operations queue"`

---

### T-17 — Arquivar, excluir, sinalizar e MOVE com alternativa

**Arquivos:**
- Modificar: `pymail_client/core/network/imap_client.py`
- Criar: `pymail_client/core/actions.py`
- Criar: `tests/test_message_actions.py`
- Requisitos: RF-ORG-01, RF-ORG-02, RF-ORG-03, RF-ORG-04, RF-ORG-05 · CA-RF-ORG-01-1, CA-RF-ORG-04-1, CA-RF-ORG-05-1

**Passo 1 — escrever o teste que falha**

```python
def test_move_uses_uid_move_when_capability_present(server_with_move, client) -> None:
    """CA-RF-ORG-01-1."""
    archive([12], destination="Archive")
    assert any("MOVE" in str(c.args) for c in server_with_move.commands)
    assert not any("COPY" in str(c.args) for c in server_with_move.commands)


def test_move_falls_back_to_copy_store_expunge(server_without_move) -> None:
    """Sem MOVE: COPY + STORE \\Deleted + EXPUNGE, nesta ordem."""
    archive([12], destination="Archive")
    verbs = [str(c.args) for c in server_without_move.commands]
    assert any("COPY" in v for v in verbs)
    assert any("+FLAGS" in v and "\\Deleted" in v for v in verbs)
    assert any("EXPUNGE" in v for v in verbs)


def test_expunge_failure_reconciles_without_duplicate_or_loss(server_expunge_fails) -> None:
    """CA-RF-ORG-05-1."""
    ...
    server_expunge_fails.recover()
    sync()
    assert count_messages(folder) == expected        # nem duplicada, nem sumida


def test_bulk_archive_of_50_messages(bulk_fixture) -> None:
    """CA-RF-ORG-04-1: 50 movimentos, UI atualizada antes da resposta do servidor."""
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_message_actions.py -v`

**Passo 3 — implementar** `set_flags` e `move` no `ImapClient` com detecção de capacidade por `CAPABILITY` (guardada na conexão, não consultada a cada operação), e as ações de domínio em `core/actions.py` sobre a fila otimista de T-16.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_message_actions.py -v`

**Passo 5 — commit:** `git commit -am "feat(org): archive, delete, flag with UID MOVE and fallback"`

---

### T-18 — Infraestrutura de threads e múltiplas contas

**Arquivos:**
- Criar: `pymail_client/core/tasks.py`
- Criar: `pymail_client/core/accounts.py`
- Criar: `tests/test_tasks.py`, `tests/test_multi_account.py`
- Requisitos: RF-ACC-02 · CA-RF-ACC-02-1

**Passo 1 — escrever o teste que falha**

```python
def test_each_account_owns_a_dedicated_thread_and_connection(multi_account_fixture) -> None:
    """ADR-001: imaplib não é thread-safe. Esta é a asserção que impede o bug."""
    workers = multi_account_fixture.manager.workers
    assert len({id(w) for w in workers.values()}) == len(workers)
    assert all(w.isRunning() for w in workers.values())
    for worker in workers.values():
        assert worker.connection_thread_id() == worker.current_thread_id()


def test_one_account_auth_failure_does_not_affect_the_others(multi_account_fixture) -> None:
    """CA-RF-ACC-02-1."""
    multi_account_fixture.server_for("b@exemplo.com").set_refuse_login(True)
    multi_account_fixture.manager.sync_all()
    assert multi_account_fixture.manager.state_of("a@exemplo.com") == "idle"
    assert multi_account_fixture.manager.state_of("b@exemplo.com") == "error"
    assert multi_account_fixture.manager.state_of("c@exemplo.com") == "idle"


def test_no_work_is_executed_on_the_gui_thread(task_pool, qtbot) -> None:
    """RNF-PERF-01, unidade: o TaskPool nunca executa na thread principal."""
    main_thread = threading.current_thread().ident
    observed = []
    task_pool.submit(lambda: observed.append(threading.current_thread().ident))
    qtbot.waitUntil(lambda: observed)
    assert observed[0] != main_thread
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_tasks.py tests/test_multi_account.py -v`

**Passo 3 — implementar**

`core/tasks.py` segue `02-arquitetura.md` §5.3. O ponto crítico: `AccountWorker` é uma `QThread` por conta, com `queue.Queue` serializando comandos e criando a conexão IMAP **dentro de `run()`**, nunca no construtor — uma conexão criada na thread da GUI e usada na thread do worker é exatamente o bug que ADR-001 existe para evitar.

`test_connection_thread_affinity` deve detectar a violação de forma **determinística**, e não por sorte de escalonamento: o cliente falso registra o `ident` da thread no momento da criação e compara com o `ident` a cada comando.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_tasks.py tests/test_multi_account.py -v`

**Passo 5 — commit:** `git commit -am "feat(tasks): per-account dedicated threads with connection affinity"`

---

### T-19 — Remover conta e limpar todos os dados

**Arquivos:**
- Modificar: `pymail_client/core/accounts.py`, `pymail_client/core/storage.py`
- Criar: `tests/test_account_deletion.py`
- Requisitos: RF-ACC-05, RNF-USA-01 · CA-RF-ACC-05-1

**Passo 1 — escrever o teste que falha**

```python
def test_deleting_account_leaves_no_trace(full_fixture) -> None:
    """CA-RF-ACC-05-1: nenhuma linha em accounts/folders/messages/bodies/attachments,
    nenhuma entrada no índice, nenhuma credencial no keyring."""
    account_id = full_fixture.account_id
    message_ids = full_fixture.storage.list_message_ids(account_id)
    assert message_ids

    full_fixture.manager.remove_account(account_id, confirmed=True)

    assert full_fixture.storage.get_account(account_id) is None
    assert full_fixture.storage.count_messages_of_account(account_id) == 0
    assert full_fixture.storage.fts_rows_for(message_ids) == 0
    assert full_fixture.keyring.get_credential("a@exemplo.com") is None


def test_deletion_requires_explicit_confirmation(full_fixture) -> None:
    with pytest.raises(ConfirmationRequired):
        full_fixture.manager.remove_account(full_fixture.account_id, confirmed=False)
    assert full_fixture.storage.get_account(full_fixture.account_id) is not None
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_account_deletion.py -v`

**Passo 3 — implementar** com `ON DELETE CASCADE` (que depende de `PRAGMA foreign_keys=ON`, verificado em T-02) mais a remoção explícita das linhas de `messages_fts`, que **não** participam do cascade por ser tabela virtual. Esse é o detalhe que faz este teste falhar se esquecido.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_account_deletion.py -v`

**Passo 5 — commit:** `git commit -am "feat(accounts): complete local data removal on account deletion"`

---

## M3 — Leitura e privacidade na interface

### T-20 — Links, confirmação de destino e navegação externa

**Arquivos:**
- Criar: `pymail_client/core/links.py`
- Modificar: `pymail_client/ui/components/reader.py`
- Criar: `tests/test_links.py`
- Requisitos: RF-RD-06, RF-RD-07 · CA-RF-RD-07-1

**Passo 1 — escrever o teste que falha**

```python
def test_confirmation_shows_real_host_not_display_text() -> None:
    """CA-RF-RD-07-1: texto exibido mente; o host real não."""
    link = parse_link('<a href="https://exemplo.com/x">https://banco-falso.com</a>')
    assert link.display_text == "https://banco-falso.com"
    assert link.real_host == "exemplo.com"
    assert "exemplo.com" in build_confirmation_message(link)


@pytest.mark.parametrize("href", [
    "javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)", "file:///C:/Windows/System32/",
])
def test_dangerous_schemes_are_never_openable(href: str) -> None:
    assert is_openable(href) is False


def test_reader_never_navigates_away_from_the_message(reader, qtbot) -> None:
    """RF-RD-07: o leitor não é um navegador."""
    ...
    assert reader.view.url().scheme() == "pymail"
    assert opened_externally == ["https://exemplo.com/x"]
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_links.py -v`

**Passo 3 — implementar** com `QDesktopServices.openUrl` para navegação externa e bloqueio de navegação interna. Configure também `QWebEnginePage.acceptNavigationRequest` para recusar qualquer navegação que não seja para a `baseUrl` fictícia.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_links.py -v`

**Passo 5 — commit:** `git commit -am "feat(reader): external-only navigation with real-destination confirmation"`

---

### T-21 — Anexos sob demanda e sanitização de nomes

**Arquivos:**
- Modificar: `pymail_client/core/network/imap_client.py`, `pymail_client/core/storage.py`
- Criar: `pymail_client/core/attachments.py`
- Criar: `tests/test_attachments.py`
- Requisitos: RF-MSG-07, RNF-SEC-04 · CA-RNF-SEC-04-1

**Passo 1 — escrever o teste que falha**

```python
@pytest.mark.parametrize("hostile,expected_safe", [
    ("../../evil.sh", "evil.sh"),
    ("..\\..\\win.ini", "win.ini"),
    ("CON", "_CON"),
    ("PRN.txt", "_PRN.txt"),
    ("arquivo\x00.txt", "arquivo.txt"),
    ("a" * 300 + ".pdf", None),          # truncado, com extensão preservada
    ("...", "_"),
])
def test_hostile_filenames_are_sanitized(hostile, expected_safe, tmp_path) -> None:
    """CA-RNF-SEC-04-1."""
    result = safe_attachment_path(tmp_path, hostile)
    assert result.parent == tmp_path.resolve()          # nunca escapa do destino
    if expected_safe is not None:
        assert result.name == expected_safe


def test_collision_never_overwrites(tmp_path) -> None:
    first = safe_attachment_path(tmp_path, "nota.pdf"); first.write_bytes(b"a")
    second = safe_attachment_path(tmp_path, "nota.pdf")
    assert second != first and first.read_bytes() == b"a"


def test_attachment_is_not_downloaded_until_requested(sync_fixture) -> None:
    """RF-MSG-07: na fase 1, só metadados."""
    sync_fixture.sync()
    assert sync_fixture.storage.attachments_are_metadata_only()
    assert not _attachment_fetches(sync_fixture.server.commands)
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_attachments.py -v`

**Passo 3 — implementar** `list_attachments` a partir do `BODYSTRUCTURE` já obtido em T-10 (sem novo `FETCH`), `fetch_attachment` sob demanda, e `safe_attachment_path` cobrindo travessia, nomes reservados do Windows, caracteres de controle, byte nulo, truncamento e colisão.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_attachments.py -v`

**Passo 5 — commit:** `git commit -am "feat(attachments): metadata-first listing and hostile-name sanitization"`

---

### T-22 — Autorização de imagens por remetente

**Arquivos:**
- Modificar: `pymail_client/core/storage.py`, `pymail_client/ui/components/reader.py`
- Criar: `tests/test_image_allowlist.py`
- Requisitos: RF-RD-03, RNF-PRIV-04 · CA-RF-RD-03-2

**Passo 1 — escrever o teste que falha**

```python
def test_allowlist_is_scoped_to_account_and_sender(allowlist_fixture) -> None:
    """CA-RF-RD-03-2: autorizar A não autoriza B, e não vaza entre contas."""
    allowlist_fixture.allow(account_id=1, from_addr="a@exemplo.com")

    assert allowlist_fixture.is_allowed(account_id=1, from_addr="a@exemplo.com") is True
    assert allowlist_fixture.is_allowed(account_id=1, from_addr="b@exemplo.com") is False
    assert allowlist_fixture.is_allowed(account_id=2, from_addr="a@exemplo.com") is False


def test_allowlist_survives_restart(allowlist_fixture) -> None:
    allowlist_fixture.allow(1, "a@exemplo.com")
    allowlist_fixture.restart()
    assert allowlist_fixture.is_allowed(1, "a@exemplo.com") is True


def test_allowlist_matching_is_case_insensitive(allowlist_fixture) -> None:
    allowlist_fixture.allow(1, "A@Exemplo.COM")
    assert allowlist_fixture.is_allowed(1, "a@exemplo.com") is True


def test_revoking_stops_future_image_loading(allowlist_fixture) -> None:
    """RNF-PRIV-04: a autorização é revogável."""
    ...


def test_allowing_images_never_restores_tracking_pixels(allowlist_fixture) -> None:
    """RF-RD-04 + CA-RF-RD-04-1: a remoção é irreversível, mesmo com consentimento."""
    ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_image_allowlist.py -v`

**Passo 3 — implementar** sobre a tabela `sender_image_policy` (`03-modelo-de-dados.md` §3), endereço normalizado para minúsculo, e o banner de consentimento no leitor. Ao autorizar, o HTML é re-renderizado a partir de `restore_remote_resources` (T-05), que reaplica `data-pymail-src` em `src` — e nada mais.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_image_allowlist.py -v`

**Passo 5 — commit:** `git commit -am "feat(privacy): per-sender image allowlist, revocable"`

---

### T-23 — Controles do leitor e zoom persistente

**Arquivos:**
- Modificar: `pymail_client/ui/components/reader.py`, `pymail_client/config.py`
- Criar: `tests/test_reader_controls.py`
- Requisitos: RF-RD-08

**Passo 1 — escrever o teste que falha**

```python
def test_zoom_shortcuts_change_and_reset(reader, qtbot) -> None:
    qtbot.keyClick(reader, Qt.Key_Plus, Qt.ControlModifier)
    assert reader.zoom_factor() > 1.0
    qtbot.keyClick(reader, Qt.Key_0, Qt.ControlModifier)
    assert reader.zoom_factor() == 1.0


def test_zoom_persists_across_sessions(reader, config_path) -> None:
    reader.set_zoom_factor(1.25)
    assert load_config(config_path).reader_zoom == 1.25
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_reader_controls.py -v`

**Passo 3 — implementar** `setZoomFactor` com limites (0,5 a 3,0) e persistência em `AppConfig`.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_reader_controls.py -v`

**Passo 5 — commit:** `git commit -am "feat(reader): zoom controls with persisted preference"`

---

## M4 — Composição e envio

### T-24 — Compositor com validações

**Arquivos:**
- Criar: `pymail_client/ui/components/composer.py`
- Criar: `tests/test_composer.py`
- Requisitos: RF-SND-01, RF-SND-06, RF-SND-08

**Passo 1 — escrever o teste que falha**

```python
def test_composer_collects_all_fields(composer, qtbot) -> None:
    composer.set_to("a@exemplo.com, b@exemplo.com")
    composer.set_cc("c@exemplo.com")
    composer.set_bcc("d@exemplo.com")
    composer.set_subject("Assunto")
    composer.set_body("Corpo")
    draft = composer.to_draft()
    assert draft.to_addrs == ("a@exemplo.com", "b@exemplo.com")
    assert draft.cc_addrs == ("c@exemplo.com",)
    assert draft.bcc_addrs == ("d@exemplo.com",)


@pytest.mark.parametrize("value", ["a@", "@b.com", "sem-arroba", "a@b@c.com", ""])
def test_invalid_recipients_are_rejected(composer, value) -> None:
    ...


def test_large_attachment_requires_confirmation(composer, monkeypatch) -> None:
    """RF-SND-06: acima de 20 MB padrão."""
    composer.attach(FakeAttachment(size_bytes=25 * 1024 * 1024))
    assert composer.send_clicked() is False
    assert composer.warning_shown == "large_attachment"


def test_missing_subject_warns_but_allows_sending(composer) -> None:
    """RF-SND-08: alerta, não impede."""
    composer.set_to("a@exemplo.com")
    assert composer.confirm_needed() == "empty_subject"
    assert composer.send_clicked(confirmed=True) is True
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_composer.py -v`

**Passo 3 — implementar** o compositor seguindo a anatomia de `04-ui-ux.md` §4. **O `to_draft()` não abre rede e não conhece SMTP** — ele apenas produz um `Draft`, que é o que torna o Undo Send possível (T-26/T-28).

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_composer.py -v`

**Passo 5 — commit:** `git commit -am "feat(composer): draft creation with validation, no network side effects"`

---

### T-25 — Responder, responder a todos e encaminhar

**Arquivos:**
- Criar: `pymail_client/core/compose.py`
- Criar: `tests/test_reply_forward.py`
- Requisitos: RF-SND-02

**Passo 1 — escrever o teste que falha**

```python
def test_reply_targets_sender_not_all_recipients() -> None:
    draft = build_reply(original_message, mode=ReplyMode.SENDER)
    assert draft.to_addrs == ("remetente@exemplo.com",)


def test_reply_all_excludes_own_address_and_deduplicates() -> None:
    """Erro clássico: responder a si mesmo."""
    draft = build_reply(original_with_self_in_cc, mode=ReplyMode.ALL,
                        own_addresses={"eu@exemplo.com"})
    assert "eu@exemplo.com" not in draft.to_addrs + draft.cc_addrs
    assert len(set(draft.cc_addrs)) == len(draft.cc_addrs)


def test_threading_headers_are_preserved() -> None:
    """Sem isto, a resposta não aparece encadeada no cliente do destinatário."""
    draft = build_reply(original_message, mode=ReplyMode.SENDER)
    assert draft.in_reply_to == original_message.message_id
    assert draft.references_hdr == " ".join((*original.references, original.message_id))


@pytest.mark.parametrize("subject,expected", [
    ("Reunião", "Re: Reunião"),
    ("Re: Reunião", "Re: Reunião"),          # nunca "Re: Re:"
    ("RE: Reunião", "RE: Reunião"),
    ("Enc: Reunião", "Re: Enc: Reunião"),
])
def test_subject_prefix_is_not_duplicated(subject, expected) -> None:
    ...


def test_forward_has_empty_recipients_and_quoted_body() -> None:
    draft = build_forward(original_message)
    assert draft.to_addrs == ()
    assert "---------- Mensagem encaminhada ----------" in draft.body_text
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_reply_forward.py -v`

**Passo 3 — implementar** em `core/compose.py` como funções puras `(MessageRow, ...) -> Draft`. Funções puras aqui valem muito: é onde os bugs de citação e encadeamento vivem, e testá-las sem interface é barato.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_reply_forward.py -v`

**Passo 5 — commit:** `git commit -am "feat(compose): reply, reply-all and forward with correct threading"`

---

### T-26 — Fila de saída persistente

**Arquivos:**
- Modificar: `pymail_client/core/storage.py`
- Criar: `pymail_client/core/outbox.py`
- Criar: `tests/test_outbox.py`
- Requisitos: RF-SND-04, RNF-REL-01 · CA-RF-SND-04-1

**Passo 1 — escrever o teste que falha**

```python
def test_message_is_persisted_before_any_network_call(outbox_fixture) -> None:
    """RNF-REL-01: existe em disco antes de existir na rede."""
    outbox_fixture.enqueue(draft)
    outbox_fixture.storage.close_thread_connection()      # simula encerramento
    assert Storage(outbox_fixture.db_path).due_outgoing(now=10**12)


def test_message_id_is_stable_between_enqueue_and_send(outbox_fixture) -> None:
    """CA-RF-SND-03-2."""
    outbox_id = outbox_fixture.enqueue(draft)
    stable = outbox_fixture.storage.get_outgoing(outbox_id).message_id
    outbox_fixture.run_scheduler_until_sent()
    assert outbox_fixture.smtp_server.sent[0].message_id == stable


def test_restart_expired_message_within_grace_is_sent(outbox_fixture) -> None:
    """CA-RF-SND-04-1: dentro da carência de 24 h, envia."""
    ...


def test_restart_expired_message_beyond_grace_becomes_failure_with_notice(outbox_fixture) -> None:
    """CA-RF-SND-04-1: além da carência, falha notificada — nunca desaparece em silêncio."""
    ...
    assert outbox_fixture.storage.get_outgoing(outbox_id).state == "failed"
    assert outbox_fixture.notices[-1].kind == "send_expired"
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_outbox.py -v`

**Passo 3 — implementar** `enqueue_outgoing`, `due_outgoing`, `mark_outgoing` conforme `03-modelo-de-dados.md` §5.4 e §9, mais a lógica de recuperação na inicialização descrita em `02-arquitetura.md` §6.3 passo 5.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_outbox.py -v`

**Passo 5 — commit:** `git commit -am "feat(outbox): durable send queue with restart recovery"`

---

### T-27 — Cliente SMTP com TLS obrigatório

**Arquivos:**
- Criar: `pymail_client/core/network/smtp_client.py`
- Criar: `tests/fakes/smtp_server.py`
- Criar: `tests/test_smtp_client.py`
- Requisitos: RF-SND-03, RF-SND-07 · CA-RF-SND-07-1

**Passo 1 — escrever o teste que falha**

```python
def test_plaintext_smtp_is_refused_by_default(smtp_server_plain) -> None:
    """CA-RF-SND-07-1: exceção exige opt-in explícito e registrado."""
    with pytest.raises(TLSError):
        SmtpClient(host="127.0.0.1", port=smtp_server_plain.port,
                   security="none", allow_insecure=False).connect()


def test_plaintext_allowed_only_with_explicit_optin(smtp_server_plain, caplog) -> None:
    SmtpClient(..., security="none", allow_insecure=True).connect()
    assert any("insecure" in r.message.lower() for r in caplog.records)


def test_starttls_upgrade_is_performed(smtp_server_starttls) -> None:
    client = SmtpClient(..., security="starttls", allow_insecure=False)
    client.connect()
    assert smtp_server_starttls.commands[0].verb in {"EHLO", "STARTTLS"}


def test_send_builds_rfc5322_message_with_attachments(smtp_server_starttls, draft) -> None:
    ...
    assert sent.headers["MIME-Version"] == "1.0"
    assert sent.headers["Message-ID"] == draft.message_id
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_smtp_client.py -v`

**Passo 3 — implementar** sobre `smtplib` com `ssl.create_default_context()`, `starttls()` quando aplicável, e montagem MIME com `email.message.EmailMessage`. O servidor falso de SMTP **conta conexões recebidas** — é isso que prova CA-RF-SND-03-1 em T-28.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_smtp_client.py -v`

**Passo 5 — commit:** `git commit -am "feat(smtp): TLS-enforced sending with MIME composition"`

---

### T-28 — Agendador do Undo Send

**Arquivos:**
- Criar: `pymail_client/core/send_scheduler.py`
- Modificar: `pymail_client/ui/components/toasts.py`
- Criar: `tests/test_undo_send.py`
- Requisitos: RF-SND-03 · CA-RF-SND-03-1, CA-RF-SND-03-2

**Passo 1 — escrever o teste que falha**

```python
def test_cancel_within_window_opens_no_smtp_connection(scheduler_fixture) -> None:
    """CA-RF-SND-03-1: a prova é a contagem de conexões, não o estado interno."""
    outbox_id = scheduler_fixture.send(draft)
    scheduler_fixture.advance_time(seconds=5)          # janela é de 10 s
    scheduler_fixture.cancel(outbox_id)
    scheduler_fixture.advance_time(seconds=60)

    assert scheduler_fixture.smtp_server.connections == 0
    assert scheduler_fixture.storage.get_outgoing(outbox_id).state == "canceled"
    assert scheduler_fixture.draft_was_reopened(outbox_id) is True


def test_not_cancelling_sends_exactly_once(scheduler_fixture) -> None:
    """CA-RF-SND-03-2."""
    scheduler_fixture.send(draft)
    scheduler_fixture.advance_time(seconds=11)
    scheduler_fixture.advance_time(seconds=600)

    assert len(scheduler_fixture.smtp_server.sent) == 1
    assert scheduler_fixture.storage.get_outgoing(outbox_id).state == "sent"


@pytest.mark.parametrize("delay", [5, 10, 30])
def test_configurable_window_is_respected(scheduler_fixture, delay) -> None:
    ...


def test_scheduler_uses_a_timer_not_a_busy_loop(scheduler_fixture, qtbot) -> None:
    """O agendador agenda; não executa trabalho na thread da GUI."""
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_undo_send.py -v`

**Passo 3 — implementar** com um `QTimer` de 1 s na thread da GUI que apenas consulta `due_outgoing` e delega o envio à thread de envio. Testar com tempo virtual (`advance_time`) em vez de `sleep`, para que a suíte não leve minutos.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_undo_send.py -v`

**Passo 5 — commit:** `git commit -am "feat(send): undo-send window with zero SMTP contact while cancellable"`

### T-29 — Ciclo de vida da aplicação e recuperação na inicialização

**Arquivos:**
- Criar: `pymail_client/main.py`
- Criar: `pymail_client/core/bootstrap.py`
- Criar: `tests/test_bootstrap.py`
- Requisitos: RF-SND-04, RF-SET-03 · CA-RF-SND-04-1

**Passo 1 — escrever o teste que falha**

```python
def test_startup_sequence_order_is_fixed(bootstrap_spy) -> None:
    """A ordem importa: migrar antes de ler, verificar antes de migrar."""
    run_bootstrap(bootstrap_spy.config)
    assert bootstrap_spy.calls == [
        "load_config",
        "open_storage",
        "quick_check",        # nunca migrar um banco já corrompido
        "migrate",
        "recover_outbox",     # antes de qualquer sincronização
        "build_ui",
    ]


def test_corrupt_database_is_detected_before_migration(bootstrap_spy) -> None:
    """03-modelo-de-dados.md §8.1: migrar banco corrompido propaga a corrupção."""
    bootstrap_spy.truncate_database()
    run_bootstrap(bootstrap_spy.config)
    assert "migrate" not in bootstrap_spy.calls
    assert "recover_corrupt" in bootstrap_spy.calls


def test_expired_outbox_entries_are_resolved_at_startup(bootstrap_spy) -> None:
    """CA-RF-SND-04-1."""
    ...


def test_atshared_opengl_attribute_is_set_before_qapplication(bootstrap_spy) -> None:
    """02-arquitetura.md §5.5: errar isto causa encerramento sem mensagem útil."""
    assert bootstrap_spy.attribute_set_before_app_creation is True
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_bootstrap.py -v`

**Passo 3 — implementar**

`bootstrap.py` executa a sequência na ordem acima, nesta razão: **antes** de qualquer sincronização e **antes** de qualquer migração, o banco precisa passar por `quick_check`; e antes de qualquer leitura, o `outbox` deve ser recuperado, porque ele contém o dado do usuário. `main.py` define `AA_ShareOpenGLContexts` e importa `QtWebEngineWidgets` **antes** de criar o `QApplication`, conforme o que foi confirmado em T-07.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_bootstrap.py -v`

**Passo 5 — commit:** `git commit -am "feat(bootstrap): fixed startup sequence with integrity and outbox recovery"`

---

### T-30 — Falha de envio, motivo visível e reenvio

**Arquivos:**
- Modificar: `pymail_client/core/send_scheduler.py`, `pymail_client/ui/components/toasts.py`
- Criar: `tests/test_send_failure.py`
- Requisitos: RF-SND-05 · CA-RF-SND-05-1

**Passo 1 — escrever o teste que falha**

```python
def test_refused_connection_leaves_message_in_error_state(send_fixture) -> None:
    """CA-RF-SND-05-1."""
    send_fixture.smtp_server.refuse_connections()
    send_fixture.send_and_wait(draft)

    row = send_fixture.storage.get_outgoing(send_fixture.outbox_id)
    assert row.state == "failed"
    assert row.last_error                       # motivo do servidor preservado
    assert send_fixture.ui_shows_retry(row.id)


def test_message_is_never_silently_discarded(send_fixture) -> None:
    """Requisito explícito: nenhum descarte silencioso."""
    send_fixture.smtp_server.reject_recipient("a@exemplo.com", code=550)
    send_fixture.send_and_wait(draft)
    assert send_fixture.storage.get_outgoing(send_fixture.outbox_id) is not None


def test_retry_after_transient_failure_succeeds(send_fixture) -> None:
    send_fixture.smtp_server.refuse_connections()
    send_fixture.send_and_wait(draft)
    send_fixture.smtp_server.accept_connections()
    send_fixture.retry(send_fixture.outbox_id)
    assert send_fixture.storage.get_outgoing(send_fixture.outbox_id).state == "sent"
    assert len(send_fixture.smtp_server.sent) == 1        # enviado uma vez, não duas


def test_retry_does_not_duplicate_a_message_already_sent(send_fixture) -> None:
    """Risco real: o servidor aceitou e a resposta se perdeu. Message-ID estável
    permite reenviar sem duplicar do ponto de vista do destinatário."""
    ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_send_failure.py -v`

**Passo 3 — implementar** a classificação de erro SMTP (transitório 4xx versus permanente 5xx), o estado `failed` com `last_error` e `smtp_response`, e o botão de reenvio reutilizando o mesmo `Message-ID` de T-26.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_send_failure.py -v`

**Passo 5 — commit:** `git commit -am "feat(send): explicit failure state with safe retry"`

---

## M5 — Interface completa

### T-31 — Interface de busca, filtros e debounce

**Arquivos:**
- Criar: `pymail_client/ui/components/search_bar.py`
- Criar: `tests/test_search_ui.py`
- Requisitos: RF-SRCH-02, RF-SRCH-03, RNF-PERF-04 · CA-RF-SRCH-02-1

**Passo 1 — escrever o teste que falha**

```python
def test_typing_debounces_to_a_single_query(search_ui, qtbot) -> None:
    """RF-SRCH-02: 250 ms, uma consulta e não uma por tecla."""
    search_ui.search_bar.type_text("relatorio", interval_ms=30)
    qtbot.wait(400)
    assert search_ui.storage.query_count == 1


def test_fifty_thousand_messages_query_under_100ms(seeded_storage) -> None:
    """CA-RF-SRCH-02-1, com margem de 3x tolerada em CI (06-estrategia-de-testes.md)."""
    elapsed = timed_search(seeded_storage, "nota fiscal")
    assert elapsed < 0.300


def test_filters_combine_with_text_query(search_ui, qtbot) -> None:
    search_ui.set_filters(account_id=1, unread_only=True, with_attachment=True, since=...)
    ...


def test_no_results_state_is_explicit(search_ui) -> None:
    """RF-UI-07: nunca uma área vazia sem explicação."""
    ...


def test_search_never_runs_on_the_gui_thread(search_ui, qtbot) -> None:
    ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_search_ui.py -v`

**Passo 3 — implementar** `QTimer` de debounce, consulta no `TaskPool`, filtros de RF-SRCH-03, e ordenação alternável por data ou relevância (`03-modelo-de-dados.md` §5.4).

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_search_ui.py -v`

**Passo 5 — commit:** `git commit -am "feat(search-ui): debounced incremental search with filters"`

---

### T-32 — Janela principal e layout de três colunas

**Arquivos:**
- Criar: `pymail_client/ui/main_window.py`
- Criar: `tests/test_main_window.py`
- Requisitos: RF-UI-01, RF-UI-07

**Passo 1 — escrever o teste que falha**

```python
def test_three_columns_exist_with_spec_widths(main_window) -> None:
    """RF-UI-01 + 04-ui-ux.md §3."""
    assert main_window.splitter.count() == 3
    assert main_window.sidebar.width() == SIDEBAR_W
    assert main_window.minimumWidth() == WINDOW_MIN_W


def test_geometry_is_restored_between_sessions(main_window, qtbot) -> None:
    main_window.resize(1400, 900)
    main_window.splitter.setSizes([300, 450, 650])
    main_window.close()
    reopened = build_main_window()
    assert reopened.size() == QSize(1400, 900)


def test_empty_state_explains_what_to_do(main_window) -> None:
    """RF-UI-07."""
    assert main_window.reader.visible_state() == "empty"
    assert main_window.reader.empty_message()      # texto não vazio
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_main_window.py -v`

**Passo 3 — implementar** o `QSplitter` de três colunas com larguras de `04-ui-ux.md` §3, persistência de geometria via `QSettings` ou `AppConfig`, e todos os estados vazios vindos do documento de UI. Este é o esqueleto em que os componentes de T-31 e T-33 a T-36 se encaixam.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_main_window.py -v`

**Passo 5 — commit:** `git commit -am "feat(ui): three-column main window with persisted geometry"`

---

### T-33 — Sidebar colapsável, contadores e progresso

**Arquivos:**
- Criar: `pymail_client/ui/components/sidebar.py`
- Criar: `tests/test_sidebar.py`
- Requisitos: RF-UI-02, RF-UI-10, RNF-USA-01

**Passo 1 — escrever o teste que falha**

```python
def test_sidebar_collapse_state_persists(sidebar, qtbot) -> None:
    sidebar.toggle_collapsed()
    assert sidebar.is_collapsed() is True
    assert build_sidebar().is_collapsed() is True       # RF-UI-02


def test_unread_badges_match_database(sidebar_with_data) -> None:
    counts = sidebar_with_data.unread_counts()
    assert counts["INBOX"] == sidebar_with_data.storage.count_unread("INBOX")


def test_sync_progress_is_shown_per_account(sidebar_with_data, qtbot) -> None:
    """RF-UI-10: indicador discreto, por conta."""
    sidebar_with_data.worker_for(1).report_progress(done=50, total=200)
    assert sidebar_with_data.progress_for(1) == 0.25


def test_account_removal_asks_for_confirmation(sidebar_with_data, qtbot) -> None:
    """RNF-USA-01 + T-19."""
    ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_sidebar.py -v`

**Passo 3 — implementar** conforme a anatomia de `04-ui-ux.md` §4.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_sidebar.py -v`

**Passo 5 — commit:** `git commit -am "feat(ui): collapsible sidebar with unread counts and sync progress"`

---

### T-34 — Atalhos de teclado com guarda de foco

Esta tarefa tem a armadilha mais comum de clientes de e-mail. A guarda de foco é o requisito, não um detalhe.

**Arquivos:**
- Criar: `pymail_client/ui/shortcuts.py`
- Modificar: `pymail_client/ui/main_window.py`
- Criar: `tests/test_shortcuts.py`
- Requisitos: RF-UI-03, RF-UI-04 · CA-RF-UI-03-1, CA-RF-UI-04-1

**Passo 1 — escrever o teste que falha**

```python
@pytest.mark.parametrize("key,action", [
    (Qt.Key_C, "compose"), (Qt.Key_E, "archive"), (Qt.Key_Backspace, "archive"),
    (Qt.Key_D, "trash"), (Qt.Key_Delete, "trash"), (Qt.Key_Slash, "focus_search"),
    (Qt.Key_J, "next_message"), (Qt.Key_K, "previous_message"),
])
def test_shortcuts_fire_with_list_focused(main_window, qtbot, key, action) -> None:
    """CA-RF-UI-03-1."""
    main_window.message_list.setFocus()
    qtbot.keyClick(main_window, key)
    assert main_window.last_action == action


@pytest.mark.parametrize("key", [Qt.Key_C, Qt.Key_E, Qt.Key_D, Qt.Key_J, Qt.Key_K])
def test_letter_shortcuts_do_not_fire_while_typing(main_window, qtbot, key) -> None:
    """CA-RF-UI-04-1: o bug clássico. Digitar 'c' na busca não abre o compositor."""
    main_window.search_bar.setFocus()
    before = main_window.last_action
    qtbot.keyClick(main_window.search_bar, key)
    assert main_window.last_action == before


def test_typing_in_search_inserts_the_character(main_window, qtbot) -> None:
    field = main_window.search_bar.line_edit
    field.setFocus()
    qtbot.keyClicks(field, "caixa")
    assert field.text() == "caixa"


def test_escape_returns_focus_to_list_and_reactivates_shortcuts(main_window, qtbot) -> None:
    """CA-RF-UI-04-1, segunda parte."""
    main_window.search_bar.line_edit.setFocus()
    qtbot.keyClick(main_window.search_bar.line_edit, Qt.Key_Escape)
    assert main_window.message_list.hasFocus()

    qtbot.keyClick(main_window, Qt.Key_J)
    assert main_window.last_action == "next_message"


def test_composer_body_never_triggers_navigation_shortcuts(main_window, qtbot) -> None:
    main_window.open_composer().body.setFocus()
    qtbot.keyClicks(main_window.composer.body, "jkjk")
    assert main_window.composer.body.toPlainText() == "jkjk"
    assert main_window.last_action != "next_message"
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_shortcuts.py -v`

**Passo 3 — implementar**

`shortcuts.py` centraliza o registro com um predicado de guarda explícito, em vez de espalhar `QShortcut` pela interface:

```python
def _text_input_has_focus() -> bool:
    """RF-UI-04: atalhos de letra ficam inertes em campos de texto.

    Cobre QLineEdit, QTextEdit, QPlainTextEdit e QComboBox editável.
    Esc NÃO é suprimido: é o que devolve o foco (CA-RF-UI-04-1).
    """
    widget = QApplication.focusWidget()
    return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit))
```

Use `Qt.ShortcutContext.WindowShortcut` e registre as teclas de letra condicionadas a `not _text_input_has_focus()`. `Esc` é registrado **sem** guarda, justamente para poder sair do campo.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_shortcuts.py -v`

**Passo 5 — commit:** `git commit -am "feat(ui): inbox-zero shortcuts with focus guard"`

---

### T-35 — Lista de mensagens virtualizada

**Arquivos:**
- Criar: `pymail_client/ui/components/message_list.py`
- Criar: `tests/test_message_list.py`
- Requisitos: RF-UI-05, RF-UI-09, RF-UI-11 · CA-RF-UI-05-1

**Passo 1 — escrever o teste que falha**

```python
def test_fifty_thousand_messages_create_no_per_item_widgets(message_list) -> None:
    """CA-RF-UI-05-1: widgets limitados à área visível + margem."""
    message_list.set_messages(generate_messages(50_000))
    assert message_list.row_count() == 50_000
    assert message_list.created_item_widgets() < 50        # não 50.000


def test_item_shows_all_required_fields(message_list) -> None:
    """RF-UI-11: remetente, assunto, trecho, data, não lido, sinalizado, anexo."""
    ...


@pytest.mark.parametrize("density,expected_height", [("comfortable", 72), ("compact", 40)])
def test_density_changes_row_height(message_list, density, expected_height) -> None:
    """RF-UI-09; alturas conforme 04-ui-ux.md §2."""
    ...


def test_scrolling_large_list_stays_responsive(message_list, qtbot) -> None:
    message_list.set_messages(generate_messages(50_000))
    with qtbot.waitUntil(lambda: message_list.scroll_to_bottom_and_settle(), timeout=2000):
        ...
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_message_list.py -v`

**Passo 3 — implementar** com `QListView` mais um `QAbstractListModel` e um delegate — nunca `QListWidget` com um item de interface por mensagem. A paginação (`storage.list_messages(offset, limit)`) carrega sob demanda conforme a rolagem.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_message_list.py -v`

**Passo 5 — commit:** `git commit -am "feat(ui): virtualized message list with density options"`

---

### T-36 — Temas claro e escuro seguindo o sistema

**Arquivos:**
- Criar: `pymail_client/ui/styles.py`
- Criar: `assets/themes/light.qss`, `assets/themes/dark.qss`
- Criar: `assets/icons/*.svg`
- Criar: `tests/test_themes.py`
- Requisitos: RF-UI-06, RNF-A11Y-01 · CA-RF-UI-06-1

**Passo 1 — escrever o teste que falha**

```python
def test_follows_system_color_scheme(main_window, qtbot, monkeypatch) -> None:
    """RF-UI-06."""
    monkeypatch.setattr(QGuiApplication.styleHints(), "colorScheme",
                        lambda: Qt.ColorScheme.Dark)
    main_window.apply_theme()
    assert main_window.current_theme() == "dark"


def test_manual_override_beats_system(main_window, monkeypatch) -> None:
    """CA-RF-UI-06-1."""
    monkeypatch.setattr(QGuiApplication.styleHints(), "colorScheme",
                        lambda: Qt.ColorScheme.Dark)
    main_window.set_theme_preference("light")
    assert main_window.current_theme() == "light"


def test_override_persists_across_restart(main_window, qtbot) -> None:
    main_window.set_theme_preference("dark")
    assert build_main_window().current_theme() == "dark"


def test_scheme_change_applies_without_restart(main_window, qtbot) -> None:
    """CA-RF-UI-06-1: sem reiniciar e sem recarregar a lista."""
    before = main_window.message_list.row_count()
    main_window.on_color_scheme_changed(Qt.ColorScheme.Dark)
    assert main_window.current_theme() == "dark"
    assert main_window.message_list.row_count() == before


def test_every_token_resolves_in_both_stylesheets() -> None:
    """Erro silencioso comum: uma cor definida só no tema claro."""
    assert set(load_tokens("light")) == set(load_tokens("dark"))


def test_contrast_meets_aa_in_both_themes() -> None:
    """RNF-A11Y-01: 4.5:1 para texto normal, verificado por cálculo."""
    for theme in ("light", "dark"):
        for pair in TEXT_ON_SURFACE_PAIRS:
            assert contrast_ratio(*resolve(theme, pair)) >= 4.5, (theme, pair)
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_themes.py -v`

**Passo 3 — implementar** `styles.py` sobre os tokens de `04-ui-ux.md` §2: um dicionário de tokens por tema, renderizado em QSS por interpolação, com `QStyleHints.colorSchemeChanged` conectado. Os ícones SVG são monocromáticos e recoloridos pelo QSS.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_themes.py -v`

**Passo 5 — commit:** `git commit -am "feat(ui): adaptive light/dark themes from design tokens"`

---

## M6 — Robustez, desempenho e entrega

### T-37 — Logs com redação e exportação de diagnóstico

**Arquivos:**
- Criar: `pymail_client/core/logging_setup.py`
- Criar: `tests/test_logging_redaction.py`
- Requisitos: RF-SET-04, RNF-SEC-01, RNF-PRIV-02 · CA-RF-SET-04-1

**Passo 1 — escrever o teste que falha**

```python
def test_no_secret_ever_reaches_the_logs(exercised_app_logs) -> None:
    """CA-RF-SET-04-1: varredura sobre os logs de uma execução que faz login,
    lê e envia. Falha se qualquer valor sensível aparecer."""
    contents = exercised_app_logs.read_all()
    for secret in (exercised_app_logs.password, exercised_app_logs.oauth_token):
        assert secret not in contents
    assert exercised_app_logs.message_body[:40] not in contents
    assert str(exercised_app_logs.attachment_path) not in contents


def test_redaction_filter_covers_all_handlers(app_with_logging) -> None:
    """Redigir em um handler e esquecer outro é o erro comum."""
    for handler in app_with_logging.logger.handlers:
        assert isinstance(handler.filters[0], RedactionFilter)


def test_diagnostics_export_is_scrubbed(diagnostics_export) -> None:
    assert diagnostics_export.password not in diagnostics_export.archive_text


def test_no_telemetry_endpoint_is_ever_contacted(network_recorder) -> None:
    """RNF-PRIV-02: zero telemetria. Verificado por ausência, não por confiança."""
    run_full_session()
    assert network_recorder.hosts_outside(["127.0.0.1"]) == []
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_logging_redaction.py -v`

**Passo 3 — implementar** `RedactionFilter` aplicado a **todos** os handlers na criação, mais rotação de arquivo. A exportação de diagnóstico monta um arquivo com versões, sistema, configuração (sem credenciais) e logs já redigidos.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_logging_redaction.py -v`

**Passo 5 — commit:** `git commit -am "feat(diagnostics): redacting logs and scrubbed diagnostic export"`

---

### T-38 — Detecção e recuperação de banco corrompido

**Arquivos:**
- Modificar: `pymail_client/core/storage.py`, `pymail_client/core/bootstrap.py`
- Criar: `tests/test_corruption_recovery.py`
- Requisitos: RF-SET-05, RNF-REL-02 · CA-RF-SET-05-1

**Passo 1 — escrever o teste que falha**

```python
def test_truncated_database_is_detected(corruption_fixture) -> None:
    corruption_fixture.truncate()
    assert corruption_fixture.storage.integrity_check() is False


def test_outbox_is_exported_before_any_repair(corruption_fixture) -> None:
    """CA-RF-SET-05-1: o dado do usuário tem prioridade sobre o cache."""
    corruption_fixture.seed_outbox(3)
    corruption_fixture.recover()

    exported = json.loads(corruption_fixture.export_path.read_text(encoding="utf-8"))
    assert len(exported["outbox"]) == 3


def test_corrupt_file_is_renamed_never_deleted(corruption_fixture) -> None:
    """Nunca destruir a evidência."""
    corruption_fixture.recover()
    assert corruption_fixture.corrupt_backup_path.exists()


def test_recovery_rebuilds_cache_from_scratch(corruption_fixture) -> None:
    corruption_fixture.recover()
    assert corruption_fixture.storage.migrate() == SCHEMA_VERSION
    corruption_fixture.sync()
    assert corruption_fixture.storage.count_messages() > 0     # RNF-REL-02


def test_user_is_notified_in_plain_language(corruption_fixture) -> None:
    notice = corruption_fixture.recover().notice
    assert notice.export_path and notice.backup_path
    assert not notice.message.startswith("sqlite3.")
```

**Passo 2 — rodar e verificar que falha:** `python -m pytest tests/test_corruption_recovery.py -v`

**Passo 3 — implementar** a ordem obrigatória de `03-modelo-de-dados.md` §8.2: detectar → **exportar antes de reparar** → renomear (jamais apagar) → recriar → ressincronizar → notificar.

**Passo 4 — rodar e verificar que passa:** `python -m pytest tests/test_corruption_recovery.py -v`

**Passo 5 — commit:** `git commit -am "feat(recovery): detect corruption, preserve user data, rebuild cache"`

---

### T-39 — Instrumento de desempenho: o guardião da interface que não trava

Esta é a tarefa que sustenta a afirmação central do projeto. Se ela for feita mal, as outras não importam.

**Arquivos:**
- Criar: `tests/test_gui_never_blocks.py`
- Criar: `tests/perf/conftest.py`
- Criar: `tests/test_perf_budgets.py`
- Requisitos: RNF-PERF-01, RNF-PERF-02, RNF-PERF-03, RNF-PERF-04 · CA-RNF-PERF-01-1

**Passo 1 — escrever o teste que falha**

`tests/test_gui_never_blocks.py`:

```python
def test_gui_thread_never_blocks_during_full_sync(qtbot, sync_fixture) -> None:
    """CA-RNF-PERF-01-1 — a afirmação central do projeto.

    O QTimer dispara na thread principal. Se a thread principal estiver
    bloqueada, o disparo atrasa exatamente a duração do bloqueio. Logo, o
    intervalo entre disparos consecutivos mede o pior bloqueio observado.
    """
    gaps: list[float] = []
    last = time.monotonic()

    def probe() -> None:
        nonlocal last
        now = time.monotonic()
        gaps.append(now - last)
        last = now

    watchdog = QTimer()
    watchdog.setTimerType(Qt.TimerType.PreciseTimer)
    watchdog.setInterval(10)
    watchdog.timeout.connect(probe)
    watchdog.start()

    sync_fixture.start_sync_of(5_000)
    qtbot.waitUntil(lambda: sync_fixture.finished, timeout=120_000)
    watchdog.stop()

    samples = gaps[1:]                      # descarta a primeira amostra (aquecimento)
    worst = max(samples)
    assert worst < 0.100, (
        f"thread da GUI bloqueou por {worst * 1000:.0f} ms "
        f"(pior amostra de {len(samples)})"
    )
```

Escreva o teste **antes** de qualquer otimização, rode-o e veja-o falhar. Um teste de desempenho que nunca falhou não prova nada.

**Passo 2 — rodar e verificar que falha, e ver por quê**

```powershell
python -m pytest tests/test_gui_never_blocks.py -v
```

Esperado: falha com um valor de bloqueio concreto. **Registre esse número no commit** — ele é a linha de base do projeto. Se o teste passar de primeira, ele está mal instrumentado: verifique se a sincronização realmente está rodando (a fixture precisa produzir trabalho real) antes de concluir que a interface está boa.

**Por que esta abordagem funciona, e qual é o limite dela.** `QTimer` só executa quando a thread principal volta ao laço de eventos; um bloqueio de 300 ms aparece como um intervalo de 300 ms entre disparos. Os limites: (a) só detecta bloqueios maiores que o intervalo do timer, aqui 10 ms; (b) não diz *qual* chamada bloqueou — para isso, complemente com `sys.setprofile` ou `cProfile` na thread principal quando a asserção falhar; (c) em CI compartilhado e ruidoso, a medição sofre interferência de escalonamento. Para (c), **não aumente o limite de 100 ms** — a saída correta é rodar o pior caso com margem, reportar a distribuição e, se necessário, marcar o teste como `@pytest.mark.slow` e executá-lo em um trabalho dedicado de CI, nunca removê-lo da suíte.

Use `time.monotonic()` e nunca `time.time()`: o relógio de parede pode recuar por ajuste de NTP e produzir um intervalo negativo ou distorcido.

**Passo 3 — escrever os testes de orçamento**

`tests/test_perf_budgets.py`:

```python
@pytest.mark.slow
def test_cold_start_under_1500ms(perf_app) -> None:
    """RNF-PERF-02."""
    assert perf_app.measure_cold_start() < 1.5


@pytest.mark.slow
def test_list_of_10k_messages_populates_under_500ms(populated_storage) -> None:
    assert populated_storage.measure_list_load(limit=10_000) < 0.5


@pytest.mark.slow
def test_cached_message_opens_under_150ms(populated_storage) -> None:
    """RNF-PERF-03."""
    assert populated_storage.measure_open_cached_message() < 0.150


@pytest.mark.slow
def test_search_50k_under_100ms(seeded_storage_50k) -> None:
    """RNF-PERF-04, com margem de 3x em CI."""
    assert seeded_storage_50k.measure_search("nota fiscal") < 0.300
```

**Passo 4 — rodar e verificar que passa**

```powershell
python -m pytest tests/test_gui_never_blocks.py -v
python -m pytest tests/test_perf_budgets.py -v -m slow
```

**Passo 5 — commit**

```powershell
git add tests/test_gui_never_blocks.py tests/test_perf_budgets.py tests/perf/
git commit -m "test(perf): GUI-blocking watchdog proving RNF-PERF-01 (baseline 12 ms)"
```

Substitua `12 ms` pelo valor real medido. O número no commit é o registro histórico do desempenho naquele ponto.

---

### T-40 — Empacotamento e medição de tamanho

**Arquivos:**
- Criar: `packaging/pymail.spec`
- Criar: `packaging/build.ps1`, `packaging/build.sh`
- Criar: `docs/packaging-sizes.md`
- Requisitos: RNF-COMP-01, RNF-PACK-01, RNF-PACK-02 · CA-RNF-PACK-01-1

**Passo 1 — escrever o script de medição primeiro**

O critério de aceite exige números medidos, não estimados. O script mede o artefato e grava em `docs/packaging-sizes.md`.

```powershell
# packaging/build.ps1
python -m PyInstaller packaging/pymail.spec --noconfirm --clean
$size = (Get-ChildItem -Recurse dist/pymail | Measure-Object -Property Length -Sum).Sum
"Windows: {0:N1} MB" -f ($size / 1MB) | Tee-Object -Append docs/packaging-sizes.md
```

**Passo 2 — escrever um teste de fumaça que falha sem o pacote**

```python
def test_packaged_app_starts_and_shows_window(packaged_app) -> None:
    """RNF-PACK-02: sem privilégios administrativos."""
    assert packaged_app.launch_and_wait_for_window(timeout_s=30) == 0
```

Escreva um teste que **execute o binário empacotado** e verifique que a janela aparece — empacotamento quebra de formas que nenhum teste unitário captura (módulo Qt faltando, recurso não incluído, import dinâmico não detectado pelo PyInstaller).

**Passo 3 — implementar o `spec`**

`packaging/pymail.spec` deve excluir os módulos Qt não utilizados para que o custo do motor de renderização fique visível em vez de diluído: gere duas medições, **com** e **sem** `QtWebEngine`, e registre a diferença em `docs/packaging-sizes.md`. É exatamente isso que `CA-RNF-PACK-01-1` pede.

Inclua em `datas` os diretórios `assets/themes` e `assets/icons` — recursos externos não são detectados automaticamente e é o erro mais comum de empacotamento deste projeto.

**Passo 4 — rodar e registrar os números**

```powershell
pwsh packaging/build.ps1
Get-Content docs/packaging-sizes.md
```

Esperado: `docs/packaging-sizes.md` com o tamanho real por plataforma. **Atualize também `01-requisitos.md` §6** para substituir a estimativa de 150–200 MB pelo valor medido, e marque o item B-02 do backlog de `02-arquitetura.md` §11 como resolvido.

**Passo 5 — commit**

```powershell
git add packaging/ docs/packaging-sizes.md
git commit -m "build(packaging): PyInstaller artifacts with measured sizes"
```

---

### T-41 — Portões de cobertura, lint e integração contínua

**Arquivos:**
- Criar: `.github/workflows/ci.yml`
- Modificar: `pyproject.toml`
- Requisitos: RNF-MAINT-01, RNF-MAINT-02

**Passo 1 — verificar a cobertura atual antes de fixar a meta**

```powershell
python -m pytest --cov=pymail_client.core --cov-report=term-missing
```

Registre o número. A meta de 80% sobre `core/` é de `RNF-MAINT-01`.

**Passo 2 — configurar o portão**

```toml
[tool.coverage.run]
source = ["pymail_client/core"]

[tool.coverage.report]
fail_under = 80
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",   # contratos e stubs de fase 2
]
```

**Passo 3 — escrever o workflow**

`.github/workflows/ci.yml` com matriz de `ubuntu-latest`, `windows-latest`, `macos-latest` e Python 3.11 e 3.12 (RNF-COMP-01, RNF-COMP-02), com `QT_QPA_PLATFORM=offscreen`. Detalhes em `06-estrategia-de-testes.md` §10. Pontos que quebram na prática e precisam de tratamento explícito:

- `keyring` não tem backend nos *runners* de CI. Os testes usam `FakeKeyring`; um teste de fumaça que exija keyring real deve ser marcado como `integration`.
- O teste de bloqueio da GUI é sensível a ruído: rode-o como trabalho separado, não com `-n auto`.
- `pytest-xdist` não pode ser usado nos testes que compartilham arquivo de banco.

**Passo 4 — rodar localmente o que o CI vai rodar**

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest -q --cov=pymail_client.core --cov-report=term-missing
```

Esperado: sem avisos do ruff, cobertura ≥ 80%, todos os testes passando.

**Passo 5 — commit**

```powershell
git add .github/ pyproject.toml
git commit -m "ci: coverage gate, lint and three-platform matrix"
```

---

## Ordem de execução e paralelismo

```text
M0  T-01 ─ T-02 ─ T-03 ─ T-04
M1  T-05 ─ T-06     T-07     T-08 ─ T-09
M2  T-10 ─ T-11 ─ T-12 ─ T-13 ─ T-14 ─ T-15 ─ T-16 ─ T-17 ─ T-18 ─ T-19
M3  T-20 ─ T-21 ─ T-22 ─ T-23
M4  T-24 ─ T-25 ─ T-26 ─ T-27 ─ T-28 ─ T-29 ─ T-30
M5  T-31 ─ T-32 ─ T-33 ─ T-34 ─ T-35 ─ T-36
M6  T-37 ─ T-38 ─ T-39 ─ T-40 ─ T-41
```

Dependências que **não** podem ser quebradas: `T-02` antes de tudo que toca o banco; `T-05` antes de `T-07` e `T-12`; `T-16` antes de `T-17`; `T-18` antes de `T-19`; `T-26` antes de `T-28`; `T-32` antes de `T-33` a `T-36`.

Paralelismo seguro para execução com subagentes:

| Faixa paralela | Tarefas | Observação |
|---|---|---|
| A | `T-05`, `T-06` | Sanitização e texto plano, mesmo módulo — execute em sequência se houver conflito de arquivo |
| B | `T-07`, `T-08`, `T-09` | Módulos distintos, sem dependência entre si |
| C | `T-20`, `T-21`, `T-22`, `T-23` | Independentes entre si, após M2 |
| D | `T-24`, `T-25` | Composição, sem rede |
| E | `T-31`, `T-33`, `T-34`, `T-35`, `T-36` | Componentes de UI distintos; `T-32` precisa vir antes |
| F | `T-37`, `T-38` | Independentes entre si |

**Não paralelize** `T-10` a `T-18`: todas tocam `storage.py` e `imap_client.py` e vão gerar conflitos de merge que custam mais do que o tempo economizado.

---

## Definição de pronto de cada tarefa

Uma tarefa só está concluída quando **todas** as condições valem:

1. O teste especificado foi escrito **antes** da implementação e foi visto falhar.
2. O teste passa, e passa de forma determinística — rodar cinco vezes seguidas produz o mesmo resultado.
3. `python -m ruff check .` e `python -m ruff format --check .` sem avisos.
4. Nenhum requisito adjacente foi quebrado: a suíte completa continua verde.
5. O commit foi feito com mensagem descritiva que referencia o requisito quando aplicável.
6. Se a tarefa revelou que a spec estava errada, **a spec foi corrigida no mesmo commit**. A spec é um documento vivo; código que contradiz a spec sem atualizá-la é dívida técnica criada no mesmo instante.

---

## Armadilhas conhecidas (leia antes de começar)

Cada item abaixo é um erro que esta arquitetura torna fácil de cometer e que custa caro depois.

| Armadilha | Por que acontece | Como evitar | Onde está o teste |
|---|---|---|---|
| Compartilhar a conexão IMAP entre threads | `imaplib` não é thread-safe; falha intermitente por cruzar respostas | Uma conexão por conta, criada **dentro** de `run()` da `AccountWorker` | T-18 |
| Esquecer `PRAGMA foreign_keys=ON` | É por conexão, não persistido no arquivo | Aplicar em `_conn()`, sempre | T-02, T-19 |
| Usar `BODY[]` em vez de `BODY.PEEK[]` | Marca como lida no servidor como efeito colateral | `BODY.PEEK[]` sempre | T-12 |
| Despejar a entrada do FTS5 junto com o corpo | Parece econômico; quebra a busca silenciosamente | Despejo em dois níveis: HTML primeiro, índice nunca | T-09 |
| Reconstruir tabela com `foreign_keys` ligado | O `DROP` dispara `CASCADE` e apaga dados do usuário | Desligar antes, religar depois | T-02 |
| Atalhos de letra ativos em campos de texto | `QShortcut` em contexto de janela ignora o foco | Guarda de foco explícita; `Esc` sem guarda | T-34 |
| `time.sleep()` em testes de tempo | Suíte lenta e instável | Tempo virtual (`advance_time`) no agendador | T-28 |
| Migrar antes de verificar integridade | Propaga a corrupção para um banco novo | `quick_check` antes de `migrate` | T-29, T-38 |
| Apagar rascunho ao excluir a conta | `CASCADE` alcança `outbox` | `ON DELETE SET NULL` em `outbox.account_id` | T-19, T-38 |
| Recursos não incluídos no pacote | `assets/` não é detectado automaticamente | Declarar em `datas` do `spec`; teste de fumaça do binário | T-40 |

---

## Rastreabilidade

A correspondência completa entre requisito, critério de aceite, forma de verificação e tarefa está em `docs/spec/01-requisitos.md` §8. Esta é a fonte da verdade: **nenhuma tarefa deste plano existe sem um requisito que a justifique**, e nenhum requisito de fase 1 existe sem uma tarefa que o implemente.

Critério de conclusão da fase 1: `docs/spec/01-requisitos.md` §9.

---

## Próximo passo

**Plano completo e salvo em `docs/plans/fase1.md`. Duas formas de executar:**

**1. Dirigido por subagentes (nesta sessão)** — um subagente novo por tarefa, com revisão entre tarefas e iteração rápida. Use `subagent-driven-development`. Recomendado para as tarefas de `M1` e `M2`, onde a revisão entre tarefas pega cedo os erros de afinidade de thread e de atomicidade.

**2. Sessão paralela (separada)** — abra uma nova sessão no worktree com a skill `executing-plans`, executando em lotes com pontos de verificação. Recomendado se você preferir revisar o progresso em blocos maiores.

Antes de começar: `T-05` (sanitização) e `T-39` (guardião de desempenho) são as duas tarefas que definem se o produto entrega o que promete. Se o tempo for curto, corte funcionalidade — **nunca** corte essas duas.


