"""Fixtures compartilhadas pelos testes do PyMail Client.

Cada fixture é criada aqui em vez de repetida por arquivo de teste, para que
mudanças de contrato (servidor IMAP falso, cofre de credenciais, banco) fiquem
visíveis num único lugar.
"""

from __future__ import annotations

# As fixtures compartilhadas (servidor IMAP falso, cofre de credenciais, banco)
# entram aqui a partir de T-02; este arquivo é o ponto único de contrato.
