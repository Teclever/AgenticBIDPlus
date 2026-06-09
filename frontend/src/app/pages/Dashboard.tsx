import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Building, Rocket, Plane } from "lucide-react";
import { portalApi, ApiRequestError, isAuthError } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { formatWindowDate } from "../lib/format";
import type { BidFilter, PortalId, PortalStats } from "../lib/types";
import { Button } from "../components/ui/button";

const PORTALS: { id: PortalId; name: string; fullName: string; icon: React.ReactNode; color: "blue" | "indigo" | "purple" }[] = [
  { id: "gem", name: "GEM", fullName: "Government e-Marketplace", icon: <Building className="w-8 h-8" />, color: "blue" },
  { id: "hal", name: "HAL", fullName: "Hindustan Aeronautics Limited", icon: <Plane className="w-8 h-8" />, color: "indigo" },
  { id: "isro", name: "ISRO", fullName: "Indian Space Research Organisation", icon: <Rocket className="w-8 h-8" />, color: "purple" },
];

const EMPTY_STATS: Record<PortalId, PortalStats | null> = {
  gem: null,
  hal: null,
  isro: null,
};

export function Dashboard() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [statsMap, setStatsMap] = useState(EMPTY_STATS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const entries = await Promise.all(
        PORTALS.map(async (p) => {
          const stats = await portalApi.stats(p.id);
          return [p.id, stats] as const;
        }),
      );
      const map = { ...EMPTY_STATS };
      for (const [id, stats] of entries) {
        map[id] = stats;
      }
      setStatsMap(map);
    } catch (e) {
      if (e instanceof ApiRequestError && isAuthError(e.status, e.code)) {
        navigate("/login", { replace: true });
        return;
      }
      setStatsMap(EMPTY_STATS);
      setError("Unable to load dashboard stats. Try refreshing the page.");
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (authLoading || !user) return;
    loadStats();
  }, [user, authLoading, loadStats]);

  const statsReady = PORTALS.every((p) => statsMap[p.id] !== null);

  if (authLoading || (loading && !statsReady)) {
    return <p className="text-gray-500">Loading dashboard…</p>;
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-bold text-gray-900">Procurement Portals</h1>
        <p className="text-red-600">{error}</p>
        <Button variant="outline" onClick={loadStats}>
          Retry
        </Button>
      </div>
    );
  }

  if (!statsReady) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-bold text-gray-900">Procurement Portals</h1>
        <p className="text-gray-600">Portal statistics could not be loaded.</p>
        <Button variant="outline" onClick={loadStats}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Procurement Portals</h1>
        <p className="text-gray-600 mt-1">AI-powered bid intelligence and opportunity tracking</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {PORTALS.map((portal) => (
          <PortalCard
            key={portal.id}
            {...portal}
            stats={statsMap[portal.id]!}
          />
        ))}
      </div>
    </div>
  );
}

interface PortalCardProps {
  id: PortalId;
  name: string;
  fullName: string;
  icon: React.ReactNode;
  color: "blue" | "indigo" | "purple";
  stats: PortalStats;
}

function PortalCard({ id, name, fullName, icon, color, stats }: PortalCardProps) {
  const colorClasses = {
    blue: { icon: "text-blue-600 bg-blue-100", accent: "text-blue-600" },
    indigo: { icon: "text-indigo-600 bg-indigo-100", accent: "text-indigo-600" },
    purple: { icon: "text-purple-600 bg-purple-100", accent: "text-purple-600" },
  };

  const counts = stats.counts;
  const windowLabel = formatWindowDate(stats.windowDate);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-lg transition-shadow">
      <div className="flex items-center gap-2 mb-4">
        <div className={`p-2 rounded-lg ${colorClasses[color].icon}`}>{icon}</div>
        <span className="text-sm font-medium text-gray-600">{name}</span>
      </div>

      <div className="h-16 flex items-start">
        <h3 className="text-xl font-bold text-gray-900">{fullName}</h3>
      </div>

      <div className="mb-6">
        <div className="text-xs text-gray-500 mb-1">Actionable bids closing by {windowLabel}</div>
        <Link
          to={`/portal/${id}?filter=closingactionable`}
          className={`text-2xl font-bold hover:underline ${colorClasses[color].accent}`}
        >
          {counts.closingSoonActionable}
        </Link>
        <div className="text-xs text-gray-400 mt-0.5">Accepted bids, within 10 days</div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatLink to={`/portal/${id}?filter=new`} label="New" value={counts.new} />
        <StatLink to={`/portal/${id}?filter=all`} label="Accepted" value={counts.accepted} accent />
      </div>

      <Link to={`/portal/${id}`}>
        <Button variant="outline" className="w-full mb-6">
          All Bids
        </Button>
      </Link>

      <div className="pt-6 border-t border-gray-100">
        <span className="text-xs text-gray-500 font-medium">Opportunity Distribution</span>
        <div className="grid grid-cols-3 gap-2 mt-3 mb-3">
          <FilterChipLink portalId={id} filter="score1to3" label="Score 1–3" newCount={counts.scoreBelow4New} acceptedCount={counts.scoreBelow4Accepted} colorClass="bg-gray-100 hover:bg-gray-200 text-gray-700" />
          <FilterChipLink portalId={id} filter="score4" label="Score 4" newCount={counts.scoreExact4New} acceptedCount={counts.scoreExact4Accepted} colorClass="bg-blue-50 hover:bg-blue-100 text-blue-700" />
          <FilterChipLink portalId={id} filter="score5" label="Score 5" newCount={counts.scoreExact5New} acceptedCount={counts.scoreExact5Accepted} colorClass="bg-blue-100 hover:bg-blue-200 text-blue-800" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <FilterChipLink portalId={id} filter="highpriority" label="High Priority" value={counts.highPriority} colorClass="bg-green-50 hover:bg-green-100 text-green-700" />
          <FilterChipLink portalId={id} filter="closingsoon" label="Closing Soon" value={counts.closingSoon} colorClass="bg-orange-50 hover:bg-orange-100 text-orange-700" />
        </div>
        <p className="text-xs text-gray-400 mt-2">Closing Soon = score 3–5, not rejected, within 10 days</p>
      </div>
    </div>
  );
}

function StatLink({ to, label, value, accent }: { to: string; label: string; value: number; accent?: boolean }) {
  return (
    <Link
      to={to}
      className={`border rounded-lg px-3 py-2 transition-all hover:scale-105 group ${
        accent
          ? "bg-green-50 hover:bg-green-100 border-green-200 hover:border-green-300"
          : "bg-gray-50 hover:bg-blue-50 border-gray-200 hover:border-blue-300"
      }`}
    >
      <div className={`text-2xl font-bold ${accent ? "text-green-700 group-hover:text-green-800" : "text-gray-900 group-hover:text-blue-600"}`}>
        {value.toLocaleString()}
      </div>
      <div className="text-xs text-gray-500">{label}</div>
    </Link>
  );
}

function FilterChipLink({
  portalId, filter, label, newCount, acceptedCount, colorClass,
}: {
  portalId: string; filter: BidFilter; label: string; newCount: number; acceptedCount: number; colorClass: string;
}) {
  return (
    <Link
      to={`/portal/${portalId}?filter=${filter}`}
      className={`rounded-lg px-2 py-2 transition-colors text-center border border-transparent hover:border-current ${colorClass}`}
    >
      <div className="text-xs font-semibold opacity-80 mb-1">{label}</div>
      <div className="text-sm font-bold leading-tight">{newCount.toLocaleString()} <span className="text-xs font-normal opacity-70">new</span></div>
      <div className="text-xs leading-tight mt-0.5 opacity-80">{acceptedCount.toLocaleString()} acc</div>
    </Link>
  );
}
