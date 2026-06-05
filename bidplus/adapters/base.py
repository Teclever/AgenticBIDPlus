"""The ``PortalAdapter`` protocol + its small data carriers (stubs, no impls).

The orchestrator touches portals ONLY through this protocol. Adapters wrap each
tool's existing scrape -> Pass 1 -> own-bids.db pipeline and per-portal document
acquisition; they never re-implement portal transport (fetcher.py / HAL session.py /
GeM csrf_handler.py). Implementations arrive in S1 (HAL) and S2 (ISRO + GeM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class FetchedDoc:
    """A single downloaded document descriptor. The adapter returns these for raw
    files it acquired; it does NOT extract text or decide what goes to Sonnet (the
    §8b summarization module owns that)."""

    doc_name: str
    local_path: str
    fmt: str


@dataclass
class RunResult:
    """Outcome of one portal's pipeline run, surfaced to scrape_runs (S4)."""

    portal: str
    status: str = "success"  # running | success | partial | failed
    new_count: int = 0
    updated_count: int = 0
    closed_count: int = 0
    scored_count: int = 0
    error_summary: str | None = None
    stage_timings: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class PortalAdapter(Protocol):
    """One adapter per portal: 'gem' | 'hal' | 'isro'."""

    portal: str

    def run_pipeline(self) -> RunResult:
        """Wrap the tool's existing scrape -> Pass 1 -> own-bids.db flow. Returns
        counts + status for scrape_runs. Reuses the sample code; does not
        re-implement portal transport."""
        ...

    def tool_db_path(self) -> str:
        """Path to this tool's own bids.db (merge source), resolved under
        $BIDPLUS_RUNTIME_DIR/<portal>/ — never inside the synced source tree."""
        ...

    def fetch_documents(self, source_pk: str) -> list[FetchedDoc]:
        """Per-portal acquisition into the bid's per-bid dir
        $BIDPLUS_RUNTIME_DIR/<portal>/bids/<sanitised source_pk>/. HAL/ISRO enumerate
        all docs from the tender document-view; GeM downloads the one primary PDF,
        parses it for supporting-doc links, then fetches those. Downloads raw bytes
        only — text extraction and the text-vs-scan split belong to the §8b module."""
        ...

    def explain(self, source_pk: str) -> dict:
        """Dry-run view: input fields -> assembled prompt -> parsed Pass-1 result.
        Powers manual validation."""
        ...
