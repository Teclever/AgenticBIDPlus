"""The ``PortalAdapter`` protocol + its small data carriers (stubs, no impls).

The orchestrator touches portals ONLY through this protocol. Adapters wrap each
tool's existing scrape -> Pass 1 -> own-bids.db pipeline and per-portal document
acquisition; they never re-implement portal transport (fetcher.py / HAL session.py /
GeM csrf_handler.py). Implementations arrive in S1 (HAL) and S2 (ISRO + GeM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class FetchedDoc:
    """A single downloaded document descriptor. The adapter returns these for raw
    files it acquired; it does NOT extract text or decide what goes to Sonnet (the
    §8b summarization module owns that)."""

    doc_name: str
    local_path: str
    fmt: str


def fetched_docs_in(out_dir: str | Path) -> list["FetchedDoc"]:
    """Enumerate the raw files a tool's ``fetch-docs`` subcommand wrote into a per-bid
    staging dir into ``FetchedDoc`` descriptors (the adapter does not parse stdout).
    Skips dotfiles and Channel-2 ``.txt`` extractions (which the §8b module writes later)."""
    out = Path(out_dir)
    if not out.is_dir():
        return []
    docs: list[FetchedDoc] = []
    for p in sorted(out.iterdir()):
        if not p.is_file() or p.name.startswith(".") or p.suffix.lower() == ".txt":
            continue
        docs.append(FetchedDoc(doc_name=p.name, local_path=str(p),
                               fmt=p.suffix.lower().lstrip(".") or "bin"))
    return docs


@dataclass
class RunResult:
    """Outcome of one portal's pipeline run, surfaced to scrape_runs (S4)."""

    portal: str
    status: str = "success"  # running | success | partial | failed
    new_count: int = 0
    updated_count: int = 0
    closed_count: int = 0
    scored_count: int = 0
    keyword_scored_count: int = 0
    model_scored_count: int = 0
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
