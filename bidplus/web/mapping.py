"""Per-portal column → normalized API field mapping + row serializers (API.md §3/§4).

The three portal tables (`gem_bids`/`hal_bids`/`isro_bids`) have different column names; the
front-end consumes one normalized shape. This module owns that translation. Columns that don't
exist for a portal map to ``None`` and serialize as ``null``.
"""

from __future__ import annotations

import datetime
import json
import sqlite3

from bidplus import lifecycle

# Normalized field -> tool column (None = portal has no such field).
PORTAL_FIELDS = {
    "gem": {
        "pk": ("bid_number",),
        "title": "items", "buyer": "organization", "ministry": "ministry",
        "department": "department", "location": None, "value": None,
        "opening": "start_date", "closing": "end_date",
    },
    "hal": {
        "pk": ("tender_number", "line_number"),
        "title": "tender_description", "buyer": "buyer", "ministry": None,
        "department": None, "location": "tender_region", "value": "estimated_cost",
        "opening": "opening_date", "closing": "closing_date",
    },
    "isro": {
        "pk": ("tender_id",),
        "title": "tender_description", "buyer": "center_name", "ministry": None,
        "department": None, "location": None, "value": None,
        "opening": "bid_opening_date", "closing": "bid_closing_date",
    },
}

PORTALS = tuple(PORTAL_FIELDS.keys())


def pk_cols(portal: str) -> tuple[str, ...]:
    return PORTAL_FIELDS[portal]["pk"]


def bid_key(row: dict, portal: str) -> str:
    """Canonical '|'-joined PK — the form summarize/governance/dispositions expect."""
    return "|".join(str(row[c]) for c in pk_cols(portal))


def bid_id_display(row: dict, portal: str) -> str:
    """Human-facing id. HAL is composite (tender + line); others are the single PK."""
    if portal == "hal":
        return f"{row['tender_number']} (line {row['line_number']})"
    return str(row[pk_cols(portal)[0]])


def _val(row: dict, col: str | None):
    return row.get(col) if col else None


def _iso_closing(raw) -> str | None:
    dt = lifecycle.parse_closing(raw)
    return dt.isoformat() if dt else None


def list_item(row: dict, portal: str) -> dict:
    f = PORTAL_FIELDS[portal]
    closing_raw = _val(row, f["closing"])
    return {
        "portal": portal,
        "bidKey": bid_key(row, portal),
        "bidId": bid_id_display(row, portal),
        "title": _val(row, f["title"]),
        "buyer": _val(row, f["buyer"]),
        "rating": row.get("pass1_score"),
        "method": row.get("pass1_method") or "model",
        "eliminatedBy": row.get("pass1_eliminated_by"),
        "autoRejected": bool(row.get("auto_rejected")),
        "userState": row.get("user_state") or "new",
        "bidStatus": row.get("bid_status") or "OPEN",
        "hasRestrictiveEligibility": bool(row.get("has_restrictive_eligibility")),
        "summaryAvailable": bool(row.get("summary_json")),
        "closingDate": _iso_closing(closing_raw),
        "closingDateRaw": closing_raw,
    }


def _summary_block(row: dict) -> dict:
    """Build the detail `summary` object. Renders stored summary_json -> markdown."""
    raw = row.get("summary_json")
    if not raw:
        return {"available": False, "status": row.get("summary_status"),
                "markdown": None, "coverage": None, "unparsedDocuments": [],
                "model": row.get("summary_model"), "generatedAt": row.get("summary_generated_at")}
    from bidplus import summarize  # heavy import deferred to when a summary exists
    try:
        summary = summarize.BidSummary(**json.loads(raw))
        markdown = summarize.render_markdown(summary)
        unparsed = summary.unparsed_documents
        coverage = summary.coverage
        critical_flags = [f.model_dump() for f in summary.critical_flags]
    except Exception:
        markdown, unparsed, coverage, critical_flags = None, [], row.get("summary_coverage"), []
    return {
        "available": True,
        "status": row.get("summary_status") or "ok",
        "markdown": markdown,
        "coverage": coverage or row.get("summary_coverage"),
        "unparsedDocuments": unparsed,
        "criticalFlags": critical_flags,
        "model": row.get("summary_model"),
        "generatedAt": row.get("summary_generated_at"),
    }


def detail(row: dict, portal: str) -> dict:
    f = PORTAL_FIELDS[portal]
    closing_raw = _val(row, f["closing"])
    return {
        "portal": portal,
        "bidKey": bid_key(row, portal),
        "bidId": bid_id_display(row, portal),
        "rating": row.get("pass1_score"),
        "rationale": row.get("pass1_rationale"),
        "method": row.get("pass1_method") or "model",
        "eliminatedBy": row.get("pass1_eliminated_by"),
        "autoRejected": bool(row.get("auto_rejected")),
        "userState": row.get("user_state") or "new",
        "bidStatus": row.get("bid_status") or "OPEN",
        "hasRestrictiveEligibility": bool(row.get("has_restrictive_eligibility")),
        "overview": {
            "title": _val(row, f["title"]),
            "buyer": _val(row, f["buyer"]),
            "ministry": _val(row, f["ministry"]),
            "department": _val(row, f["department"]),
            "location": _val(row, f["location"]),
            "value": _val(row, f["value"]),
            "openingDateRaw": _val(row, f["opening"]),
            "closingDate": _iso_closing(closing_raw),
            "closingDateRaw": closing_raw,
        },
        "summary": _summary_block(row),
    }


def notification_item(row: dict, portal: str) -> dict:
    f = PORTAL_FIELDS[portal]
    return {
        "portal": portal,
        "bidKey": bid_key(row, portal),
        "bidId": bid_id_display(row, portal),
        "description": _val(row, f["title"]),
        "matchedKeyword": row.get("pass1_eliminated_by"),
        "closingDateRaw": _val(row, f["closing"]),
        "firstSeen": row.get("first_seen_date"),
    }


# ── timestamp parse for the per-user notification watermark (API.md §5) ────────────────

def parse_ts(value) -> datetime.datetime | None:
    """Best-effort parse of a first_seen_date / last_viewed_at string. ISO first, then the
    day-first portal formats. Unparseable -> None (caller treats as 'new', never hides)."""
    if not value:
        return None
    return lifecycle.parse_closing(value)
