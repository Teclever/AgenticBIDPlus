import { useEffect, useState } from "react";
import { CheckCircle, XCircle, User, FileText, Building, MessageSquare } from "lucide-react";
import { activityApi } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { ActivityItem } from "../lib/types";

export function ActivityLog() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    activityApi
      .list()
      .then((data) => setItems(data.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-gray-500">Loading activity…</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Activity Log</h1>
        <p className="text-gray-600 mt-1">Track all bid decisions and actions taken by the team</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">User</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Bid ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Portal</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Action</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Date & Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {items.map((activity) => (
                <ActivityRow key={activity.id} activity={activity} />
              ))}
            </tbody>
          </table>
        </div>

        <div className="md:hidden divide-y divide-gray-200">
          {items.map((activity) => (
            <ActivityCard key={activity.id} activity={activity} />
          ))}
        </div>
      </div>

      {items.length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <FileText className="w-8 h-8 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No activity yet</h3>
          <p className="text-gray-600">Activity will appear here when team members accept or reject bids</p>
        </div>
      )}
    </div>
  );
}

function ActivityRow({ activity }: { activity: ActivityItem }) {
  const { date, time } = formatDateTime(activity.createdAt);
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
            <User className="w-4 h-4 text-blue-600" />
          </div>
          <span className="text-sm font-medium text-gray-900">{activity.user}</span>
        </div>
      </td>
      <td className="px-6 py-4">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-blue-600 font-medium">{activity.bidId}</span>
        </div>
      </td>
      <td className="px-6 py-4">
        <div className="flex items-center gap-2">
          <Building className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-gray-900 uppercase">{activity.portal}</span>
        </div>
      </td>
      <td className="px-6 py-4">
        <ActionBadge action={activity.action} detail={activity.detail} />
      </td>
      <td className="px-6 py-4">
        <div className="text-sm text-gray-900">{date}</div>
        <div className="text-xs text-gray-500">{time}</div>
      </td>
    </tr>
  );
}

function ActivityCard({ activity }: { activity: ActivityItem }) {
  const { date, time } = formatDateTime(activity.createdAt);
  return (
    <div className="p-4">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">
            <User className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <div className="font-medium text-gray-900">{activity.user}</div>
            <div className="text-sm text-gray-500">{date} · {time}</div>
          </div>
        </div>
        <ActionBadge action={activity.action} detail={activity.detail} />
      </div>
      <div className="ml-13 space-y-1">
        <div className="flex items-center gap-2 text-sm">
          <FileText className="w-4 h-4 text-gray-400" />
          <span className="text-blue-600 font-medium">{activity.bidId}</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Building className="w-4 h-4 text-gray-400" />
          <span className="uppercase">{activity.portal}</span>
        </div>
      </div>
    </div>
  );
}

function ActionBadge({ action, detail }: { action: string; detail: string | null }) {
  if (action === "accepted") {
    return (
      <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
        <CheckCircle className="w-3 h-3" />
        Accepted
      </span>
    );
  }
  if (action === "disputed") {
    return (
      <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800" title={detail ?? undefined}>
        <MessageSquare className="w-3 h-3" />
        Disputed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700">
      <XCircle className="w-3 h-3" />
      Rejected
    </span>
  );
}
