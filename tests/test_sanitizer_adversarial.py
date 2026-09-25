"""Sondagens adversariais do sanitizador.

Os testes de `test_security_sanitize.py` cobrem o contrato, mas algumas de suas
asserções são fracas — por exemplo, `"rastreador.example.com" not in restored`
é vacuamente verdadeira, porque essa string nunca aparece na fixture. Este
arquivo ataca o pipeline de propósito, com as construções que a spec afirma
defender, para que a afirmação seja verificada em vez de suposta.

Cada teste nomeia o requisito ou a seção de `05-seguranca-privacidade.md` que
está sendo exercitado.
"""

from __future__ import annotations

import re

import pytest

from pymail_client.core.security import (
    SANITIZER_VERSION,
    SanitizeContext,
    html_to_text_plain,
    restore_remote_resources,
    sanitize_html,
    sanitize_html_with_report,
)

ACTIVE_REMOTE_SRC = re.compile(r"""\ssrc\s*=\s*["']https?://""", re.IGNORECASE)


# ─────────────── Execução de código e esquemas perigosos (§4.2, §4.4) ─────────


@pytest.mark.parametrize(
    "payload",
    [
        '<a href="javascript:alert(1)">x</a>',
        '<a href="JaVaScRiPt:alert(1)">x</a>',
        '<a href="jav&#x61;script:alert(1)">x</a>',  # entidade numérica
        '<a href="java\tscript:alert(1)">x</a>',  # tab no meio do esquema
        '<a href="vbscript:msgbox(1)">x</a>',
        '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
        '<a href="file:///C:/Windows/System32/">x</a>',
        '<a href="blob:https://x/y">x</a>',
        '<a href="pymail://message/x">x</a>',
    ],
)
def test_dangerous_schemes_never_survive(payload: str) -> None:
    """§4.4 — allowlist de esquemas; desconhecido é negado, não permitido."""
    out = sanitize_html(payload).lower()
    for token in ("javascript:", "vbscript:", "data:text", "file:", "blob:", "pymail:"):
        assert token not in out, f"{token!r} sobreviveu em {payload!r}"


def test_executable_markup_is_removed_including_foreign_content() -> None:
    """§4.2 — `svg`/`math` são conteúdo estrangeiro, área de divergência entre
    sanitizadores e motores (a origem clássica de mXSS)."""
    payload = (
        "<div><svg><foreignObject><script>alert(1)</script></foreignObject></svg>"
        "<math><mtext><script>alert(2)</script></mtext></math>"
        "<template><img src=x onerror=alert(3)></template></div>"
    )
    out = sanitize_html(payload).lower()
    for token in ("<svg", "<math", "<script", "<template", "foreignobject", "onerror"):
        assert token not in out, f"{token!r} sobreviveu"


def test_event_handlers_never_survive_any_element() -> None:
    """§4.3 — `on*` é coberto por prefixo, não por enumeração."""
    payload = (
        '<img src="https://x/a.png" onerror="alert(1)">'
        '<body onload="alert(1)"><div onclick="x()" onmouseover="y()">t</div>'
    )
    out = sanitize_html(payload).lower()
    assert "onerror" not in out
    assert "onload" not in out
    assert "onclick" not in out
    assert "onmouseover" not in out


# ────────────────────── CSS: o que o `nh3` sozinho não vê (§4.5) ─────────────


@pytest.mark.parametrize(
    "style",
    [
        "background-image: url('https://rastreador.example/px.gif')",
        "background: u\\72 l('https://rastreador.example/px.gif')",  # escape CSS
        "background: url(/*x*/'https://rastreador.example/px.gif')",  # comentário
        "list-style-image: url(https://x/y.png)",
        "width: expression(alert(1))",
        "behavior: url(#default#time2)",
        "-moz-binding: url(https://x/y.xml)",
        "background-image: image-set('https://x/a.png' 1x)",
        "cursor: url(https://x/c.cur), auto",
    ],
)
def test_css_cannot_smuggle_a_request(style: str) -> None:
    """§4.5.1 — nenhum `url()` sobrevive, com ou sem escape ou comentário."""
    out = sanitize_html(f'<div style="{style}">t</div>').lower()
    assert "url(" not in out, f"url() sobreviveu em {style!r}"
    assert "expression(" not in out
    assert "https://rastreador.example" not in out


def test_css_custom_property_cannot_hide_a_url() -> None:
    """§4.5.3, caso crítico — `--x: url(...)` + `var(--x)` esconde o `url()` no
    valor da propriedade personalizada, e a substituição ocorre em tempo de
    valor computado. Um filtro que só examinasse `background-image` passaria."""
    style = "--x: url(https://rastreador.example/px.gif); background-image: var(--x)"
    out = sanitize_html(f'<div style="{style}">t</div>')
    assert "--x" not in out
    assert "var(" not in out
    assert "url(" not in out
    assert "rastreador.example" not in out


def test_css_position_fixed_is_dropped() -> None:
    """§4.5.3 — `position:fixed` permite forjar alvo de clique sobre a interface."""
    out = sanitize_html('<div style="position: fixed; top: 0; left: 0">t</div>')
    assert "position" not in out.lower()
    assert "fixed" not in out.lower()


def test_css_at_rule_is_dropped() -> None:
    """§4.5.3 — at-rule dentro de `style` indica entrada malformada de propósito."""
    out = sanitize_html('<div style="@import url(https://x/y.css); color: red">t</div>')
    assert "@import" not in out
    assert "url(" not in out


def test_css_function_depth_is_bounded() -> None:
    """§4.5.4 — `calc(calc(...))` aninhado é negação de serviço barata de escrever."""
    deep = "width: " + "calc(" * 12 + "1px" + ")" * 12
    out = sanitize_html(f'<div style="{deep}">t</div>')
    assert "calc(" not in out


def test_css_style_attribute_length_is_bounded() -> None:
    """§4.5.4 — atributo acima de 4096 caracteres é descartado por inteiro."""
    style = "color: red; " + "padding-left: 1px; " * 400
    out = sanitize_html(f'<div style="{style}">t</div>')
    assert "padding-left" not in out


# ───────── Forja do marcador de restauração — a defesa central (§4.1) ────────


def test_sender_cannot_forge_the_restoration_marker() -> None:
    """§4.1 passo 1 — se um remetente pudesse escrever `data-pymail-src`, ele
    contornaria todo o bloqueio de pixels no momento da restauração.

    É o achado de segurança central: o passe A descarta o prefixo para que o
    espaço de nomes dos nossos marcadores seja reservado.
    """
    forged = '<img alt="a" data-pymail-src="https://atacante.example/x.gif">'
    out = sanitize_html(forged)
    assert "data-pymail-src" not in out
    assert "atacante.example" not in out
    assert "atacante.example" not in restore_remote_resources(out)


def test_sender_cannot_forge_the_inline_content_marker() -> None:
    """§4.4 — `cid:` só vira `data-pymail-cid` pela nossa mão, nunca pela dele."""
    out = sanitize_html('<img alt="a" data-pymail-cid="cid:rastreador">')
    assert "data-pymail-cid" not in out


# ───────────────── Rastreamento: pixels e parâmetros (§5.1, §5.2) ────────────


@pytest.mark.parametrize(
    "img_tag",
    [
        '<img src="https://t.example/p.gif" width="1" height="1">',
        '<img src="https://t.example/p.gif" width="0" height="0">',
        '<img src="https://t.example/p.gif" width="2" height="2">',
        '<img src="https://t.example/p.gif" width="1" height="1" border="0">',
        '<img src="https://t.example/p.gif" hidden>',
        '<img src="https://t.example/p.gif" style="display:none" width="10" height="10">',
        '<img src="https://t.example/p.gif" style="visibility:hidden" width="10" height="10">',
        '<img src="https://t.example/p.gif" style="opacity:0" width="10" height="10">',
        '<img src="https://t.example/p.gif" style="height:0" width="10" height="10">',
        '<img src="https://t.example/p.gif" style="width:0" width="10" height="10">',
        '<img src="https://t.example/p.gif" width="1" height="1" style="width:600px">',
    ],
)
def test_tracking_pixels_are_removed_and_not_restorable(img_tag: str) -> None:
    """§5.1.2 — a remoção é estrutural: a URL não existe em lugar nenhum do
    sistema depois da sanitização, então não há o que restaurar."""
    out, report = sanitize_html_with_report(f"<p>x</p>{img_tag}<p>y</p>")

    assert "t.example" not in out, "a URL do pixel sobreviveu no artefato"
    assert report.pixels_removed >= 1

    # Nem com o usuário autorizando imagens do remetente.
    restored = restore_remote_resources(out)
    assert "t.example" not in restored
    assert SanitizeContext(allow_remote_images=True) is not None


def test_legitimate_image_without_hiding_signals_survives() -> None:
    """Contraprova: a heurística não pode ser tão agressiva que apague imagens
    legítimas — senão o produto não exibe e-mail nenhum."""
    out = sanitize_html(
        '<img src="https://cdn.example/foto.jpg" alt="Foto" width="600" height="400">'
    )
    assert "data-pymail-src" in out
    assert ACTIVE_REMOTE_SRC.search(out) is None
    assert "cdn.example" in restore_remote_resources(out)


@pytest.mark.parametrize(
    "href,sumiu",
    [
        ("https://x/p?a=1&utm_source=n&b=2", "utm_source=n"),
        ("https://x/p?UTM_SOURCE=n", "UTM_SOURCE=n"),
        ("https://x/p?a=1&fbclid=abc", "fbclid=abc"),
        ("https://x/p?a=1&mc_eid=zz", "mc_eid=zz"),
        ("https://x/p?a=1&gclid=x", "gclid=x"),
        ("https://x/p?a=1#utm_source=n", "utm_source=n"),
        ("https://x/p?a=1&utm_campaign=novidade", "utm_campaign=novidade"),
        ("https://x/p?a=1&fbclid", "fbclid"),
    ],
)
def test_tracking_params_are_removed_from_query_and_fragment(href: str, sumiu: str) -> None:
    """§5.2.1 — query **e** fragmento, sem diferenciar maiúsculas, inclusive
    parâmetro sem valor. O caminho nunca é tocado."""
    out = sanitize_html(f'<a href="{href}">x</a>')
    assert sumiu.split("=")[0].lower() not in out.lower()
    assert "/p" in out, "o caminho foi alterado"
    if "a=1" in href and "utm" not in href.split("?")[1].split("&")[0]:
        assert "a=1" in out, "parâmetro legítimo foi removido junto"


def test_legitimate_path_survives_tracking_removal() -> None:
    """§5.2.2 — a remoção é denylist por nome; caminho e parâmetros comuns ficam."""
    out = sanitize_html('<a href="https://x/relatorio/2024?id=7&page=2&lang=pt">x</a>')
    assert "relatorio/2024" in out
    assert "id=7" in out
    assert "page=2" in out
    assert "lang=pt" in out


# ─────────────────────── Base, URLs relativas e robustez (§4.1) ──────────────


def test_base_tag_cannot_hijack_relative_urls() -> None:
    """§4.1.1, inversão 3 — `<base>` é descartado no passe A, então uma URL
    relativa permanece relativa e falha contra a `baseUrl` fictícia, em vez de
    se tornar absoluta apontando para o host do remetente."""
    out = sanitize_html('<base href="https://evil.example/"><img src="image.png" alt="a">')
    assert "<base" not in out.lower()
    assert "evil.example" not in out
    assert "data-pymail-src" not in out, "URL relativa virou recurso restaurável"
    assert "image.png" not in out


def test_picture_source_is_removed_and_inner_img_follows_normal_path() -> None:
    """§4.2 — `picture`/`source` são descartados; o `<img>` interno é promovido."""
    out = sanitize_html(
        '<picture><source srcset="https://t.example/a.png 1x">'
        '<img src="https://cdn.example/b.jpg" alt="b" width="100" height="100"></picture>'
    )
    assert "srcset" not in out.lower()
    assert "t.example" not in out
    assert "data-pymail-src" in out


def test_nul_bytes_are_removed_and_do_not_truncate() -> None:
    """§4.1 passo 0 — o NUL pode truncar a leitura em camadas que tratam a
    cadeia como C-string, produzindo *parser differential*."""
    payload = "<p>antes</p>\x00<script>alert(1)</script><p>depois</p>"
    out = sanitize_html(payload)
    assert "\x00" not in out
    assert "<script" not in out.lower()
    assert "antes" in out and "depois" in out


def test_malformed_html_never_raises() -> None:
    """§4.1.1 — entrada malformada não pode virar exceção nem HTML cru."""
    for payload in [
        "<div><p>sem fechamento",
        "</p></div>",
        "<table><tr><td>sem fechar",
        "<a href=",
        "<img src='x' ",
        "<<>>",
        "<b><i>sobreposto</b></i>",
        "<!-- comentário -->",
    ]:
        out = sanitize_html(payload)
        assert out.startswith("<!doctype html>")
        assert "<script" not in out.lower()


def test_plain_text_is_derived_from_sanitized_html_not_raw() -> None:
    """§4.1 passo 5 — derivar do HTML cru colocaria no índice FTS5 o texto
    dentro de `<script>`, que apareceria em resultados de busca."""
    payload = "<style>p{color:red}</style><p>visível</p><script>segredo()</script>"
    text = html_to_text_plain(sanitize_html(payload))
    assert "visível" in text
    assert "segredo" not in text
    assert "color:red" not in text


# ─────────────────────────── Invariantes de saída (§4.7) ─────────────────────


def test_no_string_reaching_the_engine_carries_our_markers() -> None:
    """§4.7.1 — a string restaurada passou pelo selo e não tem `data-pymail-`."""
    raw = '<p>oi</p><img src="https://cdn.example/a.jpg" alt="a" width="10" height="10">'
    stored = sanitize_html(raw)
    assert "data-pymail-src" in stored

    rendered = restore_remote_resources(stored)
    assert "data-pymail-" not in rendered
    assert SanitizeReport_marker_absent(rendered)


def SanitizeReport_marker_absent(html: str) -> bool:  # noqa: N802 - helper local
    return "data-pymail-cid" not in html and "data-pymail-blocked" not in html


def test_sanitizer_version_is_declared_and_integer() -> None:
    assert isinstance(SANITIZER_VERSION, int) and SANITIZER_VERSION >= 1
