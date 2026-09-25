"""Gestão de credenciais no cofre do sistema operacional (RNF-SEC-01).

Este módulo é a **única** fronteira do projeto que fala com o `keyring`: banco,
config e interface nunca tocam o segredo, apenas esta camada. A sanitização de
HTML mora no mesmo arquivo por decisão de `02-arquitetura.md` §2.1, com o
prefixo `sanitize_html` para manter as duas famílias separadas.

Regras que o código abaixo existe para garantir (05-seguranca-privacidade §2):

* A chave é `service="pymail-client"`, `username=<email normalizado>`; para a
  fase 2, `<email>#oauth`. Nunca `accounts.id`: o banco é cache descartável e o
  caminho de recuperação do RF-SET-05 o recria do zero.
* **Nunca** existe fallback para arquivo em texto claro. A ausência dessa opção
  é a própria mitigação — uma opção seria encontrada, habilitada e esquecida.
* Sem cofre do SO, a credencial vive **apenas em memória, pela sessão**, e o
  usuário é avisado de forma explícita: a degradação é visível, não silenciosa.
* Um backend de cofre em texto claro é tratado como se não houvesse cofre.
"""

from __future__ import annotations

import logging
from typing import Any

import keyring
import keyring.errors

logger = logging.getLogger(__name__)

#: `service` de todo item gravado pelo PyMail Client (03-modelo-de-dados §3).
KEYRING_SERVICE = "pymail-client"

#: Separa os dois segredos da mesma conta: senha (F1) e token OAuth2 (F2).
OAUTH_SUFFIX = "#oauth"

#: Chave inexistente usada na leitura de sonda da detecção de disponibilidade.
_PROBE_KEY = "__pymail_probe__"

#: Backends recusados por serem cofres em texto claro ou sentinelas de falha
#: (05-seguranca-privacidade §2.2). `keyrings.alt` não é dependência do projeto:
#: a lista existe porque o usuário pode tê-la instalada no mesmo ambiente.
_DENYLISTED_BACKENDS = frozenset(
    {
        "keyring.backends.file.PlaintextKeyring",
        "keyrings.alt.file.PlaintextKeyring",
        "keyrings.alt.file.EncryptedKeyring",
        "keyring.backends.fail.Keyring",
    }
)
_DENYLISTED_CLASS_NAMES = frozenset({"PlaintextKeyring", "EncryptedKeyring"})

_MASK = "***"

MEMORY_MODE_WARNING = (
    "As credenciais não podem ser guardadas: o cofre do sistema não está "
    "disponível. As senhas serão pedidas a cada início."
)
WRITE_FAILED_WARNING = (
    "Não foi possível gravar a credencial no cofre do sistema. Ela será mantida "
    "somente em memória até o fim desta sessão."
)


class Redacted(str):
    """`str` que não se imprime (05-seguranca-privacidade §2.6.2).

    Continua sendo `str` porque o protocolo precisa do valor utilizável
    (`AUTHENTICATE`), mas `str()`, `repr()` e `format()` devolvem `"***"`. Assim um
    `logger.debug("auth=%r", value)` acidental não vaza o segredo. O valor real só
    sai por `reveal()`, e as chamadas a `reveal()` ficam em `auth.py` e nos
    clientes de protocolo.

    Limitação honesta: a `str` original continua viva na memória do processo até a
    coleta de lixo. Isto não zera nada; apenas impede o vazamento por log.
    """

    __slots__ = ()

    def __str__(self) -> str:
        return _MASK

    def __repr__(self) -> str:
        return _MASK

    def __format__(self, format_spec: str) -> str:
        return _MASK

    def reveal(self) -> str:
        """Única saída do valor real. Não registre o que esta função devolve."""
        return str.__str__(self)


class MemoryCredentialStore:
    """Cofre de memória para a sessão, usado só quando o cofre do SO não existe.

    Guarda instâncias de `Redacted`, nunca `str` cru (05-seguranca-privacidade
    §2.2). O `dict` é limpo no encerramento, em *best effort*.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Redacted] = {}

    def get(self, service: str, username: str) -> Redacted | None:
        return self._items.get((service, username))

    def set(self, service: str, username: str, secret: Redacted) -> None:
        self._items[(service, username)] = secret

    def delete(self, service: str, username: str) -> None:
        self._items.pop((service, username), None)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


_MEMORY_STORE = MemoryCredentialStore()

#: Resultado da detecção de disponibilidade, cacheado (§2.2: uma vez na
#: inicialização da camada). `None` significa "ainda não detectado".
_availability: bool | None = None

#: Avisos que a interface precisa exibir. A camada de UI os consome e os exibe
#: como aviso não modal e persistente; o núcleo não tem como avisar sozinho.
_warnings: list[str] = []


def pending_warnings() -> list[str]:
    """Avisos de degradação acumulados desde o último `reset_credential_state`."""
    return list(_warnings)


def reset_credential_state() -> None:
    """Zera detecção em cache, avisos e o cofre de memória.

    Usado no encerramento da aplicação e pelos testes, que precisam que a
    detecção de disponibilidade seja refeita com o dublê da sua própria sessão.
    """
    global _availability
    _availability = None
    _warnings.clear()
    _MEMORY_STORE.clear()


def _warn(message: str) -> None:
    """Registra uma degradação para a interface, sem repetir a mesma mensagem.

    O log leva o motivo técnico (útil para diagnóstico) mas nunca o segredo.
    """
    logger.warning("credencial: %s", message)
    if message not in _warnings:
        _warnings.append(message)


def _normalize(account: str | Any) -> str:
    """Chave normalizada da conta: `email.strip().lower()`.

    Sem isso, `Joao@Exemplo.com` e `joao@exemplo.com` seriam duas contas
    distintas no cofre após uma reimportação da mesma caixa.
    """
    email = account if isinstance(account, str) else account.email
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("account email must not be empty")
    return normalized


def _username(account: str | Any, *, oauth: bool) -> str:
    return _normalize(account) + (OAUTH_SUFFIX if oauth else "")


def _backend_is_denied(backend: object) -> bool:
    """Diz se o backend escolhido é um cofre em texto claro (ou uma sentinela)."""
    cls = type(backend)
    qualified = f"{cls.__module__}.{cls.__qualname__}"
    return qualified in _DENYLISTED_BACKENDS or cls.__name__ in _DENYLISTED_CLASS_NAMES


def _detect() -> bool:
    """Executa a detecção de §2.2: backend escolhido + leitura de sonda.

    Aplica-se a regra transversal: o aplicativo nunca decide por ambiente ou por
    nome de distribuição — pergunta ao `keyring`, valida o backend contra a
    denylist e reage ao resultado.
    """
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001 — NoKeyringError e afins viram "indisponível"
        return False
    if _backend_is_denied(backend):
        logger.warning("credencial: backend de cofre recusado (%s)", type(backend).__name__)
        return False
    try:
        keyring.get_password(KEYRING_SERVICE, _PROBE_KEY)
    except keyring.errors.KeyringError:
        # NoKeyringError (sem Secret Service) e KeyringLocked (cofre bloqueado).
        return False
    except Exception:  # noqa: BLE001 — exceções de secretstorage/D-Bus do backend
        return False
    return True


def keyring_is_available(*, refresh: bool = False) -> bool:
    """Se o cofre do SO pode ser usado agora. Resultado cacheado (§2.2)."""
    global _availability
    if _availability is None or refresh:
        _availability = _detect()
        if not _availability:
            _warn(MEMORY_MODE_WARNING)
    return _availability


def credential_storage_mode() -> str:
    """`"keyring"` ou `"memory"`, para `config.toml` registrar o modo vigente.

    Nunca há um terceiro valor: `05-seguranca-privacidade` §2.2 não prevê, e
    prevê-la aqui criaria exatamente a opção esquecida que ele proíbe.
    """
    return "keyring" if keyring_is_available() else "memory"


def get_credential(account: str | Any, *, oauth: bool = False) -> str | None:
    """Lê a credencial do cofre. `None` significa "não há valor guardado".

    Aceita o e-mail ou o próprio `AccountConfig`, porque os dois aparecem como
    chamada natural em código de aplicação e de teste.
    """
    key = _username(account, oauth=oauth)
    if not keyring_is_available():
        stored = _MEMORY_STORE.get(KEYRING_SERVICE, key)
        return stored
    try:
        return keyring.get_password(KEYRING_SERVICE, key)
    except keyring.errors.KeyringError:
        # O cofre pode travar com *timeout* no meio da sessão: a degradação é
        # reexibida e nada é gravado em disco (§2.2).
        _warn(WRITE_FAILED_WARNING)
        return _MEMORY_STORE.get(KEYRING_SERVICE, key)


def set_credential(account: str | Any, secret: str, *, oauth: bool = False) -> None:
    """Guarda a credencial, sempre como `Redacted`.

    Só é chamada depois da verificação de conexão do RF-ACC-03: nunca se grava
    valor para conta que não conectou.
    """
    value = secret if isinstance(secret, Redacted) else Redacted(secret)
    key = _username(account, oauth=oauth)
    if keyring_is_available():
        try:
            keyring.set_password(KEYRING_SERVICE, key, value)
            return
        except keyring.errors.KeyringError:
            _warn(WRITE_FAILED_WARNING)
    _MEMORY_STORE.set(KEYRING_SERVICE, key, value)


def delete_credential(account: str | Any, *, oauth: bool = False) -> None:
    """Apaga a credencial. Idempotente (05-seguranca-privacidade §2.1).

    Entrada inexistente é sucesso: remover conta não pode falhar porque a senha
    já havia sido apagada manualmente.
    """
    key = _username(account, oauth=oauth)
    _MEMORY_STORE.delete(KEYRING_SERVICE, key)
    if not keyring_is_available():
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        return


# Nomes canônicos da interface interna de `05-seguranca-privacidade.md` §2.1,
# mantidos como aliases para que chamadores possam citar a família `keyring_*`.
keyring_get_credential = get_credential
keyring_set_credential = set_credential
keyring_delete_credential = delete_credential


# ─────────────────────── Sanitização de HTML (§4 de 05) ───────────────────────
# O pipeline vive em `core/sanitizer.py` porque este módulo passou do limiar de
# ~300 linhas que `02-arquitetura.md` §2.1 fixa para a separação. A separação é
# deliberada: gestão de credenciais é I/O contra o sistema operacional, e
# sanitização é função pura `str -> str` — as duas coisas que mais precisam de
# teste neste projeto, e testá-las no mesmo módulo tornaria o teste pior.
#
# A transferência é invisível para os chamadores: o import continua sendo
# `from pymail_client.core.security import sanitize_html`.

from pymail_client.core.sanitizer import (  # noqa: E402
    CSP_NO_IMAGES,
    CSP_WITH_IMAGES,
    SANITIZER_VERSION,
    SanitizeContext,
    SanitizeReport,
    html_to_text_plain,
    restore_remote_resources,
    sanitize_html,
    sanitize_html_with_report,
)

__all__ = [
    "CSP_NO_IMAGES",
    "CSP_WITH_IMAGES",
    "KEYRING_SERVICE",
    "SANITIZER_VERSION",
    "SanitizeContext",
    "SanitizeReport",
    "delete_credential",
    "get_credential",
    "html_to_text_plain",
    "keyring_delete_credential",
    "keyring_get_credential",
    "keyring_is_available",
    "keyring_set_credential",
    "restore_remote_resources",
    "sanitize_html",
    "sanitize_html_with_report",
    "set_credential",
]
