# 02 — Arquitetura

**Projeto:** PyMail Client
**Versão desta spec:** 1.0 · **Data:** 2026-09-25
**Documentos correlatos:** `01-requisitos.md` (o quê) · `03-modelo-de-dados.md` (persistência) · `04-ui-ux.md` · `05-seguranca-privacidade.md` · `06-estrategia-de-testes.md` · `../plans/fase1.md` (execução)

---

## 1. Princípios de arquitetura

Cinco princípios governam todas as decisões deste documento. Quando houver dúvida de projeto, a resposta é a que respeita estes princípios.

1. **A thread da interface nunca espera.** Nenhuma chamada de rede, nenhuma consulta a banco que possa tocar o disco, nenhuma sanitização de HTML acontece na thread da GUI. Isso não é uma meta de desempenho, é uma invariante estrutural verificada por teste (RNF-PERF-01).
2. **O cache local é descartável; o que o usuário escreveu não é.** Tudo que veio do servidor pode ser reconstruído e apagado a qualquer momento. Rascunhos e a fila de envio são dados do usuário e sobrevivem a falhas, reinícios e até corrupção do banco.
3. **Privacidade é imposta na camada de rede, não na boa vontade do HTML.** Não basta limpar o HTML: a requisição tem de ser cancelada no momento em que seria emitida, porque o HTML de um e-mail é hostil por definição.
4. **Dependências apontam para dentro.** A interface conhece o núcleo; o núcleo não conhece a interface. Detalhes de protocolo ficam atrás de interfaces, para que OAuth2 e POP3 entrem na fase 2 sem tocar em `ui/`.
5. **Estado visível primeiro, verdade do servidor depois.** A interface reflete a intenção do usuário imediatamente e a fila de operações reconcilia com o servidor. Lentidão de rede não pode virar lentidão percebida.

---

## 2. Estrutura de diretórios alvo

A estrutura abaixo preserva integralmente a estrutura pedida no prompt mestre. As linhas marcadas **[+]** são acréscimos justificados; **[F2]** indica arquivos que só existem na fase 2.

```text
pymail_client/
├── main.py                     # Ponto de entrada: bootstrap, tema, DI das dependências
├── config.py                   # Configurações do usuário (TOML), caminhos do SO
├── pyproject.toml         [+]  # Dependências, ruff, pytest, mypy
├── assets/
│   ├── icons/*.svg             # Ícones SVG minimalistas
│   └── themes/
│       ├── light.qss
│       └── dark.qss
├── core/
│   ├── __init__.py
│   ├── auth.py            [+]  # AuthProvider (ABC), PasswordAuth, registry  ← D2
│   ├── models.py          [+]  # Dataclasses de domínio (HeaderEnvelope, RemoteFolder, ...)
│   ├── tasks.py           [+]  # Infra de threads: AccountWorker, TaskPool, CancellationToken
│   ├── security.py             # keyring + sanitização de HTML (ver §2.1)
│   ├── storage.py              # SQLite + FTS5: cache, busca, outbox, migrações
│   ├── errors.py          [+]  # Taxonomia de erros e classificação para a UI
│   └── network/
│       ├── __init__.py
│       ├── base.py        [+]  # Protocolos de cliente de entrada/saída         ← D1
│       ├── imap_client.py      # IMAP síncrono, afinidade de thread, IDLE
│       ├── pop_client.py       # POP3                                            [F2]
│       └── smtp_client.py      # Envio com buffer de "Undo"
├── ui/
│   ├── __init__.py
│   ├── main_window.py          # Janela principal, orquestração, atalhos
│   ├── styles.py               # Temas Claro e Escuro (QSS), detecção do tema do SO
│   ├── shortcuts.py       [+]  # Registro de atalhos com guarda de foco
│   └── components/
│       ├── sidebar.py          # Contas/pastas, colapsável
│       ├── message_list.py     # Lista virtualizada (QListView + modelo)
│       ├── reader.py           # Leitor QWebEngineView + interceptor de privacidade
│       ├── composer.py         # Composição, resposta, encaminhamento
│       ├── search_bar.py  [+]  # Busca incremental
│       └── toasts.py      [+]  # Feedback não modal (erros, undo send)
└── tests/
    ├── conftest.py
    ├── fakes/              [+]  # Servidores IMAP/SMTP falsos, keyring falso
    ├── fixtures/eml/       [+]  # Corpus de mensagens (incluindo hostis)
    └── ...
```

### 2.1 Desvios da estrutura pedida no prompt, e por quê

O prompt mestre pedia `security.py` com "gestão do keyring e sanitização de HTML". Mantive o arquivo, mas a separação interna merece registro, porque essas duas responsabilidades têm naturezas opostas:

- **Gestão de credenciais** é I/O contra um serviço do sistema operacional, difícil de testar, com efeitos colaterais.
- **Sanitização de HTML** é uma função pura `str -> str`, determinística e altamente testável com um corpus de mensagens hostis.

São as duas coisas que mais precisam de teste no projeto (é a proposta de valor do produto), e testá-las juntas torna o teste pior. **Decisão:** `security.py` expõe duas famílias de funções com prefixos distintos (`Keyring*` e `sanitize_html`). Se o arquivo passar de aproximadamente 300 linhas na implementação, a sanitização migra para `core/sanitizer.py` — mudança mecânica, sem impacto em chamadores, porque o import é sempre `from core.security import sanitize_html`. Os demais acréscimos (`auth.py`, `tasks.py`, `base.py`, `models.py`, `errors.py`) existem por consequência direta de D1, D2 e D4 e estão justificados nos ADRs da seção 3.

---

## 3. ADRs — Registros de decisão de arquitetura

### ADR-001 — Rede com bibliotecas síncronas da stdlib, com afinidade de thread por conta

**Contexto.** O prompt pedia `imaplib`/`aioimaplib` e, ao mesmo tempo, `QThread` ou `asyncio`. São modelos incompatíveis: as bibliotecas `aio*` exigem um event loop `asyncio`, e o Qt já possui o seu. O requisito real, que aparece em vários itens, é um só: **a interface nunca pode travar**.

**Decisão.** Usar `imaplib`, `poplib` e `smtplib` (biblioteca padrão, síncronos), executados em threads de trabalho, com uma **conexão por conta amarrada a uma thread dedicada**.

**Refinamento necessário, e a razão dele.** A formulação inicial "rodar tudo em `QThreadPool`" é insuficiente e teria produzido um bug intermitente e difícil de diagnosticar: **objetos `imaplib.IMAP4` não são thread-safe.** Se duas tarefas do pool usarem a mesma conexão, as respostas do servidor se cruzam e uma tarefa recebe a resposta da outra — falha silenciosa, dependente de timing, que aparece em produção e não em teste. Portanto:

- O `QThreadPool` global executa trabalho **sem estado compartilhado**: sanitização de HTML, cálculo de texto plano, escrita no índice de busca, cálculos de cache.
- Cada conta possui **uma `QThread` dedicada** com uma fila de comandos serializada (`queue.Queue`) e **uma única conexão IMAP** criada e usada exclusivamente nessa thread.
- Se a thread de uma conta morrer, o pool é irrelevante: só aquela conta reconecta.

**Consequências.**

- Positivas: bibliotecas maduras da stdlib (sem dependência de terceiros para o núcleo); modelo de concorrência simples de raciocinar; testável com servidor falso em socket; troca futura por `aioimaplib` isolada em `core/network/imap_client.py`, porque a UI só conhece `IncomingMailClient` (`network/base.py`).
- Negativas: uma thread por conta (custo irrelevante na faixa de 1 a 10 contas); cancelamento é cooperativo, via `CancellationToken`, não é interrupção forçada; `IDLE` precisa ser implementado à mão porque `imaplib` não o expõe.
- **Aceito explicitamente:** o consumo de threads é maior que o de um modelo assíncrono puro. Em troca, elimina-se a categoria de bug descrita acima.

**Alternativas rejeitadas.** `aioimaplib` + `qasync`: substitui o event loop do Qt por um de terceiros, adicionando risco de integração em troca de elegância, e ainda exigiria threads para o trabalho intensivo de CPU. Híbrido com event loop `asyncio` em thread dedicada: dois event loops para depurar, ganho marginal na faixa de contas realista.

---

### ADR-002 — Autenticação plugável; senha na fase 1, OAuth2 na fase 2

**Contexto.** A Microsoft descontinuou a autenticação básica em IMAP/SMTP no Exchange Online; OAuth2 passou a ser obrigatório. O Google desativou "less secure apps", mas app passwords ainda funcionam para contas com verificação em duas etapas. *(Verificação pendente: o ambiente de desenvolvimento estava sem acesso à busca web durante a escrita desta spec; os links `05-seguranca-privacidade.md` §7 e o item de backlog B-01 registram a necessidade de reconfirmar o estado atual junto à documentação oficial antes de congelar a fase 2.)*

**Decisão.** Definir `AuthProvider` como interface abstrata desde o primeiro dia, com `PasswordAuth` implementado na fase 1 e `OAuth2Auth` na fase 2. A UI e o armazenamento nunca conhecem o mecanismo: pedem ao provider os dados de autenticação e tratam um resultado uniforme.

**Consequências.**

- Positivas: a fase 2 é aditiva. Nenhuma refatoração em `ui/` nem em `storage.py`, o que é verificado pelo critério de aceite CA-RF-ACC-04-1.
- Negativas: **contas Microsoft 365 não funcionam na fase 1** (declarado em `01-requisitos.md` §6). Há uma indireção a mais no caminho crítico de conexão.

**Alternativas rejeitadas.** OAuth2 já na fase 1: exige registrar aplicativo no Google Cloud Console e no Azure AD, manter `client_id` como ponto de falha externo e implementar fluxo de navegador, PKCE, refresh e revogação — multiplica o tamanho do núcleo antes de existir um cliente que funcione. Apenas senha sem abstração: tornaria a fase 2 uma refatoração da camada de conexão inteira.

---

### ADR-003 — `QWebEngineView` com JavaScript desabilitado e interceptor de rede

**Contexto.** O prompt pede `QWebEngineView` e, ao mesmo tempo, um cliente "leve". São objetivos em tensão: o motor de renderização é Chromium embarcado e responde por 150 a 200 MB no instalador e por processos próprios em memória. O prompt também cita "renderização quebrada" como um dos gargalos históricos a resolver.

**Decisão.** Usar `QWebEngineView` com **JavaScript permanentemente desabilitado** e um `QWebEngineUrlRequestInterceptor` que decide, requisição por requisição, entre permitir e cancelar.

**Consequências.**

- Positivas: HTML5/CSS moderno renderiza fielmente, o que elimina o gargalo de renderização quebrada. O bloqueio de privacidade deixa de ser heurística de HTML e passa a ser imposição de rede — a única abordagem que cobre `background` em CSS, `<picture>`/`srcset`, `@import` remoto e beacons que não são `<img>`.
- Negativas: instalador grande e consumo de memória elevado. Ambos medidos e declarados em vez de supostos (RNF-PACK-01, RNF-PERF-05).
- Imposto: o teste automatizado de interface fica restrito a asserções sobre o HTML sanitizado e sobre o interceptor; a verificação visual da renderização é procedimento manual, porque executar `QWebEngineView` em ambiente headless é frágil (ver `06-estrategia-de-testes.md` §6).

**Alternativas rejeitadas.** `QTextBrowser`: instalador de poucos MB, mas entende apenas um subconjunto de HTML4/CSS2.1 — sem flexbox, sem grid, sem media queries — o que **reintroduz exatamente o problema que o projeto existe para resolver**, além de obrigar a bloquear rastreamento por heurística de HTML. Modo duplo (`QWebEngineView` + `QTextBrowser`): dois renderizadores, dois pipelines de sanitização e duas suítes de teste mantidos indefinidamente, com um modo degradado que só falha para parte da base de usuários.

---

### ADR-004 — Sanitização com biblioteca de allowlist sobre parser HTML real

**Contexto.** É a funcionalidade central do produto e a de maior risco de segurança. A abordagem precisa ser allowlist (permitir o que se conhece), nunca blocklist, e nunca por expressão regular.

**Decisão.** Usar `nh3` (ligações Rust do sanitizador `ammonia`) para a estrutura HTML, com allowlist de tags, atributos e esquemas de URL, complementada por:

- `tinycss2` para filtrar propriedades CSS permitidas dentro do atributo `style` (o `nh3` não interpreta CSS; sem filtro, `expression()` e `url()` remotos passariam).
- Um passe próprio, determinístico e testável, para as regras de privacidade que nenhuma biblioteca genérica resolve: remoção irreversível de pixels de rastreamento, reescrita de recursos remotos com preservação da URL original em `data-*`, e limpeza de parâmetros de rastreamento em links.
- Injeção de `<meta http-equiv="Content-Security-Policy">` restritiva no HTML final, como defesa em profundidade.

**Dependência acrescentada fora da lista original do prompt.** Justificativa: `bleach` está sem manutenção desde 2023 e `lxml.html.clean` foi removido no lxml 5. Escrever um sanitizador próprio é a alternativa que este ADR rejeita explicitamente.

**Consequências.**

- Positivas: sanitização testável como função pura, com corpus hostil versionado; desempenho adequado (Rust) para sanitizar sob demanda sem travar nada.
- Negativas: duas dependências nativas a mais (ambas com *wheels* para as três plataformas alvo — precisa ser confirmado no primeiro passo da tarefa T-05, antes de qualquer código depender delas).
- Imposto: as regras de privacidade do passe próprio são código nosso, e é nelas que os testes de segurança se concentram.

**Alternativas rejeitadas.** `bleach` (sem manutenção), `lxml.html.clean` (removido), sanitizador próprio completo (reimplementar `ammonia` é como se escrevem vulnerabilidades).

**Emenda, após a revisão de segurança de `05-seguranca-privacidade.md` §4.** Aquele documento detalhou o pipeline e refinou este ADR em dois pontos que a implementação deve seguir literalmente, porque inverter a ordem reintroduz o defeito:

1. **São dois passes de `nh3`, com um passo de reescrita entre eles**, de modo que a autoridade estrutural seja sempre a **última** transformação. Um passe único que reescrevesse atributos depois da allowlist permitiria à reescrita reintroduzir algo que o `nh3` já havia removido.
2. **O espaço de nomes `data-pymail-*` é descartado no primeiro passe e recriado apenas pelo passo de reescrita.** Sem isso, um remetente malicioso poderia embutir `data-pymail-src` no próprio HTML e **forjar o marcador** que o leitor usa para restaurar imagens quando o usuário autoriza — transformando o mecanismo de consentimento em vetor de carregamento de conteúdo remoto. É por isso que o atributo não pode ser simplesmente "permitido" na allowlist, e é o achado de segurança mais relevante desta fase.

A ordem normativa das etapas é a de `05` §4, que inclui o passo intermediário de reescrita entre os dois passes do `nh3`. A tarefa `T-05` deve implementá-la nessa ordem, e `CA-RF-RD-01-1` é o teste que a protege.

---

### ADR-005 — Manutenção explícita do índice FTS5, sem gatilhos

**Contexto.** O índice de busca precisa ficar consistente com o conteúdo. O SQLite oferece gatilhos que mantêm tabelas FTS5 sincronizadas automaticamente.

**Decisão.** Manter o índice **explicitamente, dentro da mesma transação** que grava o corpo (RF-SRCH-04), sem gatilhos de banco.

**Consequências.**

- Positivas: a lógica fica visível e depurável em Python, junto do código que grava; o teste de rollback (CA-RF-SRCH-04-1) verifica diretamente a atomicidade; migrações futuras do esquema não precisam recriar gatilhos.
- Negativas: exige disciplina — todo caminho que grava corpo precisa indexar. Mitigação: a gravação de corpo e a indexação acontecem em um único método de `storage.py`, e nenhum outro código escreve na tabela `bodies`. Além disso, um teste de consistência compara a contagem do índice com a contagem de mensagens com corpo (CA-RF-SRCH-04-1).
- **Nota técnica:** o tokenizador é `unicode61 remove_diacritics 2` mais `prefix='2 3'`, o que entrega a insensibilidade a acentos exigida por CA-RF-SRCH-01-1 e a busca por prefixo de RF-SRCH-02. A sintaxe do usuário é escapada antes de virar consulta (RF-SRCH-05), para que uma aspa ou um `NEAR(` digitado por acidente não vire erro de sintaxe.

**Alternativas rejeitadas.** Gatilhos de banco: mais difíceis de depurar, invisíveis na leitura do código Python, e propensos a divergir do esquema após migração.

---

### ADR-006 — Uma conexão SQLite por thread, com WAL e transações curtas

**Contexto.** Múltiplas threads de conta gravam no mesmo banco enquanto a UI lê.

**Decisão.** `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, e **uma conexão por thread** obtida de um `threading.local()`. Regra inviolável: **nenhuma transação fica aberta atravessando I/O de rede.**

**Consequências.**

- Positivas: WAL permite leitores concorrentes com um escritor, que é exatamente o padrão de uso; conexão por thread evita compartilhar um objeto `sqlite3.Connection`, que também não é seguro entre threads.
- Negativas: `SQLITE_BUSY` continua possível sob escrita concorrente; tratado com `busy_timeout` e nova tentativa limitada. Escritas das threads de conta são naturalmente serializadas por serem curtas.
- Imposto: a regra da transação curta é o que impede que uma conexão de rede lenta bloqueie o banco inteiro. É verificada em revisão de código e o teste CA-RF-MSG-08-1 exercita o cenário.

**Alternativas rejeitadas.** Conexão única com `check_same_thread=False` e um lock global: serializa leitura e escrita, e o lock tende a ser mantido durante a rede. Thread dedicada de escrita com fila: correta, mas complexa demais para o volume real de escrita deste aplicativo (cabeçalhos e corpos sob demanda).

---

## 4. Modelo de threads e regras de afinidade

Quatro tipos de thread, com permissões estritamente definidas. A tabela é normativa: código que viole uma linha dela é um defeito.

| Thread | Quantidade | Pode fazer | **Não pode fazer** |
|---|---|---|---|
| **GUI (principal)** | 1 | Ler cache já carregado; atualizar widgets; disparar trabalho | Rede, disco, sanitização de HTML, consulta SQL que toque o disco |
| **`AccountWorker`** | 1 por conta | Dona exclusiva da conexão IMAP; protocolo; gravação de cabeçalhos e corpos no banco | Criar ou tocar widgets; chamar métodos de `ui/` |
| **`TaskPool` (`QThreadPool`)** | `min(8, 2×contas)` | Sanitização de HTML, derivação de texto plano, indexação FTS5, cálculos de cache | Tocar a conexão IMAP; criar widgets |
| **Temporizadores (`QTimer`)** | Poucos, na thread da GUI | Agendar (undo send, polling, debounce de busca); emitir sinal | Executar trabalho pesado — apenas enfileiram |

**Comunicação: sempre e apenas por sinais Qt**, nunca por acesso direto a atributos entre threads. `AccountWorker` emite sinais; a thread da GUI os conecta a slots. Objetos entregues por sinal são **imutáveis** (dataclasses congeladas em `core/models.py`) — essa regra elimina a classe inteira de bugs de estado compartilhado mutável.

**Cancelamento.** `CancellationToken` envolvendo um `threading.Event`, checado em pontos definidos do laço de sincronização e entre mensagens. Cancelamento é cooperativo e não deixa estado inconsistente: a tarefa encerra na próxima verificação e reporta conclusão parcial, que é válida porque a gravação é incremental.

---

## 5. Contratos de interface

Os contratos são o que permite que a fase 2 (OAuth2, POP3, visualização unificada, snooze) entre sem refatoração. Estão escritos aqui como código efetivo, porque são a parte da spec que a implementação deve seguir literalmente.

### 5.1 Protocolo de cliente de entrada — `core/network/base.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True, slots=True)
class RemoteFolder:
    name: str
    delimiter: str
    kind: str  # inbox | sent | drafts | trash | archive | spam | custom


@dataclass(frozen=True, slots=True)
class FolderStatus:
    exists: int
    uidvalidity: int
    uidnext: int
    unread: int


@dataclass(frozen=True, slots=True)
class HeaderEnvelope:
    """Cabeçalhos de uma mensagem. Nunca contém corpo (RF-MSG-01)."""
    remote_id: str          # UID no IMAP; identificador estável dentro da pasta
    message_id: str | None
    subject: str
    from_name: str
    from_addr: str
    to_addrs: tuple[str, ...]
    cc_addrs: tuple[str, ...]
    date_utc: datetime
    size_bytes: int
    flags: frozenset[str]
    has_attachments: bool
    in_reply_to: str | None
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawMessage:
    """Mensagem completa, ainda não sanitizada."""
    remote_id: str
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class AttachmentMeta:
    part_id: str
    filename: str
    mime_type: str
    size_bytes: int
    content_id: str | None


@runtime_checkable
class IncomingMailClient(Protocol):
    """Contrato de recebimento. IMAP hoje, POP3 em [F2] — a UI não distingue."""

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def list_folders(self) -> Sequence[RemoteFolder]: ...
    def select_folder(self, name: str) -> FolderStatus: ...
    def fetch_headers(self, start_uid: int, limit: int) -> Sequence[HeaderEnvelope]: ...
    def fetch_body(self, remote_id: str) -> RawMessage: ...
    def fetch_attachment(self, remote_id: str, part_id: str) -> bytes: ...
    def list_attachments(self, remote_id: str) -> Sequence[AttachmentMeta]: ...
    def set_flags(self, remote_ids: Sequence[str], flags: Sequence[str], add: bool) -> None: ...
    def move(self, remote_ids: Sequence[str], destination: str) -> None: ...
    def supports(self, capability: str) -> bool: ...
    def wait_for_changes(self, timeout_s: float) -> Sequence[str]:
        """IDLE quando disponível; NOOP + UID SEARCH como alternativa (RF-MSG-05)."""
        ...
```

O token de autenticação nunca trafega por esses métodos: o cliente já nasce autenticado, construído a partir do resultado de `AuthProvider`. É isso que torna OAuth2 invisível para o resto do sistema.

### 5.2 Provedor de autenticação — `core/auth.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Resultado uniforme de autenticação, independente do mecanismo."""
    username: str
    secret: str | None          # senha ou app password; None quando usa token
    access_token: str | None    # OAuth2 [F2]
    expires_at: float | None


class AuthProvider(ABC):
    """D2: senha hoje, OAuth2 na fase 2, sem alterar UI nem storage."""

    name: str

    @abstractmethod
    def authenticate(self, account: "AccountConfig", *, interactive: bool) -> AuthResult: ...

    @abstractmethod
    def can_renew_silently(self) -> bool: ...

    @abstractmethod
    def invalidate(self) -> None: ...


class PasswordAuth(AuthProvider):
    """Lê a credencial no keyring. Nunca aceita senha vinda de arquivo ou banco."""
    name = "password"
    # authenticate() consulta core.security.get_credential(account.id)


# Registry: a fase 2 registra OAuth2Auth aqui, sem tocar em chamadores.
_PROVIDERS: dict[str, type[AuthProvider]] = {PasswordAuth.name: PasswordAuth}


def register_provider(cls: type[AuthProvider]) -> type[AuthProvider]:
    _PROVIDERS[cls.name] = cls
    return cls


def get_provider(name: str) -> AuthProvider:
    ...
```

### 5.3 Infraestrutura de tarefas — `core/tasks.py`

```python
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal


class CancellationToken:
    """Cancelamento cooperativo. Verificado em pontos definidos, nunca por interrupção."""
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled()


class AccountWorker(QThread):
    """Uma por conta. Dona exclusiva da conexão IMAP (ADR-001)."""

    headers_ready = Signal(int, object)      # account_id, tuple[HeaderEnvelope, ...]
    body_ready = Signal(int, str, object)    # account_id, remote_id, RawMessage
    folder_status = Signal(int, str, object)
    state_changed = Signal(int, str)         # idle | syncing | offline | error
    failed = Signal(int, object)             # account_id, MailError

    def submit(self, command: Callable[[CancellationToken], Any],
               *, on_result: Callable[[Any], None] | None = None,
               on_error: Callable[[Exception], None] | None = None) -> None:
        """Enfileira um comando. Executado em série, nesta thread."""
        self._queue.put(_Command(command, on_result, on_error))


class TaskPool:
    """QThreadPool para trabalho sem estado compartilhado (sanitização, índice, cache)."""
    def __init__(self, max_threads: int) -> None: ...
    def submit(self, fn: Callable[..., Any], *args: Any,
               on_result: Callable[[Any], None] | None = None,
               on_error: Callable[[Exception], None] | None = None) -> None: ...
```

### 5.4 Fachada de armazenamento — `core/storage.py`

Todos os métodos são seguros entre threads conforme ADR-006. Nomes e assinaturas são normativos:

```python
class Storage:
    def __init__(self, db_path: Path) -> None: ...

    # Migrações e ciclo de vida
    def migrate(self) -> int: ...                     # devolve a versão aplicada
    def integrity_check(self) -> bool: ...
    def close_thread_connection(self) -> None: ...

    # Contas e pastas
    def upsert_account(self, account: AccountConfig) -> int: ...
    def list_accounts(self) -> Sequence[AccountConfig]: ...
    def delete_account(self, account_id: int) -> None: ...
    def upsert_folder(self, account_id: int, folder: RemoteFolder,
                      status: FolderStatus) -> int: ...
    def list_folders(self, account_id: int) -> Sequence[FolderRecord]: ...

    # Cabeçalhos (RF-MSG-01) e corpos (RF-MSG-02)
    def insert_headers(self, account_id: int, folder_id: int,
                       envelopes: Sequence[HeaderEnvelope]) -> int: ...
    def store_body(self, message_rowid: int, raw: RawMessage,
                   sanitized_html: str, text_plain: str) -> None:
        """Grava corpo E índices na MESMA transação (ADR-005, RF-SRCH-04)."""
        ...
    def last_known_uid(self, folder_id: int) -> int: ...
    def invalidate_folder(self, folder_id: int) -> None: ...   # RF-MSG-04

    # Consulta para a lista (nunca na thread da GUI se puder tocar o disco)
    def list_messages(self, folder_id: int, *, offset: int, limit: int,
                      filters: MessageFilters | None = None) -> Sequence[MessageRow]: ...

    # Busca (RF-SRCH-*)
    def search(self, query: str, filters: MessageFilters | None = None,
               limit: int = 200) -> Sequence[MessageRow]: ...

    # Anexos (RF-MSG-07) e permissões de imagem (RF-RD-03)
    def store_attachment_meta(self, message_rowid: int,
                              metas: Sequence[AttachmentMeta]) -> None: ...
    def is_sender_allowed(self, account_id: int, from_addr: str) -> bool: ...
    def allow_sender_images(self, account_id: int, from_addr: str) -> None: ...

    # Fila de envio (RF-SND-03) e cache (RF-MSG-06)
    def enqueue_outgoing(self, draft: Draft) -> int: ...
    def due_outgoing(self, now: float) -> Sequence[OutgoingRow]: ...
    def mark_outgoing(self, outbox_id: int, state: str, error: str | None = None) -> None: ...
    def evict_bodies_lru(self, target_bytes: int) -> int: ...
```

### 5.5 Interceptor de privacidade — `ui/components/reader.py`

```python
class PrivacyInterceptor(QWebEngineUrlRequestInterceptor):
    """Última linha de defesa (ADR-003). Registra TODA tentativa, inclusive as
    bloqueadas — é esse registro que torna CA-RNF-PRIV-01-1 verificável."""

    def __init__(self, allow_remote_images: Callable[[], bool],
                 recorder: RequestRecorder) -> None: ...

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        kind = info.resourceType()
        if kind == QWebEngineUrlRequestInfo.ResourceType.ResourceTypeImage:
            if not self._allow_remote_images():
                self._recorder.record_blocked(info.requestUrl().toString())
                info.block(True)
                return
            self._recorder.record_allowed(info.requestUrl().toString())
        else:
            # Todo o resto é negado sempre: CSS remoto, fontes, XHR, mídia.
            self._recorder.record_blocked(info.requestUrl().toString())
            info.block(True)
```

Configuração do perfil e das definições, em `ReaderPane`:

```python
profile = QWebEngineProfile(self)                     # perfil off-the-record
profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
profile.setHttpCacheType(QWebEngineProfile.NoCache)
profile.setUrlRequestInterceptor(PrivacyInterceptor(...))
profile.setHttpUserAgent(GENERIC_USER_AGENT)          # não revelar impressão digital do app

s = view.settings()
s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
s.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, False)
s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
s.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)

# baseUrl fictícia: URL relativa no e-mail falha em vez de resolver para um host remoto.
view.setHtml(sanitized_html, QUrl("pymail://message/"))
```

**Requisito de inicialização.** Em algumas combinações de Qt/plataforma, o motor de renderização exige `QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)` **antes** da criação do `QApplication`, e o import de `QtWebEngineWidgets` precisa ocorrer antes de instanciar o aplicativo. `main.py` faz as duas coisas incondicionalmente, porque a falha quando isso está errado é um encerramento sem mensagem útil. **Verificar na versão de Qt efetivamente adotada no primeiro passo da tarefa T-07** — é um detalhe de plataforma, não uma certeza a ser assumida.

---

## 6. Fluxos principais

### 6.1 Sincronização inicial de uma conta

1. Thread da GUI cria a `AccountWorker` para a conta, com `AuthProvider` resolvido.
2. Worker: `connect()` → `list_folders()` → para cada pasta de interesse, `select_folder()`.
3. Worker: `fetch_headers(start_uid=1, limit=200)` em lotes; cada lote é gravado em **uma** transação (`insert_headers`) e emitido via `headers_ready`.
4. Thread da GUI recebe o lote, atualiza o modelo da lista e a barra de progresso. **Nenhum corpo é baixado** (CA-RF-MSG-01-1).
5. Ao terminar as pastas, o worker entra no laço de `wait_for_changes` (IDLE ou NOOP).
6. Nova mensagem detectada → `fetch_headers(last_uid + 1, limit=N)` → mesmo caminho do passo 3.

### 6.2 Abertura de uma mensagem

1. Usuário seleciona a mensagem; a GUI mostra imediatamente cabeçalho, remetente e estado de carregamento (RNF-USA-02).
2. Se o corpo está em cache: leitura e exibição diretas. Fim.
3. Se não está: o worker recebe `fetch_body(remote_id)`.
4. Corpo chega → **a GUI nunca sanitiza**. O `TaskPool` executa `sanitize_html` e a derivação de texto plano.
5. `store_body(...)` grava corpo, HTML sanitizado, texto plano e entradas do FTS5 na **mesma transação**.
6. Sinal para a GUI exibir o HTML sanitizado no `QWebEngineView`.
7. O `TaskPool` dispara a pré-busca das próximas N mensagens, em prioridade baixa e cancelável (RF-MSG-03).

### 6.3 Envio com Undo Send

1. Compositor validado → `Draft` → `enqueue_outgoing(state='queued', send_at=now + delay)`. A mensagem **existe em disco antes de qualquer rede** (RNF-REL-01).
2. Um `QTimer` na GUI, de 1 em 1 segundo, consulta `due_outgoing(now)`.
3. Enquanto `now < send_at`, o usuário pode cancelar: `mark_outgoing(state='canceled')` → reabre o rascunho. Nenhuma conexão SMTP foi aberta (CA-RF-SND-03-1).
4. Ao vencer, o worker de envio (SMTP tem conexão própria, separada da IMAP) transmite, e o `Message-ID` gerado no passo 1 é reaproveitado, garantindo estabilidade (CA-RF-SND-03-2).
5. Sucesso → `state='sent'`; falha → `state='failed'` com o texto do servidor e ação de reenvio.

### 6.4 Arquivar com sincronização otimista

1. Atalho `E` → a linha sai da lista **imediatamente** e a pasta de destino é atualizada no modelo local.
2. Operação entra na fila persistente de operações pendentes do worker daquela conta.
3. Worker executa `move(...)` com `UID MOVE`, ou `COPY` + `STORE \Deleted` + `EXPUNGE` (RF-ORG-05).
4. Falha definitiva → reversão com aviso explícito; nunca reversão silenciosa (CA-RF-MSG-09-1).
5. A próxima sincronização é a autoridade final e reconcilia divergências (CA-RF-ORG-05-1).

### 6.5 Busca enquanto se digita

1. Cada tecla atualiza o campo e reinicia o debounce de 250 ms (RF-SRCH-02).
2. Ao disparar, a consulta é escapada (RF-SRCH-05) e executada no `TaskPool`, nunca na GUI.
3. Resultados chegam por sinal e substituem o modelo da lista, mantendo o contexto de pasta e conta.

---

## 7. Tratamento de erros

Taxonomia em `core/errors.py`, porque a UI precisa reagir de formas diferentes e "deu erro" não é informação útil:

```python
class MailError(Exception): ...
class AuthError(MailError): ...            # credencial inválida → pedir de novo, pausar a conta
class NetworkError(MailError): ...         # transitório → recuar e tentar
class TLSError(NetworkError): ...          # certificado → NUNCA tentar sem TLS (RNF-SEC-02)
class ProtocolError(MailError): ...        # servidor respondeu algo inesperado → registrar bruto
class NotFoundError(MailError): ...        # mensagem/pasta não existe mais → remover do cache
class OperationCancelled(MailError): ...   # não é falha; não notificar o usuário
class StorageError(MailError): ...         # banco → caminho de recuperação (RF-SET-05)
```

Regras de comportamento:

| Situação | Comportamento | Requisito |
|---|---|---|
| Erro transitório de rede | Recuo exponencial (1s, 2s, 4s… teto de 5 min), estado "offline" na UI, retomada automática | RF-MSG-08 |
| Credencial inválida | Pausar **aquela** conta, notificar uma vez, oferecer reautenticação; as outras contas seguem | CA-RF-ACC-02-1 |
| Erro de certificado | Falhar e explicar; jamais prosseguir sem validação | RNF-SEC-02 |
| Mensagem sumiu no servidor | Remover do cache, `NotFoundError` não é exibido como erro | RF-MSG-04 |
| Cancelamento | Silencioso por definição | — |
| Falha ao gravar no banco | Preservar rascunhos e outbox, oferecer reconstrução do cache | RF-SET-05 |
| Falha de envio | Estado de erro visível com motivo e reenvio; nunca descarte silencioso | RF-SND-05 |

**Redação de logs.** Nenhum nível de log contém senha, token, corpo de mensagem ou caminho de anexo do usuário (CA-RF-SET-04-1). Um filtro de logging central aplica a redação; os testes verificam o resultado, não a intenção.

---

## 8. Dependências

| Dependência | Papel | Fase | Origem |
|---|---|---|---|
| `PySide6` (`Essentials` + `Addons`) | GUI, threads, `QWebEngineView` | F1 | prompt |
| `nh3` | Sanitização HTML por allowlist | F1 | **ADR-004 (acréscimo)** |
| `tinycss2` | Filtro de CSS permitido no atributo `style` | F1 | **ADR-004 (acréscimo)** |
| `html5lib` | Árvore HTML real para o passo de reescrita de privacidade entre os dois passes do `nh3` | F1 | **ADR-004 emenda (acréscimo)** |
| `keyring` | Credenciais no cofre do SO | F1 | prompt |
| `sqlite3` (stdlib) | Armazenamento e FTS5 | F1 | prompt |
| `imaplib`, `smtplib`, `poplib` (stdlib) | Protocolos | F1 / F2 | prompt, ADR-001 |
| `platformdirs` | Diretórios de dados por SO | F1 | **acréscimo menor** (alternativa: `QStandardPaths`, já disponível) |
| `pytest`, `pytest-qt`, `pytest-cov`, `ruff` | Teste e qualidade | F1 | dev |
| `aiosmtplib`, `aioimaplib` | — | — | **não usados** (ADR-001) |
| `poplib` | POP3 | F2 | prompt |

`platformdirs` é o único acréscimo discutível: `QStandardPaths` do próprio Qt resolve o mesmo problema sem dependência. **Decisão:** usar `QStandardPaths`, e não acrescentar `platformdirs`. A linha fica na tabela apenas para registrar a alternativa avaliada.

### 8.1 Localização dos dados

| Conteúdo | Local | Permissão |
|---|---|---|
| Banco (`pymail.db`, `-wal`, `-shm`) | `QStandardPaths.AppDataLocation` | 0600, diretório 0700 |
| Configuração (`config.toml`) | `QStandardPaths.AppConfigLocation` | 0600 |
| Logs | `QStandardPaths.AppDataLocation/logs`, com rotação | 0600 |
| Anexos baixados | Pasta escolhida pelo usuário; padrão `AppDataLocation/attachments` | 0600 |
| Credenciais | keyring do SO | — |

**Permissão de `config.toml` — divergência reconciliada com `05-seguranca-privacidade.md`.** A redação anterior desta spec registrava `0644`. `05` §10.1 adota `0600`, e **essa é a decisão válida**, porque `config.toml` contém hosts de servidor, nomes de usuário e a lista de remetentes com imagens autorizadas — metadados de comunicação, que `05` §1 classifica como ativo a proteger. Isso resolve o item 20 do backlog daquele documento. A configuração não contém segredo algum (as credenciais estão no keyring), então `0600` não custa nada e fecha uma exposição desnecessária em máquinas compartilhadas. Em **Windows** não existe modo POSIX: ali a proteção é a ACL herdada do perfil do usuário, e é exatamente isso que `CA-RNF-SEC-05-1` verifica.

---

## 9. Pontos de extensão para a fase 2

Cada item da fase 2 entra por um ponto já existente. Se algum exigir refatoração, este documento estava errado.

| Fase 2 | Ponto de extensão | Impacto esperado |
|---|---|---|
| OAuth2 (RF-ACC-06) | `register_provider(OAuth2Auth)` em `core/auth.py` | Novo arquivo; zero mudança em `ui/` e `storage.py` (verificado por CA-RF-ACC-04-1) |
| POP3 (RF-ACC-07) | `core/network/pop_client.py` implementando `IncomingMailClient` | Novo arquivo; campos `protocol` já no schema |
| Caixa unificada (RF-MSG-10) | `storage.list_messages_unified()` + um modelo de lista agregado | Consulta e modelo; sem mudança de schema |
| Snooze (RF-ORG-07) | Colunas `snoozed_until` já reservadas na migração v1, mais um `QTimer` | Sem migração destrutiva |
| Retenção (RF-MSG-11) | `evict_bodies_lru` já existe; acrescenta-se critério por idade | Sem mudança estrutural |
| Busca no servidor (RF-SRCH-06) | `IncomingMailClient` recebe `search()` no protocolo | Um método no protocolo e no cliente IMAP |
| Conversas (RF-RD-10) | `thread_id` reservado na migração v1 | Sem migração destrutiva |
| OpenPGP (RNF-SEC-06) | Pipeline de sanitização e `composer` | Trabalho novo, não extensão trivial |

---

## 10. Riscos técnicos

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| `nh3`/`tinycss2` sem *wheel* para alguma plataforma alvo | Baixa | Médio | Verificar na tarefa T-05, antes de qualquer código depender; alternativa `bleach` congelado se necessário |
| `QWebEngineView` frágil em ambiente headless de CI | Alta | Médio | Testes de renderização limitados a asserções sobre HTML e interceptor; renderização visual é verificação manual (ADR-003) |
| Bug de afinidade de thread em `imaplib` | Média | **Alto** | Afinidade imposta por tipo: só `AccountWorker` toca a conexão; teste com servidor falso que falha se dois comandos se cruzarem |
| `IDLE` implementado à mão divergir entre servidores | Média | Médio | Queda automática para polling após falha; teste com servidor falso que recusa IDLE |
| `SQLITE_BUSY` sob escrita concorrente | Média | Baixo | WAL, `busy_timeout`, transações curtas (ADR-006) |
| Migração de schema perder dados do usuário | Baixa | **Alto** | `schema_migrations`, teste de ida e volta por versão, recusa de downgrade (CA-RF-SET-03-1) |
| Interpretar a disponibilidade de app password do Google como permanente | Média | Alto | Backlog B-01: reconfirmar com a documentação oficial; OAuth2 na fase 2 é a resposta estrutural |
| Desvio de escopo para "cliente de e-mail completo" | **Alta** | Alto | Seção 7 de `01-requisitos.md` é normativa: fora de escopo exige decisão registrada |

---

## 11. Backlog registrado durante a especificação

| # | Item | Por que está aqui |
|---|---|---|
| B-01 | Reconfirmar, na documentação oficial de Google e Microsoft, o estado atual de autenticação básica e app passwords em IMAP/SMTP | A busca web estava indisponível durante a escrita da spec; não congelar a fase 2 sobre uma premissa não reconfirmada |
| B-02 | Medir o tamanho real do pacote por plataforma e o RSS do motor de renderização | Substituir as estimativas de `01-requisitos.md` §6 por números medidos |
| B-03 | Avaliar se a sanitização sai de `security.py` para `core/sanitizer.py` | Decisão adiada para quando o arquivo real existir (§2.1) |
