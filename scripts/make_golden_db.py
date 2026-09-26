#!/usr/bin/env python
"""Generate the v1 golden database for migration preservation tests.

Creates a Storage, migrates to version 1, populates with synthetic data
(two accounts, three folders, 200 messages, 20 bodies, two outbox drafts),
and writes the result to ``tests/fixtures/db/v1_golden.db``.

The database is committed to git as a fixed reference (06-estrategia-de-testes.md
§7.4.5, item L-01). Running this script regenerates the file deterministically;
the row counts are the contract, not the data itself.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from pymail_client.core.storage import Storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "db" / "v1_golden.db"
TEMP_DB = FIXTURE_PATH.parent / "_golden_build.db"


def _populate(conn: sqlite3.Connection, now: int) -> None:
    """Insert synthetic data into a freshly migrated v1 database."""
    cur = conn.cursor()

    # ── Two accounts ──────────────────────────────────────────────────
    cur.execute(
        """
        INSERT INTO accounts (email, display_name, protocol, auth_type,
            username, incoming_host, incoming_port, incoming_security,
            outgoing_host, outgoing_port, outgoing_security,
            allow_insecure_outgoing, is_enabled, sort_order, created_at, updated_at)
        VALUES (?, ?, 'imap', 'password', ?, ?, 993, 'ssl', ?, 587, 'starttls',
            0, 1, 0, ?, ?)
        """,
        (
            "user1@example.com",
            "User One",
            "user1@example.com",
            "imap.example.com",
            "smtp.example.com",
            now,
            now,
        ),
    )
    cur.execute(
        """
        INSERT INTO accounts (email, display_name, protocol, auth_type,
            username, incoming_host, incoming_port, incoming_security,
            outgoing_host, outgoing_port, outgoing_security,
            allow_insecure_outgoing, is_enabled, sort_order, created_at, updated_at)
        VALUES (?, ?, 'imap', 'password', ?, ?, 993, 'ssl', ?, 587, 'starttls',
            0, 1, 1, ?, ?)
        """,
        (
            "user2@example.com",
            "User Two",
            "user2@example.com",
            "imap.example.com",
            "smtp.example.com",
            now,
            now,
        ),
    )

    account1_id = 1
    account2_id = 2

    # ── Three folders (2 for account 1, 1 for account 2) ──────────────
    cur.execute(
        """
        INSERT INTO folders (account_id, remote_name, display_name, kind,
            delimiter, uidvalidity, uidnext, unread_count, is_selectable,
            last_sync_at)
        VALUES (?, 'INBOX', 'INBOX', 'inbox', '/', 300, 201, 50, 1, ?)
        """,
        (account1_id, now),
    )
    cur.execute(
        """
        INSERT INTO folders (account_id, remote_name, display_name, kind,
            delimiter, uidvalidity, uidnext, unread_count, is_selectable,
            last_sync_at)
        VALUES (?, 'Sent', 'Sent', 'sent', '/', 400, 101, 0, 1, ?)
        """,
        (account1_id, now),
    )
    cur.execute(
        """
        INSERT INTO folders (account_id, remote_name, display_name, kind,
            delimiter, uidvalidity, uidnext, unread_count, is_selectable,
            last_sync_at)
        VALUES (?, 'INBOX', 'INBOX', 'inbox', '/', 500, 151, 20, 1, ?)
        """,
        (account2_id, now),
    )

    folder1_id = 1  # account1/INBOX
    folder2_id = 2  # account1/Sent
    folder3_id = 3  # account2/INBOX

    # ── 200 messages (100 + 50 + 50) ───────────────────────────────────
    for i in range(1, 201):
        if i <= 100:
            folder_id, account_id = folder1_id, account1_id
        elif i <= 150:
            folder_id, account_id = folder2_id, account1_id
        else:
            folder_id, account_id = folder3_id, account2_id

        is_read = 1 if i > 20 else 0
        has_attachments = 1 if i % 10 == 0 else 0
        body_state = "cached" if i <= 20 else "headers"

        cur.execute(
            """
            INSERT INTO messages (account_id, folder_id, remote_id, message_id,
                in_reply_to, references_hdr, thread_id, subject, from_name,
                from_addr, to_addrs, cc_addrs, date_utc, size_bytes,
                has_attachments, is_read, is_flagged, is_answered, is_draft,
                body_state, body_fetched_at, snoozed_until, pending_op,
                created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, '[]', '[]', ?, ?, ?,
                ?, 0, 0, 0, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                account_id,
                folder_id,
                str(i),
                f"<msg{i}@example.com>",
                f"Assunto {i}",
                f"Remetente {i}",
                f"remetente{i}@example.com",
                now - i,
                2048,
                has_attachments,
                is_read,
                body_state,
                now if i <= 20 else None,
                now,
                now,
            ),
        )

    # ── 20 bodies (for messages 1–20) ──────────────────────────────────
    for i in range(1, 21):
        text = f"Corpo da mensagem {i}. " * 20
        html = f"<p>Corpo da mensagem {i}</p>"
        cur.execute(
            """
            INSERT INTO bodies (message_rowid, text_plain, html_sanitized,
                sanitizer_version, size_bytes, fetched_at, last_access_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (i, text, html, len(text) + len(html), now, now),
        )
        # FTS5 index entry — ADR-005: maintained explicitly in the same tx.
        cur.execute(
            """
            INSERT INTO messages_fts (rowid, subject, sender, recipients, body)
            VALUES (?, ?, ?, ?, ?)
            """,
            (i, f"Assunto {i}", f"Remetente {i} remetente{i}@example.com", "[]", text),
        )

    # ── Two drafts in outbox ───────────────────────────────────────────
    cur.execute(
        """
        INSERT INTO outbox (account_id, message_id, to_addrs, cc_addrs,
            bcc_addrs, subject, body_text, body_html, in_reply_to,
            references_hdr, attachment_paths, state, send_at, attempts,
            last_error, smtp_response, created_at, updated_at)
        VALUES (?, ?, '["dest1@example.com"]', '[]', '[]', ?, ?, ?, NULL, NULL,
            '[]', 'draft', NULL, 0, NULL, NULL, ?, ?)
        """,
        (
            account1_id,
            f"<draft1-{now}@example.com>",
            "Rascunho 1",
            "Texto do rascunho 1",
            None,
            now,
            now,
        ),
    )
    cur.execute(
        """
        INSERT INTO outbox (account_id, message_id, to_addrs, cc_addrs,
            bcc_addrs, subject, body_text, body_html, in_reply_to,
            references_hdr, attachment_paths, state, send_at, attempts,
            last_error, smtp_response, created_at, updated_at)
        VALUES (?, ?, '["dest2@example.com"]', '["cc@example.com"]', '[]',
            ?, ?, ?, NULL, NULL, '[]', 'queued', ?, 0, NULL, NULL, ?, ?)
        """,
        (
            account2_id,
            f"<draft2-{now}@example.com>",
            "Rascunho 2",
            "Texto do rascunho 2",
            None,
            now + 10,
            now,
            now,
        ),
    )


def main() -> None:
    """Generate the golden database."""
    if TEMP_DB.exists():
        TEMP_DB.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(TEMP_DB) + suffix)
        if p.exists():
            p.unlink()

    storage = Storage(TEMP_DB)
    storage.migrate()

    now = int(time.time())
    conn = storage._conn()
    _populate(conn, now)
    conn.commit()
    storage.close_thread_connection()

    # Checkpoint WAL so all data lives in the main file (06 §4.7).
    conn = sqlite3.connect(str(TEMP_DB))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    # Remove WAL/SHM — empty after TRUNCATE, but be explicit.
    for suffix in ("-wal", "-shm"):
        p = Path(str(TEMP_DB) + suffix)
        if p.exists():
            p.unlink()

    # Replace the golden DB.
    if FIXTURE_PATH.exists():
        FIXTURE_PATH.unlink()
    shutil.copy2(str(TEMP_DB), str(FIXTURE_PATH))
    TEMP_DB.unlink()

    # ── Verification ──
    conn = sqlite3.connect(str(FIXTURE_PATH))
    try:
        counts: dict[str, int] = {}
        for table in ("accounts", "folders", "messages", "bodies", "outbox"):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    finally:
        conn.close()

    print(f"Golden DB written to {FIXTURE_PATH}")
    print(f"  Schema version: {version}")
    print(f"  Accounts:      {counts['accounts']}")
    print(f"  Folders:       {counts['folders']}")
    print(f"  Messages:      {counts['messages']}")
    print(f"  Bodies:        {counts['bodies']}")
    print(f"  FTS entries:   {fts_count}")
    print(f"  Outbox drafts: {counts['outbox']}")


if __name__ == "__main__":
    main()
