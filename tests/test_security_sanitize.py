"""Testes para o sanitizador de HTML e pipeline de privacidade."""

import re

import pytest

from pymail_client.core.security import (
    CSP_NO_IMAGES,
    SANITIZER_VERSION,
    restore_remote_resources,
    sanitize_html,
)

#: `src` ATIVO apontando para a rede. Não confundir com a substring `src="http`,
#: que aparece legitimamente dentro de `data-pymail-src` — o `\s` antes de `src`
#: é o que distingue um atributo real do nosso marcador, que é precedido de `-`.
#: (O esboço original deste teste usava a substring e era autocontraditório:
#: exigia `'src="http' not in sanitized` junto com 20 ocorrências de
#: `data-pymail-src`, que contém exatamente aquela substring.)
ACTIVE_REMOTE_SRC = re.compile(r"""\ssrc\s*=\s*["']https?:""", re.IGNORECASE)

FORBIDDEN = [
    "<script",
    "<iframe",
    "<object",
    "<embed",
    "<form",
    "javascript:",
    "onerror=",
    "onload=",
    "expression(",
]


@pytest.mark.parametrize(
    "name",
    [
        "script_inline",
        "javascript_href",
        "onerror_img",
        "iframe",
        "object_embed",
        "form_phishing",
        "css_expression",
        "css_remote_import",
        "base_href_hijack",
    ],
)
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
    """RF-RD-03: sem consentimento, nenhum recurso remoto é buscável."""
    sanitized = sanitize_html(load_eml("remote_images_20").html)
    assert ACTIVE_REMOTE_SRC.search(sanitized) is None
    assert sanitized.count("data-pymail-src") >= 20

    restored = restore_remote_resources(sanitized)
    assert len(ACTIVE_REMOTE_SRC.findall(restored)) >= 20


def test_csp_meta_is_injected(load_eml) -> None:
    result = sanitize_html(load_eml("script_inline").html)
    assert "Content-Security-Policy" in result


def test_tracking_params_are_stripped_from_links(load_eml) -> None:
    result = sanitize_html(load_eml("tracking_params").html)
    for param in ("utm_source", "utm_campaign", "fbclid", "gclid", "mc_eid"):
        assert param not in result


def test_malformed_html_never_raises_and_never_falls_back_to_raw(load_eml) -> None:
    """Fail-safe: se a reescrita falhar, o chamador recebe texto plano, nunca HTML cru."""
    # O sanitizador não deve lançar exceção
    result = sanitize_html(load_eml("malformed_html").html)
    # Não deve conter construções proibidas
    lowered = result.lower()
    for token in FORBIDDEN:
        assert token not in lowered, f"{token!r} sobreviveu em malformed_html"


def test_sanitizer_version_is_positive_int() -> None:
    assert isinstance(SANITIZER_VERSION, int)
    assert SANITIZER_VERSION >= 1


def test_pipeline_is_deterministic(load_eml) -> None:
    """Mesma entrada, mesma saída — pré-requisito de qualquer outra asserção."""
    for name in ["script_inline", "remote_images_20", "tracking_params"]:
        html = load_eml(name).html
        assert sanitize_html(html) == sanitize_html(html)


def test_resanitizing_the_artifact_is_safe_and_stable(load_eml) -> None:
    """A idempotência estrita de `05` §4.7.2 é INALCANÇÁVEL, e a razão importa.

    O artefato gravado carrega `data-pymail-src` por projeto (§4.1 passo 2c), e o
    passe A descarta esse prefixo por projeto (§4.1 passo 1) para que um
    remetente não possa forjar o marcador de restauração. Realimentar o artefato
    satisfaz as duas regras ao mesmo tempo **apenas perdendo o marcador**.

    Aceitar o marcador vindo da mensagem fecharia a idempotência abrindo a forja:
    bastaria um remetente escrever `data-pymail-src="https://atacante/x.gif"` e a
    restauração o carregaria, com um host que o usuário nunca escolheu. A
    propriedade de segurança vence a estética — e nenhum consumidor do sistema
    realimenta `sanitize_html` com o próprio artefato; ele recebe HTML cru do
    servidor. (Alternativa avaliada e rejeitada: assinar o marcador com HMAC de
    processo, para distinguir o nosso do forjado. Resolveria a idempotência ao
    custo de um segredo persistido e de complexidade sem consumidor.)

    O que se exige, e é o que este teste verifica: re-sanitizar é **seguro** e o
    documento final é **estável** — mesmo wrapper, mesma CSP, nada ativo.
    """
    raw = load_eml("remote_images_20").html
    first = sanitize_html(raw)
    second = sanitize_html(first)

    assert first.startswith("<!doctype html>")
    assert second.startswith("<!doctype html>")
    assert CSP_NO_IMAGES in second
    assert ACTIVE_REMOTE_SRC.search(second) is None
    assert "<script" not in second.lower()
    # Documenta o custo declarado: o marcador NÃO sobrevive ao passe A.
    assert second.count("data-pymail-src") == 0
    assert first.count("data-pymail-src") >= 20
