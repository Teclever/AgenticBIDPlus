import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, XCircle } from "lucide-react";
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

  const fetchNotifications = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await notificationsApi.list();
      setItems(toArray(data.items));
      setTotal(data.total);
      await notificationsApi.viewed().catch(() => {});
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load notifications."));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchNotifications(); }, []);

  const handleSaveAll = async () => {
    setSaving(true);
    setError(null);
    try {
      const data = await notificationsApi.saveAll();
      setItems([]);
      setTotal(0);
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
      cancelDispute();
    } catch (err) {
      setDisputeError(getErrorMessage(err, "Dispute failed. Try again."));
    } finally {
      setDisputing(false);
    }
  };

  if (loading) {
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
        <button onClick={fetchNotifications} className="text-blue-600 hover:text-blue-800 font-medium">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Notifications</h1>
          <p className="text-gray-600 mt-1">Review bids flagged by the auto-filter</p>
        </div>
        {total > 0 && (
          <Button
            variant="primary"
            onClick={handleSaveAll}
            disabled={saving}
            className="gap-2"
          >
            {saving ? (
              <><Loader2 className="w-4 h-4 animate-spin" />Saving…</>
            ) : (
              `Save All (${total} bid${total !== 1 ? "s" : ""})`
            )}
          </Button>
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
