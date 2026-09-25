"""Dataclasses de domínio (02-arquitetura.md §5).

Todas são **congeladas**: elas atravessam sinais entre a thread da interface e as
threads de trabalho, e um objeto mutável compartilhado entre threads é bug, não
estilo. Alterar um registro de domínio é produzir outro com `dataclasses.replace`.

`AccountConfig` é o tipo que `Storage.upsert_account` recebe e que
`AuthProvider.authenticate` consome; os demais registros de domínio (cabeçalhos,
pastas, rascunhos) entram aqui à medida que as tarefas seguintes os exigem.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountConfig:
    """Uma conta de correio, espelhando a tabela `accounts` (03-modelo-de-dados §3).

    Não existe campo de senha nem de token aqui, e essa ausência é_normativa_:
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
