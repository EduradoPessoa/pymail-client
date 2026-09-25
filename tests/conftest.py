"""Fixtures compartilhadas pelos testes do PyMail Client.

Cada fixture é criada aqui em vez de repetida por arquivo de teste, para que
mudanças de contrato (servidor IMAP falso, cofre de credenciais, banco) fiquem
visíveis num único lugar.
"""

from __future__ import annotations

import pytest

from tests.fakes.fake_keyring import fake_keyring  # noqa: F401
from tests.fakes.imap_server import (
    imap_server_factory as _make_imap_server,
)
from tests.fakes.imap_server import (
    plain_server as _make_plain_server,
)
from tests.fakes.imap_server import (
    tls_server_selfsigned as _make_tls_server,
)


@pytest.fixture
def imap_server_factory():
    """Factory para criar servidores IMAP de teste.

    Uso:
        def test_algo(imap_server_factory):
            server = imap_server_factory(refuse_login=True)
            # server.port tem a porta
            # server.commands tem a lista de comandos recebidos
    """
    servers = []

    def _factory(**kwargs):
        server = _make_imap_server(**kwargs)
        servers.append(server)
        return server

    yield _factory

    for s in servers:
        s.shutdown_server()


@pytest.fixture
def tls_server_selfsigned():
    """Servidor TLS com certificado auto-assinado."""
    server = _make_tls_server()
    yield server
    server.shutdown_server()


@pytest.fixture
def plain_server():
    """Servidor IMAP sem TLS (texto claro)."""
    server = _make_plain_server()
    yield server
    server.shutdown_server()
