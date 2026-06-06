import { useEffect, useState } from "react";
import { X, AlertTriangle } from "lucide-react";
import { Button } from "./ui/button";
import { notificationsApi } from "../lib/api";
import { ApiRequestError } from "../lib/api";
import type { NotificationItem } from "../lib/types";
import { bidDetailPath } from "../lib/format";
import { useNavigate } from "react-router";

interface NotificationPanelProps {
  open: boolean;
  onClose: () => void;
  onQueueChange: () => void;
}

export function NotificationPanel({ open, onClose, onQueueChange }: NotificationPanelProps) {
  const navigate = useNavigate();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [disputeTarget, setDisputeTarget] = useState<NotificationItem | null>(null);
  const [reason, setReason] = useState("");
  const [disputing, setDisputing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchQueue = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await notificationsApi.list();
      setItems(data.items);
    } catch {
      setError("Unable to load notifications.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    fetchQueue();
    notificationsApi.viewed().then(() => onQueueChange()).catch(() => {});
  }, [open]);

  const handleSaveAll = async () => {
    setSaving(true);
    setError(null);
    try {
      await notificationsApi.saveAll();
      setItems([]);
      onQueueChange();
    } catch {
      setError("Save all failed. Try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleDispute = async () => {
    if (!disputeTarget || !reason.trim()) return;
    setDisputing(true);
    setError(null);
    try {
      await notificationsApi.dispute(disputeTarget.portal, disputeTarget.bidKey, reason.trim());
      setItems((prev) => prev.filter((i) => i.bidKey !== disputeTarget.bidKey));
      setDisputeTarget(null);
      setReason("");
      onQueueChange();
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 404) {
        setItems((prev) => prev.filter((i) => i.bidKey !== disputeTarget.bidKey));
        setDisputeTarget(null);
        setReason("");
        onQueueChange();
      } else {
        setError("Dispute failed. Try again.");
      }
    } finally {
      setDisputing(false);
    }
  };

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} aria-hidden />
      <div className="fixed top-16 right-4 sm:right-8 z-50 w-full max-w-md bg-white rounded-xl shadow-2xl border border-gray-200 flex flex-col max-h-[calc(100vh-5rem)]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Auto-filtered bids</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mx-4 mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {loading ? (
            <p className="text-sm text-gray-500 text-center py-8">Loading…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-8">All caught up — no bids pending review.</p>
          ) : (
            items.map((item) => (
              <button
                key={`${item.portal}-${item.bidKey}`}
                onClick={() => setDisputeTarget(item)}
                className="w-full text-left p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50/50 transition-colors"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                    {item.portal}
                  </span>
                  <span className="text-sm font-medium text-blue-600 truncate">{item.bidId}</span>
                </div>
                <p className="text-sm text-gray-900 line-clamp-2">{item.description}</p>
                <p className="text-xs text-amber-700 mt-1">Filtered: {item.matchedKeyword}</p>
                <p className="text-xs text-gray-500 mt-1">Closes: {item.closingDateRaw}</p>
              </button>
            ))
          )}
        </div>

        {items.length > 0 && (
          <div className="px-4 py-3 border-t border-gray-200">
            <Button
              variant="primary"
              className="w-full"
              onClick={handleSaveAll}
              disabled={saving}
            >
              {saving ? "Saving…" : "Save all"}
            </Button>
          </div>
        )}
      </div>

      {disputeTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4">
          <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl">
            <div className="flex items-start gap-3 mb-4">
              <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Dispute auto-filter</h3>
                <p className="text-sm text-gray-600 mt-1">{disputeTarget.description}</p>
                <p className="text-xs text-amber-700 mt-1">
                  Matched keyword: {disputeTarget.matchedKeyword}
                </p>
              </div>
            </div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Why should this bid be promoted for scoring?
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              placeholder="Explain why this is a false filter…"
            />
            <div className="flex gap-3 justify-end mt-4">
              <Button variant="ghost" onClick={() => { setDisputeTarget(null); setReason(""); }}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleDispute}
                disabled={!reason.trim() || disputing}
              >
                {disputing ? "Submitting…" : "Confirm dispute"}
              </Button>
            </div>
            <button
              type="button"
              onClick={() => {
                onClose();
                setDisputeTarget(null);
                navigate(bidDetailPath(disputeTarget.portal, disputeTarget.bidKey));
              }}
              className="mt-3 text-xs text-blue-600 hover:underline"
            >
              View bid detail instead
            </button>
          </div>
        </div>
      )}
    </>
  );
}
