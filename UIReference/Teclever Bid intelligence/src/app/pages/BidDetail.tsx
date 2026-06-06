import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router";
import {
  ArrowLeft,
  Building2,
  Calendar,
  MapPin,
  CheckCircle,
  XCircle,
  Sparkles,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { portalApi, ApiRequestError } from "../lib/api";
import { formatClosingDate } from "../lib/format";
import type { BidDetail as BidDetailType, BidSummary, PortalId } from "../lib/types";
import { RatingDisplay } from "../components/RatingDisplay";
import { MarkdownContent } from "../components/MarkdownContent";

export function BidDetail() {
  const { portalId, bidKey } = useParams<{ portalId: string; bidKey: string }>();
  const navigate = useNavigate();
  const portal = portalId as PortalId;
  const decodedBidKey = bidKey ? decodeURIComponent(bidKey) : "";

  const [bid, setBid] = useState<BidDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<BidSummary | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [showAcceptModal, setShowAcceptModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [disposing, setDisposing] = useState(false);

  useEffect(() => {
    if (!portal || !decodedBidKey) return;
    setLoading(true);
    portalApi
      .bidDetail(portal, decodedBidKey)
      .then((data) => {
        setBid(data);
        setSummary(data.summary);
      })
      .catch(() => setBid(null))
      .finally(() => setLoading(false));
  }, [portal, decodedBidKey]);

  const handleGenerateSummary = async () => {
    if (!portal || !decodedBidKey) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const { summary: newSummary } = await portalApi.generateSummary(portal, decodedBidKey);
      setSummary(newSummary);
    } catch (e) {
      if (e instanceof ApiRequestError && e.code === "summarization_busy") {
        setGenerateError(
          "Summarization is busy (nightly run in progress). Try again shortly.",
        );
      } else if (e instanceof ApiRequestError && e.code === "bid_closed") {
        setGenerateError("This bid is closed — summarization is not available.");
      } else {
        setGenerateError("Unable to generate summary. Try again later.");
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleDisposition = async (action: "accepted" | "rejected") => {
    if (!portal || !decodedBidKey || !bid) return;
    setDisposing(true);
    try {
      const { userState } = await portalApi.disposition(portal, decodedBidKey, action);
      setBid({ ...bid, userState: userState as BidDetailType["userState"] });
      setShowAcceptModal(false);
      setShowRejectModal(false);
    } finally {
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
  const summaryAvailable = summary?.available && summary.markdown;
  const isClosed = bid.bidStatus === "CLOSED";

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <button
          onClick={() => navigate(`/portal/${portal}`)}
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
            <Button variant="primary" onClick={() => setShowAcceptModal(true)} className="gap-2">
              <CheckCircle className="w-4 h-4" />
              Accept
            </Button>
            <Button variant="danger" onClick={() => setShowRejectModal(true)} className="gap-2">
              <XCircle className="w-4 h-4" />
              Reject
            </Button>
          </div>
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
              disabled={isClosed || generating}
              className="gap-2"
            >
              Generate Summary
            </Button>
            {generateError && (
              <p className="text-sm text-red-600">{generateError}</p>
            )}
          </div>
        )}
      </section>

      {showAcceptModal && (
        <ConfirmModal
          title="Accept Bid"
          message={`Are you sure you want to accept bid ${bid.bidId}?`}
          confirmText="Accept"
          confirmVariant="primary"
          loading={disposing}
          onConfirm={() => handleDisposition("accepted")}
          onCancel={() => setShowAcceptModal(false)}
        />
      )}

      {showRejectModal && (
        <ConfirmModal
          title="Reject Bid"
          message={`Are you sure you want to reject bid ${bid.bidId}?`}
          confirmText="Reject"
          confirmVariant="danger"
          loading={disposing}
          onConfirm={() => handleDisposition("rejected")}
          onCancel={() => setShowRejectModal(false)}
        />
      )}
    </div>
  );
}

function SummaryBlock({ summary }: { summary: BidSummary }) {
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

function ConfirmModal({
  title,
  message,
  confirmText,
  confirmVariant,
  loading,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmText: string;
  confirmVariant: "primary" | "danger";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">{title}</h3>
        <p className="text-gray-600 mb-6">{message}</p>
        <div className="flex gap-3 justify-end">
          <Button variant="ghost" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm} disabled={loading}>
            {loading ? "Saving…" : confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
}
