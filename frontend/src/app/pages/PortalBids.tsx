import { useState, useEffect, useRef } from "react";
import { useParams, Link, useSearchParams, useNavigate } from "react-router";
import { Search, Filter, Calendar, ChevronRight, X, Loader2, Sparkles, CheckCircle, XCircle, Star } from "lucide-react";
import { Button } from "../components/ui/button";
import { portalApi } from "../lib/api";
import {
  bidDetailPath,
  FILTER_LABELS,
  formatClosingDate,
} from "../lib/format";
import type { BidFilter, BidListItem, PortalId } from "../lib/types";
import { RatingDisplay } from "../components/RatingDisplay";
import { Pagination } from "../components/Pagination";
import { ApiRequestError, isAuthError } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const PAGE_SIZE = 50;

const PORTAL_NAMES: Record<PortalId, string> = {
  gem: "GEM - Government e-Marketplace",
  hal: "HAL - e-Procurement",
  halc: "HAL - Corporate Tenders",
  isro: "ISRO - Indian Space Research Organisation",
};

const VALID_FILTERS = new Set<string>([
  "all", "new", "filtered", "score1to3", "score4", "score5", "highpriority", "closingsoon", "closingactionable", "singletender",
]);

function isSelectable(bid: BidListItem): boolean {
  return bid.userState === "new" && bid.method === "model";
}

export function PortalBids() {
  const { user, loading: authLoading } = useAuth();
  const { portalId } = useParams<{ portalId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const portal = portalId as PortalId;

  // The URL is the single source of truth for every list parameter, so both
  // back buttons (browser + in-app) restore the exact view.
  const urlFilter = searchParams.get("filter") ?? "all";
  const activeFilter: BidFilter = VALID_FILTERS.has(urlFilter)
    ? (urlFilter as BidFilter)
    : "all";
  const statusFilter = searchParams.get("status") ?? "all";
  const searchTerms = searchParams.getAll("search");
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const paramsKey = searchParams.toString();

  const [searchInput, setSearchInput] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [bids, setBids] = useState<BidListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [disposingKey, setDisposingKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const updateParams = (mutate: (p: URLSearchParams) => void, resetPage = true) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    if (resetPage) next.delete("page");
    setSearchParams(next);
  };

  // Effective search = committed chips + the in-progress input (live narrowing)
  const effectiveSearch = [...searchTerms];
  if (searchInput.trim()) effectiveSearch.push(searchInput.trim());

  useEffect(() => {
    if (!portal || authLoading || !user) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const doFetch = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await portalApi.bids(portal, {
          filter: activeFilter,
          search: effectiveSearch.length ? effectiveSearch : undefined,
          status: statusFilter !== "all" ? statusFilter : undefined,
          page,
          pageSize: PAGE_SIZE,
        });
        setBids(data.items);
        setTotal(data.total);
        setSelected(new Set());
      } catch (e) {
        if (e instanceof ApiRequestError && isAuthError(e.status, e.code)) return;
        setBids([]);
        setTotal(0);
        setError("Unable to load bids. Try refreshing the page.");
      } finally {
        setLoading(false);
      }
    };
    debounceRef.current = setTimeout(doFetch, searchInput ? 300 : 0);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [portal, paramsKey, searchInput, user, authLoading, reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const commitSearchChip = () => {
    const term = searchInput.trim();
    if (!term) return;
    updateParams((p) => p.append("search", term));
    setSearchInput("");
  };

  const removeSearchChip = (term: string) => {
    updateParams((p) => {
      const rest = p.getAll("search").filter((t) => t !== term);
      p.delete("search");
      for (const t of rest) p.append("search", t);
    });
  };

  const setStatus = (status: string) => {
    updateParams((p) => {
      if (status === "all") p.delete("status");
      else p.set("status", status);
    });
  };

  const clearUrlFilter = () => updateParams((p) => p.delete("filter"));

  const setQuickFilter = (filter: BidFilter) => {
    updateParams((p) => {
      if (filter === "all") p.delete("filter");
      else p.set("filter", filter);
    });
  };

  const clearAll = () => {
    setSearchInput("");
    updateParams((p) => {
      p.delete("search");
      p.delete("status");
    });
  };

  const setPage = (n: number) => {
    updateParams((p) => {
      if (n <= 1) p.delete("page");
      else p.set("page", String(n));
    }, false);
  };

  // Return context for BidDetail: the full list query + the bid's index on this page.
  const detailLink = (bidKey: string, idx: number) =>
    `${bidDetailPath(portal, bidKey)}?ret=${encodeURIComponent(paramsKey)}&ridx=${idx}`;

  const handleDisposition = async (
    bidKey: string,
    action: "accepted" | "rejected",
    e: React.MouseEvent,
  ) => {
    e.stopPropagation();
    e.preventDefault();
    setDisposingKey(bidKey);
    try {
      const { userState } = await portalApi.disposition(portal, bidKey, action);
      setBids((prev) =>
        prev.map((b) =>
          b.bidKey === bidKey
            ? { ...b, userState: userState as BidListItem["userState"] }
            : b,
        ),
      );
    } finally {
      setDisposingKey(null);
    }
  };

  const toggleSelect = (bidKey: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(bidKey)) next.delete(bidKey);
      else next.add(bidKey);
      return next;
    });
  };

  const selectableBids = bids.filter(isSelectable);
  const allSelected = selectableBids.length > 0 && selectableBids.every((b) => selected.has(b.bidKey));

  const toggleSelectAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(selectableBids.map((b) => b.bidKey)));
  };

  const handleBulk = async (action: "accepted" | "rejected") => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    setError(null);
    try {
      await portalApi.bulkDisposition(portal, [...selected], action);
      setSelected(new Set());
      setReloadKey((k) => k + 1);
    } catch {
      setError("Bulk action failed. Try again.");
    } finally {
      setBulkBusy(false);
    }
  };

  if (!portal || !PORTAL_NAMES[portal]) {
    return <p className="text-gray-600">Unknown portal.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">{PORTAL_NAMES[portal]}</h1>
        <p className="text-gray-600 mt-1">
          {loading ? " " : `${total.toLocaleString()} opportunities found`}
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-600 px-4 py-3 bg-red-50 border border-red-200 rounded-xl">
          {error}
        </p>
      )}

      {activeFilter !== "all" && (
        <div className="flex items-center justify-between gap-4 px-4 py-3 bg-blue-50 border border-blue-200 rounded-xl">
          <p className="text-sm font-medium text-blue-900">
            Showing: {FILTER_LABELS[activeFilter]}
          </p>
          <button
            onClick={clearUrlFilter}
            className="text-sm font-medium text-blue-700 hover:text-blue-900 whitespace-nowrap"
          >
            Clear filter
          </button>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder={searchTerms.length
                ? "Add another keyword (Enter to add)…"
                : "Search bids by description, buyer, ID… (Enter to add as keyword)"}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitSearchChip();
                }
              }}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <Button variant="secondary" onClick={() => setShowFilters(!showFilters)} className="gap-2">
            <Filter className="w-4 h-4" />
            Filters
          </Button>
        </div>

        {(statusFilter !== "all" || searchTerms.length > 0) && (
          <div className="flex items-center justify-between gap-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              {searchTerms.map((term) => (
                <FilterChip key={term} label={`Search: "${term}"`} onRemove={() => removeSearchChip(term)} />
              ))}
              {statusFilter !== "all" && (
                <FilterChip
                  label={`Status: ${statusFilter.charAt(0).toUpperCase() + statusFilter.slice(1)}`}
                  onRemove={() => setStatus("all")}
                />
              )}
            </div>
            <button
              onClick={clearAll}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
            >
              Clear All
            </button>
          </div>
        )}

        {showFilters && (
          <div className="pt-4 border-t border-gray-200">
            <div className="mb-4 max-w-xs">
              <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">All Status</option>
                <option value="new">New</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>
            <div className="pt-3 border-t border-gray-200">
              <label className="block text-sm font-medium text-gray-700 mb-2">Quick Filters</label>
              <div className="flex flex-wrap gap-2">
                {(["all", "new", "filtered", "score1to3", "score4", "score5", "closingsoon", "closingactionable", "highpriority", "singletender"] as BidFilter[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setQuickFilter(f)}
                    className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                      activeFilter === f
                        ? "bg-blue-600 text-white"
                        : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                    }`}
                  >
                    {FILTER_LABELS[f]}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {selected.size > 0 && (
        <div className="flex items-center justify-between gap-4 px-4 py-3 bg-indigo-50 border border-indigo-200 rounded-xl">
          <p className="text-sm font-medium text-indigo-900">
            {selected.size} bid{selected.size !== 1 ? "s" : ""} selected
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleBulk("accepted")}
              disabled={bulkBusy}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-green-700 bg-green-100 hover:bg-green-200 disabled:opacity-50 rounded-lg transition-colors"
            >
              {bulkBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              Accept selected
            </button>
            <button
              onClick={() => handleBulk("rejected")}
              disabled={bulkBusy}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-red-700 bg-red-100 hover:bg-red-200 disabled:opacity-50 rounded-lg transition-colors"
            >
              {bulkBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
              Reject selected
            </button>
            <button
              onClick={() => setSelected(new Set())}
              disabled={bulkBusy}
              className="text-xs text-indigo-700 hover:text-indigo-900 font-medium px-2"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center min-h-[400px]">
          <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
        </div>
      ) : (
        <>
          <div className="hidden lg:block bg-white rounded-xl border border-gray-200 overflow-hidden">
            {bids.length > 0 ? (
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-3 py-3 w-10">
                      {selectableBids.length > 0 && (
                        <input
                          type="checkbox"
                          checked={allSelected}
                          onChange={toggleSelectAll}
                          title="Select all new bids on this page"
                          className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        />
                      )}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">Bid ID</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">Buyer</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">Close Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">Rating</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">AI</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">Status</th>
                    <th className="px-4 py-3" />
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {bids.map((bid, idx) => (
                    <tr
                      key={bid.bidKey}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => navigate(detailLink(bid.bidKey, idx))}
                    >
                      <td className="px-3 py-4" onClick={(e) => e.stopPropagation()}>
                        {isSelectable(bid) && (
                          <input
                            type="checkbox"
                            checked={selected.has(bid.bidKey)}
                            onChange={() => toggleSelect(bid.bidKey)}
                            className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                          />
                        )}
                      </td>
                      <td className="px-4 py-4 text-blue-600 font-medium text-sm">{bid.bidId}</td>
                      <td className="px-4 py-4 text-sm text-gray-900">{bid.buyer}</td>
                      <td className="px-4 py-4 text-sm text-gray-900 line-clamp-2 max-w-md">{bid.title}</td>
                      <td className="px-4 py-4 text-sm text-gray-900">
                        {formatClosingDate(bid.closingDate, bid.closingDateRaw)}
                      </td>
                      <td className="px-4 py-4">
                        <RatingDisplay
                          rating={bid.rating}
                          method={bid.method}
                          eliminatedBy={bid.eliminatedBy}
                          compact
                        />
                      </td>
                      <td className="px-4 py-4">
                        {bid.summaryAvailable
                          ? <Sparkles className="w-4 h-4 text-teal-500" title="AI summary available" />
                          : <Sparkles className="w-4 h-4 text-gray-300" title="No AI summary yet" />}
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-col gap-1">
                          <StatusBadge status={bid.userState} />
                          {bid.isSingleTender && <SingleTenderBadge org={bid.singleTenderOrg} />}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {isSelectable(bid) && (
                          <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                            <button
                              onClick={(e) => handleDisposition(bid.bidKey, "accepted", e)}
                              disabled={disposingKey === bid.bidKey}
                              title="Accept"
                              className="p-1.5 rounded-md text-green-600 hover:bg-green-50 disabled:opacity-40 transition-colors"
                            >
                              {disposingKey === bid.bidKey
                                ? <Loader2 className="w-4 h-4 animate-spin" />
                                : <CheckCircle className="w-4 h-4" />}
                            </button>
                            <button
                              onClick={(e) => handleDisposition(bid.bidKey, "rejected", e)}
                              disabled={disposingKey === bid.bidKey}
                              title="Reject"
                              className="p-1.5 rounded-md text-red-500 hover:bg-red-50 disabled:opacity-40 transition-colors"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4"><ChevronRight className="w-5 h-5 text-gray-400" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-12 text-center">
                <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Search className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">No bids found</h3>
                <p className="text-gray-600">Try adjusting your filters or search query</p>
              </div>
            )}
            {bids.length > 0 && (
              <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
            )}
          </div>

          <div className="lg:hidden space-y-4">
            {bids.length > 0 ? (
              <>
                {bids.map((bid, idx) => (
                  <Link
                    key={bid.bidKey}
                    to={detailLink(bid.bidKey, idx)}
                    className="block bg-white rounded-xl border border-gray-200 p-4 hover:shadow-lg transition-shadow"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-start gap-2.5">
                        {isSelectable(bid) && (
                          <span onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
                            <input
                              type="checkbox"
                              checked={selected.has(bid.bidKey)}
                              onChange={() => toggleSelect(bid.bidKey)}
                              className="w-4 h-4 mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                            />
                          </span>
                        )}
                        <div>
                          <div className="text-blue-600 font-semibold mb-1 text-sm">{bid.bidId}</div>
                          <div className="text-sm text-gray-900 font-medium">{bid.buyer}</div>
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <StatusBadge status={bid.userState} />
                        {bid.isSingleTender && <SingleTenderBadge org={bid.singleTenderOrg} />}
                      </div>
                    </div>
                    <p className="text-sm text-gray-600 line-clamp-2 mb-3">{bid.title}</p>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <RatingDisplay rating={bid.rating} method={bid.method} eliminatedBy={bid.eliminatedBy} compact />
                        {bid.summaryAvailable && (
                          <Sparkles className="w-4 h-4 text-teal-500" title="AI summary available" />
                        )}
                      </div>
                      <div className="flex items-center gap-1 text-sm text-gray-500">
                        <Calendar className="w-4 h-4" />
                        {formatClosingDate(bid.closingDate, bid.closingDateRaw)}
                      </div>
                    </div>
                    {isSelectable(bid) && (
                      <div className="flex gap-2 pt-2 border-t border-gray-100">
                        <button
                          onClick={(e) => handleDisposition(bid.bidKey, "accepted", e)}
                          disabled={disposingKey === bid.bidKey}
                          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-sm font-medium text-green-700 bg-green-50 hover:bg-green-100 disabled:opacity-40 transition-colors"
                        >
                          {disposingKey === bid.bidKey
                            ? <Loader2 className="w-4 h-4 animate-spin" />
                            : <CheckCircle className="w-4 h-4" />}
                          Accept
                        </button>
                        <button
                          onClick={(e) => handleDisposition(bid.bidKey, "rejected", e)}
                          disabled={disposingKey === bid.bidKey}
                          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-sm font-medium text-red-600 bg-red-50 hover:bg-red-100 disabled:opacity-40 transition-colors"
                        >
                          <XCircle className="w-4 h-4" />
                          Reject
                        </button>
                      </div>
                    )}
                  </Link>
                ))}
                <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                  <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
                </div>
              </>
            ) : (
              <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
                <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Search className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">No bids found</h3>
                <p className="text-gray-600">Try adjusting your filters or search query</p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <div className="inline-flex items-center gap-1.5 bg-blue-50 border border-blue-200 rounded-md px-2.5 py-1 text-xs">
      <span className="text-blue-900 font-medium">{label}</span>
      <button onClick={onRemove} className="text-blue-600 hover:text-blue-800 rounded-full p-0.5" aria-label="Remove filter">
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    new: "bg-blue-100 text-blue-700",
    accepted: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
  };
  return (
    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[status] ?? "bg-gray-100 text-gray-700"}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function SingleTenderBadge({ org }: { org: string | null }) {
  const isTeclever = /teclever/i.test(org ?? "");
  if (isTeclever) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-800 border border-green-300">
        <Star className="w-3 h-3 fill-green-600 text-green-600" />
        Single Tender – Teclever
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300">
      Single Tender
    </span>
  );
}
