"""Portal adapters — the single seam between the orchestrator and the tool code.

S0 defines the protocol only. HAL (S1), ISRO + GeM (S2) implementations land later.
"""

from bidplus.adapters.base import FetchedDoc, PortalAdapter, RunResult

__all__ = ["FetchedDoc", "PortalAdapter", "RunResult"]
