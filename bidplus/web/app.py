"""FastAPI app — the read/act layer over parent.db (WEBAPP_DESIGN §16, contract in API.md).

Reuses bidplus modules directly: summarize (the one path to Sonnet, behind locks.summarize_lock),
governance (promote/accept), dispositions (accept/reject + activity), lifecycle (date parsing),
merge (connection). Serves the built React UI (UIReference/.../dist) as static if present.

Run:  uvicorn bidplus.web.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from urllib.parse import unquote

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bidplus.config as config
from bidplus import dispositions, governance, locks, runs
from bidplus.web import mapping, passwords
from bidplus.web.auth import COOKIE_NAME, create_session, current_user, delete_session, get_db

app = FastAPI(title="Teclever Bid Intelligence API", version="1.0")

PORTALS = mapping.PORTALS
CLOSING_WINDOW_DAYS = 7

_STATUS_CODE = {400: "bad_request", 401: "unauthenticated", 403: "forbidden",
                404: "not_found", 409: "conflict", 422: "unprocessable"}


@app.exception_handler(HTTPException)
async def _http_exc(request, exc: HTTPException):
    d = exc.detail
    err = d if isinstance(d, dict) and "code" in d else {
        "code": _STATUS_CODE.get(exc.status_code, "error"), "message": str(d)}
    return JSONResponse(status_code=exc.status_code, content={"error": err})


# ── helpers ────────────────────────────────────────────────────────────────────────

def _check_portal(portal: str) -> str:
    if portal not in PORTALS:
        raise HTTPException(404, {"code": "not_found", "message": f"unknown portal {portal!r}"})
    return portal


def _row_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _fetch_bid(db: sqlite3.Connection, portal: str, key: str) -> dict:
    pk = mapping.pk_cols(portal)
    vals = key.split("|") if len(pk) > 1 else [key]
    where = " AND ".join(f"{c}=?" for c in pk)
    row = db.execute(f"SELECT * FROM {portal}_bids WHERE {where}", vals).fetchone()
    if row is None:
        raise HTTPException(404, {"code": "not_found", "message": f"no bid {key!r}"})
    return _row_dict(row)


def _window_date() -> datetime.date:
    return datetime.date.today() + datetime.timedelta(days=CLOSING_WINDOW_DAYS)


def _activity_bid_id(portal: str, bid_key: str) -> str:
    if portal == "hal" and "|" in bid_key:
        a, b = bid_key.split("|", 1)
        return f"{a} (line {b})"
    return bid_key


# ── request bodies ───────────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    email: str
    password: str
    rememberMe: bool = False


class DispositionBody(BaseModel):
    action: str


class DisputeBody(BaseModel):
    reason: str = ""


# ── auth ──────────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, db: sqlite3.Connection = Depends(get_db)):
    email = body.email.strip().lower()
    if not passwords.is_teclever_email(email):
        raise HTTPException(422, {"code": "non_teclever_email",
                                  "message": "Use your Teclever email."})
    row = db.execute("SELECT id, username, password_hash FROM users WHERE username=?",
                     (email,)).fetchone()
    if row is None or not passwords.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, {"code": "invalid_credentials",
                                  "message": "Sign in failed. Check your Teclever email and password."})
    token, expires = create_session(db, row["id"], body.rememberMe)
    max_age = int((expires - datetime.datetime.now()).total_seconds())
    response.set_cookie(COOKIE_NAME, token, max_age=max_age, httponly=True,
                        samesite="lax", path="/")
    return {"user": {"id": row["id"], "email": row["username"]}}


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response, user: dict = Depends(current_user),
           db: sqlite3.Connection = Depends(get_db)):
    delete_session(db, user["token"])
    response.delete_cookie(COOKIE_NAME, path="/")
    return Response(status_code=204)


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"id": user["id"], "email": user["email"]}


# ── dashboard stats ──────────────────────────────────────────────────────────────────

@app.get("/api/portals/{portal}/stats")
def stats(portal: str, user: dict = Depends(current_user),
          db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    table = f"{portal}_bids"
    closing_col = mapping.PORTAL_FIELDS[portal]["closing"]

    def c(where: str) -> int:
        return int(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])

    counts = {
        "total": c("1=1"),
        "new": c("user_state='new'"),
        "score3plus": c("pass1_score >= 3"),
        "score4plus": c("pass1_score >= 4"),
        "score5": c("pass1_score = 5"),
        "highPriority": c("pass1_score >= 4 AND user_state='new'"),
    }
    win = _window_date()
    today = datetime.date.today()
    cs = cb = 0
    for r in db.execute(
        f"SELECT pass1_score, {closing_col} AS cdate FROM {table} "
        "WHERE user_state='new' AND COALESCE(bid_status,'') <> 'CLOSED'"
    ):
        dt = mapping.lifecycle.parse_closing(r["cdate"])
        if dt and today <= dt.date() <= win:   # upcoming only — past-closing is effectively closed
            cs += 1
            if r["pass1_score"] in (4, 5):
                cb += 1
    counts["closingSoon"] = cs
    counts["bidsClosingBy"] = cb
    return {"portal": portal, "windowDate": win.isoformat(), "counts": counts}


# ── bid listing ──────────────────────────────────────────────────────────────────────

_FILTER_WHERE = {
    "all": None,
    "new": "user_state='new'",
    "score3plus": "pass1_score >= 3",
    "score4plus": "pass1_score >= 4",
    "score5": "pass1_score = 5",
    "highpriority": "pass1_score >= 4 AND user_state='new'",
}


@app.get("/api/portals/{portal}/bids")
def list_bids(portal: str,
              page: int = Query(1, ge=1), pageSize: int = Query(50, ge=1, le=200),
              search: str | None = None, filter: str = "all", status: str | None = None,
              user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    table = f"{portal}_bids"
    f = mapping.PORTAL_FIELDS[portal]
    order = "ORDER BY pass1_score IS NULL, pass1_score DESC"

    # closing-soon depends on per-portal date parsing → Python pipeline (bounded by 'new').
    if filter == "closingsoon":
        win = _window_date()
        today = datetime.date.today()
        rows = [r for r in db.execute(
            f"SELECT * FROM {table} WHERE user_state='new' "
            "AND COALESCE(bid_status,'') <> 'CLOSED' " + order)]
        keep = []
        for r in rows:
            dt = mapping.lifecycle.parse_closing(r[f["closing"]])
            if dt and today <= dt.date() <= win:
                keep.append(r)
        total = len(keep)
        start = (page - 1) * pageSize
        items = [mapping.list_item(_row_dict(r), portal) for r in keep[start:start + pageSize]]
        return {"items": items, "page": page, "pageSize": pageSize, "total": total}

    where = ["1=1"]
    params: list = []
    fw = _FILTER_WHERE.get(filter)
    if fw:
        where.append(fw)
    if status:
        where.append("user_state=?"); params.append(status)
    if search:
        cols = [c for c in (f["title"], f["buyer"], *f["pk"]) if c]
        where.append("(" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")")
        params += [f"%{search}%"] * len(cols)
    where_sql = " AND ".join(where)

    total = int(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}", params).fetchone()[0])
    rows = db.execute(
        f"SELECT * FROM {table} WHERE {where_sql} {order} LIMIT ? OFFSET ?",
        [*params, pageSize, (page - 1) * pageSize]).fetchall()
    items = [mapping.list_item(_row_dict(r), portal) for r in rows]
    return {"items": items, "page": page, "pageSize": pageSize, "total": total}


# ── bid detail + actions ─────────────────────────────────────────────────────────────

@app.get("/api/portals/{portal}/bids/{bidKey:path}")
def bid_detail(portal: str, bidKey: str, user: dict = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    row = _fetch_bid(db, portal, unquote(bidKey))
    return mapping.detail(row, portal)


@app.post("/api/portals/{portal}/bids/{bidKey:path}/generate-summary")
def generate_summary(portal: str, bidKey: str, user: dict = Depends(current_user),
                     db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    key = unquote(bidKey)
    row = _fetch_bid(db, portal, key)
    if (row.get("bid_status") or "").upper() == "CLOSED":
        raise HTTPException(422, {"code": "bid_closed",
                                  "message": "This bid is closed — no AI action available."})
    from bidplus import summarize
    try:
        with locks.summarize_lock(blocking=False):
            summarize.summarize_bid(portal, key, db, fetch=True)
    except locks.LockBusy:
        raise HTTPException(409, {"code": "summarization_busy",
                                  "message": "Summarization is busy (nightly run in progress). "
                                             "Try again shortly."})
    except HTTPException:
        raise
    except Exception as e:  # missing API key, fetch failure, etc.
        raise HTTPException(500, {"code": "summarize_error", "message": str(e)})
    row = _fetch_bid(db, portal, key)
    return mapping.detail(row, portal)["summary"]


@app.post("/api/portals/{portal}/bids/{bidKey:path}/disposition")
def disposition(portal: str, bidKey: str, body: DispositionBody,
                user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    if body.action not in ("accepted", "rejected"):
        raise HTTPException(422, {"code": "bad_request",
                                  "message": "action must be 'accepted' or 'rejected'"})
    try:
        return dispositions.dispose(db, portal, unquote(bidKey), body.action, user["id"])
    except LookupError as e:
        raise HTTPException(404, {"code": "not_found", "message": str(e)})


# ── notifications (auto-filtered review) ──────────────────────────────────────────────

def _pending_rows(db: sqlite3.Connection, portal: str) -> list[sqlite3.Row]:
    return db.execute(
        f"SELECT * FROM {portal}_bids "
        "WHERE auto_rejected=1 AND human_disposition IS NULL "
        "ORDER BY first_seen_date DESC").fetchall()


@app.get("/api/notifications/auto-filtered")
def notifications(user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    items, total = [], 0
    for portal in PORTALS:
        rows = _pending_rows(db, portal)
        total += len(rows)
        for r in rows[:200]:
            items.append(mapping.notification_item(_row_dict(r), portal))
    return {"items": items[:200], "total": total}


@app.get("/api/notifications/auto-filtered/count")
def notifications_count(user: dict = Depends(current_user),
                        db: sqlite3.Connection = Depends(get_db)):
    vrow = db.execute("SELECT last_viewed_at FROM notification_views WHERE user_id=?",
                      (user["id"],)).fetchone()
    watermark = mapping.parse_ts(vrow["last_viewed_at"]) if vrow else None
    count = 0
    for portal in PORTALS:
        for r in _pending_rows(db, portal):
            if watermark is None:
                count += 1
                continue
            seen = mapping.parse_ts(r["first_seen_date"])
            if seen is None or seen > watermark:   # unparseable → treat as new (never hide)
                count += 1
    return {"count": count}


@app.post("/api/notifications/auto-filtered/viewed", status_code=204)
def notifications_viewed(user: dict = Depends(current_user),
                         db: sqlite3.Connection = Depends(get_db)):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO notification_views (user_id, last_viewed_at) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET last_viewed_at=excluded.last_viewed_at",
        (user["id"], now))
    db.commit()
    return Response(status_code=204)


@app.post("/api/notifications/auto-filtered/save-all")
def notifications_save_all(user: dict = Depends(current_user),
                           db: sqlite3.Connection = Depends(get_db)):
    accepted = sum(governance.accept(db, portal, None)["accepted"] for portal in PORTALS)
    return {"accepted": accepted}


@app.post("/api/notifications/auto-filtered/{portal}/{bidKey:path}/dispute")
def notifications_dispute(portal: str, bidKey: str, body: DisputeBody,
                          user: dict = Depends(current_user),
                          db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    key = unquote(bidKey)
    try:
        governance.promote(db, portal, key, body.reason, user["id"])
    except RuntimeError as e:
        raise HTTPException(404, {"code": "not_found", "message": str(e)})
    dispositions.log_activity(db, user["id"], portal, key, "disputed", body.reason or None)
    return {"disputed": True}


# ── activity log ─────────────────────────────────────────────────────────────────────

@app.get("/api/activity")
def activity(page: int = Query(1, ge=1), pageSize: int = Query(50, ge=1, le=200),
             user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    total = int(db.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0])
    rows = db.execute(
        "SELECT a.id, u.username, a.portal, a.bid_key, a.action, a.detail, a.created_at "
        "FROM activity_log a JOIN users u ON u.id = a.user_id "
        "ORDER BY a.id DESC LIMIT ? OFFSET ?", (pageSize, (page - 1) * pageSize)).fetchall()
    items = [{
        "id": r["id"], "user": r["username"], "portal": r["portal"],
        "bidId": _activity_bid_id(r["portal"], r["bid_key"]),
        "action": r["action"], "detail": r["detail"], "createdAt": r["created_at"],
    } for r in rows]
    return {"items": items, "page": page, "pageSize": pageSize, "total": total}


# ── system alert banner ──────────────────────────────────────────────────────────────

@app.get("/api/system-alert")
def system_alert(user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    rows = runs.active_alerts(db)
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "reason": r["reason"], "raisedAt": r["raised_at"]}


@app.post("/api/system-alert/{alert_id}/clear", status_code=204)
def system_alert_clear(alert_id: int, user: dict = Depends(current_user),
                       db: sqlite3.Connection = Depends(get_db)):
    db.execute("UPDATE system_alerts SET cleared_at=?, cleared_by=? WHERE id=? AND cleared_at IS NULL",
               (datetime.datetime.now().isoformat(timespec="seconds"), user["id"], alert_id))
    db.commit()
    return Response(status_code=204)


# ── static UI (mounted last so it never shadows /api) ────────────────────────────────

_DIST = Path(__file__).resolve().parents[2] / "UIReference" / "Teclever Bid intelligence" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
