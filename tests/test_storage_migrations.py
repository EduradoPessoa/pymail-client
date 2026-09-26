import sqlite3
from pathlib import Path

import pytest

from pymail_client.core.errors import StorageError
from pymail_client.core.storage import MIGRATIONS, SCHEMA_VERSION, Storage


def test_fresh_database_migrates_to_current_version(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "pymail.db")
    assert storage.migrate() == SCHEMA_VERSION
    assert storage.migrate() == SCHEMA_VERSION  # idempotente


def test_foreign_keys_are_enabled_per_connection(tmp_path: Path) -> None:
    """Sem isso, ON DELETE CASCADE vira decoração e CA-RF-ACC-05-1 falha."""
    storage = Storage(tmp_path / "pymail.db")
    storage.migrate()
    assert storage._conn().execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert storage._conn().execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_newer_database_version_is_refused_without_writing(tmp_path: Path) -> None:
    """CA-RF-SET-03-1: recusar é obrigatório; adivinhar corrompe dados."""
    path = tmp_path / "pymail.db"
    storage = Storage(path)
    storage.migrate()
    storage._conn().execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION + 5, 0),
    )
    storage._conn().commit()
    storage.close_thread_connection()

    # CA-RF-SET-03-1 (parte 2): a recusa não escreve nada no banco.
    before = path.read_bytes()

    with pytest.raises(StorageError, match="versão"):
        Storage(path).migrate()

    assert path.read_bytes() == before, "banco foi modificado ao recusar a migração"


def test_failed_migration_rolls_back_entirely(tmp_path: Path, monkeypatch) -> None:
    """Migration é transacional: falha no meio deixa a versão anterior intacta."""
    path = tmp_path / "pymail.db"
    storage = Storage(path)
    storage.migrate()
    original_version = SCHEMA_VERSION

    def broken(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE parcial (x INTEGER)")
        raise RuntimeError("falha simulada no meio da migração")

    monkeypatch.setitem(MIGRATIONS, original_version + 1, broken)
    with pytest.raises(RuntimeError, match="falha simulada"):
        storage.migrate()

    # Migration é transacional: nada da migration 2 deve ter persistido.
    conn = sqlite3.connect(str(path))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        conn.close()
    assert "parcial" not in tables
    assert version == original_version
