import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, XCircle, Search, Download } from "lucide-react";
import { Link } from "react-router";
import { notificationsApi } from "../lib/api";
import { getErrorMessage, formatDateSafe, toString, toArray } from "../lib/utils";
import { Button } from "../components/ui/button";
import { bidDetailPath } from "../lib/format";
import type { NotificationItem } from "../lib/types";
import { formatDistanceToNow, format } from "date-fns";

export function Notifications() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [disputingKey, setDisputingKey] = useState<string | null>(null);
  const [disputeReason, setDisputeReason] = useState("");
  const [disputeError, setDisputeError] = useState<string | null>(null);
  const [disputing, setDisputing] = useState(false);
  const [search, setSearch] = useState("");
  const [matched, setMatched] = useState(0);
  const [downloading, setDownloading] = useState(false);

  const fetchNotifications = async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await notificationsApi.list(q);
      setItems(toArray(data.items));
      setTotal(data.total);
      setMatched(data.matched ?? data.total);
      await notificationsApi.viewed().catch(() => {});
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load notifications."));
      setItems([]);
      setTotal(0);
      setMatched(0);
    } finally {
      setLoading(false);
    }
  };

  // Debounced fetch on search change (initial load fires immediately with empty search).
  useEffect(() => {
    const t = setTimeout(() => fetchNotifications(search), search ? 350 : 0);
    return () => clearTimeout(t);
  }, [search]);

  const handleDownloadCsv = async () => {
    setDownloading(true);
    try {
      const blob = await notificationsApi.exportCsv(search);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `auto-filtered-bids-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(getErrorMessage(err, "CSV download failed."));
    } finally {
      setDownloading(false);
    }
  };

  const handleSaveAll = async () => {
    setSaving(true);
    setError(null);
    try {
      const data = await notificationsApi.saveAll();
      setItems([]);
      setTotal(0);
      setMatched(0);
      setSaveMessage(`Accepted ${data.accepted} filtered bid${data.accepted !== 1 ? "s" : ""}`);
    } catch (err) {
      setError(getErrorMessage(err, "Save all failed. Try again."));
    } finally {
      setSaving(false);
    }
  };

  const startDispute = (bidKey: string) => {
    setDisputingKey(bidKey);
    setDisputeReason("");
    setDisputeError(null);
  };

  const cancelDispute = () => {
    setDisputingKey(null);
    setDisputeReason("");
    setDisputeError(null);
  };

  const handleDispute = async (item: NotificationItem) => {
    if (!disputeReason.trim()) {
      setDisputeError("Please provide a reason.");
      return;
    }
    setDisputing(true);
    setDisputeError(null);
    try {
      await notificationsApi.dispute(item.portal, item.bidKey, disputeReason.trim());
      setItems((prev) => prev.filter((i) => i.bidKey !== item.bidKey));
      setTotal((t) => t - 1);
      setMatched((m) => m - 1);
      cancelDispute();
    } catch (err) {
      setDisputeError(getErrorMessage(err, "Dispute failed. Try again."));
    } finally {
      setDisputing(false);
    }
  };

  if (loading && items.length === 0 && !search) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-600 mb-4">{error}</p>
        <button onClick={() => fetchNotifications(search)} className="text-blue-600 hover:text-blue-800 font-medium">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Notifications</h1>
            <p className="text-gray-600 mt-1">Review bids flagged by the auto-filter</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={handleDownloadCsv} disabled={downloading || total === 0} className="gap-2">
              {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              Download CSV
            </Button>
            {total > 0 && (
              <Button variant="primary" onClick={handleSaveAll} disabled={saving} className="gap-2">
                {saving ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />Saving…</>
                ) : (
                  `Accept All (${total.toLocaleString()})`
                )}
              </Button>
            )}
          </div>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search flagged bids by Bid ID, title, or filter keyword…"
            className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
          />
          {loading && <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 animate-spin text-gray-400" />}
        </div>

        {total > 0 && (
          <p className="text-sm text-gray-500">
            {search.trim()
              ? `${matched.toLocaleString()} match${matched !== 1 ? "es" : ""}${matched > items.length ? " (showing first 200)" : ""} · ${total.toLocaleString()} flagged in total`
              : `Showing ${items.length.toLocaleString()} of ${total.toLocaleString()} flagged bids${total > items.length ? " — search to find specific bids, or download the CSV for the full list" : ""}`}
          </p>
        )}
      </div>

      {saveMessage && (
        <div className="px-4 py-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800 flex items-center justify-between">
          <span>{saveMessage}</span>
          <button onClick={() => setSaveMessage(null)} className="ml-4 text-green-600 hover:text-green-800">
            Dismiss
          </button>
        </div>
      )}

      {total === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <AlertTriangle className="w-8 h-8 text-gray-400" />
          </div>
          <h3 className="text-lg font-medium text-gray-900 mb-2">No flagged bids</h3>
          <p className="text-gray-600">The auto-filter queue is clear</p>
        </div>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <Search className="w-8 h-8 text-gray-400" />
          </div>
          <h3 className="text-lg font-medium text-gray-900 mb-2">No matches</h3>
          <p className="text-gray-600 mb-4">No flagged bids match “{search}”.</p>
          <button onClick={() => setSearch("")} className="text-blue-600 hover:text-blue-800 font-medium">Clear search</button>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <div
              key={`${item.portal}-${item.bidKey}`}
              className="bg-white rounded-xl border border-gray-200 p-6"
            >
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <Link
                      to={bidDetailPath(item.portal, item.bidKey)}
                      className="text-blue-600 font-semibold hover:text-blue-800"
                    >
                      {toString(item.bidId)}
                    </Link>
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 uppercase">
                      {toString(item.portal)}
                    </span>
                  </div>
                  <p className="text-gray-900 line-clamp-2">{toString(item.description)}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm mb-4">
                <div>
                  <span className="text-gray-600">Filtered by:</span>
                  <span className="ml-2 font-medium text-amber-700">{toString(item.matchedKeyword)}</span>
                </div>
                <div>
                  <span className="text-gray-600">Closes:</span>
                  <span className="ml-2 font-medium text-gray-900">
                    {formatDateSafe(item.closingDateRaw, (d) => format(d, "MMM dd, yyyy"), item.closingDateRaw)}
                  </span>
                </div>
                <div>
                  <span className="text-gray-600">First seen:</span>
                  <span className="ml-2 font-medium text-gray-900">
                    {formatDateSafe(item.firstSeen, (d) => formatDistanceToNow(d, { addSuffix: true }))}
                  </span>
                </div>
              </div>

              {disputingKey === item.bidKey ? (
                <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Why should this bid be promoted for scoring?
                  </label>
                  <textarea
                    value={disputeReason}
                    onChange={(e) => setDisputeReason(e.target.value)}
                    placeholder="Explain why this is a false filter…"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent mb-2 text-sm"
                    rows={3}
                  />
                  {disputeError && (
                    <div className="mb-2 text-sm text-red-600 flex items-center gap-2">
                      <XCircle className="w-4 h-4 shrink-0" />
                      {disputeError}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button
                      variant="primary"
                      onClick={() => handleDispute(item)}
                      disabled={!disputeReason.trim() || disputing}
                      className="gap-2"
                    >
                      {disputing ? <><Loader2 className="w-4 h-4 animate-spin" />Submitting…</> : "Confirm dispute"}
                    </Button>
                    <Button variant="ghost" onClick={cancelDispute}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => startDispute(item.bidKey)}
                  className="px-4 py-2 bg-amber-100 text-amber-800 rounded-lg hover:bg-amber-200 text-sm font-medium"
                >
                  Dispute
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
