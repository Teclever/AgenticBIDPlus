import { useEffect, useState } from "react";
import { X, ShieldAlert, RefreshCw, CheckCircle, AlertTriangle, Clock } from "lucide-react";
import { Button } from "./ui/button";
import { systemAlertsApi, ApiRequestError } from "../lib/api";
import type { SystemAlert, AlertStatus } from "../lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onAlertsChange: () => void;
}

const ALERT_TYPE_LABELS: Record<string, string> = {
  SCORING_FAILURE: "Scoring failed",
  CREDIT_EXHAUSTED: "Anthropic credit limit reached",
  INVALID_API_KEY: "Invalid API key",
  SUMMARY_FAILURE: "AI summary failed",
  CYCLE_FAILED: "Nightly cycle failed",
  CYCLE_PARTIAL: "Nightly cycle partial failure",
};

function alertLabel(type: string): string {
  return ALERT_TYPE_LABELS[type] ?? type;
}

function StatusBadge({ status }: { status: AlertStatus }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
        <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
        Active
      </span>
    );
  }
  if (status === "retry_failed") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
        <AlertTriangle className="w-3 h-3" />
        Retry failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
      <CheckCircle className="w-3 h-3" />
      Cleared
    </span>
  );
}

function AlertCard({
  alert,
  onRetry,
  retrying,
}: {
  alert: SystemAlert;
  onRetry: (alertType: string, portal: string | null) => void;
  retrying: boolean;
}) {
  const isActionable = alert.status === "active" || alert.status === "retry_failed";
  const cardBg =
    alert.status === "active"
      ? "bg-red-50 border-red-200"
      : alert.status === "retry_failed"
      ? "bg-orange-50 border-orange-200"
      : "bg-gray-50 border-gray-200";

  return (
    <div className={`rounded-lg border p-4 space-y-2 ${cardBg}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900">{alertLabel(alert.alertType)}</p>
          {alert.portal && (
            <p className="text-xs text-gray-500 mt-0.5 uppercase tracking-wide">{alert.portal}</p>
          )}
        </div>
        <StatusBadge status={alert.status} />
      </div>

      <p className="text-sm text-gray-700 leading-snug">{alert.reason}</p>

      {alert.bidRefs.length > 0 && (
        <p className="text-xs text-gray-500">
          {alert.bidRefs.length} affected bid{alert.bidRefs.length !== 1 ? "s" : ""}
          {alert.bidRefs.length <= 3
            ? `: ${alert.bidRefs.join(", ")}`
            : `: ${alert.bidRefs.slice(0, 3).join(", ")} + ${alert.bidRefs.length - 3} more`}
        </p>
      )}

      {alert.lastRetryError && (
        <p className="text-xs text-orange-700 italic">Last retry error: {alert.lastRetryError}</p>
      )}

      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-1 text-xs text-gray-400">
          <Clock className="w-3 h-3" />
          {new Date(alert.raisedAt).toLocaleString()}
          {alert.retryCount > 0 && ` · ${alert.retryCount} retr${alert.retryCount === 1 ? "y" : "ies"}`}
        </div>
        {isActionable && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => onRetry(alert.alertType, alert.portal)}
            disabled={retrying}
            className="gap-1.5 text-xs"
          >
            {retrying ? (
              <RefreshCw className="w-3 h-3 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3" />
            )}
            Retry & Clear
          </Button>
        )}
      </div>
    </div>
  );
}

export function SystemAlertPanel({ open, onClose, onAlertsChange }: Props) {
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);
  const [showCleared, setShowCleared] = useState(false);
  const [loading, setLoading] = useState(false);
  const [retryingKey, setRetryingKey] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);

  const load = async (incCleared = showCleared) => {
    setLoading(true);
    try {
      const { items } = await systemAlertsApi.list(incCleared);
      setAlerts(items);
    } catch {
      // silently ignore load errors
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      load();
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleToggleCleared = () => {
    const next = !showCleared;
    setShowCleared(next);
    load(next);
  };

  const handleRetry = async (alertType: string, portal: string | null) => {
    const key = `${alertType}|${portal ?? ""}`;
    setRetryingKey(key);
    setRetryError(null);
    try {
      await systemAlertsApi.retry(alertType, portal);
      await load();
      onAlertsChange();
    } catch (e) {
      if (e instanceof ApiRequestError) {
        setRetryError(e.message);
      } else {
        setRetryError("Retry failed. Try again later.");
      }
      await load();
    } finally {
      setRetryingKey(null);
    }
  };

  if (!open) return null;

  const activeAlerts = alerts.filter((a) => a.status !== "cleared");
  const clearedAlerts = alerts.filter((a) => a.status === "cleared");

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="relative w-full max-w-md bg-white shadow-xl flex flex-col h-full">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-red-600" />
            <h2 className="text-base font-semibold text-gray-900">System Alerts</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {loading && (
            <p className="text-sm text-gray-500 text-center py-4">Loading…</p>
          )}

          {!loading && retryError && (
            <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">{retryError}</p>
            </div>
          )}

          {!loading && activeAlerts.length === 0 && (
            <div className="text-center py-8 text-gray-500">
              <CheckCircle className="w-8 h-8 mx-auto mb-2 text-green-400" />
              <p className="text-sm">No active alerts</p>
            </div>
          )}

          {activeAlerts.map((a) => (
            <AlertCard
              key={a.id}
              alert={a}
              onRetry={handleRetry}
              retrying={retryingKey === `${a.alertType}|${a.portal ?? ""}`}
            />
          ))}

          {showCleared && clearedAlerts.length > 0 && (
            <>
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wide pt-2">
                Cleared (last 10 days)
              </p>
              {clearedAlerts.map((a) => (
                <AlertCard
                  key={a.id}
                  alert={a}
                  onRetry={handleRetry}
                  retrying={false}
                />
              ))}
            </>
          )}
        </div>

        <div className="px-4 py-3 border-t border-gray-200">
          <button
            onClick={handleToggleCleared}
            className="text-xs text-blue-600 hover:underline"
          >
            {showCleared ? "Hide cleared" : "Show cleared alerts"}
          </button>
        </div>
      </aside>
    </div>
  );
}
