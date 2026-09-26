# PyMail Client

![status](https://img.shields.io/badge/status-alfa%20inicial-orange)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![qt](https://img.shields.io/badge/Qt-PySide6%206.6%2B-green)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

Cliente de e-mail desktop leve, minimalista e multiplataforma (Windows, Linux, macOS), escrito em Python com PySide6. Privacidade por padrão, renderização de HTML sem quebras e sincronização de cabeçalhos antes de corpos.

> **Estado: alfa inicial.** O núcleo de dados, o sanitizador de HTML e a camada de conexão estão implementados e testados. **Ainda não existe interface gráfica nem ponto de entrada executável** — veja [Estado do projeto](#estado-do-projeto) antes de tentar rodar o aplicativo.

---

## O problema que este projeto ataca

Clientes de e-mail clássicos falham em três frentes concretas, e cada uma tem um requisito verificável por teste automatizado aqui dentro:

| Problema | Como é resolvido | Como é comprovado |
|---|---|---|
| **Lentidão** — a interface congela durante rede e disco | Uma thread dedicada e uma conexão por conta; nenhuma operação de rede ou disco na thread da GUI | `CA-RNF-PERF-01-1` — detector de bloqueio da thread principal durante sincronização de 5.000 mensagens |
| **Renderização quebrada** — HTML moderno desmonta | `QWebEngineView` com JavaScript desabilitado, sanitização por allowlist sobre parser real | `CA-RF-RD-01-1` — corpus hostil de 15 mensagens |
| **Rastreamento** — pixels e parâmetros de rastreio expõem o usuário | Bloqueio na camada de rede por interceptor, remoção irreversível de pixels, sem imagens externas por padrão | `CA-RNF-PRIV-01-1` — zero requisições originadas pelo conteúdo |
| **Não achar nada** — busca lenta ou inexistente | SQLite com FTS5, índice insensível a acentos mantido na mesma transação do corpo | `CA-RF-SRCH-01-1` — buscar `acao` encontra `Ação` |

---

## Estado do projeto

Última verificação: **2026-09-25**. Suíte: **96 testes passando**, `ruff check` e `ruff format --check` sem avisos.

### O que funciona hoje

| Módulo | Situação | Testes |
|---|---|---|
| `pymail_client/config.py` | `AppConfig` com todos os padrões da spec validados | 7 |
| `pymail_client/core/security.py` | Credenciais exclusivamente no keyring, com denylist de backends em texto claro | 10 |
| `pymail_client/core/sanitizer.py` | Pipeline completo em 8 passos: pixels, parâmetros de rastreio, CSS, CSP | 72 |
| `pymail_client/core/storage.py` | Schema v1, migrações transacionais, PRAGMAs, FTS5 | 4 |
| `pymail_client/core/network/imap_client.py` | Conexão com TLS validado e erros tipados | 3 |
| `tests/fakes/imap_server.py` | Servidor IMAP falso em socket, com registro de comandos | — |

### O que ainda não existe

| Ausente | Consequência |
|---|---|
| `pymail_client/main.py` | O aplicativo não inicia. Não há como usá-lo como cliente de e-mail ainda |
| Todo o `pymail_client/ui/` | Sem janela, sem lista, sem leitor, sem compositor |
| `pymail_client/core/tasks.py` | A infraestrutura de threads ainda não está implementada |
| `pymail_client/core/clock.py` | Tempo não é injetável, o que trava os testes de Undo Send e de carência de 24 h |
| Fachada da `Storage` | 13 métodos (`search`, `upsert_account`, `evict_bodies_lru`…) estão declarados com `...` e **retornam `None` silenciosamente** |
| `.github/workflows/` e portão de cobertura | Sem integração contínua; o portão de 80% de `RNF-MAINT-01` não está ativo |
| `LICENSE` | MIT está declarado em `pyproject.toml`, mas o arquivo ainda não foi criado |

Progresso: **4 de 41 tarefas** do plano de execução. A especificação completa está em [`docs/spec/`](docs/spec/) e o plano em [`docs/plans/fase1.md`](docs/plans/fase1.md).

---

## Requisitos

- **Python 3.11 ou superior** — o ambiente de desenvolvimento atual usa 3.14; a matriz de integração contínua prevista cobre 3.11 e 3.12, que ainda **não foram exercitados**
- Windows 10+, Ubuntu 22.04+/Debian 12+ ou macOS 12+
- No Linux, um provedor de Secret Service ativo (GNOME Keyring, KWallet) para o `keyring`; sem ele o aplicativo mantém a credencial apenas em memória, nunca em arquivo

## Instalação

```bash
git clone https://github.com/EduradoPessoa/pymail-client.git
cd pymail-client

python -m venv .venv
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

A instalação editável é o modo previsto de trabalho: ela torna `pymail_client` importável de qualquer diretório, o que é necessário para que os utilitários em `scripts/` rodem fora do `pytest`.

## Desenvolvimento

```bash
python -m pytest -q                     # suíte completa
python -m pytest tests/test_sanitizer_adversarial.py -v   # só as sondagens de segurança
python -m ruff check .                  # análise estática
python -m ruff format --check .         # formatação
python -m pytest --cov=pymail_client.core --cov-report=term-missing   # cobertura do núcleo
```

### Utilitários

```bash
python scripts/make_golden_db.py        # regenera tests/fixtures/db/v1_golden.db
```

O banco de referência existe para provar que uma migração preserva dados reais, e não apenas um banco recém-criado. **Hoje nenhum teste o consome** — a lacuna está registrada em [`docs/spec/06-estrategia-de-testes.md`](docs/spec/06-estrategia-de-testes.md).

---

## Arquitetura

Quatro papéis de thread, com permissões estritamente definidas. Código que viole uma linha desta tabela é um defeito:

| Thread | Quantidade | Pode | **Não pode** |
|---|---|---|---|
| GUI | 1 | Ler cache já carregado, atualizar widgets, enfileirar trabalho | Rede, disco, sanitização, SQL que toque o disco |
| `AccountWorker` | 1 por conta | Ser dona exclusiva da conexão IMAP; gravar no banco | Criar ou tocar widgets |
| `TaskPool` | `min(8, 2×contas)` | Sanitizar HTML, derivar texto plano, indexar, calcular cache | Tocar a conexão IMAP |
| Temporizadores | poucos, na GUI | Agendar e enfileirar | Executar trabalho pesado |

**Por que uma thread por conta, e não um pool genérico.** `imaplib` **não é thread-safe**. Compartilhar uma conexão entre tarefas de um pool faz as respostas do servidor se cruzarem, e uma tarefa recebe a resposta da outra — falha intermitente, dependente de timing, que aparece em produção e não em teste. A afinidade de thread é imposta por construção: a conexão nasce dentro de `run()` do worker da conta.

**Comunicação apenas por sinais Qt.** Nada de acesso direto a atributos entre threads. Os objetos entregues por sinal são dataclasses congeladas, o que elimina a classe inteira de bugs de estado compartilhado mutável.

As decisões estão registradas como ADRs em [`docs/spec/02-arquitetura.md`](docs/spec/02-arquitetura.md), cada um com contexto, alternativas rejeitadas e consequências.

---

## Privacidade e segurança

### O que é garantido, e como

| Garantia | Mecanismo |
|---|---|
| Nenhuma requisição de rede originada pelo conteúdo de um e-mail | Interceptor de rede bloqueia por tipo de recurso; o HTML nunca carrega `src` remoto até o usuário autorizar |
| Pixels de rastreamento removidos de forma **irreversível** | O elemento e sua URL são removidos do artefato; não existe marcador para restaurar, então nenhuma autorização futura pode ressuscitá-los |
| Imagens externas desligadas por padrão | URLs preservadas em `data-pymail-src`, restauradas apenas por autorização **por remetente e por conta** |
| JavaScript nunca executa | Desabilitado nas definições do motor, bloqueado pela allowlist e pela CSP — três barreiras independentes |
| Credenciais nunca em disco | Exclusivamente no keyring do sistema operacional, com denylist explícita de backends em texto claro |
| Sem telemetria | Nenhuma métrica, nenhum identificador, nenhuma verificação de atualização |

O pipeline de sanitização aplica, nesta ordem: normalização da entrada, allowlist estrutural, reescrita de privacidade, e uma **segunda** allowlist como autoridade final. A ordem é normativa: inverter os passos reintroduz o pixel, apaga a evidência de ocultação ou congela um host remoto escolhido pelo remetente.

### Limitações honestas

- **Contas Microsoft 365 e Outlook.com não conectam.** A autenticação básica em IMAP/SMTP foi descontinuada pela Microsoft e OAuth2 é obrigatório, o que está previsto para uma fase seguinte. Contas Google e demais servidores IMAP funcionam com app password.
- **O instalador será grande** (~150–200 MB), porque o motor de renderização é Chromium embarcado. É o preço aceito para renderizar HTML moderno sem quebrar e bloquear rastreamento de forma confiável.
- **O sanitizador vê marcação, nunca os pixels.** Um pixel de 3×3, ou uma imagem pequena declarada como `width="600"`, não é distinguível de uma imagem legítima sem baixá-la — e baixá-la é exatamente o que o produto se recusa a fazer. Antes da autorização do remetente, nenhum desses casos gera requisição.
- **O banco local não é cifrado.** O conteúdo em cache é legível por qualquer processo com acesso à conta do usuário.
- **Sem OpenPGP ou S/MIME.**

---

## Estrutura do projeto

```text
pymail_client/
├── main.py                        ⏳  ponto de entrada — AUSENTE
├── config.py                      ✅  AppConfig, caminhos por sistema operacional
├── core/
│   ├── auth.py                    ✅  AuthProvider plugável; senha hoje, OAuth2 depois
│   ├── sanitizer.py               ✅  pipeline de HTML e privacidade (8 passos)
│   ├── security.py                ✅  keyring; reexporta o sanitizador
│   ├── storage.py                 ⚠️  schema e migrações OK; fachada só declarada
│   ├── models.py                  ✅  dataclasses de domínio congeladas
│   ├── errors.py                  ✅  taxonomia de erros
│   ├── clock.py                   ⏳  relógio injetável — AUSENTE
│   ├── tasks.py                   ⏳  AccountWorker e TaskPool — AUSENTE
│   └── network/
│       ├── base.py                ✅  protocolo IncomingMailClient
│       ├── imap_client.py         ✅  conexão, TLS, erros tipados
│       ├── smtp_client.py         ⏳  AUSENTE
│       └── pop_client.py          ⏳  fase 2
├── ui/                            ⏳  INTEIRO AUSENTE
│   ├── main_window.py
│   ├── styles.py
│   ├── shortcuts.py
│   └── components/                (sidebar, message_list, reader, composer, …)
├── assets/                        ⏳  ícones SVG e folhas QSS
└── tests/
    ├── fakes/                     ✅  servidor IMAP falso, keyring falso
    ├── fixtures/eml/malicious/    ✅  15 mensagens hostis
    └── fixtures/db/               ⚠️  banco de referência gerado, ainda sem consumidor
```

## Onde ficam os dados

| Conteúdo | Local | Permissão |
|---|---|---|
| Banco (`pymail.db`) e arquivos WAL | diretório de dados do aplicativo (`QStandardPaths`) | 0600, diretório 0700 |
| Configuração (`config.toml`) | diretório de configuração do aplicativo | 0600 |
| Logs | `logs/`, com rotação e redação de dados sensíveis | 0600 |
| Anexos | pasta escolhida pelo usuário | 0600 |
| Credenciais | keyring do sistema operacional | — |

O cache local é descartável por definição: pode ser apagado e reconstruído a partir do servidor. O que o usuário escreveu — rascunhos e a fila de envio — é preservado mesmo em caso de corrupção do banco.

---

## Documentação

A especificação é a fonte da verdade do projeto, e cada requisito tem um critério de aceite verificável por teste ou por procedimento manual documentado.

| Documento | Conteúdo |
|---|---|
| [`docs/spec/README.md`](docs/spec/README.md) | Índice, decisões fixadas e achados da revisão cruzada |
| [`docs/spec/01-requisitos.md`](docs/spec/01-requisitos.md) | 95 requisitos, critérios de aceite e matriz de rastreabilidade |
| [`docs/spec/02-arquitetura.md`](docs/spec/02-arquitetura.md) | 6 ADRs, modelo de threads, contratos de interface |
| [`docs/spec/03-modelo-de-dados.md`](docs/spec/03-modelo-de-dados.md) | DDL completo, FTS5, política de cache, migrações |
| [`docs/spec/04-ui-ux.md`](docs/spec/04-ui-ux.md) | Tokens, layout, atalhos, temas, acessibilidade |
| [`docs/spec/05-seguranca-privacidade.md`](docs/spec/05-seguranca-privacidade.md) | Modelo de ameaças, sanitização, limites honestos |
| [`docs/spec/06-estrategia-de-testes.md`](docs/spec/06-estrategia-de-testes.md) | Testes críticos, dublês, corpus hostil, integração contínua |
| [`docs/plans/fase1.md`](docs/plans/fase1.md) | 41 tarefas em TDD, com caminhos e comandos exatos |

O registro de execução (`docs/progress/PROGRESS.md`) existe no ambiente de desenvolvimento mas **ainda não está versionado**, e está desatualizado em relação ao plano — inclusive com numeração de tarefas divergente. Enquanto isso não for corrigido, trate `docs/plans/fase1.md` como a referência de progresso.

Caminho mais curto para entender o projeto: este README → `01-requisitos.md` §1 e §9 → `02-arquitetura.md` §1 e §3.

---

## Roteiro

**Fase 1 — núcleo vertical utilizável.** Contas IMAP múltiplas, sincronização por cabeçalhos com corpo sob demanda, leitura sanitizada, busca local, composição com Undo Send, temas, atalhos de teclado, despejo de cache, recuperação de banco corrompido, empacotamento medido.

**Fase 2.** OAuth2 (Google e Microsoft), POP3, Snooze, caixa de entrada unificada, retenção por idade, busca no servidor, painel de conversas.

**Fora de escopo.** Calendário e contatos, plugins de terceiros, Exchange ActiveSync/JMAP, aplicativo móvel, cifragem do banco local, sincronização entre máquinas.

## Problemas conhecidos

Defeitos abertos, registrados de forma explícita para que não sejam descobertos em produção:

| # | Problema | Impacto |
|---|---|---|
| 1 | Os 13 métodos de fachada da `Storage` retornam `None` em silêncio em vez de levantar `NotImplementedError` | Falha silenciosa longe da causa; **infla a cobertura**, porque uma função de uma linha conta como executada |
| 2 | O banco de referência é gerado mas nenhum teste o consome | O artefato não prova o que existe para provar |
| 3 | O servidor IMAP falso não sabe simular queda de conexão nem falha de `EXPUNGE` | Dois critérios de aceite não podem ser testados |
| 4 | `core/clock.py` ausente | Undo Send e carência de 24 h só se testariam com `sleep` |
| 5 | `imap_client.py` com 58% de cobertura, incluindo o caminho de STARTTLS | Módulo de segurança sem teste no caminho crítico |
| 6 | `docs/progress/PROGRESS.md` está desatualizado e usa numeração de tarefas diferente da do plano | Rastreabilidade requisito → tarefa deixa de ser verificável |
| 7 | Sem integração contínua e sem portão de cobertura | `RNF-MAINT-01` não é aplicado |
| 8 | Nada foi executado em Python 3.11 ou 3.12 | Compatibilidade declarada, não verificada |

## Contribuindo

- **Documentos e comentários explicativos em português; código, identificadores, nomes de arquivo e mensagens de commit em inglês.**
- Cada tarefa segue TDD: escreva o teste que falha, veja-o falhar, implemente o mínimo, veja-o passar, e só então faça o commit.
- Uma tarefa só está concluída com a suíte inteira verde, `ruff` sem avisos e o commit feito.
- Se a implementação revelar que a especificação está errada, **corrija a especificação no mesmo commit**. Código que contradiz a spec sem atualizá-la é dívida criada no mesmo instante.
- Requisito sem critério de aceite é requisito mal escrito: reescreva-o em vez de implementá-lo.

## Licença

MIT — declarada em `pyproject.toml`. O arquivo `LICENSE` ainda não foi adicionado ao repositório.
