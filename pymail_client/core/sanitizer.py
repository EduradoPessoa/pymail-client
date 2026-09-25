"""Sanitização de HTML e pipeline de privacidade.

Implementa `05-seguranca-privacidade.md` §4. É a funcionalidade central do
produto: um e-mail é conteúdo hostil por definição, e é aqui que ele deixa de
ser. Função pura, sem I/O — roda no `TaskPool`, nunca na thread da GUI.

Ordem normativa do pipeline (§4.1). Não reordene sem ler §4.1.1:

    0. `normalize_input`      decodifica, remove BOM/NUL, aplica teto de tamanho
    1. `structure_pass`       nh3 passe A — allowlist; DESCARTA `data-pymail-*`
    2. `privacy_rewrite`      html5lib — remove pixels, limpa rastreamento,
                              move `src` para `data-pymail-src`, remove `src`
    3. `seal_pass`            nh3 passe B — autoridade estrutural FINAL
    4. `scan`                 contagens para o `SanitizeReport`
    5. `html_to_text_plain`   derivado do HTML JÁ sanitizado, nunca do cru
    6. `wrap_document`        `<head>` com CSP e `referrer`, montados por nós
    7. persistência           fora deste módulo (`Storage.store_body`)
    8. `restore_remote_images` inverso de 2c + selo de novo

Duas resoluções de ambiguidade da spec, registradas porque a implementação
depende delas:

**`src` em `<img>`.** §4.3 lista os atributos de `img` sem `src` ("quem o
escreve é o passo 2 ou a restauração"), mas §4.1 passo 2c precisa *ler* o `src`
para movê-lo. §4.4 resolve a contradição ao dizer "Imagem (`src` **antes do
passo 2**)". Portanto: o passe A **mantém** `src` (senão o passo 2 não teria o
que ler) e o passe B o remove. Há duas variantes de allowlist de selo — uma
para o artefato gravado, sem `src`; outra para renderização, com `src`.

**H4 não vê `transform`/`clip`/`clip-path`.** §5.1 H4 lista esses sinais de
ocultação, mas §4.5.3 não os admite na allowlist de CSS, então o filtro os
remove no passe A e a heurística nunca os lê. Implementado o subconjunto que
sobrevive (`display`, `visibility`, `opacity`, `height`, `max-height`, `width`,
`max-width`, `overflow`), que cobre os pixels reais. A lacuna está reportada
como defeito de spec, não silenciada em código.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import html5lib
import nh3
import tinycss2
from html5lib.serializer import serialize as _html5_serialize

# ─────────────────────────────── Versão e tetos ───────────────────────────────

#: §4.7.5 — incrementar a cada mudança de allowlist, esquemas, propriedades CSS,
#: heurística de pixel ou lista de parâmetros. Um incremento marca os corpos
#: antigos para rebusca sob demanda (`03-modelo-de-dados.md` §6.3).
SANITIZER_VERSION: Final[int] = 1

MAX_HTML_BYTES: Final[int] = 5 * 1024 * 1024
MAX_STYLE_LENGTH: Final[int] = 4096
MAX_CSS_DECLARATIONS: Final[int] = 32
MAX_CSS_VALUE_LENGTH: Final[int] = 256
MAX_CSS_FUNCTION_DEPTH: Final[int] = 8
MAX_URL_LENGTH: Final[int] = 8192
MAX_TEXT_ATTRIBUTE: Final[int] = 512
MAX_ARIA_ATTRIBUTE: Final[int] = 256

# ──────────────────────────── Allowlist de tags (§4.2) ────────────────────────

ALLOWED_TAGS: Final[frozenset[str]] = frozenset(
    """
    a abbr address article aside b bdi bdo blockquote br caption center cite code
    col colgroup dd del details dfn div dl dt em figcaption figure footer h1 h2
    h3 h4 h5 h6 header hr i img ins kbd li main mark nav ol p pre q s samp
    section small span strike strong sub summary sup table tbody td tfoot th
    thead time tr tt u ul var wbr
    """.split()
)

#: §4.2 — sem isto o `nh3` preserva o **conteúdo textual** de uma tag descartada,
#: e o corpo de um `<script>` viraria texto visível e seria indexado pelo FTS5.
CLEAN_CONTENT_TAGS: Final[frozenset[str]] = frozenset({"script", "style"})

# ────────────────────────── Allowlist de atributos (§4.3) ─────────────────────

_GLOBAL_ATTRS: Final[frozenset[str]] = frozenset({"style", "title", "dir", "lang", "role"})

ARIA_ALLOWED_ROLES: Final[frozenset[str]] = frozenset(
    """
    alert alertdialog application article banner button cell checkbox columnheader
    combobox complementary contentinfo definition dialog directory document feed
    figure form grid gridcell group heading img link list listbox listitem log
    main marquee math menu menubar menuitem meter navigation none note option
    presentation progress radio radiogroup region row rowgroup rowheader
    scrollbar search separator slider spinbutton status switch tab table tablist
    tabpanel term textbox timer toolbar tooltip tree treegrid treeitem
    """.split()
)

# Passe A: lê `src` para o passo 2 poder reescrevê-lo (§4.4, "src antes do passo 2").
# `hidden` entra aqui, e SÓ aqui, por causa de H3 (§5.1.1): a heurística de pixel
# roda depois deste passe e precisa do sinal. O selo não o admite, então um
# `hidden` que não caracterize pixel não chega ao artefato final.
_ATTRS_PASS_A: Final[dict[str, frozenset[str]]] = {
    "*": _GLOBAL_ATTRS,
    "a": frozenset({"href"}),
    "img": frozenset({"src", "alt", "width", "height", "hidden"}),
    "td": frozenset(
        {"colspan", "rowspan", "align", "valign", "width", "height", "headers", "scope"}
    ),
    "th": frozenset(
        {"colspan", "rowspan", "align", "valign", "width", "height", "headers", "scope"}
    ),
    "table": frozenset({"border", "cellpadding", "cellspacing", "width", "align", "summary"}),
    "col": frozenset({"span", "width"}),
    "colgroup": frozenset({"span", "width"}),
    "ol": frozenset({"start", "type", "reversed"}),
    "li": frozenset({"value"}),
    "blockquote": frozenset({"cite"}),
    "q": frozenset({"cite"}),
    "del": frozenset({"datetime"}),
    "ins": frozenset({"datetime"}),
    "time": frozenset({"datetime"}),
    "details": frozenset({"open"}),
}

# Passe B do artefato GRAVADO: sem `src`, com os marcadores de restauração.
_ATTRS_SEAL_STORED: Final[dict[str, frozenset[str]]] = {
    **_ATTRS_PASS_A,
    "img": frozenset({"alt", "width", "height", "data-pymail-src", "data-pymail-cid"}),
}

# Selo de RENDERIZAÇÃO: `src` (escrito pela restauração), SEM `data-pymail-*`.
# É o invariante de §4.7.1: toda string que chega ao motor passa pelo `nh3`
# como última transformação estrutural, e nenhuma carrega os nossos marcadores.
_ATTRS_SEAL_RENDER: Final[dict[str, frozenset[str]]] = {
    **_ATTRS_PASS_A,
    "img": frozenset({"src", "alt", "width", "height"}),
}

#: §4.3 — nunca permitidos, em nenhuma tag, em nenhum passe. `on*` é coberto por
#: prefixo no filtro; `id`/`class` por decisão explícita (nada os referencia).
NEVER_ALLOWED_ATTRS: Final[frozenset[str]] = frozenset(
    """
    srcset imagesrcset sizes imagesizes background poster lowsrc dynsrc formaction
    action method ping manifest data codebase archive classid usemap srcdoc
    sandbox http-equiv content target rel download integrity nonce crossorigin
    referrerpolicy autofocus autoplay controls loop muted preload xlink:href
    xml:base xmlns id class name slot is part exportparts
    """.split()
)

# ───────────────────────────── Esquemas de URL (§4.4) ─────────────────────────

#: `data` deliberadamente fora: bloqueio integral na fase 1, inclusive para
#: imagens base64 legítimas (§4.4, com o custo declarado).
NH3_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "mailto", "cid"})
LINK_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "mailto"})
IMAGE_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

_SCHEME_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_CONTROL_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_LANG_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8}){0,2}$")
_DATETIME_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)

# ──────────────────────── CSS no atributo `style` (§4.5) ──────────────────────

ALLOWED_CSS_PROPERTIES: Final[frozenset[str]] = frozenset(
    """
    background-color border border-bottom border-bottom-color border-bottom-style
    border-bottom-width border-collapse border-color border-left border-left-color
    border-left-style border-left-width border-radius border-right
    border-right-color border-right-style border-right-width border-spacing
    border-style border-top border-top-color border-top-style border-top-width
    border-width bottom caption-side clear color direction display empty-cells
    float font font-family font-size font-style font-variant font-weight height
    left letter-spacing line-height list-style list-style-position list-style-type
    margin margin-bottom margin-left margin-right margin-top max-height max-width
    min-height min-width opacity overflow overflow-x overflow-y padding
    padding-bottom padding-left padding-right padding-top position right
    table-layout text-align text-decoration text-decoration-color text-indent
    text-transform top unicode-bidi vertical-align visibility white-space width
    word-break word-spacing word-wrap z-index
    """.split()
)

ALLOWED_CSS_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"rgb", "rgba", "hsl", "hsla", "calc", "min", "max", "clamp"}
)

#: §4.5.3 — carregam recurso ou avaliam expressão. A declaração inteira cai.
FORBIDDEN_CSS_FUNCTIONS: Final[frozenset[str]] = frozenset(
    """
    url var attr expression image image-set -webkit-image-set cross-fade element
    paint src format local counter counters symbols
    """.split()
)

_CSS_ENUMS: Final[dict[str, frozenset[str]]] = {
    "position": frozenset({"static", "relative"}),
    "overflow": frozenset({"visible", "hidden"}),
    "overflow-x": frozenset({"visible", "hidden"}),
    "overflow-y": frozenset({"visible", "hidden"}),
    "visibility": frozenset({"visible", "hidden", "collapse"}),
    "display": frozenset(
        """
        block inline inline-block flex inline-flex grid inline-grid table
        inline-table table-row table-cell table-row-group table-header-group
        table-footer-group table-column table-column-group list-item none contents
        """.split()
    ),
    "clear": frozenset({"none", "left", "right", "both"}),
    "float": frozenset({"none", "left", "right"}),
    "direction": frozenset({"ltr", "rtl"}),
    "text-align": frozenset({"left", "right", "center", "justify", "start", "end"}),
    "vertical-align": frozenset(
        {"baseline", "sub", "super", "top", "text-top", "middle", "bottom", "text-bottom"}
    ),
    "text-transform": frozenset({"none", "capitalize", "uppercase", "lowercase"}),
    "white-space": frozenset({"normal", "nowrap", "pre", "pre-wrap", "pre-line", "break-spaces"}),
    "border-collapse": frozenset({"collapse", "separate"}),
    "table-layout": frozenset({"auto", "fixed"}),
    "list-style-position": frozenset({"inside", "outside"}),
    "align": frozenset({"left", "center", "right", "justify", "char"}),
    "valign": frozenset({"top", "middle", "bottom", "baseline"}),
}

_LENGTH_RE: Final[re.Pattern[str]] = re.compile(r"^(-?\d+(?:\.\d+)?)(px|%|em|rem|pt|vh|vw|ch|ex)?$")
_COLOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|(?:rgb|rgba|hsl|hsla)\(.*\))$"
)
_INTEGER_RE: Final[re.Pattern[str]] = re.compile(r"^-?\d+$")

#: §4.5.3 — faixas numéricas. `None` em `min`/`max` significa sem limite.
_LENGTH_RANGES: Final[dict[str, tuple[float | None, float | None, bool, float | None]]] = {
    # propriedade: (min_px, max_px, aceita_%, max_%)
    "top": (-1000, 1000, False, 0),
    "right": (-1000, 1000, False, 0),
    "bottom": (-1000, 1000, False, 0),
    "left": (-1000, 1000, False, 0),
    "width": (0, 4096, True, 100),
    "height": (0, 4096, True, 100),
    "min-width": (0, 4096, True, 100),
    "min-height": (0, 4096, True, 100),
    "max-width": (0, 4096, True, 100),
    "max-height": (0, 4096, True, 100),
    "font-size": (0, 256, True, 1000),
}

_COLOR_PROPERTIES: Final[frozenset[str]] = frozenset(
    {
        "color",
        "background-color",
        "border-color",
        "border-top-color",
        "border-bottom-color",
        "border-left-color",
        "border-right-color",
        "text-decoration-color",
    }
)

# ───────────────────── Parâmetros de rastreamento (§5.2) ──────────────────────

#: `utm_*` é tratado por PREFIXO: enumerar variantes é trabalho perdido.
TRACKING_PARAM_PREFIXES: Final[tuple[str, ...]] = ("utm_",)

TRACKING_PARAMS: Final[frozenset[str]] = frozenset(
    """
    fbclid gclid mc_eid _hsenc _hsmi vero_id igshid
    gclsrc dclid msclkid yclid wbraid gbraid twclid ttclid epik s_cid sc_cid
    mkt_tok _ke _ga _gl _openstat mc_cid pk_campaign pk_kwd mtm_campaign mtm_source
    mtm_medium mtm_content mtm_term oly_anon_id oly_enc_id _branch_match_id
    wickedid spm scm cmpid si ref_src ref_url
    """.split()
)

#: §5.2.2 — um nome errado aqui quebra funcionalidade em silêncio. A asserção
#: no fim do módulo impede que alguém acrescente um destes à lista de remoção.
NEVER_REMOVE_PARAMS: Final[frozenset[str]] = frozenset(
    """
    id ids code token key api_key apikey sig signature hash nonce state session
    sid auth access_token refresh_token expires exp expiring ts t v p q s n page
    paged offset limit start end date lang locale hl ie oe
    """.split()
)

# ─────────────────────── Heurísticas de pixel (§5.1.1) ────────────────────────

_PIXEL_FILENAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(pixel|beacon|open|track|spacer|blank|clear|transparent|1x1|dot)"
    r"(\.(gif|png|jpg|jpeg))?($|[?#])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SanitizeContext:
    """Entrada da sanitização. `allow_remote_images` decide apenas a CSP."""

    allow_remote_images: bool = False


@dataclass
class SanitizeReport:
    """Contagens do que o pipeline fez (§4.1, passo 4). Lido pela interface e
    pelos testes — nunca contém URLs, que são o identificador de rastreamento."""

    pixels_removed: int = 0
    tracking_params_removed: int = 0
    remote_images_preserved: int = 0
    restorable_images: int = 0
    urls_discarded: int = 0
    css_declarations_dropped: int = 0
    attributes_dropped: int = 0
    truncated: bool = False
    rejected_schemes: dict[str, int] = field(default_factory=dict)

    def _bump_scheme(self, scheme: str) -> None:
        self.rejected_schemes[scheme] = self.rejected_schemes.get(scheme, 0) + 1


# ═══════════════════════════ Passo 0 — normalize_input ════════════════════════


def normalize_input(raw: str | bytes, charset: str | None = None) -> tuple[str, bool]:
    """§4.1 passo 0. Devolve `(html, truncado)`.

    O `NUL` é removido porque pode truncar a leitura em camadas que tratam a
    cadeia como C-string, produzindo divergência entre o que o sanitizador vê e
    o que o motor vê — a definição de *parser differential*.
    """
    if isinstance(raw, bytes):
        text: str | None = None
        for encoding in (charset, "utf-8", "latin-1"):
            if not encoding:
                continue
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:  # pragma: no cover - latin-1 nunca falha
            text = raw.decode("utf-8", errors="replace")
    else:
        text = raw

    truncated = False
    if len(text) > MAX_HTML_BYTES:
        text = text[:MAX_HTML_BYTES]
        truncated = True

    text = text.lstrip("\ufeff")  # BOM
    text = text.replace("\x00", "")  # NUL, em qualquer posição
    return text, truncated


# ══════════════════════ Passos 1 e 3 — passes do `nh3` ════════════════════════


def _split_style(style: str) -> list[tuple[str, str]]:
    """Declarações `(propriedade, valor)` sobreviventes. Usado pela heurística H4
    e pelo próprio filtro — sempre sobre o valor já filtrado."""
    declarations: list[tuple[str, str]] = []
    for node in tinycss2.parse_declaration_list(style, skip_comments=True, skip_whitespace=True):
        if node.type != "declaration":
            continue
        declarations.append((node.lower_name, tinycss2.serialize(node.value).strip()))
    return declarations


def _serialize_tokens(tokens) -> str:  # noqa: ANN001 - API do tinycss2
    """Serializa tokens removendo `!important` (§4.5.3)."""
    parts: list[str] = []
    for token in tokens:
        if token.type == "literal" and token.value == "!":
            continue
        if getattr(token, "lower_value", None) == "important" and token.type == "ident":
            continue
        parts.append(tinycss2.serialize([token]))
    return "".join(parts).strip()


def _function_depth(tokens, depth: int = 0) -> int:  # noqa: ANN001
    """Profundidade máxima de aninhamento de funções (§4.5.4)."""
    worst = depth
    for token in tokens:
        if token.type == "function":
            worst = max(worst, _function_depth(token.arguments, depth + 1))
    return worst


def _has_forbidden_construct(tokens) -> bool:  # noqa: ANN001
    """`url()`, `var()`, `expression()`, `attr()` e afins, em qualquer posição e
    com qualquer escape — o tokenizador resolve escapes e comentários, uma busca
    textual não resolveria (§4.5.1)."""
    for token in tokens:
        ttype = token.type
        if ttype == "url":
            return True
        if ttype == "function":
            name = (token.lower_name or "").strip()
            if name in FORBIDDEN_CSS_FUNCTIONS or name.startswith("-"):
                return True
            if name not in ALLOWED_CSS_FUNCTIONS:
                return True
            if _has_forbidden_construct(token.arguments):
                return True
        elif ttype in {"() block", "[] block", "{} block"}:
            return True
    return False


def _validate_length(prop: str, value: str) -> bool:
    match = _LENGTH_RE.match(value)
    if not match:
        return (
            prop
            in {
                "width",
                "height",
                "min-width",
                "min-height",
                "max-width",
                "max-height",
                "top",
                "right",
                "bottom",
                "left",
            }
            and value == "0"
        )
    number = float(match.group(1))
    unit = match.group(2)
    min_px, max_px, allow_pct, max_pct = _LENGTH_RANGES[prop]
    if unit == "%":
        return allow_pct and 0 <= number <= max_pct
    if unit in (None, "px"):
        px = number
    elif unit in ("em", "rem"):
        px = number * 16.0
    elif unit == "pt":
        px = number * 4 / 3
    else:  # vh/vw/ch/ex — magnitude checada, sem conversão fiel de viewport
        return abs(number) <= 100
    if min_px is not None and px < min_px:
        return False
    if max_px is not None and px > max_px:
        return False
    return True


def _validate_css_value(prop: str, value: str) -> bool:
    """Allowlist de valores por propriedade (§4.5.3). Na dúvida, recusa — é uma
    allowlist, e o erro dela é visível (formatação perdida), não explorável."""
    if prop in _CSS_ENUMS:
        return value.lower() in _CSS_ENUMS[prop]
    if prop == "opacity":
        try:
            return 0.0 <= float(value) <= 1.0
        except ValueError:
            return False
    if prop == "z-index":
        return bool(_INTEGER_RE.match(value)) and -100 <= int(value) <= 100
    if prop in _LENGTH_RANGES:
        return _validate_length(prop, value)
    if prop in _COLOR_PROPERTIES:
        return bool(_COLOR_RE.match(value))
    # Demais propriedades: escalar de formato conhecido, ou função permitida.
    if _LENGTH_RE.match(value) or _INTEGER_RE.match(value) or _COLOR_RE.match(value):
        return True
    if re.match(r"^[a-zA-Z-]+$", value):  # palavra-chave enumerada
        return True
    if re.match(r"^(?:rgb|rgba|hsl|hsla|calc|min|max|clamp)\(", value):
        return True
    if all(ch.isalnum() or ch in " #%,.()-/" for ch in value):
        return len(value) <= 64
    return False


def filter_style(style: str, report: SanitizeReport | None = None) -> str | None:
    """§4.5 — filtro do atributo `style`. Devolve a cadeia sobrevivente ou
    `None` quando o atributo inteiro deve ser descartado."""
    if len(style) > MAX_STYLE_LENGTH:
        if report:
            report.attributes_dropped += 1
        return None

    kept: list[str] = []
    seen = 0
    for node in tinycss2.parse_declaration_list(style, skip_comments=True, skip_whitespace=True):
        if node.type != "declaration":
            continue
        prop = node.lower_name
        # `--*` cai inteira: `--x: url(...); background: var(--x)` esconderia o
        # `url()` no valor da propriedade personalizada (§4.5.3, crítico).
        if prop.startswith("--") or prop not in ALLOWED_CSS_PROPERTIES:
            if report:
                report.css_declarations_dropped += 1
            continue
        if _has_forbidden_construct(node.value):
            if report:
                report.css_declarations_dropped += 1
            continue
        if _function_depth(node.value) > MAX_CSS_FUNCTION_DEPTH:
            if report:
                report.css_declarations_dropped += 1
            continue
        value = _serialize_tokens(node.value)
        if not value or len(value) > MAX_CSS_VALUE_LENGTH:
            if report:
                report.css_declarations_dropped += 1
            continue
        if not _validate_css_value(prop, value):
            if report:
                report.css_declarations_dropped += 1
            continue
        seen += 1
        if seen > MAX_CSS_DECLARATIONS:
            if report:
                report.css_declarations_dropped += 1
            continue
        kept.append(f"{prop}: {value}")

    if not kept:
        return None
    return "; ".join(kept)


def _normalize_url_value(value: str) -> str | None:
    """§4.4 passos 1–4. Devolve `None` para valor rejeitado."""
    if len(value) > MAX_URL_LENGTH:
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    text = text.strip("".join(chr(c) for c in range(0x21) if chr(c) not in "!#$&*+,-./"))
    if _CONTROL_RE.search(text) or "\x00" in text:
        return None
    if len(text) > MAX_URL_LENGTH:
        return None
    return text


def is_tracking_param(name: str) -> bool:
    """§5.2.1 — comparação sem diferenciar maiúsculas."""
    lowered = name.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PARAM_PREFIXES)


def strip_tracking_params(url: str) -> tuple[str, int]:
    """§5.2.1 — remove parâmetros da query **e** do fragmento, nunca do caminho.

    Devolve `(url_limpa, removidos)`. Se a URL for malformada a ponto de não se
    poder separar query e caminho com segurança, devolve `("", -1)` para o
    chamador descartar o atributo (allowlist: na dúvida, remover)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "", -1

    removed = 0

    def _clean(raw: str) -> str:
        nonlocal removed
        pairs = parse_qsl(raw, keep_blank_values=True)
        kept = [(k, v) for k, v in pairs if not is_tracking_param(k)]
        removed += len(pairs) - len(kept)
        return urlencode(kept, doseq=True)

    query = _clean(parts.query) if parts.query else parts.query
    fragment = _clean(parts.fragment) if "=" in parts.fragment else parts.fragment
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))
    return (cleaned if cleaned != url else url), removed


def _check_url(value: str, *, kind: str, report: SanitizeReport | None) -> str | None:
    """§4.4 — valida o esquema por tipo de uso. `kind` ∈ {link, image, cite}."""
    normalized = _normalize_url_value(value)
    if normalized is None:
        if report:
            report.urls_discarded += 1
        return None
    if normalized == "":
        return None

    match = _SCHEME_RE.match(normalized)
    if not match:  # relativo: mantido como tal
        return None if kind == "image" else normalized

    scheme = match.group(1).lower()
    if scheme == "cid":
        return normalized if kind == "image" else None
    allowed = LINK_SCHEMES if kind in {"link", "cite"} else IMAGE_SCHEMES
    if scheme not in allowed:
        if report:
            report.urls_discarded += 1
            report._bump_scheme(scheme)
        return None
    if scheme == "mailto":
        return normalized.split("?", 1)[0]  # sem ?subject=/?body= (§4.4)
    return normalized


def _scalar_attr_ok(name: str, value: str) -> bool:
    """Validação de escalares de §4.3. Regex é aceitável aqui: valida formato
    fixo, não interpreta HTML nem CSS (§4.9)."""
    if name == "dir":
        return value.lower() in {"ltr", "rtl", "auto"}
    if name == "lang":
        return bool(_LANG_RE.match(value))
    if name == "role":
        return value.lower() in ARIA_ALLOWED_ROLES
    if name.startswith("aria-"):
        return len(value) <= MAX_ARIA_ATTRIBUTE
    if name == "datetime":
        return bool(_DATETIME_RE.match(value))
    if name in {"colspan", "rowspan", "span"}:
        return bool(_INTEGER_RE.match(value)) and 1 <= int(value) <= 1000
    if name == "start":
        return bool(_INTEGER_RE.match(value)) and -10000 <= int(value) <= 10000
    if name == "value":
        return bool(_INTEGER_RE.match(value))
    if name in {"border", "cellpadding", "cellspacing"}:
        return bool(_INTEGER_RE.match(value)) and 0 <= int(value) <= 20
    if name == "align":
        return value.lower() in _CSS_ENUMS["align"]
    if name == "valign":
        return value.lower() in _CSS_ENUMS["valign"]
    if name == "type":
        return value in {"1", "a", "A", "i", "I"}
    if name in {"reversed", "open"}:
        return True
    if name in {"width", "height"}:
        # Tabela: inteiro 1–4096 ou percentual inteiro 1–100%.
        # Imagem: apenas inteiro decimal, com sufixo `px` aceito, faixa 1–4096.
        return _validate_table_or_image_dimension(value)
    return len(value) <= 100


def _validate_table_or_image_dimension(value: str) -> bool:
    text = value.strip().lower()
    if text.endswith("px"):
        text = text[:-2]
    if text.endswith("%"):
        body = text[:-1]
        return bool(_INTEGER_RE.match(body)) and 1 <= int(body) <= 100
    if not _INTEGER_RE.match(text):
        return False
    return 1 <= int(text) <= 4096


def _make_attribute_filter(*, pass_a: bool, report: SanitizeReport | None):
    """Filtro de atributos dos passes A e B (§4.1 passos 1 e 3)."""

    def _filter(element: str, attribute: str, value: str) -> str | None:
        name = attribute.lower()

        # (a) Reserva do espaço de nomes: o passe A descarta `data-pymail-*`
        # para que um remetente não possa forjar o marcador que o leitor usa
        # para restaurar imagens (§4.1 passo 1 — achado de segurança central).
        if name.startswith("data-pymail-"):
            if pass_a:
                if report:
                    report.attributes_dropped += 1
                return None
            return value

        # (b) `on*` coberto por prefixo, não por enumeração.
        if name.startswith("on"):
            if report:
                report.attributes_dropped += 1
            return None

        if name in NEVER_ALLOWED_ATTRS:
            if report:
                report.attributes_dropped += 1
            return None

        # (c) CSS do atributo `style`.
        if name == "style":
            return filter_style(value, report)

        # (d) URLs — validação fina por tipo de uso, que o `nh3` não distingue.
        if name == "href":
            cleaned, removed = strip_tracking_params(value)
            if removed < 0:
                if report:
                    report.urls_discarded += 1
                return None
            if report:
                report.tracking_params_removed += removed
            return _check_url(cleaned, kind="link", report=report)
        if name == "cite":
            return _check_url(value, kind="cite", report=report)
        if name == "src":
            return _check_url(value, kind="image", report=report)

        if name in {"title", "alt", "summary", "headers", "scope", "id", "class"}:
            if len(value) > MAX_TEXT_ATTRIBUTE:
                return None
            return value

        # ── Janela de detecção da heurística de pixel (§5.1) ──────────────────
        # Este filtro roda no passe A, e a heurística roda DEPOIS dele. Os sinais
        # decisivos H2 (`width`/`height` = 0) e H3 (`hidden`) seriam descartados
        # aqui pela validação estrita de §4.3 — faixa 1–4096, e `hidden` fora da
        # allowlist — e a heurística ficaria cega: um pixel `width="0"` ou
        # `hidden` sobreviveria, e com autorização do remetente confirmaria a
        # leitura que RF-RD-04 proíbe. Passar por aqui é o que mantém H2/H3 vivas.
        #
        # O passe B (selo) reaplica a disciplina: faixa estrita 1–4096 e sem
        # `hidden`. Quando o sinal existe, o elemento é removido inteiro no passo
        # 2a e nada dele chega ao artefato; quando não caracteriza pixel, o
        # atributo cai no selo. Nenhum dos dois casos deixa resíduo.
        if pass_a and element == "img" and name in {"width", "height"}:
            text = value.strip().lower()
            if text.endswith("px"):
                text = text[:-2]
            if _INTEGER_RE.match(text) and 0 <= int(text) <= 4096:
                return text
            if report:
                report.attributes_dropped += 1
            return None
        if pass_a and element == "img" and name == "hidden":
            return value

        if not _scalar_attr_ok(name, value):
            if report:
                report.attributes_dropped += 1
            return None
        return value

    return _filter


def _clean(
    html: str,
    attrs: dict[str, frozenset[str]],
    *,
    pass_a: bool,
    report: SanitizeReport | None,
    allow_pymail_prefix: bool,
) -> str:
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        clean_content_tags=CLEAN_CONTENT_TAGS,
        attributes={tag: set(names) for tag, names in attrs.items()},
        attribute_filter=_make_attribute_filter(pass_a=pass_a, report=report),
        strip_comments=True,
        link_rel=None,
        generic_attribute_prefixes={"aria-", "data-pymail-"} if allow_pymail_prefix else {"aria-"},
        url_schemes=set(NH3_URL_SCHEMES),
    )


def structure_pass(html: str, report: SanitizeReport | None = None) -> str:
    """Passo 1 — passe A. Descarta `data-pymail-*`, normaliza a árvore e elimina
    `<base>`, `<style>`, `<meta>`, `<link>`, `<picture>`, `<svg>`, `<math>`."""
    return _clean(html, _ATTRS_PASS_A, pass_a=True, report=report, allow_pymail_prefix=False)


def seal_pass(
    html: str, *, allow_restored_src: bool = False, report: SanitizeReport | None = None
) -> str:
    """Passo 3 — passe B: a **autoridade estrutural final**.

    Duas variantes de allowlist, conforme a ambiguidade de `src` documentada no
    topo do módulo: a do artefato gravado (sem `src`, com os marcadores) e a da
    renderização (com `src`, sem marcador nenhum)."""
    attrs = _ATTRS_SEAL_RENDER if allow_restored_src else _ATTRS_SEAL_STORED
    return _clean(
        html,
        attrs,
        pass_a=False,
        report=report,
        allow_pymail_prefix=not allow_restored_src,
    )


# ═════════════════ Passo 2 — reescrita de privacidade (html5lib) ══════════════


def _style_map(style: str | None) -> dict[str, str]:
    if not style:
        return {}
    return {prop: value.lower() for prop, value in _split_style(style)}


def _attr_int(element, name: str) -> int | None:  # noqa: ANN001
    raw = element.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text.endswith("px"):
        text = text[:-2]
    return int(text) if _INTEGER_RE.match(text) else None


def is_tracking_pixel(element) -> bool:
    """§5.1.1 — regra de decisão:
    `H1 ∨ H2 ∨ H3 ∨ H4 ∨ H5 ∨ H6 ∨ (H7 ∧ (H1 ∨ H2 ∨ H6))`.
    Sinais `R` (H8, H9, H10) **nunca** decidem sozinhos."""
    width = _attr_int(element, "width")
    height = _attr_int(element, "height")
    styles = _style_map(element.get("style"))
    css_height = _length_px(styles.get("height"))
    css_width = _length_px(styles.get("width"))
    css_max_height = _length_px(styles.get("max-height"))
    css_max_width = _length_px(styles.get("max-width"))

    h1 = width is not None and height is not None and width <= 2 and height <= 2
    h2 = (width == 0) or (height == 0)
    h3 = "hidden" in element.attrib
    h4 = (
        styles.get("display") == "none"
        or styles.get("visibility") in {"hidden", "collapse"}
        or styles.get("opacity") == "0"
        or css_height == 0
        or css_max_height == 0
        or css_width == 0
        or css_max_width == 0
        or (styles.get("overflow") == "hidden" and css_height == 0)
    )
    h5 = (
        (width is not None and width <= 2 and ((css_width or 0) > 2 or (css_height or 0) > 2))
        or (height is not None and height <= 2 and ((css_width or 0) > 2 or (css_height or 0) > 2))
        or (css_width is not None and css_width <= 2 and (width or 0) > 2)
        or (css_height is not None and css_height <= 2 and (height or 0) > 2)
    )
    h6 = width is not None and height is not None and (width * height) <= 4
    h7 = str(element.get("border", "")).strip() == "0"

    return bool(h1 or h2 or h3 or h4 or h5 or h6 or (h7 and (h1 or h2 or h6)))


def _length_px(value: str | None) -> int | None:
    if not value:
        return None
    match = _LENGTH_RE.match(value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "%":
        return None  # percentual não é dimensão absoluta
    if unit in ("em", "rem"):
        number *= 16
    elif unit == "pt":
        number *= 4 / 3
    return int(number)


def _looks_like_beacon_name(element) -> bool:  # noqa: ANN001
    """H8 — reforço apenas."""
    alt = (element.get("alt") or "").strip()
    if alt:
        return False
    url = element.get("src") or element.get("data-pymail-src") or ""
    return bool(_PIXEL_FILENAME_RE.search(url))


def privacy_rewrite(html: str, report: SanitizeReport) -> str:
    """Passo 2 — sobre `html_a`, com `html5lib`.

    Ordem interna obrigatória (§4.1.1): remover pixels (2a) **antes** de mover a
    URL (2c), e limpar parâmetros (2b) **antes** de qualquer cópia — senão a
    cópia carregaria o rastreador, e o pixel voltaria na restauração.
    """
    tree = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    removed: list[tuple[object, object]] = []

    for parent in tree.iter():
        for element in list(parent):
            tag = element.tag.lower() if isinstance(element.tag, str) else ""

            if tag == "img":
                # (2a) Remoção IRREVERSÍVEL: o elemento sai inteiro, com a URL.
                # Não há `data-pymail-src` para um pixel, portanto não há o que
                # restaurar — a irreversibilidade é estrutural, não uma promessa.
                if is_tracking_pixel(element):
                    removed.append((parent, element))
                    report.pixels_removed += 1
                    continue

                # (2b) já aplicado a `href` no filtro; (2c) preserva a URL.
                src = element.get("src")
                if src:
                    if src.lower().startswith("cid:"):
                        element.set("data-pymail-cid", src)
                        report.attributes_dropped += 1
                    else:
                        element.set("data-pymail-src", src)
                        report.remote_images_preserved += 1
                        report.restorable_images += 1
                    # (2d) nenhuma imagem mantém `src` no artefato gravado.
                    del element.attrib["src"]

    for parent, element in removed:
        parent.remove(element)

    return _html5_serialize(
        tree,
        tree="etree",
        quote_attr_values="always",
        omit_optional_tags=False,
        use_trailing_solidus=False,
        space_before_trailing_solidus=False,
    )


# ══════════════════ Passos 5 e 6 — texto plano e documento ═══════════════════

_BLOCK_TAGS: Final[frozenset[str]] = frozenset(
    """
    address article aside blockquote br dd div dl dt fieldset figcaption figure
    footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table
    tbody td tfoot th thead tr ul
    """.split()
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "head", "title"}:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head", "title"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def html_to_text_plain(html: str) -> str:
    """Passo 5 — derivado do HTML **já sanitizado**.

    Derivar do HTML cru colocaria no índice FTS5 e na pré-visualização conteúdo
    que foi removido — por exemplo o texto dentro de `<script>` (§4.1, passo 5).
    """
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


CSP_NO_IMAGES: Final[str] = (
    "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
    "img-src 'none'; font-src 'none'; media-src 'none'; object-src 'none'; "
    "frame-src 'none'; worker-src 'none'; manifest-src 'none'; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'"
)
CSP_WITH_IMAGES: Final[str] = CSP_NO_IMAGES.replace("img-src 'none'", "img-src https:")


def wrap_document(body_html: str, *, allow_remote_images: bool = False) -> str:
    """Passo 6 — monta o documento. O `<meta>` de CSP só tem efeito se estiver
    no `<head>` e antes do conteúdo, e é por isso que montamos o documento nós
    mesmos em vez de confiar no que veio na mensagem."""
    csp = CSP_WITH_IMAGES if allow_remote_images else CSP_NO_IMAGES
    return (
        "<!doctype html><html><head>"
        '<meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        '<meta name="referrer" content="no-referrer">'
        "</head><body>"
        f"{body_html}"
        "</body></html>"
    )


# ═════════════════════════════ Portas de entrada ═════════════════════════════


def sanitize_html(
    raw_html: str | bytes,
    context: SanitizeContext | None = None,
    *,
    charset: str | None = None,
) -> str:
    """Pipeline completo (§4.1, passos 0–6). Idempotente por invariante (§4.7.2).

    Função pura: sem rede, sem banco, sem keyring (§4.7.3).
    """
    ctx = context or SanitizeContext()
    report = SanitizeReport()

    html, truncated = normalize_input(raw_html, charset)
    report.truncated = truncated
    if truncated and not html.strip():
        return wrap_document("", allow_remote_images=ctx.allow_remote_images)

    html_a = structure_pass(html, report)
    html_b = privacy_rewrite(html_a, report)
    html_c = seal_pass(html_b, report=report)
    return wrap_document(html_c, allow_remote_images=ctx.allow_remote_images)


def sanitize_html_with_report(
    raw_html: str | bytes, context: SanitizeContext | None = None
) -> tuple[str, SanitizeReport]:
    """Variante que devolve o `SanitizeReport` (passo 4), usado pela interface
    para informar quantos pixels foram removidos."""
    ctx = context or SanitizeContext()
    report = SanitizeReport()
    html, truncated = normalize_input(raw_html)
    report.truncated = truncated
    html_a = structure_pass(html, report)
    html_b = privacy_rewrite(html_a, report)
    html_c = seal_pass(html_b, report=report)
    return wrap_document(html_c, allow_remote_images=ctx.allow_remote_images), report


def restore_remote_resources(html: str) -> str:
    """Passo 8 — inverso de 2c, seguido do selo **de novo** (§4.7.1).

    Só restaura o que existe: pixels de rastreamento foram removidos no passo 2a
    sem deixar marcador, então não há como ressuscitá-los. A string devolvida
    passou pelo `nh3` como última transformação e não contém `data-pymail-`."""
    tree = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    for element in tree.iter():
        tag = element.tag.lower() if isinstance(element.tag, str) else ""
        if tag != "img":
            continue
        preserved = element.get("data-pymail-src")
        if preserved:
            element.set("src", preserved)
            del element.attrib["data-pymail-src"]
        element.attrib.pop("data-pymail-cid", None)

    body = _html5_serialize(
        tree,
        tree="etree",
        quote_attr_values="always",
        omit_optional_tags=False,
        use_trailing_solidus=False,
        space_before_trailing_solidus=False,
    )
    return wrap_document(seal_pass(body, allow_restored_src=True), allow_remote_images=True)


# §5.2.2 — um nome de parâmetro que não pode ser removido nunca deve entrar na
# lista de remoção. Verificado na importação, não em revisão de código.
assert not (TRACKING_PARAMS & NEVER_REMOVE_PARAMS), (
    "parâmetro marcado como 'nunca remover' entrou na lista de rastreamento"
)
assert not any(p.startswith(TRACKING_PARAM_PREFIXES) for p in NEVER_REMOVE_PARAMS), (
    "parâmetro 'nunca remover' colide com um prefixo de rastreamento"
)
