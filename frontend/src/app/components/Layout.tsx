import { useCallback, useEffect, useState } from "react";
import { Outlet, Link, useNavigate } from "react-router";
import { Bell, LogOut, Loader2, ShieldAlert } from "lucide-react";
import { Button } from "./ui/button";
import TecleverLogo from "../../imports/TECLEVER_Logo.jpg";
import { authApi, notificationsApi, systemAlertsApi } from "../lib/api";
import { getAnyGenerating, subscribe as subscribeGenerating } from "../lib/generationState";
import { useAuth } from "../context/AuthContext";
import { SystemAlertPanel } from "./SystemAlertPanel";

export function Layout() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [notifCount, setNotifCount] = useState(0);
  const [alertCount, setAlertCount] = useState(0);
  const [alertPanelOpen, setAlertPanelOpen] = useState(false);
  const [generatingBid, setGeneratingBid] = useState<{ bidId: string } | null>(null);

  const refreshNotifCount = useCallback(async () => {
    try {
      const { count } = await notificationsApi.count();
      setNotifCount(count);
    } catch {
      setNotifCount(0);
    }
  }, []);

  const refreshAlertCount = useCallback(async () => {
    try {
      const { items } = await systemAlertsApi.list(false);
      setAlertCount(items.length);
    } catch {
      setAlertCount(0);
    }
  }, []);

  const checkGeneratingBid = useCallback(() => {
    setGeneratingBid(getAnyGenerating());
  }, []);

  useEffect(() => {
    refreshNotifCount();
    refreshAlertCount();
    checkGeneratingBid();
    const interval = setInterval(() => {
      refreshNotifCount();
      refreshAlertCount();
    }, 60_000);
    const unsub = subscribeGenerating(checkGeneratingBid);
    return () => {
      clearInterval(interval);
      unsub();
    };
  }, [refreshNotifCount, refreshAlertCount, checkGeneratingBid]);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      navigate("/login");
    }
  };

  const handleShieldClick = () => {
    setAlertPanelOpen(true);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-8">
              <Link to="/" className="flex items-center gap-2">
                <img src={TecleverLogo} alt="Teclever" className="h-8" />
              </Link>
              <nav className="hidden md:flex items-center gap-6">
                <Link
                  to="/"
                  className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
                >
                  Dashboard
                </Link>
                <Link
                  to="/activity"
                  className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
                >
                  Activity Log
                </Link>
              </nav>
            </div>
            <div className="flex items-center gap-4">
              <button
                onClick={handleShieldClick}
                className="relative p-2 text-gray-400 hover:text-gray-600 transition-colors"
                aria-label="System alerts"
              >
                <ShieldAlert className="w-5 h-5" />
                {alertCount > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
                )}
              </button>
              <Link
                to="/notifications"
                className="relative p-2 text-gray-400 hover:text-gray-600 transition-colors"
                aria-label="Notifications"
              >
                <Bell className="w-5 h-5" />
                {notifCount > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
                )}
              </Link>
              <Button variant="ghost" size="sm" onClick={handleLogout} className="gap-2">
                <LogOut className="w-4 h-4" />
                <span className="hidden sm:inline">Logout</span>
              </Button>
            </div>
          </div>
        </div>
      </header>
      {generatingBid && (
        <div className="bg-blue-50 border-b border-blue-200 px-4 py-2 flex items-center gap-2 text-sm text-blue-800">
          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
          <span>Generating AI summary for <span className="font-semibold">{generatingBid.bidId}</span>…</span>
        </div>
      )}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>

      <SystemAlertPanel
        open={alertPanelOpen}
        onClose={() => setAlertPanelOpen(false)}
        onAlertsChange={refreshAlertCount}
      />
    </div>
  );
}
