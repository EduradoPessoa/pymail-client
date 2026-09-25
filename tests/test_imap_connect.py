"""Testes de conexão IMAP e validação TLS (T-04).

Cobre: CA-RF-ACC-03-1, CA-RNF-SEC-02-1
"""

from __future__ import annotations

import pytest

from pymail_client.core.errors import AuthError, NetworkError, TLSError
from pymail_client.core.network.imap_client import ImapClient
from tests.fakes.imap_server import imap_server_factory as _make_imap_server


def test_error_kinds_are_distinguished() -> None:
    """CA-RF-ACC-03-1: DNS, recusa de conexão e credencial inválida são distintos."""
    # DNS falha (host inexistente)
    with pytest.raises(NetworkError, match="resolver"):
        ImapClient(host="host-que-nao-existe.invalid", port=993).connect()

    # Conexão recusada (servidor não escuta) — usa texto claro para testar recusa pura
    with pytest.raises(
        NetworkError, match="recusa|connection refused|conexão recusada|recusou ativamente"
    ):
        ImapClient(host="127.0.0.1", port=12345, security="none", allow_insecure=True).connect()

    # Credencial inválida — usa servidor sem TLS que recusa login
    server = _make_imap_server(use_tls=False, refuse_login=True)
    try:
        with pytest.raises(AuthError):
            ImapClient(
                host="127.0.0.1",
                port=server.port,
                username="user",
                password="wrong",
                security="none",
                allow_insecure=True,
            ).connect()
    finally:
        server.shutdown_server()


def test_self_signed_certificate_is_a_hard_failure(tls_server_selfsigned) -> None:
    """CA-RNF-SEC-02-1: nunca degradar para texto claro em silêncio."""
    with pytest.raises(TLSError):
        ImapClient(
            host="127.0.0.1",
            port=tls_server_selfsigned.port,
            username="user",
            password="pass",
        ).connect()


def test_plaintext_connection_is_refused_by_default(plain_server) -> None:
    """TLS é obrigatório por padrão."""
    with pytest.raises(TLSError):
        ImapClient(
            host="127.0.0.1",
            port=plain_server.port,
            username="user",
            password="pass",
            security="none",
            allow_insecure=False,
        ).connect()
