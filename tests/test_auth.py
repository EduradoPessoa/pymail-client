"""Testes de autenticação e credenciais (T-03).

Cobre: RF-ACC-01, RF-ACC-04, RNF-SEC-01 · CA-RF-ACC-04-1, CA-RNF-SEC-01-1
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import pytest

from pymail_client.core.auth import (
    AccountConfig,
    AuthProvider,
    AuthResult,
    PasswordAuth,
    get_provider,
    register_provider,
)
from pymail_client.core.errors import AuthError
from pymail_client.core.security import (
    MEMORY_MODE_WARNING,
    credential_storage_mode,
    delete_credential,
    get_credential,
    pending_warnings,
    set_credential,
)

SECRET = "senha-super-secreta-42"
OAUTH_SECRET = '{"access_token": "tok", "expires_at": 0.0}'


def _account(email: str = "a@exemplo.com") -> AccountConfig:
    """Conta mínima válida, com os mesmos campos de `accounts` (03-modelo-de-dados §3)."""
    return AccountConfig(
        email=email,
        username=email,
        incoming_host="imap.exemplo.com",
        incoming_port=993,
        outgoing_host="smtp.exemplo.com",
        outgoing_port=587,
    )


def test_credential_never_reaches_database_or_config(tmp_path: Path, fake_keyring) -> None:
    """CA-RNF-SEC-01-1: a senha não existe em banco, config nem log."""
    account = _account()
    set_credential(account.email, SECRET)

    # O segredo só pode existir no cofre do SO, sob a chave normativa.
    assert fake_keyring.stored_secrets == [SECRET]
    assert fake_keyring.store_keys() == [("pymail-client", "a@exemplo.com")]

    # A verificação no banco depende de `core/storage.py` (T-02). Enquanto ela não
    # existe, a varredura abaixo cobre tudo que existe: qualquer arquivo criado
    # sob tmp_path, o banco inclusive, e config.toml.
    db_path = tmp_path / "pymail.db"
    if importlib.util.find_spec("pymail_client.core.storage") is not None:
        from pymail_client.core.storage import Storage

        storage = Storage(db_path)
        storage.migrate()
        storage.upsert_account(account)
        storage.close_thread_connection()

    assert not list(tmp_path.rglob("*.toml")) or all(
        SECRET not in path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.toml")
    )
    for path in tmp_path.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        assert SECRET.encode() not in payload
        # Forma reversível: base64 e hex do valor também não podem aparecer.
        assert base64.b64encode(SECRET.encode()) not in payload
        assert SECRET.encode().hex().encode() not in payload
    assert credential_storage_mode() == "keyring"


def test_register_provider_needs_no_ui_or_storage_change() -> None:
    """CA-RF-ACC-04-1: é esta indireção que torna a fase 2 aditiva."""

    class FakeOAuthProvider(AuthProvider):
        name = "oauth2-fake"

        def authenticate(self, account, *, interactive: bool):
            return AuthResult(
                username=account.username, secret=None, access_token="tok", expires_at=None
            )

        def can_renew_silently(self) -> bool:
            return True

        def invalidate(self) -> None: ...

    register_provider(FakeOAuthProvider)
    assert isinstance(get_provider("oauth2-fake"), FakeOAuthProvider)
    # Nenhuma outra peça do sistema foi tocada: senha e OAuth coexistem.
    assert isinstance(get_provider("password"), PasswordAuth)
    with pytest.raises(AuthError):
        get_provider("inexistente")


def test_password_auth_reads_only_from_keyring(fake_keyring) -> None:
    """RF-ACC-04 / RF-ACC-01: a senha vem do cofre, nunca de arquivo ou banco."""
    account = _account()
    provider = get_provider("password")
    assert provider.can_renew_silently() is False

    # Ausência de credencial é AuthError: pausa só esta conta (05 §2.3).
    with pytest.raises(AuthError):
        provider.authenticate(account, interactive=False)

    set_credential(account.email, SECRET)
    result = provider.authenticate(account, interactive=True)
    assert result.secret == SECRET
    assert result.username == account.username
    assert result.access_token is None
    assert result.expires_at is None
    # A leitura aconteceu no cofre do SO, com a chave normativa do §3.
    assert ("get", "pymail-client", "a@exemplo.com") in fake_keyring.calls
    assert [c for c in fake_keyring.calls if c[0] == "set"] == [
        ("set", "pymail-client", "a@exemplo.com")
    ]

    # invalidate() descarta o cache do provider, não o segredo do cofre.
    provider.invalidate()
    assert get_credential(account.email) == SECRET
    assert provider.authenticate(account, interactive=True).secret == SECRET


def test_account_deletion_removes_credential(fake_keyring) -> None:
    """CA-RF-ACC-05-1 (parte de credencial): senha e #oauth saem juntas."""
    email = "a@exemplo.com"
    set_credential(email, SECRET)
    set_credential(email, OAUTH_SECRET, oauth=True)

    delete_credential(email)
    delete_credential(email, oauth=True)

    assert not fake_keyring.has_entry_for(email)
    assert not fake_keyring.has_entry_for(f"{email}#oauth")
    assert fake_keyring.stored_secrets == []
    assert [c for c in fake_keyring.calls if c[0] == "delete"] == [
        ("delete", "pymail-client", "a@exemplo.com"),
        ("delete", "pymail-client", "a@exemplo.com#oauth"),
    ]

    # Idempotente: apagar de novo não falha (05 §2.1).
    delete_credential(email)
    assert get_credential(email) is None


def test_oauth_item_does_not_overwrite_password(fake_keyring) -> None:
    """O sufixo `#oauth` separa os dois segredos da mesma conta (05 §2.1)."""
    set_credential("a@exemplo.com", SECRET)
    set_credential("a@exemplo.com", OAUTH_SECRET, oauth=True)

    assert get_credential("a@exemplo.com") == SECRET
    assert get_credential("a@exemplo.com", oauth=True) == OAUTH_SECRET
    assert fake_keyring.stored_secrets == [SECRET, OAUTH_SECRET]


def test_credential_key_is_normalized(fake_keyring) -> None:
    """`email.strip().lower()`: a mesma conta não gera duas chaves."""
    set_credential("  Joao@Exemplo.COM ", SECRET)
    assert fake_keyring.store_keys() == [("pymail-client", "joao@exemplo.com")]
    assert get_credential("joao@exemplo.com") == SECRET


def test_secret_is_redacted_in_repr_and_str(fake_keyring) -> None:
    """05 §2.6.1 e §2.6.2: `repr` e `str` não revelam o segredo."""
    from pymail_client.core.security import Redacted

    set_credential("a@exemplo.com", SECRET)
    result = PasswordAuth().authenticate(_account(), interactive=True)

    assert repr(result) == (
        "AuthResult(username=<oculto>, secret=<oculto>, access_token=None, expires_at=None)"
    )
    assert SECRET not in repr(result)
    assert "a@exemplo.com" not in repr(result)
    assert "***" in str(result.secret)
    assert f"{result.secret}" == "***"
    assert isinstance(result.secret, Redacted)
    assert result.secret.reveal() == SECRET
    assert result.secret == SECRET  # continua sendo str para o protocolo
    # O cofre recebe o valor utilizável, não a máscara.
    assert fake_keyring.stored_secrets == [SECRET]


def test_unavailable_keyring_never_writes_plaintext_file(tmp_path: Path, fake_keyring) -> None:
    """05 §2.2: sem cofre, memória da sessão + aviso; nunca arquivo em texto claro."""
    fake_keyring.available = False

    assert credential_storage_mode() == "memory"
    set_credential("a@exemplo.com", SECRET)

    assert get_credential("a@exemplo.com") == SECRET
    assert credential_storage_mode() == "memory"
    assert pending_warnings(), "a degradação precisa ser visível ao usuário"
    assert fake_keyring.stored_secrets == []

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()

    # A memória some com a sessão: `reset_credential_state()` é o encerramento.
    from pymail_client.core.security import reset_credential_state

    reset_credential_state()
    assert get_credential("a@exemplo.com") is None
    # A degrração é reexibida enquanto o modo memória continuar valendo (§2.2).
    assert MEMORY_MODE_WARNING in pending_warnings()


def test_plaintext_backend_is_rejected(fake_keyring, monkeypatch: pytest.MonkeyPatch) -> None:
    """05 §2.2: backend em texto claro é rebaixado a memória, como se não houvesse."""
    import keyring

    from pymail_client.core.security import keyring_is_available, reset_credential_state

    class PlaintextKeyring:
        pass

    monkeypatch.setattr(keyring, "get_keyring", lambda: PlaintextKeyring(), raising=True)
    reset_credential_state()

    assert keyring_is_available() is False
    assert credential_storage_mode() == "memory"

    set_credential("a@exemplo.com", SECRET)
    assert fake_keyring.stored_secrets == []
    assert get_credential("a@exemplo.com") == SECRET


def test_missing_backend_is_reported_as_unavailable(fake_keyring, monkeypatch) -> None:
    """05 §2.4: sessão sem Secret Service cai para memória, sem quebrar o cliente."""
    import keyring
    import keyring.errors

    from pymail_client.core.security import keyring_is_available, reset_credential_state

    def _no_backend():
        raise keyring.errors.NoKeyringError("nenhum backend de keyring disponível")

    monkeypatch.setattr(keyring, "get_keyring", _no_backend, raising=True)
    reset_credential_state()

    assert keyring_is_available() is False
    assert credential_storage_mode() == "memory"
