# 04 — UI/UX

**Projeto:** PyMail Client · **Versão desta spec:** 1.0 · **Data:** 2026-09-25
**Documentos correlatos:** `01-requisitos.md` (o quê) · `02-arquitetura.md` (ADRs, threads, contratos) · `03-modelo-de-dados.md` (schema e consultas) · `05-seguranca-privacidade.md` · `06-estrategia-de-testes.md` · `../plans/fase1.md`

**Escopo deste documento:** geometria, tokens, estados, atalhos, fluxos e acessibilidade da camada `ui/`. Não repete ADRs nem o schema; referencia por seção. Todos os números aqui são normativos: quando um valor divergir do código, o código é o defeito.

---

## 1. Princípios de design

Cinco princípios. Cada um existe porque impõe uma consequência concreta e verificável; nenhum é decoração.

### P1 — A interface responde antes de saber a resposta

Toda ação do usuário produz mudança visível **em menos de 100 ms**, mesmo quando o resultado final depende de rede (RNF-USA-02, `02-arquitetura.md` §1.5).

**Consequência prática:** nenhum slot de `ui/` pode aguardar sinal de rede. Arquivar, sinalizar, marcar como lida e enviar alteram o modelo local e desenham o novo estado antes de qualquer chamada de protocolo. Se uma implementação precisa esperar para saber o que desenhar, o desenho está errado. A única exceção é a abertura de uma mensagem sem corpo em cache, e mesmo ela tem estado de carregamento imediato (§6.2).

### P2 — O teclado é a interface primária; o mouse é o atalho

Todo fluxo completo — ler, arquivar, buscar, responder, enviar, desfazer — é executável sem mouse (RF-UI-03, critério de conclusão 4 de `01-requisitos.md` §9).

**Consequência prática:** nenhum controle existe sem atalho ou alcançável por `Tab`; nenhuma informação existe apenas em `hover` ou em `tooltip` (o tooltip é redundância, nunca a única fonte); nenhum diálogo modal bloqueia o fluxo principal — `QMessageBox` só aparece para operação destrutiva sem desfazer (RNF-USA-01).

### P3 — A densidade de informação é decisão do usuário, não do designer

Duas densidades exatas (confortável: 72 px por item; compacta: 48 px por item), alternáveis sem recarregar a lista (RF-UI-09).

**Consequência prática:** o delegate não pode ter altura implícita. `sizeHint()` devolve valor constante por densidade, `QListView.setUniformItemSizes(True)` é obrigatório, e trocar de densidade chama `scheduleDelayedItemsLayout()` no viewport — nunca `setModel()` de novo.

### P4 — Nada de cromo; a mensagem ocupa a tela

Sem barra de ferramentas com ícones decorativos, sem avatares, sem sombras em repouso, sem gradientes, sem animação que não comunique estado.

**Consequência prática:** um único nível de elevação real (`surface-raised` sobre `surface`) e uma única sombra no sistema (o `Toast`, §4.6). Barras de ação aparecem somente quando há contexto que as justifique (seleção múltipla, anexo grande, assunto vazio) e desaparecem quando o contexto some.

### P5 — Privacidade é visível, não silenciosa

Bloqueio de imagem e remoção de rastreador são afirmados na tela, com números (RF-RD-03, RF-RD-04, RNF-PRIV-03).

**Consequência prática:** o `ReaderPane` mostra quantos pixels de rastreamento foram removidos naquela mensagem e mantém o banner de imagens bloqueadas visível enquanto houver recurso remoto suprimido. Um produto que bloqueia em silêncio não é verificável pelo usuário — e CA-RF-RD-04-1 só é crível se a interface disser o que fez.

### P6 — Nenhuma área em branco sem explicação

Todo widget de conteúdo tem quatro estados implementados: vazio, carregando, populado, erro (RF-UI-07).

**Consequência prática:** o estado é propriedade explícita do componente (`MessageListState`), não algo inferido de `model.rowCount() == 0`. Uma lista vazia porque a pasta está vazia, porque a busca não achou nada e porque o servidor falhou são três telas distintas, com textos e ações distintas.

---

## 2. Design tokens

Fonte única de verdade: dicionários `LIGHT` e `DARK` em `ui/styles.py`, mais `assets/themes/light.qss` e `assets/themes/dark.qss` como **modelos** com marcadores `{token}` resolvidos por `str.format_map(_Tokens(**tokens))` sobre um `dict` que levanta `KeyError` em token inexistente. Isso evita divergência entre o QSS e o `QColor` usado pelo delegate, que pinta em código.

`ui/styles.py` expõe:

```python
LIGHT: dict[str, str]           # hex, ex.: "surface": "#FFFFFF"
DARK:  dict[str, str]
def tokens(scheme: Qt.ColorScheme) -> dict[str, str]: ...
def build_qss(scheme: Qt.ColorScheme) -> str: ...
def build_palette(scheme: Qt.ColorScheme) -> QPalette: ...
def icon(name: str, size: int, token: str, dpr: float) -> QIcon: ...
```

### 2.1 Escala de espaçamento

Base 4 px. Toda margem, padding e gap do aplicativo é um destes valores — nenhum número solto.

| Token | px | Uso típico |
|---|---|---|
| `space-0h` | 2 | Gap entre badge e texto; offset do anel de foco |
| `space-1` | 4 | Gap entre botões de ícone; padding interno de chip |
| `space-2` | 8 | Padding horizontal de linha de lista; gap entre indicadores |
| `space-3` | 12 | Padding esquerdo/direito do item de lista; padding de botão |
| `space-4` | 16 | Padding de painel; gap entre colunas de formulário |
| `space-5` | 20 | Margem de estado vazio |
| `space-6` | 24 | Padding de diálogo; recuo de pasta filha na sidebar |
| `space-8` | 32 | Separação de blocos em estados vazios |
| `space-10` | 40 | Altura de cabeçalho de seção |
| `space-12` | 48 | Altura do trilho colapsado da sidebar |

### 2.2 Escala tipográfica

Família por plataforma, resolvida em `ui/styles.py:font_stack()` e aplicada como `font-family` no QSS raiz. A primeira existente vence; a última é o fallback garantido.

| Token | pt | px @96dpi | Peso | Altura de linha | Uso |
|---|---|---|---|---|---|
| `font-size-xs` | 8 pt | 10,7 | 400 | 14 px | badge de contagem, cabeçalho de agrupamento por data |
| `font-size-sm` | 9 pt | 12,0 | 400 | 16 px | trecho de pré-visualização, data, linha de destinatários, nome de pasta |
| `font-size-md` | 10 pt | 13,3 | 400 | 18 px | remetente na lista, corpo do leitor, campos do compositor |
| `font-size-lg` | 11 pt | 14,7 | 600 | 20 px | assunto na lista, título do cabeçalho do leitor |
| `font-size-xl` | 13 pt | 17,3 | 400 | 24 px | título de estado vazio |
| `font-size-2xl` | 16 pt | 21,3 | 600 | 28 px | título de diálogo modal |
| `font-size-mono` | 9 pt | 12,0 | 400 | 16 px | cabeçalhos brutos (fonte monoespaçada) |

| Papel | Windows | macOS | Linux (ordem de tentativa) |
|---|---|---|---|
| UI (`font-sans`) | `Segoe UI Variable Text`, `Segoe UI` | `SF Pro Text`, `.AppleSystemUIFont` | `Inter`, `Cantarell`, `Noto Sans`, `DejaVu Sans` |
| Mono (`font-mono`) | `Cascadia Mono`, `Consolas` | `SF Mono`, `Menlo` | `JetBrains Mono`, `Noto Sans Mono`, `DejaVu Sans Mono` |

Pesos usados: `400` normal, `600` semibold, `700` negrito. **Nenhum outro peso** — `500` não é usado, porque em `Segoe UI Variable` ele é indistinguível de `400` em tamanho pequeno e cria inconsistência entre plataformas.

Regras de peso, sem exceção:

- Item **não lido**: assunto em `600` + remetente em `600`. Item lido: ambos em `400`.
- Remetente desconhecido (sem `from_name`): exibe `from_addr` com o mesmo estilo do nome.
- Assunto vazio: exibe `(sem assunto)` em `text-muted`, itálico desabilitado, mesmo tamanho.
- Nada no aplicativo usa texto abaixo de 8 pt, em nenhuma densidade.

### 2.3 Raios, durações e elevação

| Token | Valor | Uso |
|---|---|---|
| `radius-none` | 0 | linhas de lista, divisores |
| `radius-sm` | 3 px | chip, item de menu, badge |
| `radius-md` | 5 px | campo de entrada, botão, cartão de toast |
| `radius-lg` | 8 px | diálogo, painel de estado |
| `radius-pill` | 999 px | pílula de destinatário, badge de contagem |

| Token | ms | Uso |
|---|---|---|
| `dur-instant` | 0 | mudança de estado de item de lista (hover, seleção, lido) |
| `dur-fast` | 80 | hover de botão, cor de fundo de linha |
| `dur-base` | 120 | aparição de barra de ações, crossfade de banner |
| `dur-slow` | 180 | colapso/expansão da sidebar (`QPropertyAnimation` em `maximumWidth`) |
| `dur-toast-in` | 220 | entrada do toast (opacidade 0→1 + `pos` +12 px) |
| `dur-toast-out` | 160 | saída do toast |
| `dur-spin` | 1200 | uma volta completa do indicador de sincronização |
| `delay-spinner` | 150 | atraso antes de mostrar qualquer spinner (evita piscada) |
| `debounce-search` | 250 | debounce da busca incremental (RF-SRCH-02) |
| `delay-mark-read` | 1500 | atraso de marcar como lida (RF-RD-09) |
| `send-window` | 10000 | janela padrão do Undo Send, 5000–30000 (RF-SND-03) |

**`delay-spinner` é obrigatório:** nenhum indicador de carregamento aparece antes de 150 ms. Operações que terminam antes disso não mostram spinner algum.

| Elevação | Valor | Aplicação |
|---|---|---|
| `elev-0` | sem sombra | tudo, exceto toast e diálogo |
| `elev-1` | `QGraphicsDropShadowEffect(blurRadius=24, offset=(0,4), color=rgba(0,0,0,0.18))` | Toast, menu flutuante |
| `elev-2` | `blurRadius=32, offset=(0,8), color=rgba(0,0,0,0.28)` | `QDialog` modal |

### 2.4 Paleta semântica

Tema claro (`LIGHT`):

| Token | Hex | Uso |
|---|---|---|
| `surface` | `#FFFFFF` | fundo da lista, do leitor, da sidebar; fundo base de `QWidget` |
| `surface-raised` | `#F6F7F9` | cabeçalhos de coluna, barras de ação, chips, toast, menus |
| `surface-sunken` | `#EDEFF3` | poço do campo de busca, fundo atrás de conteúdo ainda não carregado |
| `surface-unread` | `#EEF3FD` | fundo de item não lido |
| `surface-hover` | `#F1F3F7` | fundo de item sob o cursor |
| `surface-selected` | `#1F5FD0` | fundo do item selecionado (= `accent`) |
| `text-primary` | `#16181D` | texto principal |
| `text-muted` | `#5B6270` | texto secundário, data, trecho, rótulo |
| `text-disabled` | `#8B93A1` | texto de controle desabilitado |
| `text-on-accent` | `#FFFFFF` | texto sobre `accent` |
| `border-subtle` | `#DDE1E8` | divisores, contorno de cartão |
| `border-strong` | `#767E8C` | contorno de campo de entrada e de botão secundário |
| `accent` | `#1F5FD0` | ação primária, seleção, foco, link |
| `accent-hover` | `#1A52B8` | `accent` sob cursor |
| `accent-pressed` | `#17489F` | `accent` pressionado |
| `accent-subtle` | `#E4EDFC` | fundo de chip de filtro ativo |
| `focus-ring` | `#1F5FD0` | anel de foco (2 px) |
| `danger` | `#B3261E` | erro, exclusão, falha de envio |
| `danger-subtle` | `#FCEBEA` | fundo de faixa de erro |
| `warning` | `#8A5300` | aviso, anexo grande, offline |
| `warning-subtle` | `#FDF3E2` | fundo de faixa de aviso |
| `success` | `#1B6B3A` | confirmação de envio concluído |
| `unread-indicator` | `#1F5FD0` | barra de 3 px do item não lido |
| `flag-indicator` | `#8A5300` | estrela de sinalizado |
| `scrollbar-handle` | `#7C8595` | polegar de barra de rolagem |
| `tooltip-bg` | `#16181D` | fundo de `QToolTip` |
| `tooltip-text` | `#FFFFFF` | texto de `QToolTip` |

Tema escuro (`DARK`):

| Token | Hex | Uso |
|---|---|---|
| `surface` | `#16181C` | base |
| `surface-raised` | `#1E2126` | elevação 1 |
| `surface-sunken` | `#101215` | poço |
| `surface-unread` | `#1B2432` | item não lido |
| `surface-hover` | `#23272E` | item sob cursor |
| `surface-selected` | `#6EA8FE` | item selecionado (= `accent`) |
| `text-primary` | `#E8EAED` | texto principal |
| `text-muted` | `#9AA1AC` | texto secundário |
| `text-disabled` | `#6B7280` | controle desabilitado |
| `text-on-accent` | `#0B0E12` | texto sobre `accent` |
| `border-subtle` | `#2E3238` | divisores |
| `border-strong` | `#8B93A1` | contorno de campo |
| `accent` | `#6EA8FE` | ação primária, foco |
| `accent-hover` | `#86B7FE` | hover |
| `accent-pressed` | `#A0C8FF` | pressionado |
| `accent-subtle` | `#1C2A42` | chip de filtro ativo |
| `focus-ring` | `#6EA8FE` | anel de foco |
| `danger` | `#FFB4AB` | erro |
| `danger-subtle` | `#3A1D1B` | faixa de erro |
| `warning` | `#F5C77E` | aviso |
| `warning-subtle` | `#33280F` | faixa de aviso |
| `success` | `#7FD79B` | confirmação |
| `unread-indicator` | `#6EA8FE` | barra de não lido |
| `flag-indicator` | `#F5C77E` | estrela |
| `scrollbar-handle` | `#6B7280` | polegar |
| `tooltip-bg` | `#E8EAED` | `QToolTip` |
| `tooltip-text` | `#16181C` | texto de `QToolTip` |

### 2.5 Contraste verificado (WCAG 2.1)

Razões calculadas pela fórmula de luminância relativa da WCAG 2.1 sobre os valores hexadecimais acima. **Texto normal exige ≥ 4,5:1; componente de interface não textual exige ≥ 3:1.** Todos os pares abaixo foram medidos, não estimados.

Tema claro:

| Primeiro plano | Fundo | Razão | Exigido | Resultado |
|---|---|---|---|---|
| `text-primary` `#16181D` | `surface` `#FFFFFF` | 17,8:1 | 4,5:1 | PASSA |
| `text-primary` `#16181D` | `surface-raised` `#F6F7F9` | 16,6:1 | 4,5:1 | PASSA |
| `text-primary` `#16181D` | `surface-hover` `#F1F3F7` | 16,7:1 | 4,5:1 | PASSA |
| `text-primary` `#16181D` | `surface-unread` `#EEF3FD` | 16,0:1 | 4,5:1 | PASSA |
| `text-muted` `#5B6270` | `surface` `#FFFFFF` | 6,1:1 | 4,5:1 | PASSA |
| `text-muted` `#5B6270` | `surface-raised` `#F6F7F9` | 5,7:1 | 4,5:1 | PASSA |
| `text-muted` `#5B6270` | `surface-hover` `#F1F3F7` | 5,5:1 | 4,5:1 | PASSA |
| `text-muted` `#5B6270` | `surface-unread` `#EEF3FD` | 5,5:1 | 4,5:1 | PASSA |
| `accent` `#1F5FD0` | `surface` `#FFFFFF` | 5,8:1 | 4,5:1 | PASSA |
| `accent` `#1F5FD0` | `surface-unread` `#EEF3FD` | 5,2:1 | 4,5:1 | PASSA |
| `danger` `#B3261E` | `surface` `#FFFFFF` | 6,5:1 | 4,5:1 | PASSA |
| `warning` `#8A5300` | `surface` `#FFFFFF` | 6,3:1 | 4,5:1 | PASSA |
| `success` `#1B6B3A` | `surface` `#FFFFFF` | 6,4:1 | 4,5:1 | PASSA |
| `text-on-accent` `#FFFFFF` | `surface-selected` `#1F5FD0` | 5,8:1 | 4,5:1 | PASSA |
| `tooltip-text` `#FFFFFF` | `tooltip-bg` `#16181D` | 17,8:1 | 4,5:1 | PASSA |
| `border-strong` `#767E8C` | `surface` `#FFFFFF` | 4,1:1 | 3:1 | PASSA |
| `scrollbar-handle` `#7C8595` | `surface-raised` `#F6F7F9` | 3,5:1 | 3:1 | PASSA |
| `unread-indicator` `#1F5FD0` | `surface` `#FFFFFF` | 5,8:1 | 3:1 | PASSA |

Tema escuro:

| Primeiro plano | Fundo | Razão | Exigido | Resultado |
|---|---|---|---|---|
| `text-primary` `#E8EAED` | `surface` `#16181C` | 14,8:1 | 4,5:1 | PASSA |
| `text-primary` `#E8EAED` | `surface-raised` `#1E2126` | 13,4:1 | 4,5:1 | PASSA |
| `text-primary` `#E8EAED` | `surface-hover` `#23272E` | 12,4:1 | 4,5:1 | PASSA |
| `text-primary` `#E8EAED` | `surface-unread` `#1B2432` | 13,0:1 | 4,5:1 | PASSA |
| `text-muted` `#9AA1AC` | `surface` `#16181C` | 6,8:1 | 4,5:1 | PASSA |
| `text-muted` `#9AA1AC` | `surface-raised` `#1E2126` | 6,2:1 | 4,5:1 | PASSA |
| `text-muted` `#9AA1AC` | `surface-hover` `#23272E` | 5,8:1 | 4,5:1 | PASSA |
| `text-muted` `#9AA1AC` | `surface-unread` `#1B2432` | 6,0:1 | 4,5:1 | PASSA |
| `accent` `#6EA8FE` | `surface` `#16181C` | 7,4:1 | 4,5:1 | PASSA |
| `accent` `#6EA8FE` | `surface-unread` `#1B2432` | 6,5:1 | 4,5:1 | PASSA |
| `danger` `#FFB4AB` | `surface` `#16181C` | 10,5:1 | 4,5:1 | PASSA |
| `warning` `#F5C77E` | `surface` `#16181C` | 11,3:1 | 4,5:1 | PASSA |
| `success` `#7FD79B` | `surface` `#16181C` | 10,9:1 | 4,5:1 | PASSA |
| `text-on-accent` `#0B0E12` | `surface-selected` `#6EA8FE` | 8,0:1 | 4,5:1 | PASSA |
| `tooltip-text` `#16181C` | `tooltip-bg` `#E8EAED` | 14,8:1 | 4,5:1 | PASSA |
| `border-strong` `#8B93A1` | `surface` `#16181C` | 5,7:1 | 3:1 | PASSA |
| `scrollbar-handle` `#6B7280` | `surface-raised` `#1E2126` | 3,3:1 | 3:1 | PASSA |
| `unread-indicator` `#6EA8FE` | `surface` `#16181C` | 7,4:1 | 3:1 | PASSA |

Três exceções declaradas, ambas normativas:

1. **`text-disabled` não é exigido a atingir 4,5:1.** A WCAG 2.1 isenta controles inativos (1.4.3). Os valores escolhidos atingem 3,1:1 (claro) e 3,2:1 (escuro) por escolha, para que o texto desabilitado continue legível.
2. **`border-subtle` não atinge 3:1 e não precisa atingir.** Ele desenha divisores decorativos, não o limite de um controle. Todo limite de controle usa `border-strong`.
3. **No item selecionado, todo o texto usa `text-on-accent`.** `text-muted` sobre `surface-selected` dá 1,5:1 no tema claro — por isso o delegate, ao pintar a linha selecionada, troca *todos* os papéis de cor do item para `text-on-accent`, inclusive data, trecho e indicadores. Indicadores que ficariam invisíveis (`unread-indicator` sobre `accent`) são simplesmente omitidos na linha selecionada.

---

## 3. Layout de três colunas

### 3.1 Estado normal

Janela padrão `1280×800`, mínima `720×480`. Divisores: `QSplitter::handle` com largura 4 px (área de arrasto), pintado como linha de 1 px `border-subtle`, cursor `Qt.SplitHCursor`.

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ QMainWindow  1280 × 800                                                                   │
├─────────────────┬──┬────────────────────────────────┬──┬──────────────────────────────────┤
│    Sidebar      │  │      MessageList column        │  │          ReaderPane              │
│    248 px       │4 │           400 px               │4 │           624 px                 │
│                 │px│                                │px│                                  │
│ PyMail    ✎  ◀  │  │ Caixa de entrada    12 não lid.│  │ Assunto: Proposta comercial      │
│ ─────────────── │  │ 🔍  ⟳  ⋯                       │  │ Maria Silva <maria@exemplo.com>  │
│ ▾ ◉ joao@ex.com │  │ ┌────────────────────────────┐ │  │ para mim ▾      hoje, 14:32      │
│    ⟳ 3          │  │ │▌Maria Silva   14:32  ★ 📎  │ │  │ ──────────────────────────────── │
│    ▸ Caixa (12) │  │ │ Re: Proposta comercial      │ │  │ [Responder] [Todos] [Encam.] [⋯] │
│      Enviadas   │  │ │ Segue a proposta ajustada…  │ │  │ ┌──────────────────────────────┐ │
│      Rascunhos 2│  │ ├────────────────────────────┤ │  │ │ ⚠ Imagens remotas bloqueadas │ │
│      Arquivo    │  │ │  João Souza    13:05     📎 │ │  │ │  [Carregar deste remetente]  │ │
│      Lixeira    │  │ │  Orçamento 2027            │ │  │ └──────────────────────────────┘ │
│ ▾ ◉ ana@ex.com  │  │ │  Bom dia, segue em anexo…  │ │  │ ▸ 2 pixels de rastreamento remov.│
│    ▸ Caixa (4)  │  │ ├────────────────────────────┤ │  │ ┌──────────────────────────────┐ │
│      Enviadas   │  │ │  ⋮ (continua)              │ │  │ │                              │ │
│                 │  │ │                            │ │  │ │   QWebEngineView (JS off)    │ │
│                 │  │ │  ── Carregar mais (200) ── │ │  │ │                              │ │
└─────────────────┴──┴────────────────────────────────┴──┴──────────────────────────────────┘
```

### 3.2 Sidebar colapsada

Estado persistido (RF-UI-02). Colapsar e expandir animam `maximumWidth` de 248→48 em `dur-slow` (180 ms), `QEasingCurve.OutCubic`. O conteúdo interno não é destruído, apenas oculto com `setVisible(False)`.

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ QMainWindow  1280 × 800 — sidebar em trilho (48 px)                                       │
├────┬──┬──────────────────────────────────┬──┬─────────────────────────────────────────────┤
│ 48 │4 │             400 px               │4 │                 824 px                      │
│    │px│                                  │px│                                             │
│ ▶  │  │ Caixa de entrada      12 não lid.│  │ Assunto: Proposta comercial                 │
│    │  │ 🔍  ⟳  ⋯                         │  │ Maria Silva <maria@exemplo.com>             │
│ ◉  │  │ ┌──────────────────────────────┐ │  │ ─────────────────────────────────────────── │
│ •3 │  │ │▌Maria Silva  14:32  ★ 📎     │ │  │ [Responder] [Todos] [Encam.] [⋯]            │
│    │  │ │ Re: Proposta comercial        │ │  │ ⚠ Imagens remotas bloqueadas                │
│ ✎  │  │ │ Segue a proposta ajustada…    │ │  │  [Carregar deste remetente]                 │
│    │  │ ├──────────────────────────────┤ │  │ ┌─────────────────────────────────────────┐ │
│ ◉  │  │ │  João Souza   13:05       📎  │ │  │ │        QWebEngineView (JS off)          │ │
│ •4 │  │ │  Orçamento 2027               │ │  │ │                                         │ │
│    │  │ │  Bom dia, segue em anexo…     │ │  │ └─────────────────────────────────────────┘ │
│ ◀  │  │ │                               │ │  │                                             │
└────┴──┴──────────────────────────────────┴──┴─────────────────────────────────────────────┘
```

Conteúdo do trilho, de cima para baixo, com 4 px de gap:

| Ordem | Widget | Dimensão | Comportamento |
|---|---|---|---|
| 1 | `btnRailExpand` (`QToolButton`) | 32×32, ícone 16 | Expande a sidebar. Tooltip "Expandir barra lateral (Ctrl+\\)" |
| 2 | `btnRailCompose` | 32×32, ícone 16 | Equivalente a `C` |
| 3 | `railAccountButton[account_id]` — um por conta | 32×32, ícone 16 + badge | Clique abre `QMenu` com as pastas daquela conta (linhas de 28 px, badge de não lidos à direita). Foco por teclado: `Tab` percorre os botões; `Enter`/`Espaço` abre o menu; setas navegam; `Esc` fecha e devolve o foco ao botão |
| 4 | `railSpacer` | elástico | — |
| 5 | `btnRailCollapse` | 32×32 | Alterna para expandida |

Badge do botão de conta: círculo `radius-pill` de 14 px de diâmetro mínimo, fundo `accent`, texto `text-on-accent` em `font-size-xs`, posicionado no canto inferior direito do botão com 1 px de deslocamento para fora. Mostra a soma de não lidos da conta; oculto quando 0.

### 3.3 Larguras, mínimos e máximos

| Região | Padrão | Mínimo | Máximo | Como é ajustada |
|---|---|---|---|---|
| `Sidebar` expandida | 248 px | 200 px | 320 px | `QSplitter` (arrasto ou `Ctrl+\\` alterna colapsada) |
| `Sidebar` colapsada | 48 px | 48 px | 48 px | Fixo. Sem arrasto |
| Divisor 1 | 4 px | 4 px | 4 px | Fixo |
| `MessageList` | 400 px | 320 px | 640 px | `QSplitter` |
| Divisor 2 | 4 px | 4 px | 4 px | Fixo |
| `ReaderPane` | resto | 460 px | sem máximo | Consequência dos demais |
| Janela | 1280×800 | 720×480 | 2× `availableGeometry` | `QMainWindow.setMinimumSize(720, 480)` |

`setStretchFactor`: sidebar 0, lista 0, leitor 1. Ao redimensionar a janela para mais, **todo** o crescimento vai para o leitor. Ao encolher, a lista cede primeiro (até seu mínimo), depois o leitor (até o seu).

### 3.4 Comportamento responsivo

Dois pontos de quebra, avaliados em `resizeEvent` do `QMainWindow` com histerese de 16 px para evitar oscilação em arrasto lento.

| Faixa de largura da janela | Comportamento |
|---|---|
| ≥ 1024 px | Três colunas, conforme §3.1. Barra lateral no estado persistido pelo usuário |
| 860–1023 px | **A barra lateral colapsa automaticamente** para o trilho de 48 px. O valor persistido do usuário **não** é alterado: ao voltar acima de 1024 px, a sidebar retorna ao estado que o usuário escolheu. Se o usuário expandir manualmente dentro desta faixa, a escolha manual vence até o próximo cruzamento de ponto de quebra |
| 720–859 px | Barra lateral em trilho (48 px) **e o leitor deixa de ser coluna**: `ReaderPane` passa a ser um painel sobreposto (`raise_()`, `setGeometry` ancorado à direita) com largura `min(560, largura_janela - 48 - 4 - 320)` e altura total da janela. A lista ocupa todo o resto. O painel sobreposto recebe uma sombra `elev-2` e uma faixa de cabeçalho de 32 px com botão "Voltar para a lista" (ícone `chevron-left`) e o assunto elidido |

**A sidebar nunca colapsa automaticamente por causa da janela estreita quando já está colapsada pelo usuário** — o gatilho é a largura, não a repetição do evento.

Transição entre faixas:

- Lista → leitor sobreposto: entrada com `dur-base` (120 ms), opacidade 0→1 e deslocamento de +24 px à direita.
- Leitor sobreposto → lista: saída com `dur-base`, opacidade 1→0 e −24 px.
- Ao entrar na faixa 720–859, se havia uma mensagem aberta, o painel sobreposto **abre já visível** com a mesma mensagem — não se perde o contexto de leitura.

### 3.5 Persistência de geometria e estado

Arquivo: `config.toml`, seção `[ui]` (RF-SET-01, `02-arquitetura.md` §8.1). **Não se usa `QMainWindow.saveState()`**: o blob binário do Qt não é inspecionável, quebra silenciosamente entre versões de Qt e mistura estado de barras de ferramentas que este aplicativo não possui.

```toml
[ui]
theme = "system"              # system | light | dark
density = "comfortable"       # comfortable | compact
sidebar_collapsed = false
sidebar_width = 248
list_width = 400
window_geometry = [120, 80, 1280, 800]   # x, y, w, h em pixels lógicos
window_maximized = false
window_screen = "\\\\.\\DISPLAY1"        # nome do monitor no momento em que foi salvo
reader_zoom_percent = 100
reader_plain_text_mode = false
search_bar_visible = false
last_account_id = 1
last_folder_id = 4
```

Gravação: em `closeEvent`, de forma síncrona (é um arquivo de poucas centenas de bytes, não viola RNF-PERF-01). **Não** se grava a cada `resizeEvent` — gravar geometria a cada pixel arrastado é I/O na thread da GUI, exatamente o que ADR-001/§4 proíbem. `resizeEvent` apenas atualiza atributos em memória.

Restauração, na ordem:

1. Ler `config.toml`. Valores ausentes ou inválidos caem no padrão, com registro em log de nível `debug` — nunca exceção.
2. Ler geometria. Aplicar `resize()` antes de `show()`, para não haver um frame na posição errada.
3. Se `window_maximized = true`, chamar `showMaximized()`.
4. Restaurar `sidebar_collapsed`, `sidebar_width`, `list_width` **antes** de criar os widgets filhos, passando-os ao construtor do layout.
5. Restaurar `last_account_id`/`last_folder_id`; se a pasta não existir mais no banco, cair na caixa de entrada da primeira conta habilitada.

### 3.6 Múltiplos monitores

Regra de visibilidade: a geometria restaurada é aceita somente se a interseção com `QGuiApplication.screens()[i].availableGeometry()` for de **pelo menos 200 px de largura e 100 px de altura** — ou seja, a barra de título permanece alcançável.

```python
def visible_enough(geo: QRect) -> bool:
    for screen in QGuiApplication.screens():
        inter = screen.availableGeometry().intersected(geo)
        if inter.width() >= 200 and inter.height() >= 100:
            return True
    return False
```

Se a checagem falhar (monitor desconectado, resolução reduzida): centralizar na tela primária com `1280×800`, sem maximizar, e registrar o evento em log. Nunca abrir a janela fora da área visível.

Outras regras:

- A geometria é gravada e restaurada em **pixels lógicos** (`QWidget.geometry()`, que já é independente de DPI). Não se converte nem se reescala ao restaurar em um monitor com `devicePixelRatio` diferente: a janela mantém o mesmo tamanho lógico, que é o comportamento esperado em HiDPI.
- Se `QWindow.screenChanged` disparar durante a sessão (usuário arrastou a janela para outro monitor), nada é reposicionado; só se atualiza `window_screen` no fechamento.
- Não há suporte a "lembrar geometria por monitor". A janela tem uma geometria, gravada por último uso.
- O leitor sobreposto da faixa estreita (§3.4) é posicionado relativo à janela, não à tela — comportamento idêntico em qualquer monitor.

---

## 4. Anatomia dos componentes

### 4.1 `Sidebar`

Arquivo: `ui/components/sidebar.py`. Classes: `Sidebar(QWidget)`, `SidebarDelegate(QStyledItemDelegate)`.

```text
┌─ Sidebar (248 × 800) ──────────────────┐
│ PyMail              ✎      ◀           │  40 px  header
│ ────────────────────────────────────── │
│ ▾ ◉ joao@exemplo.com          (3)  ⟳   │  32 px  nó de conta
│    ▸ Caixa de entrada         (12)     │  28 px  pasta
│      Enviadas                          │  28 px
│      Rascunhos                  (2)    │  28 px
│      Arquivo                           │  28 px
│      Lixeira                           │  28 px
│ ▾ ◉ ana@exemplo.com           (4)  ⚠   │  32 px  conta com erro
│    ▸ Caixa de entrada          (4)     │  28 px
└────────────────────────────────────────┘
   ↑                    ↑
   16 px                badge à direita, 12 px da borda
```

| Zona | Widget | Altura | Detalhe |
|---|---|---|---|
| Header | `QLabel` "PyMail" + `QToolButton` ×2 | 40 px | Rótulo em `font-size-sm`, `text-muted`, caixa alta, `letter-spacing: 0.5px`. `btnCompose` e `btnCollapse` com 24×24, ícone 16 |
| Árvore | `QTreeView` (`sidebarTree`) | resto | Uma raiz por conta, filhos = pastas. `setUniformRowHeights(True)`, `setHeaderHidden(True)`, `setIndentation(20)`, `setExpandsOnDoubleClick(False)`, `setRootIsDecorated(True)`, `verticalScrollMode(ScrollPerPixel)` |
| Rodapé | `QLabel` de armazenamento | 24 px | "Cache: 312 MB de 500 MB" em `font-size-xs`, `text-muted`; clicável, abre Configurações → Armazenamento. Oculto quando o cache usa menos de 80 % do limite |

Colunas da linha (`SidebarDelegate.paint`, uma única coluna com layout interno):

| Posição | Conteúdo | Fonte | Cor |
|---|---|---|---|
| x = 0–16 | Chevron de expansão (só em nós de conta) / vazio | — | `text-muted` |
| x = 18–34 | Ícone de conta ou de pasta, 16×16 | — | `text-muted`; `accent` quando a pasta está selecionada |
| x = 38 → `w-56` | Nome (display name da conta, ou `display_name` da pasta) | `font-size-sm` | `text-primary`; `600` quando selecionada |
| x = 38 → `w-56` | Contador de não lidos se for filho | `font-size-sm` | `accent` |
| `w-52` → `w-40` | Badge de não lidos: pílula de altura 16 px, largura mínima 20 px | `font-size-xs` | fundo `accent`, texto `text-on-accent`; oculto quando 0 |
| `w-34` → `w-20` | Indicador de sincronização, 12×12 | — | ver tabela abaixo |

Indicador de sincronização — estados, vindos de `AccountWorker.state_changed(account_id, str)`:

| Estado | Ícone | Cor | Comportamento |
|---|---|---|---|
| `idle` | nenhum | — | Espaço reservado, nada desenhado |
| `syncing` | `sync.svg` | `accent` | `QTimer` de 16 ms rotaciona o `QTransform` 360° em `dur-spin` (1200 ms), linear |
| `offline` | `offline.svg` | `warning` | Tooltip "Sem conexão — nova tentativa em N s" |
| `error` | `sync-error.svg` | `danger` | Tooltip com a mensagem da `MailError` |
| `paused` (credencial inválida) | `alert-triangle.svg` | `danger` | Tooltip "Credencial recusada — clique para reautenticar". Clique emite `reauth_requested(account_id)` |

Estados da `Sidebar` como um todo:

| Estado | Aparência |
|---|---|
| Carregando pastas | Três linhas esqueleto de 28 px com 60 % de opacidade, sem texto, por 300 ms no máximo antes de dados reais ou erro |
| Populada | Conforme acima |
| Vazia (nenhuma conta) | Bloco centralizado: ícone `account.svg` 32 px, "Nenhuma conta configurada" (`font-size-md`, `600`), "Adicione uma conta para começar." (`font-size-sm`, `text-muted`), botão primário "Adicionar conta" (`RF-ACC-01`) |
| Erro de carregamento | Faixa `warning-subtle` de 40 px no topo da sidebar com o texto do erro e botão "Tentar novamente" |
| Offline global | Cada conta mostra `offline.svg`. A sidebar **não** esconde pastas já conhecidas: cache local é o comportamento correto offline |

Estados de linha: `normal`, `hover` (fundo `surface-hover`, `dur-fast`), `selected` (fundo `surface-selected`, texto e ícone em `text-on-accent`, peso `600`), `focused` (anel de 2 px `focus-ring` desenhado pelo delegate, inset 1 px, raio `radius-sm`), `dropTarget` (linha de 2 px `accent` no topo ou base do item, durante arrasto de mensagem sobre uma pasta — `[F2]`, depende de RF-ORG-07 estar implementado; na fase 1 o arrasto de mensagem sobre pasta não está habilitado e **nenhum** feedback de `dropTarget` é exibido).

Colapso: `btnCollapse` (24×24, ícone `sidebar-collapse.svg`) e `Ctrl+\\`. O botão alterna ícone para `sidebar-expand.svg` no trilho.

### 4.2 `MessageList`

Arquivo: `ui/components/message_list.py`. Classes: `MessageListView(QListView)`, `MessageItemDelegate(QStyledItemDelegate)`, `MessageListModel(QAbstractListModel)`, `MessageListHeader(QWidget)`, `SelectionActionBar(QWidget)`, `MessageListState(QWidget)`.

#### 4.2.1 Coluna da lista

```text
┌─ coluna da lista (400 px) ───────────────────────┐
│ Caixa de entrada                 🔍  ⟳  ⋯        │  40 px  header
│ 12 não lidas · 1.482 mensagens                   │  (linha 2, só se houver contagem)
├──────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────┐ │  40 px  barra de busca (se visível)
│ │ 🔍  buscar                          ( ✕ )    │ │
│ └──────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────┤
│ 3 selecionadas   Arquivar Lixeira Lida Sinalizar✕│  40 px  barra de ações (se seleção múltipla)
├──────────────────────────────────────────────────┤
│ ▌Maria Silva                     14:32   ★  📎   │  72 px  item confortável (não lido)
│   Re: Proposta comercial                         │
│   Segue a proposta ajustada conforme convers…    │
├──────────────────────────────────────────────────┤
│   João Souza                     13:05       📎   │  72 px  item lido
│   Orçamento 2027                                 │
│   Bom dia, segue em anexo a planilha revisada…   │
├──────────────────────────────────────────────────┤
│              ── Carregar mais (200) ──           │  36 px  rodapé de paginação
└──────────────────────────────────────────────────┘
```

Header: `QLabel` do nome da pasta em `font-size-md`/`600`; à direita três `QToolButton` de 24×24 (`search.svg`, `refresh.svg`, `more-horizontal.svg`), gap 4 px. A segunda linha (contagens) usa `font-size-sm`/`text-muted` e só existe quando há ao menos uma contagem conhecida.

#### 4.2.2 Anatomia do item — densidade confortável (72 px)

Altura fixa de 72 px, sem exceções. `sizeHint()` devolve `QSize(0, 72)`.

| Faixa vertical | Conteúdo | Fonte | Cor |
|---|---|---|---|
| y = 8–26 (18 px) | Remetente (nome exibido, elidido à direita com margem para a data) | `font-size-md` | `text-primary`; `600` se não lido |
| y = 8–26, alinhado à direita | Data/hora | `font-size-sm` | `text-muted` |
| y = 28–48 (20 px) | Assunto, elidido | `font-size-lg` | `text-primary`; `600` se não lido |
| y = 28–48, à direita | Indicadores (estrela, clipe, respondida) | 12×12 | `flag-indicator` / `text-muted` |
| y = 50–66 (16 px) | Trecho de pré-visualização, elidido | `font-size-sm` | `text-muted` |

Padding: 12 px à esquerda do bloco de texto quando não há barra de não lido (x = 12), 15 px quando há (barra de 3 px em x = 0). 12 px à direita. Gap entre indicadores: 6 px. Ordem dos indicadores da direita para a esquerda: `attachment.svg`, `reply.svg` (respondida), `flag-filled.svg` (sinalizado).

#### 4.2.3 Anatomia do item — densidade compacta (48 px)

Altura fixa de 48 px. Duas faixas de 18 px com 6 px de padding superior e inferior.

| Faixa vertical | Conteúdo | Fonte | Cor |
|---|---|---|---|
| y = 6–24 | Remetente, elidido | `font-size-md` | `text-primary`; `600` se não lido |
| y = 6–24, à direita | Data | `font-size-sm` | `text-muted` |
| y = 24–42 | `Assunto — trecho`, em uma linha só, com o assunto em `600` se não lido. Separador ` — ` (espaço, travessão, espaço) | `font-size-md` | assunto `text-primary`, trecho `text-muted` |
| y = 24–42, à direita | Indicadores, 12×12, gap 4 px | — | idem |

Regra do separador: se o assunto estiver vazio, exibe apenas o trecho; se o trecho estiver vazio, exibe apenas o assunto; se ambos vazios, exibe "(sem conteúdo)" em `text-muted`.

Trocar de densidade: altera `density` no delegate, chama `viewport().update()` e `scheduleDelayedItemsLayout()`. Tempo alvo < 50 ms para 200 itens em tela. **Não** recria o modelo, **não** perde a seleção nem a posição de rolagem.

#### 4.2.4 Estados do item

| Estado | Aparência | Gatilho |
|---|---|---|
| Lido | Fundo `surface`; remetente e assunto em `400` | `messages.is_read = 1` |
| Não lido | Fundo `surface-unread`; barra de 3 px `unread-indicator` em x = 0 com altura total do item; remetente e assunto em `600` | `messages.is_read = 0` |
| Hover | Fundo `surface-hover`, aplicado em `dur-fast` | `QEvent.Enter` no índice sob o cursor. `setMouseTracking` não é usado: o delegate consulta `QStyle.State_MouseOver` |
| Selecionado (único) | Fundo `surface-selected`; todos os textos em `text-on-accent`; barra de não lido omitida; indicadores omitidos | `selectionModel().isSelected(index)` |
| Foco (item atual) | Retângulo de 2 px `focus-ring`, inset 1 px, raio `radius-sm`, desenhado pelo delegate quando `QStyle.State_HasFocus` e o índice é o `currentIndex`. Deslocado 2 px para dentro nas bordas laterais para não cobrir a barra de não lido | `setCurrentIndex` + `hasFocus()` do view |
| Pressionado | Idêntico a selecionado, sem alteração adicional | — |
| Arrastando (origem) | Opacidade 0,45 nos itens que compõem o arrasto; cursor `Qt.DragMoveCursor`; pixmap de arrasto é uma renderização de uma linha de 48 px com fundo `surface-raised` e o assunto em `font-size-md` | `[F2]`; na fase 1 o arrasto existe apenas para *exportar* a mensagem como arquivo (`.eml`), e o alvo é o sistema de arquivos |
| Alvo de soltar | Ver §4.1 (`dropTarget`) | `[F2]` |
| Operação pendente | `messages.pending_op IS NOT NULL`: ícone `sync.svg` de 12 px em `text-muted` na posição do terceiro indicador, com rotação a 1 volta/1200 ms. A linha permanece interativa | RF-MSG-09 |
| Corpo despejado | Nenhuma diferença visual. O usuário não deve saber onde está o cache | RF-MSG-06 |
| Falha de envio (na pasta Rascunhos) | Faixa de 2 px `danger` na base do item + `danger` no lugar da data, com o texto "falha" | RF-SND-05 |

#### 4.2.5 Carregamento de mais itens

Paginação: `PageSize = 200` (ORDER BY `date_utc DESC`, `LIMIT 200 OFFSET n` conforme `03-modelo-de-dados.md` §9). O modelo mantém `_pages: list[list[MessageRow]]`.

| Evento | Comportamento |
|---|---|
| Rolagem chega a 300 px do fim | `canFetchMore()` passa a `True`; `fetchMore()` é chamado pelo próprio `QListView` |
| `fetchMore` disparado | Emite `load_more_requested(folder_id, offset, 200)`; o `Storage` é consultado no `TaskPool`, nunca na thread da GUI |
| Rodapé da lista | Enquanto carrega: linha de 36 px com spinner de 14 px + "Carregando…" em `font-size-sm`/`text-muted`. Fim da pasta: linha de 36 px com "Fim da pasta · 1.482 mensagens" em `font-size-xs`/`text-muted` |
| Resultado chega | `beginInsertRows(count, count+n-1)` + `endInsertRows()`, e `rowCount()` dobra. Nunca `beginResetModel()` |
| Erro de paginação | Substitui o rodapé por faixa de 36 px `danger-subtle` com o motivo e botão "Tentar novamente" de 24 px de altura |
| Fim dos dados | Para de chamar `fetchMore`. O rodapé de fim fica visível |

Virtualização (RF-UI-05, CA-RF-UI-05-1): `setUniformItemSizes(True)`, `setLayoutMode(QListView.Batched)`, `setBatchSize(200)`, `setVerticalScrollMode(QListView.ScrollPerPixel)`, `setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)`, `setSelectionMode(QAbstractItemView.ExtendedSelection)`, `setEditTriggers(NoEditTriggers)`, `setUniformItemSizes` combinado com delegate sem `sizeHint` variável. Com 50.000 itens, apenas as linhas do viewport mais uma margem são criadas — o cache de layout do `QListView` é limitado pelo `batchSize`, e não há `QWidget` por linha, porque o delegate pinta diretamente.

#### 4.2.6 Seleção múltipla e barra de ações

| Ação | Resultado |
|---|---|
| Clique simples | Seleciona apenas aquele item, define `currentIndex` |
| `Ctrl`+clique | Alterna o item na seleção |
| `Shift`+clique | Seleciona o intervalo entre `currentIndex` e o clicado |
| `X` | Alterna o item atual e avança para o próximo (`J`), encadeando seleção por teclado |
| `Shift+J` / `Shift+K` | Estende a seleção para baixo/cima, movendo o `currentIndex` |
| `Ctrl+A` | Seleciona **todas as linhas carregadas** (não as 50.000 — a lista não está toda em memória). A barra de ações exibe "1.000 selecionadas (todas as carregadas)" com botão "Selecionar todas as 1.482" que dispara a operação sobre o conjunto por consulta, sem carregar linhas |
| `Esc` | Limpa a seleção múltipla e mantém o `currentIndex` (§5.3, regra 5) |

A `SelectionActionBar` ocupa 40 px, fundo `surface-raised`, borda inferior de 1 px `border-subtle`, e aparece/some com crossfade de `dur-base` (120 ms). Conteúdo, da esquerda para a direita:

| Elemento | Largura | Ação |
|---|---|---|
| `QLabel` "N selecionadas" | mínimo 96 px, `font-size-sm`, `text-muted` | — |
| `btnArchive` `QToolButton` 24×24 | 24 px | Arquivar (RF-ORG-01, RF-ORG-04) |
| `btnTrash` 24×24 | 24 px | Lixeira (RF-ORG-02) |
| `btnToggleRead` 24×24 | 24 px | Marcar como lida/não lida (RF-ORG-03) |
| `btnFlag` 24×24 | 24 px | Sinalizar/desinalizar (RF-ORG-03) |
| espaçador elástico | — | — |
| `btnClearSelection` 24×24 (`close.svg`) | 24 px | Limpa a seleção |

Todas as ações são otimistas (RF-MSG-09): a lista é atualizada **antes** de qualquer resposta do servidor. Com 50 itens arquivados, a barra troca o contador por "Arquivando 50…" no mesmo frame e some; um único progresso agregado aparece no rodapé da lista (CA-RF-ORG-04-1).

#### 4.2.7 Estados globais da lista

| Estado | Aparência | Texto e ação |
|---|---|---|
| Vazio — pasta sem mensagens | Ícone `folder-inbox.svg` de 48 px em `text-muted`, centralizado verticalmente | Título "Nada por aqui" (`font-size-xl`, 400); corpo "Sua caixa de entrada está zerada." (`font-size-sm`, `text-muted`, largura máxima 320 px); botão secundário "Sincronizar agora" |
| Vazio — sem conta | Ícone `account.svg` 48 px | "Nenhuma conta configurada" + "Adicione uma conta para começar a sincronizar." + botão primário "Adicionar conta" |
| Carregando — primeira sincronização | 6 linhas esqueleto de 72 px com blocos de `border-subtle` a 60 % de opacidade, mais uma faixa de progresso de 2 px no topo da lista | Sem texto na área |
| Carregando — paginação | Ver §4.2.5 | — |
| Erro | Ícone `alert-triangle.svg` 48 px em `danger` | Título "Não foi possível carregar esta pasta" (`font-size-xl`); corpo com a mensagem classificada de `core/errors.py` (`NetworkError` → "Sem conexão com o servidor", `AuthError` → "Credencial recusada", `ProtocolError` → "O servidor respondeu de forma inesperada"); botões "Tentar novamente" (primário) e "Ver diagnóstico" (secundário, abre Configurações → Logs) |
| Offline | Faixa de 32 px `warning-subtle` no topo da lista, texto `warning`: "Sem conexão — novos itens aparecerão quando a rede voltar". A lista **continua mostrando o cache**: nunca esvazia por causa de rede (RF-UI-08, RF-MSG-08) |
| Busca sem resultados | Ver §4.5 | — |

### 4.3 `ReaderPane`

Arquivo: `ui/components/reader.py`. Classes: `ReaderPane(QWidget)`, `PrivacyInterceptor(QWebEngineUrlRequestInterceptor)`, `TrackingBanner(QWidget)`, `ImageBlockBanner(QWidget)`, `ReaderFindBar(QWidget)`.

```text
┌─ ReaderPane (624 px) ───────────────────────────────────────────────────┐
│ Proposta comercial Q4                                        − 100%  +  │  40 px  barra de zoom/menu
│ Maria Silva <maria@exemplo.com>                                         │  24 px
│ para mim  ▾        hoje, 14:32                            ★  📎  📄     │  24 px
├─────────────────────────────────────────────────────────────────────────┤
│ [Responder] [Responder a todos] [Encaminhar]        [Arquivar] [Lixeira]│  40 px  ações
├─────────────────────────────────────────────────────────────────────────┤
│ ⚠ Imagens remotas bloqueadas.            [Carregar imagens deste remet.]│  40 px  banner de imagens
├─────────────────────────────────────────────────────────────────────────┤
│ ▸ 2 pixels de rastreamento removidos desta mensagem            ( ✕ )    │  28 px  aviso de rastreamento
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                      QWebEngineView (JavaScript off)                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.3.1 Cabeçalho

| Faixa | Altura | Conteúdo |
|---|---|---|
| Linha 1 | 40 px | Assunto em `font-size-lg`/`600`, elidido. À direita: `btnZoomOut`, `lblZoom` ("100 %", `font-size-sm`, 48 px de largura fixa, centralizado), `btnZoomIn`, `btnMore` — todos 28×28 |
| Linha 2 | 24 px | Remetente: `from_name` em `font-size-md`/`600` + ` <` + `from_addr` em `text-muted` + `>`. Se `from_name` vazio, exibe apenas o endereço |
| Linha 3 | 24 px | `para mim` quando o usuário está em `to_addrs`; senão "para " + lista de destinatários elidida. `▾` é um `QToolButton` de 16×16 que expande o painel de detalhes (ver abaixo). À direita: data formatada com `QLocale.system()`, indicadores `flag-filled.svg` (se sinalizada), `attachment.svg` (se `has_attachments`), `text-mode.svg` (se o modo texto simples estiver ativo) |
| Linha 4 (expansível) | 8 + 16·n px | **Painel de detalhes**, oculto por padrão. Mostra `De:`, `Para:`, `Cc:`, `Data:` (com fuso e formato completo, ex. "seg, 25 set 2026 14:32:07 -0300"), `Tamanho:` em KB/MB. Animação de altura em `dur-base` |

Cabeçalho total: 108 px colapsado (40+24+24+20 de padding), 188 + 16·n px expandido.

Ao navegar entre mensagens com `J`/`K`, o painel de detalhes **recolhe automaticamente** — sua expansão é estado de leitura corrente, não persistido.

#### 4.3.2 Botões de ação

Barra de 40 px, gap 4 px, botões `QToolButton` de 28×28 com `ToolButtonTextBesideIcon` onde há espaço, `setIconSize(QSize(16,16))`.

| Botão | Ícone | Rótulo | Atalho | `accessibleName` |
|---|---|---|---|---|
| `btnReply` | `reply.svg` | Responder | `R` | "Responder para Maria Silva" |
| `btnReplyAll` | `reply-all.svg` | Responder a todos | `Shift+R`, `A` | "Responder a todos os destinatários" (`[F2]` se mais de 5 destinatários, ver §10) |
| `btnForward` | `forward.svg` | Encaminhar | `F` | "Encaminhar mensagem" |
| `btnArchive` | `archive.svg` | Arquivar | `E` | "Arquivar mensagem" |
| `btnTrash` | `trash.svg` | Lixeira | `D` | "Mover para a lixeira" |
| `btnFlag` | `flag.svg` / `flag-filled.svg` | Sinalizar | `S` | Alterna entre "Sinalizar mensagem" e "Remover sinalização" |
| `btnMore` | `more-horizontal.svg` | — | — | "Mais ações" |

Menu do `btnMore` (`QMenu`, itens de 24 px de altura, largura mínima 220 px):

| Item | Atalho | Ação |
|---|---|---|
| Marcar como não lida | `I` | RF-ORG-03 |
| Ver cabeçalhos brutos | `Ctrl+Shift+H` | Abre `QDialog` de 720×480 com `QPlainTextEdit` em `font-size-mono`, conteúdo dos cabeçalhos originais |
| Exportar mensagem (.eml) | — | `QFileDialog.getSaveFileName`; grava `raw_bytes` |
| Ler como texto simples | `Ctrl+Shift+T` | Alterna o modo de leitura (ver §8.5) |
| Autorizações de imagens… | — | Abre Configurações → Privacidade → Remetentes autorizados (`RNF-PRIV-04`) |
| Localizar na mensagem | `Ctrl+F` | Abre a `ReaderFindBar` |

#### 4.3.3 Banner de imagens bloqueadas

Aparece quando o HTML sanitizado contém ao menos um recurso remoto com `data-pymail-remote-src` (reescrita de `ADR-004`, `02-arquitetura.md`).

Dimensões: altura 40 px, fundo `surface-raised`, borda esquerda de 3 px `accent`, padding horizontal 12 px.

Conteúdo: ícone `image-off.svg` de 16 px em `text-muted`; texto "**N** imagens remotas bloqueadas" quando N conhecido, ou "Imagens remotas bloqueadas" quando não; botão `btnAllowSender` (`QPushButton` primário de 28 px de altura, texto "Carregar imagens deste remetente"); botão `btnAllowOnce` (secundário, "Só nesta mensagem"); botão `btnDismissBanner` de 20×20 (`close.svg`) à direita.

Ação de autorizar (RF-RD-03):
1. `btnAllowSender` chama `storage.allow_sender_images(account_id, from_addr)` **no `TaskPool`** e, em paralelo, dispara a recarga do HTML com a política já em memória (o usuário não espera o disco).
2. A gravação em `sender_image_policy` é o que faz a autorização sobreviver ao reinício (CA-RF-RD-03-2).
3. O banner desaparece no mesmo frame; as imagens carregam conforme o interceptor passa a permitir `ResourceTypeImage` para aquele host.
4. Um `Toast` confirma: "Imagens de maria@exemplo.com sempre carregarão" com ação "Desfazer" durante 6000 ms, que remove a linha de `sender_image_policy`.

**Pixels de rastreamento permanecem removidos mesmo após autorizar** (RF-RD-04, CA-RF-RD-04-1): a remoção acontece na sanitização, antes do motor de renderização, e a autorização posterior não reintroduz o elemento. O interceptor é a segunda barreira, não a única.

`btnAllowOnce` não grava política: recarrega o HTML com permissão em memória válida somente enquanto a mensagem estiver aberta.

#### 4.3.4 Aviso de rastreamento removido

Visível apenas quando a sanitização removeu ao menos um pixel de rastreamento. Altura 28 px, fundo `surface`, borda esquerda de 3 px `warning`, texto em `font-size-sm`/`text-muted`: "▸ **2** pixels de rastreamento removidos desta mensagem", com `shield.svg` de 14 px à esquerda e `close.svg` de 20×20 à direita.

O botão `▸` expande um painel de 8 + 18·n px listando cada ocorrência: `img 1×1 — cdn.rastreador.com/px.gif`, `div display:none — …`. O painel existe para que o usuário verifique a afirmação do produto — sem ele, o aviso é uma promessa não auditável.

Dispensar o aviso vale **somente para a mensagem aberta**; não há persistência, e a próxima mensagem com rastreamento volta a exibir o aviso.

#### 4.3.5 Área do `QWebEngineView`

Configuração exata em `02-arquitetura.md` §5.5. Do ponto de vista de UI:

| Propriedade | Valor |
|---|---|
| `setContextMenuPolicy` | `Qt.NoContextMenu` — o menu nativo do Chromium expõe "Exibir código-fonte" e "Recarregar", irrelevantes e barulhentos. O botão direito é tratado por um `QMenu` próprio com "Copiar link", "Abrir link no navegador", "Copiar texto selecionado", "Localizar na mensagem" |
| Fundo | `page().setBackgroundColor(QColor(tokens["surface"]))`, reaplicado a cada mudança de tema. Sem isso, o leitor pisca branco no tema escuro |
| Margem do conteúdo | O HTML sanitizado recebe um `<style>` injetado com `body { margin: 0; padding: 16px 20px; font-family: <font_stack>; font-size: 13.3px; line-height: 1.5; color: <text-primary>; background: <surface>; word-wrap: break-word; }` e `img { max-width: 100%; height: auto; }`. O `<style>` é gerado por `sanitizer.build_reader_css(tokens)` e faz parte do HTML final |
| Rolagem | Barra de rolagem do Chromium é substituída: `QTWEBENGINE_CHROMIUM_FLAGS` não é usado; em vez disso, o CSS injetado define `::-webkit-scrollbar` com 10 px, polegar `scrollbar-handle` com raio 4 px e trilho transparente, mantendo a aparência idêntica à do resto do aplicativo |
| Links | Clique em link com `Ctrl` ou clique simples: emite sinal próprio capturado por `QWebEnginePage.acceptNavigationRequest` (o interceptor também bloqueia navegação de topo) e abre o diálogo de confirmação (§4.3.7). **O leitor nunca navega** (RF-RD-07) |
| Zoom | `view.setZoomFactor(percent / 100)` |

#### 4.3.6 Controles de zoom

| Elemento | Valor |
|---|---|
| Escala | 25, 33, 50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400 (%) |
| Passo | `Ctrl+=` e `Ctrl+-` avançam um degrau na lista. `Ctrl+0` volta a 100 % |
| Persistência | `ui.reader_zoom_percent` no `config.toml` é o padrão do aplicativo (RF-RD-08). O valor é gravado no fechamento da janela, não a cada tecla |
| Rótulo | `lblZoom` mostra o percentual, largura fixa de 48 px para não deslocar os botões vizinhos |
| Limites | Em 25 % `btnZoomOut` fica desabilitado; em 400 %, `btnZoomIn`. Desabilitado não é oculto |

#### 4.3.7 Confirmação de link externo (RF-RD-07)

`QMessageBox` não é usado — o diálogo é um `QDialog` de 480 px de largura, sem ícone decorativo, com `Qt.WindowModal`:

```text
┌──────────────────────────────────────────────────────┐
│ Abrir link no navegador?                             │
│                                                      │
│ Destino real:                                        │
│   exemplo.com                                        │
│                                                      │
│ URL completa:                                        │
│   https://exemplo.com/x/pagina?a=1                   │
│                                                      │
│ [Abrir no navegador]  [Copiar link]  [Cancelar]      │
└──────────────────────────────────────────────────────┘
```

O **host** é exibido em `font-size-lg`/`600` e a URL completa em `font-size-sm`/`text-muted` com quebra em até 3 linhas. O botão "Abrir no navegador" é o padrão; `Esc` cancela. O destino exibido é sempre `href` resolvido, nunca o texto visível do link (CA-RF-RD-07-1). Parâmetros de rastreamento já foram removidos por `RF-RD-05`; quando a URL original diferia, uma quarta linha mostra "Parâmetros de rastreamento removidos: utm_source, utm_campaign".

#### 4.3.8 Estados do `ReaderPane`

| Estado | Aparência |
|---|---|
| Vazio (nada selecionado) | Área central com ícone `mail-open.svg` de 64 px em `text-muted`, título "Nenhuma mensagem selecionada" (`font-size-xl`), corpo em `font-size-sm`/`text-muted`: "Use `J` e `K` para navegar, `Enter` para abrir, `?` para ver todos os atalhos." |
| Carregando (corpo fora do cache) | O cabeçalho e a barra de ações são desenhados **imediatamente** com os dados do `HeaderEnvelope`. A área do corpo mostra, após `delay-spinner` (150 ms), um spinner de 24 px centralizado + "Carregando mensagem…" (`font-size-sm`, `text-muted`). Um botão secundário "Cancelar" aparece após 2 s |
| Carregando (corpo em cache, `body_state = 'cached'`) | Nenhum spinner: exibição direta. Alvo < 150 ms (RNF-PERF-03) |
| Corpo despejado (`evicted`) | Trata como fora do cache: rebusca. Mensagem de 150 ms é a mesma; nenhuma distinção visual |
| Erro de rede ao buscar corpo | Ícone `alert-triangle.svg` 32 px em `danger`; "Não foi possível carregar a mensagem"; motivo classificado; botões "Tentar novamente" e "Ver cabeçalhos brutos" (que mostra o que já existe localmente). O cabeçalho permanece visível: nunca uma área em branco (RF-UI-07) |
| Erro de sanitização | Não existe estado visível. Uma falha do sanitizador é um defeito, registra log de nível `error` e cai no texto plano derivado, com a frase "Exibindo versão em texto simples" |
| Mensagem removida no servidor (`NotFoundError`) | Sem tela de erro: a lista remove a linha e o leitor volta ao estado vazio |

### 4.4 `Composer`

Arquivo: `ui/components/composer.py`. Classe: `ComposerWindow(QDialog)`.

**Decisão de contêiner:** o compositor é uma **janela separada** (`QDialog` não modal, `Qt.Window`), não um painel embutido. Razões: (a) não força reflow das três colunas, que é o que RF-UI-01 fixa; (b) permite consultar a caixa de entrada enquanto se escreve, o que é o fluxo real de quem responde; (c) permite múltiplos rascunhos abertos simultaneamente. Tamanho padrão `760×560`, mínimo `560×400`. Posição: centralizada sobre a janela principal com deslocamento de +24 px em x e +24 px em y a cada novo compositor aberto, para não empilhar exatamente.

```text
┌─ Composer — Nova mensagem (760 × 560) ────────────────────────── □ ✕ ──┐
│ De: joao@exemplo.com  ▾                                                 │  28 px
│ Para: ┌──────────────────┐ ┌────────────────┐  Cc  Cco                  │  36 px min
│       │ maria@exemplo.com✕│ │ joao@x.com    ✕│                         │
│       └──────────────────┘ └────────────────┘                           │
│ Assunto: Proposta comercial Q4                                          │  28 px
├─────────────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ João,                                                               │ │
│ │                                                                     │ │
│ │ > Em 25/09, Maria escreveu:                                         │ │
│ │ > Segue a proposta ajustada…                                        │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ 📎 planilha-orcamento-2027.xlsx  1,2 MB ✕   📎 contrato.pdf  840 KB ✕   │  32 px
├─────────────────────────────────────────────────────────────────────────┤
│ ⚠ O anexo de 34,2 MB excede o limite de 20 MB.                          │  32 px
├─────────────────────────────────────────────────────────────────────────┤
│ [Enviar]  [Anexar]  [⋯]                            Rascunho salvo 14:31 │  40 px
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.4.1 Campos

| Campo | Widget | Altura | Detalhe |
|---|---|---|---|
| De | `QComboBox` não editável | 28 px | Lista as contas habilitadas; rótulo = `display_name <email>`. Só aparece com ≥ 2 contas; com uma conta, o rótulo fica em `font-size-sm`/`text-muted` |
| Para / Cc / Cco | `QScrollArea` com `RecipientChipContainer` (`QWidget` + `FlowLayout` customizado) sobre `QLineEdit` (`recipientInput`) | mínimo 36 px, máximo 96 px | `FlowLayout` reflui chips. Acima de 96 px a área rola verticalmente. O `QLineEdit` fica **abaixo** dos chips, sempre visível |
| Assunto | `QLineEdit` | 28 px | Sem placeholder; rótulo fixo "Assunto:" à esquerda em `font-size-sm`/`text-muted`, 72 px de largura |
| Corpo | `QPlainTextEdit` (modo padrão) ou `QTextEdit` (modo HTML) | elástico | Modo texto por padrão. Recuo automático de 8 px em linhas citadas é feito pelo editor com `setTabStopDistance` e formatação de bloco, não com espaços |
| Anexos | `AttachmentBar` (`QWidget` + `FlowLayout`) | 0 ou 32 px | Oculto quando vazio |
| Ações | `QHBoxLayout` | 40 px | — |

#### 4.4.2 Chips de destinatário

| Propriedade | Valor |
|---|---|
| Altura | 24 px |
| Padding | 0 8 px (esquerda) e 0 4 px (direita, antes do ✕) |
| Raio | `radius-pill` |
| Fundo | `accent-subtle` |
| Texto | `font-size-sm`, `text-primary`. Exibe `Nome <email>` quando o nome é conhecido — 24 px é pouco, então o chip exibe o nome quando houver e o endereço completo no `tooltip` e no `accessibleName` |
| Botão ✕ | 16×16, `close.svg` 12 px, `accessibleName` = "Remover maria@exemplo.com" |
| Gap entre chips | 4 px |
| Validação | O endereço é validado no momento em que o chip é criado (por `Enter`, `,`, `;`, `Tab` ou perda de foco). Inválido: chip não é criado; o `QLineEdit` fica com borda `danger`, `tooltip` com o motivo, e o texto NÃO é apagado |
| Autocompletar | `[F2]`. Na fase 1, apenas endereços já vistos no cache local (`SELECT DISTINCT from_addr, from_name FROM messages`) alimentam um `QCompleter` com correspondência por prefixo, sensível a maiúsculas apenas no início |
| Colar múltiplos | Colar "a@x.com, b@y.com; c@z.com" cria três chips de uma vez |
| Backspace no campo vazio | Remove o último chip e o move para o campo como texto, permitindo correção |
| Navegação por teclado | `Tab` a partir do campo vai para o campo seguinte (Assunto), não para os chips, evitando uma armadilha de foco. Os chips são alcançáveis com `Shift+Tab` a partir do campo |

#### 4.4.3 Cc e Cco

Ocultos por padrão. Dois `QToolButton` de texto plano ("Cc", "Cco") de 24 px de altura, alinhados à direita da linha de destinatários, revelam o campo correspondente e o mantêm visível enquanto a janela estiver aberta. `Ctrl+Shift+B` alterna o Cco. Ao responder, Cc é revelado automaticamente se o original tinha Cc.

#### 4.4.4 Barra de anexos

| Item | Valor |
|---|---|
| Altura do chip | 28 px |
| Conteúdo | `attachment.svg` 14 px + nome do arquivo elidido no meio (nunca no fim — a extensão precisa permanecer visível) com largura máxima de 220 px + tamanho formatado (`QLocale.system().formattedDataSize`) em `font-size-xs`/`text-muted` + `✕` de 16×16 |
| Total | No fim da barra: "Total: 35,4 MB" em `font-size-xs`, `text-muted` |
| Adicionar | Botão "Anexar", `Ctrl+Shift+A`, ou arrastar arquivos sobre a janela (o `dragEnterEvent` aceita `text/uri-list` e a janela inteira vira alvo com borda de 2 px `accent` tracejada) |
| Anexo indisponível | Se o caminho não existe mais ao enviar, o chip fica com borda `danger` e o motivo no `tooltip`; o envio é bloqueado com a mensagem "1 anexo não está mais disponível" |

#### 4.4.5 Aviso de anexo grande

Gatilho: soma do tamanho dos anexos > limite configurável (`RF-SND-06`, padrão 20 MB, `config.toml [send] max_attachment_mb`).

Aviso inline de 32 px, fundo `warning-subtle`, borda esquerda de 3 px `warning`, texto em `font-size-sm`: "O anexo de 34,2 MB excede o limite de 20 MB. O destinatário pode não receber a mensagem."

Comportamento exato: o botão "Enviar" **continua habilitado**, mas o primeiro `Ctrl+Enter`/clique não envia — exibe o aviso e muda o rótulo do botão para "Enviar mesmo assim". O segundo acionamento, dentro de 10 s, envia. Passados 10 s, o rótulo volta a "Enviar" e o ciclo recomeça. Nenhuma caixa de diálogo modal.

#### 4.4.6 Aviso de assunto vazio

Gatilho: `RF-SND-08` — assunto vazio e corpo não vazio, no momento do envio.

Aviso inline idêntico em forma, fundo `surface-raised`, borda esquerda `warning`, 32 px: "Esta mensagem está sem assunto." com o botão "Adicionar assunto" (foca o campo Assunto) e "Enviar mesmo assim". O mesmo ciclo de dois acionamentos de §4.4.5 se aplica: o primeiro envio mostra o aviso, o segundo envia.

Aviso de destinatário ausente: mesmo mecanismo, texto "Esta mensagem não tem destinatário." — e nesse caso o segundo acionamento **não** envia; o botão permanece bloqueado, porque não existe envio válido sem destinatário. `RF-SND-08` permite alertar e enviar mesmo assim quanto ao assunto; quanto a não ter destinatário, não há para onde enviar.

Enquanto houver aviso visível, o grupo de avisos permanece fixo no rodapé, entre o corpo e a barra de ações.

#### 4.4.7 Barra de ações e estado de envio

| Elemento | Esquerda → direita |
|---|---|
| `btnSend` | `QPushButton` primário, altura 28 px, largura mínima 96 px, texto "Enviar (Ctrl+Enter)" |
| `btnAttach` | `QPushButton` secundário, "Anexar" |
| `btnMoreComposer` | `QToolButton` 24×24, menu: "Salvar rascunho" (`Ctrl+S`), "Descartar rascunho", "Modo HTML" (alterna), "Assinatura…" |
| Espaçador | elástico |
| `lblDraftState` | `font-size-xs`, `text-muted`: "Rascunho salvo 14:31" — atualizado a cada gravação automática de rascunho (a cada 5 s de inatividade, e no `closeEvent`) |

Estados do envio:

| Estado | Aparência | Duração |
|---|---|---|
| Editando | Conforme acima | — |
| Enfileirando | `btnSend` desabilitado, spinner de 14 px dentro do botão, rótulo "Enviando…" | ≤ 250 ms (gravação em `outbox` é disco, não rede) |
| Enfileirado | A janela fecha. `Toast` de Undo Send assume (§4.6) | `send-window` (padrão 10 s) |
| Falha ao enfileirar (disco cheio, banco corrompido) | A janela **não fecha**. Faixa `danger-subtle` de 40 px, texto do `StorageError`, botões "Tentar novamente" e "Salvar como arquivo…" | Até resolução |
| Envio falhou depois (SMTP) | Toast `danger` de 8000 ms: "Não foi possível enviar: <resposta do servidor>" com ação "Reenviar" e "Ver mensagem em Rascunhos". A mensagem permanece em `outbox` com `state='failed'` e aparece na pasta Rascunhos com a faixa vermelha de §4.2.4 (RF-SND-05, CA-RF-SND-05-1) | — |
| Recusado por TLS | Antes do envio: faixa `danger-subtle` de 40 px, "O servidor de saída não oferece TLS. O envio foi recusado." com link "Configurações → Conta" (RF-SND-07, CA-RF-SND-07-1) | Até resolução |

`Ctrl+Enter` envia; `Esc` aplica a regra 2 da escada de `Esc` (§5.3); `Ctrl+W` também tenta fechar.

### 4.5 `SearchBar`

Arquivo: `ui/components/search_bar.py`. Classe: `SearchBar(QWidget)`.

Oculto por padrão (P4). Revelado por `/`, por `Ctrl+F`? Não: `Ctrl+F` é a busca **na mensagem** (§4.3.2). A busca global é `/` ou o botão `search.svg` no header da lista.

```text
┌─ coluna da lista ────────────────────────────────────────────────┐
│ Caixa de entrada                          🔍  ⟳  ⋯               │
├──────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────┐ │  40 px
│ │ 🔍  proposta comercial                        ( ✕ )          │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ ( Não lidos ) ( Com anexo ) ( 30 dias ▾ ) ( Conta ▾ ) ( ✕ )      │  28 px
├──────────────────────────────────────────────────────────────────┤
│  12 resultados em todas as pastas                                │  24 px
├──────────────────────────────────────────────────────────────────┤
│ ▌Maria Silva      hoje    ★ 📎   Caixa de entrada                │  72 px
│   Re: Proposta comercial                                         │
│   Segue a proposta ajustada conforme convers…                    │
└──────────────────────────────────────────────────────────────────┘
```

| Elemento | Dimensões | Comportamento |
|---|---|---|
| `searchInput` (`QLineEdit`) | 28 px de altura, dentro de um contêiner de 40 px com padding vertical 6 px | `setClearButtonEnabled(False)` — o ✕ é um `QToolButton` próprio de 20×20, para controle de acessibilidade e estilo. Fundo `surface-sunken`, borda 2 px transparente que vira `accent` no foco |
| Debounce | `QTimer` single-shot de 250 ms reiniciado a cada tecla (RF-SRCH-02, `debounce-search`) | Enquanto o timer está pendente, nada é consultado |
| Execução | `TaskPool.submit(storage.search, ...)`, nunca na thread da GUI | `02-arquitetura.md` §6.5 |
| Marcação | O termo encontrado é destacado no assunto e no trecho com fundo `accent-subtle` e texto `text-primary`. O destaque é calculado sobre a string já tokenizada insensível a acentos — a implementação usa o mesmo `remove_diacritics` do FTS5 para mapear o deslocamento |
| Cancelamento | Se uma nova consulta chega antes da anterior terminar, a anterior é marcada com `CancellationToken` e seu resultado é descartado (ignorado por número de sequência) |

Filtros (RF-SRCH-03), linha de 28 px, chips de 22 px de altura com gap 4 px:

| Chip | Tipo | Valores |
|---|---|---|
| `Não lidos` | `QToolButton` checkable | Alterna `unread_only` |
| `Com anexo` | `QToolButton` checkable | Alterna `with_attach` |
| `Período` | `QToolButton` com menu | Qualquer data · 7 dias · 30 dias · 90 dias · Este ano |
| `Conta` | `QToolButton` com menu | Todas as contas · lista das contas (`[F2]` para caixa unificada, mas o filtro por conta já funciona na fase 1) |
| `De` | `QToolButton` com menu | Remetentes presentes nos resultados atuais |
| `✕` | `QToolButton` | Limpa todos os filtros |

Chip ativo: fundo `accent-subtle`, borda 1 px `accent`, texto `text-primary`. Chip inativo: fundo `surface-raised`, borda 1 px `border-subtle`.

Estados:

| Estado | Aparência |
|---|---|
| Oculto | A linha inteira não existe no layout (`setVisible(False)`), a lista começa no topo. Sem altura reservada |
| Vazio (foco, sem texto) | Nenhuma consulta é feita. A lista continua mostrando a pasta atual. Dica em `font-size-xs`/`text-muted` à direita do campo: "Assunto, remetente, corpo. `Esc` para sair." |
| Consultando | Spinner de 12 px no lugar do ✕, à direita do campo. Somente após `delay-spinner` (150 ms) — consultas locais de `RF-SRCH-02` retornam antes disso em 50.000 mensagens (CA-RF-SRCH-02-1, < 100 ms) |
| Com resultados | Linha de 24 px: "**N resultados** em <escopo>", em `font-size-xs`. A lista exibe os resultados no lugar das mensagens da pasta |
| Sem resultados | Ícone `search.svg` de 48 px em `text-muted`; título "Nenhum resultado para «proposta comercial»" (`font-size-lg`, 600), onde o termo é o texto digitado elidido em 40 caracteres; corpo "Verifique a grafia ou remova os filtros." + `font-size-xs`/`text-muted`: "A busca é insensível a acentos e maiúsculas."; botões "Limpar filtros" (secundário) e "Limpar busca" (primário). O botão "Buscar no servidor" **não** existe na fase 1 — `RF-SRCH-06` é `[F2]` |
| Erro | Não há estado de erro visível para busca local, porque `RF-SRCH-05`/`CA-RF-SRCH-05-1` exigem que nenhuma entrada produza exceção. Um erro de banco cai no estado de erro da lista (§4.2.7) |
| Termo inválido | Não existe: `build_match_query` transforma qualquer entrada em literal (`03-modelo-de-dados.md` §5.3). `"`, `AND`, `*`, `NEAR(`, `col:valor`, `-excluir` são buscados como texto |

Limpar, em cascata — cada `Esc` executa um passo:

1. Texto presente → limpa o texto, mantém o foco no campo, mantém a barra visível.
2. Texto vazio e há filtros ativos → limpa os filtros, mantém a barra visível.
3. Texto vazio, sem filtros → oculta a barra, restaura a lista da pasta, devolve o foco à `MessageList` (`setFocus(Qt.ShortcutFocusReason)`).
4. O botão ✕ executa os passos 1 e 2 de uma vez, em um único clique, sem ocultar a barra.

Sair da busca com a barra fechada **restaura a seleção anterior** na lista de mensagens, guardada no momento em que a busca começou. Se a mensagem selecionada não estava entre os resultados, o `currentIndex` volta para ela — mas como ela não está na lista filtrada, a seleção cai no primeiro resultado e a mensagem anterior volta a ser o alvo quando a busca é limpa.

### 4.6 `Toast`

Arquivo: `ui/components/toasts.py`. Classes: `ToastManager(QObject)`, `Toast(QWidget)`, `ToastHost(QWidget)`.

Widget flutuante, sem barra de título, sem foco inicial:

```python
self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
self.setAttribute(Qt.WA_ShowWithoutActivating, True)
self.setFocusPolicy(Qt.StrongFocus)   # alcançável por teclado quando contém ação
```

Posicionamento: `ToastHost` é filho da `QMainWindow`, cobre a área do `ReaderPane` e não intercepta mouse (`WA_TransparentForMouseEvents` no host, removido nos toasts). Empilhamento de baixo para cima, ancorado a 16 px da base da janela, com 8 px de gap entre toasts. Largura: `min(480, largura_do_leitor − 32)` px; mínimo de 320 px. Centralizado horizontalmente na coluna do leitor; na faixa estreita (§3.4), centralizado na janela.

| Propriedade | Valor |
|---|---|
| Altura | 48 px (uma linha de texto) ou 64 px (título + detalhe) |
| Raio | `radius-md` (5 px) |
| Fundo | `surface-raised` |
| Borda | 1 px `border-subtle` |
| Borda esquerda | 3 px na cor do tipo: `accent` (info), `warning` (aviso), `danger` (erro), `success` (confirmação) |
| Sombra | `elev-1` |
| Padding | 12 px horizontal, 8 px vertical |
| Ícone | 20×20, à esquerda, cor do tipo |
| Texto | `font-size-md`/`text-primary`; a segunda linha em `font-size-sm`/`text-muted` |
| Botão de ação | `QPushButton` de texto, 24 px de altura, cor do tipo |
| Botão fechar | 20×20, `close.svg`, `text-muted`, presente apenas em toasts persistentes |
| Entrada | 220 ms: opacidade 0→1 + `pos` de +12 px para 0, `OutCubic` |
| Saída | 160 ms: opacidade 1→0 |
| Foco | Nunca é roubado. Quando o toast tem ação, o botão entra no fim da cadeia de `Tab` enquanto está visível, e a ação tem atalho global (`Ctrl+Z` para desfazer, `Alt+R` para reenviar) |

Durações e comportamento por tipo:

| Tipo | Duração | Persistente | Exemplo |
|---|---|---|---|
| Info | 4000 ms | não | "3 mensagens arquivadas" |
| Sucesso | 4000 ms | não | "Imagens de maria@exemplo.com sempre carregarão" |
| Aviso | 8000 ms | não | "Sem conexão — tentando novamente em 4 s" (este se repete enquanto durar o estado offline, reaproveitando o mesmo toast) |
| Erro com ação | 12000 ms | não | "Falha ao enviar: 550 relay denied" + "Reenviar" |
| Erro sem ação | nunca expira | sim | Falha de banco com impacto no trabalho |
| **Undo Send** | `send-window` (padrão 10 s) | não | ver abaixo |

Limite: no máximo **3 toasts** simultâneos. Ao entrar o quarto, o mais antigo sai imediatamente (160 ms), mesmo que ainda esteja no prazo. Toasts de erro persistente têm prioridade e não são descartados por um toast informativo.

#### 4.6.1 Toast de Undo Send (RF-SND-03)

```text
┌──────────────────────────────────────────────────────────────────┐
│ ✉  Mensagem enviada para maria@exemplo.com                       │
│    Enviando em 7 s…                        [ Desfazer ]          │
│ ████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │  3 px
└──────────────────────────────────────────────────────────────────┘
```

| Elemento | Especificação |
|---|---|
| Altura | 64 px (duas linhas + barra de progresso) |
| Ícone | `send.svg` de 20 px, cor `accent` |
| Linha 1 | "Mensagem enviada para <primeiro destinatário>" — se houver mais destinatários, "+ N outros". `font-size-md`, `text-primary` |
| Linha 2 | "Enviando em **7 s**…" — contagem regressiva em segundos inteiros, `font-size-sm`, `text-muted`. O número é atualizado a cada 1000 ms |
| Progresso | Barra de 3 px na base do toast, largura total, cor `accent`, avançando linearmente de 100 % a 0 % em `send-window`. Atualizada a cada 100 ms via `QTimer` (não por `QPropertyAnimation`, para que a barra continue correta se a janela do undo for reconfigurada) |
| Botão "Desfazer" | `QPushButton` de texto, 24 px de altura, cor `accent`, `accessibleName` "Desfazer o envio desta mensagem" |
| Atalho | `Ctrl+Z` executa a mesma ação de "Desfazer" enquanto o toast estiver visível |
| Ao desfazer | `storage.mark_outgoing(outbox_id, 'canceled')` no `TaskPool`; o `Toast` sai em 160 ms e é substituído por um de 4000 ms: "Envio cancelado" com ação "Reabrir rascunho", que reabre o `ComposerWindow` com o conteúdo de `outbox`. **Nenhuma conexão SMTP é aberta** (CA-RF-SND-03-1) |
| Ao vencer o prazo | O toast não some abruptamente: a linha 2 muda para "Enviando…" por no máximo 300 ms e então o toast sai. Se o SMTP falhar, entra um `Toast` de erro com §4.4.7 |
| Reinício do aplicativo | O toast não é recriado a partir de `outbox` com `state='queued'`: ao abrir, o aplicativo verifica `due_outgoing(now)`. Se o prazo já passou, envia; se ainda não passou, exibe o toast **com o tempo restante correto** (CA-RF-SND-04-1) |
| Múltiplos envios | Um toast por mensagem, empilhados até 3. O `Ctrl+Z` desfaz o **mais recente**. Cada toast tem seu próprio `outbox_id`, e o botão sempre age sobre o seu |

Todos os textos do toast são anunciados: `setAccessibleName` é atualizado em cada mudança de estado ("Enviando em 7 segundos. Desfazer disponível.").

### 4.7 Estados globais

| Estado | Onde aparece | Especificação |
|---|---|---|
| **Vazio — sem conta** | `Sidebar` e `ReaderPane` | Sidebar: bloco de §4.1. Reader: `ReaderPaneState.EMPTY_NO_ACCOUNT` com botão "Adicionar conta" que abre o diálogo de `RF-ACC-01` |
| **Vazio — pasta vazia** | `MessageList` | §4.2.7 |
| **Vazio — busca sem resultado** | `MessageList` | §4.5 |
| **Vazio — nada selecionado** | `ReaderPane` | §4.3.8 |
| **Carregando — primeira execução** | Barra de status de 24 px na base da janela | "Sincronizando Caixa de entrada… 320 de 1.482". Aparece só após 500 ms. Some ao terminar. Não bloqueia nada |
| **Carregando — sincronização incremental** | Indicador de 12 px na linha da conta (§4.1) | Nenhum overlay, nenhum bloqueio |
| **Erro — conta específica** | Linha da conta na sidebar + `Toast` de erro na primeira ocorrência | `CA-RF-ACC-02-1`: as outras contas continuam funcionando. O erro de uma conta **nunca** produz um estado de erro global |
| **Erro — global (banco)** | Faixa de 48 px abaixo do header da janela, largura total, `danger-subtle` | Texto claro do `StorageError`, com a ordem de recuperação de `03-modelo-de-dados.md` §8.2: o aplicativo informa o arquivo `outbox-recuperado-<timestamp>.json` e que o cache será reconstruído. Botões "Abrir pasta de dados" e "Reconstruir agora" |
| **Offline** | Faixa de 32 px no topo da coluna da lista + ícone `offline.svg` na conta | Texto: "Sem conexão — tentando novamente em **N s**". `N` conta regressivamente conforme o recuo exponencial de 1 s, 2 s, 4 s, 8 s, 16 s, 32 s, 64 s, 128 s, 256 s, teto de 300 s (`02-arquitetura.md` §7). A interface **continua totalmente funcional** sobre o cache: ler, arquivar, sinalizar e enviar (enfileirando) funcionam. Ao reconectar, a faixa desaparece em 120 ms e um `Toast` de 4000 ms informa "Conexão restabelecida — sincronizando" |

Nenhum desses estados usa `QMessageBox`. Nenhum deles desabilita a janela inteira. Nenhum deles esvazia conteúdo já carregado.

---

## 5. Mapa de atalhos de teclado

### 5.1 Registro e contexto

`ui/shortcuts.py` define `ShortcutRegistry`, que centraliza a criação. Nenhum `QShortcut` é criado fora dele.

```python
class Scope(enum.Enum):
    GLOBAL = "global"      # ativo em qualquer lugar, exceto entrada de texto sem modificador
    LIST = "list"          # exige foco na MessageList ou no ReaderPane
    COMPOSER = "composer"  # exige foco na ComposerWindow
    READER = "reader"      # exige foco no ReaderPane
```

Todos os atalhos são criados com `context=Qt.WindowShortcut` sobre a janela que os possui (a `QMainWindow` ou a `ComposerWindow`), nunca com `Qt.ApplicationShortcut` — este último dispara mesmo com um `QDialog` modal aberto, o que produziria ações destrutivas atrás de um diálogo.

O registro guarda, para cada atalho, uma função `enabled()` que consulta o escopo. Os atalhos de escopo `LIST` verificam `self._is_list_scope()`:

```python
def _is_list_scope(self) -> bool:
    fw = QApplication.focusWidget()
    return isinstance(fw, (MessageListView, ReaderPane, ReaderWebView)) or self._list_view.hasFocus()
```

### 5.2 Tabela completa

| Tecla | Ação | Contexto ativo | Efeito |
|---|---|---|---|
| `C` | Compor | GLOBAL | Abre `ComposerWindow` vazia, com foco no campo Para. Se já houver um compositor aberto e não modificado, foca nele em vez de abrir outro |
| `E` | Arquivar | LIST | Move para a pasta de arquivo. Atualização otimista (RF-ORG-01, RF-MSG-09). Com seleção múltipla, aplica a todas |
| `Backspace` | Arquivar | LIST | Idêntico a `E` (RF-UI-03) |
| `D` | Lixeira | LIST | Move para a lixeira (RF-ORG-02) |
| `Delete` | Lixeira | LIST | Idêntico a `D` |
| `/` | Focar busca | GLOBAL | Revela a `SearchBar` (se oculta) e dá foco a `searchInput`, com o texto anterior selecionado |
| `J` | Próxima mensagem | LIST | Move o `currentIndex` para baixo; se já está na última linha carregada e há mais, dispara a paginação; se a última linha entra em tela, seleciona-a. O leitor atualiza após `delay-reader` = 120 ms |
| `K` | Mensagem anterior | LIST | Idem, para cima |
| `↓` / `↑` | Próxima / anterior | LIST | Idêntico a `J`/`K`. Com `Ctrl`, move a rolagem sem mudar a seleção |
| `N` | Próxima não lida | LIST | Avança até a próxima mensagem com `is_read = 0`, ignorando as lidas |
| `P` | Não lida anterior | LIST | Idem, para cima |
| `Enter` | Abrir | LIST | Move o foco para o leitor (`setFocus(Qt.ShortcutFocusReason)` no `webView`), mantendo a mensagem selecionada |
| `O` | Abrir | LIST | Idêntico a `Enter` |
| `U` | Voltar para a lista | READER | Devolve o foco à `MessageList`, preservando o `currentIndex` e a rolagem |
| `Space` | Página seguinte | LIST | Rola a lista em uma página (`viewport().height() - itemHeight`), mover o `currentIndex` para o primeiro item visível |
| `Shift+Space` | Página anterior | LIST | Idem, para cima |
| `Home` / `End` | Primeira / última | LIST | Primeira carregada / última carregada. Com `Ctrl`, primeira / última da pasta, disparando paginação até o fim apenas se `End` for pressionado com `Ctrl` |
| `R` | Responder | LIST, READER | Abre o compositor com o remetente em Para, assunto com prefixo "Re: " e citação (RF-SND-02) |
| `Shift+R` | Responder a todos | LIST, READER | Idem, com todos os destinatários originais em Para/Cc |
| `A` | Responder a todos | LIST, READER | Sinônimo de `Shift+R` |
| `F` | Encaminhar | LIST, READER | Assunto com prefixo "Enc: " e corpo com a citação |
| `S` | Sinalizar | LIST, READER | Alterna `is_flagged`. Otimista |
| `I` | Alternar lida | LIST, READER | Alterna `is_read`. Otimista |
| `X` | Selecionar e avançar | LIST | Alterna a seleção do item atual e move para o próximo (encadeia seleção por teclado) |
| `Shift+J` | Estender seleção para baixo | LIST | Adiciona o item seguinte à seleção e move o `currentIndex` |
| `Shift+K` | Estender seleção para cima | LIST | Idem, para cima |
| `Ctrl+A` | Selecionar tudo carregado | LIST | Ver §4.2.6 |
| `Ctrl+Z` | Desfazer | GLOBAL | Prioridade: (1) se há `Toast` de Undo Send visível, cancela aquele envio; (2) `[F2]` caso contrário, desfaz o último arquivamento/exclusão (RF-ORG-06). Na fase 1, sem toast visível, o atalho não tem efeito e nenhuma mensagem é exibida |
| `,` | (não usado) | — | — |
| `Ctrl+,` | Configurações | GLOBAL | Abre o diálogo de Configurações |
| `Ctrl+R` | Sincronizar agora | GLOBAL | Enfileira sincronização de todas as contas habilitadas |
| `F5` | Sincronizar agora | GLOBAL | Sinônimo de `Ctrl+R` |
| `Ctrl+Shift+D` | Alternar densidade | GLOBAL | Alterna confortável ↔ compacta (RF-UI-09), com `Toast` de 4000 ms informando a densidade ativa |
| `Ctrl+\\` | Colapsar / expandir sidebar | GLOBAL | Alterna e persiste (RF-UI-02) |
| `Ctrl+=` | Aumentar zoom | READER | Um degrau acima (§4.3.6) |
| `Ctrl+-` | Diminuir zoom | READER | Um degrau abaixo |
| `Ctrl+0` | Zoom 100 % | READER | Redefine |
| `Ctrl+Shift+T` | Alternar texto simples | READER | Troca o `QWebEngineView` pelo `QPlainTextEdit` acessível e vice-versa (§8.5) |
| `Ctrl+Shift+H` | Cabeçalhos brutos | READER | Abre o diálogo de cabeçalhos |
| `Ctrl+F` | Localizar na mensagem | READER | Abre a `ReaderFindBar` de 32 px no topo do corpo. `Enter`/`Shift+Enter` próxima/anterior; `Esc` fecha e devolve o foco ao leitor. Usa `QWebEnginePage.findText`, que funciona com JavaScript desabilitado |
| `?` | Ajuda de atalhos | GLOBAL | Abre `ShortcutCheatsheetDialog` (720×560, duas colunas, tabela de §5.2 sem a coluna Contexto). Fecha com `Esc` ou `?` |
| `Tab` / `Shift+Tab` | Foco seguinte / anterior | GLOBAL | Cadeia de §8.1 |
| `Ctrl+Tab` | Sair do leitor | READER | Devolve o foco à `MessageList`. Necessário porque `Tab` dentro do `QWebEngineView` pode ser consumido pelo Chromium |
| `Ctrl+W` | Fechar janela | COMPOSER | Fecha o compositor, gravando rascunho (regra 2 de `Esc`) |
| `Ctrl+Q` | Sair | GLOBAL | Se há mensagem em `outbox` com `state='queued'`, mostra um diálogo de confirmação explicando que ela será enviada ou marcada como falha. Senão, fecha |
| `Ctrl+Enter` | Enviar | COMPOSER | Ver §4.4.7 |
| `Ctrl+S` | Salvar rascunho | COMPOSER | Grava imediatamente em `outbox` com `state='draft'` |
| `Ctrl+Shift+B` | Mostrar Cco | COMPOSER | Revela o campo Cco e o foca |
| `Ctrl+Shift+A` | Anexar | COMPOSER | Abre `QFileDialog.getOpenFileNames` |
| `Alt+U` | Desfazer envio | GLOBAL | Executa a ação do `Toast` de Undo Send visível, **sem** exigir foco nele |
| `Alt+R` | Reenviar | GLOBAL | Executa a ação de reenvio do `Toast` de erro visível |
| `Esc` | Ver §5.3 | GLOBAL | Regras em cascata |
| `F1` | Ajuda | GLOBAL | Sinônimo de `?` |

Atalhos deliberadamente **ausentes**: `Ctrl+P` (imprimir) e `Ctrl+N` (nova janela). Impressão não está em escopo (`01-requisitos.md` §7) e uma segunda janela principal exigiria um segundo modelo de estado sem requisito que o justifique.

### 5.3 `Esc` — cascata determinística

`Esc` é o atalho mais sujeito a bug em clientes de e-mail porque várias camadas querem consumi-lo. A ordem abaixo é normativa: a **primeira** condição verdadeira vence e as demais não são avaliadas.

| # | Condição | Efeito |
|---|---|---|
| 1 | `QApplication.activeModalWidget()` existe | Fecha o modal (`reject()`). Nenhum outro tratamento. `Esc` nunca dispara duas ações |
| 2 | Foco em `ComposerWindow` e o corpo está modificado | Diálogo "Salvar rascunho?" com "Salvar" (padrão), "Descartar", "Cancelar". Sem modificação, fecha direto e remove o `outbox` com `state='draft'` |
| 3 | Foco em `ComposerWindow` e há campo de texto focado que não é o corpo | Move o foco para o corpo. Não fecha nada |
| 4 | `ReaderFindBar` visível | Fecha a barra, limpa o destaque (`page().findText("")`) e devolve o foco ao `webView` |
| 5 | `SearchBar` visível e `searchInput` tem texto | Limpa o texto. Foco permanece no campo. A lista volta ao conteúdo da pasta |
| 6 | `SearchBar` visível, texto vazio, filtros ativos | Limpa os filtros. A barra continua visível |
| 7 | `SearchBar` visível, texto vazio, sem filtros | Oculta a barra e devolve o foco à `MessageList` com `Qt.ShortcutFocusReason`, reativando os atalhos de letra |
| 8 | Seleção múltipla ativa (≥ 2 itens) | Reduz a seleção ao `currentIndex`. A seleção do item atual **nunca** é perdida |
| 9 | `Toast` com ação está focado | Fecha o toast sem executar a ação (não desfaz o envio) |
| 10 | Foco na `Sidebar` | Devolve o foco à `MessageList` |
| 11 | Foco no `ReaderPane` ou no `webView` | Devolve o foco à `MessageList` |
| 12 | Foco em qualquer outro campo de texto | Devolve o foco à `MessageList` |
| 13 | Nenhuma condição | Nenhum efeito. A tecla é consumida de todo modo, para que `Esc` nunca chegue ao `QWebEngineView` e cancele um carregamento do Chromium |

**Regra transversal:** `Esc` nunca fecha a janela principal, nunca apaga a seleção do item atual e nunca descarta conteúdo do usuário sem confirmação.

### 5.4 Guarda de foco de `RF-UI-04` — especificação precisa

`RF-UI-04` exige desativar atalhos de letra enquanto o foco estiver em campo de texto, saindo do campo com `Esc`. O erro clássico é implementar isso apenas dentro do slot do atalho: nesse momento a tecla **já foi consumida** pelo `QShortcut` e nunca chega ao `QLineEdit`. A implementação correta intercepta `QEvent.ShortcutOverride`, que o Qt envia ao widget focado **antes** de resolver o atalho.

`ShortcutRegistry.__init__` instala um filtro de eventos em `QApplication`:

```python
def eventFilter(self, obj: QObject, event: QEvent) -> bool:
    if event.type() == QEvent.Type.ShortcutOverride:
        if self._blocks_letter_shortcuts(QApplication.focusWidget()):
            mods = event.modifiers()
            # Só suprime atalhos sem modificador (ou com Shift, que é o caso de "?").
            # Combinações com Ctrl/Alt/Meta continuam valendo: Ctrl+Enter envia,
            # Ctrl+S salva rascunho, Ctrl+Z desfaz.
            if not (mods & ~(Qt.KeyboardModifier.ShiftModifier)):
                event.accept()   # o widget recebe a tecla literal; o atalho não dispara
                return True
    return False
```

A função de guarda é a única fonte de verdade sobre o que é "campo de texto":

```python
_TEXT_INPUT_TYPES = (QLineEdit, QPlainTextEdit, QTextEdit,
                     QAbstractSpinBox, QKeySequenceEdit)

def _blocks_letter_shortcuts(widget: QWidget | None) -> bool:
    if widget is None:
        return False
    if QApplication.activeModalWidget() is not None:
        return True
    if widget.property("pymailTextInput") is True:
        return True
    node: QWidget | None = widget
    while node is not None:
        # O leitor NÃO é campo de texto: as letras continuam valendo enquanto se lê.
        # Esta checagem vem primeiro, porque QWebEngineView tem proxies de foco
        # internos que poderiam casar com outras regras.
        if node.inherits("QWebEngineView"):
            return False
        if isinstance(node, _TEXT_INPUT_TYPES):
            return True
        if isinstance(node, QComboBox) and node.isEditable():
            return True
        node = node.parentWidget()
    return False
```

Conjunto exato de widgets que suprimem atalhos de letra:

| Widget | Onde | Suprime? | Observação |
|---|---|---|---|
| `QLineEdit` | `searchInput`, `recipientInput`, `subjectEdit`, `readerFindInput` | **sim** | `CA-RF-UI-04-1` depende disso: digitar `c` na busca insere `c` e não abre o compositor |
| `QPlainTextEdit` | corpo do compositor (modo texto) | **sim** | `c` insere `c` |
| `QTextEdit` | corpo do compositor (modo HTML), diálogo de cabeçalhos brutos | **sim** | — |
| `QAbstractSpinBox` | campo numérico de Configurações (janela do Undo Send) | **sim** | — |
| `QKeySequenceEdit` | Configurações → Atalhos, se existir | **sim** | Também evita que gravar um atalho dispare outro |
| `QComboBox` editável | campo "De" do compositor, quando editável | **sim** | Na fase 1 o "De" não é editável, portanto não suprime |
| `QWebEngineView` do leitor | corpo da mensagem | **não** | Decisão explícita: ler uma mensagem não é digitar. `J`, `K`, `E`, `C` funcionam com o foco no leitor. Isso é o que torna o fluxo "leia e arquive sem tocar no mouse" possível |
| `ReaderFindInput` | barra de localizar na mensagem | **sim** | É um `QLineEdit` |
| Chips de destinatário | `ComposerWindow` | **não** | Não recebem foco por `Tab` (§4.4.2); o foco está sempre no `recipientInput` |
| `MessageListView`, `Sidebar`, botões | — | **não** | São os alvos naturais dos atalhos |

Widgets que precisarem do comportamento sem herdar de um tipo listado marcam-se com a propriedade dinâmica `pymailTextInput = true` — é o gancho de extensão, e ele é a única forma de adicionar supressão sem tocar em `shortcuts.py`.

**Segunda linha de defesa.** Cada slot de atalho de letra começa com uma verificação redundante:

```python
def _archive(self) -> None:
    if _blocks_letter_shortcuts(QApplication.focusWidget()):
        return
    ...
```

Ela cobre caminhos que não passam pelo `ShortcutOverride` — por exemplo, um atalho acionado programaticamente, ou um widget que engole o evento antes do filtro.

**Devolver o foco com `Esc`.** Regras 5–7 e 10–12 de §5.3 são o mecanismo. O ponto crítico: ao devolver o foco, o widget de destino é focado com `Qt.ShortcutFocusReason`, o que (a) desenha o anel de foco no item atual da lista e (b) faz `_blocks_letter_shortcuts` retornar `False` no próximo teste, reativando imediatamente `J`, `K`, `E`, `C`. Não há "modo" a desligar: a guarda é uma função pura do foco.

**Teste obrigatório** (CA-RF-UI-04-1 e CA-RF-UI-03-1): com o foco em `searchInput`, injetar `c` produz o caractere no campo e **nenhuma** janela de compositor; injetar `Esc` devolve o foco a `MessageListView`, e a partir daí injetar `c` abre o compositor.

---

## 6. Fluxos de interação

Todos os tempos abaixo são metas verificáveis. `t` é medido a partir do evento de entrada.

### 6.1 Arquivar com atualização otimista (`E`)

| t | O que o usuário vê |
|---|---|
| 0 ms | Tecla `E` pressionada |
| ≤ 8 ms | A linha desaparece da lista com uma animação de colapso de altura (72→0 px) em `dur-base` (120 ms). A linha seguinte sobe. O total da pasta decrementa no header |
| ≤ 16 ms | `storage` grava `messages.pending_op = 'move:<id>'` e insere uma linha em `pending_ops` — **no `TaskPool`**, nunca na thread da GUI (RNF-PERF-01). Se o banco demorar, a UI já mudou |
| ≤ 100 ms | `MessageListModel` recebe `beginRemoveRows`/`endRemoveRows`. Um `Toast` de 4000 ms aparece: "1 mensagem arquivada" (ou "50 mensagens arquivadas", com um único progresso agregado no rodapé, CA-RF-ORG-04-1) |
| 100 ms – 3 s | O `AccountWorker` da conta executa `UID MOVE` (ou `COPY` + `STORE \Deleted` + `EXPUNGE` quando o servidor não anuncia `MOVE`, RF-ORG-05) |
| sucesso | `pending_op` é zerado. **Nada muda visualmente** — o usuário não precisa saber que o servidor confirmou |
| falha definitiva | A linha **volta** à posição original (animação de altura 0→72 px em `dur-base`), com um `Toast` de erro `danger` de 12000 ms: "Não foi possível arquivar: <motivo do servidor>" e ação "Tentar novamente". Reversão silenciosa é proibida (CA-RF-MSG-09-1) |
| offline | Tudo igual até o passo 100 ms. O `Toast` diz "1 mensagem arquivada — será sincronizada quando a conexão voltar". Nada é revertido. A operação espera em `pending_ops` |

Se a mensagem arquivada era a que estava aberta no leitor: o leitor passa para a mensagem seguinte na lista (não para o estado vazio), mantendo o ritmo de Inbox Zero. Se era a última, o leitor vai para o estado vazio.

### 6.2 Abrir mensagem não cacheada

| t | O que o usuário vê |
|---|---|
| 0 ms | `K`/`J` ou clique define a mensagem |
| 0–120 ms | O leitor espera `delay-reader` (120 ms) para não disparar `FETCH` em navegação rápida com `J` repetido. Cada nova navegação reinicia o timer (equivale a um debounce de leitura) |
| 120 ms | Cabeçalho, barra de ações, assunto, remetente, destinatários e data são desenhados **imediatamente**, a partir do `HeaderEnvelope` já em cache. Fundo `surface` |
| ≤ 150 ms | Se o corpo está em cache (`body_state='cached'`): HTML sanitizado exibido. **Fim** (RNF-PERF-03) |
| 120–270 ms | Se não está: nada visível ainda — o spinner só aparece após `delay-spinner` (150 ms). A área do corpo fica vazia com fundo `surface` |
| 270 ms | Spinner de 24 px + "Carregando mensagem…". O botão "Cancelar" **não** aparece ainda |
| 2 s | Botão "Cancelar" aparece, 24 px, secundário. Cancelar usa `CancellationToken` e volta ao estado vazio (ou à mensagem anterior) sem toast — cancelamento é silencioso (`02-arquitetura.md` §7) |
| ~1 s (rede típica) | Corpo chega. A thread da GUI **não sanitiza**: o `TaskPool` executa `sanitize_html` e a derivação de texto plano (`02-arquitetura.md` §6.2) |
| +80–250 ms | HTML exibido por `view.setHtml(...)`. Tempo total típico: 1,2–1,5 s, contra o limite de 3 s de RNF-PERF-03 |
| após exibir | O `TaskPool` dispara a pré-busca das próximas 5 mensagens em prioridade baixa (RF-MSG-03), cancelável a cada nova navegação. Nada disso é visível |
| +1500 ms | Se `mark_read_delay` estiver habilitado, a mensagem é marcada como lida (RF-RD-09): o fundo do item na lista passa de `surface-unread` para `surface`, a barra de 3 px desaparece e o remetente/assunto perdem o `600`, em `dur-fast`. Se o usuário navegar antes de 1500 ms, o timer é cancelado e a mensagem **não** é marcada |
| falha | Após 3 s sem resposta e sem estado, mostra o erro de §4.3.8. A mensagem permanece selecionada |

### 6.3 Responder (`R`)

| t | O que o usuário vê |
|---|---|
| 0 ms | `R` |
| ≤ 60 ms | `ComposerWindow` aparece já posicionada, com "De" preenchido com a conta que recebeu a mensagem, "Para" com `from_addr` do original, assunto com "Re: " prefixado (se já não começar por "Re: "), e o corpo com a citação e uma linha em branco acima do cursor |
| ≤ 60 ms | Foco no corpo, **cursor acima da citação**. O usuário digita sem tocar em nada |
| 0 ms | Cabeçalhos `In-Reply-To` e `References` são gravados na `outbox` desde a criação, não no envio (RF-SND-02) |
| a cada 5 s de inatividade | Rascunho gravado; `lblDraftState` passa a "Rascunho salvo HH:MM" |
| reinício do app | O rascunho reaparece em Rascunhos, e o `ComposerWindow` é reaberto se o app foi fechado com ele aberto (RF-SND-04) |

Citação exata: `\n\nEm <data por extenso no locale>, <remetente> escreveu:\n> <linha 1>\n> <linha 2>…`. No modo HTML, a citação vira um `<blockquote>` com `border-left: 2px solid <border-subtle>`.

### 6.4 Enviar com Undo Send (`Ctrl+Enter`)

| t | O que o usuário vê |
|---|---|
| 0 ms | `Ctrl+Enter` |
| ≤ 20 ms | Validação dos destinatários e dos anexos. Falha → §4.4.5/§4.4.6, nada é enviado |
| ≤ 40 ms | `btnSend` desabilitado, spinner, "Enviando…" |
| ≤ 250 ms | `outbox` gravado com `state='queued'` e `send_at = now + 10 s`, com `Message-ID` já gerado e estável (CA-RF-SND-03-2). **A mensagem existe em disco antes de qualquer rede** (RNF-REL-01). A janela fecha |
| ≤ 250 ms | `Toast` de Undo Send aparece (§4.6.1), com contagem de 10 s e "Desfazer" |
| 250 ms – 10 s | O usuário pode: `Ctrl+Z`, `Alt+U` ou clicar "Desfazer". Qualquer um cancela: `state='canceled'`, toast substituído por "Envio cancelado" com "Reabrir rascunho". **Zero conexões SMTP** (CA-RF-SND-03-1) |
| 10 s | `QTimer` de 1 s chama `due_outgoing(now)` e encontra a mensagem |
| 10 s + | `state='sending'`; a thread de envio abre SMTP com STARTTLS obrigatório (RF-SND-07) |
| ~11 s | `state='sent'`. Toast de 4000 ms: "Mensagem enviada" — sem ação |
| falha SMTP | Toast de erro 12000 ms com o texto do servidor e "Reenviar"; `state='failed'`; a mensagem aparece em Rascunhos com a marca de falha (§4.2.4, CA-RF-SND-05-1) |
| fechamento no meio | Se o app é encerrado com a mensagem em `queued`, ao reabrir: prazo vencido → envia; prazo não vencido → o toast reaparece com o tempo restante. Em nenhum caso a mensagem desaparece (CA-RF-SND-04-1) |

### 6.5 Buscar

| t | O que o usuário vê |
|---|---|
| 0 ms | `/` |
| ≤ 30 ms | A barra de 40 px aparece (sem animação de altura, para não competir com a digitação) e o foco vai para `searchInput`. A lista **não** muda ainda — continua mostrando a pasta |
| digitação | Cada tecla atualiza o campo e reinicia o debounce de 250 ms (RF-SRCH-02). Nenhuma consulta é disparada durante a digitação contínua |
| +250 ms após a última tecla | Consulta escapada (RF-SRCH-05) executada no `TaskPool` |
| +250 a +350 ms | Resultados substituem o modelo. Em 50.000 mensagens a consulta leva < 100 ms (CA-RF-SRCH-02-1); o total percebido fica abaixo de 400 ms desde a última tecla |
| durante | Linha "N resultados" aparece. Spinner só se passar de 150 ms |
| sem resultados | Estado de §4.5 |
| `Esc` | Cascata de §5.3, regras 5–7 |
| resultado clicado | O leitor abre a mensagem; o termo buscado é destacado na lista e, no leitor, a `ReaderFindBar` **não** abre automaticamente (o destaque no corpo exigiria JavaScript, que está desabilitado por `RF-RD-01`). O termo é destacado apenas nos campos de texto da lista |

Filtros: alterar qualquer chip reinicia o debounce de 250 ms (não consulta imediatamente) e mantém o texto e o foco.

### 6.6 Autorizar imagens de um remetente

| t | O que o usuário vê |
|---|---|
| 0 ms | Clique em "Carregar imagens deste remetente" (ou `Alt+I`) |
| ≤ 16 ms | O banner de §4.3.3 desaparece. O HTML é recarregado com a permissão em memória |
| ~200–600 ms | As imagens remotas aparecem. Somente `ResourceTypeImage` é permitido pelo interceptor (`02-arquitetura.md` §5.5); CSS remoto, fontes e XHR continuam cancelados e registrados |
| ≤ 100 ms | `Toast` de sucesso 6000 ms: "Imagens de maria@exemplo.com sempre carregarão" com "Desfazer" |
| background | `storage.allow_sender_images(account_id, from_addr)` grava em `sender_image_policy` no `TaskPool`. A autorização vale para **aquela conta e aquele remetente** e sobrevive ao reinício (CA-RF-RD-03-2) |
| "Desfazer" | Remove a linha de `sender_image_policy`; o HTML volta a bloquear; um toast de 4000 ms confirma "Autorização removida" |
| pixel de rastreamento presente | Mesmo autorizando, **nenhuma** requisição é emitida para ele: o elemento foi removido na sanitização e não existe no HTML final. O aviso de §4.3.4 continua exibindo a contagem (CA-RF-RD-04-1) |
| próxima mensagem do mesmo remetente | Já abre com as imagens permitidas, sem banner |

### 6.7 Perda de conexão

| t | O que o usuário vê |
|---|---|
| 0 ms | A conexão cai |
| ≤ 100 ms | A UI **não muda** por causa do erro em si. O que estava em tela permanece: a lista continua populada a partir do cache, o leitor continua legível |
| imediato | Se a falha foi detectada durante uma operação (sincronização, arquivamento, busca de corpo), essa operação mostra seu próprio estado de erro no contexto dela |
| +1 s | Primeira tentativa de reconexão (recuo exponencial 1 s, 2 s, 4 s…). Só na segunda falha o estado global aparece |
| +2 s | Faixa de 32 px no topo da lista: "Sem conexão — tentando novamente em **2 s**". Ícone `offline.svg` na linha da conta. `Toast` de aviso, uma única vez, com o mesmo texto |
| durante o offline | **Tudo funciona sobre o cache**: ler mensagens em cache, buscar localmente (FTS5 é local), arquivar, sinalizar, marcar como lida, responder e enviar. Cada operação otimista entra em `pending_ops` e é anunciada com a ressalva de sincronização (§6.1). Enviar entra em `outbox` e o toast de Undo Send funciona normalmente |
| mensagem sem corpo em cache | O leitor mostra o erro de §4.3.8 com "Tentar novamente". O cabeçalho permanece visível |
| recuo | 1, 2, 4, 8, 16, 32, 64, 128, 256, 300 s (teto de 5 min, `02-arquitetura.md` §7). A faixa mostra a contagem regressiva do próximo intervalo |
| ao reconectar | A faixa desaparece em 120 ms. Um `Toast` de 4000 ms: "Conexão restabelecida — sincronizando". O `AccountWorker` drena `pending_ops` em ordem e roda a sincronização incremental por `UIDNEXT` (RF-MSG-04) |
| reconciliação | Se o servidor diverge do estado otimista (a mensagem já não existe na pasta de origem), o item é removido localmente **sem** toast de erro — é reconciliação, não falha (CA-RF-ORG-05-1) |

### 6.8 Feedback em menos de 100 ms (RNF-USA-02)

Regra de implementação, não de intenção: **todo slot conectado a um sinal de entrada do usuário executa apenas código de memória.** A verificação de que isso se sustenta é o teste de `CA-RNF-PERF-01-1` (supervisor de bloqueio de 100 ms na thread principal) mais um teste de UI que mede, para cada atalho da tabela de §5.2, o tempo entre `QTest.keyClick` e a primeira alteração de estado observável.

| Ação | Primeira mudança visível | Prazo |
|---|---|---|
| Arquivar / lixeira / sinalizar / lida | Remoção ou repintura da linha | ≤ 16 ms |
| Navegar `J`/`K` | Cabeçalho do leitor atualizado | ≤ 20 ms (após `delay-reader` de 120 ms) |
| Abrir busca | Barra visível | ≤ 30 ms |
| Enviar | Botão em estado "Enviando…" | ≤ 40 ms |
| Responder | Janela do compositor visível e focada | ≤ 60 ms |
| Colapsar sidebar | Início da animação | ≤ 16 ms (fim em 180 ms) |
| Alternar densidade | Lista repintada | ≤ 50 ms |
| Alternar tema | `setStyleSheet` aplicado e lista repintada | ≤ 80 ms |

---

## 7. Temas claro e escuro

### 7.1 Estrutura de `ui/styles.py`

```python
LIGHT: dict[str, str] = {...}          # §2.4
DARK:  dict[str, str] = {...}

_QSS_DIR = Path(__file__).parent.parent / "assets" / "themes"

def _template(name: str) -> str:
    return (_QSS_DIR / name).read_text(encoding="utf-8")

class _Tokens(dict[str, str]):
    """Falha alto em token inexistente: um QSS que referencia {surface-raysed}
    deve quebrar em teste, não virar 'background-color: {surface-raysed}' no app."""
    def __missing__(self, key: str) -> str:
        raise KeyError(f"token de tema inexistente: {key}")

def tokens(scheme: Qt.ColorScheme) -> dict[str, str]:
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT

def build_qss(scheme: Qt.ColorScheme) -> str:
    return _template(f"{_scheme_name(scheme)}.qss").format_map(_Tokens(tokens(scheme)))

def build_palette(scheme: Qt.ColorScheme) -> QPalette: ...
def icon(name: str, size: int, token: str, dpr: float) -> QIcon: ...
```

`assets/themes/light.qss` e `assets/themes/dark.qss` são **modelos**, não folhas prontas. Os valores hexadecimais aparecem uma única vez, em `styles.py`, e o QSS os referencia por nome. O delegate lê o mesmo `dict`, o que garante que a linha pintada em `QPainter` e o `QPushButton` ao lado dela nunca divergem.

### 7.2 Trechos reais de QSS

Campo de busca — a reserva de borda transparente é o que evita o salto de layout de 2 px quando o anel de foco aparece:

```qss
QLineEdit#searchInput {
    background-color: {surface_sunken};
    color: {text_primary};
    border: 2px solid transparent;
    border-radius: {radius_md};
    padding: 0 {space_3};
    min-height: 28px;
    max-height: 28px;
    selection-background-color: {accent};
    selection-color: {text_on_accent};
}
QLineEdit#searchInput:hover  { border-color: {border_strong}; }
QLineEdit#searchInput:focus  { border-color: {accent}; background-color: {surface}; }
QLineEdit#searchInput[queryActive="true"] { border-color: {accent}; }
QLineEdit#searchInput:disabled { color: {text_disabled}; border-color: {border_subtle}; }
```

O placeholder **não** tem seletor em QSS; sua cor vem do `QPalette.ColorRole.PlaceholderText`, definido em `build_palette()` com `text_muted`. Isso precisa ser dito porque é um erro comum tentar `QLineEdit::placeholder` no QSS e não ver efeito algum.

Botão de ação primária:

```qss
QPushButton#primaryAction {
    background-color: {accent};
    color: {text_on_accent};
    border: 2px solid transparent;
    border-radius: {radius_md};
    padding: 0 {space_4};
    min-height: 28px;
    font-size: {font_size_md};
    font-weight: 600;
}
QPushButton#primaryAction:hover    { background-color: {accent_hover}; }
QPushButton#primaryAction:pressed  { background-color: {accent_pressed}; }
QPushButton#primaryAction:focus    { border-color: {focus_ring}; }
QPushButton#primaryAction:disabled {
    background-color: {surface_sunken};
    color: {text_disabled};
}
```

O ícone do botão é recolocado a cada troca de tema por `styles.icon()`, porque o `QIcon` de um SVG não é recolorido pelo QSS.

Lista virtualizada — o `outline: 0` é deliberado: o foco é pintado pelo `MessageItemDelegate`, não pelo Qt:

```qss
QListView#messageList {
    background-color: {surface};
    border: 0;
    outline: 0;
    padding: 0;
    selection-background-color: transparent;   /* o delegate pinta a seleção */
}
QListView#messageList::item {
    border: 0;
    padding: 0;
    margin: 0;
}
```

Barra de rolagem (a mesma aparência em qualquer widget, e a do leitor é replicada em CSS injetado):

```qss
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
    border: 0;
}
QScrollBar::handle:vertical {
    background: {scrollbar_handle};
    border-radius: 4px;
    min-height: 32px;
    margin: 2px 2px;
}
QScrollBar::handle:vertical:hover { background: {text_muted}; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
```

Divisores, menus e tooltips:

```qss
QSplitter::handle:horizontal {
    background-color: {border_subtle};
    width: 4px;
}
QSplitter::handle:horizontal:hover { background-color: {accent}; }

QMenu {
    background-color: {surface_raised};
    border: 1px solid {border_subtle};
    border-radius: {radius_md};
    padding: {space_1};
}
QMenu::item {
    padding: {space_1} {space_6} {space_1} {space_3};
    border-radius: {radius_sm};
    min-height: 22px;
    color: {text_primary};
}
QMenu::item:selected { background-color: {accent}; color: {text_on_accent}; }
QMenu::separator { height: 1px; background: {border_subtle}; margin: {space_1} {space_2}; }

QToolTip {
    background-color: {tooltip_bg};
    color: {tooltip_text};
    border: 1px solid {border_subtle};
    border-radius: {radius_sm};
    padding: {space_1} {space_2};
}
```

### 7.3 Detecção do tema do sistema

```python
def detect_system_scheme() -> Qt.ColorScheme:
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme()           # Qt 6.5+
    if scheme == Qt.ColorScheme.Unknown:
        return Qt.ColorScheme.Light        # fallback determinístico, nunca "adivinhar"
    return scheme
```

A solução completa fica em `ThemeController(QObject)`, em `ui/styles.py`:

```python
class ThemeController(QObject):
    theme_changed = Signal(object)         # dict[str, str] de tokens

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._hints = QGuiApplication.styleHints()
        self._hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self._current = self._effective_scheme()

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self._config.ui.theme == "system":
            self._apply()

    def set_override(self, mode: str) -> None:      # "system" | "light" | "dark"
        self._config.ui.theme = mode
        self._apply()                              # tempo real, sem reiniciar (RF-UI-06)
```

`colorSchemeChanged` é emitido pela plataforma quando o SO muda de tema. O slot só aplica se o modo for `system`: uma sobreposição manual precisa vencer o sistema (CA-RF-UI-06-1).

**Guarda de versão.** `QStyleHints.colorScheme()` e o sinal `colorSchemeChanged` existem a partir do Qt 6.5. `pyproject.toml` exige `PySide6>=6.5`; ainda assim, `ThemeController.__init__` protege com `hasattr(self._hints, "colorSchemeChanged")`, degradando para o tema claro com um registro em log, em vez de quebrar em uma plataforma empacotada com Qt mais antigo.

### 7.4 Sobreposição manual em tempo real

Sequência de `_apply()`, na ordem — a ordem importa:

1. Chamar `hints.setColorScheme(...)`? **Não.** Alterar o esquema global do Qt afeta outros aplicativos e não é necessário. A sobreposição é aplicada apenas a este aplicativo.
2. Calcular `self._token_map = tokens(self._effective_scheme())`.
3. Construir o `QPalette` com `build_palette()` e aplicar com `QApplication.setPalette(palette)`. Isto é necessário para tudo que **não** é estilizável por QSS: menus nativos, diálogos de arquivo, `QMessageBox` residual, cores de `PlaceholderText`, `Highlight`, `HighlightedText`, `ToolTipBase`, `ToolTipText`, `Disabled/Text`, `Disabled/WindowText`. Sem este passo, o tema escuro fica com caixas brancas nos diálogos do sistema.
4. `QApplication.instance().setStyleSheet(build_qss(scheme))`. O `setStyleSheet` global provoca um re-polimento de todos os widgets, mas **não** recria nenhum: o modelo da lista, a seleção, a rolagem e o estado do leitor permanecem íntegros (CA-RF-UI-06-1 exige explicitamente que a lista não seja recarregada).
5. `self.theme_changed.emit(self._token_map)`.
6. Cada consumidor reage: `MessageItemDelegate` e `SidebarDelegate` guardam referência ao `dict` e chamam `viewport().update()` (não `reset()`); `ReaderPane` reaplica `page().setBackgroundColor(...)` e, se há mensagem aberta, reexecuta `view.setHtml(html, baseUrl)` com o `<style>` regenerado para o novo tema; `ThemeController` atualiza todos os `QIcon` em cache chamando `styles.icon()` novamente.
7. Gravar a preferência no `config.toml` **de forma adiada** (`QTimer.singleShot(0, ...)`), para não bloquear o slot de mudança de tema com I/O.

**Custo medido alvo:** troca de tema completa em menos de 80 ms com 200 itens visíveis, sem perda de seleção, sem perda de posição de rolagem, sem nova consulta ao banco. Reexecutar `setHtml` do leitor custa 30–60 ms; por isso ele é feito **depois** de o resto da interface já estar repintado, de forma que o usuário nunca veja o aplicativo pela metade.

Onde a preferência é escolhida: menu "Exibir → Tema" (três `QAction` checkable em um `QActionGroup` exclusivo) e Configurações → Aparência. Os dois escrevem no mesmo `config.ui.theme`.

### 7.5 Reação ao tema do sistema nos casos de borda

| Situação | Comportamento |
|---|---|
| SO muda o tema com o app aberto e `theme = system` | `colorSchemeChanged` → `_apply()`. Sem reiniciar, sem recarregar a lista (CA-RF-UI-06-1) |
| SO muda o tema com `theme = dark` | Nada acontece. A sobreposição manual vence |
| SO muda o tema com `theme = dark` para claro e depois `theme` volta a `system` | `_apply()` com `detect_system_scheme()` no momento |
| Plataforma não reporta esquema (`Unknown`) | Tema claro, sempre, em qualquer sessão |
| App iniciado em `system` | O esquema é lido antes de `QApplication.setStyleSheet`, para não haver um primeiro frame no tema errado |
| Tema escuro e leitor | `page().setBackgroundColor(surface)` **antes** do primeiro `setHtml` da sessão. Caso contrário há um flash branco de ~1 frame |

### 7.6 Ícones SVG

**Onde entram.** `assets/icons/`, um arquivo por ícone, todos monoespaçados, desenhados em `viewBox="0 0 24 24"` com `stroke-width="2"`, `stroke-linecap="round"`, `stroke-linejoin="round"`, `fill="none"` (exceto `flag-filled.svg`, `check.svg` e `unread-dot.svg`, que usam `fill`). Nenhum ícone tem cor própria: o arquivo usa `stroke="#000000"`.

**Recoloração.** O Qt não suporta `currentColor` em SVG nem recolore por QSS. `styles.icon(name, size, token, dpr)` lê o SVG, substitui `#000000` pelo hexadecimal do token e renderiza com `QSvgRenderer` em um `QPixmap` de `size × dpr` com `setDevicePixelRatio(dpr)`, guardando o resultado em `_ICON_CACHE[(name, size, token, dpr)]`. A limpeza do cache acontece a cada troca de tema. Isso mantém um único conjunto de arquivos para os dois temas e garante nitidez em HiDPI.

`QIcon` resultante é aplicado com `setIconSize(QSize(size, size))`. `QIcon.addPixmap` recebe também os estados `On`/`Off` para ícones de alternância (`flag`/`flag-filled`, `sidebar-collapse`/`sidebar-expand`) — mas o aplicativo troca o nome do arquivo explicitamente em vez de depender de `QIcon.State`, porque o estado visual e o estado lógico do botão precisam coincidir mesmo durante a animação.

Lista completa de ícones da fase 1:

| Arquivo | Tamanho nominal de uso (px) | Onde |
|---|---|---|
| `compose.svg` | 20 | Sidebar header, trilho |
| `sidebar-collapse.svg` | 16 | Sidebar header |
| `sidebar-expand.svg` | 16 | Trilho |
| `chevron-left.svg` | 16 | Painel sobreposto, navegação |
| `chevron-right.svg` | 16 | Aninhamento de pasta |
| `chevron-down.svg` | 16 | Expansão de conta, painel de detalhes |
| `account.svg` | 16 / 48 | Nó de conta, estado vazio |
| `folder-inbox.svg` | 16 / 48 | Pasta Caixa de entrada, estado vazio |
| `folder-sent.svg` | 16 | Pasta Enviadas |
| `folder-drafts.svg` | 16 | Pasta Rascunhos |
| `folder-trash.svg` | 16 | Pasta Lixeira |
| `folder-archive.svg` | 16 | Pasta Arquivo |
| `folder-spam.svg` | 16 | Pasta Spam |
| `folder-custom.svg` | 16 | Pasta genérica |
| `search.svg` | 16 / 48 | Botão de busca, estado sem resultados |
| `close.svg` | 12 / 16 / 20 | Chips, banners, toasts |
| `sync.svg` | 12 / 16 | Indicador de conta, operação pendente |
| `sync-error.svg` | 12 | Indicador de conta em erro |
| `offline.svg` | 12 / 16 | Indicador de conta, faixa offline |
| `alert-triangle.svg` | 16 / 48 | Avisos, estado de erro |
| `info.svg` | 16 | Toasts informativos |
| `check.svg` | 16 | Toasts de sucesso, itens de menu marcados |
| `undo.svg` | 16 | Ação "Desfazer" do toast |
| `reply.svg` | 16 / 20 | Ação e indicador de respondida |
| `reply-all.svg` | 20 | Ação |
| `forward.svg` | 20 | Ação |
| `archive.svg` | 20 | Ação |
| `trash.svg` | 20 | Ação |
| `flag.svg` | 16 / 20 | Ação e indicador |
| `flag-filled.svg` | 12 / 20 | Indicador e ação ativa |
| `attachment.svg` | 12 / 14 | Indicador de linha, chip de anexo |
| `image-off.svg` | 16 | Banner de imagens bloqueadas |
| `shield.svg` | 14 | Aviso de rastreamento removido |
| `more-horizontal.svg` | 16 | Menus "mais ações" |
| `external-link.svg` | 14 | Diálogo de link externo |
| `send.svg` | 20 | Toast de Undo Send, botão de envio |
| `text-mode.svg` | 16 | Modo texto simples ativo |
| `mail-open.svg` | 64 | Leitor vazio |
| `zoom-in.svg` | 16 | Controle de zoom |
| `zoom-out.svg` | 16 | Controle de zoom |
| `unread-dot.svg` | 8 | Marca alternativa de não lido (usada apenas no trilho) |

Total: 39 arquivos. Todos são necessários na fase 1; nenhum é decoração.

---

## 8. Acessibilidade

### 8.1 Ordem de tabulação

Definida explicitamente com `QWidget.setTabOrder()`, na inicialização, na seguinte cadeia:

```text
sidebarTree
  → btnCompose (sidebar header)
  → btnCollapseSidebar
  → searchInput            (somente quando a SearchBar está visível)
  → btnClearSearch         (somente quando visível)
  → messageList
  → btnReply
  → btnReplyAll
  → btnForward
  → btnArchive
  → btnTrash
  → btnFlag
  → btnMore
  → readerFindInput        (somente quando visível)
  → readerWebView          (ou readerPlainText, no modo texto simples)
  → [volta para sidebarTree]
```

Regras:

- Widgets ocultos são retirados da cadeia automaticamente pelo Qt (`setVisible(False)` implica fora do `Tab`). A cadeia acima é reaplicada depois de cada mudança de visibilidade da `SearchBar`, porque `setTabOrder` opera sobre o widget, não sobre o índice.
- A `SelectionActionBar` **não** entra na cadeia: seus botões são alcançáveis por atalho (`E`, `D`, `I`, `S`) e o último elemento é o `btnClearSelection`, alcançável por `Esc`. Inserir quatro botões entre a busca e a lista faria `Tab` custar seis pressionamentos para sair do topo da coluna — pior para quem usa teclado, que é justamente o público-alvo.
- O `Toast` entra no fim da cadeia temporariamente, apenas quando contém ação, e é removido ao desaparecer.
- Dentro do `QWebEngineView`, `Tab` é consumido pelo Chromium para navegar entre elementos focáveis do HTML. Por isso existe `Ctrl+Tab` (§5.2) para sair do leitor sem depender de `Tab`. Este é um comportamento declarado, não um bug a corrigir.
- O `ComposerWindow` tem cadeia própria: `accountCombo` → `recipientInput` → `ccInput` → `bccInput` → `subjectEdit` → `bodyEditor` → `btnSend` → `btnAttach` → `btnMoreComposer` → [volta].
- O `QDialog` de Configurações usa a ordem declarada no `.ui`/código, com `setTabOrder` explícito, e sempre tem um botão padrão (`OK`) e um de escape (`Cancelar`) — `RF-SET-02` não define a ordem, mas nenhum formulário de configuração pode ter ordem implícita.

### 8.2 Indicador de foco visível

Valores, para cada superfície:

| Superfície | Indicador | Especificação |
|---|---|---|
| Botão, campo, combo (QSS) | Anel de 2 px | Borda de 2 px `focus-ring`, com a mesma borda reservada como `2px solid transparent` no estado padrão (§7.2). **Sem** deslocamento de layout: o indicador substitui uma borda já existente |
| Item de lista (`MessageItemDelegate`) | Retângulo de 2 px | `QPen(QColor(focus_ring), 2)`, `drawRoundedRect(rect.adjusted(1,1,-1,-1), 3, 3)`. Desenhado **depois** do conteúdo, para não ser coberto |
| Linha da sidebar (`SidebarDelegate`) | Retângulo de 2 px | `drawRoundedRect(rect.adjusted(1,1,-1,-1), 3, 3)` |
| `QTreeView` / `QListView` como um todo | Nenhum | `outline: 0` no QSS. O foco é sempre por item |
| `QWebEngineView` | Moldura de 2 px `focus-ring` | Aplicada por um `QFrame` contêiner com `QSS border`. Colocar o anel no próprio `QWebEngineView` é instável entre versões |
| Chip de filtro ativo | Anel de 2 px | Além do estado ativo (borda `accent` de 1 px), o foco adiciona 2 px `focus-ring` |
| `Toast` com ação | Anel no botão | Anel de 2 px no `QPushButton` da ação |

O anel de foco é mostrado **sempre** que o widget tem foco, inclusive quando o foco veio de um clique de mouse. A alternativa (`:focus-visible`, mostrar só para foco por teclado) exigiria um filtro de eventos que marca uma propriedade dinâmica, com `unpolish`/`polish` em cada mudança de widget — complexidade que não se paga e que introduz bugs de anel preso. Mostrar sempre é previsível, testável e mais acessível.

### 8.3 Nomes acessíveis

Todo widget interativo recebe `setAccessibleName()` e, quando o nome não basta, `setAccessibleDescription()`. Nomes de ação são **verbos com objeto**, nunca apenas ícone.

| Widget | `accessibleName` | `accessibleDescription` |
|---|---|---|
| `sidebarTree` | "Contas e pastas" | "Use as setas para navegar, Enter para abrir a pasta" |
| Nó de conta | "joao@exemplo.com, 3 não lidas, sincronizando" | — |
| Linha de pasta | "Caixa de entrada, 12 não lidas" | — |
| `railAccountButton` | "Conta joao@exemplo.com, 3 não lidas" | "Abre a lista de pastas desta conta" |
| `btnCompose` | "Escrever nova mensagem" | — |
| `btnCollapseSidebar` | "Recolher barra lateral" / "Expandir barra lateral" | — |
| `searchInput` | "Buscar mensagens" | "Busca por assunto, remetente e corpo. Insensível a acentos" |
| `btnClearSearch` | "Limpar busca" | — |
| Chip de filtro | "Filtro: não lidos, ativo" / "…, inativo" | — |
| `messageList` | "Lista de mensagens, 1.482 itens" (atualizado a cada mudança de pasta) | "Use J e K para navegar, Enter para abrir" |
| Item da lista (via modelo) | "Maria Silva. Re: Proposta comercial. Segue a proposta ajustada conforme conversa anterior. Hoje, 14:32. Não lida. Sinalizada. Com anexo." | Papel `AccessibleTextRole`, ver abaixo |
| `btnReply` | "Responder" | — |
| `btnReplyAll` | "Responder a todos" | — |
| `btnForward` | "Encaminhar" | — |
| `btnArchive` | "Arquivar mensagem" | — |
| `btnTrash` | "Mover para a lixeira" | "Pode ser desfeito com Ctrl+Z" (`[F2]`) |
| `btnFlag` | "Sinalizar mensagem" / "Remover sinalização" | — |
| `btnMore` | "Mais ações" | — |
| `btnZoomIn` / `btnZoomOut` | "Aumentar zoom" / "Diminuir zoom" | "Zoom atual: 100 por cento" |
| `readerWebView` | "Conteúdo da mensagem. <assunto>. De <remetente>. <data>." | Ver §8.5 |
| `readerPlainText` | Idem + ", modo texto simples" | — |
| `btnAllowSender` | "Carregar imagens deste remetente" | "Autoriza imagens de maria@exemplo.com em todas as mensagens futuras" |
| `recipientInput` | "Destinatários" | "Separe vários endereços com vírgula" |
| `subjectEdit` | "Assunto" | — |
| `bodyEditor` | "Corpo da mensagem" | — |
| `btnSend` | "Enviar mensagem" | "Ctrl e Enter" |
| Botão "Desfazer" do toast | "Desfazer o envio desta mensagem" | "A mensagem ainda não foi transmitida" |
| `Toast` (container) | Atualizado a cada estado: "Mensagem enviada para maria@exemplo.com. Enviando em 7 segundos." | Papel `QAccessible.Notification` via `QAccessibleEvent` |

**Item de lista e delegado customizado.** Como `MessageItemDelegate` pinta com `QPainter`, o Qt não consegue derivar o texto acessível do item. O modelo **precisa** fornecer os papéis explicitamente:

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole):
    row = self._row(index)
    if role == Qt.ItemDataRole.AccessibleTextRole:
        return self._accessible_text(row)              # conforme a tabela acima
    if role == Qt.ItemDataRole.AccessibleDescriptionRole:
        return f"Pasta {row.folder_name}. Pressione Enter para abrir."
    if role == Qt.ItemDataRole.DisplayRole:
        return row.subject or "(sem assunto)"
    ...
```

Sem isso, um leitor de tela anuncia apenas "item" para cada uma das 50.000 linhas. Este é o defeito de acessibilidade mais provável em um `QListView` com delegate próprio, e é o primeiro a verificar no procedimento manual PM-07.

### 8.4 Navegação completa por teclado

Verificação de cobertura: cada linha abaixo deve ser executável sem mouse. É a lista de verificação do PM-07.

| Tarefa | Somente teclado |
|---|---|
| Cadastrar uma conta | `Ctrl+,` → `Tab` até "Adicionar conta" → `Enter` → `Tab` pelos campos → `Enter` em "Testar conexão" → `Enter` em "Salvar" (critério 4 de `01-requisitos.md` §9) |
| Ler | `J`/`K` para navegar, `Enter` para focar o leitor, `Ctrl+Tab` para voltar |
| Selecionar texto do corpo | `Ctrl+Shift+T` (modo texto simples) → `Ctrl+A` → `Ctrl+C` |
| Arquivar | `E` |
| Descartar | `D` |
| Sinalizar / marcar lida | `S` / `I` |
| Selecionar várias e agir | `X` repetido, ou `Shift+J`, depois `E` |
| Buscar | `/` → digitar → `↓` → `Enter`; `Esc` para sair |
| Responder | `R` → digitar → `Ctrl+Enter` |
| Desfazer envio | `Ctrl+Z` enquanto o toast está visível |
| Alternar tema | `Ctrl+,` → `Tab` até Tema → setas → `Enter` |
| Alternar densidade | `Ctrl+Shift+D` |
| Ajuda | `?` |
| Colapsar sidebar | `Ctrl+\\` |
| Configurar tudo | `Ctrl+,` |

Nenhum fluxo depende de `hover`, de `tooltip` ou de clique com o botão direito. Os menus próprios (mais ações, conta no trilho, filtros) abrem com `Enter`/`Espaço` e são navegáveis com setas.

### 8.5 A área do `QWebEngineView` — limitação declarada

**A limitação, dita sem rodeio.** `QWebEngineView` é o componente menos acessível do aplicativo. O motor do Chromium só expõe sua árvore de acessibilidade ao sistema operacional quando o modo de acessibilidade do Chromium está ativo, o que depende de detecção de leitor de tela na plataforma ou de `QTWEBENGINE_CHROMIUM_FLAGS=--force-renderer-accessibility` definido **antes** da criação do `QApplication`. Ativar isso incondicionalmente tem custo de memória e de desempenho, e o suporte ainda é incompleto: a ordem de leitura dentro de um HTML complexo não é confiável, e a seleção de texto por teclado exige o modo de navegação por cursor (*caret browsing*), que precisa de flag própria. Não é possível afirmar que uma pessoa que usa leitor de tela consegue ler uma mensagem em HTML arbitrário por meio do `QWebEngineView`. Finjo que não é uma opção: a limitação é registrada aqui e no procedimento PM-10.

**O que é oferecido em substituição.** Quatro medidas, todas implementadas na fase 1:

1. **Modo texto simples (`Ctrl+Shift+T`).** Troca o `QWebEngineView` por um `QPlainTextEdit` somente leitura com `bodies.text_plain` — o mesmo texto derivado que alimenta o índice de busca (`RF-RD-02`). Um `QPlainTextEdit` é totalmente acessível: navegação por setas e `PageUp`/`PageDown`, seleção com `Shift`, `Ctrl+A`, `Ctrl+C`, e leitura linear e previsível pelo leitor de tela. O modo é uma preferência persistida (`ui.reader_plain_text_mode`) e a barra de ações do leitor mostra o ícone `text-mode.svg` quando está ativo. Se o `text_plain` não foi derivado (mensagem só em texto), o modo é idêntico e nada muda.
2. **Anúncio dos metadados.** Ao selecionar uma mensagem, o `accessibleName` do contêiner do leitor é atualizado com assunto, remetente e data, e um `QAccessibleEvent` de notificação é emitido. Assim, mesmo sem acesso ao corpo, a pessoa ouve quem escreveu, quando e sobre o quê — o suficiente para decidir se arquiva ou responde.
3. **Cabeçalhos brutos (`Ctrl+Shift+H`).** Um `QPlainTextEdit` monoespaçado com os cabeçalhos originais, para quem precisa verificar remetente real, `Reply-To`, cadeia de `Received` e `Authentication-Results`.
4. **Nenhuma informação exclusiva do HTML.** Tudo que a interface afirma — anexos, imagens bloqueadas, pixels de rastreamento removidos, link externo e seu destino real — aparece em widgets Qt (banners, diálogos, toasts) que são acessíveis, e nunca apenas dentro do HTML renderizado. O diálogo de link externo (§4.3.7) é o exemplo crítico: o destino real é anunciado por um `QLabel`, não por texto dentro da página.

**Restrição adicional.** Como `RF-RD-01` mantém JavaScript permanentemente desabilitado, não há como injetar um modo de acessibilidade dentro da página nem aplicar `aria-*` que altere a árvore de acessibilidade do Chromium. O CSS injetado (§4.3.5) pode melhorar legibilidade visual — tamanho de fonte, contraste, espaçamento — mas não é uma solução de acessibilidade assistiva.

### 8.6 Contraste

Os valores medidos estão em §2.5 e são a base de `RNF-A11Y-01`. Duas obrigações de implementação:

1. **Nenhum widget pode pintar texto com cor calculada em tempo de execução** (por exemplo, escurecer um token com `QColor.darker()`). Uma cor derivada deixa de ter razão de contraste conhecida. Se um estado novo precisar de cor nova, ele ganha um token em `styles.py` e uma linha na tabela de §2.5.
2. **O delegate, ao pintar a linha selecionada, usa `text-on-accent` para todos os papéis** (§2.5, exceção 3) e não desenha indicadores cujo token coincida com o fundo.

---

## 9. Critérios de aceite de UI

### 9.1 Critérios que já existem em `01-requisitos.md` §4.7

Estes critérios **não são reescritos aqui** e permanecem a autoridade:

| Critério | O que verifica | Como este documento o satisfaz |
|---|---|---|
| `CA-RF-UI-03-1` | Cada atalho ocorre com foco na lista e **não** ocorre com foco no corpo do compositor nem no campo de busca | §5.2 (tabela) e §5.4 (guarda de foco com `ShortcutOverride`) |
| `CA-RF-UI-04-1` | Digitar `c` no campo de busca insere `c` e não abre o compositor; `Esc` devolve o foco à lista e reativa os atalhos | §5.4 (conjunto exato de widgets) e §5.3 (regras 5–7, 10–12) |
| `CA-RF-UI-05-1` | 50.000 mensagens com rolagem fluida e sem um widget por mensagem | §4.2.5 (paginação de 200, `Batched`, delegate sem widget) |
| `CA-RF-UI-06-1` | Troca de tema do sistema altera cores sem reiniciar e sem recarregar a lista; a preferência manual sobrepõe e é persistida | §7.3 e §7.4 (`colorSchemeChanged`, `setStyleSheet`, `viewport().update()`, `config.toml`) |

Critérios correlatos que também se aplicam à interface: `CA-RF-RD-03-1` e `CA-RF-RD-03-2` (§4.3.3), `CA-RF-RD-04-1` (§4.3.4), `CA-RF-RD-06-1`, `CA-RF-RD-07-1` (§4.3.7), `CA-RF-SND-03-1` e `CA-RF-SND-03-2` (§4.6.1), `CA-RF-SND-04-1` e `CA-RF-SND-05-1` (§4.4.7), `CA-RF-ORG-04-1` (§4.2.6), `CA-RF-MSG-08-1` e `CA-RF-MSG-09-1` (§6.1), `CA-RF-SRCH-02-1` e `CA-RF-SRCH-05-1` (§4.5), `CA-RF-ACC-02-1` (§4.7), `CA-RF-ACC-03-1` (diálogo de conta), `CA-RF-SET-05-1` (§4.7, estado de erro global), `CA-RNF-PERF-01-1` (§6.8), `CA-RNF-PRIV-01-1` (§4.3.3), `CA-RNF-SEC-02-1` (§4.4.7, estado de TLS).

### 9.2 Requisitos de UI sem critério de aceite

A matriz de `01-requisitos.md` §8 marca estes requisitos como verificação manual (`M`) e sem `CA`. O procedimento correspondente está indicado; a ausência do critério no documento de requisitos está registrada em §10.

| Requisito | Procedimento |
|---|---|
| RF-UI-01 | PM-01 |
| RF-UI-02 | PM-01 |
| RF-UI-07 | PM-03 |
| RF-UI-09 | PM-02 |
| RF-UI-10 | PM-04 |
| RF-UI-11 | PM-05 |
| RF-RD-08 | PM-11 |
| RNF-USA-01 | PM-13 |
| RNF-A11Y-01 | PM-06, PM-07, PM-10 |
| RNF-COMP-01 | PM-08 |
| RNF-PERF-05 | PM-15 |

### 9.3 Procedimentos de verificação manual

Cada procedimento é executável por uma pessoa, sem conhecimento interno do código, com resultado observável.

**PM-01 — Layout de três colunas e colapso (RF-UI-01, RF-UI-02)**
1. Abrir o aplicativo com janela em 1280×800. Conferir que existem três colunas, com 248 px, 400 px e o restante, e que os dois divisores podem ser arrastados.
2. Arrastar o divisor da sidebar até 200 px e até 320 px. Confirmar que o arrasto para nesses limites.
3. Arrastar o divisor da lista até 320 px e até 640 px. Confirmar os limites.
4. Pressionar `Ctrl+\\`. Confirmar que a sidebar colapsa para 48 px em aproximadamente 180 ms e que o leitor cresce.
5. Fechar o aplicativo, reabrir. Confirmar que o estado colapsado e as larguras foram preservados.
6. Com a sidebar expandida, encolher a janela até 900 px de largura. Confirmar que a sidebar colapsa automaticamente para 48 px.
7. Alargar de volta para 1200 px. Confirmar que a sidebar volta a 248 px **sem** intervenção — o colapso automático não pode ter sobrescrito a preferência.
8. Encolher a janela até 800 px. Confirmar que o leitor vira painel sobreposto, com o botão "Voltar para a lista", e que a mensagem aberta permanece a mesma.
9. Tentar encolher a janela abaixo de 720×480. Confirmar que não é possível.

**PM-02 — Densidade (RF-UI-09)**
1. Com a lista populada, medir a altura de um item com uma captura de tela ampliada: deve ser exatamente 72 px em confortável.
2. Pressionar `Ctrl+Shift+D`. Medir novamente: 48 px.
3. Confirmar que a rolagem não voltou ao topo, que a seleção permaneceu e que o assunto e o trecho continuam visíveis na densidade compacta.
4. Reiniciar. Confirmar que a densidade escolhida persistiu.

**PM-03 — Estados de vazio, carregamento e erro (RF-UI-07)**
1. Abrir uma pasta vazia. Confirmar ícone, título, corpo e botão de ação — nunca uma área branca.
2. Remover todas as contas. Confirmar o estado vazio global com botão "Adicionar conta".
3. Com uma conta de 5.000 mensagens, iniciar a sincronização inicial em pasta ainda vazia. Confirmar as linhas esqueleto e a faixa de progresso, e que a interface responde a cliques durante a sincronização.
4. Buscar um termo inexistente. Confirmar o estado sem resultados com o termo exibido entre aspas angulares.
5. Apontar o host IMAP para um endereço inexistente e reiniciar. Confirmar que a mensagem distingue falha de DNS, recusa de conexão e credencial inválida (CA-RF-ACC-03-1) e que as outras contas continuam funcionando.

**PM-04 — Indicador de sincronização (RF-UI-10)**
1. Com uma conta configurada, disparar `Ctrl+R`. Confirmar que aparece um ícone girando de 12 px na linha da conta e que ele gira a aproximadamente uma volta por 1,2 s.
2. Desconectar a rede. Confirmar troca para `offline.svg` em `warning` e tooltip com a contagem regressiva.
3. Informar uma senha errada no keyring. Confirmar o ícone de pausa e o tooltip de reautenticação, e que a outra conta continua sincronizando.

**PM-05 — Pré-visualização da lista (RF-UI-11)**
1. Confirmar, em cinco mensagens distintas (lida, não lida, sinalizada, com anexo, sem assunto), a presença de remetente, assunto, trecho, data e dos três indicadores.
2. Confirmar que o não lido tem fundo `surface-unread` **e** barra de 3 px **e** pesos `600` — a diferença não pode depender só de cor.
3. Medir a razão de contraste do trecho (`text-muted` sobre `surface-unread`) em uma captura: deve ser ≥ 4,5:1.

**PM-06 — Contraste AA dos tokens (RNF-A11Y-01)**
1. Nos dois temas, capturar a tela com a interface em uso e medir com conta-gotas digital os 18 pares de §2.5.
2. Comparar com os valores publicados. Divergência acima de 2 % significa que um widget não está usando o token.
3. Confirmar visualmente que nenhum texto é desenhado com cor derivada: verificar as listas de seleção, os chips, os toasts e as faixas de aviso.

**PM-07 — Foco visível e navegação por teclado (RNF-A11Y-01)**
1. Percorrer a cadeia de §8.1 com `Tab`, conferindo que a cada passo existe um indicador de foco de 2 px visível, e que **nenhum** layout se desloca ao aparecer o indicador (comparar duas capturas).
2. Executar a tabela de §8.4 inteira sem tocar no mouse.
3. Com o foco na lista, injetar `C`, `E`, `D`, `/`, `J`, `K` — todos devem agir.
4. Com o foco em `searchInput`, digitar `c`, `e`, `d`, `j`, `k` — todos devem aparecer no campo, e nenhuma ação deve disparar.
5. Pressionar `Esc` no campo: o foco deve voltar à lista e `C` deve voltar a abrir o compositor.
6. Com o foco no compositor (corpo), digitar `c`, `e`, `d` — devem aparecer no texto.
7. Com o foco no leitor, injetar `J` e `E` — devem navegar e arquivar.
8. Com foco em cada botão do leitor, confirmar que `Enter`/`Espaço` acionam e que o nome acessível é um verbo com objeto (§8.3).

**PM-08 — Múltiplos monitores e DPI (RNF-COMP-01)**
1. Posicionar a janela no monitor secundário, fechar e reabrir. Confirmar reabertura no mesmo monitor e posição.
2. Desconectar o monitor secundário e reabrir. Confirmar que a janela abre centralizada na tela primária, totalmente visível.
3. Alterar a escala do sistema de 100 % para 150 % com o aplicativo aberto e depois reiniciá-lo. Confirmar que nenhum texto fica cortado, que os ícones SVG permanecem nítidos (sem borrão) e que as alturas de linha continuam em 72/48 px lógicos.
4. Arrastar a janela entre monitores com escalas diferentes. Confirmar que nada é reposicionado indevidamente.

**PM-09 — Renderização visual do HTML (imposto pelo ADR-003)**
Este procedimento existe porque `QWebEngineView` headless é frágil e a renderização **não** é verificável por teste automatizado (`02-arquitetura.md` §10).
1. Abrir o corpus de `tests/fixtures/eml/` com pelo menos uma mensagem de layout moderno (flexbox, grid, media query), uma com tabela aninhada de 2003 e uma com `@media print`.
2. Confirmar que a diagramação é fiel, sem sobreposição de texto e sem rolagem horizontal indevida.
3. Confirmar que `img { max-width: 100% }` está em vigor: nenhuma imagem estoura a largura do leitor.
4. Confirmar que o fundo do leitor acompanha o tema em ambos os modos, sem flash branco ao trocar de tema com uma mensagem aberta.
5. Confirmar que a barra de rolagem do leitor tem a mesma aparência (10 px, polegar `scrollbar-handle`) que a do resto do aplicativo.

**PM-10 — Leitor de tela (RNF-A11Y-01)**
1. Executar com NVDA (Windows) e Orca (Linux) e confirmar a leitura da cadeia de §8.1.
2. Confirmar que cada item da lista é anunciado com remetente, assunto, trecho, data e estado — e não como "item".
3. Abrir uma mensagem e confirmar que o anúncio do `accessibleName` do leitor ocorre ao selecionar.
4. Ativar `Ctrl+Shift+T` e confirmar que o texto do corpo é lido linearmente com setas.
5. **Registrar honestamente o que falha:** com o modo texto simples desativado, confirmar e documentar que a leitura do corpo em HTML não é confiável. Este resultado é esperado (§8.5) e a falha não é um defeito de implementação, mas o registro é obrigatório.

**PM-11 — Zoom persistente (RF-RD-08, verificação marcada como `M`)**
1. Abrir uma mensagem, aplicar `Ctrl+=` duas vezes (110 %, 125 %). Fechar e reabrir o aplicativo. Confirmar que o leitor abre em 125 %.
2. Navegar para outra mensagem e confirmar que o zoom se mantém.
3. `Ctrl+0` em qualquer mensagem. Confirmar o retorno a 100 %.
4. Levar o zoom a 25 % e a 400 % e confirmar que os botões desabilitam nos limites.

**PM-12 — Undo Send percebido (RF-SND-03)**
1. Enviar uma mensagem e cronometrar o toast: a contagem deve começar em 10 e o toast deve permanecer visível por 10 s.
2. Confirmar que a barra de progresso avança de forma linear e que o número de segundos acompanha.
3. Pressionar `Ctrl+Z` com o foco na lista: o envio deve ser cancelado e nenhuma conexão SMTP deve ter ocorrido (confirmar no servidor falso de `tests/fakes/`).
4. Repetir sem cancelar: confirmar que o toast muda para "Enviando…" e some.
5. Encerrar o aplicativo com uma mensagem no prazo e reabri-lo: o toast deve reaparecer com o tempo restante correto.

**PM-13 — Operação destrutiva (RNF-USA-01)**
1. Confirmar que arquivar, lixeira, sinalizar e marcar lida **não** pedem confirmação — são reversíveis e otimistas.
2. Confirmar que remover uma conta pede confirmação explícita com o volume de dados que será apagado (RF-ACC-05).
3. Confirmar que nenhuma operação destrutiva irreversível existe sem diálogo.

**PM-14 — Feedback em menos de 100 ms (RNF-USA-02, verificação marcada como `T`)**
1. Executar o teste automatizado de §6.8 (medição por atalho). Divergência acima de 100 ms em qualquer linha é falha.
2. Como complemento humano: com o servidor falso configurado para responder em 5 s, executar arquivar, sinalizar, marcar lida, abrir e enviar, e confirmar que **nenhuma** dessas ações parece lenta. Este é o teste que o usuário final faz, e ele não pode depender de cronômetro.

**PM-15 — Consumo de memória com o leitor aberto (RNF-PERF-05)**
1. Abrir o aplicativo com uma conta e uma mensagem aberta. Medir o RSS do processo principal: deve ficar abaixo de 400 MB.
2. Medir separadamente o RSS dos processos de `QtWebEngineProcess`. Este número **não** conta para `RNF-PERF-05` (a exclusão é declarada no requisito) e deve ser registrado no relatório de medição para substituir as estimativas de `01-requisitos.md` §6, conforme o backlog B-02 de `02-arquitetura.md` §11.

### 9.4 O que não é testável automaticamente

Registrado de forma explícita, porque a matriz de requisitos exige que todo critério seja verificável por teste **ou** por procedimento manual documentado — e estes são do segundo tipo:

| Item | Por que não é automatizável |
|---|---|
| Renderização visual do HTML | `QWebEngineView` em ambiente headless é frágil (`02-arquitetura.md` §10); comparar imagem exigiria tolerância a diferenças de fonte e de GPU entre plataformas |
| Multi-monitor e troca de DPI | Requer hardware e configuração do sistema operacional |
| Leitor de tela | Requer NVDA/Orca/Narrator e julgamento humano sobre a inteligibilidade do anúncio |
| Percepção de fluidez da rolagem | É uma medida humana; o teste automatizado mede criação de widgets, não fluidez percebida |
| Contraste em tela renderizada | Os tokens podem ser verificados por teste, mas a cor efetivamente pintada em cada widget depende da plataforma e do tema nativo |
| Aparência das barras de rolagem do Chromium | Dependentes do motor; a verificação é visual |
| Diálogos nativos (`QFileDialog`, menu de bandeja do SO) | Não são estilizáveis nem inspecionáveis de forma portável |
| Fonte efetivamente usada | Depende das fontes instaladas na máquina; a cadeia de fallback só pode ser validada em execução real |
| Comportamento do gerenciador de janelas | A posição e a decoração da janela diferem entre Windows, GNOME/KDE e macOS |

### 9.5 Rastreabilidade requisito de UI → seção deste documento

| Requisito | Seção |
|---|---|
| RF-UI-01 | §3.1, §3.3 |
| RF-UI-02 | §3.2, §3.5 |
| RF-UI-03 | §5.2 |
| RF-UI-04 | §5.3, §5.4 |
| RF-UI-05 | §4.2.5 |
| RF-UI-06 | §7.3, §7.4, §7.5 |
| RF-UI-07 | §4.2.7, §4.3.8, §4.7 |
| RF-UI-08 | §4.7, §6.7 |
| RF-UI-09 | §4.2.2, §4.2.3 |
| RF-UI-10 | §4.1 |
| RF-UI-11 | §4.2.2, §4.2.3, §4.2.4 |
| RF-UI-12 `[F2]` | Não especificado na fase 1. Ponto de extensão: o leitor já reserva a faixa de cabeçalho (§4.3.1) e `messages.thread_id` já existe |
| RF-RD-03 | §4.3.3 |
| RF-RD-04 | §4.3.4, §6.6 |
| RF-RD-05 | §4.3.7 |
| RF-RD-07 | §4.3.7 |
| RF-RD-08 | §4.3.6 |
| RF-RD-09 | §6.2 |
| RF-SND-03 | §4.6.1, §6.4 |
| RF-SND-05 | §4.4.7 |
| RF-SND-06 | §4.4.5 |
| RF-SND-07 | §4.4.7 |
| RF-SND-08 | §4.4.6 |
| RF-SRCH-02 | §4.5 |
| RF-SRCH-03 | §4.5 |
| RF-SRCH-05 | §4.5 |
| RF-ORG-01..05 | §4.2.6, §6.1 |
| RF-ORG-06 `[F2]` | §5.2 (`Ctrl+Z`, segundo nível) |
| RF-MSG-08 | §4.7, §6.7 |
| RF-MSG-09 | §4.2.4, §6.1 |
| RNF-USA-01 | §4.4.5, §4.4.6, §5.3, §9.3 (PM-13) |
| RNF-USA-02 | §6.8 |
| RNF-A11Y-01 | §8 (completo) |
| RNF-PRIV-04 | §4.3.3, §4.3.2 (menu "Autorizações de imagens…") |

---

## 10. Lacunas identificadas

Necessidades reais encontradas durante a especificação da interface que **não** correspondem a nenhum requisito existente em `01-requisitos.md`. Nenhum ID novo foi criado. Cada item indica onde a lacuna aparece e o que ela impede hoje.

| # | Lacuna | Onde apareceu | Consequência de não resolver |
|---|---|---|---|
| L-01 | **Não há requisito de cobertura de testes para `ui/`.** `RNF-MAINT-01` fixa ≥ 80 % apenas para `core/`. As partes mais testáveis e mais propensas a regressão da interface — `_blocks_letter_shortcuts`, `build_match_query` aplicado ao destaque, `MessageItemDelegate.sizeHint` por densidade, a cascata de `Esc`, `build_qss` com token inexistente, a geometria de `ToastManager` — estão fora de qualquer meta de cobertura | `01-requisitos.md` §5.4, RNF-MAINT-01 | Os defeitos de interface que este documento tenta prevenir por especificação (guarda de foco, cascata de `Esc`) não têm teste obrigatório que os mantenha corretos |
| L-02 | **`RNF-A11Y-01` não tem critério de aceite.** Exige "contraste mínimo AA nas duas folhas de estilo", mas nenhum `CA-RNF-A11Y-01-*` existe para verificar a razão de contraste de cada par de tokens. A matriz de §8 de `01-requisitos.md` marca a verificação como `M` sem CA | `01-requisitos.md` §5.4 e §8 | A afirmação "atinge AA" fica sem prova. O cálculo de §2.5 deste documento poderia virar um teste de unidade trivial, mas não há requisito que o exija |
| L-03 | **Nenhum requisito sobre comportamento responsivo.** `RF-UI-01` fixa três colunas sem definir o que acontece quando a janela não comporta as três, nem a largura mínima da janela, nem o que colapsa primeiro | `01-requisitos.md` §4.7 | A §3.4 deste documento é uma decisão de design sem requisito que a ancore. Uma implementação futura pode mudá-la sem violar nada |
| L-04 | **Nenhum requisito sobre o painel de gerenciamento das autorizações de imagens.** `RNF-PRIV-04` diz que a autorização deve ser "gerenciável em um painel", mas não existe RF descrevendo esse painel: onde fica, o que lista, como revoga em massa, se mostra data de autorização, se permite bloquear um remetente que já foi autorizado | `01-requisitos.md` §5.3 | `RNF-PRIV-04` é inimplementável como requisito verificável: não se sabe o que construir, nem como provar que é revogável |
| L-05 | **Nenhum requisito para busca dentro da mensagem (*find in page*).** Ler uma mensagem longa e localizar um termo é uso básico, e o Qt oferece `QWebEnginePage.findText`, que funciona com JavaScript desabilitado | §4.3.2 (`Ctrl+F`), §5.2 | A funcionalidade entra na fase 1 por decisão de design, sem requisito nem critério de aceite — e, portanto, sem rastreabilidade e sem teste obrigatório |
| L-06 | **Ambiguidade em `RF-RD-08`.** "Persistindo a preferência por mensagem lida e como padrão do aplicativo" admite duas leituras: (a) o zoom é por mensagem individual, ou (b) o zoom aplicado ao ler uma mensagem passa a ser o padrão global. A §4.3.6 adota (b), que é a leitura simples e compatível com o schema — não há tabela para zoom por mensagem, e criar uma seria uma migração | `01-requisitos.md` §4.3 | Sem esclarecimento, a implementação escolhe uma das duas e o CA correspondente (que também não existe) não pode ser escrito |
| L-07 | **Nenhum requisito sobre idioma, localização e formatação.** Toda esta especificação está em português do Brasil, mas não há `RNF` ou `RF` que determine o idioma da interface, o uso de `QLocale` para data e hora, a formatação de tamanho de arquivo (`formattedDataSize`) ou a pluralização ("1 mensagem" / "2 mensagens"). `RNF-COMP-01` fixa três plataformas em três idiomas de sistema diferentes | Todo o documento (textos de estado, datas, tamanhos) | Não se sabe se o aplicativo deve traduzir. Um cliente usado em macOS em inglês exibirá "Nenhuma mensagem selecionada" — decisão que precisa ser consciente, não acidental |
| L-08 | **Nenhum requisito sobre respeitar a preferência de movimento reduzido do sistema operacional.** As animações de §2.3 (colapso de sidebar, entrada de toast, recolhimento de linha) não têm contrapartida para quem configura redução de movimento no SO | §2.3, §3.2, §6.1 | Um requisito de acessibilidade razoável (`RNF-A11Y`) fica de fora e a interface mantém 180 ms de animação para todo mundo |
| L-09 | **Nenhum requisito sobre o comportamento de fechamento da janela com trabalho pendente.** `RF-SND-04` garante que rascunhos e fila sobrevivem ao reinício, mas não define o que o usuário vê ao fechar: confirmação, segundo plano, ou saída silenciosa. Também não há requisito sobre ícone de bandeja ou notificações de novas mensagens | §5.2 (`Ctrl+Q`), §6.4 | O `Ctrl+Q` de §5.2 inventa um diálogo de confirmação que nenhum requisito pede. E fica indefinido se o aplicativo deve notificar novas mensagens fora da janela |
| L-10 | **Nenhum requisito sobre o comportamento de notificação e sobre o limite de desfazer.** `RNF-USA-01` exige confirmação ou desfazer, sem definir por quanto tempo o desfazer fica disponível, quantos podem coexistir, nem o que acontece quando dois desfazer se sobrepõem | §4.6 | O limite de 3 toasts e as durações de §4.6 são decisões de design sem base em requisito. Duas operações destrutivas encadeadas podem ficar sem desfazer, e nada no requisito diz se isso é aceitável |
| L-11 | **`RF-UI-02` não tem critério de aceite.** A matriz de `01-requisitos.md` §8 marca verificação `T` para RF-UI-02 e deixa a coluna de CA vazia. O mesmo vale para `RF-UI-01`, `RF-UI-07`, `RF-UI-09`, `RF-UI-10` e `RF-UI-11`, marcados `M` sem CA | `01-requisitos.md` §8 | O §2 de `01-requisitos.md` é explícito: "Requisito sem critério de aceite é requisito mal escrito e deve ser reescrito, não implementado." Seis requisitos de interface violam essa regra. Os procedimentos PM-01 a PM-05 deste documento podem virar esses critérios |
| L-12 | **Nenhum requisito sobre aviso de destinatário externo ou de "responder a todos" perigoso.** Clientes corporativos e até o Gmail alertam quando uma resposta vai para muitos destinatários ou para fora do domínio. `RF-SND-02` define "responder a todos" sem nenhuma salvaguarda | §4.3.2 (`btnReplyAll`) | O erro de responder a todos por acidente é caro e socialmente irreversível — não há desfazer para e-mail enviado. A interface não tem como mitigar sem requisito |
| L-13 | **Nenhum requisito sobre o indicador de uso do cache de corpos.** `RF-MSG-06` define limite de 500 MB e despejo LRU, mas não pede que o usuário possa ver quanto o cache ocupa. Sem essa visibilidade, um despejo que apaga o HTML de uma mensagem é indistinguível de uma lentidão de rede para quem usa o aplicativo | §4.1 (rodapé da sidebar) | A decisão de mostrar "Cache: 312 MB de 500 MB" é de design, sem requisito. Fica também sem resposta se o usuário deve poder limpar o cache manualmente |
| L-14 | **Nenhum requisito sobre o contrato de `E`/`Backspace` quanto à pasta de arquivo por conta.** `RF-ORG-01` diz "a pasta de arquivo (criando-a se não existir)" sem definir o nome remoto, o que é ambíguo justamente onde a interface precisa mostrar o destino: em um servidor em português existe "Arquivo", em inglês "Archive", e em servidores com `[Gmail]/All Mail` a semântica é outra | §4.1, §6.1 | A interface não sabe qual nome exibir no `Toast` de arquivamento nem na confirmação de criação de pasta. Não é uma lacuna de UI a resolver sozinha, mas a UI depende dela |

**Observação sobre L-14 e os itens não-UI.** L-06, L-12 e L-14 são lacunas que a especificação de interface revelou mas cuja decisão pertence aos requisitos, não ao `ui/`. Estão listadas por terem sido encontradas aqui, conforme a instrução de registrá-las sem criar IDs.
