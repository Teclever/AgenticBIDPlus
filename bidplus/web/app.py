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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bidplus.config as config
from bidplus import dispositions, governance, locks, runs
from bidplus.web import mapping, passwords
from bidplus.web.auth import COOKIE_NAME, create_session, current_user, delete_session, get_db

app = FastAPI(title="Teclever Bid Intelligence API", version="1.0")

# Vite dev server (5173) may call this API cross-origin during local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PORTALS = mapping.PORTALS
CLOSING_WINDOW_DAYS = 10

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
        "scoreBelow4": c("pass1_score >= 1 AND pass1_score <= 3"),
        "scoreExact4": c("pass1_score = 4"),
        "scoreExact5": c("pass1_score = 5"),
        # closingSoon / closingSoonActionable / highPriority added below (need date parsing)
    }
    win = _window_date()
    today = datetime.date.today()
    cs1 = cs2 = cs3 = 0
    for r in db.execute(
        f"SELECT pass1_score, user_state, {closing_col} AS cdate FROM {table} "
        "WHERE COALESCE(bid_status,'') <> 'CLOSED'"
    ):
        dt = mapping.lifecycle.parse_closing(r["cdate"])
        if not (dt and today <= dt.date() <= win):
            continue
        score = r["pass1_score"]
        state = r["user_state"] or "new"
        # Category 1: score 3–5, not rejected
        if score is not None and score >= 3 and state != "rejected":
            cs1 += 1
        # Category 2: score 5 or accepted
        if score == 5 or state == "accepted":
            cs2 += 1
        # Category 3: accepted
        if state == "accepted":
            cs3 += 1
    counts["closingSoon"] = cs1
    counts["closingSoonActionable"] = cs2
    counts["highPriority"] = cs3
    return {"portal": portal, "windowDate": win.isoformat(), "counts": counts}


# ── bid listing ──────────────────────────────────────────────────────────────────────

_FILTER_WHERE = {
    "all": None,
    "new": "user_state='new'",
    "filtered": "pass1_score = 0",
    "score1to3": "pass1_score >= 1 AND pass1_score <= 3",
    "score4": "pass1_score = 4",
    "score5": "pass1_score = 5",
    # closingsoon / closingactionable / highpriority are date-based → handled in list_bids
}


@app.get("/api/portals/{portal}/bids")
def list_bids(portal: str,
              page: int = Query(1, ge=1), pageSize: int = Query(50, ge=1, le=200),
              search: str | None = None, filter: str = "all", status: str | None = None,
              user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    _check_portal(portal)
    table = f"{portal}_bids"
    f = mapping.PORTAL_FIELDS[portal]
    order = "ORDER BY first_seen_date DESC, pass1_score IS NULL, pass1_score DESC"

    # Date-based filters require per-portal closing-date parsing — handled here, return early.
    if filter in ("closingsoon", "closingactionable", "highpriority"):
        win = _window_date()
        today = datetime.date.today()
        rows = db.execute(
            f"SELECT * FROM {table} WHERE COALESCE(bid_status,'') <> 'CLOSED' " + order
        ).fetchall()
        keep = []
        for r in rows:
            dt = mapping.lifecycle.parse_closing(r[f["closing"]])
            if not (dt and today <= dt.date() <= win):
                continue
            score = r["pass1_score"]
            state = r["user_state"] or "new"
            if filter == "closingsoon":
                # Category 1: score 3–5, not rejected
                if score is not None and score >= 3 and state != "rejected":
                    keep.append(r)
            elif filter == "closingactionable":
                # Category 2: score 5 or accepted
                if score == 5 or state == "accepted":
                    keep.append(r)
            else:  # highpriority
                # Category 3: accepted
                if state == "accepted":
                    keep.append(r)
        if search:
            s = search.lower()
            cols_search = [c for c in (f["title"], f["buyer"], *f["pk"]) if c]
            keep = [r for r in keep if any(s in str(r[c] or "").lower() for c in cols_search)]
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


# ── active generation job (server-side, visible to all users / browsers) ─────────────
# One slot — the summarize lock already enforces single concurrency.
# startedAt is stored so a TTL check can auto-clear a stale slot (browser closed mid-run).

_active_job: dict | None = None
_ACTIVE_JOB_TTL = 300  # seconds — auto-clear if still set after this long


def _set_active_job(portal: str, key: str) -> None:
    global _active_job
    _active_job = {
        "portal": portal,
        "bidKey": key,
        "bidId": _activity_bid_id(portal, key),
        "startedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _clear_active_job() -> None:
    global _active_job
    _active_job = None


@app.get("/api/generating")
def get_generating(user: dict = Depends(current_user)):
    """Return the currently-active generation job, or {active: null}.
    Auto-clears a stale slot so a closed browser never leaves the banner stuck."""
    global _active_job
    if _active_job:
        started = datetime.datetime.fromisoformat(_active_job["startedAt"])
        if (datetime.datetime.now() - started).total_seconds() > _ACTIVE_JOB_TTL:
            _active_job = None
    return {"active": _active_job}


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
            _set_active_job(portal, key)
            try:
                summarize.summarize_bid(portal, key, db, fetch=True)
            finally:
                _clear_active_job()
    except locks.LockBusy:
        raise HTTPException(409, {"code": "summarization_busy",
                                  "message": "AI summarization is already in progress. "
                                             "Try again in a moment."})
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
    key = unquote(bidKey)
    if body.action not in ("accepted", "rejected", "reset"):
        raise HTTPException(422, {"code": "bad_request",
                                  "message": "action must be 'accepted', 'rejected', or 'reset'"})
    try:
        if body.action == "reset":
            return dispositions.reset_disposition(db, portal, key, user["id"])
        return dispositions.dispose(db, portal, key, body.action, user["id"])
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
        "bidKey": r["bid_key"],
        "action": r["action"], "detail": r["detail"], "createdAt": r["created_at"],
    } for r in rows]
    return {"items": items, "page": page, "pageSize": pageSize, "total": total}


# ── system alerts ────────────────────────────────────────────────────────────────────

class RetryAlertsBody(BaseModel):
    alertType: str
    portal: str | None = None


def _serialize_alert(r) -> dict:
    import json as _json
    return {
        "id": r["id"],
        "alertType": r["alert_type"] or "CYCLE_FAILED",
        "portal": r["portal"],
        "bidRefs": _json.loads(r["bid_refs"] or "[]"),
        "reason": r["reason"],
        "status": r["status"] or "active",
        "retryCount": r["retry_count"] or 0,
        "raisedAt": r["raised_at"],
        "clearedAt": r["cleared_at"],
        "lastRetryAt": r["last_retry_at"],
        "lastRetryError": r["last_retry_error"],
    }


@app.get("/api/system-alerts")
def system_alerts(includeCleared: bool = Query(False),
                  user: dict = Depends(current_user),
                  db: sqlite3.Connection = Depends(get_db)):
    rows = runs.list_alerts(db, include_cleared=includeCleared)
    return {"items": [_serialize_alert(r) for r in rows]}


@app.post("/api/system-alerts/retry")
def retry_alerts(body: RetryAlertsBody, user: dict = Depends(current_user),
                 db: sqlite3.Connection = Depends(get_db)):
    """Retry all active/retry_failed alerts of the same alertType+portal group.

    On success → cleared. On failure → retry_failed with error. All actions logged.
    """
    import json as _json
    from bidplus import merge as merge_mod, scoring, summarize as summarize_mod

    rows = db.execute(
        "SELECT * FROM system_alerts WHERE alert_type=? AND status IN ('active','retry_failed')"
        + (" AND portal=?" if body.portal else ""),
        ([body.alertType, body.portal] if body.portal else [body.alertType]),
    ).fetchall()
    if not rows:
        raise HTTPException(404, {"code": "not_found",
                                  "message": "No active alerts found for that type/portal."})

    alert_ids = [r["id"] for r in rows]
    portal = body.portal or (rows[0]["portal"] if rows[0]["portal"] else None)

    try:
        if body.alertType in ("SCORING_FAILURE", "CREDIT_EXHAUSTED", "INVALID_API_KEY"):
            if not portal:
                raise ValueError("portal required for scoring retry")
            info = scoring.score_portal(portal, db, mode="hard")
            if info.get("unscored_left", 0) > 0:
                raise RuntimeError(
                    f"{info['unscored_left']} bid(s) still unscored after retry"
                )
            merge_mod.merge_portal(portal, parent=db)
        elif body.alertType == "SUMMARY_FAILURE":
            if not portal:
                raise ValueError("portal required for summary retry")
            bid_refs: list[str] = []
            for r in rows:
                bid_refs += _json.loads(r["bid_refs"] or "[]")
            bid_refs = list(dict.fromkeys(bid_refs))  # deduplicate, preserve order
            failed: list[str] = []
            from bidplus import locks
            with locks.summarize_lock(blocking=False):
                for pk in bid_refs:
                    try:
                        res = summarize_mod.summarize_bid(portal, pk, db, fetch=True)
                        if res.get("status") == "failed":
                            failed.append(pk)
                    except Exception as e:
                        failed.append(pk)
                        print(f"[retry] {portal} {pk}: {e}")
            if failed:
                raise RuntimeError(f"{len(failed)} bid(s) still failed: {', '.join(failed[:5])}")
        elif body.alertType == "CYCLE_FAILED":
            # Best-effort: score + merge whatever remains for this portal.
            if portal:
                scoring.score_portal(portal, db, mode="hard")
                merge_mod.merge_portal(portal, parent=db)
        # success — mark all cleared + log activity
        runs.clear_alert_group(db, alert_ids, user["id"])
        dispositions.log_activity(
            db, user["id"], portal or "system", "alerts",
            "accepted",  # closest action code available
            f"Retried+cleared {len(alert_ids)} {body.alertType} alert(s)"
        )
        return {"cleared": len(alert_ids), "portal": portal}
    except locks.LockBusy:
        raise HTTPException(409, {"code": "summarization_busy",
                                  "message": "Summarization is busy (nightly run in progress)."})
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:400]}"
        runs.fail_alert_group(db, alert_ids, user["id"], error)
        dispositions.log_activity(
            db, user["id"], portal or "system", "alerts",
            "rejected",
            f"Retry FAILED for {len(alert_ids)} {body.alertType} alert(s): {error}"
        )
        raise HTTPException(500, {"code": "retry_failed", "message": error})


# ── SPA static serving (must come last so it never shadows /api) ─────────────────────
#
# StaticFiles with html=True returns 404 for React Router client-side paths like /login
# because dist/login doesn't exist as a file. Fix: mount /assets separately for asset
# bundles, then a catch-all route that serves real dist/ files when they exist and falls
# back to index.html for everything else so React Router handles routing client-side.

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_ASSETS = _DIST / "assets"
if _ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """Serve real dist/ files when they exist; fall back to index.html for SPA routes."""
    if _DIST.is_dir():
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        index = _DIST / "index.html"
        if index.is_file():
            return FileResponse(str(index))
    raise HTTPException(404)
