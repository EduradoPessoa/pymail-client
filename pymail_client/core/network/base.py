"""Contratos de interface de rede (02-arquitetura.md §5.1).

Este módulo define o protocolo `IncomingMailClient` na íntegra, exatamente
como na especificação. A implementação chega por partes (T-04, T-10, T-11,
T-12, T-14, T-17), mas o contrato é completo desde o início porque é a
interface que a fase 2 herda.

As dataclasses de domínio (`RemoteFolder`, `FolderStatus`, `HeaderEnvelope`,
`RawMessage`, `AttachmentMeta`) são importadas de `core.models` — a única fonte
de verdade — e re-exportadas aqui para que `base.py` continue sendo o ponto de
import esperado por `tests/fakes/fake_incoming.py` e pela documentação de
`06-estrategia-de-testes.md` §4.2.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pymail_client.core.models import (
    AttachmentMeta,
    FolderStatus,
    HeaderEnvelope,
    RawMessage,
    RemoteFolder,
)

__all__ = [
    "AttachmentMeta",
    "FolderStatus",
    "HeaderEnvelope",
    "IncomingMailClient",
    "RawMessage",
    "RemoteFolder",
]


@runtime_checkable
class IncomingMailClient(Protocol):
    """Contrato de recebimento. IMAP hoje, POP3 em [F2] — a UI não distingue."""

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def list_folders(self) -> Sequence[RemoteFolder]: ...
    def select_folder(self, name: str) -> FolderStatus: ...
    def fetch_headers(self, start_uid: int, limit: int) -> Sequence[HeaderEnvelope]: ...
    def fetch_body(self, remote_id: str) -> RawMessage: ...
    def fetch_attachment(self, remote_id: str, part_id: str) -> bytes: ...
    def list_attachments(self, remote_id: str) -> Sequence[AttachmentMeta]: ...
    def set_flags(self, remote_ids: Sequence[str], flags: Sequence[str], add: bool) -> None: ...
    def move(self, remote_ids: Sequence[str], destination: str) -> None: ...
    def supports(self, capability: str) -> bool: ...
    def wait_for_changes(self, timeout_s: float) -> Sequence[str]:
        """IDLE quando disponível; NOOP + UID SEARCH como alternativa (RF-MSG-05)."""
        ...
