"""Dataclasses de domínio (02-arquitetura.md §5).

Todas são **congeladas**: elas atravessam sinais entre a thread da interface e as
threads de trabalho, e um objeto mutável compartilhado entre threads é bug, não
estilo. Alterar um registro de domínio é produzir outro com `dataclasses.replace`.

A maioria dessas classes é definida em `02-arquitetura.md` §5.1 e §5.2 como parte
do contrato de interface; aqui elas são reunidas em um único módulo para que
`base.py`, `auth.py` e `storage.py` as importem de uma só fonte de verdade, e
para que o protocolo `IncomingMailClient` não precise duplicar as definições.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RemoteFolder:
    """Pasta remota no servidor de entrada."""

    name: str
    delimiter: str
    kind: str  # inbox | sent | drafts | trash | archive | spam | custom


@dataclass(frozen=True, slots=True)
class FolderStatus:
    """Estado de uma pasta selecionada."""

    exists: int
    uidvalidity: int
    uidnext: int
    unread: int


@dataclass(frozen=True, slots=True)
class HeaderEnvelope:
    """Cabeçalhos de uma mensagem. Nunca contém corpo (RF-MSG-01)."""

    remote_id: str  # UID no IMAP; identificador estável dentro da pasta
    message_id: str | None
    subject: str
    from_name: str
    from_addr: str
    to_addrs: tuple[str, ...]
    cc_addrs: tuple[str, ...]
    date_utc: datetime
    size_bytes: int
    flags: frozenset[str]
    has_attachments: bool
    in_reply_to: str | None
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawMessage:
    """Mensagem completa, ainda não sanitizada."""

    remote_id: str
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class AttachmentMeta:
    """Metadados de anexo."""

    part_id: str
    filename: str
    mime_type: str
    size_bytes: int
    content_id: str | None


@dataclass(frozen=True, slots=True)
class AccountConfig:
    """Uma conta de correio, espelhando a tabela `accounts` (03-modelo-de-dados §3).

    Não existe campo de senha nem de token aqui, e essa ausência é normativa:
    a credencial vive no keyring do SO sob a chave `pymail-client` /
    `<email>` (05-seguranca-privacidade §2.1). O banco guarda apenas metadados de
    conexão e é cache descartável (RF-SET-05).
    """

    email: str
    username: str = ""
    display_name: str = ""
    protocol: str = "imap"
    auth_type: str = "password"
    incoming_host: str = ""
    incoming_port: int = 993
    incoming_security: str = "ssl"
    outgoing_host: str = ""
    outgoing_port: int = 587
    outgoing_security: str = "starttls"
    allow_insecure_outgoing: bool = False
    is_enabled: bool = True
    sort_order: int = 0
    created_at: int = 0
    updated_at: int = 0


@dataclass(frozen=True, slots=True)
class FolderRecord:
    """Uma pasta como armazenada no cache local."""

    id: int
    account_id: int
    remote_name: str
    display_name: str
    kind: str
    delimiter: str
    uidvalidity: int
    uidnext: int
    unread_count: int
    is_selectable: bool
    last_sync_at: int | None


@dataclass(frozen=True, slots=True)
class MessageRow:
    """Cabeçalho de mensagem retornado pela lista de referência (03 §9).

    Só as colunas que a interface lista e a busca precisam; o corpo e metadados
    de anexo são buscados separadamente por demanda.
    """

    id: int
    remote_id: str
    subject: str
    from_name: str
    from_addr: str
    date_utc: int
    is_read: int
    is_flagged: int
    has_attachments: int
    body_state: str


@dataclass(frozen=True, slots=True)
class Draft:
    """Rascunho de mensagem pronto para enfileiramento na outbox (RF-SND-03).

    `to_addrs`, `cc_addrs`, `bcc_addrs` e `attachment_paths` são JSON serializados
    como na tabela `outbox`; o compositor os produz a partir de listas em memória.
    """

    message_id: str
    to_addrs: str
    cc_addrs: str
    bcc_addrs: str
    subject: str
    body_text: str
    body_html: str | None
    in_reply_to: str | None
    references_hdr: str | None
    attachment_paths: str
    state: str
    send_at: int | None
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class OutgoingRow:
    """Uma entrada da fila de saída, tal como persistida em `outbox`."""

    id: int
    account_id: int | None
    message_id: str
    to_addrs: str
    cc_addrs: str
    bcc_addrs: str
    subject: str
    body_text: str
    body_html: str | None
    in_reply_to: str | None
    references_hdr: str | None
    attachment_paths: str
    state: str
    send_at: int | None
    attempts: int
    last_error: str | None
    smtp_response: str | None
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class MessageFilters:
    """Filtros combináveis para `list_messages` e `search` (RF-SRCH-03).

    Todos os campos são `None` ou `False` por padrão: uma instância vazia
    significa "sem filtro", e a interface constrói instâncias a partir de apenas
    os campos que o usuário preencheu.
    """

    account_id: int | None = None
    folder_id: int | None = None
    since: int | None = None
    unread_only: bool = False
    with_attachments: bool = False
    from_addr: str | None = None
