"""Session auth (WEBAPP_DESIGN §16.3) — DB-backed tokens in an httpOnly cookie.

Login mints a random token in `sessions`; the cookie carries it; `current_user` resolves it on
every request. Remember-me → 30-day expiry, else 12 hours. Logout / password-change delete rows.
"""

from __future__ import annotations

import datetime
import secrets
import sqlite3

from fastapi import Cookie, Depends, HTTPException

from bidplus import merge
from bidplus.web import schema

COOKIE_NAME = "bidplus_session"
REMEMBER_DAYS = 30
SESSION_HOURS = 12


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def get_db():
    """Per-request parent.db connection (FastAPI dependency). Ensures all schema exists."""
    parent = merge.connect_parent()
    merge.ensure_shared(parent)
    schema.ensure_web_schema(parent)
    try:
        yield parent
    finally:
        parent.close()


def create_session(parent: sqlite3.Connection, user_id: int, remember: bool) -> tuple[str, datetime.datetime]:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + datetime.timedelta(days=REMEMBER_DAYS if remember else 0,
                                       hours=0 if remember else SESSION_HOURS)
    parent.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")))
    parent.commit()
    return token, expires


def delete_session(parent: sqlite3.Connection, token: str | None) -> None:
    if token:
        parent.execute("DELETE FROM sessions WHERE token=?", (token,))
        parent.commit()


def current_user(parent: sqlite3.Connection = Depends(get_db),
                 bidplus_session: str | None = Cookie(default=None)) -> dict:
    """Resolve the cookie to a user, or 401. Expired sessions are pruned and rejected."""
    if not bidplus_session:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated",
                                                     "message": "Not signed in."})
    row = parent.execute(
        "SELECT s.token, s.expires_at, u.id, u.username FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token=?", (bidplus_session,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated",
                                                     "message": "Session not found."})
    expires = datetime.datetime.fromisoformat(row["expires_at"])
    if expires < _now():
        delete_session(parent, bidplus_session)
        raise HTTPException(status_code=401, detail={"code": "unauthenticated",
                                                     "message": "Session expired."})
    return {"id": row["id"], "email": row["username"], "token": bidplus_session}
