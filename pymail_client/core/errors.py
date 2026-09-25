"""Taxonomia de erros do PyMail Client (02-arquitetura.md §7).

A UI precisa reagir de formas diferentes a cada classe de erro; "deu erro" não
é informação útil. Esta hierarquia é a única forma como o núcleo comunica
falhas para a interface.
"""

from __future__ import annotations


class MailError(Exception):
    """Erro base do domínio de e-mail."""


class AuthError(MailError):
    """Credencial inválida → pedir de novo, pausar a conta."""


class NetworkError(MailError):
    """Erro transitório de rede → recuar e tentar."""


class TLSError(NetworkError):
    """Erro de certificado/TLS → NUNCA tentar sem validação (RNF-SEC-02)."""


class ProtocolError(MailError):
    """Servidor respondeu algo inesperado → registrar bruto."""


class NotFoundError(MailError):
    """Mensagem/pasta não existe mais → remover do cache."""


class OperationCancelled(MailError):
    """Cancelamento cooperativo — não é falha; não notificar o usuário."""


class StorageError(MailError):
    """Erro de banco → caminho de recuperação (RF-SET-05)."""
