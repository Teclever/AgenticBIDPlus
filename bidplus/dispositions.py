"""Human bid dispositions + the append-only activity log (WEBAPP_DESIGN §16.5/§16.6).

Accept / Reject on a model-scored bid writes the overlay (`user_state` + `disposed_by` +
`disposed_at`) AND an `activity_log` row in ONE transaction, so the audit feed can never drift
from the current state. The notification "dispute" path (governance.promote) logs through
`log_activity` here too. Re-disposition is allowed — each writes a new append-only row; the
bid's `user_state` reflects the latest.
"""

from __future__ import annotations

import datetime
import sqlite3

_ADAPTER_PK = {"hal": ("tender_number", "line_number"), "isro": ("tender_id",), "gem": ("bid_number",)}
_VALID_ACTIONS = {"accepted", "rejected", "disputed", "reset", "promoted"}


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _split(portal: str, bid_key: str) -> list[str]:
    pk = _ADAPTER_PK[portal]
    return bid_key.split("|") if len(pk) > 1 else [bid_key]


def log_activity(parent: sqlite3.Connection, user_id: int, portal: str, bid_key: str,
                 action: str, detail: str | None = None) -> int:
    """Append one row to the audit feed. ``action`` ∈ accepted|rejected|disputed."""
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid activity action: {action!r}")
    cur = parent.execute(
        "INSERT INTO activity_log (user_id, portal, bid_key, action, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, portal, bid_key, action, detail, _now()))
    parent.commit()
    return int(cur.lastrowid)


def dispose(parent: sqlite3.Connection, portal: str, bid_key: str, action: str,
            user_id: int) -> dict:
    """Accept / reject a bid: set overlay + append the activity row atomically.

    Returns ``{"userState": <action>}``. Raises ``LookupError`` if the bid does not exist.
    """
    if action not in ("accepted", "rejected"):
        raise ValueError(f"disposition must be accepted|rejected, got {action!r}")
    pk = _ADAPTER_PK[portal]
    vals = _split(portal, bid_key)
    where = " AND ".join(f"{c}=?" for c in pk)
    table = f"{portal}_bids"
    now = _now()
    cur = parent.execute(
        f"UPDATE {table} SET user_state=?, disposed_by=?, disposed_at=? WHERE {where}",
        (action, user_id, now, *vals))
    if cur.rowcount == 0:
        parent.rollback()
        raise LookupError(f"{portal}: no bid {bid_key!r}")
    parent.execute(
        "INSERT INTO activity_log (user_id, portal, bid_key, action, detail, created_at) "
        "VALUES (?, ?, ?, ?, NULL, ?)",
        (user_id, portal, bid_key, action, now))
    parent.commit()
    return {"userState": action}


def reset_disposition(parent: sqlite3.Connection, portal: str, bid_key: str,
                      user_id: int) -> dict:
    """Reset a rejected/accepted bid back to 'new', clearing the disposition overlay."""
    pk = _ADAPTER_PK[portal]
    vals = _split(portal, bid_key)
    where = " AND ".join(f"{c}=?" for c in pk)
    table = f"{portal}_bids"
    now = _now()
    cur = parent.execute(
        f"UPDATE {table} SET user_state='new', disposed_by=NULL, disposed_at=NULL WHERE {where}",
        (*vals,))
    if cur.rowcount == 0:
        parent.rollback()
        raise LookupError(f"{portal}: no bid {bid_key!r}")
    parent.execute(
        "INSERT INTO activity_log (user_id, portal, bid_key, action, detail, created_at) "
        "VALUES (?, ?, ?, 'reset', NULL, ?)",
        (user_id, portal, bid_key, now))
    parent.commit()
    return {"userState": "new"}
