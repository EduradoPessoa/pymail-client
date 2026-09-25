"""Cliente IMAP síncrono (T-04: connect/close).

Implementa `IncomingMailClient` de `core/network/base.py`.
Conversão de erros segue `core/errors.py` e `02-arquitetura.md` §7.
"""

from __future__ import annotations

import imaplib
import socket
import ssl
from collections.abc import Sequence

from pymail_client.core.errors import AuthError, NetworkError, TLSError
from pymail_client.core.network.base import (
    AttachmentMeta,
    FolderStatus,
    HeaderEnvelope,
    IncomingMailClient,
    RawMessage,
    RemoteFolder,
)


class ImapClient(IncomingMailClient):
    """Cliente IMAP com validação TLS obrigatória e erros tipados."""

    def __init__(
        self,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        *,
        security: str = "ssl",  # "ssl" | "starttls" | "none"
        allow_insecure: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._security = security
        self._allow_insecure = allow_insecure
        self._timeout = timeout
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
        self._capabilities: set[str] = set()

    def connect(self) -> None:
        """Estabelece conexão e autentica.

        Raises:
            NetworkError: Falha de DNS, conexão recusada, timeout.
            TLSError: Falha de certificado/validação TLS.
            AuthError: Credencial inválida.
        """
        if self._security == "none" and not self._allow_insecure:
            raise TLSError("Plaintext connection refused (allow_insecure=False)")

        try:
            if self._security == "ssl":
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                self._conn = imaplib.IMAP4_SSL(
                    self._host, self._port, ssl_context=ssl_context, timeout=self._timeout
                )
            elif self._security == "starttls":
                self._conn = imaplib.IMAP4(self._host, self._port, timeout=self._timeout)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                self._conn.starttls(ssl_context=ssl_context)
            else:  # "none"
                self._conn = imaplib.IMAP4(self._host, self._port, timeout=self._timeout)

            # Login
            typ, data = self._conn.login(self._username, self._password)
            if typ != "OK":
                raise AuthError("Login failed")

            # Capture capabilities
            self._capabilities = self._parse_capabilities()

        except socket.gaierror as e:
            raise NetworkError(f"DNS resolver failed: {e}") from e
        except ConnectionRefusedError as e:
            raise NetworkError(f"Connection refused: {e}") from e
        except TimeoutError as e:
            raise NetworkError(f"Connection timeout: {e}") from e
        except ssl.SSLError as e:
            raise TLSError(f"TLS/SSL error: {e}") from e
        except imaplib.IMAP4.error as e:
            msg = str(e).lower()
            if "authentication" in msg or "login" in msg or "credentials" in msg:
                raise AuthError(f"Authentication failed: {e}") from e
            raise NetworkError(f"IMAP protocol error: {e}") from e
        except OSError as e:
            raise NetworkError(f"Network error: {e}") from e

    def close(self) -> None:
        """Fecha a conexão."""
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None
            self._capabilities.clear()

    def _parse_capabilities(self) -> set[str]:
        if not self._conn:
            return set()
        try:
            typ, data = self._conn.capability()
            if typ == "OK" and data:
                caps = data[0].decode().split()
                return set(caps)
        except Exception:
            pass
        return set()

    def supports(self, capability: str) -> bool:
        return capability.upper() in self._capabilities

    # Métodos do protocolo (stubs para T-04, implementados em tarefas futuras)
    def list_folders(self) -> list[RemoteFolder]:
        raise NotImplementedError("list_folders not implemented yet")

    def select_folder(self, name: str) -> FolderStatus:
        raise NotImplementedError("select_folder not implemented yet")

    def fetch_headers(self, start_uid: int, limit: int) -> list[HeaderEnvelope]:
        raise NotImplementedError("fetch_headers not implemented yet")

    def fetch_body(self, remote_id: str) -> RawMessage:
        raise NotImplementedError("fetch_body not implemented yet")

    def fetch_attachment(self, remote_id: str, part_id: str) -> bytes:
        raise NotImplementedError("fetch_attachment not implemented yet")

    def list_attachments(self, remote_id: str) -> list[AttachmentMeta]:
        raise NotImplementedError("list_attachments not implemented yet")

    def set_flags(self, remote_ids: Sequence[str], flags: Sequence[str], add: bool) -> None:
        raise NotImplementedError("set_flags not implemented yet")

    def move(self, remote_ids: Sequence[str], destination: str) -> None:
        raise NotImplementedError("move not implemented yet")

    def wait_for_changes(self, timeout_s: float) -> list[str]:
        raise NotImplementedError("wait_for_changes not implemented yet")
