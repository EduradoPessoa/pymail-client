# Especificação do PyMail Client

Cliente de e-mail desktop leve, minimalista, multiplataforma (Windows/Linux/macOS), em Python 3.11+ com PySide6. Voltado a resolver os três gargalos históricos de clientes clássicos: **lentidão**, **renderização quebrada** e **rastreadores**.

**Versão do conjunto:** 1.0 · **Data:** 2026-09-25 · **Escopo:** fase 1 especificada em detalhe executável; fase 2 especificada em nível de pontos de extensão.

---

## Ordem de leitura

| # | Documento | O que responde | Para quem |
|---|---|---|---|
| — | `README.md` (este) | Índice, decisões fixadas e status | todos |
| 01 | [`01-requisitos.md`](01-requisitos.md) | O **quê** e o **quanto**: 95 requisitos (81 de fase 1, 14 de fase 2) com critérios de aceite verificáveis e matriz de rastreabilidade | todos |
| 02 | [`02-arquitetura.md`](02-arquitetura.md) | O **como**: camadas, modelo de threads, 6 ADRs, contratos de interface em código, fluxos, riscos | implementadores |
| 03 | [`03-modelo-de-dados.md`](03-modelo-de-dados.md) | Persistência: DDL completo, FTS5, política de cache, migrações e recuperação | implementadores |
| 04 | [`04-ui-ux.md`](04-ui-ux.md) | Design tokens, layout, anatomia dos componentes, atalhos, temas, acessibilidade | quem faz a interface |
| 05 | [`05-seguranca-privacidade.md`](05-seguranca-privacidade.md) | Modelo de ameaças, sanitização, bloqueio de rastreamento, limites honestos | todos (é a proposta de valor) |
| 06 | [`06-estrategia-de-testes.md`](06-estrategia-de-testes.md) | Como cada afirmação é comprovada: testes críticos, dublês, corpus, CI, verificação manual | implementadores |
| — | [`../plans/fase1.md`](../plans/fase1.md) | Execução: 41 tarefas atômicas em TDD, com caminhos e comandos exatos | quem executa |

**Caminho mais curto para entender o projeto:** `README.md` → `01-requisitos.md` §1 e §9 → `02-arquitetura.md` §1 e §3 (ADRs).

---

## Decisões fixadas nesta especificação

Cinco decisões foram tomadas antes da escrita dos requisitos e são **normativas**. Cada uma tem um ADR correspondente em `02-arquitetura.md` §3 com contexto, alternativas rejeitadas e consequências.

| # | Decisão | Justificativa curta | ADR |
|---|---|---|---|
| **D1** | Rede com bibliotecas **síncronas da stdlib** (`imaplib`/`poplib`/`smtplib`) em threads, com **uma conexão dedicada por conta** | Resolve o requisito real ("a UI nunca trava") com o menor risco de integração e sem dependência de terceiros no núcleo. Refinada com afinidade de thread porque `imaplib` **não é thread-safe** — "rodar em thread de fundo" sozinho produziria um bug intermitente e caro | ADR-001 |
| **D2** | **Autenticação plugável**: senha/app password na fase 1, **OAuth2 na fase 2** | Torna a fase 2 aditiva em vez de invasiva. Custo aceito e declarado: **contas Microsoft 365 não conectam na fase 1** | ADR-002 |
| **D3** | **`QWebEngineView`** com JavaScript desabilitado e **interceptor de rede** | Único caminho que renderiza HTML moderno sem quebrar **e** bloqueia rastreamento de verdade (CSS remoto, `@import`, beacons que não são `<img>`). Custo aceito e medido: +150–200 MB no pacote e processos próprios em memória | ADR-003 |
| **D4** | Sanitização com **allowlist sobre parser HTML real** (`nh3` + `tinycss2`), nunca regex | É a funcionalidade central e a de maior risco. `bleach` está sem manutenção desde 2023 e `lxml.html.clean` foi removido | ADR-004 |
| **D5** | Fase 1 = **núcleo vertical usável**; POP3, Snooze, caixa unificada, retenção, OAuth2 e conversas na fase 2 | Cada adiamento é uma funcionalidade horizontalmente separável, com ponto de extensão já reservado no schema e nos contratos | 02 §9 |

### Escopo da fase 1

**Entra:** contas IMAP múltiplas · sincronização por cabeçalhos com corpo sob demanda · leitura sanitizada com rastreamento bloqueado e imagens desligadas por padrão · busca local FTS5 insensível a acentos · composição, resposta e encaminhamento · envio SMTP com **Undo Send** · credenciais no keyring · temas claro/escuro seguindo o sistema · atalhos de teclado *Inbox Zero* · despejo de cache · recuperação de banco corrompido · empacotamento medido.

**Fica para a fase 2:** OAuth2 (Google/Microsoft) · POP3 · Snooze · caixa de entrada unificada · retenção por idade · busca no servidor · painel de conversas · desfazer de arquivamento · gravação de rascunhos no servidor.

**Fora de escopo, nas duas fases:** calendário e contatos · plugins · Exchange ActiveSync/JMAP · mobile/web · regras de servidor · cifragem do banco local · sincronização entre máquinas. Ver `01-requisitos.md` §7.

---

## O que torna esta fase 1 verificável

Duas afirmações sustentam a proposta de valor do produto. Ambas são comprovadas por teste automatizado, não por declaração de intenção:

| Afirmação | Critério | Tarefa |
|---|---|---|
| A thread da interface **nunca** bloqueia por mais de 100 ms, nem durante uma sincronização de 5.000 mensagens | `CA-RNF-PERF-01-1` | `T-39` |
| Renderizar uma mensagem produz **zero** requisições de rede originadas pelo conteúdo do e-mail | `CA-RNF-PRIV-01-1` | `T-07`, `T-22` |

Se o tempo de implementação for curto, corte funcionalidade — **nunca** corte essas duas.

---

## Limitações conhecidas e aceitas

Registradas de propósito, para serem consequências conscientes e não defeitos descobertos em produção. Detalhamento em `01-requisitos.md` §6.

1. **Contas Microsoft 365/Outlook.com não conectam na fase 1** — a autenticação básica em IMAP/SMTP foi descontinuada e OAuth2 é obrigatório (chega na fase 2).
2. **O instalador é grande** (~150–200 MB estimados, a serem medidos em `T-40`), por causa do motor de renderização.
3. **O consumo de memória cresce com o motor de renderização**, medido à parte dos 400 MB de `RNF-PERF-05`.
4. **Sem OpenPGP/S-MIME.**
5. **A detecção de novas mensagens depende do servidor** — sem `IDLE`, a latência é a do intervalo de verificação.

---

## Backlog aberto

Itens registrados durante a especificação, que **não** bloqueiam o início da fase 1 mas precisam de decisão antes de congelar a fase 2. Também em `02-arquitetura.md` §11.

| # | Item | Origem |
|---|---|---|
| **B-01** | Reconfirmar na documentação oficial de Google e Microsoft o estado atual de autenticação básica e app passwords em IMAP/SMTP | A busca web estava indisponível durante a escrita desta spec. **Não congelar a fase 2 sobre uma premissa não reconfirmada** (`05-seguranca-privacidade.md` §12) |
| **B-02** | Substituir as estimativas de tamanho e memória por valores medidos | `T-40`; atualiza `01-requisitos.md` §6 |
| **B-03** | Avaliar se a sanitização sai de `core/security.py` para `core/sanitizer.py` quando o arquivo real existir | `02-arquitetura.md` §2.1 |

---

## Achados da revisão cruzada

Os documentos 04, 05 e 06 auditaram os três primeiros — e encontraram defeitos reais, inclusive contradições que eu havia introduzido. Tudo que era corrigível foi corrigido neste conjunto:

| Achado | Origem | Correção |
|---|---|---|
| Contradição **16 ms × 100 ms** em `RNF-PERF-01` | 06 §12, L-02 | `01-requisitos.md` §8.1 explicita que 16 ms é o orçamento por operação despachada da GUI e 100 ms é o limite observável do teste |
| **~20 requisitos sem critério de aceite**, violando a regra da própria §2 | 04 §L-11, 06 §L-07 | `01-requisitos.md` **§8.1 (nova)** acrescenta critério verificável para todos; as células `—` da matriz passam a apontar para lá |
| `RNF-A11Y-01` sem critério objetivo de contraste | 04 §L-02, 06 §L-18 | `CA-RNF-A11Y-01-1` com limiares calculados (4,5:1 e 3:1) |
| Permissão de `config.toml`: **`0644` em `02` × `0600` em `05`** | 05 §14, item 20 | `02-arquitetura.md` §8.1 adota `0600` e registra a razão (o arquivo contém metadados de comunicação) |
| **Pipeline de sanitização em dois passes**, com espaço de nomes `data-pymail-*` forjável por remetente malicioso | 05 §4 | `02-arquitetura.md` ADR-004 recebe emenda explicando por que o marcador de restauração precisa ser descartado e recriado; `html5lib` entra na tabela de dependências |
| ID inexistente: em `06` o requisito de colapso da barra lateral foi citado com o prefixo errado (`RNF` onde deveria ser `RF`) | verificação por script | Corrigido, e a linha da lacuna L-07 em `06` marcada como **RESOLVIDA** |

**Lacunas em aberto**, registradas mas não corrigidas — decisão de projeto, não erro: 14 itens em `04-ui-ux.md` §10, 21 em `05-seguranca-privacidade.md` §14 e 21 em `06-estrategia-de-testes.md` §12. As mais relevantes para decidir **antes** de implementar: revogação da autorização de imagens (05, item 4), relógio injetável para testar o Undo Send sem `sleep` (06, L-08), *seam* de injeção de falha em `Storage` para provar a atomicidade corpo+índice (06, L-09), e o escopo de rede da autorização por remetente (05, item 5).

---

## Status deste conjunto

| Documento | Status |
|---|---|
| `01-requisitos.md` | Completo — 95 requisitos; matriz de rastreabilidade cobrindo os 81 de fase 1, verificada por script contra o plano (sem lacuna, sem órfão, sem ID duplicado) |
| `02-arquitetura.md` | Completo — 6 ADRs, contratos de interface, modelo de threads, riscos |
| `03-modelo-de-dados.md` | Completo — DDL v1 integral, FTS5, política de cache, migrações |
| `04-ui-ux.md` | Completo — 1.579 linhas; tokens com contraste AA calculado, layout, atalhos com guarda de foco, 14 lacunas registradas |
| `05-seguranca-privacidade.md` | Completo — 1.067 linhas; pipeline de sanitização, matriz do interceptor, limites honestos, 21 lacunas registradas |
| `06-estrategia-de-testes.md` | Completo — 2.879 linhas; os três testes críticos com código, dublês, corpus hostil, workflow de CI, 21 lacunas registradas |
| `../plans/fase1.md` | Completo — 41 tarefas em 6 marcos |
| Código | **Não iniciado** — o prompt mestre descreve a estrutura de diretórios alvo; a implementação segue `../plans/fase1.md` a partir de `T-01` |
