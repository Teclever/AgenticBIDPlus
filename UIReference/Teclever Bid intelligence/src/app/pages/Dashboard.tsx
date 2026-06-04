import { useEffect } from "react";
import { useNavigate, Link } from "react-router";
import {
  Building,
  Rocket,
  Plane,
  TrendingUp
} from "lucide-react";
import { mockBids } from "../lib/mockData";

export function Dashboard() {
  const navigate = useNavigate();

  useEffect(() => {
    const isAuthenticated = localStorage.getItem('isAuthenticated');
    if (!isAuthenticated) {
      navigate('/login');
    }
  }, [navigate]);

  const getPortalStats = (portalId: string) => {
    const portalBids = mockBids.filter(b => b.portalId === portalId);
    const oneWeekFromNow = new Date();
    oneWeekFromNow.setDate(oneWeekFromNow.getDate() + 7);

    const highPriorityBids = portalBids.filter(b => b.aiRating >= 4 && b.status === 'new');
    const highPriorityClosingSoon = highPriorityBids.filter(b => {
      const closeDate = new Date(b.closeDate);
      return closeDate <= oneWeekFromNow && closeDate >= new Date();
    }).length;

    return {
      total: portalBids.length,
      new: portalBids.filter(b => b.status === 'new').length,
      score3Plus: portalBids.filter(b => b.aiRating >= 3).length,
      score4Plus: portalBids.filter(b => b.aiRating >= 4).length,
      score5: portalBids.filter(b => b.aiRating === 5).length,
      closingSoon: portalBids.filter(b => {
        const closeDate = new Date(b.closeDate);
        return closeDate <= oneWeekFromNow && closeDate >= new Date();
      }).length,
      highPriority: highPriorityBids.length,
      highPriorityClosingSoon: highPriorityClosingSoon
    };
  };

  const gemStats = getPortalStats('gem');
  const halStats = getPortalStats('hal');
  const isroStats = getPortalStats('isro');

  // Calculate global maximum for consistent bar heights across all portals
  const allStats = [gemStats, halStats, isroStats];
  const globalMax = Math.max(
    ...allStats.flatMap(s => [s.score3Plus, s.score4Plus, s.score5, s.highPriority, s.closingSoon])
  );

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Procurement Portals</h1>
        <p className="text-gray-600 mt-1">AI-powered bid intelligence and opportunity tracking</p>
      </div>

      <div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <PortalCard
            icon={<Building className="w-8 h-8" />}
            name="GEM"
            fullName="Government e-Marketplace"
            stats={gemStats}
            portalId="gem"
            color="blue"
            globalMax={globalMax}
          />
          <PortalCard
            icon={<Plane className="w-8 h-8" />}
            name="HAL"
            fullName="Hindustan Aeronautics Limited"
            stats={halStats}
            portalId="hal"
            color="indigo"
            globalMax={globalMax}
          />
          <PortalCard
            icon={<Rocket className="w-8 h-8" />}
            name="ISRO"
            fullName="Indian Space Research Organisation"
            stats={isroStats}
            portalId="isro"
            color="purple"
            globalMax={globalMax}
          />
        </div>
      </div>
    </div>
  );
}

interface PortalStats {
  total: number;
  new: number;
  score3Plus: number;
  score4Plus: number;
  score5: number;
  closingSoon: number;
  highPriority: number;
  highPriorityClosingSoon: number;
}

interface PortalCardProps {
  icon: React.ReactNode;
  name: string;
  fullName: string;
  stats: PortalStats;
  portalId: string;
  color: 'blue' | 'indigo' | 'purple';
  globalMax: number;
}

function PortalCard({ icon, name, fullName, stats, portalId, color, globalMax }: PortalCardProps) {
  const colorClasses = {
    blue: { icon: 'text-blue-600 bg-blue-100', accent: 'text-blue-600' },
    indigo: { icon: 'text-indigo-600 bg-indigo-100', accent: 'text-indigo-600' },
    purple: { icon: 'text-purple-600 bg-purple-100', accent: 'text-purple-600' },
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-lg transition-shadow">
      <div className="flex items-center gap-2 mb-4">
        <div className={`p-2 rounded-lg ${colorClasses[color].icon}`}>
          {icon}
        </div>
        <span className="text-sm font-medium text-gray-600">{name}</span>
      </div>

      <div className="h-16 flex items-start">
        <h3 className="text-xl font-bold text-gray-900">{fullName}</h3>
      </div>

      <div className="mb-6">
        <div className="text-xs text-gray-500 mb-1">High Priority</div>
        <div className="flex items-baseline gap-2">
          <span className={`text-2xl font-bold ${colorClasses[color].accent}`}>
            {stats.highPriority}
          </span>
          <span className="text-sm text-gray-500">
            ({stats.highPriorityClosingSoon} CLOSING SOON)
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <StatLink
          to={`/portal/${portalId}?filter=all`}
          label="Total Bids"
          value={stats.total}
        />
        <StatLink
          to={`/portal/${portalId}?filter=new`}
          label="New Bids"
          value={stats.new}
        />
      </div>

      <div className="pt-6 mt-6 border-t border-gray-100">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-gray-500">Opportunity Distribution</span>
        </div>
        <div className="h-16 flex items-end gap-1 mb-6 mt-10">
          <Link
            to={`/portal/${portalId}?filter=score3plus`}
            className="flex-1 bg-gray-200 hover:bg-blue-200 rounded-t transition-colors group relative"
            style={{ height: `${globalMax > 0 ? Math.max((stats.score3Plus / globalMax) * 100, 5) : 5}%` }}
          >
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-xs font-medium text-gray-700 whitespace-nowrap">
              {stats.score3Plus}
            </div>
          </Link>
          <Link
            to={`/portal/${portalId}?filter=score4plus`}
            className="flex-1 bg-blue-300 hover:bg-blue-400 rounded-t transition-colors group relative"
            style={{ height: `${globalMax > 0 ? Math.max((stats.score4Plus / globalMax) * 100, 5) : 5}%` }}
          >
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-xs font-medium text-gray-700 whitespace-nowrap">
              {stats.score4Plus}
            </div>
          </Link>
          <Link
            to={`/portal/${portalId}?filter=score5`}
            className="flex-1 bg-blue-500 hover:bg-blue-600 rounded-t transition-colors group relative"
            style={{ height: `${globalMax > 0 ? Math.max((stats.score5 / globalMax) * 100, 5) : 5}%` }}
          >
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-xs font-medium text-white whitespace-nowrap">
              {stats.score5}
            </div>
          </Link>
          <Link
            to={`/portal/${portalId}?filter=highpriority`}
            className="flex-1 bg-green-400 hover:bg-green-500 rounded-t transition-colors group relative"
            style={{ height: `${globalMax > 0 ? Math.max((stats.highPriority / globalMax) * 100, 5) : 5}%` }}
          >
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-xs font-medium text-gray-700 whitespace-nowrap">
              {stats.highPriority}
            </div>
          </Link>
          <Link
            to={`/portal/${portalId}?filter=closingsoon`}
            className="flex-1 bg-orange-400 hover:bg-orange-500 rounded-t transition-colors group relative"
            style={{ height: `${globalMax > 0 ? Math.max((stats.closingSoon / globalMax) * 100, 5) : 5}%` }}
          >
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-xs font-medium text-gray-700 whitespace-nowrap">
              {stats.closingSoon}
            </div>
          </Link>
        </div>
        <div className="flex justify-between text-xs text-gray-400">
          <span>3+</span>
          <span>4+</span>
          <span>5</span>
          <span title="High Priority">HP</span>
          <span title="Closing Soon">CS</span>
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-2 pt-2 border-t border-gray-100">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 bg-green-400 rounded-full"></span>
            HP = High Priority
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 bg-orange-400 rounded-full"></span>
            CS = Closing Soon
          </span>
        </div>
      </div>
    </div>
  );
}

function StatLink({ to, label, value }: { to: string; label: string; value: number }) {
  return (
    <Link
      to={to}
      className="bg-gray-50 hover:bg-blue-50 border border-gray-200 hover:border-blue-300 rounded-lg px-3 py-2 transition-all hover:scale-105 group"
    >
      <div className="text-2xl font-bold text-gray-900 group-hover:text-blue-600">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </Link>
  );
}
