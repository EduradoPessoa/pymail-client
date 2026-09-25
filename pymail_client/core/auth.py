"""Provedor de autenticação plugável (02-arquitetura.md §5.2, ADR-002).

Senha hoje, OAuth2 na fase 2, sem alterar a interface nem o armazenamento: a UI
e o storage pedem dados de autenticação a um provider e tratam um resultado
uniforme. `OAuth2Auth` entra por `register_provider`, e nenhum chamador muda.

O contrato abaixo é normativo e seguido literalmente, com uma única concessão à
spec de segurança: `AuthResult` declara `secret` e `access_token` com
`repr=False` e `__repr__` próprio, para que um `logger.debug` não vaze o segredo
(05-seguranca-privacidade §2.6.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pymail_client.core.errors import AuthError
from pymail_client.core.models import AccountConfig
from pymail_client.core.security import Redacted, get_credential

__all__ = [
    "AccountConfig",
    "AuthError",
    "AuthProvider",
    "AuthResult",
    "PasswordAuth",
    "get_provider",
    "register_provider",
]


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Resultado uniforme de autenticação, independente do mecanismo."""

    username: str
    secret: str | None = field(default=None, repr=False)
    access_token: str | None = field(default=None, repr=False)
    expires_at: float | None = None

    def __repr__(self) -> str:
        # Username é endereço de e-mail, portanto metadado pessoal (05 §2.5): sai
        # mascarado junto com os segredos. O `AuthResult(...)` aparece em log de
        # depuração com frequência, e o valor verdadeiro não pode acompanhá-la.
        return (
            f"AuthResult(username={_masked(self.username)}, secret={_masked(self.secret)}, "
            f"access_token={_masked(self.access_token)}, expires_at={self.expires_at!r})"
        )


def _masked(value: object | None) -> str:
    return "None" if value is None else "<oculto>"


class AuthProvider(ABC):
    """D2: senha hoje, OAuth2 na fase 2, sem alterar UI nem storage."""

    name: str

    @abstractmethod
    def authenticate(self, account: AccountConfig, *, interactive: bool) -> AuthResult: ...

    @abstractmethod
    def can_renew_silently(self) -> bool: ...

    @abstractmethod
    def invalidate(self) -> None: ...


class PasswordAuth(AuthProvider):
    """Lê a credencial no keyring. Nunca aceita senha vinda de arquivo ou banco."""

    name = "password"

    def __init__(self) -> None:
        # Cache por conta apenas para evitar duas leituras de cofre na mesma
        # conexão; `invalidate()` o descarta (05-seguranca-privacidade §2.3).
        self._cache: dict[str, AuthResult] = {}

    def authenticate(self, account: AccountConfig, *, interactive: bool) -> AuthResult:
        # `interactive` é ignorado de propósito: este provider nunca abre diálogo.
        # Pedir a senha é prerrogativa da UI, e é ela que decide oferecer
        # reautenticação quando este método levanta `AuthError`.
        cached = self._cache.get(_cache_key(account))
        if cached is not None:
            return cached

        secret = get_credential(account.email)
        if secret is None:
            # Conta existe e o cofre está vazio: pausa **aquela** conta e oferece
            # reautenticação. As demais contas seguem (CA-RF-ACC-02-1).
            raise AuthError(
                f"no credential stored for account {account.email!r}; reauthentication required"
            )
        result = AuthResult(
            username=account.username,
            secret=secret if isinstance(secret, Redacted) else Redacted(secret),
            access_token=None,
            expires_at=None,
        )
        self._cache[_cache_key(account)] = result
        return result

    def can_renew_silently(self) -> bool:
        """Senha não se renova sozinha: só com o usuário presente."""
        return False

    def invalidate(self) -> None:
        self._cache.clear()


def _cache_key(account: AccountConfig) -> str:
    return account.email.strip().lower()


# Registry: a fase 2 registra OAuth2Auth aqui, sem tocar em chamadores.
_PROVIDERS: dict[str, type[AuthProvider]] = {PasswordAuth.name: PasswordAuth}


def register_provider(cls: type[AuthProvider]) -> type[AuthProvider]:
    _PROVIDERS[cls.name] = cls
    return cls


def get_provider(name: str) -> AuthProvider:
    """Instancia o provider registrado com esse nome.

    Nome desconhecido é `AuthError` e não `KeyError`: a UI reage a erro de
    autenticação, e um `KeyError` escaping daqui apareceria como erro fatal.
    """
    try:
        provider = _PROVIDERS[name]
    except KeyError:
        known = ", ".join(sorted(_PROVIDERS)) or "nenhum"
        raise AuthError(f"unknown auth provider {name!r}; registered: {known}") from None
    return provider()
