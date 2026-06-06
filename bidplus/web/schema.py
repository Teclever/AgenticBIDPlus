"""Web-round parent.db tables (WEBAPP_DESIGN §16.2) — additive, idempotent.

These three tables are owned by the web layer; the read model (`{portal}_bids`, `users`,
`scrape_runs`, `system_alerts`) is created by `bidplus.merge.ensure_shared`. Kept import-light
(sqlite only) so both the FastAPI app and the `bidplus.users` CLI can call it without dragging
FastAPI in.
"""

from __future__ import annotations

import sqlite3


def ensure_web_schema(parent: sqlite3.Connection) -> None:
    """Create sessions / activity_log / notification_views if absent. Safe to call every run."""
    parent.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        " token TEXT PRIMARY KEY,"
        " user_id INTEGER NOT NULL REFERENCES users(id),"
        " created_at TEXT NOT NULL,"
        " expires_at TEXT NOT NULL)"
    )
    parent.execute(
        "CREATE TABLE IF NOT EXISTS activity_log ("        # append-only; never UPDATEd
        " id INTEGER PRIMARY KEY,"
        " user_id INTEGER NOT NULL REFERENCES users(id),"
        " portal TEXT NOT NULL,"                            # gem | hal | isro
        " bid_key TEXT NOT NULL,"                           # canonical '|'-joined PK (§16.4)
        " action TEXT NOT NULL,"                            # accepted | rejected | disputed
        " detail TEXT,"                                     # dispute reason (else NULL)
        " created_at TEXT NOT NULL)"
    )
    parent.execute(
        "CREATE TABLE IF NOT EXISTS notification_views ("
        " user_id INTEGER PRIMARY KEY REFERENCES users(id),"
        " last_viewed_at TEXT NOT NULL)"
    )
    parent.commit()
