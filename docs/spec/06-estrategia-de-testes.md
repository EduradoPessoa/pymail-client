# 06 — Estratégia de Testes

**Projeto:** PyMail Client · **Versão desta spec:** 1.0 · **Data:** 2026-09-25 · **Documentos correlatos:** `01-requisitos.md` (o quê e o quanto) · `02-arquitetura.md` (o como, ADR-001 a ADR-006, §4 afinidade, §5 contratos, §10 riscos) · `03-modelo-de-dados.md` (§8.3 testes de migração obrigatórios) · `04-ui-ux.md` · `05-seguranca-privacidade.md` · `../plans/fase1.md` (tarefas T-01 a T-41)

---

## 1. Princípios e pirâmide de testes

### 1.1 Níveis, o que cada um prova e o que cada um **não** prova

| Nível | Marcador | O que se testa | O que **não** se testa aqui | Dependências reais |
|---|---|---|---|---|
| 1. Puro | `unit` | `sanitize_html`, `build_match_query`, derivação de texto plano, parsing de envelope/cabeçalho, sanitização de nome de anexo, limpeza de parâmetros de rastreamento, cálculo de vítimas de LRU | O comportamento do `nh3`, do `tinycss2` ou do `unicode61` — são terceiros; se eles mudarem, o corpus hostil muda de resultado e é o corpus que avisa | `nh3`, `tinycss2` |
| 2. Persistência | `storage` | Migrações, FTS5 com acento, rollback de `store_body`, `ON DELETE CASCADE`, LRU em dois níveis, `quick_check`, `SQLITE_BUSY` | O motor SQLite, o comportamento de WAL sob filesystem de rede, a velocidade do disco | SQLite **real** em `tmp_path` |
| 3. Contrato de protocolo | `network` | `imap_client` e `smtp_client` contra servidor falso em socket: capabilities, `UID MOVE` vs `COPY`+`STORE`+`EXPUNGE`, `IDLE` e queda para polling, queda de conexão no meio da sincronização, TLS | Servidores reais (Gmail, Dovecot, Exchange) — isso é o nível 6 | socket TCP em `127.0.0.1` |
| 4. Concorrência e tarefas | `threaded` | `AccountWorker`, `TaskPool`, `CancellationToken`, afinidade de thread, propagação de erro por sinal, ausência de trabalho na thread da GUI | O escalonador do SO, a justiça entre threads, o desempenho absoluto | `QThreadPool` real |
| 5. Interface | `gui` | Atalhos e guarda de foco, modelo da lista, virtualização, troca de tema, estados vazios/erro, diálogo de confirmação de link | A pintura do Chromium, a aparência final, métricas de fonte, o anel de foco visível | `pytest-qt` com `QT_QPA_PLATFORM=offscreen` |
| 6. Integração real | `integration` | Paridade de protocolo contra Dovecot em contêiner; backend real de `keyring` | Não roda em PR de rotina; não é portão de merge | Docker |
| 7. Manual | — | Renderização visual, temas, memória, tamanho do pacote, operação sem mouse | Nada disso é automatizado, e o §11 assume isso explicitamente | Máquina com servidor gráfico |

**Regra da pirâmide neste projeto:** os níveis 1 a 3 concentram o volume (≈ 70% dos testes). O nível 5 é deliberadamente magro porque ADR-003 declara que executar `QWebEngineView` em ambiente headless é frágil; o esforço que normalmente iria para testes de renderização vai para o interceptor de rede (nível 3/5 híbrido), que é onde a privacidade é de fato imposta.

### 1.2 O que **não** se testa, em nenhum nível

| Não se testa | Por quê |
|---|---|
| O interior de `nh3`, `tinycss2`, `keyring`, `sqlite3`, Chromium | Testar terceiro é testar o fornecedor. Testamos **a nossa allowlist e o nosso passe de privacidade aplicados ao resultado deles** |
| Números absolutos de tempo em runner compartilhado | Produz falha intermitente e treina a equipe a ignorar vermelho (§10.6) |
| Ramos de plataforma que não existem no runner (keychain do macOS no Linux) | Cobertura de 0% neles é correta; persegui-la gera `# pragma: no cover` decorativo (§9.2) |
| Estados que o schema já torna impossíveis (`state='foo'` em `outbox`) | O `CHECK` é testado uma vez, por uma tentativa de `INSERT` inválida, e isso basta |
| Ramos de erro inalcançáveis por construção (`except` de biblioteca que não lança) | Se não há caminho executável, o teste só pode exercitar o mock |
| "O mock foi chamado com os argumentos X" para código nosso | Verifica a implementação, não o comportamento. Proibido no projeto, exceto em teste de dublê (nível 3), onde o registro do servidor **é** o comportamento observável |

### 1.3 Quando usar dublê e quando usar implementação real

| Fronteira | Decisão | Justificativa |
|---|---|---|
| `sqlite3` | **Real**, em `tmp_path` | É rápido (milissegundos), é determinístico, e é justamente o comportamento real que importa: `foreign_keys` por conexão, tokenizador `unicode61 remove_diacritics 2`, rollback transacional de DDL, `quick_check` em arquivo truncado. Um mock de `Storage` testaria a nossa própria suposição sobre o SQLite |
| `nh3` / `tinycss2` | **Real** | O comportamento real é o produto. O corpus hostil (§7) é o teste de regressão de segurança |
| `imaplib` / `smtplib` | **Cliente real, servidor falso em socket** | Um mock de `imaplib.IMAP4` não exercita: parsing de literal `{123}`, respostas *untagged* intercaladas com *tagged*, *quoting* de mailbox com espaço, codificação UTF-7 modificada, `BYE` no meio de um comando, timeout de socket. É exatamente aí que os bugs moram |
| `keyring` | **Dublê** (`FakeKeyring`), com um teste de integração separado | O cofre real tem efeito colateral no SO do desenvolvedor, comportamento diferente nas três plataformas e, no Linux de CI, muitas vezes não existe |
| `AuthProvider` | **Dublê** (`FakeAuthProvider`) | É o objeto de `CA-RF-ACC-04-1`: o teste exige que registrar um provider falso faça o app autenticar por ele sem alterar `ui/` nem `storage.py` |
| Relógio | **Dublê injetado** (`Clock`) | A janela de Undo Send não pode custar 10 s de suíte. Ver §6.5 e a lacuna L-08 |
| `QWebEngineView` | **Real quando o runner aguenta; asserção sobre o interceptor** | ADR-003: a asserção útil é sobre a lista de tentativas de requisição, não sobre o pixel |
| Rede externa | **Proibida** | Uma fixture de sessão instala um bloqueio de socket para qualquer destino que não seja `127.0.0.1`/`::1`. Teste que precise de rede externa é teste mal desenhado, e a rede do CI é instável por natureza |
| Sistema de arquivos | **Real**, em `tmp_path` | Barato e o comportamento real importa (permissões, caminhos com espaço, nome reservado no Windows) |
| Notificações do SO | **Dublê** | Não há como asserção confiável, e a notificação real atrapalha quem roda a suíte |

**Regra do dublê na fronteira errada.** Um dublê só é aceitável na fronteira de um sistema externo (SO, rede, tempo). Dublar um módulo nosso (`core/storage.py`, `core/security.py`, `core/tasks.py`) para testar outro módulo nosso é proibido: se `ui/` precisa de `storage`, o teste de `ui/` usa `Storage` real com banco vazio em `tmp_path` e um `FakeIncomingClient` para a rede. A dependência que `ui/` realmente tem é a rede e o tempo, não o banco.

**Regra da asserção vacuosa.** Todo teste cujo resultado esperado é "nada aconteceu" (zero requisições, zero conexões, zero linhas) precisa de um **controle positivo** no mesmo arquivo, provando que o instrumento detecta o evento quando ele ocorre. Sem isso, um instrumento quebrado transforma o teste em `assert True`. Exemplos: `test_watchdog_detects_induced_block` (§5.1), `test_recorder_detects_allowed_request` (§5.2), `test_interleaving_detector_fires_on_violation` (§5.3).

---

## 2. Ferramentas e configuração

### 2.1 Ferramentas

| Ferramenta | Papel | Observação |
|---|---|---|
| `pytest` | Executor | Mínimo `7.4` |
| `pytest-qt` | Laço de eventos, `qtbot`, sinais, `waitUntil` | Obrigatório para os níveis 4 e 5; também usado no nível 3 quando o cliente roda em `AccountWorker` |
| `pytest-cov` | Cobertura | Portão de 80% em `core/` (RNF-MAINT-01) |
| `pytest-timeout` | Teto por teste | Sem ele, um teste de concorrência travado pendura o job. Padrão 60 s; `perf` e `integration` com teto próprio |
| `pytest-xdist` | Paralelismo | Ver ressalva de §2.4 |
| `ruff` (`format` + `check`) | Formatação e análise estática | RNF-MAINT-02 |
| `mypy` | Tipagem estática | `core/` em modo estrito; `ui/` em modo normal |

**Não entram** dependências de relógio falso (`freezegun`) nem de mock de socket: o relógio é injetado por interface própria (`Clock`) e o socket é substituído por servidor falso real, o que é mais fiel e não adiciona dependência.

### 2.2 `pyproject.toml` — seções de teste, cobertura e qualidade

```toml
[project]
name = "pymail-client"
requires-python = ">=3.11"
dependencies = [
    "PySide6>=6.6",
    "nh3>=0.2.15",
    "tinycss2>=1.2",
    "keyring>=24.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-qt>=4.3",
    "pytest-cov>=4.1",
    "pytest-timeout>=2.2",
    "pytest-xdist>=3.4",
    "ruff>=0.4",
    "mypy>=1.8",
    "types-keyring",
]

# ─────────────────────────────── pytest ───────────────────────────────
[tool.pytest.ini_options]
minversion = "7.4"
testpaths = ["tests"]
addopts = [
    "-ra",
    "--strict-markers",
    "--strict-config",
    "--durations=15",
    "-p", "no:cacheprovider",
]
# Cada teste declara seu nível. Um teste sem marcador é um erro de configuração,
# e `--strict-markers` garante que um marcador desconhecido falhe em vez de sumir.
markers = [
    "unit: função pura, sem I/O, sem Qt",
    "storage: SQLite real em tmp_path",
    "network: servidor falso em socket (IMAP/SMTP)",
    "threaded: QThread/QThreadPool reais",
    "gui: pytest-qt; exige QT_QPA_PLATFORM=offscreen",
    "slow: mais de 1 s",
    "perf: asserção de tempo; não paralelizar, não rodar em runner ruidoso sem necessidade",
    "privacy: asserção de zero requisições de rede (CA-RNF-PRIV-01-1)",
    "integration: exige Docker; pulado quando indisponível",
    "serial: não pode rodar sob xdist (estado global, perf, Chromium)",
]
qt_api = "pyside6"
timeout = 60
timeout_method = "thread"

# ────────────────────────────── cobertura ─────────────────────────────
[tool.coverage.run]
branch = true
source = ["core", "ui"]
parallel = true
omit = [
    "*/tests/*",
    "*/__main__.py",
    "main.py",
]

[tool.coverage.report]
# Portão de RNF-MAINT-01: 80% em core/. O `--cov-fail-under` do CI aplica o
# mesmo número; este valor é a rede de segurança para execução local.
fail_under = 80
show_missing = true
skip_covered = false
exclude_also = [
    "if TYPE_CHECKING:",
    "if sys.platform",          # ramos de plataforma: ver §9.2
    "raise NotImplementedError",
    "class .*\\(Protocol\\):",
    "@(abc\\.)?abstractmethod",
]

[tool.coverage.html]
directory = "build/coverage-html"

[tool.coverage.json]
output = "build/coverage.json"

# ───────────────────────────── qualidade ──────────────────────────────
[tool.ruff]
line-length = 100
target-version = "py311"
src = ["."]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "RUF", "S", "PT"]
ignore = [
    "S101",    # assert é o mecanismo de teste
    "PT011",   # pytest.raises sem match: exigido nos testes de FTS5
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S105", "S106", "S107"]   # senhas falsas nos dublês

[tool.mypy]
python_version = "3.11"
warn_unused_configs = true
warn_redundant_casts = true
warn_unreachable = true
disallow_untyped_defs = true
no_implicit_optional = true
strict_equality = true

[[tool.mypy.overrides]]
module = ["core.*", "core.network.*"]
strict = true

[[tool.mypy.overrides]]
module = ["ui.*"]
disallow_untyped_defs = false
```

### 2.3 Variáveis de ambiente obrigatórias

```bash
# Linux e Windows, execução headless
QT_QPA_PLATFORM=offscreen
# Chromium dentro do contêiner/runner: sem sandbox e sem GPU
QTWEBENGINE_DISABLE_SANDBOX=1
QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage --disable-features=AudioServiceOutOfProcess"
# Silenciar ruído de Chromium/Qt que polui a saída e esconde falha real
QT_LOGGING_RULES="qt.webenginecontext.debug=false;qt.qpa.*=false"
# Nunca tocar no diretório de dados real do usuário (QStandardPaths test mode)
PYMAIL_TEST_MODE=1
# Isolamento de qualquer backend de keyring real, como segunda linha de defesa
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
# Reprodutibilidade do corpus gerado
PYMAIL_CORPUS_SEED=20260925
```

`QT_QPA_PLATFORM=offscreen` **não é um servidor gráfico**. Ele dá um *plugin* de plataforma sem janela: não há compositor, não há GPU, as métricas de fonte divergem das reais, `QWebEngineView` tem mais probabilidade de falhar na inicialização, e animações/rolagem não se comportam como num monitor. Consequência normativa: **nenhum teste automatizado pode afirmar sobre geometria de pixel, tempo de pintura ou aparência**. Tudo isso é procedimento manual (§11.2).

### 2.4 Ressalva sobre `pytest-xdist`

`-n auto` é usado no nível 1, 2 e 3. **Não é usado** em:

- testes de banco que compartilham arquivo entre testes (aqui não compartilham — cada teste tem seu `tmp_path` — mas a criação de índices FTS5 em paralelo com `SQLITE_BUSY` pode introduzir ruído de tempo);
- testes `perf`, que medem tempo e não podem disputar CPU;
- testes `gui` que inicializam Chromium (custo de memória por worker × N workers derruba o runner);
- testes `threaded` marcados `serial`.

Configuração de CI:

```bash
pytest -m "unit or storage or network" -n auto          # rápido, paralelo
pytest -m "threaded or gui" -n 2                        # Qt e Chromium
pytest -m "perf" -p no:xdist -n 0 --timeout=300         # job próprio
pytest -m "integration" -n 0                            # job próprio, Ubuntu
```

---

## 3. Estrutura de diretórios de testes

Espelha `02-arquitetura.md` §2 (um arquivo de teste por módulo de produção) e separa infraestrutura de teste (`fakes/`, `fixtures/`, `support/`) do teste em si.

```text
tests/
├── conftest.py                      # Fixtures globais: tmp storage, Qt, clock, bloqueio de rede externa
├── support/
│   ├── __init__.py
│   ├── clock.py                     # Clock (Protocol), RealClock, FakeClock — determinismo do Undo Send
│   ├── qt_utils.py                  # run_until(), process_events_until(), GuiBlockWatchdog
│   ├── net_guard.py                 # Bloqueio de sockets para destinos externos
│   ├── builders.py                  # Construtores: make_raw_message(), make_envelope(), make_eml()
│   └── assertions.py                # assert_no_forbidden_markup(), assert_zero_network_attempts()
├── fakes/
│   ├── __init__.py
│   ├── fake_keyring.py              # FakeKeyring: cofre em memória + registro de chamadas
│   ├── fake_incoming.py             # FakeIncomingClient: implementa IncomingMailClient (§5.1 de 02)
│   ├── fake_imap_server.py          # ThreadingTCPServer falando IMAP, com registro de comandos
│   ├── fake_smtp_server.py          # Servidor SMTP que conta conexões
│   ├── fake_auth_provider.py        # FakeAuthProvider para CA-RF-ACC-04-1
│   └── request_recorder.py          # RequestRecorder do interceptor de privacidade
├── fixtures/
│   ├── eml/
│   │   ├── benign/                  # Corpus benigno (§7)
│   │   ├── malicious/               # Corpus hostil exigido por CA-RF-RD-01-1 (§7)
│   │   ├── malformed/               # Cabeçalhos ausentes/malformados, charset exótico
│   │   ├── tracking/                # Imagens remotas, CSS remoto, beacons (§7)
│   │   └── tools/
│   │       └── build_corpus.py      # Gerador determinístico (semente fixa) do corpus volumoso
│   ├── protocol/
│   │   ├── uidvalidity_change.json  # Cenário de servidor (não é .eml) para CA-RF-MSG-04-1
│   │   └── drop_mid_sync.json       # Cenário de queda no meio da sincronização
│   ├── db/
│   │   └── v1_golden.db             # Banco na versão 1, com dados, para CA-RF-SET-03-1
│   └── perf/
│       └── corpus_50k.sql           # Geração do corpus de 50.000 mensagens (CA-RF-SRCH-02-1)
├── unit/
│   ├── test_sanitize_html.py            # Allowlist, tags/atributos/esquemas, corpus hostil
│   ├── test_sanitize_privacy.py         # Pixels, reescrita de recursos, data-*, parâmetros de rastreamento
│   ├── test_css_filter.py               # tinycss2: propriedades permitidas, expression(), url() remoto
│   ├── test_match_query.py              # build_match_query: escaping e neutralização (CA-RF-SRCH-05-1)
│   ├── test_plain_text.py               # Derivação de texto plano a partir de HTML (RF-RD-02)
│   ├── test_attachment_names.py         # Sanitização de nome de anexo (CA-RNF-SEC-04-1)
│   ├── test_message_parsing.py          # Cabeçalhos → HeaderEnvelope, datas, encodings, charset exótico
│   └── test_link_confirmation.py        # Host real vs texto exibido (CA-RF-RD-07-1)
├── security/
│   ├── test_keyring_credentials.py      # Nenhuma senha em banco/config/log (CA-RNF-SEC-01-1)
│   ├── test_keyring_lifecycle.py        # Remoção ao excluir conta (CA-RF-ACC-05-1), keyring indisponível
│   └── test_log_redaction.py            # CA-RF-SET-04-1: varredura de logs
├── storage/
│   ├── test_migrations.py               # 03-modelo-de-dados.md §8.3 e CA-RF-SET-03-1
│   ├── test_accounts_cascade.py         # CA-RF-ACC-05-1
│   ├── test_headers_bodies.py           # RF-MSG-01/02, transições de body_state
│   ├── test_fts_accent.py               # CA-RF-SRCH-01-1, parametrizado
│   ├── test_fts_query_safety.py         # CA-RF-SRCH-05-1, parametrizado
│   ├── test_store_body_atomicity.py     # CA-RF-SRCH-04-1, dois sentidos de falha
│   ├── test_index_consistency.py        # consulta de §5.5 de 03
│   ├── test_cache_eviction.py           # CA-RF-MSG-06-1, dois níveis
│   ├── test_corruption_recovery.py      # CA-RF-SET-05-1
│   ├── test_concurrency.py              # ADR-006: conexão por thread, SQLITE_BUSY
│   └── test_search_perf.py              # CA-RF-SRCH-02-1 (margem de 3× em CI)
├── network/
│   ├── test_incoming_contract.py        # Suíte de contrato parametrizada (§6.4)
│   ├── test_imap_headers_only.py        # CA-RF-MSG-01-1, zero FETCH de corpo
│   ├── test_imap_body_on_demand.py      # CA-RF-MSG-02-1
│   ├── test_imap_uidvalidity.py         # CA-RF-MSG-04-1
│   ├── test_imap_move.py                # CA-RF-ORG-01-1, CA-RF-ORG-05-1
│   ├── test_imap_idle_fallback.py       # RF-MSG-05: IDLE recusado → polling
│   ├── test_imap_drop_mid_sync.py       # CA-RF-MSG-08-1
│   ├── test_imap_thread_affinity.py     # ADR-001 (teste crítico, §5.3)
│   ├── test_imap_tls.py                 # CA-RNF-SEC-02-1
│   ├── test_smtp_undo_window.py         # CA-RF-SND-03-1, CA-RF-SND-03-2
│   ├── test_smtp_failure.py             # CA-RF-SND-05-1
│   └── test_smtp_requires_tls.py        # CA-RF-SND-07-1
├── tasks/
│   ├── test_account_worker.py           # Enfileiramento serial, cancelamento, sinais
│   ├── test_task_pool.py                # Trabalho sem estado compartilhado
│   ├── test_cancellation.py             # Cancelamento cooperativo e conclusão parcial
│   └── test_no_gui_thread_work.py       # Base do CA-RNF-PERF-01-1
├── gui/
│   ├── conftest.py                      # Fixtures de janela, qtbot, tema, skip quando Chromium falha
│   ├── test_shortcuts.py                # CA-RF-UI-03-1, CA-RF-UI-04-1
│   ├── test_message_list_model.py       # CA-RF-UI-05-1 (virtualização)
│   ├── test_theme.py                    # CA-RF-UI-06-1
│   ├── test_sidebar.py                  # RF-UI-02
│   ├── test_states.py                   # RF-UI-07, RF-UI-08
│   ├── test_interceptor.py              # CA-RF-RD-06-1, CA-RNF-PRIV-01-1 (nível Chromium)
│   └── test_reader_html.py              # Asserções sobre HTML sanitizado entregue ao view, sem Chromium
├── perf/
│   ├── test_gui_never_blocks.py         # CA-RNF-PERF-01-1 (teste crítico, §5.1)
│   └── test_startup_and_open.py         # RNF-PERF-02/03 (relatório, sem portão)
├── privacy/
│   └── test_zero_network_requests.py    # CA-RNF-PRIV-01-1, corpus completo (§5.2)
├── integration/
│   ├── conftest.py                      # Skip quando Docker indisponível (§8)
│   ├── test_dovecot_contract.py         # Mesma suíte de contrato, contra Dovecot real
│   └── test_real_keyring.py             # Backend real de keyring, informativo
└── manual/
    └── procedures.md                    # MV-01 a MV-05 de §11, com espaço para evidência
```

---

## 4. Dublês e servidores falsos

### 4.1 `tests/fakes/fake_keyring.py`

Substitui o cofre do SO. Registra **toda** chamada, para que o teste de `CA-RNF-SEC-01-1` possa afirmar tanto o conteúdo do cofre quanto a ausência de tentativas em outros lugares.

```python
from __future__ import annotations

import keyring
import keyring.errors
import pytest


class FakeKeyring:
    """Cofre em memória. Nenhum teste toca o keyring real do SO."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []
        # Permite simular ausência de backend (Linux sem secret service).
        self.available = True
        self.fail_on_write = False
        self.read_count = 0

    # ── API no formato do módulo `keyring` ──
    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        self.read_count += 1
        if not self.available:
            raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        if not self.available:
            raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")
        if self.fail_on_write:
            raise keyring.errors.KeyringError("cofre bloqueado")
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        if not self.available:
            raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")
        if (service, username) in self._store:
            del self._store[(service, username)]
        else:
            raise keyring.errors.PasswordDeleteError("credencial inexistente")

    # ── Apoio ao teste ──
    @property
    def stored_secrets(self) -> list[str]:
        return list(self._store.values())

    def has_entry_for(self, username: str) -> bool:
        return any(u == username for (_s, u) in self._store)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    """Instala o FakeKeyring no lugar do módulo `keyring` usado por core.security."""
    fake = FakeKeyring()
    monkeypatch.setattr(keyring, "get_password", fake.get_password, raising=True)
    monkeypatch.setattr(keyring, "set_password", fake.set_password, raising=True)
    monkeypatch.setattr(keyring, "delete_password", fake.delete_password, raising=True)
    return fake
```

Uso no teste central de `RNF-SEC-01`:

```python
SENTINEL = "S3nh4-Do-Teste-Nao-Pode-Vazar-7f3a"


def test_no_password_written_to_database(tmp_path, fake_keyring, storage, account_config):
    """CA-RNF-SEC-01-1 — a senha não aparece no banco em claro nem em forma reversível."""
    from core.security import set_credential

    set_credential(account_config, SENTINEL)
    account_id = storage.upsert_account(account_config)

    payload = (tmp_path / "pymail.db").read_bytes()
    assert SENTINEL.encode() not in payload
    # Forma "reversível": base64 e hex do valor também não podem aparecer.
    import base64

    assert base64.b64encode(SENTINEL.encode()) not in payload
    assert SENTINEL.encode().hex().encode() not in payload
    # E o schema não tem coluna capaz de guardá-la (03-modelo-de-dados.md §4).
    columns = {
        row[1]
        for table in ("accounts", "folders", "messages", "bodies", "outbox")
        for row in storage._conn_for_current_thread().execute(f"PRAGMA table_info({table})")
    }
    assert not any("pass" in c or "secret" in c or "token" in c for c in columns)
    assert fake_keyring.stored_secrets == [SENTINEL]
```

### 4.2 `tests/fakes/fake_incoming.py`

Implementa o protocolo `IncomingMailClient` de `02-arquitetura.md` §5.1 com dados em memória. É o dublê de nível alto, usado por `ui/`, `core/tasks.py` e pelos testes de desempenho — rápido, determinístico, e permite injetar falhas sem falar protocolo.

```python
from __future__ import annotations

import threading
from datetime import datetime, timezone

from core.errors import NetworkError, NotFoundError
from core.network.base import (
    AttachmentMeta,
    FolderStatus,
    HeaderEnvelope,
    RawMessage,
    RemoteFolder,
)


class FakeIncomingClient:
    """IncomingMailClient em memória (contrato de 02-arquitetura.md §5.1).

    Registra chamadas para que as asserções sejam sobre comportamento observável:
    quais UIDs foram baixados, quantas vezes, em que ordem.
    """

    def __init__(
        self,
        folders: dict[str, list[tuple[str, bytes]]] | None = None,
        *,
        capabilities: frozenset[str] = frozenset({"IMAP4rev1", "UIDPLUS", "MOVE", "IDLE"}),
        body_latency_s: float = 0.0,
    ) -> None:
        self.folders = folders or {"INBOX": []}
        self._capabilities = capabilities
        self._body_latency_s = body_latency_s
        self._lock = threading.Lock()

        self.connected = False
        self.selected: str | None = None
        self.uidvalidity = 1
        self.calls: list[tuple[str, tuple]] = []
        self.fetched_body_uids: list[str] = []
        self.moved: list[tuple[tuple[str, ...], str]] = []
        self.flag_changes: list[tuple[tuple[str, ...], tuple[str, ...], bool]] = []
        self.fail_next: dict[str, Exception] = {}
        self.drop_after_n_calls: int | None = None

    # ── instrumentação ──
    def _record(self, name: str, *args) -> None:
        with self._lock:
            self.calls.append((name, args))
            if self.drop_after_n_calls is not None and len(self.calls) >= self.drop_after_n_calls:
                self.drop_after_n_calls = None
                self.connected = False
                raise NetworkError("conexão encerrada pelo servidor")
        if name in self.fail_next:
            raise self.fail_next.pop(name)

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def count(self, name: str) -> int:
        return self.call_names().count(name)

    # ── IncomingMailClient ──
    def connect(self) -> None:
        self._record("connect")
        self.connected = True

    def close(self) -> None:
        self._record("close")
        self.connected = False

    def list_folders(self) -> list[RemoteFolder]:
        self._record("list_folders")
        self._require_connected()
        return [RemoteFolder(name=n, delimiter="/", kind="inbox" if n == "INBOX" else "custom")
                for n in self.folders]

    def select_folder(self, name: str) -> FolderStatus:
        self._record("select_folder", name)
        self._require_connected()
        if name not in self.folders:
            raise NotFoundError(name)
        self.selected = name
        return FolderStatus(
            exists=len(self.folders[name]),
            uidvalidity=self.uidvalidity,
            uidnext=len(self.folders[name]) + 1,
            unread=sum(1 for _uid, raw in self.folders[name] if b"\\Seen" not in raw[:200]),
        )

    def fetch_headers(self, start_uid: int, limit: int) -> list[HeaderEnvelope]:
        self._record("fetch_headers", start_uid, limit)
        self._require_connected()
        assert self.selected is not None, "fetch_headers exige select_folder antes"
        out = []
        for uid, raw in self.folders[self.selected]:
            if int(uid) < start_uid:
                continue
            out.append(self._envelope(uid, raw))
            if len(out) >= limit:
                break
        return out

    def fetch_body(self, remote_id: str) -> RawMessage:
        self._record("fetch_body", remote_id)
        self._require_connected()
        self.fetched_body_uids.append(remote_id)
        return RawMessage(remote_id=remote_id, raw_bytes=self._raw(remote_id))

    def fetch_attachment(self, remote_id: str, part_id: str) -> bytes:
        self._record("fetch_attachment", remote_id, part_id)
        return b"conteudo-do-anexo"

    def list_attachments(self, remote_id: str) -> list[AttachmentMeta]:
        self._record("list_attachments", remote_id)
        return []

    def set_flags(self, remote_ids, flags, add: bool) -> None:
        self._record("set_flags", tuple(remote_ids), tuple(flags), add)
        self.flag_changes.append((tuple(remote_ids), tuple(flags), add))

    def move(self, remote_ids, destination: str) -> None:
        self._record("move", tuple(remote_ids), destination)
        self.moved.append((tuple(remote_ids), destination))

    def supports(self, capability: str) -> bool:
        return capability.upper() in self._capabilities

    def wait_for_changes(self, timeout_s: float) -> list[str]:
        self._record("wait_for_changes", timeout_s)
        return []

    # ── apoio ──
    def _require_connected(self) -> None:
        if not self.connected:
            raise NetworkError("cliente não conectado")

    def _raw(self, remote_id: str) -> bytes:
        assert self.selected is not None
        for uid, raw in self.folders[self.selected]:
            if uid == remote_id:
                return raw
        raise NotFoundError(remote_id)

    def _envelope(self, uid: str, raw: bytes) -> HeaderEnvelope:
        return HeaderEnvelope(
            remote_id=uid,
            message_id=f"<{uid}@exemplo.com>",
            subject=f"Assunto {uid}",
            from_name="Remetente",
            from_addr="remetente@exemplo.com",
            to_addrs=("eu@exemplo.com",),
            cc_addrs=(),
            date_utc=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
            size_bytes=len(raw),
            flags=frozenset(),
            has_attachments=False,
            in_reply_to=None,
            references=(),
        )
```

### 4.3 Servidor IMAP falso em socket — `tests/fakes/fake_imap_server.py`

Fala o subconjunto de IMAP que o cliente usa e, crucialmente, **registra todos os comandos recebidos**. É esse registro que torna verificáveis `CA-RF-MSG-01-1` (zero `FETCH` de corpo), `CA-RF-MSG-02-1` (exatamente um `FETCH` de corpo), `CA-RF-ORG-01-1` (`UID MOVE` e não `COPY`), `CA-RF-ORG-05-1` (`EXPUNGE` que falha) e o comportamento de `IDLE`.

Capacidades exigidas do servidor falso:

| Recurso | Como é pedido | Serve a |
|---|---|---|
| Registro de todos os comandos | `server.commands` (lista com `name`, `args`, `raw`) | CA-RF-MSG-01-1, 02-1, ORG-01-1, ORG-05-1 |
| Recusar `IDLE` | `FakeImapServer(refuse_idle=True)` — `IDLE` responde `NO` e some do `CAPABILITY` | RF-MSG-05 (queda para polling) |
| Mudar `UIDVALIDITY` | `server.set_uidvalidity("INBOX", 42)` | CA-RF-MSG-04-1 |
| Cair no meio da sincronização | `server.drop_after_n_commands(3)` fecha o socket após o N-ésimo comando | CA-RF-MSG-08-1 |
| Sem `MOVE` | `capabilities` sem `MOVE` | CA-RF-ORG-01-1 (caminho alternativo) |
| `EXPUNGE` que falha | `server.fail_command("EXPUNGE", "NO [SERVERBUG] expunge failed")` | CA-RF-ORG-05-1 |
| Detectar uso concorrente da conexão | `server.hold_response("FETCH")` + `server.concurrent_use_detected` | ADR-001 (§5.3) |
| TLS com certificado autoassinado | `FakeImapServer(tls_cert=...)` | CA-RNF-SEC-02-1 |

```python
from __future__ import annotations

import socket
import socketserver
import threading
from dataclasses import dataclass, field


@dataclass
class ImapCommand:
    tag: str
    name: str            # maiúsculo, sem o prefixo UID
    raw: str             # linha crua, para asserções de forma
    is_uid: bool = False
    literal_bytes: int = 0


@dataclass
class FakeMailbox:
    name: str
    messages: list[tuple[int, frozenset[str], bytes]] = field(default_factory=list)
    uidvalidity: int = 1
    uidnext: int = 1


class _Handler(socketserver.StreamRequestHandler):
    """Um handler por conexão. Conversa IMAP linha a linha (literais são aceitos crus)."""

    server: "FakeImapServer"

    def handle(self) -> None:
        srv = self.server
        srv.connection_count += 1
        tag_counter = 0
        selected: FakeMailbox | None = None
        in_idle = False

        self._send("* OK [CAPABILITY %s] PyMail Fake IMAP ready" % srv.capability_string())

        while True:
            line = self.rfile.readline()
            if not line:
                break
            raw = line.decode("utf-8", "replace").rstrip("\r\n")
            parts = raw.split(" ", 2)
            if len(parts) < 2:
                continue
            tag, verb = parts[0], parts[1].upper()
            rest = parts[2] if len(parts) > 2 else ""

            is_uid = verb == "UID"
            name = rest.split(" ", 1)[0].upper() if is_uid else verb
            args = rest.split(" ", 1)[1] if is_uid and " " in rest else rest

            cmd = ImapCommand(tag=tag, name=name, raw=raw, is_uid=is_uid)
            with srv._lock:
                srv.commands.append(cmd)
                srv.command_event.set()
                # Detecção determinística de uso concorrente: uma resposta
                # deliberadamente retida é a prova de que outra thread emitiu
                # comando na MESMA conexão antes de a primeira terminar.
                srv.inflight += 1
                if srv.inflight > 1:
                    srv.concurrent_use_detected = True
                hold = srv._hold.get(name)

            if hold is not None:
                hold.wait(timeout=5.0)     # o teste decide quando liberar

            try:
                in_idle = self._dispatch(srv, name, args, tag, selected, in_idle,
                                         is_uid=is_uid, raw=raw)
                if name == "SELECT":
                    selected = srv.mailboxes[args.strip('"')]
            except _DropConnection:
                break
            except _CommandFailed as exc:
                self._send(f"{tag} {exc.response}")
            finally:
                with srv._lock:
                    srv.inflight -= 1

        with srv._lock:
            srv.connection_count -= 1

    def _dispatch(self, srv, name, args, tag, selected, in_idle, *, is_uid, raw) -> bool:
        if name in srv.fail_next:
            response = srv.fail_next.pop(name)
            raise _CommandFailed(response)

        if srv.drop_after_n is not None and len(srv.commands) >= srv.drop_after_n:
            srv.drop_after_n = None
            raise _DropConnection()

        if name == "CAPABILITY":
            self._send(f"* CAPABILITY {srv.capability_string()}")
            self._send(f"{tag} OK CAPABILITY completed")
        elif name == "LOGIN":
            srv.logins.append(args)
            self._send(f"{tag} OK LOGIN completed")
        elif name in ("SELECT", "EXAMINE"):
            mb = srv.mailboxes[args.strip('"')]
            self._send(f"* {len(mb.messages)} EXISTS")
            self._send(f"* 0 RECENT")
            self._send(f"* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)")
            self._send(f"* OK [UIDVALIDITY {mb.uidvalidity}] UIDs valid")
            self._send(f"* OK [UIDNEXT {mb.uidnext}] Predicted next UID")
            self._send(f"{tag} OK [READ-WRITE] SELECT completed")
        elif name == "LIST":
            for mb in srv.mailboxes.values():
                self._send(f'* LIST (\\HasNoChildren) "/" "{mb.name}"')
            self._send(f"{tag} OK LIST completed")
        elif name == "FETCH":
            self._send_headers(srv, selected, args)
            self._send(f"{tag} OK FETCH completed")
        elif name == "SEARCH":
            self._send(f"* SEARCH {' '.join(str(u) for u, _f, _r in selected.messages)}")
            self._send(f"{tag} OK SEARCH completed")
        elif name == "STORE":
            self._send(f"{tag} OK STORE completed")
        elif name == "MOVE":
            self._send(f"{tag} OK MOVE completed")
        elif name == "COPY":
            self._send(f"{tag} OK [COPYUID 1 1 1] COPY completed")
        elif name == "EXPUNGE":
            self._send("* 1 EXPUNGE")
            self._send(f"{tag} OK EXPUNGE completed")
        elif name == "APPEND":
            self._send(f"{tag} OK [APPENDUID 1 99] APPEND completed")
        elif name == "IDLE":
            if srv.refuse_idle or "IDLE" not in srv.capabilities:
                self._send(f"{tag} NO [UNAVAILABLE] IDLE not supported here")
            else:
                srv.idle_entered.set()
                self._send("+ idling")
                # Fica em IDLE até o teste liberar ou o cliente enviar DONE.
                srv.idle_release.wait(timeout=srv.idle_timeout_s)
                self._send("* 1 EXISTS")
                self._send(f"{tag} OK IDLE terminated")
                return False
        elif name == "NOOP":
            self._send(f"{tag} OK NOOP completed")
        elif name == "LOGOUT":
            self._send("* BYE PyMail Fake IMAP logging out")
            self._send(f"{tag} OK LOGOUT completed")
        else:
            self._send(f"{tag} BAD unknown command {name}")
        return in_idle

    def _send_headers(self, srv, selected: FakeMailbox | None, args: str) -> None:
        fields = args.upper()
        for uid, flags, _raw in selected.messages:
            flag_str = " ".join(sorted(flags))
            if "BODY.PEEK[]" in fields or "BODY[]" in fields:
                srv.body_fetch_uids.append(uid)          # ← prova de CA-RF-MSG-01-1/02-1
                payload = f"BODY[] {{{len(_raw)}}}"
                self._send(f"* {uid} FETCH (UID {uid} FLAGS ({flag_str}) {payload})")
                self.wfile.write(_raw)
            elif "BODYSTRUCTURE" in fields or "ENVELOPE" in fields:
                self._send(
                    f"* {uid} FETCH (UID {uid} FLAGS ({flag_str}) "
                    f'INTERNALDATE "25-Sep-2026 12:00:00 +0000" RFC822.SIZE 2048 '
                    f"ENVELOPE (NIL NIL NIL NIL NIL NIL NIL NIL NIL NIL) "
                    f"BODYSTRUCTURE (\"TEXT\" \"PLAIN\" NIL NIL NIL \"7BIT\" 100 3))"
                )

    def _send(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")


class FakeImapServer(socketserver.ThreadingTCPServer):
    """Servidor IMAP falso. `allow_reuse_address` e daemon threads para não prender a suíte."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, mailboxes: dict[str, FakeMailbox] | None = None, *,
                 capabilities: frozenset[str] = frozenset({"IMAP4rev1", "UIDPLUS", "MOVE", "IDLE"}),
                 refuse_idle: bool = False,
                 tls_context=None) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mailboxes = mailboxes or {"INBOX": FakeMailbox("INBOX")}
        self.capabilities = capabilities
        self.refuse_idle = refuse_idle
        self.tls_context = tls_context

        self.commands: list[ImapCommand] = []
        self.logins: list[str] = []
        self.body_fetch_uids: list[int] = []
        self.connection_count = 0
        self.inflight = 0
        self.concurrent_use_detected = False
        self.drop_after_n: int | None = None
        self.fail_next: dict[str, str] = {}
        self.idle_entered = threading.Event()
        self.idle_release = threading.Event()
        self.idle_timeout_s = 5.0
        self._hold: dict[str, threading.Event] = {}
        self.command_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    # ── configuração exigida pela estratégia ──
    def capability_string(self) -> str:
        caps = set(self.capabilities)
        if self.refuse_idle:
            caps.discard("IDLE")
        return " ".join(sorted(caps))

    def set_uidvalidity(self, mailbox: str, value: int) -> None:
        self.mailboxes[mailbox].uidvalidity = value

    def drop_after_n_commands(self, n: int) -> None:
        with self._lock:
            self.drop_after_n = max(n, len(self.commands) + 1)

    def fail_command(self, name: str, response: str) -> None:
        self.fail_next[name.upper()] = response

    def hold_response(self, name: str) -> threading.Event:
        """Retém a resposta do comando até o evento ser liberado (teste de concorrência)."""
        event = threading.Event()
        self._hold[name.upper()] = event
        return event

    def wait_for_command(self, name: str, timeout: float = 5.0) -> bool:
        deadline = threading.Event()
        wanted = name.upper()
        end = timeout
        while end > 0:
            with self._lock:
                if any(c.name == wanted for c in self.commands):
                    return True
            deadline.wait(0.02)
            end -= 0.02
        return False

    # ── consultas de asserção ──
    def command_names(self) -> list[str]:
        return [c.name for c in self.commands]

    def count_commands(self, name: str) -> int:
        return self.command_names().count(name.upper())

    def body_fetch_count(self) -> int:
        return len(self.body_fetch_uids)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


class _DropConnection(Exception):
    """Fecha o socket no meio do comando: simula queda de rede (CA-RF-MSG-08-1)."""


class _CommandFailed(Exception):
    def __init__(self, response: str) -> None:
        self.response = response
        super().__init__(response)
```

### 4.4 Servidor SMTP falso — `tests/fakes/fake_smtp_server.py`

O contador de conexões é o instrumento de `CA-RF-SND-03-1`: cancelar dentro da janela de undo tem de resultar em **zero conexões**, não em "conexão aberta e mensagem não transmitida".

```python
from __future__ import annotations

import smtpd
import threading


class FakeSmtpServer(smtpd.SMTPServer):
    """Servidor SMTP mínimo que conta conexões e guarda as mensagens transmitidas."""

    def __init__(self, *, refuse_connections: bool = False, reply_code: str = "250 OK") -> None:
        super().__init__(("127.0.0.1", 0), None, decode_data=False)
        self.connection_count = 0          # ← prova de CA-RF-SND-03-1
        self.messages: list[bytes] = []
        self.recipients: list[list[str]] = []
        self.refuse_connections = refuse_connections
        self.reply_code = reply_code
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def handle_accept(self):                # chamado a cada conexão TCP aceita
        self.connection_count += 1
        if self.refuse_connections:
            return None
        return super().handle_accept()

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        self.recipients.append(list(rcpttos))
        self.messages.append(data)
        return self.reply_code

    @property
    def port(self) -> int:
        return self.socket.getsockname()[1]

    def stop(self) -> None:
        self.close()


class RefusingSmtpServer:
    """Porta fechada: usada para CA-RF-SND-05-1. Não escuta nada."""

    def __init__(self) -> None:
        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()                            # porta livre, ninguém escutando
        self.connection_count = 0
```

### 4.5 `tests/fakes/request_recorder.py`

Instrumento de `CA-RNF-PRIV-01-1`, `CA-RF-RD-03-1`, `CA-RF-RD-04-1` e `CA-RF-RD-06-1`. Registra **tentativas**, incluindo as bloqueadas — porque uma requisição bloqueada ainda prova que o conteúdo tentou sair da máquina.

```python
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Attempt:
    url: str
    resource_type: str
    allowed: bool


class RequestRecorder:
    """Registro de toda tentativa de requisição do interceptor (02-arquitetura.md §5.5).

    Thread-safe: a documentação do Qt indica que o callback do interceptor pode
    ser invocado fora da thread da GUI; por isso há lock e nada aqui toca widgets.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: list[Attempt] = []

    def record(self, url: str, resource_type: str, *, allowed: bool) -> None:
        with self._lock:
            self._attempts.append(Attempt(url, resource_type, allowed))

    # Compatibilidade com a assinatura de 02-arquitetura.md §5.5
    def record_blocked(self, url: str, resource_type: str = "unknown") -> None:
        self.record(url, resource_type, allowed=False)

    def record_allowed(self, url: str, resource_type: str = "image") -> None:
        self.record(url, resource_type, allowed=True)

    @property
    def attempts(self) -> list[Attempt]:
        with self._lock:
            return list(self._attempts)

    @property
    def urls(self) -> list[str]:
        return [a.url for a in self.attempts]

    @property
    def blocked(self) -> list[Attempt]:
        return [a for a in self.attempts if not a.allowed]

    @property
    def allowed(self) -> list[Attempt]:
        return [a for a in self.attempts if a.allowed]

    def external_attempts(self) -> list[Attempt]:
        """Ignora o esquema interno pymail:// e as URLs de dados."""
        return [a for a in self.attempts
                if a.url.startswith(("http://", "https://", "//", "ftp://"))]

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()

    def wait_for_attempt(self, timeout_s: float = 2.0) -> Attempt | None:
        """Espera bloqueante por uma tentativa — usada no controle positivo do teste."""
        import time

        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            got = self.attempts
            if got:
                return got[0]
            time.sleep(0.01)
        return None
```

### 4.6 Por que estes dublês são de socket/interface e não `unittest.mock`

| Se mockássemos | O que deixaria de ser exercitado | Bug que passaria |
|---|---|---|
| `imaplib.IMAP4` (objeto) | Parsing de literal `{123}` (leitura de bytes crus do socket), distinção entre respostas *untagged* e *tagged*, *quoting* de mailbox com espaço ou acento, `BYE` no meio do comando, timeout de socket, encoding UTF-7 modificado | "O `select_folder('Caixa de Entrada')` funciona em todos os servidores menos naquele que o usuário usa" |
| `smtplib.SMTP` (objeto) | Handshake, negociação `STARTTLS`, resposta `5xx` com texto real do servidor, `Message-ID` no cabeçalho efetivamente transmitido | "Cancelar dentro da janela de undo ainda abre conexão TCP" (CA-RF-SND-03-1 é justamente sobre a conexão, não sobre a transmissão) |
| `sqlite3.connect` | Tokenizador `unicode61 remove_diacritics 2`, `foreign_keys` por conexão, rollback transacional de DDL, `quick_check` em arquivo truncado | "A busca não acha `Ação` quando o usuário digita `acao`" |
| `keyring` (real, sempre) | Nada de útil — mas o teste passa a depender do cofre da máquina | Suíte vermelha no Linux de CI sem *secret service* e verde na máquina do desenvolvedor |
| `QWebEngineUrlRequestInterceptor` | A decisão de bloquear | "O bloqueio de privacidade funciona porque o teste afirma que o método foi chamado" — e a requisição sai pela rede de verdade |

**Consequência prática:** o dublê fica na fronteira de rede (servidor falso TCP) ou de sistema operacional (keyring), e a asserção é sempre sobre **o que o servidor falso observou** ou sobre **o conteúdo do banco**, nunca sobre a lista de chamadas de um mock do nosso próprio módulo.

---

## 5. Os três testes críticos do projeto

Estes três testes não são "mais um item da suíte": são a tradução executável das afirmações centrais de `01-requisitos.md` §1. Se um deles for removido, enfraquecido ou marcado como *skip* permanente, o projeto perde a capacidade de afirmar o que promete.

| Teste | Critério | Requisito | Tarefa | Arquivo |
|---|---|---|---|---|
| A interface não bloqueia | `CA-RNF-PERF-01-1` | RNF-PERF-01 | T-39 | `tests/perf/test_gui_never_blocks.py` |
| Zero requisições de rede | `CA-RNF-PRIV-01-1` | RNF-PRIV-01 | T-07 | `tests/privacy/test_zero_network_requests.py` |
| Afinidade de thread do `imaplib` | (guarda de ADR-001, §10 riscos) | RF-MSG-01/04, risco "Bug de afinidade de thread em `imaplib`" de `02-arquitetura.md` §10 | T-10, T-11 | `tests/network/test_imap_thread_affinity.py` |

---

### 5.1 `CA-RNF-PERF-01-1` — a interface nunca bloqueia por mais de 100 ms

#### 5.1.1 Como instrumentar a thread principal do Qt

A thread da GUI do Qt é um laço de eventos cooperativo: `QTimer` só dispara quando o laço volta a processar eventos. Portanto, se um `QTimer` configurado para cada 20 ms dispara 340 ms depois do disparo anterior, alguém ocupou a thread da GUI por ~320 ms. **A latência de disparo do temporizador é a medida do bloqueio.**

```python
# tests/support/qt_utils.py
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Qt


@dataclass(frozen=True, slots=True)
class GuiBlock:
    duration_ms: float
    at_monotonic: float
    stacks: tuple[str, ...]


class StackSampler(threading.Thread):
    """Amostra a pilha da thread da GUI de fora dela.

    Enquanto a thread da GUI está bloqueada, esta thread continua rodando — logo
    ela captura exatamente a pilha do código culpado. Sem isso, a falha diz
    apenas "bloqueou 340 ms", e descobrir onde custa horas.
    """

    def __init__(self, target_thread_id: int, interval_s: float = 0.005) -> None:
        super().__init__(name="StackSampler", daemon=True)
        self._target = target_thread_id
        self._interval = interval_s
        self._stop = threading.Event()
        self._samples: deque[tuple[float, str]] = deque(maxlen=400)

    def run(self) -> None:
        import traceback

        while not self._stop.is_set():
            frame = sys._current_frames().get(self._target)
            if frame is not None:
                stack = "".join(traceback.format_stack(frame, limit=8))
                self._samples.append((time.monotonic(), stack))
            time.sleep(self._interval)

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=1.0)

    def stacks_between(self, t0: float, t1: float) -> tuple[str, ...]:
        seen: list[str] = []
        with threading.Lock():
            for ts, stack in list(self._samples):
                if t0 <= ts <= t1:
                    if stack not in seen:
                        seen.append(stack)
        return tuple(seen)


class GuiBlockWatchdog(QObject):
    """Detecta bloqueio da thread da GUI medindo a latência do próprio QTimer.

    Intervalo de 20 ms contra limite de 100 ms: cinco oportunidades de disparo
    dentro do orçamento de RNF-PERF-01 (que fala em 16 ms por operação; o
    critério de aceite CA-RNF-PERF-01-1 é explícito no limite de 100 ms, e é
    esse número que este teste verifica).
    """

    def __init__(self, parent: QObject | None = None, *,
                 interval_ms: int = 20, threshold_ms: float = 100.0) -> None:
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._threshold_ms = threshold_ms
        self._timer = QTimer(self)
        # PreciseTimer evita a granularidade grosseira do timer coarse do Windows.
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

        self._last = 0.0
        self._sampler: StackSampler | None = None
        self.ticks = 0
        self.violations: list[GuiBlock] = []
        self.max_delta_ms = 0.0

    # ── ciclo de vida ──
    def start(self, *, sample_stacks: bool = True) -> None:
        self.ticks = 0
        self.violations.clear()
        self.max_delta_ms = 0.0
        if sample_stacks:
            self._sampler = StackSampler(threading.get_ident())
            self._sampler.start()
        self._last = time.monotonic()
        self._timer.start()

    def stop(self) -> GuiBlockWatchdog:
        self._timer.stop()
        if self._sampler is not None:
            self._sampler.stop()
        return self

    # ── medição ──
    def _tick(self) -> None:
        now = time.monotonic()
        delta_ms = (now - self._last) * 1000.0
        previous = self._last
        self._last = now
        self.ticks += 1
        self.max_delta_ms = max(self.max_delta_ms, delta_ms)
        if delta_ms > self._threshold_ms:
            stacks = (self._sampler.stacks_between(previous, now)
                      if self._sampler is not None else ())
            self.violations.append(GuiBlock(delta_ms, now, stacks))

    # ── relatório ──
    def report(self) -> str:
        lines = [
            f"ticks={self.ticks} max_delta_ms={self.max_delta_ms:.1f} "
            f"violations={len(self.violations)}"
        ]
        for block in self.violations[:3]:
            lines.append(f"  bloqueio de {block.duration_ms:.0f} ms; pilhas capturadas:")
            for stack in block.stacks[:3]:
                lines.append("    " + stack.replace("\n", "\n    "))
        return "\n".join(lines)
```

**Por que a abordagem funciona.** O laço de eventos do Qt entrega para `_tick` apenas quando a thread está livre. A diferença entre dois disparos consecutivos é, portanto, `intervalo + tempo em que o laço esteve impedido de rodar`. Com intervalo de 20 ms e limite de 100 ms, um bloqueio real produz uma leitura de pelo menos ~120 ms — cinco vezes acima do ruído normal de agendamento, que é da ordem de 1 a 5 ms.

**Por que `time.monotonic()` e não `time.time()`.** Medimos uma **duração**, não um instante. `time.time()` é o relógio de parede: pode saltar para frente ou para trás por sincronização NTP, ajuste manual, mudança de horário de verão ou suspensão da máquina. Um salto para frente produziria uma violação falsa de vários segundos; um salto para trás produziria uma duração negativa. `time.monotonic()` é garantidamente não decrescente e não é afetado por ajustes do relógio. (`time.perf_counter()` seria igualmente correto e teria resolução maior em algumas plataformas; o que não se pode usar aqui é `time.time()`.)

**Limites conhecidos da abordagem — declarados, não escondidos:**

| Limite | Consequência | Mitigação |
|---|---|---|
| Só detecta bloqueio **do laço de eventos** | Um trecho que chame `QDialog.exec()`, `QMessageBox.exec()` ou `QEventLoop.exec()` processa eventos por dentro e mantém o temporizador disparando: o bloqueio real passa despercebido | Proibição arquitetural de laço de eventos aninhado em caminho de trabalho, verificada por revisão; o teste complementar de §5.1.2 cobre latência de entrega de eventos, com outro ponto cego |
| Resolução limitada pelo intervalo | Um bloqueio de 90 ms não é distinguível de ruído de agendamento de 90 ms | Irrelevante para este critério: o orçamento é 100 ms, e o intervalo é 20 ms |
| Mede o **agendamento**, não o trabalho | Não diz quanto custou a operação, apenas que ela impediu o laço | É exatamente o que o requisito afirma ("a thread da GUI nunca executa operação que possa exceder…") |
| O próprio watchdog roda na thread da GUI | Se ele quebrar (timer não iniciado, threshold absurdo), o teste passa vazio e feliz | Asserção de sanidade: `watchdog.ticks > 500` e o controle positivo de §5.1.3 |
| Ruído do ambiente | Em runner compartilhado, todo o processo pode ser dessecado por centenas de ms | Medição de linha de base em repouso antes da carga, e política de §5.1.4 |

#### 5.1.2 Sonda complementar: latência de entrega de evento publicado

Um segundo instrumento, com ponto cego diferente, cobre o caso em que a thread da GUI está processando eventos mas com latência alta (por exemplo, `processEvents` em laço apertado dentro de um cálculo longo).

```python
# tests/support/qt_utils.py (continuação)
class EventDeliveryProbe:
    """Uma thread auxiliar publica um evento na thread da GUI e mede quando ele é entregue."""

    def __init__(self, target: QObject, *, interval_s: float = 0.05) -> None:
        self._target = target
        self._interval = interval_s
        self._stop = threading.Event()
        self.latencies_ms: list[float] = []
        self._thread = threading.Thread(target=self._run, name="EventDeliveryProbe", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent

        while not self._stop.is_set():
            posted = time.monotonic()
            delivered = threading.Event()
            marker = _LatencyMarker(delivered)   # QEvent com timestamp de origem
            marker.posted_at = posted
            QCoreApplication.postEvent(self._target, marker)
            delivered.wait(timeout=1.0)
            self.latencies_ms.append((time.monotonic() - posted) * 1000.0)
            self._stop.wait(self._interval)
```

A sonda de evento e o watchdog do `QTimer` diferem em um aspecto importante: a sonda mede latência de **entrega**, o watchdog mede latência de **disparo de temporizador**. Os dois falham se a thread estiver ocupada; apenas a sonda falha se a thread estiver processando eventos em laço apertado. Usar os dois no teste crítico custa pouco e estreita o ponto cego.

#### 5.1.3 Teste crítico, com controle positivo

```python
# tests/perf/test_gui_never_blocks.py
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QTimer

from core.network.base import RemoteFolder
from core.storage import Storage
from core.tasks import AccountWorker, TaskPool
from tests.fakes.fake_incoming import FakeIncomingClient
from tests.support.qt_utils import EventDeliveryProbe, GuiBlockWatchdog

BULK_MESSAGES = 5_000
BUDGET_MS = 100.0


@pytest.fixture
def bulk_client() -> FakeIncomingClient:
    """Pasta com 5.000 mensagens, tamanho realista de corpo médio."""
    raw = b"Subject: x\r\n\r\n" + b"corpo medio " * 200
    return FakeIncomingClient(
        folders={"INBOX": [(str(uid), raw) for uid in range(1, BULK_MESSAGES + 1)]}
    )


@pytest.mark.perf
@pytest.mark.serial
@pytest.mark.timeout(300)
def test_gui_thread_never_blocks_during_bulk_sync(qtbot, tmp_path, bulk_client, account_config):
    """CA-RNF-PERF-01-1 (RNF-PERF-01, T-39).

    Durante uma sincronização de 5.000 mensagens, nenhuma operação submetida à
    thread da GUI pode bloqueá-la por mais de 100 ms.
    """
    from ui.components.message_list import MessageListModel

    storage = Storage(tmp_path / "pymail.db")
    storage.migrate()
    account_id = storage.upsert_account(account_config)
    folder_id = storage.upsert_folder(account_id, RemoteFolder("INBOX", "/", "inbox"),
                                      bulk_client.select_folder("INBOX"))

    model = MessageListModel(storage)          # construído na thread da GUI
    pool = TaskPool(max_threads=8)

    # ── linha de base: quanto este runner atrasa com o laço ocioso ──
    baseline = GuiBlockWatchdog(threshold_ms=BUDGET_MS)
    baseline.start(sample_stacks=False)
    qtbot.wait(1000)
    baseline.stop()
    if baseline.max_delta_ms > 50.0:
        pytest.skip(
            f"Runner ruidoso: latência ociosa de {baseline.max_delta_ms:.0f} ms. "
            "O teste de bloqueio não é conclusivo aqui; executar no job de perf dedicado."
        )

    worker = AccountWorker(account_id=account_id, client=bulk_client, storage=storage,
                           pool=pool)
    # O caminho crítico real: o lote chega por sinal e o MODELO é atualizado na GUI.
    worker.headers_ready.connect(
        lambda _acc, batch: model.append_batch(storage, folder_id, batch),
        type=Qt.ConnectionType.QueuedConnection,
    )

    watchdog = GuiBlockWatchdog(threshold_ms=BUDGET_MS)
    probe = EventDeliveryProbe(model)
    probe.start()
    watchdog.start()
    worker.start()

    try:
        worker.submit(lambda token: worker.sync_folder("INBOX", token))
        qtbot.waitUntil(lambda: worker.state == "idle", timeout=180_000)
        qtbot.wait(200)         # deixa a última atualização de modelo aterrissar
    finally:
        watchdog.stop()
        probe.stop()
        worker.shutdown()
        pool.waitForDone(5_000)

    # ── sanidade do instrumento: sem isso, um watchdog quebrado "passa" ──
    assert watchdog.ticks > 500, f"watchdog não coletou amostras: {watchdog.report()}"
    assert probe.latencies_ms, "sonda de eventos não produziu nenhuma amostra"

    # ── sanidade do cenário: o trabalho realmente aconteceu ──
    assert storage.count_messages(folder_id) == BULK_MESSAGES
    assert bulk_client.body_fetch_count() == 0        # CA-RF-MSG-01-1 de brinde

    # ── a asserção do critério de aceite ──
    assert watchdog.violations == [], (
        "A thread da GUI bloqueou além de 100 ms.\n" + watchdog.report()
    )
    worst_event_ms = max(probe.latencies_ms)
    assert worst_event_ms <= BUDGET_MS + 50.0, (
        f"Entrega de evento na GUI levou {worst_event_ms:.0f} ms"
    )


@pytest.mark.perf
@pytest.mark.serial
def test_watchdog_detects_induced_block(qtbot):
    """Controle positivo: o instrumento detecta um bloqueio que sabemos existir.

    Sem este teste, `watchdog.violations == []` é indistinguível de um watchdog
    que nunca dispara. Este é o teste que dá valor ao anterior.
    """
    watchdog = GuiBlockWatchdog(threshold_ms=BUDGET_MS)
    watchdog.start(sample_stacks=True)
    QTimer.singleShot(50, lambda: time.sleep(0.35))   # bloqueio induzido de ~350 ms

    qtbot.waitUntil(lambda: bool(watchdog.violations), timeout=3_000)
    watchdog.stop()

    worst = max(v.duration_ms for v in watchdog.violations)
    assert worst >= 300.0, f"bloqueio de 350 ms não detectado: {watchdog.report()}"
    assert any("test_watchdog_detects_induced_block" in s for s in watchdog.violations[0].stacks)
```

#### 5.1.4 Quando este teste falhar de forma intermitente

Aumentar o limite de 100 ms **não é uma opção**: o critério de aceite tem esse número, e afrouxá-lo transforma uma prova em decoração. O protocolo é:

1. **Ler a pilha, não o número.** O `StackSampler` capturou a pilha da thread da GUI *durante* o bloqueio. Se ela aponta para código do projeto (`core/storage.py` sendo consultado na GUI, `sanitize_html` chamado num slot, `time.sleep`, I/O de arquivo), é **defeito real** — corrigir o código, não o teste. Todo bloqueio que aparece com pilha do projeto é tratado como bug de arquitetura (violação da tabela normativa de `02-arquitetura.md` §4).
2. **Verificar a linha de base.** A falha imprime `max_delta_ms` da medição ociosa. Se o runner já atrasa > 50 ms ocioso, o teste se **pula** com motivo explícito (§5.1.3) em vez de mentir. O job de perf dedicado (`.github/workflows/ci.yml`, job `perf`) é onde ele é conclusivo.
3. **Reproduzir localmente**: `pytest tests/perf/test_gui_never_blocks.py -p no:xdist -n 0 --timeout=300 -x` e repetir 5 vezes. Defeito real reproduz em todas; ruído de co-tenant não.
4. **Correlacionar com o evento.** Se a violação sempre coincide com o mesmo lote (por exemplo, o primeiro `insert_headers` de 200 itens), o culpado é aquele caminho — investigar por que ele roda na GUI.
5. **Quarentena, nunca afrouxamento.** Persistindo como ruído puro de runner (sem pilha do projeto, sem correlação, presente também na linha de base), o teste recebe `@pytest.mark.quarantine` com *issue* aberto, **continua rodando** e continua relatando, e passa a ser obrigatório no job noturno. O portão de merge usa o resultado do job de perf dedicado. O limite de 100 ms permanece intocado em todos os cenários.

---

### 5.2 `CA-RNF-PRIV-01-1` — zero requisições de rede originadas pelo conteúdo

#### 5.2.1 O corpus

```python
# tests/privacy/corpus.py
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eml"


def _collect(*dirs: str) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        files.extend(sorted((FIXTURES / d).glob("*.eml")))
    assert files, f"corpus vazio em {dirs}: ver §7 de 06-estrategia-de-testes.md"
    return files


# Todo arquivo cobre um vetor de vazamento diferente (ver §7):
#   tracking/  → <img> 1x1, background-image, @import, @font-face, <picture>/srcset,
#                <video poster>, <track>, <link rel=preload>, <meta refresh>, form action
#   malicious/ → <script>, onerror, iframe, javascript:, <object>, <embed>, <base href>
CORPUS_EML = _collect("tracking", "malicious")


@pytest.fixture(params=CORPUS_EML, ids=lambda p: f"{p.parent.name}/{p.stem}")
def corpus_message(request) -> Path:
    return request.param
```

#### 5.2.2 Nível A — asserção estática sobre o HTML sanitizado (roda em todo PR, sem Chromium)

```python
# tests/privacy/test_zero_network_requests.py
from __future__ import annotations

import re

import pytest

from core.security import sanitize_html

REMOTE_REF = re.compile(
    r"""(?:src|href|background|poster|data|action|srcset|content)\s*=\s*"""
    r"""["']?\s*(?:https?:)?//""",
    re.IGNORECASE,
)


@pytest.mark.unit
@pytest.mark.privacy
def test_sanitized_output_has_no_active_remote_references(corpus_message):
    """Origem: CA-RNF-PRIV-01-1 (RNF-PRIV-01, T-07) e CA-RF-RD-03-1 (RF-RD-03).

    O HTML sanitizado pode CONTER a URL original, mas apenas em atributos
    data-* (preservação exigida por 03-modelo-de-dados.md §6.3 e pelo RF-RD-05).
    Nenhum atributo capaz de fazer o motor buscar recurso pode apontar para fora.
    """
    raw = corpus_message.read_bytes()
    html = sanitize_html(raw)

    # Controle positivo do teste: a mensagem realmente aponta para fora.
    assert b"http://" in raw or b"https://" in raw, "fixture sem referência remota"
    assert REMOTE_REF.search(html) is None, f"referência remota ativa em {corpus_message.name}"
    # ... e a URL original foi preservada para a interface (data-*), provando que
    # não estamos apenas apagando tudo.
    assert "data-original-src" in html or "data-original-href" in html
```

#### 5.2.3 Nível B — o teste do critério de aceite, com `QWebEngineView` real

```python
@pytest.mark.gui
@pytest.mark.privacy
@pytest.mark.slow
@pytest.mark.serial
@pytest.mark.timeout(180)
def test_rendering_corpus_produces_zero_network_requests(
    qtbot, corpus_message, fake_keyring, tmp_path, local_http_server,
):
    """CA-RNF-PRIV-01-1 (RNF-PRIV-01, T-07) — a prova da proposta de valor do produto.

    Renderiza a mensagem sanitizada em QWebEngineView real com o
    PrivacyInterceptor instalado e exige que a lista de TENTATIVAS de requisição
    fique vazia.

    Decisões que fazem este teste ser honesto:
      * asserção sobre `recorder.attempts` (tentativas), não sobre o HTML;
      * controle positivo DENTRO do mesmo view ao final, provando que o
        interceptor e o motor estão vivos e que uma referência remota real
        produziria uma tentativa — sem ele, o teste passa vazio;
      * `pymail://message/` como baseUrl (02-arquitetura.md §5.5): URL relativa
        em e-mail falha em vez de resolver para um host remoto.
    """
    from PySide6.QtCore import QUrl

    from tests.fakes.request_recorder import RequestRecorder
    from ui.components.reader import PrivacyInterceptor, ReaderPane

    raw = corpus_message.read_bytes()
    html = sanitize_html(raw)

    recorder = RequestRecorder()
    pane = ReaderPane(allow_remote_images=lambda: False, recorder=recorder)
    qtbot.addWidget(pane)

    corpus_attempts: list[str] = []

    def on_loaded(ok: bool) -> None:
        # Depois de loadFinished, o Chromium ainda pode disparar requisições de
        # sub-recursos. Processar eventos por um intervalo de acomodação é parte
        # do protocolo do teste, e está registrado como fragilidade conhecida.
        qtbot.wait(750)
        corpus_attempts.extend(a.url for a in recorder.external_attempts())

    pane.view.loadFinished.connect(on_loaded)
    pane.view.setHtml(html, QUrl("pymail://message/"))
    qtbot.waitUntil(lambda: bool(corpus_attempts) or pane.view.loadFinished, timeout=30_000)
    qtbot.wait(1000)

    # ── prova de vida do instrumento, no MESMO view e no MESMO profile ──
    before = len(recorder.external_attempts())
    beacon = f'<html><body><img src="{local_http_server.url}/beacon.png"></body></html>'
    pane.view.setHtml(beacon, QUrl("pymail://message/"))
    qtbot.wait(1000)
    after = recorder.external_attempts()
    assert len(after) > before, (
        "O interceptor não registrou nenhuma tentativa para um beacon conhecido: "
        "o instrumento está morto e este teste não prova nada."
    )
    assert after[-1].allowed is False, "beacon deveria ter sido BLOQUEADO"

    # ── a asserção do critério de aceite ──
    assert corpus_attempts == [], (
        "Conteúdo do e-mail originou requisições de rede:\n  "
        + "\n  ".join(corpus_attempts)
    )
```

#### 5.2.4 Por que a asserção é sobre as tentativas e não sobre o HTML

| Motivo | Detalhe |
|---|---|
| O requisito é sobre rede, não sobre marcação | `RNF-PRIV-01` diz "nenhuma requisição de rede é originada pelo conteúdo". Inspecionar o HTML é uma proxy; a tentativa registrada pelo interceptor é o fato |
| Vetores que não são tags | `background-image: url(...)` em atributo `style`, `@import` e `@font-face` dentro de `<style>`, `<meta http-equiv="refresh">`, `<link rel="preload">`, `<video poster>`, `<track src>`, `<form action>`, `<picture>/<srcset>`. Uma varredura de tags `<img>` deixa todos passarem |
| O nosso próprio passe reescreve URLs | `data-original-src` preserva a URL (exigido por RF-RD-05/RF-RD-07). Uma varredura ingênua por `http` no HTML sanitizado produziria **falso positivo** — e alguém "resolveria" removendo a preservação, quebrando um requisito |
| O motor pede coisas que o HTML não pediu | favicon, pré-carregamento especulativo, redirecionamentos, `data:` URIs, arquivos de fonte. Só o interceptor vê o que realmente sai |
| O interceptor vê também o que foi **cancelado** | `info.block(True)` não apaga o registro da tentativa. Bloquear no último instante é diferente de nunca tentar, e essa diferença é informação de segurança |
| Defesa em profundidade | Sanitização e interceptor são camadas distintas (ADR-003/ADR-004). O teste mede a camada que o produto promete: a de rede |

#### 5.2.5 Quando este teste falhar de forma intermitente

| Sintoma | Causa provável | Ação |
|---|---|---|
| Falha em `assert len(after) > before` (beacon não registrado) | Chromium não inicializou, ou o profile não recebeu o interceptor | É **falha do harness**, não do produto: `tests/gui/conftest.py` detecta indisponibilidade de Chromium na sessão e marca `pytest.skip("QWebEngineView indisponível neste runner")`. A suíte de privacidade do PR continua coberta pelo nível A |
| `corpus_attempts` contém favicon ou `pymail://` | Ruído do motor, não vazamento | Filtrar apenas esquemas externos (`external_attempts()`); nunca relaxar a asserção para "quase vazio" |
| `corpus_attempts` contém um host real | **Vazamento de verdade** | Reproduzir localmente; identificar o vetor na fixture; corrigir sanitização *e* interceptor. Um vazamento encontrado aqui é a falha mais grave que a suíte pode reportar — tratar como incidente de segurança, não como flake |
| Timeout em `loadFinished` | Chromium travado no runner (memória, sandbox) | Rodar com `-n 0`, `QTWEBENGINE_DISABLE_SANDBOX=1`, `--disable-dev-shm-usage`; se persistir, mover o nível B para o job noturno e manter o nível A no PR |

---

### 5.3 Afinidade de thread do `imaplib` — o cenário que ADR-001 existe para evitar

#### 5.3.1 O problema, exatamente

`imaplib.IMAP4` não é thread-safe. Duas threads usando a mesma conexão não produzem uma exceção: produzem **respostas cruzadas**. A thread A emite `UID FETCH 1:200 (ENVELOPE)`; a thread B emite `UID FETCH 201:400 (ENVELOPE)`; o `readline()` de A consome a resposta de B, e cada uma recebe dados plausíveis e errados. O sintoma aparece em produção como "mensagens trocadas na lista", de forma intermitente, sem exceção e sem log. É o risco de impacto **Alto** registrado em `02-arquitetura.md` §10.

Detectar isso "esperando a corrida acontecer" é inútil: depende de escalonamento. A detecção precisa ser **estrutural**.

#### 5.3.2 Detecção determinística: três camadas

| Camada | Onde atua | O que detecta | Por que é determinística |
|---|---|---|---|
| 1. `ThreadAffinityGuard` | Envolve o objeto `IMAP4`; compara `threading.get_ident()` com o dono registrado na criação, a **cada** chamada | Uso por qualquer thread estranha | Não observa corrida: compara identidade na entrada da chamada. Independe da ordem de execução |
| 2. `ConnectionTouchLog` | Registra a identidade de toda thread que chamou qualquer método público | Conjunto de threads que tocaram a conexão | Asserção sobre um conjunto, não sobre um instante |
| 3. Servidor falso com resposta retida | Atrasa deliberadamente a resposta do primeiro comando; se outro comando chegar na mesma conexão antes, marca `concurrent_use_detected` | Uso concorrente mesmo quando o objeto `IMAP4` não está envolto (acesso direto ao socket, biblioteca de terceiros) | O teste controla quando liberar a resposta, com `threading.Event` — sem `sleep` |

```python
# tests/fakes/affinity.py
from __future__ import annotations

import threading
from typing import Any


class ThreadAffinityViolation(RuntimeError):
    """A conexão IMAP foi usada por uma thread que não é a sua dona (ADR-001)."""


class ThreadAffinityGuard:
    """Torna a violação de afinidade em erro determinístico, no ponto da chamada.

    Envolve um IMAP4 já construído. É instalado no `AccountWorker` no primeiro
    passo da tarefa T-10; em produção o guard fica ativo (custo desprezível) e
    converte um bug silencioso em exceção explícita.
    """

    def __init__(self, conn: Any, *, record_touches: bool = True) -> None:
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_owner_thread", threading.get_ident())
        object.__setattr__(self, "_owner_name", threading.current_thread().name)
        object.__setattr__(self, "_busy", threading.Lock())
        object.__setattr__(self, "_touch_log", _ConnectionTouchLog() if record_touches else None)
        object.__setattr__(self, "violations", [])

    def __getattr__(self, name: str) -> Any:
        attr = getattr(object.__getattribute__(self, "_conn"), name)
        if not callable(attr):
            return attr

        def guarded(*args: Any, **kwargs: Any) -> Any:
            ident = threading.get_ident()
            owner = object.__getattribute__(self, "_owner_thread")
            if ident != owner:
                violation = ThreadAffinityViolation(
                    f"{name}() chamado por thread {ident} "
                    f"({threading.current_thread().name}); "
                    f"a conexão pertence à thread {owner} "
                    f"({object.__getattribute__(self, '_owner_name')})"
                )
                object.__getattribute__(self, "violations").append(violation)
                raise violation
            # Reentrância: uso concorrente dentro do próprio dono (laço aninhado,
            # processEvents dentro de um comando) também é violação.
            busy = object.__getattribute__(self, "_busy")
            if not busy.acquire(blocking=False):
                violation = ThreadAffinityViolation(f"{name}() reentrante na conexão IMAP")
                object.__getattribute__(self, "violations").append(violation)
                raise violation
            log = object.__getattribute__(self, "_touch_log")
            try:
                if log is not None:
                    log.record(name, ident)
                return attr(*args, **kwargs)
            finally:
                busy.release()

        return guarded


class _ConnectionTouchLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[tuple[str, int]] = []

    def record(self, method: str, thread_id: int) -> None:
        with self._lock:
            self._entries.append((method, thread_id))

    @property
    def entries(self) -> list[tuple[str, int]]:
        with self._lock:
            return list(self._entries)

    def thread_ids(self) -> set[int]:
        return {tid for _m, tid in self.entries}
```

#### 5.3.3 Os testes

```python
# tests/network/test_imap_thread_affinity.py
from __future__ import annotations

import threading
import time

import pytest

from core.network.imap_client import ImapIncomingClient
from tests.fakes.affinity import ThreadAffinityGuard, ThreadAffinityViolation
from tests.fakes.fake_imap_server import FakeImapServer, FakeMailbox


@pytest.fixture
def imap_server() -> FakeImapServer:
    server = FakeImapServer({"INBOX": FakeMailbox("INBOX", [(1, frozenset(), b"x")])})
    yield server
    server.stop()


@pytest.mark.network
@pytest.mark.threaded
@pytest.mark.serial
def test_imap_connection_is_used_by_exactly_one_thread(imap_server, account_config, qtbot):
    """Guarda de ADR-001 (02-arquitetura.md §4 e §10) — o caminho correto.

    O `AccountWorker` é dono exclusivo da conexão. Nenhuma outra thread — em
    especial a do TaskPool, que sanitiza HTML e indexa — pode tocá-la.
    """
    from core.tasks import AccountWorker, TaskPool

    client = ImapIncomingClient(account_config, port=imap_server.port)
    guard = ThreadAffinityGuard(client._conn)
    client._conn = guard

    pool = TaskPool(max_threads=4)
    worker = AccountWorker(account_id=1, client=client, storage=None, pool=pool)

    # Trabalho pesado e legítimo do TaskPool, em paralelo com a rede.
    for _ in range(20):
        pool.submit(lambda: "sanitize" * 1000)

    worker.submit(lambda token: (client.connect(), client.list_folders(),
                                 client.select_folder("INBOX")))
    worker.start()
    qtbot.waitUntil(lambda: worker.state == "idle", timeout=15_000)

    assert guard.violations == []
    assert guard._touch_log.thread_ids() == {worker.current_thread_id()}
    assert len(guard._touch_log.thread_ids()) == 1

    worker.shutdown()
    pool.waitForDone(5_000)


@pytest.mark.network
@pytest.mark.serial
def test_guard_fails_when_second_thread_uses_connection(imap_server, account_config):
    """Controle positivo, e a razão de o teste acima valer algo.

    Duas threads na MESMA conexão. O guard precisa falhar — de forma
    determinística, no ponto da chamada, sem depender de sorte de escalonamento.
    """
    client = ImapIncomingClient(account_config, port=imap_server.port)
    guard = ThreadAffinityGuard(client._conn)
    client._conn = guard
    client.connect()

    errors: list[BaseException] = []

    def offending_thread() -> None:
        try:
            client.list_folders()
        except BaseException as exc:      # noqa: BLE001 — o teste quer o erro
            errors.append(exc)

    t = threading.Thread(target=offending_thread, name="Offender")
    t.start()
    t.join(timeout=5.0)

    assert len(errors) == 1
    assert isinstance(errors[0], ThreadAffinityViolation)
    assert "Offender" in str(errors[0])
    assert len(guard.violations) == 1


@pytest.mark.network
@pytest.mark.serial
def test_server_detects_concurrent_commands_on_same_connection(imap_server, account_config):
    """Camada 3: detecta uso concorrente mesmo sem o guard, no nível do protocolo.

    O servidor RETÉM a resposta do primeiro FETCH. Se um segundo comando chegar
    na mesma conexão antes de o primeiro terminar, a conexão está sendo usada
    por duas partes ao mesmo tempo — que é a definição do bug de ADR-001.
    O `threading.Event` da liberação é o que torna isto determinístico.
    """
    import imaplib

    conn_a = imaplib.IMAP4("127.0.0.1", imap_server.port)
    conn_a.login("u", "p")
    conn_a.select("INBOX")

    release = imap_server.hold_response("FETCH")

    holder = threading.Thread(
        target=lambda: conn_a.uid("FETCH", "1", "(ENVELOPE)"),
        name="Holder",
        daemon=True,
    )
    holder.start()
    assert imap_server.wait_for_command("FETCH", timeout=5.0)

    # Segundo comando na MESMA conexão, enquanto o primeiro está em voo.
    conn_a.noop()
    assert imap_server.concurrent_use_detected is True

    release.set()
    holder.join(timeout=5.0)
    conn_a.logout()


@pytest.mark.network
@pytest.mark.serial
def test_pool_work_never_touches_the_imap_connection(imap_server, account_config, qtbot):
    """ADR-001, §4: TaskPool faz sanitização e índice; nunca rede.

    Mesmo com 200 tarefas no pool durante uma sincronização real, o guard não
    vê uma única chamada vinda de outra thread.
    """
    from core.tasks import AccountWorker, TaskPool

    client = ImapIncomingClient(account_config, port=imap_server.port)
    guard = ThreadAffinityGuard(client._conn)
    client._conn = guard
    pool = TaskPool(max_threads=8)
    worker = AccountWorker(account_id=1, client=client, storage=None, pool=pool)

    for _ in range(200):
        pool.submit(lambda: "plain text derivation" * 500)
    worker.submit(lambda token: (client.connect(), client.fetch_headers(1, 50)))
    worker.start()
    qtbot.waitUntil(lambda: worker.state == "idle", timeout=20_000)

    assert guard.violations == []
    assert guard._touch_log.thread_ids() == {worker.current_thread_id()}
    worker.shutdown()
    pool.waitForDone(5_000)
```

#### 5.3.4 Quando este teste falhar de forma intermitente

| Teste | Falha intermitente significa | Ação |
|---|---|---|
| `test_imap_connection_is_used_by_exactly_one_thread` | **Não é flake.** É a violação de ADR-001 acontecendo. O `_touch_log` imprime exatamente quais métodos foram chamados por qual thread | Tratar como defeito de arquitetura de prioridade máxima: localizar o chamador pelo nome do método e pela pilha, e mover a chamada para dentro da `AccountWorker`. Nunca marcar como *rerun* |
| `test_guard_fails_when_second_thread_uses_connection` | O guard não detectou, ou detectou duas vezes (o segundo `connect()` no mesmo teste) | Se não detectou, o guard está mal instalado (envolve o objeto errado); corrigir o harness. Este teste não pode ser tolerado intermitente: ele é o controle positivo |
| `test_server_detects_concurrent_commands_on_same_connection` | Sincronização do harness: o `hold_response` foi liberado antes do segundo comando, ou o servidor não estava segurando | Substituir qualquer espera por `threading.Event` (`wait_for_command` já é por evento). Se ainda oscilar, o problema é a fila do `imaplib` local, não o detector |
| `test_pool_work_never_touches_the_imap_connection` | Uma tarefa do pool recebeu o cliente por engano (captura de `self` em *closure*) | Defeito real de vazamento de escopo. Corrigir passando apenas dados imutáveis ao pool, como manda `02-arquitetura.md` §4 |

**Asserção de conjunto em vez de asserção temporal.** Toda a estratégia evita `sleep` e "torcer para a corrida aparecer": a violação é detectada na comparação de identidade de thread, o que é uma propriedade estrutural do programa, não um evento probabilístico. É por isso que este teste pode ser um portão de merge sem gerar ruído.

---

### 5.4 Resumo: falha intermitente nos três testes críticos

| Teste | Nunca fazer | Fazer |
|---|---|---|
| `CA-RNF-PERF-01-1` | Aumentar 100 ms; adicionar `sleep`; marcar `skip` | Ler a pilha capturada; checar a linha de base ociosa; reproduzir 5× local; quarentena com issue se for ruído puro de runner |
| `CA-RNF-PRIV-01-1` | Relaxar para "poucas requisições"; ignorar host real | Distinguir falha do harness (beacon não detectado → skip por Chromium indisponível) de vazamento real (host externo → incidente de segurança) |
| Afinidade de thread | `rerun`; `pytest-rerunfailures`; `sleep` para "dar tempo" | Tratar como defeito de arquitetura; o `_touch_log` diz quem chamou o quê |

---

## 6. Testes por módulo

Em toda subseção, "Origem" indica o critério de aceite (`CA-*`), o requisito (`RF-*`/`RNF-*`) e a tarefa (`T-*`) de que o teste nasce. Teste sem origem declarada é teste que alguém esqueceu de justificar — e a primeira coisa a cortar quando a suíte ficar lenta.

### 6.1 `core/security.py` — sanitização de HTML

**Origem principal:** `CA-RF-RD-01-1` (RF-RD-01, RNF-SEC-03, T-05) · **Origem secundária:** `CA-RF-RD-03-1`, `CA-RF-RD-04-1`, `CA-RF-RD-06-1`, `CA-RF-RD-07-1`, `CA-RNF-PRIV-01-1`, RF-RD-05.

Sanitização é a única função do projeto que é pura, determinística e alvo de ataque. Todo teste aqui é parametrizado sobre o corpus de `tests/fixtures/eml/malicious/` — é o corpus que `CA-RF-RD-01-1` exige literalmente.

| Teste | Verifica | Origem |
|---|---|---|
| `test_sanitize_removes_forbidden_elements[script,iframe,object,embed,form,base,style_import]` | Nenhum dos elementos proibidos sobrevive ao HTML final | CA-RF-RD-01-1 |
| `test_sanitize_removes_event_handler_attributes[onerror,onload,onclick,onmouseover]` | Nenhum atributo `on*` sobrevive, em nenhum elemento | CA-RF-RD-01-1 |
| `test_sanitize_strips_javascript_scheme` | `href`/`src` com `javascript:`, `vbscript:` e `data:text/html` são neutralizados | CA-RF-RD-01-1 |
| `test_sanitize_strips_css_expression_and_behavior` | `expression()`, `behavior:` e `-moz-binding` são removidos do `style` (passe `tinycss2`) | CA-RF-RD-01-1 |
| `test_sanitize_removes_remote_css_import` | `@import url(http://...)` e `url(http://...)` em `style`/`<style>` não sobrevivem | CA-RF-RD-01-1 |
| `test_sanitize_blocks_all_remote_resources` | Todo recurso remoto é neutralizado ou reescrito | CA-RF-RD-03-1, CA-RNF-PRIV-01-1 |
| `test_sanitize_preserves_original_url_in_data_attr` | A URL original sobrevive em `data-original-src`/`data-original-href` | RF-RD-05, 03 §6.3 |
| `test_sanitize_removes_tracking_pixels_irreversibly[pixel_1x1, pixel_0x0, display_none, visibility_hidden, hidden_attr, width_attr]` | O pixel é removido **mesmo** com `allow_remote_images=True` | CA-RF-RD-04-1, RNF-PRIV-03 |
| `test_sanitize_keeps_legitimate_inline_image_as_data_uri` | Imagem embutida legítima não é destruída junto com os rastreadores | RF-RD-03 |
| `test_sanitize_strips_tracking_query_params[utm_source,utm_medium,fbclid,gclid,mc_eid,_hsenc,_hsmi,vero_id,igshid]` | Parâmetro de rastreamento removido do `href`, preservando os demais | RF-RD-05 |
| `test_sanitize_preserves_anchor_text_of_misleading_link` | O texto exibido (`banco-falso.com`) não é alterado, e o `data-original-href` guarda o destino real | CA-RF-RD-07-1 |
| `test_sanitize_injects_csp_meta` | `<meta http-equiv="Content-Security-Policy">` presente e restritivo no HTML final | RF-RD-06 (defesa em profundidade) |
| `test_sanitize_is_idempotent` | `sanitize_html(sanitize_html(x)) == sanitize_html(x)` — permite re-sanitizar sem degradar | 03 §6.3 (re-sanitização por `sanitizer_version`) |
| `test_sanitize_handles_missing_or_malformed_headers` | Cabeçalhos ausentes/malformados não geram exceção nem HTML vazio | fixtures `malformed/` |
| `test_sanitize_decodes_iso8859_1_and_utf8_with_bom` | `Ação`, `serviço`, cedilha e circunflexo sobrevivem à decodificação correta | RF-RD-02 |
| `test_sanitize_large_body_completes_within_budget` | Corpo de 5 MB sanitiza sem estourar tempo nem memória | RNF-PERF-03 |
| `test_sanitize_output_never_contains_user_script_payload` | O payload exato da fixture não aparece no resultado | CA-RF-RD-01-1 |

```python
# tests/unit/test_sanitize_html.py
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.security import sanitize_html

MALICIOUS = Path(__file__).resolve().parents[1] / "fixtures" / "eml" / "malicious"
CORPUS = sorted(MALICIOUS.glob("*.eml"))

FORBIDDEN_TAGS = ("script", "iframe", "object", "embed", "form", "base", "applet", "meta")
# `meta` é permitido apenas para o CSP que nós injetamos: o teste trata o caso.
FORBIDDEN_ATTR_PATTERN = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
FORBIDDEN_SCHEME_PATTERN = re.compile(
    r"(?:href|src|action|data)\s*=\s*[\"']?\s*(?:javascript|vbscript|data:text/html)",
    re.IGNORECASE,
)
CSS_DANGER_PATTERN = re.compile(
    r"(expression\s*\(|behavior\s*:|@import|-moz-binding|javascript\s*:)", re.IGNORECASE
)


@pytest.mark.unit
@pytest.mark.privacy
@pytest.mark.parametrize("eml_path", CORPUS, ids=lambda p: p.stem)
def test_sanitize_removes_all_forbidden_markup(eml_path: Path) -> None:
    """Origem: CA-RF-RD-01-1 (RF-RD-01, RNF-SEC-03, T-05).

    O teste FALHA se qualquer elemento, atributo ou esquema proibido sobreviver —
    não há lista de tolerância.
    """
    raw = eml_path.read_bytes()
    html = sanitize_html(raw)
    lowered = html.lower()

    for tag in FORBIDDEN_TAGS:
        if tag == "meta":
            # Só o nosso meta de CSP é aceitável.
            for match in re.finditer(r"<meta\b[^>]*>", lowered):
                assert "content-security-policy" in match.group(0), (
                    f"<meta> não-CSP sobreviveu em {eml_path.name}"
                )
            continue
        assert f"<{tag}" not in lowered, f"<{tag}> sobreviveu em {eml_path.name}"

    assert FORBIDDEN_ATTR_PATTERN.search(html) is None
    assert FORBIDDEN_SCHEME_PATTERN.search(html) is None
    assert CSS_DANGER_PATTERN.search(html) is None

    # Controle positivo: o corpus realmente contém esses vetores. Um corpus
    # "limpo" por acidente faria este teste passar sem provar nada.
    assert (
        FORBIDDEN_ATTR_PATTERN.search(raw.decode("utf-8", "replace")) is not None
        or b"<script" in raw.lower()
        or b"javascript:" in raw.lower()
    ), f"{eml_path.name} não contém vetor hostil — corpus inútil"


@pytest.mark.unit
@pytest.mark.privacy
@pytest.mark.parametrize(
    "markup",
    [
        '<img src="http://track.exemplo.com/p.gif" width="1" height="1">',
        '<img src="http://track.exemplo.com/p.gif" style="width:1px;height:1px">',
        '<img src="http://track.exemplo.com/p.gif" style="display:none">',
        '<img src="http://track.exemplo.com/p.gif" style="visibility:hidden">',
        '<img src="http://track.exemplo.com/p.gif" hidden>',
        '<img src="http://track.exemplo.com/p.gif" width="0" height="0">',
    ],
)
def test_sanitize_removes_tracking_pixels_even_when_images_allowed(markup: str) -> None:
    """Origem: CA-RF-RD-04-1 (RF-RD-04, RNF-PRIV-03, T-05, T-07).

    Remoção IRREVERSÍVEL: a autorização de imagens do remetente (RF-RD-03) não
    ressuscita o pixel. O teste roda o passe com a autorização ligada.
    """
    html = sanitize_html(f"<html><body>{markup}</body></html>", allow_remote_images=True)
    assert "track.exemplo.com" not in html
    assert "p.gif" not in html
```

**Cuidado com a fragilidade destes testes.** Eles asseram sobre *ausência* de padrões textuais no HTML de saída. Quando o `nh3` for atualizado, a forma exata da saída pode mudar (ordem de atributos, normalização de entidades, um `<style>` que passa a aparecer como `<style>` vazio) e alguns testes quebram sem que a segurança tenha piorado. Regra: quando isso acontecer, **revisar o diff do corpus antes de ajustar a asserção** — a atualização do sanitizador é exatamente o momento em que uma regressão de segurança passaria despercebida. O comentário no topo de `tests/unit/test_sanitize_html.py` registra essa obrigação.

### 6.2 `core/security.py` — keyring

**Origem principal:** `CA-RNF-SEC-01-1` (RNF-SEC-01, T-03, T-37) · **Origem secundária:** `CA-RF-ACC-05-1`, `CA-RF-SET-04-1`, RF-ACC-01, RF-ACC-03.

| Teste | Verifica | Origem |
|---|---|---|
| `test_no_password_written_to_database` | O sentinela não aparece em claro, nem em base64/hex, em nenhum byte do arquivo do banco; o schema não tem coluna capaz de guardá-lo | CA-RNF-SEC-01-1 |
| `test_no_password_in_config_file` | `config.toml` não contém o sentinela nem campo de credencial | CA-RNF-SEC-01-1 |
| `test_no_password_in_logs_at_any_level` | Execução de login+leitura+envio gera arquivos de log sem o sentinela, sem corpo de mensagem e sem caminho de anexo do usuário | CA-RF-SET-04-1 |
| `test_password_never_in_process_arguments` | `sys.argv` do processo de teste não recebe credencial em nenhum caminho | RNF-SEC-01 |
| `test_credential_roundtrip_uses_keyring_only` | Gravar e ler passa exclusivamente pelo dublê; o banco não é tocado | RF-ACC-01 |
| `test_credential_removed_when_account_deleted` | Após `delete_account`, a entrada do keyring falso não existe mais | CA-RF-ACC-05-1 |
| `test_deleted_account_leaves_no_rows_in_any_table` | `accounts`, `folders`, `messages`, `bodies`, `attachments` e `messages_fts` sem referência à conta | CA-RF-ACC-05-1 |
| `test_keyring_unavailable_raises_actionable_error` | `NoKeyringError` vira erro de domínio com mensagem que o usuário entende, sem *crash* | RF-ACC-03 |
| `test_keyring_write_failure_does_not_fall_back_to_file` | Falha do cofre **não** degrada para gravar a senha em config/banco (nunca um caminho de fallback silencioso) | RNF-SEC-01 |
| `test_delete_of_missing_credential_is_idempotent` | Remover conta cujo segredo já sumiu não deixa a operação pela metade | CA-RF-ACC-05-1 |

```python
def test_credential_removed_when_account_deleted(storage, fake_keyring, account_config):
    """CA-RF-ACC-05-1 (RF-ACC-05, T-19): remover a conta limpa banco E keyring."""
    from core.security import set_credential

    set_credential(account_config, "senha-de-teste")
    account_id = storage.upsert_account(account_config)
    assert fake_keyring.has_entry_for(account_config.email)

    storage.delete_account(account_id)
    storage.delete_credential_for_account(account_config)      # chamado pelo fluxo de remoção

    assert not fake_keyring.has_entry_for(account_config.email)
    assert ("delete", "pymail-client", account_config.email) in fake_keyring.calls
    for table in ("folders", "messages", "bodies", "attachments", "pending_ops"):
        remaining = storage._conn_for_current_thread().execute(
            f"SELECT COUNT(*) FROM {table} WHERE account_id = ?", (account_id,)
        ).fetchone()[0] if table != "bodies" and table != "attachments" else storage._conn_for_current_thread().execute(
            f"SELECT COUNT(*) FROM {table} t JOIN messages m ON m.id = "
            f"{'t.message_rowid' if table != 'messages' else 't.id'} WHERE m.account_id = ?",
            (account_id,),
        ).fetchone()[0]
        assert remaining == 0, f"sobrou linha em {table}"


def test_no_password_in_logs_at_any_level(tmp_path, fake_keyring, account_config, caplog):
    """CA-RF-SET-04-1 (RF-SET-04, T-37): varredura de logs após exercitar o fluxo."""
    import logging

    sentinel = "S3nh4-Log-Nao-Pode-Vazar"
    with caplog.at_level(logging.DEBUG):
        run_full_flow_with_password(account_config, sentinel)   # helper de tests/support

    for record in caplog.records:
        assert sentinel not in record.getMessage()
        assert sentinel not in str(record.__dict__)
    for log_file in (tmp_path / "logs").glob("*.log"):
        assert sentinel.encode() not in log_file.read_bytes()
```

### 6.3 `core/storage.py`

**Origem principal:** `03-modelo-de-dados.md` §8.3 (testes de migração obrigatórios) + `CA-RF-SET-03-1`, `CA-RF-SRCH-01-1`, `CA-RF-SRCH-04-1`, `CA-RF-SRCH-05-1`, `CA-RF-MSG-06-1`, `CA-RF-SET-05-1`, `CA-RF-ACC-05-1`, `CA-RF-SRCH-02-1` (T-02, T-08, T-09, T-31, T-38).

#### 6.3.1 Migrações e ciclo de vida

| Teste | Verifica | Origem |
|---|---|---|
| `test_migrate_from_empty_database_reaches_current_version` | Banco novo chega à versão corrente em uma única transação | 03 §8.3 |
| `test_migrate_is_idempotent` | Chamar `migrate()` duas vezes não altera nada e não reinsere em `schema_migrations` | RF-SET-03 |
| `test_migrate_refuses_newer_schema_with_clear_message` | `StorageError` com mensagem clara e **nenhuma escrita** | CA-RF-SET-03-1 |
| `test_failed_migration_leaves_previous_version_intact` | Migração que falha no meio deixa banco íntegro na versão anterior | 03 §8.3 |
| `test_rebuild_table_preserves_row_counts` | `CREATE new`→`INSERT SELECT`→`DROP old`→`RENAME` preserva contagens e `foreign_keys` volta a ON | 03 §8.3 |
| `test_migration_from_v1_golden_database_preserves_all_data` | Banco `fixtures/db/v1_golden.db` migra sem perder linhas | CA-RF-SET-03-1 |
| `test_pragmas_applied_on_every_connection` | `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, `synchronous=NORMAL` em cada conexão nova | 03 §2 |
| `test_foreign_keys_enabled_per_thread_connection` | `ON DELETE CASCADE` funciona em conexão obtida em outra thread | CA-RF-ACC-05-1 |
| `test_delete_account_cascades_all_child_tables` | Apagar conta remove pastas, mensagens, corpos, anexos, política de imagens e ops pendentes | CA-RF-ACC-05-1 |
| `test_delete_account_preserves_outbox_as_draft` | `ON DELETE SET NULL`: o rascunho do usuário sobrevive | RF-SND-04, RNF-REL-01 |

```python
# tests/storage/test_migrations.py
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from core.errors import StorageError
from core.storage import MIGRATIONS, Storage

V1_GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "db" / "v1_golden.db"


@pytest.mark.storage
def test_migrate_from_empty_database_reaches_current_version(tmp_path):
    """03-modelo-de-dados.md §8.3: migração de banco vazio até a versão corrente."""
    storage = Storage(tmp_path / "pymail.db")
    applied = storage.migrate()
    assert applied == max(MIGRATIONS)
    with storage._write_transaction() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert versions == list(range(1, max(MIGRATIONS) + 1))


@pytest.mark.storage
def test_migrate_refuses_newer_schema_with_clear_message(tmp_path):
    """CA-RF-SET-03-1 (RF-SET-03, T-02): versão mais nova é RECUSADA, nunca adivinhada."""
    db = tmp_path / "futuro.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER)")
    conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (max(MIGRATIONS) + 5, int(time.time())))
    conn.commit()
    conn.close()
    before = db.read_bytes()

    with pytest.raises(StorageError) as excinfo:
        Storage(db).migrate()

    assert "Atualize o PyMail Client" in str(excinfo.value)
    assert db.read_bytes() == before, "o banco foi modificado ao recusar a migração"


@pytest.mark.storage
def test_failed_migration_leaves_previous_version_intact(tmp_path, monkeypatch):
    """03 §8.3: migração que falha no meio reverte por completo (DDL é transacional)."""
    db = tmp_path / "pymail.db"
    storage = Storage(db)
    storage.migrate()
    original = max(MIGRATIONS)

    def broken(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE parcial (x INTEGER)")
        raise RuntimeError("falha simulada no meio da migração")

    monkeypatch.setitem(MIGRATIONS, original + 1, broken)
    with pytest.raises(RuntimeError):
        storage.migrate()

    storage2 = Storage(db)
    with storage2._write_transaction() as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert version == original
    assert "parcial" not in tables
    assert storage2.integrity_check() is True


@pytest.mark.storage
def test_migration_from_v1_golden_database_preserves_all_data(tmp_path):
    """CA-RF-SET-03-1: 'preserva todos os dados' precisa de número, não de adjetivo."""
    db = tmp_path / "pymail.db"
    shutil.copy(V1_GOLDEN, db)
    before = _row_counts(db)

    Storage(db).migrate()

    after = _row_counts(db)
    for table in ("accounts", "folders", "messages", "bodies", "outbox"):
        assert after[table] >= before[table], f"{table} perdeu linhas na migração"
    assert after["outbox"] == before["outbox"], "rascunho do usuário perdido (RNF-REL-01)"


def _row_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(db)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("accounts", "folders", "messages", "bodies", "outbox")
        }
    finally:
        conn.close()
```

> **Ativo de teste que ainda não existe:** `tests/fixtures/db/v1_golden.db` precisa ser gerado e **versionado** (banco na versão 1, com duas contas, três pastas, 200 mensagens, 20 corpos, dois rascunhos na outbox). Sem ele, "preserva todos os dados" não é verificável — apenas afirmado. Item L-01 das lacunas.

#### 6.3.2 FTS5, insensibilidade a acentos e segurança de consulta

| Teste | Verifica | Origem |
|---|---|---|
| `test_accent_insensitive_search[acao→Ação, acao→ação, servico→serviço, ...]` | Parametrizado sobre cedilha, til, agudo, circunflexo, em ambos os sentidos | CA-RF-SRCH-01-1 |
| `test_prefix_search_matches_while_typing` | Último termo casa por prefixo (RF-SRCH-02), graças a `prefix='2 3'` | RF-SRCH-02 |
| `test_search_matches_subject_sender_recipients_and_body` | As quatro colunas do índice são pesquisáveis | RF-SRCH-01 |
| `test_build_match_query_never_produces_invalid_syntax[", AND, *, NEAR(, col:valor, -excluir, OR, ()]` | Nenhuma entrada lança exceção nem gera SQL inválido | CA-RF-SRCH-05-1 |
| `test_search_with_punctuation_only_returns_empty_not_error` | `"` e `***` retornam lista vazia, sem exceção | CA-RF-SRCH-05-1 |
| `test_search_filters_combine_with_match` | Conta, pasta, período, não lidos, com anexo e remetente | RF-SRCH-03 |
| `test_fts_index_consistency_query_returns_zero` | A consulta de `03 §5.5` retorna 0 em operação normal | ADR-005 |
| `test_fts_consistency_detects_deliberate_divergence` | Inserir linha órfã no índice faz a verificação acusar — controle positivo | ADR-005 |

```python
# tests/storage/test_fts_accent.py
import pytest

ACCENT_CASES = [
    ("acao", "Ação necessária"),
    ("ACAO", "ação necessária"),
    ("acao", "AÇÃO NECESSÁRIA"),
    ("servico", "serviço indisponível"),
    ("servico", "Serviço indisponível"),
    ("orgao", "órgão público"),
    ("coracao", "coração"),
    ("frequencia", "frequência"),
    ("voce", "você"),
]


@pytest.mark.storage
@pytest.mark.parametrize(("query", "body"), ACCENT_CASES)
def test_accent_insensitive_search(storage, seeded_message, query, body):
    """CA-RF-SRCH-01-1 (RF-SRCH-01, T-08): insensível a acentos e a maiúsculas."""
    rowid = seeded_message(body=body)
    storage.store_body(rowid, raw=None, sanitized_html="<p>x</p>", text_plain=body)

    results = storage.search(query)
    assert [r.id for r in results] == [rowid]


@pytest.mark.storage
@pytest.mark.parametrize(
    "user_input",
    ['"', "AND", "*", "NEAR(", "col:valor", "-excluir", "OR", "()", "***", "a AND (b", "\\", "'", ";--"],
)
def test_build_match_query_never_produces_invalid_syntax(storage, seeded_message, user_input):
    """CA-RF-SRCH-05-1 (RF-SRCH-05, T-08): a sintaxe do FTS5 nunca é digitada pelo usuário."""
    seeded_message(body="conteúdo qualquer")
    result = storage.search(user_input)      # não deve lançar
    assert isinstance(result, list)
```

#### 6.3.3 Atomicidade corpo + índice (rollback nos dois sentidos)

`CA-RF-SRCH-04-1` exige os dois caminhos: falha ao gravar o corpo não pode deixar entrada órfã no índice; falha ao indexar não pode deixar corpo sem índice. A injeção de falha usa o **authorizer** do `sqlite3`, que é API real da biblioteca — não é *mock* do nosso código.

```python
# tests/storage/test_store_body_atomicity.py
from __future__ import annotations

import sqlite3

import pytest

from core.errors import StorageError
from core.storage import Storage

INCONSISTENCIES_SQL = """
SELECT
  (SELECT COUNT(*) FROM bodies b
   WHERE NOT EXISTS (SELECT 1 FROM messages_fts f WHERE f.rowid = b.message_rowid))
+ (SELECT COUNT(*) FROM messages_fts f
   WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.id = f.rowid))
"""


@pytest.fixture
def deny_helper():
    """Instala um authorizer que nega escrita em uma tabela específica."""

    def install(storage: Storage, table: str) -> None:
        def authorizer(action, arg1, arg2, _db, _trigger):
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE) and arg1 == table:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        # `connection_hook` é o seam de teste documentado de Storage (ver L-09).
        storage._conn_for_current_thread().set_authorizer(authorizer)

    return install


@pytest.mark.storage
def test_store_body_rolls_back_when_index_write_fails(storage, seeded_message, deny_helper):
    """CA-RF-SRCH-04-1 (RF-SRCH-04, ADR-005, T-08) — caminho 1: índice falha.

    Exige: nada de corpo sem índice, nada de body_state='cached'.
    """
    rowid = seeded_message(subject="Assunto", body=None)
    deny_helper(storage, "messages_fts")

    with pytest.raises(StorageError):
        storage.store_body(rowid, raw=None, sanitized_html="<p>corpo</p>", text_plain="corpo")

    conn = storage._conn_for_current_thread()
    assert conn.execute("SELECT COUNT(*) FROM bodies WHERE message_rowid = ?", (rowid,)).fetchone()[0] == 0
    assert conn.execute("SELECT body_state FROM messages WHERE id = ?", (rowid,)).fetchone()[0] == "headers"
    assert conn.execute(INCONSISTENCIES_SQL).fetchone()[0] == 0


@pytest.mark.storage
def test_store_body_rolls_back_when_body_write_fails(storage, seeded_message, deny_helper):
    """CA-RF-SRCH-04-1 — caminho 2: corpo falha. Nada de entrada órfã no índice."""
    rowid = seeded_message(subject="Assunto", body=None)
    deny_helper(storage, "bodies")

    with pytest.raises(StorageError):
        storage.store_body(rowid, raw=None, sanitized_html="<p>corpo</p>", text_plain="corpo")

    conn = storage._conn_for_current_thread()
    for table in ("bodies", "messages_fts"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute(INCONSISTENCIES_SQL).fetchone()[0] == 0


@pytest.mark.storage
def test_store_body_reindex_replaces_previous_entry(storage, seeded_message):
    """Regravar o corpo não pode duplicar a linha no índice (DELETE + INSERT por rowid)."""
    rowid = seeded_message(subject="Assunto")
    storage.store_body(rowid, raw=None, sanitized_html="<p>antigo</p>", text_plain="antigo")
    storage.store_body(rowid, raw=None, sanitized_html="<p>novo</p>", text_plain="novo")

    conn = storage._conn_for_current_thread()
    assert conn.execute(
        "SELECT COUNT(*) FROM messages_fts WHERE rowid = ?", (rowid,)
    ).fetchone()[0] == 1
    assert storage.search("antigo") == []
    assert [r.id for r in storage.search("novo")] == [rowid]
```

#### 6.3.4 Despejo LRU em dois níveis, integridade e recuperação

| Teste | Verifica | Origem |
|---|---|---|
| `test_evict_level1_clears_html_keeps_text_and_headers` | `html_sanitized` zerado, `body_state='evicted'`, `text_plain` e o cabeçalho intactos | CA-RF-MSG-06-1 |
| `test_evict_level1_keeps_search_working` | Busca continua encontrando a mensagem após o nível 1 | CA-RF-MSG-06-1, 03 §6.2 |
| `test_evict_level1_reclaims_bytes_below_target` | Soma de `size_bytes` fica ≤ alvo | CA-RF-MSG-06-1 |
| `test_evict_level2_removes_body_row_but_keeps_fts_entry` | Linha de `bodies` apagada; índice preservado; cabeçalho preservado | CA-RF-MSG-06-1, 03 §6.4 |
| `test_evict_never_touches_outbox_or_pending_ops` | Rascunhos, outbox e ops pendentes intactos sob pressão extrema | RNF-REL-01, 02 §1 |
| `test_evict_is_lru_order` | A vítima é a de menor `last_access_at`, e ler a mensagem a protege | CA-RF-MSG-06-1 |
| `test_evict_runs_off_gui_thread` | O despejo é executado no `TaskPool`, nunca na GUI | CA-RNF-PERF-01-1, 03 §6.4 |
| `test_quick_check_detects_truncated_database` | `quick_check` falha em arquivo truncado | CA-RF-SET-05-1 |
| `test_corruption_recovery_exports_outbox_before_renaming` | Ordem obrigatória de 03 §8.2, com arquivo exportado legível | CA-RF-SET-05-1 |
| `test_corruption_recovery_renames_instead_of_deleting` | Banco corrompido renomeado com timestamp; evidência preservada | CA-RF-SET-05-1 |
| `test_corruption_recovery_notifies_user_with_path` | Notificação menciona o caminho do arquivo exportado | CA-RF-SET-05-1 |
| `test_thread_local_connections_are_distinct` | Conexões distintas por thread (ADR-006) | 03 §2 |
| `test_write_transaction_retries_on_sqlite_busy` | `SQLITE_BUSY` gera nova tentativa limitada e não chega à UI como erro fatal | 03 §2, ADR-006 |

```python
# tests/storage/test_cache_eviction.py
from __future__ import annotations

import time

import pytest

from core.storage import Storage


def _store_cached(storage, rowid, *, html_size, text="texto", accessed_at=None):
    storage.store_body(rowid, raw=None,
                       sanitized_html="<p>" + ("h" * html_size) + "</p>",
                       text_plain=text)
    if accessed_at is not None:
        with storage._write_transaction() as conn:
            conn.execute("UPDATE bodies SET last_access_at = ? WHERE message_rowid = ?",
                         (accessed_at, rowid))


@pytest.mark.storage
def test_evict_level1_clears_html_keeps_text_and_headers(storage, seeded_message):
    """CA-RF-MSG-06-1 (RF-MSG-06, T-09): LRU de nível 1 preserva cabeçalho e busca."""
    now = int(time.time())
    ids = [seeded_message(subject=f"Assunto {i}") for i in range(5)]
    for offset, rowid in enumerate(ids):
        _store_cached(storage, rowid, html_size=10_000, text=f"corpo unico {offset}",
                      accessed_at=now - (100 - offset))

    target = sum(10_000 for _ in ids[:2])          # força remover os três mais antigos
    removed = storage.evict_bodies_lru(target_bytes=target)

    conn = storage._conn_for_current_thread()
    assert removed == 3
    for rowid in ids[:3]:                          # mais antigos
        html, text, state = conn.execute(
            "SELECT html_sanitized, text_plain, (SELECT body_state FROM messages WHERE id = ?)"
            " FROM bodies WHERE message_rowid = ?", (rowid, rowid)
        ).fetchone()
        assert html is None
        assert text is not None                    # texto plano permanece
        assert state == "evicted"
        # Cabeçalho intacto e busca funcionando — 03 §6.2
        assert conn.execute("SELECT subject FROM messages WHERE id = ?", (rowid,)).fetchone()[0]
    assert storage.search("unico") != []


@pytest.mark.storage
def test_evict_level2_removes_body_row_but_keeps_fts_entry(storage, seeded_message):
    """CA-RF-MSG-06-1 / 03 §6.4 nível 2: sob pressão severa, o índice SOBREVIVE."""
    ids = [seeded_message(subject=f"Assunto {i}") for i in range(3)]
    for offset, rowid in enumerate(ids):
        _store_cached(storage, rowid, html_size=5_000, text=f"texto plano {offset}",
                      accessed_at=int(time.time()) - (10 - offset))
    with storage._write_transaction() as conn:
        for rowid in ids:
            conn.execute("UPDATE bodies SET html_sanitized = NULL WHERE message_rowid = ?", (rowid,))

    storage.evict_bodies_lru(target_bytes=0, level=2)

    conn = storage._conn_for_current_thread()
    assert conn.execute("SELECT COUNT(*) FROM bodies").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3
    assert storage.search("plano") != []           # a busca continua achando (03 §6.2)
```

```python
# tests/storage/test_corruption_recovery.py
@pytest.mark.storage
def test_corruption_recovery_exports_outbox_before_renaming(tmp_path):
    """CA-RF-SET-05-1 (RF-SET-05, RNF-REL-02, T-38): ordem obrigatória de 03 §8.2.

    A prioridade é o dado do usuário: o rascunho é exportado ANTES de o banco
    corrompido ser afastado.
    """
    import json

    db = tmp_path / "pymail.db"
    storage = Storage(db)
    storage.migrate()
    account_id = storage.upsert_account(account_config_fixture())
    storage.enqueue_outgoing(draft_fixture(account_id, subject="Rascunho precioso"))
    storage.close_thread_connection()

    with db.open("r+b") as fh:                     # trunca: corrupção de verdade
        fh.truncate(4_096)

    result = Storage.recover(db, data_dir=tmp_path)

    assert result.corrupted_backup is not None
    assert result.corrupted_backup.exists()        # renomeado, não apagado
    assert "corrompido" in result.corrupted_backup.name
    exported = json.loads(result.exported_outbox.read_text(encoding="utf-8"))
    assert any(d["subject"] == "Rascunho precioso" for d in exported["outbox"])
    assert Storage(db).integrity_check() is True   # banco novo, sadio
```

#### 6.3.5 Desempenho da busca

```python
# tests/storage/test_search_perf.py
import time

import pytest

CI_MARGIN = 3.0            # margem declarada em CA-RF-SRCH-02-1
BUDGET_MS = 100.0


@pytest.mark.storage
@pytest.mark.perf
@pytest.mark.slow
@pytest.mark.serial
def test_search_two_words_under_budget_with_50k_messages(storage_50k):
    """CA-RF-SRCH-02-1 (RF-SRCH-02, RNF-PERF-04, T-31): duas palavras em < 100 ms."""
    storage = storage_50k
    measured: list[float] = []
    for _ in range(5):                     # melhor de 5: o CI é ruidoso, o produto não
        start = time.monotonic()
        results = storage.search("nota fiscal")
        measured.append((time.monotonic() - start) * 1000.0)
        assert results

    best = min(measured)
    budget = BUDGET_MS * (CI_MARGIN if os.environ.get("CI") else 1.0)
    assert best < budget, f"busca levou {best:.1f} ms (orçamento {budget:.0f} ms)"
```

A margem de 3× é a declarada em `CA-RF-SRCH-02-1` ("medido no teste, com margem de 3× em CI"). Justificativa em §10.6. O alvo de produto continua sendo 100 ms; o job noturno mede sem margem e registra o número real.

### 6.4 `core/network/imap_client.py` — suíte de contrato

**Origem:** `CA-RF-MSG-01-1`, `CA-RF-MSG-02-1`, `CA-RF-MSG-04-1`, `CA-RF-MSG-08-1`, `CA-RF-ORG-01-1`, `CA-RF-ORG-05-1`, `CA-RF-SND-*`, `CA-RNF-SEC-02-1`, `CA-RNF-SEC-04-1` (T-10 a T-17, T-20, T-21).

O contrato de `02-arquitetura.md` §5.1 é testado **uma vez**, numa suíte parametrizada por implementação. A fase 2 acrescenta `PopIncomingClient` a `IMPLEMENTATIONS` e herda os testes de graça: é isso que torna o ponto de extensão de §9 do documento de arquitetura verificável.

```python
# tests/network/test_incoming_contract.py
from __future__ import annotations

import pytest

from core.network.imap_client import ImapIncomingClient
from tests.fakes.fake_imap_server import FakeImapServer, FakeMailbox

# [F2] acrescenta PopIncomingClient aqui, sem tocar nos testes.
IMPLEMENTATIONS = ["imap"]


@pytest.fixture(params=IMPLEMENTATIONS)
def incoming(request, fake_imap_server_populated, account_config):
    if request.param == "imap":
        return ImapIncomingClient(account_config, port=fake_imap_server_populated.port)
    raise AssertionError(f"implementação sem fábrica: {request.param}")


@pytest.mark.network
def test_fetch_headers_never_downloads_a_body(incoming, fake_imap_server_populated):
    """CA-RF-MSG-01-1 (RF-MSG-01, T-10, T-11): zero FETCH de corpo na sincronização."""
    incoming.connect()
    incoming.select_folder("INBOX")
    headers = incoming.fetch_headers(1, 200)
    incoming.close()

    assert len(headers) == 200
    server = fake_imap_server_populated
    assert server.body_fetch_count() == 0, (
        "comandos que baixaram corpo: "
        f"{server.body_fetch_uids} — CA-RF-MSG-01-1 exige ZERO"
    )
    assert all(h.remote_id for h in headers)


@pytest.mark.network
def test_fetch_body_issues_exactly_one_fetch_for_that_uid(incoming, fake_imap_server_populated):
    """CA-RF-MSG-02-1 (RF-MSG-02, T-12): exatamente um FETCH, para o UID pedido."""
    incoming.connect()
    incoming.select_folder("INBOX")
    incoming.fetch_body("7")
    incoming.close()

    server = fake_imap_server_populated
    assert server.body_fetch_uids == [7]


@pytest.mark.network
def test_uidvalidity_change_is_visible_as_new_status(incoming, fake_imap_server_populated):
    """CA-RF-MSG-04-1 (RF-MSG-04, T-11): UIDVALIDITY novo invalida o cache da pasta."""
    incoming.connect()
    first = incoming.select_folder("INBOX")
    incoming.close()

    fake_imap_server_populated.set_uidvalidity("INBOX", first.uidvalidity + 1)

    incoming.connect()
    second = incoming.select_folder("INBOX")
    assert second.uidvalidity != first.uidvalidity


@pytest.mark.network
def test_move_uses_uid_move_when_server_supports_it(incoming, fake_imap_server_populated):
    """CA-RF-ORG-01-1 (RF-ORG-01/05, T-17) — metade 1: MOVE habilitado."""
    incoming.connect()
    incoming.select_folder("INBOX")
    assert incoming.supports("MOVE")
    incoming.move(["1", "2"], "Archive")
    incoming.close()

    names = fake_imap_server_populated.command_names()
    assert "MOVE" in names
    assert "COPY" not in names, "CA-RF-ORG-01-1 proíbe COPY quando MOVE existe"


@pytest.mark.network
def test_move_falls_back_to_copy_store_expunge(incoming, no_move_server, account_config):
    """CA-RF-ORG-01-1 — metade 2: sem MOVE, a sequência alternativa é emitida."""
    client = ImapIncomingClient(account_config, port=no_move_server.port)
    client.connect()
    client.select_folder("INBOX")
    assert not client.supports("MOVE")
    client.move(["1", "2"], "Archive")
    client.close()

    names = no_move_server.command_names()
    assert "COPY" in names and "STORE" in names and "EXPUNGE" in names
    assert "MOVE" not in names


@pytest.mark.network
def test_expunge_failure_is_reported_not_swallowed(no_move_server, account_config):
    """CA-RF-ORG-05-1 (RF-ORG-05, T-17): falha no EXPUNGE não pode passar em silêncio."""
    client = ImapIncomingClient(account_config, port=no_move_server.port)
    client.connect()
    client.select_folder("INBOX")
    no_move_server.fail_command("EXPUNGE", "NO [SERVERBUG] expunge failed")

    with pytest.raises(MailError) as excinfo:
        client.move(["1"], "Archive")
    assert "expunge" in str(excinfo.value).lower()


@pytest.mark.network
def test_connection_drop_mid_sync_raises_network_error(fake_imap_server_populated, account_config):
    """CA-RF-MSG-08-1 (RF-MSG-08, T-15): queda no meio da sincronização vira NetworkError."""
    client = ImapIncomingClient(account_config, port=fake_imap_server_populated.port)
    client.connect()
    client.select_folder("INBOX")
    fake_imap_server_populated.drop_after_n_commands(4)

    with pytest.raises(NetworkError):
        for start in range(1, 1_000, 200):
            client.fetch_headers(start, 200)


@pytest.mark.network
def test_wait_for_changes_uses_idle_when_available(fake_imap_server_populated, account_config):
    """RF-MSG-05 (T-14): IDLE entra em IDLE de verdade."""
    client = ImapIncomingClient(account_config, port=fake_imap_server_populated.port)
    client.connect()
    client.select_folder("INBOX")
    fake_imap_server_populated.idle_release.set()
    client.wait_for_changes(1.0)
    assert fake_imap_server_populated.idle_entered.is_set()


@pytest.mark.network
def test_wait_for_changes_falls_back_to_polling_when_idle_refused(idle_refusing_server, account_config):
    """RF-MSG-05 (T-14): servidor recusa IDLE → NOOP + UID SEARCH, sem exceção."""
    client = ImapIncomingClient(account_config, port=idle_refusing_server.port)
    client.connect()
    client.select_folder("INBOX")
    client.wait_for_changes(0.2)

    names = idle_refusing_server.command_names()
    assert "IDLE" in names                      # tentou…
    assert "NOOP" in names and "SEARCH" in names  # …e caiu para polling


@pytest.mark.network
def test_self_signed_certificate_is_rejected_with_explanation(tls_server_self_signed, account_config):
    """CA-RNF-SEC-02-1 (RNF-SEC-02, T-04, T-27): nunca prosseguir sem validar o certificado."""
    client = ImapIncomingClient(account_config, host="127.0.0.1", port=tls_server_self_signed.port)
    with pytest.raises(TLSError) as excinfo:
        client.connect()
    assert "certificado" in str(excinfo.value).lower()
```

### 6.5 `core/network/smtp_client.py` e fila de envio (outbox)

**Origem:** `CA-RF-SND-03-1`, `CA-RF-SND-03-2`, `CA-RF-SND-04-1`, `CA-RF-SND-05-1`, `CA-RF-SND-07-1`, RF-SND-01/02/06/08 (T-24 a T-30).

| Teste | Verifica | Origem |
|---|---|---|
| `test_cancel_within_undo_window_never_opens_smtp_connection` | `state='canceled'` e **zero** conexões TCP no servidor falso | CA-RF-SND-03-1 |
| `test_send_after_window_transmits_exactly_once` | Uma conexão, uma mensagem, `state='sent'` | CA-RF-SND-03-2 |
| `test_message_id_stable_between_queue_and_send` | O `Message-ID` da outbox é o mesmo no cabeçalho transmitido | CA-RF-SND-03-2 |
| `test_restart_with_queued_message_sends_after_deadline` | Processo novo, `send_at` vencido → envio ocorre | CA-RF-SND-04-1 |
| `test_restart_within_grace_period_still_sends` | Dentro da carência de 24 h, o envio ocorre | CA-RF-SND-04-1 |
| `test_restart_beyond_grace_marks_failed_with_notification` | Após a carência, `state='failed'` com notificação — nunca desaparece sem rastro | CA-RF-SND-04-1 |
| `test_smtp_refusal_keeps_message_visible_with_server_text` | `state='failed'`, `last_error`/`smtp_response` com o texto do servidor, ação de reenvio | CA-RF-SND-05-1 |
| `test_resend_after_failure_increments_attempts_and_can_succeed` | Reenvio funciona e não duplica o `Message-ID` já enviado | CA-RF-SND-05-1, RNF-REL-01 |
| `test_insecure_outgoing_refused_by_default` | Porta sem TLS recusa o envio com mensagem explícita | CA-RF-SND-07-1 |
| `test_insecure_outgoing_allowed_only_with_recorded_exception` | `allow_insecure_outgoing=1` → envia, e o fato é registrado | CA-RF-SND-07-1 |
| `test_oversized_attachment_requires_confirmation` | > 20 MB exige confirmação explícita | RF-SND-06 |
| `test_reply_sets_in_reply_to_and_references` | Cabeçalhos de encadeamento corretos | RF-SND-02 |
| `test_missing_subject_or_recipient_warns_but_allows_send` | Alerta sem bloquear | RF-SND-08 |
| `test_draft_persists_across_restart` | Rascunho sobrevive ao reinício | RF-SND-04, RNF-REL-01 |

O teste de `CA-RF-SND-03-1` é o mais importante da seção, e o único que pode provar a afirmação "cancelar não abre conexão alguma":

```python
# tests/network/test_smtp_undo_window.py
from __future__ import annotations

import pytest

from core.network.smtp_client import OutboxScheduler
from core.storage import Storage
from tests.fakes.fake_smtp_server import FakeSmtpServer
from tests.support.clock import FakeClock


@pytest.fixture
def smtp_server() -> FakeSmtpServer:
    server = FakeSmtpServer()
    yield server
    server.stop()


@pytest.mark.network
@pytest.mark.timeout(30)
def test_cancel_within_undo_window_never_opens_smtp_connection(
    storage, smtp_server, account_config, make_draft, fake_keyring,
):
    """CA-RF-SND-03-1 (RF-SND-03, T-27, T-28).

    Afirmação literal do critério: cancelar dentro da janela impede QUALQUER
    conexão SMTP. A asserção é sobre `connection_count` — não sobre mensagens
    transmitidas —, porque uma conexão aberta já é a falha que o critério proíbe.

    Determinismo: o relógio é injetado. Não há `time.sleep(10)`.
    """
    clock = FakeClock(start=1_000_000.0)
    account_id = storage.upsert_account(account_config)
    outbox_id = storage.enqueue_outgoing(make_draft(account_id))
    scheduler = OutboxScheduler(
        storage=storage, account=account_config, clock=clock,
        smtp_host="127.0.0.1", smtp_port=smtp_server.port, undo_window_s=10.0,
    )

    # 1) Dentro da janela: nada acontece, nem mesmo uma conexão.
    clock.advance(5.0)
    scheduler.tick()
    assert smtp_server.connection_count == 0

    # 2) O usuário cancela.
    scheduler.cancel(outbox_id)
    assert storage.get_outgoing(outbox_id).state == "canceled"

    # 3) Avançar MUITO além do prazo não pode ressuscitar o envio.
    clock.advance(3_600.0)
    for _ in range(5):
        scheduler.tick()

    assert smtp_server.connection_count == 0, (
        "CA-RF-SND-03-1 violado: uma conexão SMTP foi aberta após o cancelamento"
    )
    assert smtp_server.messages == []
    assert storage.get_outgoing(outbox_id).state == "canceled"


@pytest.mark.network
def test_send_after_window_transmits_exactly_once(
    storage, smtp_server, account_config, make_draft,
):
    """CA-RF-SND-03-2 (RF-SND-03, T-28): enviada exatamente uma vez, ID estável."""
    clock = FakeClock(start=2_000_000.0)
    account_id = storage.upsert_account(account_config)
    draft = make_draft(account_id)
    outbox_id = storage.enqueue_outgoing(draft)
    queued_message_id = storage.get_outgoing(outbox_id).message_id
    scheduler = OutboxScheduler(storage=storage, account=account_config, clock=clock,
                                smtp_host="127.0.0.1", smtp_port=smtp_server.port,
                                undo_window_s=10.0)

    clock.advance(11.0)
    scheduler.tick()
    scheduler.tick()          # idempotência: ticks repetidos não reenviam
    scheduler.tick()

    assert smtp_server.connection_count == 1
    assert len(smtp_server.messages) == 1
    assert f"Message-ID: {queued_message_id}".encode() in smtp_server.messages[0]
    assert storage.get_outgoing(outbox_id).state == "sent"
```

### 6.6 `core/tasks.py`

**Origem:** base de `CA-RNF-PERF-01-1`, `CA-RF-ACC-02-1`, RF-MSG-03; guardas de ADR-001 e do §4 de `02-arquitetura.md` (T-10, T-13, T-39).

| Teste | Verifica | Origem |
|---|---|---|
| `test_submitted_command_runs_on_worker_thread_not_gui` | A identidade da thread de execução é a da `AccountWorker` | CA-RNF-PERF-01-1 |
| `test_no_work_executes_on_gui_thread` | Nenhuma tarefa do pool ou da fila roda na thread da GUI | CA-RNF-PERF-01-1 |
| `test_commands_run_serially_per_account` | Ordem da fila preservada; nunca duas em paralelo na mesma conexão | ADR-001 |
| `test_cancellation_is_cooperative_and_reports_partial` | Token cancelado encerra no ponto de verificação e reporta conclusão parcial válida | 02 §4 |
| `test_cancelled_command_raises_operation_cancelled_not_notified` | `OperationCancelled` silencioso por definição | 02 §7 |
| `test_exception_propagates_through_failed_signal` | Exceção no worker vira `failed` com `MailError` classificado, sem derrubar a thread | 02 §4, §7 |
| `test_worker_survives_exception_and_accepts_next_command` | Após erro, a fila continua funcionando | 02 §7 |
| `test_one_account_failure_does_not_affect_others` | Três workers; um com `AuthError`; os outros dois sincronizam | CA-RF-ACC-02-1 |
| `test_signal_payloads_are_immutable` | Toda dataclass entregue por sinal é congelada (tentativa de mutação falha) | 02 §4 |
| `test_pool_never_receives_the_imap_client` | Assinatura do pool aceita apenas dados imutáveis | ADR-001, 02 §4 |

```python
# tests/tasks/test_no_gui_thread_work.py
from __future__ import annotations

import threading

import pytest

from core.tasks import AccountWorker, TaskPool


@pytest.mark.threaded
@pytest.mark.serial
def test_task_pool_executes_off_the_gui_thread(qtbot, fake_storage):
    """Base de CA-RNF-PERF-01-1 (RNF-PERF-01, T-39)."""
    gui_ident = threading.get_ident()
    seen: list[int] = []
    done = threading.Event()

    pool = TaskPool(max_threads=4)
    pool.submit(lambda: (seen.append(threading.get_ident()), done.set()))
    qtbot.waitUntil(lambda: done.is_set(), timeout=5_000)
    pool.waitForDone(1_000)

    assert seen and seen[0] != gui_ident
    assert threading.get_ident() == gui_ident     # a thread do teste é a da GUI (qtbot)


@pytest.mark.threaded
def test_account_worker_runs_commands_serially(qtbot, fake_storage):
    """ADR-001 / 02 §4: a fila de uma conta é serializada, e o dono é a worker."""
    order: list[str] = []
    owner: list[int] = []

    worker = AccountWorker(account_id=1, client=None, storage=fake_storage, pool=None)
    for i in range(20):
        worker.submit(lambda i=i: (order.append(f"cmd{i}"), owner.append(threading.get_ident())))
    worker.start()
    qtbot.waitUntil(lambda: len(order) == 20, timeout=10_000)

    assert order == [f"cmd{i}" for i in range(20)]
    assert set(owner) == {worker.current_thread_id()}
    worker.shutdown()


@pytest.mark.threaded
def test_mail_error_is_emitted_as_classified_failure_not_crash(qtbot):
    """02 §7: a taxonomia de erros chega à UI classificada."""
    from core.errors import AuthError

    failures: list[Exception] = []
    worker = AccountWorker(account_id=1, client=None, storage=None, pool=None)
    worker.failed.connect(lambda _acc, err: failures.append(err))
    worker.submit(lambda: (_ for _ in ()).throw(AuthError("credencial inválida")))
    worker.start()
    qtbot.waitUntil(lambda: bool(failures), timeout=5_000)

    assert isinstance(failures[0], AuthError)
    assert worker.state == "error"
    worker.shutdown()
```

### 6.7 `ui/` — o que é testável com `pytest-qt` e o que não é

**Origem:** `CA-RF-UI-03-1`, `CA-RF-UI-04-1`, `CA-RF-UI-05-1`, `CA-RF-UI-06-1`, `CA-RF-RD-06-1`, `CA-RF-RD-07-1`, RF-UI-01/02/07/08/11 (T-32 a T-36).

#### 6.7.1 Testável

| Teste | Verifica | Origem |
|---|---|---|
| `test_letter_shortcuts_fire_with_focus_on_list` | `C`, `E`, `Backspace`, `D`, `Delete`, `/`, `J`, `K` produzem o efeito esperado | CA-RF-UI-03-1 |
| `test_letter_shortcuts_ignored_when_focus_in_text_field` | Com foco no compositor ou na busca, o atalho **não** dispara | CA-RF-UI-04-1, CA-RF-UI-03-1 |
| `test_typing_c_in_search_field_inserts_letter_and_does_not_compose` | O caso literal do critério | CA-RF-UI-04-1 |
| `test_escape_returns_focus_to_list_and_reactivates_shortcuts` | `Esc` em campo de texto devolve o foco e reativa os atalhos | CA-RF-UI-04-1 |
| `test_archive_removes_row_and_enqueues_pending_op` | Interface reflete a ação antes da resposta do servidor | CA-RF-MSG-09-1, CA-RF-ORG-04-1 |
| `test_archive_shortcut_does_not_fire_with_focus_in_composer` | Guarda de foco no caminho destrutivo | CA-RF-UI-03-1 |
| `test_bulk_archive_of_50_messages_produces_fifty_pending_ops` | 50 movimentos, um único progresso agregado | CA-RF-ORG-04-1 |
| `test_list_model_is_a_qabstractlistmodel_not_a_widget_per_message` | O modelo não cria item de interface por mensagem | CA-RF-UI-05-1 |
| `test_paint_calls_bounded_by_visible_area` | Durante a rolagem, o delegate pinta apenas visíveis + margem | CA-RF-UI-05-1 |
| `test_theme_switch_applies_without_reloading_list` | Troca de tema não reconstrói o modelo nem perde seleção | CA-RF-UI-06-1 |
| `test_manual_theme_overrides_system_and_persists` | Preferência manual sobrepõe o sistema e sobrevive ao reinício | CA-RF-UI-06-1 |
| `test_sidebar_collapse_state_persists` | Estado colapsado persiste entre sessões | RF-UI-02 |
| `test_empty_loading_and_error_states_render_text` | Nunca área em branco sem explicação | RF-UI-07 |
| `test_network_error_shown_non_modally_with_action` | Erro de rede não abre diálogo modal e traz ação sugerida | RF-UI-08 |
| `test_list_row_shows_preview_fields` | Remetente, assunto, trecho, data, não lido, sinalizado, anexo | RF-UI-11 |
| `test_link_confirmation_shows_real_host_not_anchor_text` | A confirmação mostra `exemplo.com`, não `banco-falso.com` | CA-RF-RD-07-1 |
| `test_reader_signals_loading_before_content` | Retorno visual imediato antes da rede | RNF-USA-02, RF-UI-07 |
| `test_privacy_interceptor_blocks_non_image_resources` | CSS remoto, fonte, XHR, mídia: bloqueados e registrados | CA-RF-RD-06-1 |

```python
# tests/gui/test_shortcuts.py
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

pytestmark = [pytest.mark.gui, pytest.mark.serial]


@pytest.fixture
def window(qtbot, storage_with_messages, fake_incoming):
    from ui.main_window import MainWindow

    win = MainWindow(storage=storage_with_messages, client=fake_incoming)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def test_typing_c_in_search_field_inserts_letter_and_does_not_compose(window, qtbot):
    """CA-RF-UI-04-1 (RF-UI-04, T-34) — o caso literal do critério.

    Digitar `c` dentro do campo de busca insere a letra `c` e NÃO abre o
    compositor; `Esc` devolve o foco à lista e reativa os atalhos.
    """
    window.search_bar.setFocus()
    qtbot.keyClicks(window.search_bar, "c")
    assert window.search_bar.text() == "c"
    assert window.composer.isVisible() is False

    qtbot.keyClick(window.search_bar, Qt.Key.Key_Escape)
    assert window.message_list.hasFocus()

    qtbot.keyClick(window.message_list, Qt.Key.Key_C)
    assert window.composer.isVisible() is True


def test_letter_shortcuts_ignored_when_focus_in_composer_body(window, qtbot):
    """CA-RF-UI-03-1 / CA-RF-UI-04-1: `e` no corpo do compositor é texto, não arquivar."""
    window.composer.open_new()
    body = window.composer.body_edit
    body.setFocus()
    qtbot.keyClicks(body, "e")
    assert body.toPlainText() == "e"
    assert window.storage.count_pending_ops() == 0


def test_archive_shortcut_removes_row_and_enqueues_pending_op(window, qtbot):
    """CA-RF-MSG-09-1 / CA-RF-ORG-04-1: estado visível primeiro, servidor depois."""
    window.message_list.setFocus()
    window.message_list.setCurrentIndex(window.message_list.model().index(0, 0))
    target_id = window.message_list.model().message_id_at(0)
    before = window.message_list.model().rowCount()

    qtbot.keyClick(window.message_list, Qt.Key.Key_E)

    assert window.message_list.model().rowCount() == before - 1
    assert window.storage.pending_ops_for_message(target_id) is not None
```

```python
# tests/gui/test_message_list_model.py
class CountingDelegate(QStyledItemDelegate):
    """Conta quantas vezes a pintura é pedida: é a medida de virtualização."""

    def __init__(self) -> None:
        super().__init__()
        self.paint_count = 0

    def paint(self, painter, option, index) -> None:
        self.paint_count += 1
        return super().paint(painter, option, index)


@pytest.mark.gui
@pytest.mark.serial
def test_paint_calls_bounded_by_visible_area(qtbot, storage_with_messages_50k):
    """CA-RF-UI-05-1 (RF-UI-05, T-35): a contagem de widgets/pinturas é limitada
    à área visível mais uma margem, e não cresce com o total de 50.000."""
    from ui.components.message_list import MessageListView, MessageListModel

    view = MessageListView()
    qtbot.addWidget(view)
    view.resize(900, 600)
    view.setModel(MessageListModel(storage_with_messages_50k, folder_id=1, page_size=200))
    delegate = CountingDelegate()
    view.setItemDelegate(delegate)
    view.show()
    qtbot.waitExposed(view)

    assert isinstance(view.model(), MessageListModel)
    assert view.model().rowCount() <= 200          # página, não 50.000

    visible = view.viewport().height() // view.sizeHintForRow(0) + 1
    for _ in range(10):
        view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 300)
        qtbot.wait(20)
    assert delegate.paint_count <= 10 * (visible + 3), (
        f"pinturas={delegate.paint_count} para {visible} linhas visíveis: "
        "a lista não está virtualizada"
    )
```

#### 6.7.2 Não testável automaticamente — declarado, com substituto

| O que não é testável | Por quê | Substituto |
|---|---|---|
| Aparência renderizada do HTML (flexbox, grid, media queries) | `offscreen` não tem compositor real; a asserção sobre pixel é frágil e não reproduz o monitor do usuário | MV-01 (§11.1) |
| Qualidade visual dos temas claro/escuro, contraste real | Depende de métricas de fonte e da tela; `offscreen` mente | MV-03 (§11.3) + verificação de contraste por cálculo (o único pedaço automatizável: W3C contrast ratio sobre as cores do QSS) |
| Anel de foco visível (RNF-A11Y-01) | Visibilidade é percepção; `offscreen` não desenha | MV-05 + revisão de QSS |
| Rolagem fluida com 50.000 itens | Fluidez é temporal e depende da GPU | Contagem de pinturas (automatizada) + MV-01 |
| Detecção do tema do SO em tempo real | Exige mudar a configuração do sistema operacional | Teste do *slot* que reage à mudança (automatizado); a detecção real em MV-03 |
| Diálogos nativos do SO (seleção de arquivo, notificação) | Bloqueiam o teste e variam por plataforma | Dublê na fronteira + MV-05 |
| Consumo de memória e tamanho do pacote | Dependem da máquina e do PyInstaller | MV-04 (§11.4) |
| Um usuário operando tudo pelo teclado | É um fluxo humano de ponta a ponta | MV-05 (§11.5), com roteiro de teclas |

### 6.8 Rastreabilidade critério → teste

| Critério de aceite | Requisito (tarefa) | Teste | Tipo |
|---|---|---|---|
| CA-RF-ACC-01-1 | RF-ACC-01 (T-03, T-04) | `test_credential_roundtrip_uses_keyring_only`, `test_session_restored_after_restart` | network/unit |
| CA-RF-ACC-02-1 | RF-ACC-02 (T-02, T-18) | `test_one_account_failure_does_not_affect_others` | threaded |
| CA-RF-ACC-03-1 | RF-ACC-03 (T-04) | `test_connection_error_messages_distinguish_dns_refused_and_auth` | network |
| CA-RF-ACC-04-1 | RF-ACC-04 (T-03) | `test_fake_auth_provider_authenticates_without_touching_ui_or_storage` | unit/network |
| CA-RF-ACC-05-1 | RF-ACC-05 (T-19) | `test_credential_removed_when_account_deleted`, `test_deleted_account_leaves_no_rows_in_any_table` | storage |
| CA-RF-MSG-01-1 | RF-MSG-01 (T-10, T-11) | `test_fetch_headers_never_downloads_a_body` | network |
| CA-RF-MSG-01-2 | RF-MSG-01 (T-10, T-11) | `test_header_sync_database_size_below_5mb` | storage |
| CA-RF-MSG-02-1 | RF-MSG-02 (T-12) | `test_fetch_body_issues_exactly_one_fetch_for_that_uid` | network |
| CA-RF-MSG-04-1 | RF-MSG-04 (T-11) | `test_uidvalidity_change_is_visible_as_new_status`, `test_folder_invalidation_drops_old_uids_without_duplicates` | network/storage |
| CA-RF-MSG-06-1 | RF-MSG-06 (T-09) | `test_evict_level1_*`, `test_evict_level2_*` | storage |
| CA-RF-MSG-08-1 | RF-MSG-08 (T-15) | `test_connection_drop_mid_sync_raises_network_error`, `test_reconnect_completes_sync_without_corruption` | network/threaded |
| CA-RF-MSG-09-1 | RF-MSG-09 (T-16) | `test_archive_removes_row_and_enqueues_pending_op`, `test_pending_op_replayed_when_connection_returns` | gui/network |
| CA-RF-RD-01-1 | RF-RD-01 (T-05) | `test_sanitize_removes_all_forbidden_markup` (parametrizado) | unit |
| CA-RF-RD-03-1 | RF-RD-03 (T-07, T-22) | `test_sanitized_output_has_no_active_remote_references`, `test_rendering_corpus_produces_zero_network_requests` | unit/gui |
| CA-RF-RD-03-2 | RF-RD-03 (T-07, T-22) | `test_sender_authorization_applies_only_to_that_sender_and_persists` | storage/gui |
| CA-RF-RD-04-1 | RF-RD-04 (T-05, T-07) | `test_sanitize_removes_tracking_pixels_even_when_images_allowed` | unit |
| CA-RF-RD-06-1 | RF-RD-06 (T-07, T-20) | `test_privacy_interceptor_blocks_and_records_non_image_resources` | gui |
| CA-RF-RD-07-1 | RF-RD-07 (T-20) | `test_link_confirmation_shows_real_host_not_anchor_text` | unit/gui |
| CA-RF-SND-03-1 | RF-SND-03 (T-27, T-28) | `test_cancel_within_undo_window_never_opens_smtp_connection` | network |
| CA-RF-SND-03-2 | RF-SND-03 (T-27, T-28) | `test_send_after_window_transmits_exactly_once`, `test_message_id_stable_between_queue_and_send` | network |
| CA-RF-SND-04-1 | RF-SND-04 (T-26, T-29) | `test_restart_with_queued_message_*`, `test_draft_persists_across_restart` | storage |
| CA-RF-SND-05-1 | RF-SND-05 (T-30) | `test_smtp_refusal_keeps_message_visible_with_server_text` | network |
| CA-RF-SND-07-1 | RF-SND-07 (T-27) | `test_insecure_outgoing_refused_by_default` | network |
| CA-RF-SRCH-01-1 | RF-SRCH-01 (T-08) | `test_accent_insensitive_search` (parametrizado) | storage |
| CA-RF-SRCH-02-1 | RF-SRCH-02 (T-31) | `test_search_two_words_under_budget_with_50k_messages` | perf |
| CA-RF-SRCH-04-1 | RF-SRCH-04 (T-08) | `test_store_body_rolls_back_when_*` (dois sentidos) | storage |
| CA-RF-SRCH-05-1 | RF-SRCH-05 (T-08) | `test_build_match_query_never_produces_invalid_syntax` | storage |
| CA-RF-ORG-01-1 | RF-ORG-01/05 (T-17) | `test_move_uses_uid_move_when_server_supports_it`, `test_move_falls_back_to_copy_store_expunge` | network |
| CA-RF-ORG-04-1 | RF-ORG-04 (T-17) | `test_bulk_archive_of_50_messages_produces_fifty_pending_ops` | gui/storage |
| CA-RF-ORG-05-1 | RF-ORG-05 (T-17) | `test_expunge_failure_is_reported_not_swallowed`, `test_reconciliation_after_failed_expunge` | network |
| CA-RF-UI-03-1 | RF-UI-03 (T-34) | `test_letter_shortcuts_fire_with_focus_on_list` | gui |
| CA-RF-UI-04-1 | RF-UI-04 (T-34) | `test_typing_c_in_search_field_inserts_letter_and_does_not_compose`, `test_escape_returns_focus_to_list_and_reactivates_shortcuts` | gui |
| CA-RF-UI-05-1 | RF-UI-05 (T-35) | `test_paint_calls_bounded_by_visible_area` | gui |
| CA-RF-UI-06-1 | RF-UI-06 (T-36) | `test_theme_switch_applies_without_reloading_list`, `test_manual_theme_overrides_system_and_persists` | gui |
| CA-RF-SET-03-1 | RF-SET-03 (T-02) | `test_migrate_refuses_newer_schema_with_clear_message`, `test_migration_from_v1_golden_database_preserves_all_data` | storage |
| CA-RF-SET-04-1 | RF-SET-04 (T-37) | `test_no_password_in_logs_at_any_level` | unit |
| CA-RF-SET-05-1 | RF-SET-05 (T-38) | `test_corruption_recovery_exports_outbox_before_renaming` | storage |
| CA-RNF-PERF-01-1 | RNF-PERF-01 (T-39) | `test_gui_thread_never_blocks_during_bulk_sync` (+ controle positivo) | perf |
| CA-RNF-SEC-01-1 | RNF-SEC-01 (T-03, T-37) | `test_no_password_written_to_database` | security |
| CA-RNF-SEC-02-1 | RNF-SEC-02 (T-04, T-27) | `test_self_signed_certificate_is_rejected_with_explanation` | network |
| CA-RNF-SEC-04-1 | RNF-SEC-04 (T-21) | `test_attachment_names_sanitized[*]` | unit |
| CA-RNF-PRIV-01-1 | RNF-PRIV-01 (T-07) | `test_rendering_corpus_produces_zero_network_requests` (+ nível A) | privacy |
| CA-RNF-PACK-01-1 | RNF-PACK-01 (T-40) | MV-04 | manual |

---

## 7. Corpus de fixtures `.eml`

### 7.1 Árvore e conteúdo exigido

```text
tests/fixtures/eml/
├── benign/
│   ├── simple_text_plain.eml            # text/plain puro, sem HTML, com acentos
│   ├── modern_html_flexbox.eml          # HTML5: flexbox, grid, media query, tabela legada
│   ├── multipart_alternative.eml        # text/plain + text/html com o MESMO conteúdo
│   ├── with_attachment_pdf.eml          # multipart/mixed, PDF de 40 KB, nomes acentuados
│   ├── with_inline_image_cid.eml        # imagem embutida por Content-ID (legítima)
│   ├── quoted_reply_long.eml            # citação longa com níveis de ">"
│   └── newsletter_legit.eml             # boletim real com imagens embutidas e link limpo
├── malicious/
│   ├── script_inline.eml                # <script>alert(1)</script> no body HTML
│   ├── script_obfuscated.eml            # <scr\0ipt>, entidades, <svg onload>, <math>
│   ├── event_handler_onerror.eml        # <img src=x onerror=...>
│   ├── event_handler_onload_body.eml    # <body onload=...>, onmouseover, onclick
│   ├── iframe_remote.eml                # <iframe src="http://evil...">, e <iframe srcdoc>
│   ├── object_embed_applet.eml          # <object data>, <embed src>, <applet code>
│   ├── form_phishing.eml                # <form action="http://...">, <input type=password>
│   ├── javascript_href.eml              # <a href="javascript:...">, src="javascript:"
│   ├── base_href_remote.eml             # <base href="http://evil/"> + link relativo
│   ├── css_expression.eml               # style="width:expression(alert(1))", behavior:, -moz-binding
│   ├── meta_refresh.eml                 # <meta http-equiv="refresh" content="0;url=http://...">
│   └── misleading_link_text.eml         # texto "https://banco-falso.com" → href https://exemplo.com/x
├── tracking/
│   ├── pixel_1x1.eml                    # um único <img width=1 height=1> remoto
│   ├── pixels_20_trackers.eml           # 20 imagens remotas distintas (CA-RF-RD-03-1)
│   ├── background_inline_style.eml      # style="background:url(http://track...)"
│   ├── css_import_remote.eml            # <style>@import url(http://...)</style>
│   ├── css_fontface_remote.eml          # @font-face src: url(http://...)
│   ├── picture_srcset.eml               # <picture><source srcset="http://..."><img srcset="...">
│   ├── non_img_beacon.eml               # <link rel=preload>, <video poster>, <track src>, <audio>
│   ├── hidden_by_attr.eml               # hidden, display:none, visibility:hidden, width=0
│   ├── tracking_params_links.eml        # utm_*, fbclid, gclid, mc_eid, _hsenc, _hsmi, vero_id, igshid
│   └── mixed_full_corpus.eml            # todos os vetores acima em uma mensagem
├── malformed/
│   ├── no_headers.eml                   # corpo sem nenhum cabeçalho
│   ├── missing_message_id.eml           # sem Message-ID e sem Date
│   ├── broken_date.eml                  # Date: "ontem à tarde" (inválida)
│   ├── broken_mime_boundary.eml         # boundary declarado e ausente no corpo
│   ├── charset_iso8859_1.eml            # declarado ISO-8859-1, com ç, ã, é, ô
│   ├── charset_utf8_bom.eml             # UTF-8 com BOM no início do corpo
│   ├── charset_declared_wrong.eml       # declara UTF-8, conteúdo ISO-8859-1
│   ├── header_injection_attempt.eml     # \r\n embutido em Subject
│   └── rfc2047_encoded_subject.eml      # =?ISO-8859-1?Q?A=E7=E3o?=
└── tools/
    ├── build_corpus.py                  # gerador determinístico (semente fixa)
    └── README.md                        # procedência de cada arquivo
```

**Exceção deliberada: `UIDVALIDITY` não é propriedade de mensagem.** O item pedido "mensagem com `UIDVALIDITY` inválido" não pode ser um `.eml`: `UIDVALIDITY` é atributo da **pasta** (resposta de `SELECT`), não do cabeçalho da mensagem. O cenário vive em `tests/fixtures/protocol/uidvalidity_change.json`, consumido pelo `FakeImapServer`, e cobre `CA-RF-MSG-04-1`:

```json
{
  "scenario": "uidvalidity_change",
  "mailbox": "INBOX",
  "before": {"uidvalidity": 1, "uids": [1, 2, 3], "uidnext": 4},
  "after":  {"uidvalidity": 987654321, "uids": [10, 11], "uidnext": 12},
  "expected": "invalidate_folder e ressincronização sem duplicatas"
}
```

### 7.2 Como cada fixture é obtida e por que não pode ser inventada no teste

| Categoria | Procedência | Por que precisa ser um arquivo versionado |
|---|---|---|
| `benign/modern_html_flexbox.eml`, `newsletter_legit.eml` | Correio real recebido, com dados pessoais substituídos por valores fictícios, cabeçalhos de rota removidos | É o HTML que o mundo envia: *inline* do Outlook, tabelas aninhadas, `!important` em série. Um HTML "moderno" escrito à mão num teste nunca se parece com isso e nunca reproduz o bug relatado |
| `benign/multipart_alternative.eml`, `with_attachment_pdf.eml` | Correio real, truncado | As fronteiras (boundary), a codificação `base64` com quebras de linha e os `Content-Type` com parâmetros só aparecem em mensagens reais |
| `malicious/*` | Derivadas de corpus públicos de segurança (coleções SpamAssassin e de *payloads* de XSS), adaptadas para caber em uma mensagem, com o payload preservado literalmente | São o artefato que a revisão de segurança audita. Se o payload for escrito "de memória" dentro do teste, ele é reescrito a cada manutenção — e o dia em que alguém "simplificar" a string é o dia em que a suíte deixa de provar a regra |
| `tracking/*` | Geradas por `build_corpus.py` com semente fixa, a partir de templates determinísticos | Cada variante precisa ser estável byte a byte para o teste de idempotência e para o diff revisável. `random` sem semente tornaria a suíte não reprodutível |
| `pixels_20_trackers.eml` | `build_corpus.py` gera exatamente 20 URLs distintas | Número exato exigido por CA-RF-RD-03-1 |
| `malformed/*` | Produzidas à mão por truncamento/edição de mensagens reais; `charset_*` geradas por script | São os casos em que o parser estoura. Um caso "malformado" inventado no teste tende a ser malformado de um jeito que o parser já aguenta |
| Corpo de 5 MB | `build_corpus.py --large mkdir` gera em `tmp_path` na primeira execução da sessão (fixture de sessão); **não é versionado** | 5 MB no repositório é custo permanente para um caso que se gera em 0,2 s de forma determinística |
| `fixtures/db/v1_golden.db` | Gerado uma vez por `build_corpus.py --golden-db`, **versionado** | É a única forma de verificar "migrar preserva os dados" (L-01) |
| `fixtures/perf/corpus_50k.sql` | Gerado por script, aplicado em `tmp_path` a cada execução | 50.000 mensagens não podem vir versionadas |

**Regra de manutenção do corpus.** `tools/README.md` registra, para cada arquivo, a origem, a data e o que ele prova. Todo arquivo do corpus cita ao menos um teste que o consome — um `.eml` sem teste é removido, porque corpus não exercitado é apenas dívida. Uma mudança no `nh3`/`tinycss2` obriga a revisar o diff de resultado do corpus inteiro antes de qualquer ajuste de asserção (§6.1).

---

## 8. Testes de integração

### 8.1 A fronteira

| O que roda contra servidor **falso** | O que roda contra servidor **real** | Justificativa da fronteira |
|---|---|---|
| Todo o contrato de `IncomingMailClient` (§6.4): capabilities, `UID MOVE` vs `COPY`, `IDLE` e queda, UIDVALIDITY, queda de conexão, `EXPUNGE` falhando | Uma suíte **reduzida** do mesmo contrato: `LOGIN`/`SELECT`/`LIST`, sincronização de 200 cabeçalhos, `UID FETCH` de corpo, `UID MOVE`, `APPEND`, `IDLE` | O servidor falso controla o que o servidor real não deixa controlar (recusar `IDLE`, mudar `UIDVALIDITY` no meio, derrubar o socket, fazer `EXPUNGE` falhar). O servidor real prova o que o falso não pode provar: que entendemos o protocolo de verdade, não a nossa própria imaginação dele |
| Todos os testes de `Storage`, migração, FTS, LRU | Migração sobre banco real de usuário (volume montado), opcional | SQLite é o mesmo em qualquer lugar |
| Todos os testes de desempenho e privacidade | Nada | Resultado de rede real não é reprodutível nem estável o suficiente para portão de merge |
| Todos os testes de `keyring` | Um teste informativo com o backend real em cada SO (§10.4) | O cofre real tem efeito colateral e comportamento diferente por plataforma |

**Regra:** todo comportamento que dependa de peculiaridade de servidor (quirks do Gmail, do Dovecot, do Exchange) é tratado como **configuração** do servidor falso — uma opção a mais no `FakeImapServer` —, não como teste de integração. O teste de integração existe para descobrir que uma configuração estava errada, não para carregar a suíte.

### 8.2 Marcação e comportamento sem Docker

```python
# tests/integration/conftest.py
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

DOVECOT_IMAGE = "dovecot/dovecot:2.3-latest"


def _docker_available() -> tuple[bool, str]:
    if os.environ.get("PYMAIL_INTEGRATION") != "1":
        return False, "PYMAIL_INTEGRATION!=1 (testes de integração são opt-in)"
    if shutil.which("docker") is None:
        return False, "binário `docker` não encontrado"
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"`docker info` falhou: {exc}"
    if proc.returncode != 0:
        return False, "daemon do Docker indisponível"
    return True, ""


@pytest.fixture(scope="session")
def dovecot(request) -> str:
    """Sobe o Dovecot; PULA (não falha) quando o Docker não está disponível."""
    available, reason = _docker_available()
    if not available:
        pytest.skip(f"integração indisponível: {reason}")

    name = f"pymail-dovecot-{os.getpid()}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name,
                    "-p", "0:993", "-e", "DOVECOT_USER=test", DOVECOT_IMAGE], check=True)
    try:
        port = int(subprocess.run(
            ["docker", "port", name, "993/tcp"], capture_output=True, text=True, check=True
        ).stdout.strip().rsplit(":", 1)[1])
        yield f"127.0.0.1:{port}"
    finally:
        subprocess.run(["docker", "stop", name], check=False, capture_output=True)
```

Comportamento obrigatório, verificado por teste próprio:

```python
@pytest.mark.integration
def test_integration_skips_instead_of_failing_without_docker(monkeypatch):
    """Portão: um runner sem Docker produz SKIP, nunca falha vermelha.

    Um teste de integração que falha por falta de Docker treina a equipe a
    ignorar vermelho — o custo é maior que o benefício.
    """
    monkeypatch.delenv("PYMAIL_INTEGRATION", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration",
         "-m", "integration", "--no-header", "-q"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "skipped" in result.stdout.lower()
    assert "failed" not in result.stdout.lower()
```

Uso em CI: o job de integração define `PYMAIL_INTEGRATION=1` e roda apenas no Ubuntu, de forma **não bloqueante** (`continue-on-error: false` só no noturno; em PR é informativo, porque um contêiner instável não deve impedir merge de código correto).

---

## 9. Cobertura e portões de qualidade

### 9.1 Meta e medição

`RNF-MAINT-01` exige **≥ 80% em `core/`**, com foco declarado em sanitização, armazenamento, fila de envio e análise de mensagens. O número é medido por *branch coverage*, não apenas por linhas:

```bash
pytest -m "not integration" \
  --cov=core --cov=ui --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-report=json:build/coverage.json \
  --cov-report=xml:build/coverage.xml

# Portão específico de core/ (RNF-MAINT-01)
coverage report --include="core/*" --fail-under=80
```

| Pacote | Meta | Natureza do portão |
|---|---|---|
| `core/` | **≥ 80% de ramos** | Portão de merge (RNF-MAINT-01) |
| `core/network/` | ≥ 80% | Dentro do portão; o servidor falso dá cobertura alta a baixo custo |
| `ui/` | Reportado, **sem portão** | Medido e publicado para detectar colapso (por exemplo, uma janela inteira sem nenhum teste), mas nunca usado para bloquear |
| `main.py`, `config.py` | Não medido | *Bootstrap*: só existe no processo real |

### 9.2 Onde **não** perseguir cobertura

| Onde não perseguir | Por quê | O que fazer em vez disso |
|---|---|---|
| Código de interface (`ui/`) | Widgets, QSS, geometria e sinais de framework produzem cobertura alta e valor baixo. Testar que um `QLabel` recebeu um texto não encontra nenhum bug real deste projeto | Cobertura apenas dos pontos com lógica: guarda de foco dos atalhos, modelo da lista, `PrivacyInterceptor`, regra de confirmação de link |
| Ramos de plataforma (`if sys.platform == "win32"`) | Só um dos três ramos existe em cada runner; perseguir 100% levaria a testes que só rodam no SO errado | Testar o ramo da plataforma corrente; o comportamento real das outras duas é MV-03/MV-04 (§11) |
| *Backends* de `keyring` | O cofre real tem efeito colateral e não existe em runner Linux sem *secret service* | `FakeKeyring` (§4.1) e um único teste informativo por SO (§10.4) |
| Caminhos de erro impossíveis (`except` de biblioteca que não lança, `if TYPE_CHECKING`) | Não há caminho executável: o teste exercita a si mesmo | `exclude_also` no `pyproject.toml`, com justificativa no código |
| Migrações futuras (v2, v3) | Não existem | Cada migração nova traz seus próprios testes (§6.3.1) junto do código |
| `main.py` (bootstrap, DI, tema) | Roda uma vez por processo; testá-lo exige subir o app inteiro | Verificação de fumaça: `test_app_starts_and_exits_cleanly` (§6.7), não cobertura linha a linha |

### 9.3 Como evitar testes que existem só para elevar o número

Regras aplicadas na revisão de código:

1. **Todo teste declara origem.** O nome do teste ou o comentário/docstring cita o `CA-*` ou o `RF-*`/`RNF-*` de que ele nasce. Teste sem origem é removido — não é dívida técnica, é ruído que esconde falha real.
2. **Proibido asserir sobre mock de código próprio.** `assert_called_once_with` sobre um módulo do projeto verifica implementação, não comportamento, e infla cobertura sem encontrar bug.
3. **Proibido `# pragma: no cover` sem frase de justificativa** na mesma linha ou acima dela. O CI verifica por `ruff`/script que todo `no cover` tem comentário.
4. **O portão é por `core/`, agregado, com piso de ramo.** Já é o recorte que importa; não se cria meta por arquivo, o que incentiva testes triviais.
5. **Cobertura alta não substitui asserção forte.** Um teste que chama `storage.migrate()` e não afirma nada dá 100% do arquivo e prova nada; a revisão rejeita testes cujo corpo não tem `assert` (verificado automaticamente: um teste sem `assert`, `pytest.raises` ou `pytest.fail` é sinalizado por script no CI).
6. **Toda asserção de "nada aconteceu" tem controle positivo** (§1.3). É a regra que mais protege contra cobertura decorativa nos testes críticos.

### 9.4 Portões de merge

| Portão | Comando | Bloqueia merge |
|---|---|---|
| Formatação | `ruff format --check .` | Sim (RNF-MAINT-02) |
| Análise estática | `ruff check .` | Sim |
| Tipagem | `mypy core/` (estrito) e `mypy ui/` | Sim |
| Suíte rápida | `pytest -m "unit or storage or network" -n auto` | Sim |
| Suíte de GUI/threads | `pytest -m "threaded or gui" -n 2` | Sim |
| Testes críticos | `pytest -m "perf or privacy"` no job dedicado | Sim (é o objeto da seção 5) |
| Cobertura | `--cov-fail-under=80` sobre `core/` | Sim (RNF-MAINT-01) |
| Integração real | `pytest -m integration` com Docker | Não em PR; sim no noturno |
| Tamanho de pacote e memória | MV-04 | Não automatizado (§11.4) |

---

## 10. CI

### 10.1 Matriz

Conforme `RNF-COMP-01` (Windows 10+, Ubuntu 22.04+/Debian 12+, macOS 12+) e `RNF-COMP-02` (Python 3.11+):

| SO | Rótulo do runner | Python | Papel |
|---|---|---|---|
| Ubuntu 22.04 | `ubuntu-22.04` | 3.11 (principal), 3.12, 3.13 | Suíte completa; `keyring` sem backend por padrão; job de integração com Docker |
| Windows Server 2022 (compatível com Win 10+) | `windows-latest` | 3.11 (principal), 3.13 | Suíte completa; caminhos com espaço e nomes reservados (`CON`) exercitados de verdade |
| macOS 13 (compatível com 12+) | `macos-13` | 3.11 (principal), 3.12 | Suíte completa; *keychain* real |

Estratégia de matriz: **completa** (os três SOs × 3.11) em todo PR; os *spot checks* (3.12, 3.13) rodam em Linux sempre e nos demais SOs apenas no noturno e em `push` para `main`. Isso mantém o tempo de PR sob controle sem abandonar a compatibilidade declarada.

```yaml
strategy:
  fail-fast: false
  matrix:
    include:
      - { os: ubuntu-22.04,  python: "3.11", full: true }
      - { os: windows-latest, python: "3.11", full: true }
      - { os: macos-13,      python: "3.11", full: true }
      - { os: ubuntu-22.04,  python: "3.12", full: false }
      - { os: ubuntu-22.04,  python: "3.13", full: false }
      - { os: windows-latest, python: "3.13", full: false }
      - { os: macos-13,      python: "3.12", full: false }
```

### 10.2 Ordem das etapas

A ordem é deliberada: falhar rápido no que é barato e determinístico, antes de gastar runner com Qt e Chromium.

1. `checkout`
2. `setup-python` (com cache)
3. Instalar dependências (com cache de *wheels*)
4. **`ruff format --check`** → falha em segundos
5. **`ruff check`** → segundos
6. **`mypy`** → dezenas de segundos
7. **Suíte rápida** (`unit`, `storage`, `network`) com `-n auto` → ~1 min
8. **Suíte de Qt** (`threaded`, `gui`) com `-n 2` e `QT_QPA_PLATFORM=offscreen` → 2 a 5 min
9. **Testes críticos** (`perf`, `privacy`) — apenas no job dedicado (§10.6)
10. **Cobertura** e upload de artefatos (relatório HTML, JSON, XML)
11. **Integração** (somente Ubuntu, com Docker, opt-in)
12. Publicação do resumo (`GITHUB_STEP_SUMMARY`) com o resultado dos testes críticos e o número medido de desempenho

### 10.3 `keyring` nos três sistemas operacionais

| SO | Comportamento no runner | Impacto nos testes |
|---|---|---|
| Linux (Ubuntu 22.04) | Não há *Secret Service*: `keyring` levanta `NoKeyringError` ou cai em backend que grava em arquivo | **Nunca tocar o cofre real nos testes de unidade.** `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` no ambiente |
| Windows | *Credential Locker* funciona, inclusive headless; grava no perfil do runner | Funciona, mas deixa estado entre execuções e pode exigir limpeza. Testes usam `FakeKeyring`; o backend real só no teste informativo |
| macOS | *Keychain* existe, mas pode exigir desbloqueio (`security unlock-keychain`) e prompt de autorização do app | Idem: `FakeKeyring` nos testes; o teste informativo marca `continue-on-error` |

Estratégia única: **a suíte de testes nunca depende do cofre real**. Um job separado e não bloqueante (`.github/workflows/ci.yml`, job `keyring-backend`) roda, em cada SO, um teste que apenas **relata** o backend disponível e se ele aceita escrita, publicando o resultado no resumo. Esse relatório é o que alimenta a decisão de produto (e o item B-02 do backlog de `02-arquitetura.md`), sem transformar diferença de plataforma em falha de build.

### 10.4 Cache de dependências

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: ${{ matrix.python }}
    cache: pip
    cache-dependency-path: pyproject.toml
- name: Cache de wheels (PySide6 é grande)
  uses: actions/cache@v4
  with:
    path: ${{ runner.temp }}/wheels
    key: wheels-${{ runner.os }}-${{ matrix.python }}-${{ hashFiles('pyproject.toml') }}
- name: Instalar
  run: |
    python -m pip install --upgrade pip
    pip install -e ".[dev]" --find-links "${{ runner.temp }}/wheels"
    pip wheel --wheel-dir "${{ runner.temp }}/wheels" -e ".[dev]" || true
```

O `PySide6` + `PySide6-Addons` (que trazem Chromium) são centenas de MB e dominam o tempo de instalação: o cache de *wheels* é o que mantém o job abaixo de poucos minutos. A chave inclui `hashFiles('pyproject.toml')` para invalidar quando a versão do Qt mudar.

### 10.5 O teste de desempenho em máquina de CI compartilhada e ruidosa

`CA-RNF-PERF-01-1` é um limite **absoluto** de 100 ms, e não uma razão. Isso é uma vantagem: ele mede o agendamento do nosso próprio laço de eventos, não a velocidade da máquina. Um bloqueio de 200 ms causado pelo nosso código aparece igualmente em um *laptop* e em um runner ocupado. O que o runner introduz é o **falso positivo**: dessecação de CPU por co-tenant, antivírus varrendo `%TEMP%`, contêiner com CPU limitada.

Política, sem afrouxar o limite:

| Mecanismo | Implementação |
|---|---|
| Job dedicado | `perf` roda em job próprio, `-n 0`, sem outros testes em paralelo |
| Linha de base obrigatória | O teste mede 1 s ocioso antes da carga; acima de 50 ms, **pula** com motivo explícito (§5.1.3) |
| Repetição no nível do job | Até 2 reexecuções do job inteiro em caso de falha sem pilha do projeto (documentado como quarentena temporária, com issue) |
| Artefato com números | `--durations=0` e o `watchdog.report()` são publicados como artefato e no resumo do PR |
| Job noturno estrito | `schedule:` roda `perf` sem margem nenhuma, em runner dedicado, e é o número levado para a spec |
| Margem de 3× | **Não se aplica a este teste.** A margem de `CA-RF-SRCH-02-1` é sobre latência de busca (uma medida de *throughput*, que sofre com CPU compartilhada), e não sobre bloqueio de laço de eventos |

**Por que 3× em `CA-RF-SRCH-02-1`.** A medição de uma consulta FTS5 depende de CPU disponível, de cache de página do sistema operacional e de contenção de disco. Em runner compartilhado, a variação observada entre execuções da mesma consulta é tipicamente de 2× a 4×. A margem de 3× é o compromisso já declarado no critério de aceite: absorve a variabilidade do CI sem deixar passar uma regressão de ordem de grandeza (uma consulta que passe de 90 ms para 3 s falha mesmo com a margem). Além disso, o teste toma o **melhor de 5** — a mediana seria mais sensível a outliers e o pior caso, ruidoso demais. O alvo de produto permanece 100 ms, e é medido sem margem no job noturno.

### 10.6 `.github/workflows/ci.yml`

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 3 * * *"          # noturno: matriz completa, integração e perf estrito
  workflow_dispatch:

env:
  PYMAIL_TEST_MODE: "1"
  PYMAIL_CORPUS_SEED: "20260925"
  PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring"
  QT_QPA_PLATFORM: "offscreen"
  QTWEBENGINE_DISABLE_SANDBOX: "1"
  QTWEBENGINE_CHROMIUM_FLAGS: >-
    --no-sandbox --disable-gpu --disable-dev-shm-usage
    --disable-features=AudioServiceOutOfProcess
  QT_LOGGING_RULES: "qt.webenginecontext.debug=false;qt.qpa.*=false"

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  # ─────────────────────────── 1. qualidade ───────────────────────────
  lint:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install -e ".[dev]"
      - run: ruff format --check .
      - run: ruff check .
      - run: mypy core/
      - run: mypy ui/

  # ─────────────────────── 2. suíte principal ─────────────────────────
  test:
    needs: lint
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - { os: ubuntu-22.04,  python: "3.11", full: true }
          - { os: windows-latest, python: "3.11", full: true }
          - { os: macos-13,      python: "3.11", full: true }
          - { os: ubuntu-22.04,  python: "3.12", full: false }
          - { os: ubuntu-22.04,  python: "3.13", full: false }
          - { os: windows-latest, python: "3.13", full: false }
          - { os: macos-13,      python: "3.12", full: false }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: ${{ matrix.python }}, cache: pip, cache-dependency-path: pyproject.toml }
      - name: Cache de wheels
        uses: actions/cache@v4
        with:
          path: ${{ runner.temp }}/wheels
          key: wheels-${{ runner.os }}-${{ matrix.python }}-${{ hashFiles('pyproject.toml') }}
      - name: Instalar dependências
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]" --find-links "${{ runner.temp }}/wheels"
          pip wheel --wheel-dir "${{ runner.temp }}/wheels" -e ".[dev]" || true

      - name: Suíte rápida (níveis 1-3)
        run: pytest -m "unit or storage or network" -n auto --timeout=120

      - name: Suíte de Qt (níveis 4-5)
        run: pytest -m "threaded or gui" -n 2 --timeout=180

      - name: Cobertura (RNF-MAINT-01)
        if: matrix.full
        run: |
          pytest -m "not integration and not perf" -n auto \
            --cov=core --cov=ui --cov-branch \
            --cov-report=term-missing:skip-covered \
            --cov-report=xml:build/coverage.xml \
            --cov-report=json:build/coverage.json
          coverage report --include="core/*" --fail-under=80

      - name: Publicar cobertura
        if: matrix.full
        uses: actions/upload-artifact@v4
        with:
          name: coverage-${{ matrix.os }}-${{ matrix.python }}
          path: build/coverage.xml

  # ─────────────── 3. testes críticos (afinidade + privacidade) ───────
  critical:
    needs: lint
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install -e ".[dev]"

      - name: Afinidade de thread do imaplib (ADR-001)
        run: pytest tests/network/test_imap_thread_affinity.py -m serial -p no:xdist -n 0 --timeout=120

      - name: Privacidade — zero requisições (CA-RNF-PRIV-01-1)
        run: pytest tests/privacy -p no:xdist -n 0 --timeout=300

  # ─────────────── 4. desempenho (bloqueio da GUI, CA-RNF-PERF-01-1) ──
  perf:
    needs: lint
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install -e ".[dev]"

      - name: Bloqueio da thread da GUI
        id: gui_block
        continue-on-error: true
        run: |
          pytest tests/perf/test_gui_never_blocks.py -p no:xdist -n 0 \
            --timeout=600 -m perf -v --durations=0 | tee perf-report.txt

      - name: Reexecução única de quarentena (ruído de runner, nunca afrouxamento)
        if: steps.gui_block.outcome == 'failure'
        run: |
          pytest tests/perf/test_gui_never_blocks.py -p no:xdist -n 0 \
            --timeout=600 -m perf -v --durations=0 | tee -a perf-report.txt

      - name: Resumo no PR
        if: always()
        run: |
          {
            echo "### CA-RNF-PERF-01-1 — linha do tempo"
            grep -E "max_delta_ms|violations|bloqueio de" perf-report.txt || echo "sem violações registradas"
          } >> "$GITHUB_STEP_SUMMARY"

      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: perf-report, path: perf-report.txt }

  # ───────────────────── 5. compatibilidade de keyring ────────────────
  keyring-backend:
    needs: lint
    continue-on-error: true          # informativo: diferença de plataforma não bloqueia
    strategy:
      fail-fast: false
      matrix: { os: [ubuntu-22.04, windows-latest, macos-13] }
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install -e ".[dev]"
      - name: Relatar backend real de keyring
        env:
          PYTHON_KEYRING_BACKEND: ""       # aqui QUEREMOS o backend real
        run: pytest tests/integration/test_real_keyring.py -m integration -p no:xdist -n 0 -v -s

  # ──────────────────────── 6. integração (Docker) ────────────────────
  integration:
    needs: lint
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch' || github.event_name == 'push'
    runs-on: ubuntu-22.04
    continue-on-error: ${{ github.event_name == 'pull_request' }}
    env:
      PYMAIL_INTEGRATION: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install -e ".[dev]"
      - name: Servidor de correio real (Dovecot em contêiner)
        run: pytest tests/integration -m integration -p no:xdist -n 0 --timeout=300 -v

  # ───────────────────────── 7. portão final ──────────────────────────
  gate:
    needs: [lint, test, critical, perf]
    runs-on: ubuntu-22.04
    steps:
      - run: echo "Portões de merge satisfeitos: lint, tipagem, suíte, cobertura, testes críticos e desempenho."
```

---

## 11. Procedimentos de verificação manual

Cada procedimento tem identificador, gatilho e evidência. `tests/manual/procedures.md` é o registro; a evidência (captura de tela, número medido) é anexada à tarefa correspondente do plano e, quando o critério exige, transcrita em `02-arquitetura.md`.

### 11.1 MV-01 — Renderização visual do HTML moderno

**Por que é manual:** ADR-003 declara que executar `QWebEngineView` em ambiente headless é frágil e que a asserção automatizada fica restrita ao HTML sanitizado e ao interceptor. Nenhum teste afirma sobre pixel; portanto a fidelidade de renderização — que é um dos três gargalos que o projeto existe para resolver — precisa de olho humano.

| Passo | Ação | Resultado esperado |
|---|---|---|
| 1 | Máquina com servidor gráfico (Windows 10+, Ubuntu 22.04 com GNOME, macOS 12+). **Não** `offscreen`. | Janela real, com compositor |
| 2 | Conta de teste configurada; importar as fixtures `benign/` para a pasta de entrada (via `APPEND` ou cópia no servidor falso em modo de desenvolvimento) | Mensagens visíveis na lista |
| 3 | Abrir `modern_html_flexbox.eml` | Colunas lado a lado com flexbox; **sem** sobreposição, sem coluna empilhada em bloco, sem barra de rolagem horizontal |
| 4 | Abrir `newsletter_legit.eml` | Layout de duas colunas preservado; imagens embutidas visíveis; tipografia semelhante à do navegador |
| 5 | Redimensionar a janela de 800×600 até maximizado | O HTML **não** quebra nem corta: o layout acompanha a largura |
| 6 | Aumentar o zoom com `Ctrl` `+` até 200% | Conteúdo legível, sem corte, sem sobreposição |
| 7 | Rolar mensagem de 5 MB até o fim | Rolagem contínua, sem travamento perceptível, sem salto de posição |
| 8 | Abrir `quoted_reply_long.eml` | Citação com `>` legível, recuo coerente |
| 9 | Abrir `with_attachment_pdf.eml` | Indicador de anexo presente na lista e no leitor, com nome e tamanho |
| 10 | Comparar com o mesmo arquivo aberto em um navegador (Firefox/Chrome) | Diferenças toleráveis são apenas as de fonte do sistema; **estrutura** idêntica |

Registrar: captura de tela de cada mensagem, em tema claro; e o resultado da comparação com o navegador.

### 11.2 MV-02 — Comportamento em ambiente headless

**Por que é manual:** `QT_QPA_PLATFORM=offscreen` não é um servidor gráfico. Verificar que o aplicativo **não depende** disso é uma afirmação sobre o produto, não sobre o teste.

| Passo | Ação | Resultado esperado |
|---|---|---|
| 1 | Condição de falha conhecida: rodar o app com `offscreen` e nenhum display (`DISPLAY=`) | Inicia e não encerra; útil apenas para o CI |
| 2 | Rodar com `QT_QPA_PLATFORM=xcb` sem display, em Linux | Falha **com mensagem clara** de Qt, não encerramento silencioso |
| 3 | Rodar com `QT_QPA_PLATFORM=xcb` sob `xvfb-run` | Inicia; janela não visível; nenhuma funcionalidade de núcleo quebrada |
| 4 | Rodar com servidor gráfico real e, em paralelo, a suíte `-m gui` em modo `offscreen` | Ambos funcionam; a suíte headless não interfere na instância real |
| 5 | Abrir uma mensagem com HTML sob `xvfb-run` | Renderiza sem exceção; **não** se afirma nada sobre fidelidade visual (isso é MV-01) |
| 6 | Verificar `QTWEBENGINE_DISABLE_SANDBOX` e `--no-sandbox` apenas em CI | Em uso normal, o sandbox do Chromium permanece **ativo** (RNF-SEC-03) — confirmar que a variável não é definida pelo aplicativo |

Registrar: linha de comando usada, saída de erro e o texto exato das mensagens.

### 11.3 MV-03 — Temas claro e escuro

**Por que é manual:** aparência é percepção e as métricas de fonte em `offscreen` mentem.

| Passo | Ação | Resultado esperado |
|---|---|---|
| 1 | Com o tema do SO em claro, abrir o app | Tema claro aplicado; nenhum texto claro sobre fundo claro |
| 2 | Trocar o tema do SO para escuro, com o app aberto | Cores mudam **em tempo real**, sem reiniciar e sem recarregar a lista (CA-RF-UI-06-1) |
| 3 | Selecionar manualmente "claro" com o SO em escuro | Preferência manual sobrepõe o sistema |
| 4 | Fechar e reabrir o app | A preferência manual persistiu (CA-RF-UI-06-1) |
| 5 | Com o tema escuro, abrir `modern_html_flexbox.eml` | O corpo da mensagem não fica com fundo branco hostil nem texto ilegível: o tema é aplicado ao leitor |
| 6 | Verificar contraste de todos os pares texto/fundo do QSS | Razão ≥ 4,5:1 para texto normal e ≥ 3:1 para texto grande (RNF-A11Y-01, AA). Medir com calculadora de contraste do WCAG, sobre as cores literais do `light.qss`/`dark.qss` |
| 7 | Percorrer a interface inteira só com `Tab` | Foco sempre **visível** em todos os elementos; ordem de foco faz sentido |
| 8 | Verificar ícones SVG nos dois temas | Ícones legíveis e coerentes nos dois |

Registrar: tabela de contraste com os valores calculados, capturas dos dois temas com a mesma mensagem aberta.

### 11.4 MV-04 — Consumo de memória e tamanho do pacote (`CA-RNF-PACK-01-1`)

**Por que é manual:** depende da máquina, do PyInstaller e dos processos do Chromium, que não existem em teste headless de forma representativa. `CA-RNF-PACK-01-1` exige o número medido e registrado, com a diferença entre o pacote com e sem os módulos Qt excluídos.

| Passo | Ação | Resultado esperado |
|---|---|---|
| 1 | `pyinstaller --noconfirm --windowed --name PyMail --collect-all PySide6.QtWebEngineWidgets pymail_client/main.py` em modo **diretório** | Pacote gerado, sem erro |
| 2 | Medir o tamanho total do diretório e o do subdiretório do motor de renderização | Registrar em MB, por plataforma |
| 3 | Repetir com `--exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtCharts --exclude-module PySide6.QtQuick3D --exclude-module PySide6.QtDesigner` e demais módulos Qt não usados | Pacote menor; a **diferença** é o número que o critério pede |
| 4 | Verificar que o pacote reduzido ainda abre, sincroniza, renderiza e envia | Nenhuma funcionalidade perdida pela exclusão |
| 5 | Executar o pacote em máquina sem Python instalado | Funciona (RNF-PACK-02: sem privilégio administrativo) |
| 6 | Medir o RSS com uma conta e uma mensagem aberta: processo principal, `QtWebEngineProcess` e ajuda do GPU | Registrar separadamente: **RNF-PERF-05 exige < 400 MB excluindo os processos do motor**, e o custo do motor é declarado à parte |
| 7 | Abrir 5 mensagens em sequência, aguardar 60 s | Registrar o RSS novamente: crescimento é esperado; crescimento **ilimitado** não é |
| 8 | Fechar a janela | Processos `QtWebEngineProcess` encerram; nenhum processo órfão fica |

Comandos de medição:

```powershell
# Windows
Get-Process PyMail, QtWebEngineProcess | Select-Object Name, Id, @{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

```bash
# Linux
for p in $(pgrep -f "PyMail|QtWebEngineProcess"); do
  echo "$p $(awk '/VmRSS/{print $2/1024 " MB"}' /proc/$p/status)"
done

# macOS
ps -Ao pid,rss,comm | grep -E "PyMail|QtWebEngineProcess" | awk '{printf "%s %.1f MB\n", $3, $2/1024}'
```

Ao final, os números substituem as estimativas de `01-requisitos.md` §6 e de `02-arquitetura.md` §10, conforme o item B-02 do backlog.

### 11.5 MV-05 — Operação completa sem mouse (critério de conclusão da fase 1, item 4)

`01-requisitos.md` §9 determina que a fase 1 só termina quando um usuário consegue cadastrar conta, sincronizar, ler, buscar, arquivar, responder e enviar com undo **sem tocar no mouse**. Isso é um fluxo humano: nenhum teste automatizado o substitui.

| Passo | Teclas | Resultado esperado |
|---|---|---|
| 1 | `Tab` × N até o botão "Adicionar conta"; `Enter` | Diálogo de conta abre **sem mouse**, com foco no primeiro campo |
| 2 | Preencher nome, e-mail, host, porta, usuário, senha; `Tab` entre campos; `Enter` em "Testar conexão" | Teste de conexão executa e reporta sucesso |
| 3 | `Enter` em "Salvar" | Conta cadastrada; a sincronização inicia |
| 4 | `Tab` até a lista de mensagens; `J`/`K` | Navegação para baixo/cima na lista, com o leitor acompanhando |
| 5 | `/` e digitar um termo; `Enter` | Foco vai para a busca; resultados aparecem enquanto se digita; `Esc` devolve o foco à lista |
| 6 | `Enter` na mensagem | Mensagem aberta; `Ctrl` `+`/`-`/`0` ajusta o zoom |
| 7 | `Tab` até um link do corpo; `Enter` | Confirmação exibe o host real; confirmar abre o navegador do sistema; `Esc` cancela |
| 8 | `Esc` para voltar à lista; `E` | Mensagem arquivada, sai da caixa de entrada, nenhuma reversão |
| 9 | `R` na mensagem | Compositor em modo resposta, com citação e `In-Reply-To` |
| 10 | Digitar destinatário, assunto e texto; `Ctrl` `Enter` para enviar | Aviso de janela de undo aparece, com contagem |
| 11 | `Ctrl` `Z` (ou botão acessível por `Tab`) dentro da janela | Envio cancelado; mensagem volta a rascunho |
| 12 | `Ctrl` `Enter` novamente e aguardar a janela | Envio concluído; mensagem em "Enviadas" |
| 13 | Recolher a barra lateral por atalho; fechar e reabrir | Estado da barra persistido (RF-UI-02) |
| 14 | Repetir o roteiro **inteiro** sem nenhum clique | Nenhum passo exige mouse |

Registrar: gravação de tela do roteiro completo, com o relógio visível, anexada à tarefa T-34. Qualquer passo que exija mouse é um defeito de acessibilidade (RNF-A11Y-01), não uma nota de rodapé.

---

## 12. Lacunas identificadas

Necessidades encontradas ao escrever esta estratégia que **não existem** em `01-requisitos.md`. Nenhum ID novo de requisito ou de tarefa foi criado aqui: a coluna "Proposta" descreve o que precisa ser acrescentado ao documento de requisitos (ou ao de arquitetura) antes de ser implementado.

| # | Lacuna | Por que importa | Proposta |
|---|---|---|---|
| L-01 | Não existe banco de referência versionado para testar migração com dados | `CA-RF-SET-03-1` exige "preserva todos os dados", e sem um banco v1 conhecido isso não é verificável — só afirmável | Versionar `tests/fixtures/db/v1_golden.db`, gerado por script, e citá-lo como ativo obrigatório de teste |
| L-02 | `RNF-PERF-01` fala em 16 ms por operação; `CA-RNF-PERF-01-1` verifica 100 ms | O teste prova uma afirmação seis vezes mais fraca que o requisito. Hoje não se sabe qual é normativo | Declarar explicitamente que 100 ms é o limite de bloqueio acumulado medido no teste e 16 ms é a meta por operação, **ou** acrescentar um critério que verifique o orçamento por operação |
| L-03 | `RF-MSG-03` (pré-busca oportunista) está marcado como verificado por teste (`T`) mas não tem `CA-*` | Sem critério, não há como saber quantas buscas são aceitáveis, nem se o cancelamento ao navegar funciona | Critério com números: pré-busca limitada a N mensagens, em prioridade baixa, cancelada em até X ms após a navegação, verificada pela contagem de `FETCH` no servidor falso |
| L-04 | `RF-MSG-05` (IDLE com queda para polling) não tem `CA-*`, embora seja testável e esteja na matriz como `T` | O requisito descreve o comportamento mais frágil do cliente (`IDLE` feito à mão, risco de `02-arquitetura.md` §10) e não tem prova | Critério: com servidor que recusa `IDLE`, o cliente passa a `NOOP`+`UID SEARCH` no intervalo configurado, sem erro visível ao usuário |
| L-05 | `RF-MSG-07` (anexo só sob demanda) não tem `CA-*` | É uma promessa de economia de banda e de tempo, e nada a verifica | Critério: a sincronização inicial de uma pasta com anexos produz zero comandos de download de anexo, com verificação no servidor falso |
| L-06 | `RF-RD-05` (remoção de parâmetros de rastreamento) não tem `CA-*` | É uma funcionalidade de privacidade com lista fechada de parâmetros — o caso mais fácil de testar de todo o documento, e o único de privacidade sem critério | Critério parametrizado sobre a lista de `01-requisitos.md` (`utm_*`, `fbclid`, `gclid`, `mc_eid`, `_hsenc`, `_hsmi`, `vero_id`, `igshid`), com preservação dos demais parâmetros |
| L-07 | Vários requisitos estão marcados como "verificado por teste" na matriz sem nenhum `CA-*`: `RNF-PRIV-02`, `RNF-SEC-05`, `RF-UI-02`, `RF-UI-11`, `RF-SRCH-03`, `RF-ORG-02`, `RF-ORG-03`, `RF-SND-01/02/06/08`, `RF-RD-02`, `RF-RD-09` | A regra de rastreabilidade de `01-requisitos.md` §2 diz que requisito sem critério de aceite é requisito mal escrito. Treze casos violam a própria regra do documento | **RESOLVIDO** — todos receberam critério de aceite verificável em `01-requisitos.md` §8.1, acrescentada após esta auditoria. Os testes devem referenciar os `CA-*` de lá, e não o requisito diretamente |
| L-08 | Nenhum requisito ou contrato menciona que o relógio precisa ser injetável | A janela de Undo Send (5 a 30 s) e o atraso de "marcar como lida" (1500 ms) não podem ser testados sem relógio falso; usar `sleep` tornaria a suíte lenta e instável | Acrescentar `Clock` como interface em `core/` (a exemplo de `AuthProvider`), injetada em `OutboxScheduler` e nos temporizadores testáveis |
| L-09 | `Storage` (contrato de `02-arquitetura.md` §5.4) não tem *seam* documentado para injeção de falha | `CA-RF-SRCH-04-1` exige testar rollback nos dois sentidos; sem um ponto de injeção documentado, o teste depende de `monkeypatch` em função interna, que quebra a cada refatoração | Acrescentar `connection_hook` opcional ao construtor de `Storage` (usado para instalar `set_authorizer`), documentado como API de teste |
| L-10 | `CA-RNF-PRIV-01-1` não define se "requisição" significa tentativa ou requisição concluída | O teste assere sobre tentativas (inclusive bloqueadas). Sem a definição no critério, um implementador pode argumentar que bloquear já satisfaz o critério, o que é mais fraco | Escrever no critério: "requisição = tentativa registrada pelo interceptor, incluindo as canceladas; a asserção é sobre zero tentativas" |
| L-11 | `RNF-PERF-02`, `RNF-PERF-03` e `RNF-PERF-05` não têm `CA-*`; os dois primeiros estão marcados como `T` e o terceiro como `M` sem procedimento escrito | Tempo de primeira janela, tempo de abertura de mensagem e consumo de memória são afirmações de produto sem prova definida | Critérios com limite e condição de medição (máquina de referência, conjunto de dados, tolerância) e procedimento manual para o RSS, nos moldes de MV-04 |
| L-12 | `RNF-PRIV-02` (não coletar telemetria) está marcado como `T` sem critério | É a segunda afirmação de privacidade do produto e a única sem prova | Critério verificável na camada de rede: com o app em execução e uma conta sincronizada, nenhum socket de saída é aberto para destino que não seja o servidor de correio configurado |
| L-13 | `CA-RF-SRCH-02-1` exige 50.000 mensagens indexadas, mas nenhum documento define como esse corpus é gerado ou quanto tempo leva | O teste é caro; sem padrão, cada execução inventa o seu e o número deixa de ser comparável | Documentar `tests/fixtures/perf/corpus_50k.sql` com distribuição de tamanhos, e orçamento de preparação (por exemplo, < 60 s) |
| L-14 | Não existe política declarada de teste instável (*flaky*) nem o significado de quarentena | Sem política, cada pessoa decide por conta própria — e a decisão mais comum é afrouxar o limite, que é exatamente o que não pode acontecer com os testes críticos | Acrescentar à spec a política de §5.4: quarentena visível com issue, proibição de afrouxar limites de critério de aceite, e reexecução apenas no nível do job |
| L-15 | Nenhum critério de aceite para os requisitos de fase 2 (`RF-ACC-06/07/08`, `RF-MSG-10/11/12`, `RF-RD-10`, `RF-ORG-06/07`, `RF-SET-06`, `RF-SND-09`, `RF-SRCH-06`) | Esta estratégia só pode reservar o espaço (a suíte de contrato de §6.4 e as colunas já existentes no schema), mas a fase 2 precisa dos seus próprios critérios antes de ser planejada | Critérios por requisito quando a fase 2 for especificada, reutilizando a suíte de contrato parametrizada |
| L-16 | `RNF-MAINT-02` aparece na matriz como verificação por teste (`T`) | `ruff format`/`ruff check` não são testes no sentido de `pytest`; a matriz mistura portão de qualidade com teste | Corrigir a coluna "Verificação" da matriz para distinguir `T` (teste), `M` (manual) e `L` (portão de lint/estático) |
| L-17 | `RNF-COMP-02` (sem código específico de plataforma fora de pontos isolados) não tem critério | É uma afirmação arquitetural que ninguém verifica e que se degrada silenciosamente | Critério verificável por análise: todo uso de `sys.platform`/`os.name` está em lista explícita e documentada, verificado por teste que varre o código-fonte |
| L-18 | `RNF-A11Y-01` é verificado só por procedimento manual, sem critério objetivo | "Contraste mínimo AA" é mensurável e não deveria depender de olho | Critério parcial automatizável: cálculo da razão de contraste dos pares de cores das duas folhas de estilo, com limite 4,5:1; o resto (foco visível, ordem de foco) permanece em MV-03/MV-05 |
| L-19 | `01-requisitos.md` não exige que o corpus hostil seja versionado, embora `CA-RF-RD-01-1` o referencie por caminho | Um critério que aponta para um diretório sem exigir que o diretório exista, com conteúdo auditável e estável, é um critério que se esvazia na primeira refatoração de testes | Exigir no critério que o corpus seja versionado, com procedência registrada e ao menos um teste consumidor por arquivo (§7.2) |
| L-20 | `RNF-REL-01` está associado apenas a `CA-RF-SND-04-1` (fila de envio) | O requisito cobre também rascunhos, e não há critério para "falha de rede ou de servidor jamais causa perda de rascunho" no caminho de digitação/autossalvamento | Critério para autossalvamento de rascunho: derrubar o processo durante a composição e reabrir resulta em rascunho recuperável com o texto digitado até o último autossalvamento |
| L-21 | `RNF-MAINT-01` não define exclusões nem como a cobertura é medida | 80% sem definir o que conta permite atingir o número excluindo justamente o que importa | Declarar no requisito: cobertura de **ramos** sobre `core/`, excluindo apenas `main.py`/`config.py`, com as exclusões listadas em `pyproject.toml` |

**Nota final sobre honestidade do documento.** Os três testes da seção 5 são os únicos que provam as afirmações centrais do produto. Deste documento, o que **não** é automatizável está declarado em §1.2, §6.7.2 e §11 — e a lista é longa de propósito: renderização visual, temas, memória, tamanho de pacote e a operação inteira pelo teclado dependem de olho humano e de máquina real. Prometer cobertura automatizada desses pontos seria a forma mais rápida de transformar esta estratégia em ficção.



