"""Dublês dos testes: servidor IMAP/SMTP falsos e cofre de credenciais em memória.

Nenhum teste toca o keyring real do sistema operacional. O cofre falso é
instalado no lugar do módulo `keyring` pela fixture `fake_keyring`.
"""
