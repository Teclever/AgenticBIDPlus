import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router";
import {
  ArrowLeft,
  Ban,
  Building2,
  Calendar,
  Download,
  MapPin,
  CheckCircle,
  XCircle,
  RotateCcw,
  Sparkles,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { portalApi, ApiRequestError } from "../lib/api";
import { formatClosingDate, bidDetailPath } from "../lib/format";
import { startGenerating, stopGenerating, isGenerating, getOtherGenerating, getGenerationError, setGenerationError, clearGenerationError, subscribe } from "../lib/generationState";
import type { BidDetail as BidDetailType, BidFilter, BidSummary, CriticalFlag, T1aFlag, T1bFlag, PortalId } from "../lib/types";
import { RatingDisplay } from "../components/RatingDisplay";
import { MarkdownContent } from "../components/MarkdownContent";

const PAGE_SIZE = 50;

export function BidDetail() {
  const { portalId, bidKey } = useParams<{ portalId: string; bidKey: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const portal = portalId as PortalId;
  const decodedBidKey = bidKey ? decodeURIComponent(bidKey) : "";

  // Return context — set by PortalBids when navigating into a bid
  const rFilter = (searchParams.get("rfilter") ?? "all") as BidFilter;
  const rPage   = parseInt(searchParams.get("rpage") ?? "1", 10);
  const rIdx    = parseInt(searchParams.get("ridx")  ?? "-1", 10);
  const hasReturnCtx = rIdx >= 0;

  const [bid, setBid] = useState<BidDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<BidSummary | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);  // initialised from generationState in the load effect
  const [otherBidGenerating, setOtherBidGenerating] = useState<string | null>(null);
  const [disposing, setDisposing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const downloadGenRef = useRef(0); // incremented on bid change; used to ignore stale callbacks

  const _genKey = `${portal}:${decodedBidKey}`;

  const _syncOtherGenerating = () => {
    setOtherBidGenerating(getOtherGenerating(_genKey));
  };

  useEffect(() => {
    if (!portal || !decodedBidKey) return;
    downloadGenRef.current++;          // invalidate any pending download callbacks from previous bid
    setLoading(true);
    setBid(null);
    setDisposing(false);
    setDownloading(false);
    setDownloadError(null);
    _syncOtherGenerating();
    // Restore any error that survived navigation
    setGenerateError(getGenerationError(_genKey));
    portalApi
      .bidDetail(portal, decodedBidKey)
      .then((data) => {
        setBid(data);
        setSummary(data.summary);
        if (!data.summary?.available && isGenerating(_genKey)) {
          setGenerating(true);
        }
      })
      .catch(() => setBid(null))
      .finally(() => setLoading(false));
  }, [portal, decodedBidKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep otherBidGenerating in sync via module-level subscription.
  useEffect(() => {
    const unsub = subscribe(_syncOtherGenerating);
    return unsub;
  }, [portal, decodedBidKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll every 3s while THIS bid is generating, until the summary appears or fails.
  useEffect(() => {
    if (!generating || summary?.available) return;
    const timer = setInterval(async () => {
      try {
        const data = await portalApi.bidDetail(portal, decodedBidKey);
        if (data.summary?.available) {
          setSummary(data.summary);
          setGenerating(false);
          stopGenerating(_genKey);
        } else if (data.summary?.status === "failed") {
          setSummary(data.summary);
          setGenerating(false);
          setGenerateError("Summary generation failed. Please try again.");
          stopGenerating(_genKey);
        }
      } catch { /* ignore poll errors */ }
    }, 3000);
    return () => clearInterval(timer);
  }, [generating, summary?.available, portal, decodedBidKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerateSummary = async () => {
    if (!portal || !decodedBidKey || !bid) return;
    // Only claim the global banner if no other bid is currently generating.
    const ownsBanner = !getOtherGenerating("");
    startGenerating(_genKey, bid.bidId); // also clears prior error in generationState
    setGenerating(true);
    setGenerateError(null);
    try {
      const newSummary = await portalApi.generateSummary(portal, decodedBidKey);
      clearGenerationError(_genKey);
      setSummary(newSummary);
    } catch (e) {
      const msg = e instanceof ApiRequestError
        ? (e.code === "bid_closed"
            ? "This bid is closed — summarization is not available."
            : e.message || "Unable to generate summary. Try again later.")
        : "Unable to generate summary. Try again later.";
      setGenerateError(msg);
      setGenerationError(_genKey, msg); // persist across navigation
    } finally {
      setGenerating(false);
      stopGenerating(_genKey);
      void ownsBanner; // referenced to satisfy linter; banner is managed by Layout subscription
    }
  };

  const navigateToNext = async () => {
    try {
      const data = await portalApi.bids(portal, { filter: rFilter, page: rPage, pageSize: PAGE_SIZE });
      // Filters like score1to3 don't exclude rejected bids, so the acted-on bid may still
      // appear in the refreshed list. Skip it explicitly and take the first bid after rIdx.
      const next = data.items.slice(rIdx).find(b => b.bidKey !== decodedBidKey);
      if (!next) {
        navigate(`/portal/${portal}?filter=${rFilter}`);
        return;
      }
      const nextIdx = data.items.indexOf(next);
      navigate(`${bidDetailPath(portal, next.bidKey)}?rfilter=${rFilter}&rpage=${rPage}&ridx=${nextIdx}`);
    } catch {
      navigate(`/portal/${portal}?filter=${rFilter}`);
    }
  };

  const handleDisposition = async (action: "accepted" | "rejected" | "reset") => {
    if (!portal || !decodedBidKey || !bid) return;
    setDisposing(true);
    try {
      const { userState } = await portalApi.disposition(portal, decodedBidKey, action);
      if (action === "reset" || !hasReturnCtx) {
        // No list context — update state in place rather than navigating blindly
        setBid({ ...bid, userState: userState as BidDetailType["userState"] });
        setDisposing(false);
      } else {
        await navigateToNext();
      }
    } catch {
      setDisposing(false);
    }
  };

  if (loading) {
    return <p className="text-gray-500">Loading bid…</p>;
  }

  if (!bid) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-600">Bid not found</p>
        <Button onClick={() => navigate(`/portal/${portal}`)} className="mt-4">
          Back to list
        </Button>
      </div>
    );
  }

  const showDisposition =
    bid.userState === "new" && bid.method === "model";
  const summaryAvailable = summary?.available && summary.status === "ok" && summary.markdown;
  const summaryFailed = !!summary?.status && summary.status !== "ok";
  const isClosed = bid.bidStatus === "CLOSED";

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <button
          onClick={() => hasReturnCtx ? navigate(`/portal/${portal}?filter=${rFilter}`) : navigate(-1)}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors self-start"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 break-all">{bid.bidId}</h1>
          {bid.overview.buyer && (
            <p className="text-gray-600 mt-1">{bid.overview.buyer}</p>
          )}
        </div>
        {showDisposition && (
          <div className="flex gap-3 shrink-0">
            <Button variant="primary" onClick={() => handleDisposition("accepted")} disabled={disposing} className="gap-2">
              {disposing ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              Accept
            </Button>
            <Button variant="danger" onClick={() => handleDisposition("rejected")} disabled={disposing} className="gap-2">
              <XCircle className="w-4 h-4" />
              Reject
            </Button>
          </div>
        )}
        {bid.userState === "rejected" && (
          <Button
            variant="secondary"
            onClick={() => handleDisposition("reset")}
            disabled={disposing}
            className="gap-2 shrink-0"
          >
            {disposing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
            Reset to New
          </Button>
        )}
      </div>

      {bid.hasRestrictiveEligibility && (
        <div className="flex items-start gap-3 px-4 py-3 bg-amber-50 border border-amber-300 rounded-xl">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-amber-900">Restrictive eligibility detected</p>
            <p className="text-sm text-amber-800 mt-0.5">
              This bid contains participation clauses that may limit vendors — review carefully before pursuing.
            </p>
          </div>
        </div>
      )}

      <section className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Bid Overview</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {bid.overview.ministry && (
            <InfoField icon={<Building2 className="w-4 h-4" />} label="Ministry" value={bid.overview.ministry} />
          )}
          {bid.overview.department && (
            <InfoField icon={<Building2 className="w-4 h-4" />} label="Department" value={bid.overview.department} />
          )}
          {bid.overview.openingDateRaw && (
            <InfoField icon={<Calendar className="w-4 h-4" />} label="Open Date" value={bid.overview.openingDateRaw} />
          )}
          {(bid.overview.closingDate || bid.overview.closingDateRaw) && (
            <InfoField
              icon={<Calendar className="w-4 h-4" />}
              label="Close Date"
              value={formatClosingDate(bid.overview.closingDate, bid.overview.closingDateRaw ?? "")}
            />
          )}
          {bid.overview.location && (
            <InfoField icon={<MapPin className="w-4 h-4" />} label="Location" value={bid.overview.location} />
          )}
          {bid.overview.value && (
            <InfoField icon={<Building2 className="w-4 h-4" />} label="Value" value={bid.overview.value} />
          )}
          <InfoField icon={<Calendar className="w-4 h-4" />} label="Bid Status" value={bid.bidStatus} />
        </div>
        {bid.overview.title && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <h3 className="text-sm font-medium text-gray-700 mb-2">Description</h3>
            <p className="text-gray-900">{bid.overview.title}</p>
          </div>
        )}
      </section>

      <section className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-xl border border-purple-200 p-6">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="w-5 h-5 text-purple-600" />
          <h2 className="text-xl font-semibold text-gray-900">AI Evaluation</h2>
        </div>
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">Rating</p>
            <RatingDisplay
              rating={bid.rating}
              method={bid.method}
              eliminatedBy={bid.eliminatedBy}
            />
          </div>
          {bid.method === "model" && bid.rationale && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">Rationale</h3>
              <p className="text-gray-900">{bid.rationale}</p>
            </div>
          )}
        </div>
      </section>

      <section className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">AI Summary</h2>

        {summaryAvailable ? (
          <SummaryBlock summary={summary!} />
        ) : (
          <div className="space-y-4">
            {generating ? (
              <div className="flex items-start gap-3 px-4 py-4 bg-blue-50 border border-blue-200 rounded-lg">
                <Loader2 className="w-5 h-5 text-blue-600 animate-spin shrink-0 mt-0.5" />
                <p className="text-sm text-blue-900">
                  Generating summary, this may take up to a minute…
                </p>
              </div>
            ) : summaryFailed ? (
              <div className="flex items-start gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-lg">
                <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-red-800">Summary generation failed</p>
                  <p className="text-sm text-red-700 mt-0.5">
                    The bid documents could not be fetched or parsed. You can try generating again, or check the source documents on the portal.
                  </p>
                </div>
              </div>
            ) : generateError ? (
              <div className="flex items-start gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-lg">
                <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                <p className="text-sm text-red-700">{generateError}</p>
              </div>
            ) : otherBidGenerating ? (
              <div className="flex items-start gap-3 px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg">
                <Loader2 className="w-4 h-4 text-blue-600 animate-spin shrink-0 mt-0.5" />
                <p className="text-sm text-blue-800">
                  Summary for <span className="font-semibold">{otherBidGenerating}</span> is in progress. Please wait until it completes.
                </p>
              </div>
            ) : (
              <p className="text-sm text-gray-600">
                {isClosed
                  ? "This bid is closed — summarization is not available."
                  : "No summary yet. Generate one from staged documents."}
              </p>
            )}
            <Button
              variant="primary"
              onClick={handleGenerateSummary}
              disabled={isClosed || generating || !!otherBidGenerating}
              className="gap-2"
            >
              Generate Summary
            </Button>
          </div>
        )}
      </section>

      <section className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Documents</h2>
        <button
          onClick={async () => {
            const gen = ++downloadGenRef.current;
            setDownloading(true);
            setDownloadError(null);
            try {
              const res = await fetch(
                portalApi.documentDownloadUrl(portal as PortalId, decodedBidKey),
                { credentials: "include" },
              );
              if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.error?.message || `Download failed (${res.status})`);
              }
              const blob = await res.blob();
              // Trigger save-to-disk regardless of whether user navigated away
              const disposition = res.headers.get("Content-Disposition") ?? "";
              const filename = disposition.match(/filename="?([^";\n]+)"?/)?.[1] ?? "documents";
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = filename;
              a.click();
              URL.revokeObjectURL(url);
            } catch (e) {
              // Only show the error if the user is still on this bid
              if (downloadGenRef.current === gen) {
                setDownloadError(e instanceof Error ? e.message : "Download failed. Try again.");
              }
            } finally {
              if (downloadGenRef.current === gen) setDownloading(false);
            }
          }}
          disabled={downloading}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
          {downloading ? "Downloading…" : "Download documents"}
        </button>
        {downloadError && (
          <p className="mt-2 text-sm text-red-600">{downloadError}</p>
        )}
        {!downloadError && (
          <p className="mt-2 text-xs text-gray-400">
            Fetches from the portal if not cached locally. May take a moment for large bids.
          </p>
        )}
      </section>

    </div>
  );
}


function SummaryBlock({ summary }: { summary: BidSummary }) {
  const flags = summary.criticalFlags ?? [];
  const poisonPills = flags.filter((f): f is T1aFlag | T1bFlag => f.tier === "T1a" || f.tier === "T1b");
  const gates = flags.filter((f) => f.tier === "T2");

  return (
    <div className="space-y-4">
      {summary.unparsedDocuments.length > 0 && (
        <div className="flex items-start gap-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-lg">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
          <div>
            <p className="font-medium text-amber-900">
              ⚠ Some documents could not be read
            </p>
            <ul className="text-sm text-amber-800 mt-1 list-disc list-inside">
              {summary.unparsedDocuments.map((doc) => (
                <li key={doc}>{doc}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {summary.coverage === "partial" && (
        <p className="text-sm text-gray-600 italic">
          Note: this summary may be incomplete (partial document coverage).
        </p>
      )}

      {flags.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
            🚩 Critical Flags
          </h3>

          {poisonPills.length > 0 && (
            <div className="space-y-2">
              {poisonPills.map((flag, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 px-4 py-3 bg-red-50 border border-red-300 rounded-lg"
                >
                  <Ban className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-semibold text-red-900">{flag.label}</p>
                    {flag.tier === "T1a" && (
                      <p className="text-sm text-red-800 mt-0.5">{(flag as T1aFlag).clause}</p>
                    )}
                    {flag.tier === "T1b" && (
                      <p className="text-sm text-red-800 mt-0.5">
                        Models: {(flag as T1bFlag).models}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {gates.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {gates.map((flag, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 px-3 py-1 text-xs font-medium bg-amber-50 border border-amber-300 text-amber-900 rounded-full"
                >
                  <AlertTriangle className="w-3 h-3" />
                  {flag.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {summary.markdown && <MarkdownContent content={summary.markdown} />}
    </div>
  );
}

function InfoField({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="p-2 bg-gray-100 rounded-lg text-gray-600">{icon}</div>
      <div>
        <div className="text-xs text-gray-500 mb-0.5">{label}</div>
        <div className="text-sm font-medium text-gray-900">{value}</div>
      </div>
    </div>
  );
}

