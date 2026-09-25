"""Cofre de credenciais falso, em memória (06-estrategia-de-testes.md §4.1).

Nenhum teste toca o keyring real do sistema operacional: ele tem efeito colateral
na máquina do desenvolvedor, comportamento diferente nas três plataformas e, em
Linux de CI, muitas vezes nem existe. A fixture substitui as funções do módulo
`keyring` por este dublê e zera o estado em cache de `core.security`, para que a
detecção de disponibilidade (§2.2 da spec de segurança) seja refeita a cada teste.
"""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import keyring.errors
import pytest

from pymail_client.core.security import reset_credential_state


class FakeKeyring:
    """Cofre em memória. Nenhum teste toca o keyring real do SO."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []
        # Permite simular ausência de backend (Linux sem secret service).
        self.available = True
        self.fail_on_write = False
        self.read_count = 0

    # ── API no formato do módulo `keyring` ──
    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        self.read_count += 1
        if not self.available:
            raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        if not self.available:
            raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")
        if self.fail_on_write:
            raise keyring.errors.KeyringError("cofre bloqueado")
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        if not self.available:
            raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")
        if (service, username) in self._store:
            del self._store[(service, username)]
        else:
            raise keyring.errors.PasswordDeleteError("credencial inexistente")

    # ── Apoio ao teste ──
    @property
    def stored_secrets(self) -> list[str]:
        return list(self._store.values())

    def store_keys(self) -> list[tuple[str, str]]:
        """Chaves (service, username) presentes, para provar o esquema de §2.1."""
        return list(self._store.keys())

    def has_entry_for(self, username: str) -> bool:
        return any(u == username for (_s, u) in self._store)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeKeyring]:
    """Instala o FakeKeyring no lugar do módulo `keyring` usado por core.security."""
    fake = FakeKeyring()
    monkeypatch.setattr(keyring, "get_password", fake.get_password, raising=True)
    monkeypatch.setattr(keyring, "set_password", fake.set_password, raising=True)
    monkeypatch.setattr(keyring, "delete_password", fake.delete_password, raising=True)
    # A detecção de disponibilidade (§2.2) pergunta qual backend está escolhido:
    # sem isto ela inspecionaria o cofre real da máquina em vez do dublê.
    monkeypatch.setattr(keyring, "get_keyring", lambda: fake, raising=True)
    reset_credential_state()
    yield fake
    reset_credential_state()
