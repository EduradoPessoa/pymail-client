# 05 — Segurança e Privacidade

**Projeto:** PyMail Client · **Versão desta spec:** 1.0 · **Data:** 2026-09-25
**Documentos correlatos:** `01-requisitos.md` (requisitos e critérios de aceite) · `02-arquitetura.md` (ADR-003, ADR-004, §5.5, §7) · `03-modelo-de-dados.md` (§3, §6.3) · `04-ui-ux.md` · `06-estrategia-de-testes.md` (implementação dos testes citados aqui) · `../plans/fase1.md`

---

## 1. Modelo de ameaças

### 1.1 Ativos a proteger

| Ativo | Onde vive | Consequência da perda |
|---|---|---|
| **Credenciais** (senha, app password, token OAuth2) | keyring do SO exclusivamente | Acesso completo à caixa de correio; reutilização da senha em outros serviços |
| **Conteúdo das mensagens** (corpo, assunto, anexos) | `bodies`, `outbox`, pasta de anexos, indexado em `messages_fts` | Exposição de comunicação privada, segredos comerciais, dados de terceiros |
| **Metadados de comunicação** (quem escreve para quem, quando, com que frequência) | `messages`, `accounts`, logs | Perfil de relacionamento e de rotina; é o ativo que o rastreamento por pixel ataca |
| **Integridade do banco local** | `pymail.db` + `-wal` + `-shm` | Conteúdo adulterado exibido ao usuário; autorização de imagens inserida à força |
| **A própria máquina do usuário** | processos do motor de renderização, pasta de anexos, navegador padrão | Execução de código, movimentação lateral, dano fora do escopo do aplicativo |

### 1.2 Adversários considerados

| Adversário | Capacidade assumida | O que ele controla |
|---|---|---|
| **Remetente malicioso** | Envia HTML/CSS/nomes de anexo escolhidos; conhece a implementação do cliente | Todo o conteúdo da mensagem, incluindo cabeçalhos MIME |
| **Rastreador de marketing** | Opera servidores HTTPS de imagem e redirecionamento; usa URLs únicas por destinatário | Os recursos externos referenciados no HTML |
| **Rede hostil** | Intercepta, injeta, redireciona e apresenta certificados | Toda a camada de transporte que não esteja sob TLS validado |
| **Malware local sem privilégios elevados** | Executa como o próprio usuário; lê arquivos, processos e a memória do aplicativo | O ambiente do usuário, incluindo o keyring **desbloqueado** |
| **Servidor de correio comprometido** | Lê e altera mensagens armazenadas; injeta HTML em qualquer mensagem | O conteúdo do lado do servidor |

### 1.3 Adversários explicitamente fora de escopo

| Adversário | Por que está fora |
|---|---|
| **Atacante com privilégios de root/administrador** | Pode ler a memória do processo e o keyring desbloqueado, trocar binários e instrumentar o sistema. Não existe defesa em espaço de usuário contra isso; qualquer promessa seria falsa |
| **Malware local com os privilégios do usuário, para efeito de leitura do cache** | O banco não é cifrado (§10). A chave de cifragem teria de estar disponível no mesmo contexto de execução, o que torna a cifragem do cache uma barreira apenas contra cópia do arquivo — cenário endereçado por cifragem de disco completa (§10.4), não pelo aplicativo |
| **Coerção legal ou comprometimento do provedor de correio** | Fora do controle do aplicativo. Sem OpenPGP na fase 1 (`RNF-SEC-06` é `[F2]`), o provedor lê tudo |
| **Cadeia de suprimentos das dependências** | `PySide6`, `nh3` e `tinycss2` são tratados como artefatos confiáveis. Não há requisito de verificação de integridade nem SBOM — registrado em §14 |
| **Fornecedor do keyring ou do sistema operacional** | Se o cofre do SO é hostil, não há credencial segura. Confiança delegada por decisão de arquitetura (`RNF-SEC-01`) |
| **Atacante que controla o DNS e o roteamento e possui um certificado válido de uma CA confiável** | Um intermediário corporativo legítimo é indistinguível de um ataque para o `ssl` da stdlib. Endereçado por fixação de certificado explícita (§3.3), não por detecção |

### 1.4 Tabela de ameaças

| # | Ameaça | Vetor | Impacto | Mitigação nesta spec | Brecha residual |
|---|---|---|---|---|---|
| T-01 | Execução de código a partir do corpo da mensagem | `<script>`, `on*`, `javascript:`, `<iframe>`, `<object>`, `<embed>`, `<svg>` com manipulação de DOM | Comprometimento do processo de renderização; com JS desabilitado, exfiltração seria impossível, mas a barreira depende de o JS permanecer desabilitado | allowlist `nh3` (§4.2), JavaScript permanentemente desabilitado (§8), CSP `script-src 'none'` (§4.6), interceptor denega `ResourceTypeScript` (§7) | Um defeito no `html5ever`/`nh3` ou no nosso passo de reescrita (§4.1, passo 2) poderia deixar markup hostil passar. Impacto contido pelo *sandbox* do Chromium e por a origem ser `pymail://` (sem cookies, sem credenciais acessíveis). Não é uma brecha de escalada direta para o processo principal |
| T-02 | Confirmação de leitura por pixel | `<img>` remoto de 1×1, 0×0, ou oculto por `hidden`/`display:none`/`visibility:hidden`/`opacity:0` | O remetente aprende que a mensagem foi aberta, quando e de qual IP | Bloqueio de todas as imagens por padrão + interceptor (§7) + remoção **irreversível** do pixel (§5.1) | A heurística opera sobre markup, **nunca sobre os bytes da imagem** (§5.1.5). Um pixel de 3×3, ou uma imagem `width="1"` sem CSS oculto, ou uma imagem ocultada apenas por um ancestral, é detectável por heurística parcial ou não é detectável. Após o usuário autorizar o remetente, esse pixel dispara |
| T-03 | Beacon que não é `<img>` | `<a ping>`, `@import` remoto, `url()` em `background`, `<link rel=preload>`, `<source srcset>`, `<video poster>`, XHR, fonte remota, `favicon`, CSP report | Mesmo impacto de T-02, sem depender de imagem | Interceptor denega **todos** os tipos de recurso exceto imagem autorizada (§7); `HyperlinkAuditingEnabled=False`, `DnsPrefetchEnabled=False` (§8.4) | O interceptor só vê requisições que passam pelo motor de renderização. Requisições feitas pelo próprio Python (IMAP/SMTP) estão fora dele e são auditadas por teste em nível de socket (§11.3) |
| T-04 | Phishing por link com texto e destino divergentes | `href` real diferente do texto exibido; homoglifos; subdomínio enganoso | O usuário entrega credenciais a um terceiro | Destino real (limpo) mostrado na confirmação, com o host em destaque, e abertura no navegador padrão (RF-RD-07, CA-RF-RD-07-1) | **Não há proteção contra phishing.** O cliente mostra o destino, não o julga: não há *safe browsing* (seria telemetria, proibida por RNF-PRIV-02) nem lista de bloqueio. Um domínio visualmente semelhante continua enganando |
| T-05 | Roubo de credencial em repouso | Banco, `config.toml`, logs, argumentos de linha de comando | Acesso à conta | Keyring obrigatório, ausência deliberada de coluna de senha (`03-modelo-de-dados.md` §4), deque de proibição em logs (§2.6) | A senha existe em memória do processo enquanto a sessão dura e pode aparecer em *core dump* ou despejo de paginação. RNF-SEC-01 cobre repouso em disco, não memória — §14, item 18 |
| T-06 | Interceptação de credencial em trânsito | Servidor sem TLS, TLS derrubado por injeção de `STARTTLS` ausente, redirecionamento para porta em texto claro | Captura da senha | TLS obrigatório com validação de certificado e de hostname; `STARTTLS` que não é anunciado é falha dura (`TLSError`); nenhuma degradação silenciosa (§3) | Uma CA confiável instalada no sistema por um intermediário corporativo faz o ataque passar como legítimo. Mitigação disponível: fixação de certificado por host (§3.3), opt-in explícito |
| T-07 | Adulteração do banco local | Processo local com os privilégios do usuário altera `messages`, `bodies` ou insere linha em `sender_image_policy` | Conteúdo falso exibido; autorização de imagens pré-concedida a um remetente de phishing | WAL + transações curtas (ADR-006), `quick_check` na inicialização, `StorageError` com caminho de recuperação (RF-SET-05) | **O banco não tem autenticidade nem cifragem.** Um atacante local pode alterar qualquer linha. É consequência direta de o cache ser descartável e não cifrado (§10.3) |
| T-08 | Execução por anexo | Nome com travessia de diretório gravando fora da pasta; nome reservado do Windows; abertura automática; execução pelo SO | Execução de código na máquina do usuário | Sanitização de nome, verificação de contenção de caminho, proibição de abertura automática, aviso reforçado por tipo (§9) | O usuário ainda pode abrir o arquivo deliberadamente, e o manipulador do SO decide o que fazer com ele. O aplicativo não inspeciona conteúdo |
| T-09 | Injeção de conteúdo pelo servidor comprometido | O servidor altera o HTML de qualquer mensagem | Mesmo de T-01 e T-02 | Todo conteúdo passa pelo mesmo pipeline, independentemente da origem; não há caminho que renderize HTML não sanitizado (§4.1, invariante de §4.7) | O servidor lê todo o correio (sem E2E, `RNF-SEC-06` é `[F2]`). Nada no aplicativo mitiga confidencialidade contra o provedor |
| T-10 | Vazamento de metadados para o servidor | Comandos IMAP revelam quais pastas e mensagens são abertas | Perfil de interesse | Nenhuma mitigação. `RF-MSG-02` busca corpo sob demanda, o que já reduz a exposição em relação a um cliente que baixa tudo | Aceito: é inerente a IMAP sem E2E |
| T-11 | Impressão digital do aplicativo | User-Agent, ordem de cabeçalhos, TLS, cache, cookies | O remetente identifica o cliente e a versão, e serve conteúdo direcionado | `User-Agent` genérico, perfil off-the-record, sem cookies persistentes, sem cache (§8) | O `User-Agent` genérico ainda revela a versão do Chromium embarcado e, portanto, a faixa de versão do Qt. JA3/TLS e ordem de cabeçalhos não são alterados. É ocultação de identidade do aplicativo, não anonimato |
| T-12 | Negação de serviço por mensagem hostil | HTML de dezenas de MB, aninhamento profundo, milhares de elementos, nomes de anexo de 1 MB | Trava da interface, consumo de memória | Sanitização sempre no `TaskPool` (nunca na thread da GUI, RNF-PERF-01); teto de tamanho na entrada (§4.1, passo 0); `style` com teto de declarações (§4.5.4) | O teto de tamanho é uma escolha desta spec, não um requisito (§14, item 9). Mensagem dentro do teto pode ainda custar sanitização perceptível, mas sempre fora da thread da GUI |
| T-13 | Redirecionamento para fora do leitor | `<meta http-equiv=refresh>`, `window.location`, `target=_blank`, clique que navega a própria view | O leitor deixa de exibir a mensagem; possível tela falsa dentro de um contexto que o usuário confia | `meta` fora da allowlist; JavaScript desabilitado; clique tratado em Python com abertura externa e confirmação (RF-RD-07); `ResourceTypeMainFrame` só permitido para `pymail://` (§7) | Nenhuma conhecida dentro do pipeline |
| T-14 | Sobreposição de interface (*clickjacking*) dentro do leitor | `position:fixed`, `z-index` alto, elemento que cobre a view | Clique do usuário desviado para um link escolhido pelo remetente | `position` restrito a `static`/`relative`; `z-index` limitado; `overflow` restrito a `visible`/`hidden` (§4.5.3) | `position:absolute` continua permitido e pode sobrepor outros elementos **dentro do corpo da mensagem**, mas não os controles do aplicativo, que são widgets Qt fora da view. Impacto restrito a um link falso dentro do próprio e-mail |
| T-15 | Vazamento de caminho local pelo conteúdo | URL `file:` apontando para arquivo do usuário, posteriormente aberta no navegador padrão | Exposição de arquivo local | Esquema `file:` removido de todos os atributos; `LocalContentCanAccessRemoteUrls=False`, `LocalContentCanAccessFileUrls=False`, `UnknownUrlSchemePolicy=DisallowUnknownUrlSchemes` (§8); abertura externa restrita a `http`/`https`/`mailto` (§5.2.4) | Nenhuma conhecida |
| T-16 | Persistência de rastreamento entre mensagens | Cookie gravado na primeira mensagem e devolvido na segunda; cache HTTP confirmando leitura | Correlação de mensagens do mesmo destinatário | Perfil off-the-record + `NoPersistentCookies` + `NoCache` (§8) | O endereço IP e o instante da requisição de imagem autorizada continuam correlacionáveis pelo servidor do remetente. Sem proxy (fora de escopo, §14 item 12), nada mitiga |

---

## 2. Gestão de credenciais

### 2.1 Esquema de chaves no keyring

Esquema normativo, idêntico ao comentário da DDL em `03-modelo-de-dados.md` §3:

| Fase | `service` | `username` | Valor armazenado |
|---|---|---|---|
| F1 — `PasswordAuth` | `pymail-client` | `<email>` | Senha ou app password, em texto, tal como digitado |
| F2 — `OAuth2Auth` | `pymail-client` | `<email>#oauth` | Objeto JSON UTF-8: `{"access_token", "refresh_token", "expires_at", "token_type", "scope", "client_id"}` |

Regras:

- O **sufixo `#oauth`** separa os dois segredos da mesma conta. Sem ele, a migração de senha para OAuth2 perderia a senha antiga na primeira gravação; com ele, a remoção de uma conta pode apagar os dois sem ambiguidade.
- A chave é o **endereço de e-mail**, nunca `accounts.id`. Motivo: `03-modelo-de-dados.md` §1 estabelece que o banco é cache descartável, e o caminho de recuperação do RF-SET-05 **recria o banco do zero** com `AUTOINCREMENT` reiniciado. Chaves derivadas de `id` tornariam a credencial inalcançável após uma recuperação — o usuário seria obrigado a redigitar a senha sem que nada estivesse errado. O e-mail é estável e `UNIQUE` na tabela `accounts`.
- Normalização da chave: `email.strip().lower()`. Sem isso, `Joao@Exemplo.com` e `joao@exemplo.com` gerariam chaves distintas para a mesma conta após uma reimportação. `03-modelo-de-dados.md` **não fixa** essa normalização em `accounts.email`; ver §14, item 19.
- Nunca gravar, sob nenhuma circunstância, um valor no keyring para uma conta que não passou pela verificação de conexão de `RF-ACC-03`.
- Um único item por conta e por fase. Nada de espalhar segredo em vários itens: estado parcial é estado inconsistente.

Interface interna (`core/security.py`, prefixo `Keyring*` conforme `02-arquitetura.md` §2.1):

```python
def keyring_is_available() -> bool: ...
def keyring_get_credential(account_email: str, *, oauth: bool = False) -> str | None: ...
def keyring_set_credential(account_email: str, secret: str, *, oauth: bool = False) -> None: ...
def keyring_delete_credential(account_email: str, *, oauth: bool = False) -> None: ...
```

`keyring_delete_credential` é **idempotente**: `keyring.errors.PasswordDeleteError` (entrada inexistente) é tratado como sucesso. A remoção de conta (RF-ACC-05) não pode falhar porque a senha já havia sido apagada manualmente.

### 2.2 Keyring indisponível — comportamento obrigatório

**Nunca cair para arquivo em texto claro.** Não existe, e não existirá, uma opção de configuração que permita gravar credencial em `config.toml`, no banco ou em arquivo próprio. Uma opção dessas seria encontrada, habilitada e esquecida; a ausência da opção é a mitigação.

Alternativa aceitável e única: **credencial apenas em memória, pela duração da sessão** (`MemoryCredentialStore`, um `dict` em processo, chaveado por e-mail normalizado).

| Aspecto | Comportamento obrigatório |
|---|---|
| Detecção | `keyring_is_available()` é executado uma vez na inicialização da camada de credenciais e o resultado é cacheado. Detecção: `keyring.get_keyring()` e uma leitura de sonda de chave inexistente dentro de `try/except`, capturando `keyring.errors.NoKeyringError`, `keyring.errors.KeyringLocked` e as exceções de `secretstorage`/D-Bus expostas pelo backend |
| Proibição de backend em texto claro | Além da indisponibilidade, `keyring_is_available()` **rejeita** qualquer backend que seja um cofre em texto claro. Verificação pelo nome de módulo/classe contra uma denylist explícita: `keyring.backends.file.PlaintextKeyring`, `keyrings.alt.file.PlaintextKeyring`, `keyrings.alt.file.EncryptedKeyring` (chave ao lado do cofre), `keyring.backends.fail.Keyring`. Se o backend escolhido estiver na denylist, o resultado é "indisponível", exatamente como se não houvesse cofre |
| Dependência | `keyrings.alt` **não** é dependência do projeto. A denylist existe porque um usuário pode tê-la instalado no mesmo ambiente Python |
| Interface | Aviso não modal e persistente no rodapé da janela: *"As credenciais não podem ser guardadas: o cofre do sistema não está disponível. As senhas serão pedidas a cada início."* Com ação "Entender" que abre uma explicação do que fazer por plataforma |
| Configuração | `config.toml` registra `credential_storage = "keyring" | "memory"` para que o modo seja inspecionável sem revelar segredo. Nunca há um terceiro valor |
| Consequência declarada | **`CA-RF-ACC-01-1` não é satisfeito neste modo**: reiniciar o aplicativo exige digitar a senha novamente. A degradação é visível ao usuário, não silenciosa — é a diferença entre um cliente que falha de forma honesta e um que guarda a senha em disco "para funcionar" |
| Falha durante a sessão | Se uma gravação posterior no keyring falhar (cofre bloqueado por *timeout*), a sessão continua com a credencial em memória e o aviso é reexibido. Nada é gravado em disco |
| Encerramento | O `dict` é limpo no encerramento, em *best effort*. Registro honesto: strings em Python são imutáveis e permanecem na memória do processo até a coleta de lixo; não há como zerá-las |
| Envelope do segredo | O `dict` guarda instâncias de `Redacted` (§2.6.3), não `str` cru, para que um `print()` ou log acidental de debug não vaze |

### 2.3 Ciclo de vida da credencial

| Fase | Gatilho | Comportamento | Requisito |
|---|---|---|---|
| **Criação** | Cadastro de conta | Credencial digitada em `QLineEdit` com `EchoMode.Password` e `setInputMethodHints(Qt.ImhHiddenText | Qt.ImhNoPredictiveText)`. Teste de conexão de entrada e de saída (`RF-ACC-03`). **Somente após sucesso** dos dois, `keyring_set_credential`. Falha no teste descarta a credencial da memória da tela e não grava nada | RF-ACC-01, RF-ACC-03 |
| **Criação — falha de gravação** | Keyring indisponível no momento do cadastro | A conta é salva com `credential_storage = "memory"`, a sessão funciona, o aviso de §2.2 aparece. Idêntico no próximo início | RNF-SEC-01 |
| **Leitura** | Conexão de conta e reautenticação | Exclusivamente na thread `AccountWorker`, nunca na thread da GUI. Motivo: uma leitura de keyring pode bloquear em D-Bus ou exibir prompt do gerenciador de chaves do ambiente, e `RNF-PERF-01` proíbe bloquear a GUI | RNF-PERF-01, RNF-SEC-01 |
| **Leitura — valor ausente** | Conta existe, keyring vazio | `AuthError`: pausa **aquela** conta, notifica uma vez, oferece reautenticação. As demais contas seguem (`CA-RF-ACC-02-1`) | RF-ACC-04 |
| **Atualização** | Reautenticação com senha nova, ou app password rotacionado | `keyring_set_credential` sobrescreve o item; `accounts.updated_at` é atualizado; `AuthProvider.invalidate()` descarta qualquer cache em memória do provider | RF-ACC-04 |
| **Atualização — OAuth2 [F2]** | Refresh de token | Gravação do JSON completo, nunca parcial: um `refresh_token` novo sem o `access_token` correspondente é estado inválido | RF-ACC-06 |
| **Desativação** | Usuário desmarca `is_enabled` | **A credencial não é apagada.** Desativar conta não é remover conta | RF-ACC-02 |
| **Remoção** | `RF-ACC-05`, com confirmação explícita | Ordem obrigatória: **(1)** `keyring_delete_credential` (senha e, se houver, `#oauth`); **(2)** `storage.delete_account(account_id)`. Se o passo 1 falhar por erro que não seja "não existe", a operação é **abortada** e o usuário é informado | RF-ACC-05, CA-RF-ACC-05-1 |

**Por que a credencial sai primeiro.** Se a linha do banco fosse removida antes e a remoção da credencial falhasse em seguida, restaria um segredo órfão no cofre: o usuário não teria mais como removê-lo pela interface do aplicativo, e a conta reapareceria como "conta fantasma" em qualquer auditoria do cofre. A ordem inversa falha de forma visível e reversível: no pior caso a conta continua lá, sem credencial, pedindo reautenticação.

`CA-RF-ACC-05-1` é verificado com o **keyring falso** de `tests/fakes/`: o teste confirma que os dois itens (`<email>` e `<email>#oauth`) sumiram, que o cofre falso não tem nenhuma chave restante para aquele endereço e que a contagem de chamadas de remoção foi 2.

### 2.4 Linux sem Secret Service ativo

| Ambiente | `keyring` disponível | Comportamento |
|---|---|---|
| GNOME/Ubuntu desktop com `gnome-keyring` | Sim, via `org.freedesktop.secrets` no D-Bus de sessão | Caminho normal |
| Sessão sem D-Bus (`ssh`, `tmux` em servidor, `cron`, CI) | Não — `NoKeyringError` | Modo memória (§2.2) |
| `gnome-keyring` instalado mas cofre bloqueado | Não — `KeyringLocked` na primeira operação | Modo memória, com mensagem que explica que o cofre existe e está bloqueado — a ação do usuário é diferente da do caso anterior |
| KDE/Plasma | Depende de o KWallet expor Secret Service na versão instalada | Tratado como os dois casos acima; o aplicativo **não** assume qual backend será escolhido e não tem código específico de desktop |
| Backend em texto claro instalado no ambiente | `keyring.get_keyring()` retorna um cofre de arquivo | **Rejeitado** pela denylist de §2.2 e rebaixado a modo memória |

Regra transversal: o aplicativo nunca decide por ambiente ou por nome de distribuição. Ele pergunta ao `keyring`, valida o backend contra a denylist e reage ao resultado. Isso é verificável por teste parametrizado que injeta backends falsos: ausente, bloqueado e em texto claro.

### 2.5 Campos proibidos em logs

`RNF-SEC-01` exige que a credencial nunca apareça em log; `CA-RF-SET-04-1` exige que **nenhum nível** de log contenha senha, token, corpo de mensagem ou caminho de anexo. A lista abaixo é a deque normativa, mais estrita que o critério de aceite.

| Categoria | Campos proibidos |
|---|---|
| Credenciais | senha, app password, `secret`, `access_token`, `refresh_token`, `id_token`, `client_secret`, `code`, `code_verifier`, `code_challenge`, `state`, valor de `Authorization`, argumentos de `AUTH`/`LOGIN`/`AUTHENTICATE`, string SASL XOAUTH2, qualquer valor lido do keyring |
| Conteúdo de mensagem | `bodies.text_plain`, `bodies.html_sanitized`, HTML cru, assunto, `message_id`, `in_reply_to`, `references`, `outbox.body_text`, `outbox.body_html`, texto de `smtp_response` que ecoe destinatários |
| Metadados pessoais | endereços de e-mail (remetente, destinatário, `accounts.username`), nomes de exibição, IP de servidor com porta |
| Caminhos locais | `attachments.cache_path`, pasta de anexos escolhida pelo usuário, qualquer caminho sob o diretório pessoal, `outbox-recuperado-*.json` |
| URLs | URL de imagem com *query string* — a *query string* **é** o vetor de rastreamento e, tipicamente, conteúdo derivado da mensagem |

O que **é** permitido registrar: `account_id` numérico, nome do host de correio **sem** porta e sem usuário, esquema e tipo de recurso de uma requisição bloqueada (`https` + `ResourceTypeImage`), códigos de resposta numéricos de IMAP/SMTP, classes de exceção, mensagens de erro do próprio aplicativo, e o caminho do banco relativo ao diretório de dados.

### 2.6 Onde a redação é aplicada

Quatro camadas, da mais estrutural para a mais frágil. A ordem importa: a primeira é a que realmente protege; as demais são redes de segurança.

1. **Não passar o segredo à API de log.** O `AuthResult` de `02-arquitetura.md` §5.2 carrega `secret` e `access_token`; a dataclass é declarada com `repr=False` nesses dois campos e um `__repr__` próprio que devolve `AuthResult(username='<oculto>', secret=<oculto>, ...)`. `Draft` e `OutgoingRow` recebem o mesmo tratamento para os campos de corpo (`body_text`, `body_html`). Um `logger.debug("auth=%r", result)` não vaza.
2. **Tipo envelope.** Todo segredo em trânsito dentro do processo é `Redacted`, um `str`-like cujo `__str__`, `__repr__` e `__format__` devolvem `"***"` e cujo valor real só sai por um método explícito `reveal()`. Chamadas a `reveal()` são poucas e ficam em `auth.py` e nos clientes de protocolo.
3. **Filtro central de logging.** `RedactionFilter`, instalado em `main.py` no *handler* raiz (e não em loggers individuais, para que um logger novo não escape por omissão). Ele opera sobre `record.getMessage()` já formatado, aplicando:
   - pares `chave=valor` ou `chave: valor` para as chaves da coluna "Credenciais" e "Conteúdo" de §2.5 → `chave=<REDACTED>`;
   - remoção da *query string* de qualquer URL absoluta, preservando esquema, host e caminho;
   - endereços de e-mail → `<email-remetente>` / `<email-destinatário>` conforme a chave;
   - caminhos absolutos sob o diretório pessoal → `<caminho-local>`;
   - valores com aparência de token (sequências `[A-Za-z0-9_\-\.]{32,}` sem espaço, não pertencentes a um caminho de arquivo nem a um `message_id` já mascarado) → `<REDACTED>`.
4. **Redação na exportação do pacote de diagnóstico (RF-SET-04).** O pacote de diagnóstico é montado passando todo conteúdo por `RedactionFilter` **de novo**, com uma instância própria, porque o pacote inclui `config.toml` e trechos do banco que nunca passaram pelo logger. Teste obrigatório: gerar o pacote a partir de uma execução que cadastrou conta, leu e enviou, e varrer o pacote pelas cadeias proibidas.

**Limite honesto desta seção.** Redação por padrão é uma rede de segurança, não uma prova: um formato de log que nenhum padrão reconheça vaza. A prova é `CA-RF-SET-04-1`, executado sobre uma execução real que exercita login, leitura e envio, e o controle positivo do próprio filtro (um teste que verifica que cada padrão **casa** com uma entrada construída para ele). Um filtro que silenciosamente não casa é o modo de falha real, e é por isso que ele é testado por acerto, não só por ausência de vazamento.

---

## 3. Segurança de transporte

### 3.1 Validação de certificado (entrada e saída)

`RNF-SEC-02` vale para **todas** as conexões de correio: IMAP, SMTP, POP3 `[F2]`.

| Elemento | Definição obrigatória |
|---|---|
| Contexto TLS | `ssl.create_default_context()`, que traz `verify_mode = CERT_REQUIRED` e `check_hostname = True` com os certificados-raiz do sistema. Nunca `ssl._create_unverified_context()`, nunca `ssl.CERT_NONE` |
| Versão mínima | `context.minimum_version = ssl.TLSVersion.TLSv1_2` |
| Negociação | Sem `ciphers` customizadas, sem `PROTOCOL_TLSv1`, sem `set_ciphers` legado. A escolha é do OpenSSL com a política padrão |
| Ponto de aplicação | `imaplib.IMAP4_SSL(host, port, ssl_context=ctx)`; `imaplib.IMAP4` + `starttls(ssl_context=ctx)`; `smtplib.SMTP_SSL(host, port, context=ctx)`; `smtplib.SMTP` + `starttls(context=ctx)` |
| Verificação de hostname | Sempre ativa. Não existe caminho de código que a desligue por conveniência |
| Falha | `ssl.SSLCertVerificationError`, `ssl.SSLError` e falha de negociação são convertidas em `TLSError` (`02-arquitetura.md` §7), que é subclasse de `NetworkError` mas **não** participa da política de recuo |

### 3.2 Erro de certificado é falha dura

| Situação | Comportamento |
|---|---|
| Certificado autoassinado, expirado, com nome divergente ou cadeia incompleta | `TLSError`. Conta pausada. Mensagem que nomeia a causa: *"O certificado de `imap.exemplo.com` não pôde ser validado: nome do servidor não corresponde ao certificado."* Sem tentativa alternativa, sem porta alternativa, sem recuo |
| `TLSError` e o recuo exponencial de `RF-MSG-08` | **Exceção explícita.** `TLSError` é terminal para o ciclo de sincronização: recuar e tentar de novo produziria a mesma falha a cada tentativa, com ruído e sem ganho. Uma nova tentativa só ocorre por ação do usuário (corrigir o host, corrigir a hora do sistema, habilitar a exceção de §3.3) ou na próxima inicialização |
| Certificado válido mas com `notBefore`/`notAfter` fora da janela | `TLSError` com a causa "relógio do sistema" quando a divergência exceder 24 h — o cenário mais comum é relógio errado, e a mensagem precisa dizer isso |
| Relatório de erro | A mensagem exibe host, causa e impressão digital SHA-256 do certificado apresentado, para que o usuário possa conferir por canal independente. A impressão digital vai para a UI e para o banco de diagnóstico; **não** vai para os logs em produção |

### 3.3 Exceções habilitáveis pelo usuário, de forma auditável

Existe **uma** forma de exceção, e ela não é "desligar a validação":

**Fixação de certificado por host.** Quando o usuário decide confiar em um servidor cujo certificado não valida (servidor próprio, servidor com certificado interno, rede doméstica), ele fixa a impressão digital SHA-256 do certificado apresentado. Regras:

- Registro em `config.toml`, na seção da conta, com os quatro campos obrigatórios: host, porta, `sha256` da impressão digital em minúsculas, `pinned_at` (epoch). Sem `pinned_at` não há auditoria.
- Aceito **apenas** o certificado cuja impressão digital coincide em SHA-256 do DER. Nenhuma tolerância a "mesmo emissor", a "mesmo assunto" ou a qualquer heurística.
- A exceção vale **por host e por porta**, nunca por conta inteira, e nunca globalmente.
- Aviso persistente e não dispensável na barra da lista de mensagens daquela conta, enquanto a fixação estiver ativa: *"Certificado verificado por fixação manual em `<host>`"*. Não existe forma de ocultar esse aviso. (Não há requisito nem critério de aceite para esse aviso; ver §14, item 15.)
- Toda conexão com fixação ativa é registrada em log com `account_id`, host e `pinned_at` — sem impressão digital, sem usuário, sem porta.
- A fixação **nunca** é oferecida como botão primário de uma caixa de diálogo de erro. Ela fica atrás de um link secundário, precedida da explicação de que significa confiar em um certificado específico e de que, se o servidor renovar o certificado, a conexão passará a falhar — o que é o comportamento correto de uma fixação.
- Remover a fixação é uma ação de um clique em "Contas", sem confirmação adicional (ação restritiva, não destrutiva).

**Proibido e sem código correspondente:** `verify_mode=CERT_NONE`, `check_hostname=False`, contexto "TLS opcional", flag de ambiente que relaxe validação, uso de `load_verify_locations` para *substituir* os certificados do sistema. Adicionar a CA do intermediário ao cofre do sistema operacional é decisão do usuário fora do aplicativo e, por definição, deixa de ser uma exceção auditável pelo PyMail Client — o aplicativo não deve encorajar esse caminho. (Não há requisito para gerenciar CAs adicionais a partir do aplicativo; §14, item 15.)

### 3.4 Proibição de degradação silenciosa

| Vetor de degradação | Tratamento |
|---|---|
| Servidor em 143 que não anuncia `STARTTLS` | Falha dura. Nunca prosseguir em texto claro "porque o servidor não suporta" |
| Falha do handshake após `STARTTLS` | Abortar a conexão. Nunca continuar no canal não cifrado: um servidor hostil responde `NO` a `STARTTLS` justamente para induzir essa queda |
| Capacidade `LOGINDISABLED` anunciada antes do STARTTLS | Respeitada: nenhum comando de autenticação antes do STARTTLS |
| Rebaixamento por redirecionamento de porta | Não existe redirecionamento no protocolo. A porta vem do cadastro e não é renegociada |
| Detecção tardia de que a conexão não é TLS | O cliente verifica `sock`/`ssl` do objeto de conexão antes de emitir qualquer comando de autenticação. A verificação é uma asserção de código, não uma convenção |
| Variável de ambiente ou flag que relaxe TLS | Não existe. Teste automatizado afirma isso: a varredura de `core/network/` não encontra `CERT_NONE`, `check_hostname=False` nem `_create_unverified_context` |

### 3.5 Tabela de combinações host/porta/segurança

Legenda: **Aceita** = conexão permitida com validação completa; **Exceção** = permitida somente com a fixação de §3.3 e o aviso persistente; **Recusada** = erro de configuração, com mensagem explicando o motivo.

| Protocolo | Porta | `security` | Veredito | Observação |
|---|---|---|---|---|
| IMAP | 993 | `ssl` | Aceita | TLS implícito. Padrão do cadastro |
| IMAP | 143 | `starttls` | Aceita | Exige annúncio de `STARTTLS` e handshake bem-sucedido **antes** de qualquer `AUTHENTICATE` |
| IMAP | 143 | `none` | **Recusada** | `RNF-SEC-02` exige TLS de entrada. O `CHECK` do schema aceita `'none'`, mas a camada de conexão recusa — ver §14, item 10 |
| IMAP | 993 | `starttls` | Recusada | `STARTTLS` sobre porta de TLS implícito falha sempre; erro de configuração, não de servidor |
| IMAP | 143 | `ssl` | Recusada | Handshake TLS contra porta em texto claro falha com `TLSError`; o aplicativo não tenta texto claro depois |
| IMAP | 993 | `none` | Recusada | Sem TLS em porta cifrada: erro explícito de configuração |
| IMAP | outras | qualquer | Recusada por padrão | Só permitida com configuração manual explícita e TLS válido; nunca em texto claro |
| SMTP | 465 | `ssl` | Aceita | TLS implícito de submissão |
| SMTP | 587 | `starttls` | Aceita | Submissão com `STARTTLS` obrigatório |
| SMTP | 25 | `starttls` | Aceita | Exige `STARTTLS` anunciado e bem-sucedido |
| SMTP | 25 | `none` | **Recusada**, salvo exceção | Exige `allow_insecure_outgoing = 1` (RF-SND-07) |
| SMTP | 587 | `none` | **Recusada**, salvo exceção | Idem |
| SMTP | 465 | `starttls` | Recusada | Erro de configuração |
| SMTP | qualquer | `none` com `allow_insecure_outgoing = 0` | **Recusada** | Padrão do schema (`03-modelo-de-dados.md` §3) |
| POP3 `[F2]` | 995 | `ssl` | Aceita | |
| POP3 `[F2]` | 110 | `starttls` | Aceita quando o servidor anunciar `STLS` | |
| POP3 `[F2]` | 110 | `none` | **Recusada** | Sem exceção de entrada (ver §14, item 10) |
| Qualquer | qualquer | algoritmo/versão anterior a TLS 1.2 | Recusada | `minimum_version = TLSv1_2` |

### 3.6 Credencial em canal sem TLS (RF-SND-07)

`RF-SND-07` exige TLS na saída por padrão e que a transmissão de credencial em texto claro só ocorra com habilitação explícita. Implementação:

1. `outgoing_security = 'none'` **e** `allow_insecure_outgoing = 0` → o envio é recusado no cliente, antes de abrir socket, com mensagem que explica que a credencial seria enviada em texto claro. Verificável por `CA-RF-SND-07-1`.
2. `allow_insecure_outgoing = 1` → o envio é permitido, e a interface mostra aviso permanente na tela de contas: *"Este servidor de saída não usa TLS. Sua senha é enviada em texto claro."*
3. A ativação da exceção é registrada no log como evento auditável: `account_id`, host de saída e o fato de a exceção estar ativa. Sem usuário, sem senha, sem porta.
4. **Mecanismo de autenticação em texto claro:** mesmo com a exceção ativa, o cliente recusa `AUTH LOGIN`/`AUTH PLAIN` sobre canal não cifrado quando o servidor oferece `XOAUTH2` ou `CRAM-MD5`, e prefere o mecanismo que não exponha a senha. A exceção autoriza transmitir a mensagem, não necessariamente a senha em claro.
5. O estado da exceção é lido do banco a cada conexão — nunca cacheado em memória de longa duração, para que desligar a exceção tenha efeito imediato.
6. **Limite honesto:** com a exceção ativa, a senha e o conteúdo da mensagem trafegam em claro e são legíveis por qualquer ponto do caminho. Nada no aplicativo mitiga isso. O valor da exceção é permitir servidores internos legados, e o custo é declarado ao usuário no momento em que ele a habilita.

---

## 4. Pipeline de sanitização de HTML

Esta é a funcionalidade central do produto e a de maior risco. O pipeline é uma função pura `sanitize_html(raw_html: str, context: SanitizeContext) -> str`, sem I/O, executada **sempre** no `TaskPool` e nunca na thread da GUI (`02-arquitetura.md` §6.2, passo 4).

### 4.1 Ordem exata das operações

A ordem é normativa. Cada passo foi posicionado onde está por uma razão que a inversão quebraria.

| # | Passo | Executa | Por que nesta posição |
|---|---|---|---|
| 0 | `normalize_input` | Decodifica o charset declarado no MIME (com queda para `utf-8` e depois `latin-1`), remove BOM, remove bytes `NUL` (`\x00`) e aplica o teto de tamanho (`MAX_HTML_BYTES = 5 MiB`). Acima do teto, o HTML é descartado e a mensagem é renderizada a partir do `text/plain` derivado | O `NUL` pode truncar a leitura em camadas que tratam a cadeia como C-string, produzindo divergência entre o que o sanitizador vê e o que o motor vê — a definição de *parser differential*. O teto é o que impede T-12 |
| 1 | **`nh3` — passe A** (`structure_pass`) | Allowlist de tags, atributos e esquemas (§4.2–§4.4), com `attribute_filter` que (a) **descarta todo atributo de prefixo `data-pymail-`**, (b) descarta todo atributo de prefixo `on`, (c) aplica o filtro CSS do §4.5 ao valor de `style`, (d) valida tamanho e conteúdo escalar de atributos. Saída: `html_a` | Passo estrutural: normaliza a árvore, decodifica referências de caractere, resolve `svg`/`math` como conteúdo estrangeiro e elimina `<base>`, `<meta>`, `<style>`, `<link>`, `<picture>`, `<source>`, `<svg>`, `<math>`. **Descartar `data-pymail-*` aqui é indispensável**: reserva o espaço de nomes dos nossos marcadores. Se um remetente pudesse escrever `data-pymail-src` diretamente, ele contornaria todo o bloqueio de pixels no momento da restauração |
| 2 | **Passo de privacidade** (`privacy_rewrite`) | Sobre `html_a`, com `html5lib` (mesmo algoritmo de construção de árvore do `html5ever`, portanto sem divergência relevante de parsing): **(2a)** remove `<img>` identificada como pixel (§5.1) — elemento e atributos, sem deixar rastro; **(2b)** remove parâmetros de rastreamento de `href` (§5.2), incluindo na *fragment string*; **(2c)** move a URL remota preservada de `src` para `data-pymail-src` e de `cid:` para `data-pymail-cid`; **(2d)** remove `src` de todas as imagens | Precisa vir **depois** do passe A, para que os marcadores que ele escreve não sejam descartados pela regra "descarta `data-pymail-*`". E precisa vir **antes** do passo 3, que é a autoridade final. Ver §4.1.1 para as três inversões que produzem defeito |
| 3 | **`nh3` — passe B** (`seal_pass`) | Mesma allowlist do passe A, **mais** `generic_attribute_prefixes` incluindo `data-pymail-`. Saída: `html_sanitized` | A **autoridade estrutural é sempre a última transformação**. Qualquer coisa que o passo 2 tenha introduzido de errado (atributo inesperado, aninhamento estranho, esquema hostil marcado por engano) é reavaliada aqui. O resultado é que um defeito no passo 2 pode, no pior caso, rotular mal uma URL, mas não introduzir XSS |
| 4 | `tracking_param_scan` / `pixel_scan` | Não altera o HTML: devolve um `SanitizeReport` com contagens (pixels removidos, parâmetros removidos, imagens remotas preservadas, imagens autorizáveis) para a interface e para os testes | Última leitura do artefato final, para que as contagens descrevam o que realmente foi gravado |
| 5 | `derive_plain_text` | Deriva o texto plano **de `html_sanitized`**, nunca do HTML cru | `RF-RD-02` pede texto plano para pré-visualização e indexação. Derivar do HTML cru colocaria no índice FTS5 e na pré-visualização conteúdo que foi removido — por exemplo o texto dentro de `<script>`, que apareceria em resultados de busca (`RF-SRCH-01`) |
| 6 | `wrap_document` | Monta o documento final: `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="…"><meta name="referrer" content="no-referrer"></head><body>…</body></html>` | O `<meta>` de CSP só tem efeito se estiver no `<head>` e antes do conteúdo. Montamos o documento nós mesmos justamente para garantir que a política seja a primeira coisa depois do `charset` |
| 7 | Persistência | `store_body` grava `html_sanitized`, `text_plain`, `sanitizer_version` e o índice FTS5 na **mesma transação** | ADR-005, RF-SRCH-04 |
| 8 | Restauração (renderização, opcional) | Quando há autorização de imagens para o remetente: `restore_remote_images` executa o inverso do passo 2c (`data-pymail-src` → `src`) e **em seguida o passe B de novo** (`seal_pass`), com a allowlist que não permite `data-pymail-`. O resultado é a string entregue a `setHtml` | Garante o invariante de §4.7: **toda** string que chega ao motor passou pelo `nh3` como última transformação estrutural, inclusive a restaurada |

#### 4.1.1 Por que a ordem importa — três inversões que produzem defeito

1. **Reescrita antes da remoção de pixels reintroduz o pixel.** Se `src` fosse movido para `data-pymail-src` (2c) antes de a heurística rodar (2a), a heurística teria de reconhecer "imagem remota" por um atributo que já não é `src`. Pior: a remoção deixaria de ser evidente, e a autorização do remetente restauraria o pixel — exatamente o que `RF-RD-04` e `RNF-PRIV-03` proíbem. Depois da remoção primeiro, o pixel não existe no artefato: **não há URL para restaurar**.
2. **Filtro CSS antes da detecção de pixel apaga a evidência.** Se o filtro de §4.5 rodasse primeiro, `display:none` e `visibility:hidden` seriam removidos por não estarem na allowlist de valores seguros, e uma imagem oculta por esses meios deixaria de parecer oculta para a heurística. Por isso o filtro CSS roda dentro do passe A sobre o valor **original** do atributo `style`, e a detecção de pixel do passo 2 roda sobre `html_a` — cujo `style` filtrado preserva `display`/`visibility`/`opacity` justamente porque são propriedades com valores seguros (`display:none`, `visibility:hidden`, `opacity:0` sobrevivem ao filtro; o que não sobrevive é `url()`, `expression()` e `--*`).
3. **Remoção de `<base>` depois da reescrita congela um host remoto.** Se o passo de privacidade resolvesse URLs relativas contra a `<base href>` do remetente antes de `<base>` ser descartada, toda imagem relativa se tornaria absoluta apontando para o host do remetente — e passaria a ser "restaurável" sob autorização, com um host que o usuário nunca escolheu. Como `<base>` não está na allowlist e é descartada no passe A, URLs relativas permanecem relativas e falham contra a `baseUrl` fictícia `pymail://message/` (`02-arquitetura.md` §5.5). Consequência aceita: imagens relativas nunca carregam, nem com autorização.
4. **Remoção de parâmetros depois da cópia preserva rastreadores na cópia.** Se a URL fosse copiada para um atributo `data-*` antes da limpeza (2b), a cópia manteria `utm_*`/`fbclid` e seria ela a usada na restauração. Por isso a limpeza (2b) é anterior a qualquer cópia.

### 4.2 Allowlist de tags

Somente estas tags sobrevivem. Qualquer outra é descartada pelo `nh3`, preservando o conteúdo textual dos filhos quando a tag não estiver em `clean_content_tags`.

```text
a, abbr, address, article, aside, b, bdi, bdo, blockquote, br, caption, center,
cite, code, col, colgroup, dd, del, details, dfn, div, dl, dt, em, figcaption,
figure, footer, h1, h2, h3, h4, h5, h6, header, hr, i, img, ins, kbd, li, main,
mark, nav, ol, p, pre, q, s, samp, section, small, span, strike, strong, sub,
summary, sup, table, tbody, td, tfoot, th, thead, time, tr, tt, u, ul, var, wbr
```

Configuração obrigatória de `nh3` que acompanha esta lista: `clean_content_tags = {"script", "style"}`. Sem isso, o `nh3` preserva o **conteúdo textual** de uma tag descartada — e o corpo de um `<script>` apareceria como texto visível na mensagem e, pior, seria indexado pelo FTS5 pelo passo 5.

**Tags deliberadamente fora da allowlist, com a razão:**

| Tag | Por que não |
|---|---|
| `script` | Execução de código. Descartada com conteúdo |
| `style` | Um bloco `<style>` é CSS que o `nh3` **não** interpreta: `@import`, `url()`, `expression()` e seletores passariam intactos. Filtrado seria possível, mas o custo de risco não se paga na fase 1. **Custo declarado:** e-mails que dependem de um bloco `<style>` perdem formatação e ficam visualmente mais pobres; só o atributo `style` inline sobrevive |
| `iframe`, `frame`, `frameset`, `noframes` | Subdocumento com origem e carregamento próprios; vetor de beacon e de *clickjacking* |
| `object`, `embed`, `applet`, `param` | Carregamento de plugin/objeto ativo |
| `form`, `input`, `button`, `select`, `option`, `textarea`, `label`, `fieldset`, `legend`, `output`, `datalist`, `keygen`, `progress`, `meter` | Coleta de dados e ação em nome do usuário dentro de um conteúdo que não é confiável. Nem desabilitado: removido |
| `svg`, `math` | Conteúdo estrangeiro com namespaces, `xlink:href`, `<foreignObject>` e `<animate>`: a área onde mais se encontram divergências entre sanitizadores e motores |
| `base` | Redefine a resolução de toda URL relativa do documento |
| `meta`, `link` | `http-equiv=refresh`, `link rel=preload`/`dns-prefetch`/`stylesheet`. O `<meta>` de CSP é injetado por nós no passo 6, não vem do remetente |
| `picture`, `source` | `srcset`/`media` são vetores de requisição que a allowlist de atributos não teria como restringir sem perder utilidade. Descartadas, o `<img>` interno é promovido e segue o caminho normal |
| `video`, `audio`, `track` | Mídia remota e *beacon* por `poster`; nenhuma utilidade em cliente de e-mail |
| `template` | Conteúdo inerte para o parser, ativo ao ser clonado — divergência clássica de sanitização |
| `marquee`, `blink`, `font`, `big`, `nobr` | Obsoletas; sem ganho de fidelidade que justifique superfície |
| `map`, `area` | `area` carrega `href` e `coords`; `map` sem `area` é inútil |

### 4.3 Allowlist de atributos

Atributos globais, aceitos em qualquer tag da allowlist:

| Atributo | Regra |
|---|---|
| `style` | Filtrado por `tinycss2` conforme §4.5. Teto de 4096 caracteres e 32 declarações; acima disso, o atributo inteiro é descartado |
| `title` | Texto puro, até 512 caracteres; nunca interpretado como URL |
| `dir` | Apenas `ltr`, `rtl`, `auto` |
| `lang` | Formato `[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*`, até 3 subtags |
| `role` | Valor obrigatoriamente em uma lista fixa de papéis ARIA mantida em código. Valor fora da lista: o atributo é descartado |
| `aria-*` | Prefixo genérico `aria-`. Pelo `nh3`, via `generic_attribute_prefixes`. Valor até 256 caracteres |
| `data-pymail-*` | Prefixo genérico. **Somente no passe B**; o passe A descarta todo atributo com esse prefixo |

Atributos por tag:

| Tag | Atributos permitidos | Regra adicional |
|---|---|---|
| `a` | `href`, `title` | `href`: §4.4, mais a remoção de parâmetros de §5.2. Sem `target`, sem `rel`, sem `ping`, sem `download`, sem `referrerpolicy` |
| `img` | `alt`, `width`, `height`, `title`, `data-pymail-src`, `data-pymail-cid` | `alt`: até 512 caracteres. `width`/`height`: apenas inteiros decimais (aceito sufixo `px`), faixa 1–4096; qualquer outro valor (percentual, `auto`, `inherit`, unidade exótica) faz o atributo ser descartado. `src` **não** consta: quem o escreve é o passo 2 ou a restauração |
| `td`, `th` | `colspan`, `rowspan`, `align`, `valign`, `width`, `height`, `headers`, `scope` | `colspan`/`rowspan`: inteiro 1–1000. `align`: `left\|center\|right\|justify\|char`. `valign`: `top\|middle\|bottom\|baseline`. `width`/`height`: inteiro 1–4096 ou percentual inteiro 1–100% |
| `table` | `border`, `cellpadding`, `cellspacing`, `width`, `align`, `summary` | `border`/`cellpadding`/`cellspacing`: inteiro 0–20. `summary`: até 512 caracteres |
| `col`, `colgroup` | `span`, `width` | `span`: inteiro 1–1000 |
| `ol` | `start`, `type`, `reversed` | `start`: inteiro −10000–10000. `type`: `1\|a\|A\|i\|I` |
| `li` | `value` | Inteiro |
| `blockquote`, `q` | `cite` | Esquema validado por §4.4; a URL nunca é buscada, é exibida |
| `del`, `ins`, `time` | `datetime` | Validado por formato (`YYYY-MM-DD`, `YYYY-MM-DDThh:mm`, com ou sem `Z`/offset). Aqui uma expressão regular é aceitável: valida um escalar de formato fixo, não interpreta HTML nem CSS |
| `details` | `open` | Booleano |

**Nunca permitidos, em nenhuma tag, em nenhum passe** — a lista é a deque negativa mais importante do pipeline:

`srcset`, `imagesrcset`, `sizes`, `imagesizes`, `background`, `poster`, `lowsrc`, `dynsrc`, `formaction`, `action`, `method`, `ping`, `manifest`, `data`, `codebase`, `archive`, `classid`, `usemap`, `srcdoc`, `sandbox`, `http-equiv`, `content`, `target`, `rel`, `download`, `integrity`, `nonce`, `crossorigin`, `referrerpolicy`, `autofocus`, `autoplay`, `controls`, `loop`, `muted`, `preload`, `xlink:href`, `xml:base`, `xmlns`, qualquer atributo cujo nome comece por `on` (coberto por prefixo, não por enumeração), `id`, `class`, `name`, `slot`, `is`, `part`, `exportparts`.

`id` e `class` estão fora por decisão explícita: como `<style>` é descartado, não existe nada que os referencie, e `id` habilitaria navegação por fragmento dentro do documento. Não há ganho de fidelidade que pague a superfície.

### 4.4 Esquemas de URL permitidos

Antes de qualquer decisão por esquema, o valor passa por `normalize_url_value`:

1. Remover caracteres de controle C0 e C1, `DEL`, e todo espaço em branco (ASCII e Unicode) do **início e do fim**.
2. Rejeitar o valor se contiver `NUL` ou qualquer caractere de controle **em qualquer posição**.
3. Aplicar normalização Unicode `NFKC`.
4. Rejeitar valores acima de 8192 caracteres.
5. Determinar o esquema como o texto antes do primeiro `:` quando ele casar `[A-Za-z][A-Za-z0-9+.\-]*`; comparar em minúsculas contra a allowlist.
6. Se não houver esquema, o valor é **relativo**: nunca é resolvido contra a origem da mensagem, nunca é completado com host. Permanece relativo.

A tabela abaixo é normativa. "Descartar o atributo" significa remover o atributo inteiro, não esvaziá-lo — um `href=""` continuaria clicável e apontaria para a própria página.

| Esquema | `a/@href`, `blockquote/@cite`, `q/@cite` | Imagem (`src` antes do passo 2) | Tratamento e razão |
|---|---|---|---|
| `http` | **Permitido** | **Preservado** em `data-pymail-src` | Único caso em que um `http:` sobrevive: como destino de link. Ele é exibido ao usuário na confirmação e aberto no navegador padrão; a decisão de seguir é do usuário |
| `https` | **Permitido** | **Preservado** em `data-pymail-src` | Esquema normal de destino e de imagem |
| `mailto` | **Permitido** | — | Não abre o navegador: abre o compositor (`RF-SND-01`). Sem `?body=`, sem `?subject=` — apenas o endereço é aproveitado, e os parâmetros são descartados |
| `javascript` | **Descartar** | **Descartar** | Execução de código. Cobre `JaVaScRiPt:`, `java\tscript:`, `&#x6a;avascript:` (já decodificado pelo `nh3`) e variantes com espaços internos, porque a normalização do passo 3 e a comparação em minúsculas são aplicadas ao valor decodificado |
| `vbscript` | **Descartar** | **Descartar** | Legado de execução |
| `data` | **Descartar** | **Descartar** | Bloqueio **integral** na fase 1, inclusive para imagens base64 legítimas. Razão: `data:text/html` em `href` seria um documento aberto no navegador do usuário; `data:image/svg+xml` é um vetor de script e de referência externa; e a única forma de permitir base64 com segurança exige validação de MIME, teto de tamanho decodificado e rejeição de SVG — superfície que não se paga. **Custo declarado:** mensagens que embutem imagens como URI base64 não exibem essas imagens. Decisão a ratificar em §14, item 8 |
| `cid` | **Descartar** | Convertido em `data-pymail-cid` (nunca em `src`) | Não é recurso remoto: é parte MIME da própria mensagem. Na fase 1 **não é renderizado** (§6.4). Fora de `<img>`, descartado |
| `file` | **Descartar** | **Descartar** | Leitura de arquivo local e, no caso de `href`, entrega ao navegador padrão. Cobre `file:///`, `file://host/` e `\\servidor\share` (que, sem esquema, é tratado como relativo e nunca resolvido) |
| `ftp`, `ftps` | **Descartar** | **Descartar** | Esquema abandonado pelos navegadores; nenhum destino legítimo |
| `blob`, `filesystem` | **Descartar** | **Descartar** | Só existem com JavaScript; a presença indica conteúdo construído para um ambiente que não temos |
| `about`, `chrome`, `resource`, `qrc`, `pymail` | **Descartar** em conteúdo | **Descartar** | Esquemas internos do motor ou nossos. Conteúdo de mensagem nunca os alcança |
| `ws`, `wss` | **Descartar** | **Descartar** | Canal persistente |
| `tel`, `sms`, `geo`, `market`, `intent` | **Descartar** | — | Disparam manipuladores externos do sistema sem valor em e-mail de desktop |
| relativo | **Mantido como relativo** | **Descartado** de `data-pymail-src` | Sem host, não há o que preservar: contra `pymail://message/` a URL relativa falha. Consequência aceita: imagens relativas nunca carregam |
| qualquer outro | **Descartar** | **Descartar** | Allowlist: desconhecido é negado, não permitido |

Defesa em profundidade: `nh3` recebe `url_schemes = {"http", "https", "mailto", "cid"}`, deliberadamente **sem** `data`. Se um defeito no nosso `attribute_filter` deixar passar um `href` hostil, o `nh3` o descarta mesmo assim — e isso cobre as obfuscações que o próprio `nh3` já normaliza. A validação fina por tag acontece no nosso filtro, porque `nh3` aplica a mesma lista a todos os atributos de URL e não distingue `href` de `src`.

Toda URL descartada incrementa um contador no `SanitizeReport` e é registrada com a categoria do esquema rejeitado — nunca com o valor completo, que em `utm_*` ou `fbclid` é justamente o identificador de rastreamento (§2.5).

### 4.5 CSS no atributo `style`

#### 4.5.1 Por que o `nh3` sozinho não basta

O `nh3` é um sanitizador de **estrutura HTML**. Ele não é um interpretador de CSS: quando o atributo `style` está na allowlist, o valor atravessa sem ser examinado. Consequências diretas, todas verificadas por `CA-RF-RD-01-1`:

- `style="background-image: url('https://rastreador.example/px.gif')"` produz uma requisição de rede que **não é** um `<img>` — nenhuma heurística de HTML a vê.
- `style="width: expression(alert(1))"` passa intacto; o `expression()` é uma função, não uma tag.
- `style="behavior: url(#default#time2)"` e `-moz-binding` são vetores equivalentes.
- `style="@import url(https://exemplo/x.css)"` (malformado, mas aceito por parsers tolerantes) é um carregamento de folha de estilo remota.
- `style="position: fixed; top:0; left:0; width:100%; height:100%; z-index:9999"` sobrepõe a interface do leitor.

**Onde o `tinycss2` entra:** ele tokeniza o valor de `style` de acordo com a gramática de CSS — decodificando escapes `\75 rl(` em `url(`, tratando comentários `/* */` como trivia e produzindo blocos de função tipados. A filtragem opera sobre essa árvore de tokens, não sobre texto. É exatamente por isso que `tinycss2` e não uma busca por substrings: `background: u\72 l('https://x')` seria invisível para uma busca textual e é um `FunctionBlock` chamado `url` para o tokenizador.

#### 4.5.2 Onde o filtro roda

O filtro roda dentro do `attribute_filter` do **passe A** (§4.1, passo 1) — portanto sobre o valor original, decodificado e normalizado pelo `nh3`, e antes de qualquer remoção de pixel. Isso é o que preserva `display`, `visibility` e `opacity` como sinais para a heurística de §5.1 (inversão 2 de §4.1.1).

Saída do filtro: uma cadeia de declarações `propriedade: valor;` apenas com o que sobreviveu, ou `None` (atributo descartado) se nada sobreviveu.

#### 4.5.3 Allowlist de propriedades

```text
background-color, border, border-bottom, border-bottom-color, border-bottom-style,
border-bottom-width, border-collapse, border-color, border-left, border-left-color,
border-left-style, border-left-width, border-radius, border-right, border-right-color,
border-right-style, border-right-width, border-spacing, border-style, border-top,
border-top-color, border-top-style, border-top-width, border-width, bottom, caption-side,
clear, color, direction, display, empty-cells, float, font, font-family, font-size,
font-style, font-variant, font-weight, height, left, letter-spacing, line-height,
list-style, list-style-position, list-style-type, margin, margin-bottom, margin-left,
margin-right, margin-top, max-height, max-width, min-height, min-width, opacity,
overflow, overflow-x, overflow-y, padding, padding-bottom, padding-left, padding-right,
padding-top, position, right, table-layout, text-align, text-decoration,
text-decoration-color, text-indent, text-transform, top, unicode-bidi, vertical-align,
visibility, white-space, width, word-break, word-spacing, word-wrap, z-index
```

Valores restritos para as propriedades que importam à segurança:

| Propriedade | Valores aceitos | Motivo da restrição |
|---|---|---|
| `position` | `static`, `relative` | **`fixed` e `absolute` são excluídos.** `fixed` posiciona em relação à viewport do leitor e permite sobrepor a mensagem inteira, inclusive criar um alvo de clique falso em cima de um link legítimo. `absolute` sai do fluxo e permite sobreposição dentro do corpo. **Custo:** e-mails que usam `position:absolute` para diagramar perdem o layout. Aceito em troca de eliminar T-14 |
| `overflow`, `overflow-x`, `overflow-y` | `visible`, `hidden` | `auto`/`scroll` criam barras de rolagem dentro do conteúdo e permitem esconder conteúdo fora da área visível |
| `visibility` | `visible`, `hidden`, `collapse` | Enumerado |
| `display` | `block`, `inline`, `inline-block`, `flex`, `inline-flex`, `grid`, `inline-grid`, `table`, `inline-table`, `table-row`, `table-cell`, `table-row-group`, `table-header-group`, `table-footer-group`, `table-column`, `table-column-group`, `list-item`, `none`, `contents` | Enumerado. Não há vetor de URL em `display`; a lista existe para impedir valores exóticos que alguns motores interpretam de forma divergente |
| `opacity` | número entre `0` e `1` | Numérico. `opacity: 0` é permitido porque a detecção de pixel já rodou no passo 2 — o filtro não pode destruir o sinal antes de ele ser lido |
| `z-index` | inteiro entre `-100` e `100` | Limitado |
| `top`, `right`, `bottom`, `left` | comprimento entre `-1000px` e `1000px`, ou `0` | Limitado: `left: -99999px` é uma técnica de ocultação |
| `width`, `height`, `min-*`, `max-*` | comprimento positivo ou percentual, até `4096px` / `100%` | Teto |
| `font-size` | comprimento até `256px` ou percentual até `1000%` | Teto |
| `color`, `background-color`, `border-*-color` | cor nomeada, `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()`, `hsl()`, `hsla()`, `transparent`, `currentcolor` | Sem `url()` |
| Qualquer outra | valor como comprimento, percentual, número, cor, palavra-chave enumerada ou uma das funções permitidas abaixo | — |

**Funções permitidas em valores:** `rgb()`, `rgba()`, `hsl()`, `hsla()`, `calc()`, `min()`, `max()`, `clamp()`.

**Funções e construções proibidas:**

| Construção | Tratamento | Razão |
|---|---|---|
| `url(...)` — em qualquer posição, com ou sem aspas, com escape ou com comentário | Descarta a **declaração** inteira | Requisição de rede originada por CSS: `background-image`, `list-style-image`, `cursor`, `@font-face` |
| `expression(...)` | Descarta a declaração | Avaliação de expressão em motores legados; hoje não executa, mas o valor não tem uso legítimo e a rejeição é gratuita |
| `var()` e propriedades personalizadas `--*` | Descarta a declaração e **descarta toda declaração cujo nome comece por `--`** | **Crítico.** `--x: url(https://rastreador/px.gif); background-image: var(--x)` passa por qualquer filtro que só examine a declaração `background-image`: o token `url()` está no valor da propriedade personalizada, e a substituição ocorre em tempo de valor computado. Sem `var()` e sem `--*`, essa classe de contorno desaparece |
| `attr()` | Descarta a declaração | Não tem uso legítimo aqui |
| `image()`, `image-set()`, `cross-fade()`, `element()`, `paint()`, `-webkit-image-set()` | Descarta a declaração | Todas carregam recurso |
| `@import`, `@media`, `@supports`, `@font-face`, `@namespace`, qualquer at-rule | Descarta o nó | O valor de um atributo `style` não contém at-rules legítimos; a presença indica entrada malformada de propósito |
| `behavior`, `-moz-binding`, `filter`, `-webkit-filter`, `backdrop-filter` | Propriedades fora da allowlist | Vetores legados e superfícies de renderização |
| `font-face`/`src` | Descartados | — |
| `!important` | Removido do valor, mantendo a declaração | Determinismo da saída; sem folhas de estilo, não há precedência a disputar |
| Comentários `/* */` | Removidos pela tokenização | Não podem esconder um `url(` do tokenizador — é a razão de usar `tinycss2` |
| Nó que não seja `Declaration` (bloco de função solto, `;` extra, token desconhecido) | Descartado | Entrada malformada não gera saída |

#### 4.5.4 Tetos e limites

| Item | Limite | Ação ao exceder |
|---|---|---|
| Comprimento do atributo `style` | 4096 caracteres | Descartar o atributo inteiro |
| Número de declarações | 32 | Descartar as excedentes |
| Comprimento de um valor | 256 caracteres | Descartar a declaração |
| Profundidade de aninhamento de funções | 8 | Descartar a declaração |

Os tetos existem contra T-12: `calc(calc(calc(...)))` com 50 mil níveis é uma negação de serviço barata de escrever.

#### 4.5.5 Conteúdo que escapa do contêiner

Mesmo com `position` restrito, um conteúdo pode transbordar: `width: 4096px` em uma `<table>`, `margin-left: -1000px`, `letter-spacing` absurdo. Defesas: tetos numéricos de §4.5.3 e a própria view, cujo conteúdo é renderizado em um widget com rolagem própria, **sem** sobreposição sobre os controles Qt do aplicativo (a view é filha de um layout, não um *overlay*). Nada no conteúdo da mensagem pode cobrir a barra de ferramentas, a lista de mensagens ou a barra de status — o que limita o impacto de T-14 ao interior do painel do leitor.

### 4.6 Content-Security-Policy injetada

Diretiva exata injetada no `<head>` do documento montado (passo 6), para o caso **sem autorização de imagens** — o padrão:

```text
default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'
```

Para o caso **com autorização de imagens** do remetente, muda **uma** diretiva: `img-src https:` (nunca `http:`, nunca `data:`, nunca `*`).

```text
default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src https:; font-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'
```

Companheiro obrigatório no `<head>`, imediatamente após a CSP: `<meta name="referrer" content="no-referrer">`. Impede que uma requisição de imagem autorizada carregue qualquer informação de referência.

| Diretiva | O que defende em profundidade |
|---|---|
| `default-src 'none'` | Rede fechada por padrão. Qualquer tipo de recurso que eu tenha esquecido de enumerar cai aqui. É a diretiva que transforma a CSP em allowlist, e não em blocklist |
| `script-src 'none'` | Segunda barreira contra T-01, independente de `JavascriptEnabled=False` e do `nh3`. Se uma configuração de perfil regredir (§8.6), esta diretiva ainda bloqueia a execução |
| `style-src 'unsafe-inline'` | Necessária para os atributos `style` que sobreviveram ao filtro de §4.5. O `'unsafe-inline'` é aceitável **porque** todo `url()` e `var()` já foi removido em §4.5 e porque `img-src`/`font-src` fecham os canais de exfiltração por CSS. Custo: uma folha de estilo `<style>` injetada não executaria de todo modo, pois a tag está fora da allowlist |
| `img-src 'none'` / `img-src https:` | Terceira barreira contra T-02/T-03, e a que cobre `url()` em CSS caso o filtro de §4.5 falhe. É também a razão de a decisão de §4.4 (bloquear `data:`) ser coerente: sem `data:`, não é preciso abrir exceção |
| `font-src 'none'` | Fonte remota é beacon clássico e vetor de impressão digital (T-11) |
| `connect-src 'none'` | Bloqueia `fetch`/XHR/WebSocket/`sendBeacon`, inclusive a partir de CSS ou de um recurso que eu tenha permitido por engano |
| `object-src 'none'`, `frame-src 'none'`, `worker-src 'none'`, `media-src 'none'`, `manifest-src 'none'` | Fecham as categorias de recurso ativo que a allowlist de tags já removeu. Defesa em profundidade contra regressão da allowlist |
| `form-action 'none'` | Impede envio de formulário, mesmo se um `<form>` reaparecer por regressão |
| `base-uri 'none'` | Impede `<base>`, mesmo se ele reaparecer. Sem isso, um `<base href="https://atacante/">` tornaria remota toda URL relativa — o cenário da inversão 3 de §4.1.1 |

**Limites honestos da CSP:**

- A política é entregue por `<meta>`, e a especificação **ignora** `frame-ancestors`, `report-uri`, `report-to` e `sandbox` quando o transporte é `<meta>`. Por isso `frame-ancestors` não é incluída: seria decoração. Não precisamos dela, porque o documento nunca é enquadrado.
- Diretivas não implementadas pelo Chromium — como `navigate-to` e `prefetch-src` — foram deliberadamente omitidas em vez de incluídas "por completude": uma diretiva não suportada dá uma falsa sensação de cobertura.
- A CSP é a **terceira** linha. Se ela for ignorada por completo (uma versão de motor que não a aplique ao `setHtml`), o `nh3` e o interceptor continuam valendo. Ordem de confiança: allowlist de estrutura e de CSS (§4.2–§4.5) > interceptor (§7) > CSP.

### 4.7 Invariantes do pipeline

1. **Nenhuma string chega a `view.setHtml()` sem ter passado pelo `nh3` como última transformação estrutural.** Vale para o HTML sanitizado e para o HTML restaurado (passo 8). É verificável por teste: um duplo de `setHtml` captura a string e afirma que ela não contém `data-pymail-` (o passe B descarta esse prefixo) e não contém nenhum dos padrões proibidos.
2. **`sanitize_html` é idempotente:** `sanitize(sanitize(x)) == sanitize(x)`. Propriedade testada com o corpus hostil inteiro; é o que garante que a restauração do passo 8 não degrada o resultado.
3. **`sanitize_html` é pura e não bloqueia I/O.** Roda no `TaskPool`. Nenhuma chamada de rede, nenhuma leitura de banco, nenhum acesso ao keyring.
4. **O HTML cru nunca é persistido.** `03-modelo-de-dados.md` §6.3 não reserva coluna para ele, e não haverá: nenhum leitor do banco — usuário, ferramenta de diagnóstico ou atacante local — consegue obter HTML não sanitizado do disco.
5. **`SANITIZER_VERSION`** é uma constante inteira em `core/security.py`, incrementada a cada mudança de allowlist, de lista de esquemas, de propriedades CSS, de heurística de pixel ou de lista de parâmetros de rastreamento. As versões de `nh3` e `tinycss2` são fixadas em `pyproject.toml`; subir qualquer uma delas exige rodar o corpus hostil completo e incrementar `SANITIZER_VERSION` (o que, por `03-modelo-de-dados.md` §6.3, marca os corpos antigos para rebusca sob demanda).
6. **Nenhum caminho de código renderiza HTML não sanitizado.** Nem pré-visualização, nem página de erro, nem anexo (§9.6).

### 4.8 Por que allowlist e nunca blocklist

| Argumento | Detalhe |
|---|---|
| O espaço do desconhecido é infinito | Uma blocklist de tags precisa enumerar `script`, `iframe`, `object`, `embed`, `applet`, `frame`, `frameset`, `layer`, `ilayer`, `bgsound`, `isindex`, `marquee`… e continua errada na próxima tag que um motor passar a reconhecer. Uma allowlist não é afetada por uma tag nova: ela é negada por omissão |
| Falha segura vs. falha aberta | Um defeito em uma blocklist deixa passar. Um defeito em uma allowlist deixa de fora. O erro da allowlist é visível (conteúdo sumiu) e reversível; o erro da blocklist é invisível e explorável |
| Variação entre motores | `nh3` descarta uma tag não permitida preservando os filhos; um motor que não reconheça a tag a trata como elemento desconhecido. Divergências de tratamento são a matéria-prima de *mXSS*. Com allowlist, "não reconhecido" e "proibido" convergem para o mesmo resultado |
| Auditoria | Uma allowlist é uma lista curta e revisável; uma blocklist é uma lista que ninguém consegue afirmar completa. A primeira pode ser assinada em revisão de código; a segunda não |
| Custo | A allowlist exige atualização deliberada a cada necessidade legítima nova — e essa atualização é o ponto onde um revisor humano pensa sobre o risco. É trabalho, e é trabalho útil |

### 4.9 Por que nunca com expressões regulares

1. **HTML não é uma linguagem regular.** A construção de árvore do HTML5 inclui inserção de tags implícitas, *foster parenting* de conteúdo de tabela, tratamento de `<p>` e `<li>` sem fechamento, e conteúdo estrangeiro em `svg`/`math`. Uma expressão regular opera sobre uma sequência de caracteres e vê um documento diferente do que o motor vê. Essa diferença tem nome — *parser differential* — e é a causa raiz da maioria dos contornos de sanitizador conhecidos.
2. **A remoção por regex quebra a estrutura.** Remover `<script>.*?</script>` de `<div title="</script><img src=x onerror=y>">` produz markup que o parser reconstrói de forma diferente da que a regex supôs.
3. **Referências de caractere.** `&#x3c;script&#x3e;` é texto para a regex e uma tag para o parser — **a menos** que ela decodifique entidades, e aí a regex passa a reimplementar uma parte do parser, com todos os erros que isso implica.
4. **CSS tem gramática própria, com escapes e comentários.** Também não é regular na prática: `u\72 l(...)`, `/* */` entre quaisquer tokens, escapes hexadecimais de 1 a 6 dígitos. `tinycss2` resolve isso com um tokenizador; regex não resolve.
5. **Onde regex é aceitável:** validar um escalar de formato fixo — `datetime` de §4.3, o formato de `lang`, o padrão de nome de atributo. A regra não é "nunca use regex"; é **"nunca use regex para interpretar HTML ou CSS"**.

---

## 5. Bloqueio de rastreamento

### 5.1 Pixels de rastreamento

#### 5.1.1 Heurísticas de detecção

Aplicadas no passo 2a (§4.1) a elementos `<img>` de `html_a`, cujo `style` já passou pelo filtro de §4.5 (o que preserva `display`, `visibility` e `opacity` como sinais). `R` = sinal de reforço (não decide sozinho); `D` = sinal decisivo.

| # | Heurística | Como é detectada | Papel | Falso positivo |
|---|---|---|---|---|
| H1 | 1×1 em atributos | `width` e `height` ambos presentes e ≤ 2 (aceito sufixo `px`) | **D** | Baixo. Um elemento de espaçamento legítimo de 1×1 é removido — perda cosmética |
| H2 | 0×0 em atributos | `width` ou `height` igual a `0` ou `0px`, com o outro presente | **D** | Nenhum uso legítimo |
| H3 | `hidden` presente | Atributo booleano `hidden` | **D** | Nenhum: conteúdo oculto não tem função em leitura de e-mail |
| H4 | Oculto por CSS inline | Valor de `style` contém, após tokenização: `display:none`, `visibility:hidden`, `visibility:collapse`, `opacity:0`, `height:0`, `max-height:0`, `width:0`, `max-width:0`, `transform:scale(0)`, `clip:rect(0…)`, `clip-path:inset(50%)`, `overflow:hidden` combinado com `height:0` | **D** | Baixo: e-mail que use `display:none` para conteúdo responsivo perde a imagem |
| H5 | Atributo conflitante com CSS | `width`/`height` de atributo ≤ 2 **e** um `width`/`height` de CSS declarando valor > 2, ou o inverso | **D** | Médio. O conflito é sinal de construção deliberada; a política é remover, porque o custo é uma imagem ausente e o benefício é não confirmar leitura |
| H6 | Área declarada mínima | `width` × `height` ≤ 4 quando ambos presentes | **D** | Baixo |
| H7 | `border="0"` com dimensão mínima | `border="0"` **e** (H1 ou H2 ou H6) | **D** (o `border` isolado é **R**) | `border="0"` sozinho é ubíquo em e-mail legítimo e **nunca** decide — está listado apenas como reforço, e é por isso que a propriedade `border` continua na allowlist de §4.3 |
| H8 | Sem nome significativo | `alt` ausente ou vazio **e** o nome do arquivo na URL corresponde a `pixel`, `beacon`, `open`, `track`, `spacer`, `blank`, `clear`, `transparent`, `1x1`, `dot` (com parênteses de extensão `gif\|png\|jpg`) | **R** | `spacer.gif` costuma ser espaçamento legítimo — mas sua remoção também é inócua, então na dúvida remove |
| H9 | Atributos de acompanhamento | Presença simultânea de H1/H2/H6 e de `aria-hidden="true"` | **R** | Baixo |
| H10 | Parâmetros de rastreamento na URL | A URL contém qualquer parâmetro de §5.2 | **R** | Médio: um banner legítimo de campanha é removido |

Regra de decisão: **H1 ∨ H2 ∨ H3 ∨ H4 ∨ H5 ∨ H6 ∨ (H7 ∧ (H1∨H2∨H6))** ⇒ remover o elemento. Sinais **R** nunca decidem sozinhos.

#### 5.1.2 A remoção é irreversível — implementação

A remoção acontece no passo 2a e consiste em **remover o elemento `<img>` inteiro**, com todos os seus atributos, incluindo a URL. Não há "marcação para depois": nenhum `data-pymail-src` é escrito para um pixel, nenhum registro em tabela auxiliar, nenhuma lista de URLs ignoradas.

Por que isso é irreversibilidade estrutural, e não uma promessa de política:

- A URL do pixel **não existe** em nenhum lugar do sistema depois da sanitização. O HTML cru não é persistido (`03-modelo-de-dados.md` §6.3), o `bodies.html_sanitized` contém apenas o HTML sem o elemento, e nenhuma outra tabela guarda URLs de imagem.
- A restauração de §6.3 é uma cópia mecânica de atributo: `data-pymail-src` → `src`. Como não existe `data-pymail-src` para um pixel, **não há o que restaurar**. Nenhuma mudança futura na lógica de autorização pode ressuscitar a URL, porque a informação não está lá.
- Consequência: um defeito na autorização por remetente pode carregar imagens que o usuário talvez não quisesse, mas **não** pode reintroduzir o vetor de confirmação de leitura que o produto promete bloquear.

#### 5.1.3 Por que irreversível

| Razão | Detalhe |
|---|---|
| Requisito explícito | `RF-RD-04` diz "remover de forma **irreversível** … mesmo que o usuário autorize imagens do remetente", e `RNF-PRIV-03` repete a exigência. `CA-RF-RD-04-1` é o critério |
| Consentimento não cobre rastreamento | O botão "Carregar imagens deste remetente" significa "quero ver as imagens desta mensagem". Não significa "autorizo a confirmação de leitura". Interpretar o gesto como consentimento amplo seria uma decisão de produto tomada contra o usuário |
| A remoção reversível deixa o artefato contaminado | Se a URL do pixel fosse preservada para uma eventual restauração, ela estaria no banco, e o banco é lido por ferramentas de diagnóstico, por exportação e por qualquer processo local (T-07). Qualquer defeito na restauração, ou qualquer novo consumidor do HTML sanitizado, reintroduziria o pixel. Remover o dado elimina a categoria inteira de falha |
| Custo declarado | E-mails que usam uma imagem 1×1 como elemento de espaçamento (técnica comum em HTML de e-mail) perdem um espaçamento. O layout pode deslocar alguns pixels. Aceito |

#### 5.1.4 Verificação

- `CA-RF-RD-04-1`: com `tracking_pixel_1x1.eml` e `tracking_pixel_css_hidden.eml`, **com autorização de imagens ativa para o remetente**, o interceptor registra zero requisições para a URL do pixel, e o `bodies.html_sanitized` gravado não contém a URL do pixel como substrings — asserção de teste sobre o artefato, não sobre a intenção do código.
- `CA-RF-RD-03-1`: com imagens bloqueadas, mensagem com 20 imagens remotas produz zero requisições.
- `CA-RNF-PRIV-01-1`: corpus completo de §13.2 produz zero requisições.

#### 5.1.5 Limites honestos do bloqueio de pixel

O sanitizador vê **markup, nunca os pixels**. Ele não busca os bytes da imagem — buscar seria exatamente o que se recusa a fazer. Consequências:

| Brecha residual | Por que ocorre | Impacto |
|---|---|---|
| Pixel de 3×3, 10×10, ou com conteúdo quase transparente, sem indicação no markup | Nenhuma heurística baseada em markup o distingue de uma imagem pequena legítima | Após autorização do remetente, confirma a leitura. Esta é a **brecha principal** e não é fechável sem baixar a imagem |
| `<img>` cujo tamanho real é 1×1 mas que declara `width="600"` | A declaração mente; só os bytes revelariam | Idem |
| Imagem ocultada por um ancestral (`<div style="display:none"><img width="600" height="400">`) ou por um `<td width="1">` | A heurística não computa layout; analisar cascata e layout seria reimplementar um motor de renderização | Idem |
| Pixel que depende de uma folha de estilo remota para ser ocultado | A folha é bloqueada, então a imagem aparece em tamanho natural e não é identificada como pixel | Idem — e a imagem grande é visível, o que é ao menos honesto |
| Parâmetro de rastreamento em URL de imagem legítima (H10) | Sinal apenas de reforço | Nenhum: a URL com o parâmetro é removida de `src` de todo modo e substituída por `data-pymail-src`; o parâmetro **não** é limpo nesse caso, portanto a URL original com o rastreador é preservada e, sob autorização, é buscada com ele. Tratado em §14, item 14 |

O que a arquitetura garante apesar disso: **antes da autorização, nenhum desses casos gera requisição** — o interceptor é a barreira efetiva (§7), e a heurística existe para que a remoção sobreviva à autorização. A heurística cobre a esmagadora maioria dos pixels reais; não cobre o adversário deliberado. Dizer o contrário seria prometer o que o código não entrega.

### 5.2 Parâmetros de rastreamento em links

#### 5.2.1 Lista e semântica

Base obrigatória, de `RF-RD-05`:

```text
utm_source, utm_medium, utm_campaign, utm_term, utm_content, utm_id, utm_name,
utm_reader, utm_referrer, utm_social, utm_social-type, utm_brand, utm_source_platform,
utm_creative_format, utm_marketing_tactic,   # família utm_* (prefixo)
fbclid, gclid, mc_eid, _hsenc, _hsmi, vero_id, igshid
```

Complemento proposto por esta spec, a ratificar (§14, item 14). Entradas marcadas com o que quebrariam se removidas por engano:

```text
gclsrc, dclid, msclkid, yclid, wbraid, gbraid, twclid, ttclid, epik, s_cid, sc_cid,
mkt_tok, _ke, _ga, _gl, _openstat, mc_cid, pk_campaign, pk_kwd, mtm_campaign,
mtm_source, mtm_medium, mtm_content, mtm_term, oly_anon_id, oly_enc_id,
_branch_match_id, wickedid, spm, scm, cmpid, si, ref_src, ref_url
```

Regras de aplicação:

- Comparação **sem diferenciar maiúsculas de minúsculas** (`UTM_SOURCE`, `FbClId`). Normaliza-se o nome para minúsculas antes de comparar.
- A família `utm_*` é tratada por **prefixo**, não por enumeração: o prefixo é a origem mais comum de variantes novas e enumerar é trabalho perdido.
- Removidas **todas** as ocorrências, inclusive repetições do mesmo nome.
- Parâmetros sem valor (`?fbclid`) são removidos igualmente.
- Remoção aplicada à *query string* **e** à *fragment string* (onde o padrão `#utm_source=…` também aparece). O **caminho nunca é tocado**.
- Se a remoção esvaziar a query, o `?` é removido. Se esvaziar o fragmento, o `#` é removido.
- Se o resultado for idêntico ao original, o `href` não é reescrito (evita mexer em URLs já limpas).
- Se a URL for malformada a ponto de não ser possível separar query e caminho com segurança, **a URL é descartada** (atributo removido) e o `SanitizeReport` registra o caso. Allowlist: na dúvida, remover.

#### 5.2.2 Nunca remover

A lista é uma **denylist sobre nomes de parâmetro**, e um nome errado quebra funcionalidade de forma silenciosa e difícil de diagnosticar. Ficam permanentemente fora da lista, mesmo que apareçam em alguma fonte de rastreamento:

```text
id, ids, code, token, key, api_key, apikey, sig, signature, hash, nonce, state,
session, sid, auth, access_token, refresh_token, expires, exp, expiring, ts, t,
v, p, q, s, n, page, paged, offset, limit, start, end, date, lang, locale, hl,
ref, return, return_url, redirect, redirect_uri, next, url, u, link, target,
file, path, doc, id_doc, num, numero, pid, uid, gid, cid, order, pedido,
```

Razão: `token`, `code`, `key` e `sig` aparecem em links de redefinição de senha, confirmação de cadastro, *magic links* e URLs assinadas. Removê-los quebra o link de modo que o usuário percebe como "o cliente corrompeu o link", e o encaminha para o suporte errado.

#### 5.2.3 Processo de manutenção da lista

| Etapa | Regra |
|---|---|
| Onde vive | Uma constante única, `TRACKING_QUERY_PARAMS: frozenset[str]` mais `TRACKING_QUERY_PREFIXES: frozenset[str]`, em um módulo dedicado, com uma linha de comentário por entrada indicando a origem (documentação do fornecedor, relatório público, ou observação de campo) |
| Como uma entrada nova entra | (1) fixture em `tests/fixtures/links/tracking_params.txt` com a URL crua e a URL limpa esperada; (2) teste parametrizado cobrindo a nova entrada, incluindo uma variação de caixa e uma variação sem valor; (3) revisão humana confirmando que o nome não está na lista de §5.2.2 |
| Guarda automatizada | Um teste afirma que `TRACKING_QUERY_PARAMS` e `RESERVED_QUERY_PARAMS` são **disjuntos**. Acrescentar `token` à lista de rastreamento falha a suíte em vez de quebrar o link de um usuário em produção |
| Guarda de compatibilidade | Um corpus de URLs reais de `tests/fixtures/links/real_world.txt`, com a URL funcional esperada, roda a cada mudança. Se uma entrada nova quebrar alguma, o teste aponta qual |
| Não é atualizada pela rede | A lista é embarcada no aplicativo. Buscar uma lista remota seria uma conexão de saída não justificada e violaria `RNF-PRIV-02`. Consequência: a lista envelhece entre versões — aceito em troca de não abrir um canal |
| Remoção de entrada | Igualmente deliberada: uma entrada que quebre funcionalidade legítima é removida com o mesmo procedimento, na direção inversa |

#### 5.2.4 Comportamento na interface

| Situação | Comportamento | Requisito |
|---|---|---|
| Passar o mouse sobre um link | Barra de status do leitor mostra a URL **limpa**, com o host em destaque. É o destino real, não o original: o usuário vê o que será aberto | RF-RD-05 |
| Clicar em um link | Diálogo de confirmação obrigatório, mostrando o **host registrável** em destaque, a URL limpa completa em fonte monoespaçada e selecionável, e os botões "Abrir no navegador" (secundário) e "Cancelar" (padrão/foco inicial) | RF-RD-07 |
| Texto do link diferente do destino | O diálogo mostra **os dois**, rotulados: *"Exibido: `https://banco-falso.com`"* e *"Destino real: `https://exemplo.com/x`"*. Quando o texto exibido é ele mesmo uma URL, o alerta é destacado visualmente. Nunca abrir o texto exibido, nunca completar o destino com base no texto | CA-RF-RD-07-1 |
| Texto exibido igual ao destino | Diálogo normal, sem o bloco de divergência | RF-RD-07 |
| Esquema diferente de `http`/`https` | Não abre o navegador. `mailto:` abre o compositor com o endereço preenchido e **sem** os parâmetros `subject`/`body` do link. Qualquer outro esquema: link inerte e registro do esquema rejeitado | RF-RD-07 |
| Fragmento e query após limpeza | Exibidos como ficaram. O usuário vê exatamente o que será aberto, e não o que o remetente escreveu | RF-RD-05 |
| Nenhuma navegação interna | A view **nunca** navega. Todo clique é interceptado em Python (`linkClicked`/`acceptNavigationRequest` negando) e resolvido pelo diálogo. Combinado com `ResourceTypeMainFrame` bloqueado para esquemas diferentes de `pymail://` (§7) | RF-RD-07 |

**Custo declarado:** a confirmação obrigatória acrescenta um clique a **todo** link. A alternativa — confirmar apenas quando o texto divergir do destino — foi rejeitada porque a divergência é detectável justamente pelo adversário mais competente (que escreve o texto como o destino real e usa homoglifos ou subdomínio parecido), e porque o custo de um clique é pequeno comparado ao de uma credencial entregue a um terceiro. `T-04` permanece parcialmente aberto de qualquer forma (§1.4): o cliente mostra o destino, não o avalia.

---

## 6. Imagens externas e autorização por remetente

### 6.1 Estado padrão

Toda mensagem é renderizada com `img-src 'none'` (§4.6) e zero imagens remotas restauradas. As imagens aparecem como o `alt` textual, com uma faixa não modal no topo do leitor: *"Imagens externas bloqueadas"* e o botão **"Carregar imagens deste remetente"**. `RF-RD-03`, `RNF-PRIV-01`.

### 6.2 Concessão da autorização

| Passo | Comportamento |
|---|---|
| Gatilho | Clique em "Carregar imagens deste remetente" no leitor |
| Confirmação | O botão informa o endereço que está sendo autorizado (`from_addr` normalizado em minúsculas) e que a autorização valerá para mensagens futuras desse remetente naquela conta. Não há confirmação modal adicional: o próprio botão é a ação explícita |
| Gravação | `storage.allow_sender_images(account_id, from_addr)` insere em `sender_image_policy`, com `ON CONFLICT(account_id, from_addr) DO UPDATE SET allowed_at = excluded.allowed_at` para que reautorizar atualize o carimbo em vez de falhar |
| Efeito imediato | A mensagem aberta é re-renderizada pela restauração do passo 8 (§4.1), com `img-src https:` |
| Persistência | Sobrevive ao reinício (`CA-RF-RD-03-2`). A política não depende de a mensagem continuar em cache |
| Escopo | `UNIQUE (account_id, from_addr)`. Nunca global, nunca por domínio, nunca por mensagem |
| Não-autorização implícita | Nada autoriza automaticamente: abrir a mensagem, respondê-la, encaminhá-la ou movê-la não concede nada. Não existe "autorizar todas as imagens" global. Não existe autorização por lista de remetentes confiáveis importada |

### 6.3 O que é restaurado, exatamente

A restauração (`restore_remote_images`) executa sobre `bodies.html_sanitized` e faz exatamente isto:

1. Para cada `<img>` com `data-pymail-src`, copia o valor para `src` e remove o `data-pymail-src`.
2. Executa o **passe B** (`seal_pass`, §4.1 passo 3) sobre o resultado, com a allowlist que **não** permite `data-pymail-`.
3. Injeta o documento com `img-src https:` (§4.6).
4. Entrega a string a `view.setHtml(..., QUrl("pymail://message/"))`.

O que **não** é restaurado:

| Item | Por quê |
|---|---|
| Pixels de rastreamento | Removidos no passo 2a; a URL não existe mais (§5.1.2) |
| `srcset` / `<source>` / `<picture>` | As tags estão fora da allowlist; `srcset` nunca esteve na allowlist de atributos. Sem essas construções, não há variação por densidade de tela — perda de fidelidade aceita |
| `background` de tabela/célula | Atributo fora da allowlist; `background-image` em CSS tem `url()` removido |
| CSS remoto | `style-src` sem `url()`; folhas remotas bloqueadas no interceptor |
| Imagens relativas | Descartadas no passo 2c: sem host, não há o que preservar |
| Imagens `data:` | Bloqueadas por decisão de §4.4 |
| Imagens `cid:` | Convertidas em `data-pymail-cid` e **não** renderizadas na fase 1 (placeholder textual, com o nome do arquivo; o arquivo continua acessível pelo painel de anexos) |
| Imagens em `http:` | Bloqueadas mesmo sob autorização (§7), com aviso de contagem |
| Fontes, folhas de estilo e qualquer outro recurso | Nunca autorizados por este caminho. A autorização é de **imagem**, e o interceptor continua negando todo o resto |

### 6.4 Granularidade da autorização e sua consequência de segurança

A granularidade é **(conta, endereço de remetente)**. Não é por mensagem, não é por host de imagem, não é por domínio do remetente.

Consequências, ditas sem atenuar:

| Consequência | Análise |
|---|---|
| Autorizar uma vez libera todas as mensagens futuras daquele remetente naquela conta | É a única granularidade que evita pedir autorização a cada mensagem — o que, na prática, treinaria o usuário a clicar em "sim" por reflexo e destruiria o valor do consentimento. `CA-RF-RD-03-2` exige exatamente esse comportamento |
| Autorizar um remetente libera imagens de **qualquer host HTTPS** referenciado nas mensagens dele | **Esta é a brecha mais relevante desta seção.** Um remetente legítimo que use um provedor de e-mail marketing autorizado a carregar imagens de um CDN de rastreamento transfere a autorização para esse CDN, e o CDN aprende o IP e o instante da leitura. O cliente **não** tenta adivinhar quais hosts são "do remetente": essa heurística erraria tanto para bloquear CDNs legítimos quanto para permitir rastreadores |
| A autorização é por conta | Um remetente autorizado na conta pessoal não é autorizado na conta de trabalho, mesmo com o mesmo endereço. Impede que uma conta comprometida amplie a superfície de outra |
| Remetente forjado | `from_addr` é o campo `From:` do cabeçalho, que um remetente pode forjar. Como a autorização é local (não há verificação de SPF/DKIM no cliente — não há requisito para isso), um atacante que forje o `From:` de um remetente já autorizado faz suas imagens carregarem. Impacto limitado: ele aprende o IP e a hora, que é o que ele já conseguiria com um pixel de qualquer forma |
| Comparação do endereço | `from_addr` é comparado em minúsculas e sem espaços, consistente com `03-modelo-de-dados.md` §3 ("sempre minúsculo"). O nome de exibição **não** participa: autorizar "Banco X <a@x.com>" autoriza `a@x.com`, e um "Banco X <b@y.com>" não herda nada |
| Revogação | `RNF-PRIV-04` exige autorização "granular e revogável, gerenciável em um painel". O `Storage` de `02-arquitetura.md` §5.4 **não expõe** método de revogação nem de listagem; ver §14, item 4 |

Brecha residual aceita, em uma frase: **autorizar um remetente é autorizar a leitura daquele remetente a ser confirmada pelos hosts HTTPS que ele referenciar** — exatamente o comportamento de todo cliente de e-mail mainstream, e o preço de um consentimento utilizável em vez de um consentimento por imagem.

### 6.5 Revogação e gerenciamento

Comportamento especificado (dependente da lacuna do §14, item 4):

| Operação | Comportamento |
|---|---|
| Listar | Painel "Privacidade → Imagens autorizadas", agrupado por conta, mostrando endereço, data da autorização (`allowed_at`) e quantidade de mensagens em cache daquele remetente. A listagem exige `list_allowed_senders()` em `Storage` |
| Revogar uma | `revoke_sender_images(account_id, from_addr)`: apaga a linha e re-renderiza, se a mensagem aberta for daquele remetente, voltando a `img-src 'none'` |
| Revogar todas de uma conta | Ação com confirmação explícita, por ser potencialmente ampla |
| Revogar por exclusão de conta | Coberta por `ON DELETE CASCADE` em `sender_image_policy` (`03-modelo-de-dados.md` §3), verificada por `CA-RF-ACC-05-1` |
| Efeito imediato | A política é consultada a cada renderização, nunca cacheada em memória de longa duração. Revogar tem efeito na próxima abertura, sem reinício |
| Verificação | Teste de ida e volta: autorizar, reiniciar, confirmar autorização ativa; revogar, confirmar zero requisições na mesma mensagem; confirmar que a linha sumiu do banco |

---

## 7. Interceptor de rede

### 7.1 Por que este é o controle principal

O interceptor é a **defesa principal** de privacidade, e não a sanitização, por uma razão simples: ele opera no ponto onde a requisição seria emitida, e portanto cobre tudo que a sanitização de HTML não vê.

| O que escapa da sanitização de HTML | Por que a sanitização não basta | Como o interceptor resolve |
|---|---|---|
| `background-image: url(...)` em CSS | É uma declaração CSS, não um elemento HTML. Se um `url()` sobreviver a um defeito do filtro de §4.5, nada no HTML o denuncia | Requisição é `ResourceTypeImage` (ou `ResourceTypeStylesheet` para `@import`) e é negada |
| `@import url(https://…)` | Mesmo caso; folha de estilo remota que pode conter mais `url()` | `ResourceTypeStylesheet` negado por tipo |
| `<picture>` / `<source srcset>` / `<img srcset>` | Se a allowlist de atributos regredir e `srcset` passar, há N URLs por elemento e a reescrita de `src` não as cobre | Toda variante é uma requisição de imagem, avaliada individualmente |
| Beacon que não é `<img>` | `<a ping>`, `sendBeacon`, `<link rel=preload>`, `<video poster>`, `<track>`, `favicon`, CSP report, `<iframe>` de 1×1 | Cada um tem um `ResourceType` próprio, e **todos** são negados |
| Fonte remota | `@font-face` com `src: url()` dentro de um `<style>` que não sobrevive à allowlist — mas sobreviveria se a allowlist mudasse | `ResourceTypeFontResource` negado |
| Recurso criado por JavaScript | JavaScript está desabilitado, mas se essa configuração regredir, o HTML estático não descreve a requisição | `ResourceTypeXhr`, `Script`, `Worker`, `ServiceWorker` negados |

Formulação normativa: **a sanitização protege contra execução; o interceptor protege contra vazamento.** Nenhum dos dois é redundante, e o interceptor é o que sustenta `RNF-PRIV-01` mesmo com um defeito na camada de sanitização.

### 7.2 Precondição global

Antes da matriz, uma verificação que se aplica a **toda** requisição:

```python
first_party = info.firstPartyUrl()
if first_party.scheme() != "pymail" or first_party.host() != "message":
    record_and_block(info, reason="first_party_origin_nao_e_pymail")
    return
```

Nenhuma requisição cuja origem de primeira parte não seja o documento fictício `pymail://message/` é permitida, em nenhuma circunstância. Isso impede que uma página inesperada — página de erro do motor, documento residual, conteúdo carregado por um caminho não previsto — use a política do leitor.

Complementos obrigatórios:

- **Uma instância por perfil, e uma instância só.** `profile.setUrlRequestInterceptor(interceptor)` é chamado **antes** da criação da primeira `QWebEnginePage`. Um interceptor registrado depois não afeta páginas já criadas, e `setUrlRequestInterceptor` **substitui** o anterior — se dois `ReaderPane` registrarem interceptores no mesmo perfil, um substitui o outro silenciosamente. A verificação é por teste (§8.6).
- **`interceptRequest` roda na thread de I/O do motor.** O `RequestRecorder` precisa ser seguro entre threads (lock, ou fila `queue.Queue` consumida na thread da GUI). A política consultada é um objeto imutável trocado atomicamente (§7.4).
- **`info.block(True)` é terminal.** Não há caminho que chame `block(False)` depois.

### 7.3 Matriz de decisão completa

`AUTORIZADO` = existe linha em `sender_image_policy` para `(account_id, from_addr)` da mensagem **atualmente em exibição**, conforme §6.4.

| `ResourceType` | Veredito | Condição | Razão |
|---|---|---|---|
| `ResourceTypeMainFrame` | Permitido **apenas** para `pymail://message/` | Esquema `pymail` e host `message` | É o próprio documento. Qualquer `http(s)` aqui seria navegação para fora do leitor (`RF-RD-07`, T-13) |
| `ResourceTypeSubFrame` | **Bloqueado sempre** | — | `<iframe>`/`<frame>`: subdocumento com origem própria, vetor de beacon, de *clickjacking* e de contorno de origem |
| `ResourceTypeStylesheet` | **Bloqueado sempre** | — | CSS remoto: `@import`, `url()`, fonte remota e exfiltração por seletor. Não existe folha de estilo legítima em mensagem recebida |
| `ResourceTypeScript` | **Bloqueado sempre** | — | Execução de código. `JavascriptEnabled=False` já o impede; o interceptor é a segunda barreira |
| `ResourceTypeImage` | **Condicional** | `AUTORIZADO` **e** esquema `https` | Único recurso externo que o usuário pode liberar. Esquema `http` é negado mesmo sob autorização: o conteúdo da mensagem não é motivo para tráfego em texto claro (§14, item 6) |
| `ResourceTypeFontResource` | **Bloqueado sempre** | — | Fonte remota: beacon por requisição, revela leitura, e vetor de impressão digital |
| `ResourceTypeXhr` | **Bloqueado sempre** | — | `fetch`/XHR/`sendBeacon`: canal arbitrário e exfiltração de dados lidos do documento |
| `ResourceTypeMedia` | **Bloqueado sempre** | — | `<video>`/`<audio>`: requisição por reprodução e por `poster`, com temporização controlada pelo remetente |
| `ResourceTypeFavicon` | **Bloqueado sempre** | — | Requisição automática que o conteúdo não precisaria disparar; vetor de beacon trivial |
| `ResourceTypePing` | **Bloqueado sempre** | — | `<a ping>`: é literalmente um beacon de clique, e o tipo existe para ser negado |
| `ResourceTypeObject` | **Bloqueado sempre** | — | `<object>`/`<embed>`/plugin: conteúdo ativo |
| `ResourceTypePluginResource` | **Bloqueado sempre** | — | Recurso carregado por plugin |
| `ResourceTypeWorker` | **Bloqueado sempre** | — | Web Worker: execução fora da thread do documento |
| `ResourceTypeSharedWorker` | **Bloqueado sempre** | — | Idem, com estado compartilhado entre documentos do mesmo perfil |
| `ResourceTypeServiceWorker` | **Bloqueado sempre** | — | Interceptação persistente de rede; incompatível com um leitor que não deve ter estado |
| `ResourceTypePrefetch` | **Bloqueado sempre** | — | Pré-carregamento: dispara requisições "especulativas" sem interação |
| `ResourceTypeCspReport` | **Bloqueado sempre** | — | Relatório de violação de CSP é uma requisição de saída com origem no conteúdo; um remetente poderia induzir violações de propósito para usar o relatório como canal |
| `ResourceTypeSubResource` | **Bloqueado sempre** | — | Categoria genérica; allowlist significa negar o que não se sabe classificar |
| `ResourceTypeNavigationPreloadMainFrame` | **Bloqueado sempre** | — | Pré-carregamento de navegação |
| `ResourceTypeNavigationPreloadSubFrame` | **Bloqueado sempre** | — | Idem |
| `ResourceTypeUnknown` | **Bloqueado sempre** | — | **Falha fechada.** Um tipo que a versão do Qt não conhece é negado, nunca permitido por omissão. É a linha que garante que uma enumeração incompleta da matriz não vire uma brecha |
| Ausência no `ResourceType` (`None`) | **Bloqueado sempre** | — | Idem |

Regra de implementação: a matriz é escrita como **allowlist explícita** — o código testa a condição de permissão e nega tudo o mais, sem `else` que permita. A matriz acima é a documentação da decisão, não uma `switch` com caso padrão permissivo.

### 7.4 Autorização e ciclo de vida do estado

O interceptor não decide "o usuário autoriza imagens?" — ele decide com base em um objeto imutável publicado pelo leitor:

```python
@dataclass(frozen=True, slots=True)
class RenderPolicy:
    allow_images: bool
    account_id: int | None
    from_addr: str | None
    document_token: int          # incrementado a cada setHtml
```

- O leitor publica um novo `RenderPolicy` **antes** de cada `setHtml`, com `allow_images` já calculado a partir de `sender_image_policy`. A referência é trocada por atribuição única (atômica em CPython), sem lock.
- Ao trocar de mensagem, o leitor publica **primeiro** `RenderPolicy(allow_images=False, ...)` e só depois chama `setHtml`. Requisições residuais do documento anterior são portanto negadas.
- **Brecha residual (corrida de documento):** o motor pode ter requisições do documento anterior ainda em voo quando a política muda. Se o usuário acabou de autorizar o remetente da mensagem nova, e existirem requisições pendentes da mensagem anterior, elas seriam avaliadas contra a política nova. O pior caso é uma imagem da mensagem anterior ser buscada depois de o usuário autorizar a mensagem nova — ambas do mesmo remetente na prática, porque autorizar B enquanto A está pendente exige troca de mensagem exatamente nesse instante. Mitigação disponível e **não adotada** por custo: criar uma `QWebEnginePage` nova por mensagem, o que adicionaria centenas de milissegundos a cada abertura e conflitaria com `RNF-PERF-03` (150 ms em cache). A direção perigosa — liberar imagem de remetente não autorizado — exigiria que a política nova autorizasse e a antiga não, no mesmo instante da troca. Aceito e declarado.
- O `document_token` é registrado com cada requisição, para que os testes possam atribuir cada decisão ao documento correto.

### 7.5 Registro de tentativas e verificação de `CA-RNF-PRIV-01-1`

`RequestRecorder` registra **toda** tentativa, permitida e bloqueada. É esse registro que torna `CA-RNF-PRIV-01-1` verificável — sem ele, "zero requisições" não seria uma afirmação testável, apenas uma esperança.

```python
@dataclass(frozen=True, slots=True)
class RequestRecord:
    timestamp: float
    document_token: int
    resource_type: str        # nome do enum do Qt
    scheme: str
    host: str
    path: str                 # sem query string
    decision: str             # "allowed" | "blocked"
    reason: str               # "not_authorized" | "resource_type_blocked"
                              # | "scheme_not_https" | "first_party_foreign"
```

| Regra | Detalhe |
|---|---|
| O que é registrado na memória | Esquema, host, caminho, tipo de recurso, decisão, motivo, instante, `document_token`. **Sem *query string*** — ela contém o identificador de rastreamento e conteúdo derivado da mensagem |
| Onde vive | *Ring buffer* em memória, no `RequestRecorder`, acessível ao leitor e aos testes. Não é persistido por padrão. `document_token` permite ao leitor exibir *"3 imagens bloqueadas por não usarem HTTPS"* e *"12 imagens bloqueadas (remetente não autorizado)"* |
| O que vai para o log | Apenas agregados por documento: contagem de permitidas e de bloqueadas por `ResourceType`, com host e esquema dos bloqueios. Nunca a URL completa, nunca o caminho completo em produção |
| Modo de diagnóstico | Com `config.toml: diagnostics.record_requests = true`, o `RequestRecord` completo é gravado em arquivo, **passando pelo `RedactionFilter`**, que remove a *query string* de todo URL. O modo é explícito e a interface avisa que ele registra hosts acessados |
| Como `CA-RNF-PRIV-01-1` é verificado | O teste renderiza o corpus de §13.2 e afirma `recorder.count(decision="allowed") == 0` **e** `recorder.count(decision="blocked") > 0` — a segunda asserção é o controle positivo: prova que o interceptor foi efetivamente consultado e que o corpus contém recursos que teriam sido buscados. Um corpus que produzisse zero tentativas de qualquer tipo não provaria nada |
| Como `CA-RF-RD-03-1` é verificado | Mensagem com 20 imagens remotas: `allowed == 0`, `blocked == 20`, todas com `resource_type == "ResourceTypeImage"` e `reason == "not_authorized"` |
| Como `CA-RF-RD-06-1` é verificado | Requisições de tipos não-imagem a host externo: `allowed == 0`, cada uma com `reason == "resource_type_blocked"` |
| Limite | O registro cobre apenas o que passa pelo motor de renderização. Não vê sockets abertos pelo Python; por isso a auditoria de §11.3 instrumenta a camada de socket |

---

## 8. Superfície do motor de renderização

### 8.1 Perfil `QWebEngineProfile` — definições obrigatórias de `02-arquitetura.md` §5.5

| Definição | Código | Ataque ou vazamento que impede |
|---|---|---|
| **Perfil off-the-record** | `QWebEngineProfile(self)`, criado sem nome de armazenamento | Um perfil com nome grava cookies, cache, `LocalStorage` e histórico em disco, em um diretório compartilhado entre execuções. Isso permitiria a um remetente correlacionar mensagens lidas em dias diferentes, e deixaria artefatos do conteúdo das mensagens fora do banco — fora, portanto, de toda política de retenção, despejo (RF-MSG-06) e remoção de conta (RF-ACC-05). Off-the-record, o perfil vive na memória do processo e desaparece com ele |
| **`NoPersistentCookies`** | `profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)` | Cookie persistente é o mecanismo de rastreamento entre mensagens mais antigo e mais eficaz. Também impede que um cookie de sessão de um remetente seja reapresentado em outra mensagem. Cobre T-16 |
| **`NoCache`** | `profile.setHttpCacheType(QWebEngineProfile.NoCache)` | O cache HTTP permite duas coisas indesejadas: (a) confirmar que um recurso já foi buscado (a resposta vem do cache, sem rede — o servidor já sabe que houve a busca anteriormente); (b) deixar cópias de imagens em disco, fora de qualquer política de retenção. Custo declarado: reabrir a mesma mensagem autorizada rebusca as imagens. Aceito |
| **Interceptor registrado no perfil** | `profile.setUrlRequestInterceptor(PrivacyInterceptor(...))` | Sem ele, nada do §7 acontece. Precisa ser registrado antes da primeira página (§7.2) |
| **`User-Agent` genérico** | `profile.setHttpUserAgent(GENERIC_USER_AGENT)` | Impede que o remetente identifique o aplicativo e a versão — o que permitiria servir conteúdo explorando uma vulnerabilidade conhecida daquela versão, ou negar conteúdo para clientes "incompatíveis". Cobre parte de T-11 |
| **`baseUrl` fictícia** | `view.setHtml(sanitized_html, QUrl("pymail://message/"))` | Toda URL relativa no conteúdo aponta para uma origem que não existe e falha, em vez de resolver contra o host do remetente. Sem isso, uma `<img src="/px.gif">` relativa se resolveria contra… o quê? Um `baseUrl` `https://exemplo.com/` a resolveria para um host remoto real. Também faz o documento ter origem `pymail://`, sem cookies, sem `LocalStorage` e sem credenciais associadas. Cobre T-15 e a inversão 3 de §4.1.1 |

### 8.2 `QWebEngineSettings` — definições obrigatórias

| Definição | Código | Ataque ou vazamento que impede |
|---|---|---|
| **JavaScript desabilitado** | `setAttribute(JavascriptEnabled, False)` | Elimina a classe inteira de execução de código a partir de conteúdo: T-01. É *permanente* — não existe configuração de usuário, nem caminho de código que a habilite. Combinado com `script-src 'none'` e com o `nh3` |
| **Sem armazenamento local** | `setAttribute(LocalStorageEnabled, False)` | `LocalStorage`/`sessionStorage`/IndexedDB persistem identificadores que sobrevivem à mensagem. Com JS desabilitado já seriam inalcançáveis; a definição existe contra regressão de configuração e contra conteúdo que consiga criar um contexto de script |
| **Sem plugins** | `setAttribute(PluginsEnabled, False)` | Plugins (inclusive o visualizador de PDF embutido) são código nativo com superfície de parser própria, executado dentro do processo do renderizador sobre conteúdo controlado pelo remetente |
| **`AutoLoadImages=False`** | `setAttribute(AutoLoadImages, False)` | Bloqueio no nível do motor, anterior ao interceptor: mesmo que o interceptor falhe ou não seja registrado, o motor não busca imagens automaticamente. É a segunda barreira de T-02, explicitamente exigida por `RF-RD-03` |
| **Sem acesso a URL remota a partir de conteúdo local** | `setAttribute(LocalContentCanAccessRemoteUrls, False)` | Se algum caminho futuro carregar conteúdo como `file://` (pré-visualização local, página de erro, documento de ajuda), um script ou recurso nele não alcançaria a rede. Defesa em profundidade: hoje o único `baseUrl` é `pymail://`, para o qual a definição tem efeito limitado |
| **Sem conteúdo inseguro** | `setAttribute(AllowRunningInsecureContent, False)` | Impede que uma origem segura carregue subrecurso em texto claro. **Nota honesta:** com `baseUrl` `pymail://`, o motor não classifica o documento como origem segura, e a definição tem efeito limitado hoje. Ela é mantida porque (a) o interceptor é quem bloqueia de fato, e (b) se a `baseUrl` virar um esquema registrado como seguro, esta passa a ser a barreira relevante. A aplicabilidade deve ser **medida** por teste, não presumida |

### 8.3 Definições adicionais recomendadas

Estas **não** constam da lista de §5.5 de `02-arquitetura.md` e são acréscimo desta spec, por cobrirem vetores concretos:

| Definição | Valor | Vetor coberto |
|---|---|---|
| `HyperlinkAuditingEnabled` | `False` | `<a ping>` dispara requisição de rede no clique. O interceptor já nega `ResourceTypePing`, mas a definição fecha no motor |
| `DnsPrefetchEnabled` | `False` | **Crítico e não coberto pelo interceptor.** O pré-carregamento de DNS resolve nomes de host do documento **sem emitir requisição HTTP** e portanto sem passar pelo `interceptRequest`. Seria uma consulta DNS ao resolvedor do usuário, revelando ao resolvedor quais hosts um remetente escolheu. Ver §11 |
| `UnknownUrlSchemePolicy` | `DisallowUnknownUrlSchemes` | Impede que conteúdo acione manipuladores externos registrados no sistema para esquemas desconhecidos |
| `JavascriptCanOpenWindows` | `False` | Complementar a JS desabilitado |
| `JavascriptCanAccessClipboard`, `JavascriptCanPaste` | `False` | Idem; impede leitura ou escrita da área de transferência |
| `ScreenCaptureEnabled` | `False` | Captura de tela a partir do conteúdo |
| `WebGLEnabled` | `False` | Superfície de impressão digital conhecida; nenhuma utilidade em leitura de e-mail |
| `PdfViewerEnabled` | `False` | Remove o visualizador de PDF embutido (código nativo sobre conteúdo hostil). Reforça §9.6 |
| `NavigateOnDropEnabled` | `False` | Soltar um arquivo sobre a view não deve navegar para ele |
| `FullScreenSupportEnabled` | `False` | Conteúdo não deve poder assumir a tela |
| `PlaybackRequiresUserGesture` | `True` | Redundante com `ResourceTypeMedia` negado; mantido por consistência |
| `LocalContentCanAccessFileUrls` | `False` | Conteúdo local não alcança outros arquivos locais |
| `ErrorPageEnabled` | `True` | Não é segurança: uma página de erro explicativa é melhor que área em branco (RF-UI-07). A página de erro é gerada pelo motor e não pelo conteúdo |

### 8.4 Nenhuma herança óbvia entre perfis — a armadilha

`QWebEngineProfile` e `QWebEngineSettings` não se comportam como configuração global, e a intuição engana:

| Fato | Consequência |
|---|---|
| `QWebEngineProfile.defaultProfile()` é um perfil **persistente**, com diretório de armazenamento em disco | Uma `QWebEngineView` criada sem perfil explícito, ou uma `QWebEnginePage` construída com o perfil padrão, grava cookies e cache em disco **sem nenhum aviso**. Toda a política de §8.1 é silenciosamente ignorada |
| `QWebEngineSettings` é **por página**; os valores padrão vêm das `settings()` do perfil | Uma página criada antes da configuração, ou com outro perfil, tem os padrões do Qt — JavaScript **habilitado**, imagens automáticas **habilitadas** |
| Um perfil novo **não** herda as definições de outro perfil | Se um segundo `ReaderPane` criar seu próprio perfil e o código de configuração for refatorado para um único ponto de inicialização, o novo perfil pode ficar sem as definições. Não há herança, não há erro, não há aviso: apenas um perfil com configuração padrão |
| `setUrlRequestInterceptor` aceita um interceptor por perfil e o **substitui** | Dois `ReaderPane` no mesmo perfil resultam em um interceptor só, o último registrado — e o registro é silencioso |
| `setPersistentCookiesPolicy`, `setHttpCacheType` e `setHttpUserAgent` são por perfil | Idem: precisam ser reaplicados em todo perfil criado |
| Perfis criados em threads diferentes, ou após `QApplication` | Comportamento dependente de versão; ver o requisito de inicialização de §5.5 de `02-arquitetura.md` (`AA_ShareOpenGLContexts` e import de `QtWebEngineWidgets`) |

### 8.5 Verificação por teste

A configuração não é verificada por leitura de código, e sim por asserções sobre os objetos reais:

| Teste | Asserção |
|---|---|
| Perfil não é o padrão | `view.page().profile() is not QWebEngineProfile.defaultProfile()` |
| Perfil é off-the-record | `view.page().profile().isOffTheRecord() is True` |
| Política de cookies | `profile().persistentCookiesPolicy() == NoPersistentCookies` |
| Cache | `profile().httpCacheType() == NoCache` |
| User-Agent | `profile().httpUserAgent() == GENERIC_USER_AGENT` e que `GENERIC_USER_AGENT` não contém `"PyMail"`, `"PySide"` nem `"Qt"` |
| Interceptor presente | `profile().urlRequestInterceptor() is not None` e é uma instância de `PrivacyInterceptor` |
| Cada `WebAttribute` de §8.2 e §8.3 | Asserção parametrizada: para cada par `(atributo, valor esperado)`, `settings().testAttribute(atributo) == valor` |
| **Independência entre instâncias** | Criar dois `ReaderPane` em sequência e afirmar que **ambos** têm todas as definições esperadas. É este teste que falha se alguém assumir herança entre perfis (§8.4) |
| **Interceptação efetiva** | Carregar conteúdo que referencia recurso externo e afirmar `recorder.count("blocked") > 0`. Sem esta asserção, uma configuração "presente mas inerte" passaria |
| Ausência de disco | Após renderizar conteúdo autorizado, afirmar que nenhum arquivo novo apareceu nos diretórios `AppDataLocation` e `AppLocalDataLocation` além dos esperados (banco, config, logs) |
| Aplicabilidade de `AllowRunningInsecureContent` | Teste que **mede** se o motor aplica a definição com `baseUrl` `pymail://`, em vez de presumir. Enquanto o resultado não for conhecido, a definição é mantida por precaução e o interceptor é a barreira declarada (§8.2) |

---

## 9. Manipulação de anexos

### 9.1 Sanitização do nome de arquivo

`RNF-SEC-04` e `CA-RNF-SEC-04-1`. A função `sanitize_attachment_filename(raw_name: str) -> str` aplica, nesta ordem:

| # | Operação | Razão |
|---|---|---|
| 1 | Decodificar o nome conforme MIME: `filename*` (RFC 2231) e `filename` com `=?charset?B/Q?...?=` (RFC 2047), com queda para a forma literal | **A decodificação vem antes de tudo.** O ataque real está no valor **decodificado**: `%2e%2e%2f` ou uma codificação base64 que decodifica para `../../evil.sh`. Sanitizar a forma codificada não protege nada |
| 2 | Aplicar `NFKC` | Normaliza formas equivalentes — em especial caracteres de largura total (`．．／`) que alguns sistemas de arquivos normalizam para `.` e `/` |
| 3 | Remover bytes `NUL` e **todo o conteúdo a partir do primeiro `NUL`** | Um `NUL` no meio do nome trunca a cadeia em chamadas de sistema que usam C-string, produzindo um nome no disco diferente do nome validado |
| 4 | Remover caracteres de controle C0 (`\x00`–`\x1f`) e `DEL` (`\x7f`) | Quebra de linha no nome polui logs e interfaces; alguns sistemas de arquivos aceitam `\n` e produzem nomes que enganam a exibição |
| 5 | Substituir por `_` os caracteres proibidos no Windows: `< > : " / \ | ? *` | Proibidos no NTFS. `/` e `\` são também separadores em POSIX — removê-los aqui elimina a travessia |
| 6 | **Eliminar todo componente de caminho**: dividir por `/` e `\` e manter **apenas o último componente não vazio** | Cobre `../../evil.sh`, `..\..\win.ini`, `/etc/passwd`, `C:\Windows\System32\x.dll` e `\\servidor\share\f` |
| 7 | Tratar `..` e `.` como vazios | Se o último componente for `..` ou `.`, o resultado é vazio e cai na regra 10 |
| 8 | Remover pontos e espaços no início e no fim | Windows não cria arquivos terminados em `.` ou espaço e os trunca silenciosamente, produzindo divergência entre o nome validado e o nome gravado |
| 9 | Nomes reservados do Windows: `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, além de `CONIN$`, `CONOUT$`, insensível a maiúsculas, **com ou sem extensão** (`CON.txt`, `LPT1.tar.gz`) → prefixar com `_` | O sistema operacional interpreta esses nomes como dispositivos, não como arquivos; a gravação pode falhar ou, pior, escrever em um dispositivo |
| 10 | Se o resultado estiver vazio: `attachment` | Garante um nome válido |
| 11 | Truncar para 150 caracteres, **preservando a extensão** quando ela tiver até 10 caracteres: `base[:150 - len(ext)] + ext` | `CA-RNF-SEC-04-1` cobre 300 caracteres. O truncamento é por caractere, e o limite de 150 fica abaixo dos 255 bytes típicos mesmo com caracteres multibyte |
| 12 | Unicidade: se já existe arquivo com o nome na pasta de destino, acrescentar ` (n)` antes da extensão, com `n` de 1 a 999 | Impede sobrescrita silenciosa de um anexo anterior ou de um arquivo que o usuário já tinha ali |
| 13 | Gravar com criação **exclusiva** (`os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)`) e, em caso de `FileExistsError`, voltar ao passo 12 | A verificação de existência do passo 12 e a gravação não são atômicas; `O_EXCL` fecha a janela entre as duas |

Casos de `CA-RNF-SEC-04-1`, com resultado esperado:

| Nome de entrada | Resultado |
|---|---|
| `../../evil.sh` | `evil.sh`, gravado dentro da pasta de destino |
| `..\..\win.ini` | `win.ini`, dentro da pasta de destino |
| `CON` | `_CON` |
| `NUL.txt` | `_NUL.txt` |
| `arquivo\x00.exe` | `arquivo.exe` (nada após o `NUL`) |
| `nome com 300 caracteres` | truncado a 150 caracteres, extensão preservada |
| `/etc/passwd` | `passwd` |
| `foo/../../../bar.pdf` | `bar.pdf` |
| `relatório.pdf` (já existente) | `relatório (1).pdf` |
| `\u202eexe.gpj` (inversão de escrita RTL) | caractere de controle de formatação removido → `exe.gpj` |

O nome sanitizado é o que aparece na interface e o que é gravado. O nome original é preservado em memória apenas para exibição opcional ("nome original: …"), escapado e nunca usado como caminho.

### 9.2 Diretório de destino e contenção de caminho

| Regra | Detalhe |
|---|---|
| Padrão | `QStandardPaths.AppDataLocation/attachments`, criado com `mode=0o700` |
| Configurável | `RF-SET-02`/`RF-SET-01` permitem escolher outra pasta. A pasta escolhida é criada e verificada no momento da escolha |
| Verificação de contenção | Após montar o caminho final: `os.path.commonpath([os.path.realpath(destino), os.path.realpath(pasta)]) == os.path.realpath(pasta)`. A verificação usa `realpath`, resolvendo links simbólicos, e é **obrigatória**, independentemente da sanitização do nome — duas barreiras, porque a sanitização é uma função e a contenção é um invariante |
| Recusa de link simbólico | Se o caminho final for um link simbólico, a gravação é recusada. Em POSIX, `O_NOFOLLOW`; no Windows, verificação por `os.path.islink` antes da criação com `O_EXCL` |
| Permissão | Arquivo `0o600` (ver §10.1). Se a pasta escolhida pelo usuário tiver permissão mais permissiva, o aplicativo **avisa** e oferece corrigir, mas não altera a permissão de uma pasta do usuário sem consentimento |
| **Brecha residual (TOCTOU)** | Entre a verificação de contenção e a gravação existe uma janela em que um atacante local poderia trocar o diretório por um link. Fechá-la completamente exige `openat2`/`RESOLVE_BENEATH` (Linux) ou `CreateFile` com `FILE_FLAG_OPEN_REPARSE_POINT` (Windows), com código específico de plataforma que `RNF-COMP-02` desencoraja. Aceito porque um atacante local com permissão de escrita na pasta de anexos já tem os privilégios do usuário, e T-07/§1.3 já o colocam fora do modelo de ameaças |
| Nunca escrever fora | A gravação sempre usa o caminho derivado pelo aplicativo. O nome vindo do remetente nunca é concatenado a um caminho sem passar por §9.1 e §9.2 |
| Espaço em disco | Se a gravação falhar por espaço, a mensagem de erro é explícita e o anexo permanece marcado como `meta` em `attachments.cache_state` — nunca fica "meio gravado" |

### 9.3 Proibição de abertura automática

- Nenhum anexo é aberto, executado, pré-visualizado ou enviado ao sistema operacional sem ação explícita do usuário. `RNF-SEC-03` exige "sem abertura automática de anexos".
- Não existe `QDesktopServices.openUrl` em nenhum caminho automático. A única chamada no código está no manipulador do clique no botão "Abrir", e é verificável por teste que assere a contagem de chamadas zero em um fluxo de recebimento.
- O aplicativo **não** define a permissão de execução em nenhum arquivo gravado (`chmod +x` inexistente). `O_CREAT` com `0o600` já garante isso em POSIX.
- O aplicativo não passa o `mime_type` do remetente ao sistema operacional. O tipo usado para decidir o aviso é derivado da **extensão sanitizada**, e a decisão de abrir é do sistema operacional com seus próprios manipuladores.
- `mime_type` vindo da mensagem é tratado como dado não confiável em todos os pontos: é exibido na interface (com escape de texto, e como widget Qt que escapa por natureza) e nunca é usado para escolher um manipulador.
- Consequência declarada: o usuário que quiser ler um anexo terá de abri-lo fora do aplicativo, com o risco que isso implica e sob a responsabilidade do manipulador do SO. Ver §9.6.

### 9.4 Tipos que exigem aviso reforçado

Lista mantida em código (`DANGEROUS_EXTENSIONS: frozenset[str]`), comparada pela extensão sanitizada em minúsculas. Aviso **modal**, com o tipo nomeado e explicação, sem botão de abrir como ação padrão (o foco inicial é "Cancelar"):

**Executáveis e scripts:** `exe`, `com`, `bat`, `cmd`, `ps1`, `psm1`, `vbs`, `vbe`, `js`, `jse`, `wsf`, `wsh`, `ws`, `scr`, `pif`, `cpl`, `hta`, `msi`, `msp`, `mst`, `jar`, `class`, `lnk`, `url`, `reg`, `inf`, `scf`, `sct`, `shb`, `shs`, `sys`, `vxd`, `dll`, `ocx`, `xll`, `gadget`, `job`, `msc`, `diagcab`, `appref-ms`, `application`, `app`, `action`, `command`, `workflow`, `terminal`, `desktop`, `apk`, `dmg`, `pkg`, `deb`, `rpm`, `AppImage`, `iso`, `img`, `vhd`, `vmdk`, `ace`.

**Documentos com macro ou conteúdo ativo:** `docm`, `xlsm`, `pptm`, `dotm`, `xltm`, `potm`, `xlam`, `ppam`, `sldm`, `xlsb`, `doc`, `xls`, `ppt` (formato antigo, com macros possíveis), `pdf` (código no leitor e capacidade de abrir URLs), `rtf`, `chm`, `hlp`, `svg`, `svgz`, `mht`, `mhtml`, `eml`, `msg`.

**Dupla extensão:** qualquer nome com **duas ou mais extensões** em que a última esteja na lista acima (`fatura.pdf.exe`, `foto.jpg.scr`) dispara o aviso mesmo que o nome intermediário pareça inofensivo — e a interface exibe o nome completo, com a extensão final destacada.

Texto do aviso, obrigatório: *"`<nome sanitizado>` é um arquivo executável. Abri-lo pode executar código na sua máquina. O PyMail Client não verifica o conteúdo de anexos."* — a última frase é deliberada: ela descreve o limite do produto em vez de sugerir uma proteção que não existe.

Nada é inspecionado além da extensão: não há verificação de assinatura, de *hash* contra lista de malware (seria telemetria, `RNF-PRIV-02`), nem de tipo real por *magic bytes*. Um `fatura.pdf` que seja um executável dispara apenas o aviso de PDF.

### 9.5 Anexos e o pipeline de renderização

- Metadados de anexo (`filename`, `mime_type`, `size_bytes`) são gravados em `attachments` (`RF-MSG-07`). O nome gravado é o sanitizado.
- `content_id` é preservado para permitir a associação com `data-pymail-cid` no HTML, mas isso serve apenas para o placeholder textual de §6.3 — o conteúdo do anexo **não** é injetado no documento.
- Se, no futuro, um nome de anexo for exibido **dentro** do `QWebEngineView`, ele deverá passar pelo pipeline de sanitização como texto (nunca concatenado como HTML). Hoje a exibição é por widgets Qt, que escapam por natureza. A regra fica registrada porque é exatamente o tipo de decisão que se perde depois.

### 9.6 Por que o conteúdo do anexo nunca é renderizado dentro do aplicativo

| Razão | Detalhe |
|---|---|
| Um visualizador é um novo parser sobre entrada hostil | Renderizar um PDF, uma imagem, um documento do Office ou um SVG dentro do processo do aplicativo significa executar código de análise sobre bytes escolhidos por um terceiro. Essa é a superfície de ataque típica de clientes de e-mail, e é onde as vulnerabilidades reais aparecem |
| O motor de renderização já foi escolhido e medido | `ADR-003` aceitou 150–200 MB de instalador por um motor de renderização. Adicionar um segundo caminho de renderização (visualizador de PDF, de imagem, de documento) reintroduziria dois pipelines e duas superfícies — o mesmo argumento que ADR-003 usou para rejeitar o modo duplo com `QTextBrowser` |
| Isolamento de processo | Um anexo aberto no visualizador externo do sistema operacional roda em outro processo, com as mitigações que esse processo tenha. Dentro do nosso, compartilharia memória com o núcleo do aplicativo — inclusive com a credencial em memória (§2.2) |
| Não há requisito para pré-visualização | Nenhum `RF` pede pré-visualização de anexo. `RF-MSG-07` pede download sob demanda e, na fase 1, apenas metadados em cache |
| Custo declarado | Conveniência: o usuário precisa abrir o arquivo em outro aplicativo para ver o conteúdo. É uma perda real, e a alternativa — abrir dentro do cliente — transfere a superfície de ataque de um leitor de e-mail para todos os formatos existentes |

---

## 10. Dados locais em repouso

### 10.1 Permissões por sistema operacional

Conforme `02-arquitetura.md` §8.1 e `RNF-SEC-05`.

| Conteúdo | Caminho | POSIX (Linux/macOS) | Windows |
|---|---|---|---|
| Diretório de dados | `QStandardPaths.AppDataLocation` | `0700` (criado com esse modo; `umask` do processo ajustado para `077` durante a criação) | ACL herdada de `%LOCALAPPDATA%`: concedida ao usuário, a `SYSTEM` e a `Administradores` |
| Banco `pymail.db`, `-wal`, `-shm` | idem | `0600`, **incluindo `-wal` e `-shm`** — os arquivos auxiliares do WAL são criados pelo SQLite e herdam o `umask`; são ajustados explicitamente logo após a criação | ACL herdada; sem modo POSIX |
| Configuração `config.toml` | `QStandardPaths.AppConfigLocation` | `0600` na prática, embora §8.1 registre `0644`. **Decisão desta spec: `0600`**, porque `config.toml` contém hosts, usuários e a lista de remetentes com imagens autorizadas — metadados de comunicação, que §1.1 classifica como ativo. Divergência registrada em §14, item 20 | ACL herdada |
| Logs | `AppDataLocation/logs` | Diretório `0700`, arquivos `0600` | ACL herdada |
| Anexos baixados | Pasta escolhida pelo usuário; padrão `AppDataLocation/attachments` | Diretório `0700`, arquivos `0600` | ACL herdada |
| Credenciais | keyring do SO | — | — |

**Honestidade sobre o Windows.** O Windows não tem modos POSIX: `os.chmod` sobre arquivos NTFS altera apenas o bit de somente-leitura e não restringe o acesso. A proteção efetiva é a ACL do perfil do usuário, herdada de `%LOCALAPPDATA%`, que concede acesso ao usuário, a `SYSTEM` e a `Administradores`. Isso significa que um processo executado como o mesmo usuário — inclusive malware sem elevação — **lê o banco**. Não há como restringir mais sem cifragem, e é exatamente o cenário de §10.3. `RNF-SEC-05` diz "onde o sistema operacional permitir"; no Windows, o sistema operacional não permite muito, e a mitigação real é BitLocker (§10.4).

### 10.2 O que é protegido de fato

| Proteção | Efetiva contra |
|---|---|
| Permissões `0700`/`0600` em Linux/macOS | Outros usuários sem privilégio na mesma máquina. É a diferença entre "qualquer um com uma conta na máquina lê seu correio" e "só quem tem a sua conta" |
| Ausência de senha em banco, config e logs (`RNF-SEC-01`) | Qualquer leitura de arquivo: a credencial não está lá. Verificável por `CA-RNF-SEC-01-1`, que varre banco, config e logs |
| Ausência de HTML cru no banco (`03-modelo-de-dados.md` §6.3) | Um leitor do banco não obtém HTML não sanitizado — inclusive um processo local |
| Perfil off-the-record (§8.1) | Artefatos do motor de renderização em disco: sem cache HTTP, sem cookies, sem histórico |
| Retenção limitada (`RF-MSG-06`, despejo LRU) | Reduz a janela de exposição: corpos antigos são descartados. O que não está no disco não pode ser lido |

### 10.3 O que **não** é protegido — a brecha, declarada

**O banco não é cifrado.** `01-requisitos.md` §7 registra a cifragem do banco local em repouso como explicitamente fora de escopo. A consequência, dita sem rodeios:

> Qualquer processo executado como o usuário, ou como administrador, lê todo o conteúdo de mensagens em cache: **corpo, assunto, remetentes, destinatários, datas, nomes de anexo, o índice FTS5 completo** (que armazena sua própria cópia do texto indexado, `03-modelo-de-dados.md` §6.2) e a lista de remetentes com imagens autorizadas. Não é necessário nenhum exploit: basta abrir o arquivo.

O que **é** protegido mesmo assim: a credencial permanece no keyring, então o atacante que copia o banco não obtém acesso ao servidor de correio. Ele obtém o histórico. E se ele estiver na mesma sessão, o keyring desbloqueado também cede.

### 10.4 Por que cifrar o cache foi considerado fora de escopo

| Argumento | Detalhe |
|---|---|
| A chave teria de estar disponível no mesmo contexto | Qualquer chave que o aplicativo consiga obter sem interação do usuário está, por definição, disponível para qualquer processo rodando como o usuário. Isso inclui a chave guardada no keyring: se o cofre está desbloqueado para o aplicativo, está desbloqueado para quem lê a memória do aplicativo ou chama a mesma API do cofre. A cifragem protegeria apenas contra o cenário em que o arquivo é copiado **e** o cofre não é — uma cópia do diretório de dados para um backup, por exemplo |
| Quebraria `RNF-PERF-02` | Exigir uma senha mestra digitada no início do aplicativo para desbloquear o banco torna impossível "primeira janela utilizável em menos de 1,5 s". Seria uma regressão direta de um requisito de fase 1 |
| Custo de desempenho | Cifrar cada página tocada (SQLCipher ou equivalente) afeta exatamente as consultas mais frequentes: a página da lista (`idx_messages_folder_date`), a busca FTS5 (`CA-RF-SRCH-02-1` exige menos de 100 ms com 50 mil mensagens) e o despejo LRU. O FTS5 é particularmente penalizado: suas páginas são lidas em grande volume para consultas de prefixo |
| Dependência nativa adicional | SQLCipher não é `sqlite3` da stdlib. Adicionar uma biblioteca nativa criptográfica à cadeia de compilação e de empacotamento, para as três plataformas, em troca do ganho descrito acima |
| Conflito com `RNF-REL-02` | O cache é descartável e deve poder ser reconstruído do servidor sem intervenção manual. Perder a chave de um cache descartável é fricção sem benefício |
| Cifrar o banco não cifra tudo | `outbox.attachment_paths` e `attachments.cache_path` apontam para arquivos fora do banco, e os anexos baixados são conteúdo puro. Cifrar só o banco daria uma sensação de cobertura que não se sustenta |
| A solução correta é de outra camada | Cifragem de disco completa resolve o mesmo cenário — roubo ou descarte do equipamento, backup infiltrado — sem custo para o aplicativo, com cobertura de **todos** os arquivos, incluindo anexos e logs. Reinventá-la dentro do aplicativo seria pior em cobertura e em desempenho |

Nota adicional: mesmo com cifragem do banco, o **despejo de paginação** e o **despejo de núcleo** (`core dump`) podem conter páginas do banco e a credencial em memória. Não há requisito tratando disso — §14, item 18.

### 10.5 Mitigações disponíveis hoje

| Mitigação | Como o usuário a obtém |
|---|---|
| **Cifragem de disco completa** | BitLocker (Windows), FileVault (macOS), LUKS (Linux). É a mitigação recomendada e deve constar da tela de primeiro uso e da documentação, com uma frase direta: *"O PyMail Client não cifra o cache local. Ative a cifragem de disco do seu sistema para proteger o correio em cache."* |
| Permissões restritas | Aplicadas automaticamente (§10.1) |
| Retenção curta do cache | `RF-MSG-06`/`RF-MSG-11` `[F2]`: limite de cache configurável (padrão 500 MB) e, na fase 2, retenção por idade. Reduz a janela |
| Remoção de conta limpa tudo | `RF-ACC-05`/`CA-RF-ACC-05-1` apaga mensagens, corpos, índice, anexos e credencial da conta |
| Cache descartável | `RNF-REL-02`: o banco pode ser apagado a qualquer momento sem perda de dado do usuário (rascunhos e `outbox` são os únicos dados do usuário, e são exportáveis por `RF-SET-05`) |
| Ausência de segredo no banco | `RNF-SEC-01`/`CA-RNF-SEC-01-1`: copiar o banco não dá acesso à conta |
| **Ação de "apagar o cache local agora"** | **Não existe.** Não há requisito para isso — §14, item 11. Hoje o usuário consegue o mesmo efeito removendo a conta (o que também apaga a credencial) ou apagando o arquivo com o aplicativo fechado, e depois ressincronizando |

---

## 11. Privacidade de rede

### 11.1 Todas as conexões de saída possíveis

Esta tabela é exaustiva por decisão de projeto. Se a implementação estabelecer uma conexão que não esteja aqui, isso é um defeito e um teste deve falhar (§11.3).

| # | Destino | Quando | O que é transmitido | Justificativa |
|---|---|---|---|---|
| C-1 | Resolvedor DNS configurado no sistema | Antes de toda conexão C-2 a C-5 | O nome do host do servidor de correio da conta | Inerente a qualquer conexão por nome. **Vazamento de metadados reconhecido:** o resolvedor aprende com quais provedores de correio o usuário trabalha. Mitigar exigiria DoH/DoT — que seria, ela mesma, uma conexão a um terceiro — ou um resolvedor local. Não há requisito (§14, item 12) |
| C-2 | `incoming_host:incoming_port` de cada conta configurada | Sincronização, `IDLE`/`NOOP`, abertura de mensagem sob demanda | Comandos IMAP, credencial (dentro de TLS, ou em texto claro apenas se a exceção de §3.5 estiver ativa), e o conteúdo do correio daquela conta | `RF-MSG-01`…`RF-MSG-09`. É a razão de existir do aplicativo |
| C-3 | `outgoing_host:outgoing_port` de cada conta | Apenas ao enviar, e apenas após o vencimento da janela de undo | A mensagem completa e a credencial | `RF-SND-03`. **Nenhuma conexão SMTP é aberta antes do vencimento** (`CA-RF-SND-03-1`) — o servidor de saída não aprende que o usuário está escrevendo |
| C-4 | `incoming_host:incoming_port` de contas POP3 `[F2]` | Sincronização POP3 | Comandos POP3 e credencial | `RF-ACC-07` |
| C-5 | Hosts HTTPS referenciados em mensagens de remetentes **autorizados** | Ao renderizar uma mensagem cujo remetente tem autorização em `sender_image_policy`, e somente para `ResourceTypeImage` com esquema `https` | Um `GET` com o `User-Agent` genérico, sem cookie (perfil off-the-record), sem `Referer` (origem não-HTTP e `<meta name="referrer" content="no-referrer">`), sem cache | Consentimento explícito e revogável, `RF-RD-03`/`RNF-PRIV-04`. **O que o servidor do remetente aprende:** o endereço IP do usuário, o instante da leitura, o `User-Agent` (que revela a versão do Chromium embarcado) e o `Accept-Language` derivado do locale do sistema. Este é precisamente o dado que o pixel de rastreamento buscava — e é o preço aceito pelo consentimento (§6.4) |

### 11.2 O que **não** existe

Nenhuma outra conexão é estabelecida. Em particular:

| Categoria | Situação | Requisito |
|---|---|---|
| **Telemetria e métricas de uso** | Não existe. Nenhum contador, nenhum identificador de instalação, nenhum relatório de erro automático, nenhuma análise de uso | `RNF-PRIV-02` |
| **Verificação de atualização** | Não existe. O aplicativo nunca pergunta se há versão nova, nunca contata um servidor de distribuição. A atualização é feita pelo usuário, pelo canal de instalação | Decisão desta spec. Consequência declarada: **correções de segurança não chegam automaticamente** (ver §14, item 10) |
| **Qualquer domínio do próprio projeto** | Não existe. O PyMail Client não possui, e não contacta, domínio, CDN, servidor de telemetria ou endpoint de API próprio | `RNF-PRIV-02` |
| ***Crash reporting*** | Não existe. Nenhum Crashpad, nenhum envio de despejo. Despejos são locais, quando o sistema operacional os produz | Decisão desta spec |
| **Verificação de certificado por OCSP/CRL** | Não ocorre conexão adicional: o módulo `ssl` da stdlib valida contra os certificados-raiz locais e **não** consulta OCSP nem baixa CRL por padrão. *Nota honesta:* isso também significa que um certificado revogado é aceito — a checagem de revogação depende de o servidor enviar OCSP *staple*, e a stdlib não faz validação de *staple* na versão de referência. Registrado como limite conhecido, não como requisito cumprido | — |
| ***Safe browsing*** | Não existe. Nenhuma consulta de reputação de URL a serviço de terceiro, nem local | Consequência: T-04 permanece aberto (§1.4) |
| **Download de dicionários, fontes, listas de bloqueio** | Não existe. Tudo o que o aplicativo usa é embarcado | `RNF-PRIV-02` |
| **Sincronização entre máquinas** | Fora de escopo por `01-requisitos.md` §7 | — |
| **CDN, ícone remoto, `favicon`, conteúdo de ajuda remoto** | Não existe. Ajuda e ícones são recursos locais; `ResourceTypeFavicon` é negado (§7.3) | — |

### 11.3 Verificação por teste automatizado

Duas camadas, porque uma só não cobre o que a outra cobre:

**Camada 1 — o interceptor (dentro do motor de renderização).** O `RequestRecorder` de §7.5 registra todas as tentativas do motor. Verifica `CA-RNF-PRIV-01-1` e as demais condições de imagem. **Limite:** não vê sockets abertos pelo Python, nem consultas DNS.

**Camada 2 — a camada de socket (a aplicação inteira).** Uma *fixture* de `conftest.py` substitui `socket.socket.connect`, `socket.getaddrinfo` e `ssl.SSLContext.wrap_socket` por instrumentos que:

1. Registram `(endereço, porta, processo)` de toda tentativa de conexão e de toda resolução de nome.
2. **Falham o teste** se alguma tentativa não corresponder a um destino permitido da tabela §11.1, ou seja, a:
   - um host/porta configurado como conta no ambiente de teste (servidores falsos em `localhost`);
   - o host autorizado da mensagem de teste de imagens, quando o cenário concede autorização;
   - o resolvedor DNS, que é substituído por um duplo local e não conta como conexão permitida.

O teste de `RNF-PRIV-02` executa um fluxo completo e real — inicialização, cadastro de conta contra servidor falso, sincronização de cabeçalhos, abertura de três mensagens do corpus hostil, busca, composição, envio com undo, encerramento — e afirma que **o conjunto de destinos observados é exatamente** o conjunto esperado, sem nenhum destino extra. Não é uma asserção de ausência de "pymail.org": é uma asserção de igualdade de conjuntos, que falha tanto por destino proibido quanto por destino inesperado de origem desconhecida.

**Camada 3 — teste de deriva de configuração.** Um teste afirma o valor efetivo dos atributos `DnsPrefetchEnabled=False` e `HyperlinkAuditingEnabled=False` (§8.3), porque essas são exatamente as duas vias de rede que **não** passam pelo interceptor: uma consulta DNS de pré-carregamento e um `<a ping>` disparado no clique.

**Controle positivo obrigatório.** Cada um dos três testes inclui um cenário que **deve** produzir tráfego: uma mensagem de remetente autorizado com imagem `https` deve gerar exatamente uma requisição, registrada como `allowed`. Sem o controle positivo, um teste que não mede nada — por *fixture* mal instalada ou por o fluxo não ter executado — passaria como sucesso. Um teste de privacidade que não prova que o instrumento funciona não prova privacidade.

---

## 12. Fase 2 — OAuth2

`RF-ACC-06`: autenticação XOAUTH2 em Google e Microsoft, fluxo de navegador, PKCE, refresh de token no keyring e tratamento de revogação.

### 12.1 Armazenamento do token

Mesmo esquema de chaves de §2.1, com o sufixo `#oauth`:

| Item | Valor |
|---|---|
| `service` | `pymail-client` |
| `username` | `<email>#oauth` (`email` normalizado em minúsculas, §2.1) |
| Valor | JSON UTF-8, um único item, com as chaves `access_token`, `refresh_token`, `expires_at` (epoch UTC), `token_type`, `scope`, `client_id` |
| Gravação | Sempre o objeto completo, nunca campo a campo: um `refresh_token` rotacionado sem o `access_token` correspondente é estado inválido que só se descobre na próxima conexão |
| No banco | Nada. `accounts.auth_type = 'oauth2'` é a única marca, conforme `03-modelo-de-dados.md` §4. `RNF-SEC-01` proíbe token em banco |
| Rotação | Provedores que rotacionam `refresh_token` a cada uso: a gravação acontece **antes** de usar o `access_token` novo, para que uma queda entre as duas etapas não perca o refresh |
| Remoção | `keyring_delete_credential(email, oauth=True)`, na ordem de §2.3 |

### 12.2 PKCE

Obrigatório, mesmo para clientes que o provedor classifique como confidenciais, e mesmo com `redirect_uri` de *loopback*:

| Elemento | Definição |
|---|---|
| `code_verifier` | `secrets.token_urlsafe(64)`, resultando em 86 caracteres (dentro da faixa 43–128 do RFC 7636). Gerado por autorização, mantido **apenas em memória** |
| `code_challenge_method` | `S256`, sempre. `plain` é proibido |
| `code_challenge` | `base64url(sha256(code_verifier))` sem preenchimento `=` |
| `state` | `secrets.token_urlsafe(32)`, comparado com `secrets.compare_digest` (comparação em tempo constante) |
| `nonce` (OIDC) | `secrets.token_urlsafe(32)`, verificado no `id_token`, quando o escopo `openid` for solicitado |
| `redirect_uri` | `http://127.0.0.1:<porta_efêmera>/callback`. **Vinculado a `127.0.0.1`**, nunca `0.0.0.0`, nunca `localhost` (que pode resolver para `::1` ou para outro host em configurações exóticas) |
| Servidor de callback | `http.server` em thread dedicada, uma única requisição atendida, encerrado imediatamente. Requisições com caminho diferente de `/callback` ou sem `state` válido recebem 400 e o servidor continua aguardando |
| Tempo limite | 120 s. Ao expirar, o servidor fecha e a autorização falha com `AuthError` |
| Navegador | **O navegador padrão do sistema**, via `QDesktopServices.openUrl`. Nunca uma `QWebEngineView` embarcada: uma view embarcada receberia as credenciais do provedor dentro do processo do aplicativo, o que anula a separação entre o cliente de e-mail e o provedor de identidade |
| `client_secret` | Não existe. Cliente público, com PKCE |
| Troca do código | `POST` ao endpoint de token, com `code`, `code_verifier`, `client_id`, `redirect_uri`, `grant_type=authorization_code`. Credenciais no corpo, nunca na URL |

**Brecha residual aceita:** na máquina do usuário, qualquer processo que consiga se ligar à porta efêmera antes do nosso servidor poderia capturar o código. O `state` e o PKCE impedem que esse código seja trocado por quem não tem o `code_verifier` — que nunca sai da memória do aplicativo. A janela é de milissegundos e o atacante já teria de estar executando código como o usuário, o que §1.3 coloca fora de escopo.

### 12.3 Escopos mínimos por provedor

| Provedor | Escopos | Observação |
|---|---|---|
| **Google** | `https://mail.google.com/`; mais `openid email` quando for necessário obter o endereço do `id_token` | O Google **não oferece** escopo mais estreito para IMAP/SMTP: este escopo concede acesso total à caixa de correio via IMAP. É o mínimo que o protocolo exige, e é amplo — o usuário deve saber disso na tela de consentimento do provedor |
| **Google — parâmetros** | `access_type=offline` e `prompt=consent` na primeira autorização | Sem eles o provedor não emite `refresh_token`, e o usuário seria obrigado a reautorizar a cada expiração |
| **Microsoft** | `https://outlook.office.com/IMAP.AccessAsUser.All`, `https://outlook.office.com/SMTP.Send`, `offline_access`, `openid`, `email`, `profile` | Escopos de protocolo para Exchange Online. **Não** usar escopos do Microsoft Graph (`Mail.ReadWrite` e afins): são de outra API e não habilitam IMAP |
| **Qualquer provedor** | Proibido pedir escopo além do necessário: nada de `Calendars`, `Contacts`, `Files`, `User.Read.All`, `Mail.Send` (Graph) | `RNF-PRIV-02` no espírito, e coerência com `01-requisitos.md` §7 (calendário e contatos fora de escopo) |

Os escopos são **fixos em código** por provedor, em um dicionário `PROVIDER_SCOPES`. Não há campo de configuração para escopos livres: um campo desses seria usado para pedir mais, nunca menos.

### 12.4 Expiração e renovação

| Situação | Comportamento |
|---|---|
| Antes de cada conexão | Se `now >= expires_at - 300`, renovar proativamente |
| Onde a renovação roda | Na thread `AccountWorker` da conta. Nunca na thread da GUI (`RNF-PERF-01`) |
| Sucesso | Novo `access_token` (e possivelmente novo `refresh_token`) gravado no keyring antes do uso |
| `invalid_grant` / `invalid_token` | `AuthError`: pausa **aquela** conta, notifica uma vez, oferece reautorização. As outras contas continuam (`CA-RF-ACC-02-1`) |
| Falha transitória de rede na renovação | Recuo exponencial como `RF-MSG-08`, com teto. **Guarda contra tempestade:** no máximo uma tentativa de renovação por conta a cada 60 s, independentemente de quantas operações falharem — sem essa guarda, uma queda do provedor produziria centenas de requisições de token |
| `invalid_client` / `unauthorized_client` | Erro de configuração do aplicativo, não do usuário: mensagem distinta, sem oferecer reautorização (que não resolveria) |
| `AccountWorker` encerrado durante a renovação | A renovação é descartada; o token gravado permanece o antigo, e a próxima conexão renova de novo |
| `AuthProvider.can_renew_silently()` | `True` quando existe `refresh_token` e o escopo inclui `offline_access`. Se `False`, a conta exige interação do usuário, e a interface indica isso antes de tentar conectar |
| `AuthProvider.invalidate()` | Descarta o `access_token` em memória e força renovação na próxima conexão. Não apaga o `refresh_token` — isso é reautorização |
| Revogação pelo usuário no provedor | O refresh falha com `invalid_grant`; o caminho é o mesmo, e a interface deve dizer que a causa provável é revogação no provedor, não erro do cliente |
| Revogação pelo aplicativo | Em "Remover conta" com `[F2]`, oferece (opção marcada por padrão quando há conectividade) chamar o endpoint de revogação do provedor antes de apagar o item do keyring. **Se falhar, a remoção local prossegue** e o usuário é informado de que a autorização continua válida no provedor e pode ser revogada na página de segurança da conta. Apagar o item local satisfaz `CA-RF-ACC-05-1` |

### 12.5 O que nunca deve ser gravado em log

Além de toda a lista de §2.5, específico de OAuth2:

| Item | Por quê |
|---|---|
| `access_token`, `refresh_token`, `id_token` | Acesso direto à conta. O `refresh_token`, em particular, é de longa duração |
| `code` | Trocável por token enquanto válido |
| `code_verifier`, `code_challenge` | O `verifier` é o segredo do PKCE; o `challenge` embora não seja secreto, denuncia o algoritmo e não tem valor de diagnóstico |
| `state`, `nonce` | Não são secretos, mas registrá-los permite correlacionar tentativas de autorização e não tem valor de diagnóstico. Registra-se apenas **presença/ausência** |
| URL de autorização completa | Contém `code`, `state` e o `redirect_uri` com a porta |
| Corpo de requisição e de resposta do endpoint de token | Contém todos os campos acima |
| Cabeçalho `Authorization` e string SASL `XOAUTH2` (`user=<email>\x01auth=Bearer <token>\x01\x01`, base64) | Contém token e endereço. O código nunca forma essa string para log; se precisar de diagnóstico, registra o comprimento |
| `client_id` | Não é secreto para um cliente público, mas identifica a instalação do aplicativo. Registrado apenas em nível de diagnóstico explícito |
| Resposta de erro do provedor sem filtro | O provedor pode ecoar parâmetros da requisição. Registra-se apenas o campo `error` e o `error_description` truncado, e ambos passam pelo `RedactionFilter` |

Regra de implementação: a string SASL e o `Authorization` são construídos dentro de um escopo mínimo, em uma variável local, imediatamente antes da chamada de protocolo, e nunca são passados a `logger`. Revisão de código verifica que não existe chamada de log com essas variáveis no `core/`.

### 12.6 Pendência de verificação factual — item B-01 do backlog

Registro explícito, sem afirmação de fato verificado:

> **Durante a escrita desta especificação, o ambiente de desenvolvimento estava sem acesso à busca web.** As afirmações abaixo são **premissas não reconfirmadas** e **não** devem ser tratadas como verificadas hoje:
>
> 1. Que a Microsoft **descontinuou** a autenticação básica em IMAP/SMTP no Exchange Online, tornando OAuth2 obrigatório, e em que data e com que eventuais exceções (contas legadas, *tenants* que reativaram o SMTP AUTH).
> 2. Que o Google **ainda disponibiliza** *app passwords* para contas com verificação em duas etapas, e sob quais condições isso pode acabar.
> 3. Quais são, **hoje**, os escopos exatos exigidos por cada provedor para IMAP e SMTP.
> 4. Quais são as exigências atuais de registro de aplicativo em cada provedor para um cliente público de desktop com `redirect_uri` de *loopback* e PKCE, e se algum provedor exige `client_secret`.
> 5. Se os endpoints de token e de revogação permanecem os mesmos, e se a rotação de `refresh_token` está ativa em cada provedor.
> 6. Se `localhost`/`127.0.0.1` continua aceito como `redirect_uri`, ou se algum provedor passou a exigir esquema privado ou *device code flow*.
>
> Estas afirmações correspondem ao **item B-01** do backlog de `02-arquitetura.md` §11 e ao alerta do ADR-002. **A fase 2 não pode ser congelada sobre elas.** A ação necessária é reconfirmar cada item na documentação oficial de cada provedor, registrar a data da verificação e o *link* consultado, e só então fechar o escopo de `RF-ACC-06`.
>
> Consequência para a fase 1, que **não** depende desta verificação: a abstração `AuthProvider` (`RF-ACC-04`, `CA-RF-ACC-04-1`) garante que a fase 2 entra sem refatoração de `ui/` ou de `storage.py`, qualquer que seja a resposta.

Nada nesta seção afirma que qualquer um desses pontos está confirmado hoje.

---

## 13. Testes de segurança obrigatórios

A implementação dos testes abaixo — *fixtures*, servidores falsos, instrumentação e organização — está em `06-estrategia-de-testes.md`. Esta seção define **o que** precisa ser provado, **com que entrada** e **contra qual critério de aceite**.

### 13.1 Corpus hostil e artefatos de apoio

Corpus de `CA-RF-RD-01-1`, em `tests/fixtures/eml/malicious/`, um arquivo `.eml` por cenário:

| Arquivo | Conteúdo |
|---|---|
| `script_inline.eml` | `<script>alert(1)</script>`, `<script src="https://exemplo/x.js">`, `<script>` sem fechamento |
| `javascript_href.eml` | `javascript:alert(1)`, `JaVaScRiPt:`, `java\tscript:`, `&#x6a;avascript:`, `\x01javascript:`, ` javascript:` e `vbscript:` |
| `onerror_img.eml` | `<img src=x onerror=…>`, `onload`, `onmouseover`, `onfocus` com `autofocus`, e atributo com maiúsculas mistas |
| `iframe_remote.eml` | `<iframe src="https://exemplo/">`, `<iframe srcdoc=…>`, `<iframe>` de 1×1 |
| `object_embed.eml` | `<object data=…>`, `<embed src=…>`, `<applet>`, `<param>` |
| `form_phishing.eml` | `<form action="https://exemplo/steal" method=post>` com `<input type=password>` e `<button>` |
| `style_expression.eml` | `style="width: expression(alert(1))"`, `behavior: url(#default#time2)`, `-moz-binding` |
| `css_import_remote.eml` | `<style>@import url(https://exemplo/x.css);</style>`, `<link rel=stylesheet>`, `@font-face` |
| `css_url_background.eml` | `style="background-image:url(https://exemplo/px.gif)"`, `list-style-image`, `cursor:url()`, e a variante `u\72 l(...)` |
| `css_var_smuggle.eml` | `style="--x: url(https://exemplo/px.gif); background-image: var(--x)"` |
| `base_href.eml` | `<base href="https://exemplo/">` com `<img src="/px.gif">` e `<a href="/x">` relativos |
| `svg_foreignobject.eml` | `<svg><foreignObject>…<script>`, `<svg><a xlink:href="javascript:…">`, `<animate>` |
| `mathml_xlink.eml` | `<math><mtext><a xlink:href="javascript:…">` |
| `mXSS_nested.eml` | `<noscript><p title="</noscript><img src=x onerror=…>">`, `<div id="</div><script>…">`, `<table><script>` com *foster parenting* |
| `picture_srcset.eml` | `<picture><source srcset="https://exemplo/a 2x"></picture>` e `<img srcset=… sizes=…>` |
| `meta_refresh.eml` | `<meta http-equiv="refresh" content="0;url=https://exemplo/">` |
| `a_ping.eml` | `<a href="https://exemplo/" ping="https://exemplo/track">` |
| `data_uri_svg.eml` | `<img src="data:image/svg+xml;base64,…">` e `<a href="data:text/html,…">` |
| `nul_byte_href.eml` | `href="https://exemplo/&#0;@atacante/"`, `src` com `NUL` e byte `NUL` literal |
| `entity_obfuscated_scheme.eml` | `&#106;avascript:`, `jav&#x61;script:`, `&#14; javascript:` |
| `file_scheme.eml` | `<a href="file:///etc/passwd">`, `<a href="\\servidor\share">`, `<img src="file:///etc/shadow">` |
| `tracking_pixel_1x1.eml` | `<img src="https://rastreador/p.gif" width=1 height=1>`, `width="0"`, `border=0` combinado |
| `tracking_pixel_css_hidden.eml` | `style="display:none"`, `visibility:hidden`, `opacity:0`, `max-height:0`, `transform:scale(0)`, `clip:rect(0,0,0,0)`, `height:0` |
| `tracking_pixel_spacer.eml` | `<img src="https://exemplo/spacer.gif" alt="" width=1 height=1>` |
| `utm_links.eml` | Links com `utm_*`, `fbclid`, `gclid`, `mc_eid`, `_hsenc`, `_hsmi`, `vero_id`, `igshid`, fragmento com `#utm_source=`, parâmetro repetido, parâmetro sem valor, e um link de redefinição com `?token=…&id=…` que **deve** ser preservado |
| `link_text_mismatch.eml` | `<a href="https://exemplo.com/x">https://banco-falso.com</a>` |
| `cid_inline.eml` | `<img src="cid:logo@exemplo">` com a parte MIME correspondente |
| `position_fixed.eml` | `style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:99999"` |
| `huge_body.eml` | ~8 MB de HTML (acima do teto de §4.1, passo 0) |
| `deep_nesting.eml` | 5.000 `<div>` aninhados |
| `attachment_traversal.eml` | Partes com nomes `../../evil.sh`, `CON`, `NUL.txt`, `..\..\win.ini`, `arquivo\x00.exe`, nome de 300 caracteres, `fatura.pdf.exe` |

Artefatos de apoio: `tests/fixtures/eml/legitimate/` (corpus de mensagens reais anonimizadas, para detecção de falso positivo), `tests/fixtures/links/tracking_params.txt`, `tests/fixtures/links/real_world.txt`, `tests/fixtures/eml/beacons/` (recursos externos de §13.2).

### 13.2 Corpus de beacons de `CA-RNF-PRIV-01-1`

Mensagem que reúne, simultaneamente: imagens remotas `<img>`, CSS remoto (`@import` em `<style>` **e** em `style` inline), `background` em estilo inline, `<picture>`/`srcset`, `<video poster>`, `<link rel=preload>`, `<a ping>`, fonte remota via `@font-face`, `<iframe>`, e um beacon de abertura que é `<img>` de 1×1. Renderizar essa mensagem, **sem autorização**, deve produzir exatamente zero requisições permitidas.

### 13.3 Tabela de testes

| # | Cenário de ataque | Entrada | Resultado esperado | Critério |
|---|---|---|---|---|
| 1 | Execução de código pelo corpo | `script_inline.eml` + `mXSS_nested.eml` + `svg_foreignobject.eml` + `mathml_xlink.eml` | HTML sanitizado sem `script`, `svg`, `math`, `iframe`, `object`, `embed`, `form`; nenhum atributo de prefixo `on`; nenhum esquema `javascript:`; nenhum conteúdo textual de `<script>` visível nem indexado | CA-RF-RD-01-1 |
| 2 | Esquema hostil ofuscado | `javascript_href.eml`, `entity_obfuscated_scheme.eml`, `nul_byte_href.eml` | Todo `href`/`src` com esquema proibido **removido** (atributo ausente, não vazio) | CA-RF-RD-01-1 |
| 3 | CSS remoto | `css_import_remote.eml`, `css_url_background.eml`, `css_var_smuggle.eml` | Zero requisições; nenhum `url(`, `var(` ou `--` no `style` final; `@import` ausente | CA-RF-RD-01-1, CA-RNF-PRIV-01-1 |
| 4 | `expression()` | `style_expression.eml` | Declaração descartada; nenhuma ocorrência de `expression` no HTML final | CA-RF-RD-01-1 |
| 5 | `<base href>` e URL relativa | `base_href.eml` | Tag `base` ausente; `img` relativo sem `data-pymail-src`; `a` relativo inerte; nenhuma requisição | CA-RF-RD-01-1 |
| 6 | Redirecionamento por `meta` | `meta_refresh.eml` | Tag `meta` do remetente ausente; apenas as duas `meta` injetadas por nós | CA-RF-RD-01-1 |
| 7 | Zero requisições do corpus de beacons | `CA-RNF-PRIV-01-1` (§13.2), sem autorização | `recorder.allowed == 0` **e** `recorder.blocked > 0` | CA-RNF-PRIV-01-1 |
| 8 | 20 imagens remotas bloqueadas | mensagem com 20 `<img>` externos | `allowed == 0`, `blocked == 20`, todas `ResourceTypeImage` com `reason="not_authorized"` | CA-RF-RD-03-1 |
| 9 | Autorização por remetente | autorizar `a@exemplo.com`; abrir mensagem dele e mensagem de `b@exemplo.com`; reiniciar | Imagens de `a@` carregam (1 requisição cada, `allowed`, `https`); de `b@` não; a autorização sobrevive ao reinício | CA-RF-RD-03-2 |
| 10 | Pixel 1×1 sob autorização | `tracking_pixel_1x1.eml`, `tracking_pixel_css_hidden.eml`, **com autorização ativa** | Zero requisições para a URL do pixel; a URL do pixel não aparece no `html_sanitized` gravado; zero `data-pymail-src` apontando para ela | CA-RF-RD-04-1 |
| 11 | Nada além de imagem autorizada | requisição a host externo de folha de estilo, fonte, XHR, mídia, `favicon`, `ping`, `object`, worker, prefetch, CSP report, `ResourceTypeUnknown` | Todas canceladas e registradas com `reason="resource_type_blocked"` | CA-RF-RD-06-1 |
| 12 | Origem de primeira parte estranha | requisição cujo `firstPartyUrl` não é `pymail://message/` | Bloqueada, `reason="first_party_foreign"`, mesmo que fosse imagem autorizada | RF-RD-06 |
| 13 | Link com texto e destino divergentes | `link_text_mismatch.eml`; clicar | Diálogo mostra `https://exemplo.com/x` como destino e `https://banco-falso.com` como texto exibido; abre `exemplo.com`; nunca o texto | CA-RF-RD-07-1 |
| 14 | Parâmetros de rastreamento | `utm_links.eml` | Todos os parâmetros da lista removidos (query e fragmento, caixa variável, repetidos, sem valor); `?token=` e `?id=` **preservados**; a URL exibida na confirmação é a limpa | RF-RD-05 (sem CA — §14, item 3) |
| 15 | Nenhuma navegação interna | clique em qualquer link; `ResourceTypeMainFrame` com `http(s)` | A view permanece em `pymail://message/`; o navegador padrão recebe apenas `http`/`https`; `mailto:` abre o compositor sem `subject`/`body` | RF-RD-07 |
| 16 | Credencial fora de banco, config e log | cadastrar conta, sincronizar, ler, enviar; varrer banco, `config.toml`, arquivos de log e `sys.argv` | Senha ausente em todos, em texto claro **e** em forma reversível | CA-RNF-SEC-01-1 |
| 17 | Redação de logs | execução de teste que exercita login, leitura e envio; varrer os logs por cada cadeia de §2.5 | Nenhuma ocorrência; **e** o controle positivo do `RedactionFilter` casa com entradas construídas para cada padrão | CA-RF-SET-04-1 |
| 18 | Controle positivo da redação | chamada de log com uma entrada de cada padrão de §2.6.3 | Cada padrão é efetivamente mascarado (um filtro que não casa é uma falha, não um silêncio) | CA-RF-SET-04-1 |
| 19 | Certificado inválido | servidor falso com certificado autoassinado; depois expirado; depois com nome divergente | `TLSError` nas três; mensagem nomeia a causa; **nenhuma** conexão em texto claro é tentada em seguida; nenhuma tentativa adicional por recuo | CA-RNF-SEC-02-1 |
| 20 | Exceção de TLS auditável | habilitar fixação de impressão digital; reconectar; trocar o certificado do servidor falso | Conecta com a impressão correta; recusa com impressão diferente; log registra `account_id`, host e `pinned_at`; aviso persistente visível | CA-RNF-SEC-02-1 |
| 21 | Ausência de degradação silenciosa | servidor falso que responde `NO` a `STARTTLS`; servidor que não anuncia `STARTTLS` em 143 | Falha dura nas duas; nenhum comando de autenticação enviado em canal não cifrado (verificado no lado do servidor falso) | RNF-SEC-02 |
| 22 | Varredura estática de TLS | `core/network/` | Não existe `CERT_NONE`, `check_hostname=False`, `_create_unverified_context`, `PROTOCOL_TLSv1` nem porta de texto claro fora das tabelas de §3.5 | RNF-SEC-02 |
| 23 | Credencial em texto claro recusada | conta com `outgoing_security='none'` e `allow_insecure_outgoing=0`; enviar | Envio recusado antes de abrir socket, com mensagem explícita; o servidor falso registra **zero** conexões | CA-RF-SND-07-1 |
| 24 | Credencial em texto claro com exceção | mesma conta com `allow_insecure_outgoing=1` | Envio permitido; aviso permanente visível; evento registrado em log com `account_id` e host, sem senha | RF-SND-07 |
| 25 | Nomes de anexo hostis | `attachment_traversal.eml` | Todos gravados dentro da pasta de destino, com os nomes de §9.1; nenhum arquivo criado fora; nenhum dispositivo do Windows tocado | CA-RNF-SEC-04-1 |
| 26 | Contenção de caminho | pasta de destino com link simbólico apontando para fora | Gravação recusada; nenhum arquivo criado fora da pasta | RNF-SEC-04 |
| 27 | Sem abertura automática | receber e baixar anexo `.exe` | `QDesktopServices.openUrl` chamado zero vezes; aviso reforçado exibido; nenhuma permissão de execução definida | RNF-SEC-03 |
| 28 | Remoção de conta limpa tudo | remover conta | Zero linhas em `accounts`, `folders`, `messages`, `bodies`, `attachments`, `sender_image_policy`, `pending_ops`; zero referências no `messages_fts`; zero chaves no keyring falso | CA-RF-ACC-05-1 |
| 29 | Configuração do motor não regride | dois `ReaderPane` criados em sequência | Ambos com todas as definições de §8.1/§8.2/§8.3 nos valores esperados; perfil não é o padrão; é off-the-record; interceptor presente e efetivo | RNF-PRIV-01, RNF-SEC-03 |
| 30 | Nada é gravado pelo motor | renderizar mensagem autorizada; listar arquivos criados | Nenhum arquivo novo além de banco, `-wal`, `-shm`, config e logs | RNF-SEC-05, RNF-PRIV-01 |
| 31 | Conjunto exato de destinos de rede | fluxo completo de §11.3 | Conjunto observado de sockets idêntico ao esperado; nenhum destino extra; nenhuma resolução de nome além das esperadas; `DnsPrefetchEnabled` e `HyperlinkAuditingEnabled` em `False` | RNF-PRIV-02 |
| 32 | Controle positivo de tráfego | mensagem de remetente autorizado com imagem `https` | Exatamente 1 requisição, registrada como `allowed` | RNF-PRIV-01 |
| 33 | Idempotência e pureza | corpus hostil inteiro, `sanitize(sanitize(x)) == sanitize(x)`; e duas execuções com a mesma entrada | Saídas idênticas; nenhuma chamada de rede, banco ou keyring durante a sanitização | RNF-MAINT-01 |
| 34 | Nenhum HTML não sanitizado no motor | duplo de `setHtml` capturando a string entregue | Sem `data-pymail-` (descartado pelo passe B), sem esquema proibido, sem `on*`, com as duas `meta` esperadas | RF-RD-01, §4.7 |
| 35 | Falso positivo em corpus legítimo | `tests/fixtures/eml/legitimate/` | Todas as imagens legítimas preservadas como `data-pymail-src`; nenhuma imagem legítima removida por H1–H10; nenhum parâmetro funcional removido | RNF-USA-01, §5.2.2 |
| 36 | Mensagem hostil não trava a interface | `huge_body.eml`, `deep_nesting.eml` | Sanitização no `TaskPool`; a thread da GUI não bloqueia por mais de 100 ms | CA-RNF-PERF-01-1, RNF-PERF-01 |
| 37 | Teto de entrada respeitado | `huge_body.eml` (8 MB) | HTML descartado; renderização a partir do texto plano; nenhum consumo anômalo de memória | RNF-SEC-03 (por ausência de requisito próprio — §14, item 9) |
| 38 | Backends de keyring | backends falsos: ausente, bloqueado, em texto claro, funcional | Ausente/bloqueado/texto claro → modo memória com aviso e `credential_storage="memory"`; nenhum arquivo com segredo é criado; funcional → gravação normal | RNF-SEC-01 |
| 39 | Remoção de conta com keyring falho | simular falha de remoção no keyring | Remoção abortada antes de tocar o banco; a conta continua íntegra; usuário informado | CA-RF-ACC-05-1 |
| 40 | `AuthProvider` plugável | registrar um provider falso | Autentica por ele sem alteração em `ui/` ou em `storage.py` | CA-RF-ACC-04-1 |

**Metodologia obrigatória, aplicada a todas as linhas:** cada teste asserta um **controle positivo** — a construção hostil está presente na entrada e ausente na saída. Um teste que apenas verifica "não lançou exceção" ou "o pipeline retornou algo" não é um teste de segurança e não conta para `CA-RF-RD-01-1`. Onde houver risco de o instrumento não estar funcionando (testes 7, 11, 17, 18, 31, 32), há asserção explícita de que o instrumento **viu** o que deveria ver.

---

## 14. Lacunas identificadas

Necessidades de requisito encontradas durante a escrita desta especificação, que **não existem** em `01-requisitos.md`. Nenhum identificador novo foi criado; cada item aponta onde a falta se manifesta.

| # | Lacuna | Onde se manifesta | Impacto se não resolvida |
|---|---|---|---|
| 1 | **`RNF-SEC-05` (permissões restritas) não tem critério de aceite.** A matriz de `01-requisitos.md` §8 registra `—` | §10.1 desta spec | A seção inteira de permissões fica sem verificação obrigatória. É verificável por teste trivial (asserção de `stat`), e por isso a ausência é barata de corrigir |
| 2 | **`RNF-PRIV-02` (nenhuma telemetria) não tem critério de aceite**, embora §11.3 descreva três camadas de verificação | §11.2, §11.3 | A afirmação mais forte da proposta de valor depois do bloqueio de pixel — "não há telemetria" — não está amarrada a nenhum critério de aceite |
| 3 | **`RF-RD-05` (remoção de parâmetros de rastreamento) não tem critério de aceite.** A matriz registra `—` | §5.2 | Um requisito de privacidade sem CA verificável, contrariando a regra de rastreabilidade de `01-requisitos.md` §2. Falta algo como "`CA-RF-RD-05-1`: URL com N parâmetros da lista é reescrita sem eles, preservando `token`/`id`" |
| 4 | **Revogação e gerenciamento da autorização de imagens.** `RNF-PRIV-04` exige autorização "granular e revogável, gerenciável em um painel", mas `Storage` (`02-arquitetura.md` §5.4) expõe apenas `is_sender_allowed` e `allow_sender_images`; não existe `revoke_sender_images` nem `list_allowed_senders`. Não há requisito de UI para o painel, e `CA-RF-RD-03-2` testa apenas persistência | §6.5 | A autorização é concedível e **não revogável pela interface**, o que contraria `RNF-PRIV-04` e torna o consentimento irreversível na prática — o oposto do prometido |
| 5 | **Escopo de rede da autorização por remetente.** Não há requisito definindo se, ao autorizar um remetente, **qualquer** host HTTPS referenciado na mensagem pode ser buscado | §6.4 | É a brecha residual mais relevante do mecanismo de autorização. A alternativa seria autorização por host, ou um aviso no momento da concessão indicando os hosts que serão contatados. Decisão precisa de ratificação explícita |
| 6 | **Imagens autorizadas em `http:` (texto claro).** `RNF-SEC-02` trata das conexões de correio, não do conteúdo; nenhum requisito decide se uma imagem autorizada pode ser buscada por `http:` | §7.3 | Esta spec bloqueia `http:` mesmo sob autorização, com aviso de contagem. A decisão é conservadora e defensável, mas não está ancorada em requisito |
| 7 | **Imagens inline (`cid:`).** Nenhum requisito define o comportamento; `RF-RD-03` fala de "recursos remotos" | §6.3, §4.4 | Esta spec **não as renderiza** na fase 1 (placeholder textual; o arquivo fica no painel de anexos). É uma perda de fidelidade visível em e-mails com logotipo embutido, e a decisão precisa ser ratificada, incluindo limites de tamanho e tipos MIME aceitos |
| 8 | **URI `data:`.** Nenhum requisito. Esta spec bloqueia integralmente, inclusive imagens base64 legítimas | §4.4 | Mensagens que embutem imagens em base64 não as exibem. A alternativa (permitir com validação de MIME, teto de tamanho decodificado e rejeição de SVG) precisa de decisão e de requisito |
| 9 | **Tetos de tamanho.** Não há requisito para o tamanho máximo do HTML de entrada nem para o tamanho de anexo aceito para gravação. `RF-SND-06` cobre apenas o envio | §4.1 (passo 0), §9 | O pipeline depende de um teto para não ser vetor de negação de serviço (T-12). O valor de 5 MiB é escolha desta spec, sem requisito que o sustente, e não há teto nenhum do lado do recebimento |
| 10 | **Inconsistência entre `accounts.incoming_security` e `RNF-SEC-02`.** O `CHECK` do schema (`03-modelo-de-dados.md` §3) aceita `'none'` para entrada, mas não existe exceção de entrada simétrica a `allow_insecure_outgoing`, e `RNF-SEC-02` exige TLS de entrada | §3.5 | Um valor válido no banco é sempre recusado pela camada de conexão. Se a intenção era permitir exceção de entrada, faltam coluna e requisito; se não era, o `CHECK` deveria excluir `'none'` |
| 11 | **Ação explícita de apagar o cache local.** Não há requisito para "apagar o cache agora" — distinto de cifrar o banco, que `01-requisitos.md` §7 põe fora de escopo | §10.5 | Sem ela, o usuário que precisa reduzir exposição depende de remover a conta (perdendo configuração e credencial) ou de manipular arquivos por fora |
| 12 | **Privacidade de DNS e suporte a proxy.** Nenhum requisito. `DnsPrefetchEnabled=False` (acréscimo desta spec) e a resolução do host de correio continuam vazando ao resolvedor; e não há como rotear as requisições de imagem autorizada por um proxy ou por Tor | §8.3, §11.1 | Um cliente cujo valor é privacidade não tem como endereçar o vazamento de metadados de DNS nem a exposição do IP real quando o usuário autoriza imagens — exatamente o dado que o pixel buscava |
| 13 | **CSP e registro de tentativas bloqueadas sem critério de aceite próprio.** A injeção de `Content-Security-Policy` consta do ADR-004 mas não tem CA; `CA-RF-RD-06-1` menciona registro de bloqueio, mas não define formato, retenção nem exposição ao usuário | §4.6, §7.5 | A defesa em profundidade mais barata do pipeline não é exigível, e o registro que torna `CA-RNF-PRIV-01-1` verificável pode ser removido em uma refatoração sem que nenhum critério falhe |
| 14 | **Redação de logs mais estrita que `CA-RF-SET-04-1`.** O critério cobre senha, token, corpo e caminho de anexo; não menciona **URLs com parâmetros de rastreamento** nem endereços de e-mail | §2.5, §5.1.5 | Esta spec adota política mais estrita do que o critério exige, e a decisão não tem respaldo em requisito. Nota relacionada: a preservação da URL original com parâmetros de rastreamento em `data-pymail-src` (§5.1.5, última linha) é uma brecha conhecida que precisa de decisão explícita |
| 15 | **Exceção de TLS sem requisito de aviso e sem requisito de gestão de CA.** `CA-RNF-SEC-02-1` exige exceção "explícita e registrada", mas não há requisito para o aviso persistente, para o escopo da exceção nem para adicionar uma CA corporativa pelo aplicativo | §3.3 | O mecanismo de fixação de impressão digital desta spec é mais forte do que o critério pede, mas o usuário pode acabar em uma situação de conexão degradada sem sinalização exigível |
| 16 | **`RNF-SEC-06` (`[F2]`, OpenPGP) sem critério de aceite e sem requisito de interação com a sanitização** | §4 | Mensagem assinada ou cifrada muda o que a sanitização vê (parte `application/pkcs7-mime`, `multipart/encrypted`, texto cifrado no corpo). Sem requisito, a fase 2 pode introduzir um caminho que renderiza conteúdo sem passar pelo pipeline |
| 17 | **Cadeia de suprimentos.** Nenhum requisito de verificação de integridade, de assinatura ou de SBOM para `PySide6`, `nh3` e `tinycss2`. `RNF-PACK-01` mede tamanho, não proveniência | §1.3 | As duas dependências nativas que sustentam a sanitização são tratadas como confiáveis sem verificação declarada |
| 18 | **Segredos em memória.** `RNF-SEC-01` cobre repouso em disco. Não há requisito sobre `mlock`, sobre limpeza de buffers ou sobre desativação de despejo de núcleo | §2.2, §10.4 | Um `core dump` ou o arquivo de paginação pode conter a senha e os tokens. A limitação é declarada nesta spec, mas não é tratada por requisito |
| 19 | **Normalização de `accounts.email`.** `03-modelo-de-dados.md` §3 não fixa caixa nem normalização, mas a chave do keyring (§3, comentário da DDL) depende dela para ser estável | §2.1 | Reimportar uma conta com caixa diferente cria chave de keyring diferente e "perde" a credencial. Precisa ser fixado no schema (ou por `COLLATE NOCASE`, ou por normalização na escrita) |
| 20 | **Divergência de permissão para `config.toml`.** `02-arquitetura.md` §8.1 registra `0644`; esta spec adota `0600`, porque o arquivo contém hosts, usuários e a lista de remetentes com imagens autorizadas | §10.1 | Duas specs normativas afirmam valores diferentes para o mesmo arquivo. Uma das duas precisa ceder, e a decisão precisa ser registrada |
| 21 | **Sem requisito de atualização segura.** A ausência de verificação de atualização é coerente com `RNF-PRIV-02` e é mantida, mas não há requisito nem procedimento para que o usuário receba correções de segurança | §11.2 | Uma vulnerabilidade no pipeline de sanitização não tem canal de correção definido. A decisão é defensável, mas precisa ser explícita em vez de implícita |

---

**Fim do documento.** As afirmações de segurança desta spec foram escritas para serem verificáveis pelos critérios de `01-requisitos.md`. Onde a proteção não é completa — pixels que dependem dos bytes da imagem (§5.1.5), ausência de cifragem do cache (§10.3), autorização de remetente que libera qualquer host HTTPS (§6.4), phishing (§1.4 T-04), corrida de documento no interceptor (§7.4) — a brecha está declarada no lugar onde o leitor a encontraria, e não em nota de rodapé.
