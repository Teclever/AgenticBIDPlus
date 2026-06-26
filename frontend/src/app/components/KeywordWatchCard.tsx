import { Link } from "react-router";
import { Radar } from "lucide-react";
import type { KeywordWatchStats } from "../lib/types";
import { formatWindowDate } from "../lib/format";

/**
 * Dashboard "Keyword Watch" card — a 5th card below the portal grid showing GeM bids found via
 * the org-agnostic keyword-discovery channel (orgs we don't actively monitor). The Part-B
 * score-4 floor guarantees nothing below 4, so each watch family shows only Score 5 / Score 4.
 * Every count deep-links into the GeM list filtered to keyword finds (and family / score).
 */
export function KeywordWatchCard({ stats }: { stats: KeywordWatchStats }) {
  const { categories, counts } = stats;
  const windowLabel = formatWindowDate(stats.windowDate);
  const base = "/portal/gem?discoverySource=keyword";

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-lg transition-shadow">
      <div className="flex items-center gap-2 mb-4">
        <div className="p-2 rounded-lg text-cyan-600 bg-cyan-100">
          <Radar className="w-8 h-8" />
        </div>
        <div>
          <span className="text-sm font-medium text-gray-600">Keyword Watch</span>
          <p className="text-xs text-gray-400">Cross-portal discovery · organisations we don't monitor</p>
        </div>
      </div>

      <div className="mb-6">
        <div className="text-xs text-gray-500 mb-1">Actionable bids closing by {windowLabel}</div>
        <Link
          to={`${base}&filter=closingactionable`}
          className="text-2xl font-bold text-cyan-600 hover:underline"
        >
          {counts.closingSoonActionable}
        </Link>
        <div className="text-xs text-gray-400 mt-0.5">Accepted keyword finds, within 10 days</div>
      </div>

      <div className="space-y-4 pt-2 border-t border-gray-100">
        {categories.map((cat) => (
          <div key={cat.id}>
            <div className="text-xs font-semibold text-gray-600 mb-2">{cat.label}</div>
            <div className="grid grid-cols-2 gap-2">
              <ScoreChip
                to={`${base}&discoveryCategory=${cat.id}&filter=score5`}
                label="Score 5"
                newCount={cat.score5New}
                acceptedCount={cat.score5Accepted}
                colorClass="bg-blue-100 hover:bg-blue-200 text-blue-800"
              />
              <ScoreChip
                to={`${base}&discoveryCategory=${cat.id}&filter=score4`}
                label="Score 4"
                newCount={cat.score4New}
                acceptedCount={cat.score4Accepted}
                colorClass="bg-blue-50 hover:bg-blue-100 text-blue-700"
              />
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2 mt-5 pt-4 border-t border-gray-100">
        <CountChip
          to={`${base}&filter=closingsoon`}
          label="Closing Soon"
          value={counts.closingSoon}
          colorClass="bg-orange-50 hover:bg-orange-100 text-orange-700"
        />
        <CountChip
          to={`${base}&status=accepted`}
          label="Accepted"
          value={counts.accepted}
          colorClass="bg-green-50 hover:bg-green-100 text-green-700"
        />
      </div>
    </div>
  );
}

function ScoreChip({
  to, label, newCount, acceptedCount, colorClass,
}: {
  to: string; label: string; newCount: number; acceptedCount: number; colorClass: string;
}) {
  return (
    <Link
      to={to}
      className={`rounded-lg px-2 py-2 transition-colors text-center border border-transparent hover:border-current ${colorClass}`}
    >
      <div className="text-xs font-semibold opacity-80 mb-1">{label}</div>
      <div className="text-sm font-bold leading-tight">
        {(newCount ?? 0).toLocaleString()} <span className="text-xs font-normal opacity-70">new</span>
      </div>
      <div className="text-xs leading-tight mt-0.5 opacity-80">{(acceptedCount ?? 0).toLocaleString()} acc</div>
    </Link>
  );
}

function CountChip({
  to, label, value, colorClass,
}: {
  to: string; label: string; value: number; colorClass: string;
}) {
  return (
    <Link
      to={to}
      className={`rounded-lg px-2 py-2 transition-colors text-center border border-transparent hover:border-current ${colorClass}`}
    >
      <div className="text-xs font-semibold opacity-80 mb-1">{label}</div>
      <div className="text-base font-bold leading-tight py-0.5">{(value ?? 0).toLocaleString()}</div>
    </Link>
  );
}
