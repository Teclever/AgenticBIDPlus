import { useCallback, useEffect, useState } from "react";
import { Outlet, Link, useNavigate } from "react-router";
import { Bell, LogOut } from "lucide-react";
import { Button } from "./ui/button";
import TecleverLogo from "../../imports/TECLEVER_Logo.jpg";
import { authApi, notificationsApi } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { NotificationPanel } from "./NotificationPanel";

export function Layout() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [notifCount, setNotifCount] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);

  const refreshNotifCount = useCallback(async () => {
    try {
      const { count } = await notificationsApi.count();
      setNotifCount(count);
    } catch {
      setNotifCount(0);
    }
  }, []);

  useEffect(() => {
    refreshNotifCount();
    const interval = setInterval(refreshNotifCount, 60_000);
    return () => clearInterval(interval);
  }, [refreshNotifCount]);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      navigate("/login");
    }
  };

  const handleBellClick = () => {
    setPanelOpen(true);
    setNotifCount(0);
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
                onClick={handleBellClick}
                className="relative p-2 text-gray-400 hover:text-gray-600 transition-colors"
                aria-label="Notifications"
              >
                <Bell className="w-5 h-5" />
                {notifCount > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
                )}
              </button>
              <Button variant="ghost" size="sm" onClick={handleLogout} className="gap-2">
                <LogOut className="w-4 h-4" />
                <span className="hidden sm:inline">Logout</span>
              </Button>
            </div>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>

      <NotificationPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        onQueueChange={refreshNotifCount}
      />
    </div>
  );
}
