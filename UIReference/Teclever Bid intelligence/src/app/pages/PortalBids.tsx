import { useState, useMemo, useEffect } from "react";
import { useParams, Link, useSearchParams } from "react-router";
import { Search, Filter, Star, Calendar, ArrowUpDown, ChevronRight, X } from "lucide-react";
import { mockBids, Bid } from "../lib/mockData";
import { Button } from "../components/ui/Button";
import { format } from "date-fns";

export function PortalBids() {
  const { portalId } = useParams<{ portalId: string }>();
  const [searchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState("");
  const [filterRating, setFilterRating] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterMinistry, setFilterMinistry] = useState<string>("all");
  const [filterOrganization, setFilterOrganization] = useState<string>("all");
  const [filterDepartment, setFilterDepartment] = useState<string>("all");
  const [filterLocation, setFilterLocation] = useState<string>("all");
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    const filter = searchParams.get('filter');
    if (filter) {
      switch (filter) {
        case 'new':
          setFilterStatus('new');
          break;
        case 'score3plus':
          setFilterRating('3plus');
          break;
        case 'score4plus':
          setFilterRating('high');
          break;
        case 'score5':
          setFilterRating('5');
          break;
        case 'closingsoon':
          setFilterRating('closingsoon');
          break;
        case 'highpriority':
          setFilterRating('high');
          setFilterStatus('new');
          break;
      }
    }
  }, [searchParams]);

  const portalNames = {
    gem: "GEM - Government e-Marketplace",
    hal: "HAL - Hindustan Aeronautics Limited",
    isro: "ISRO - Indian Space Research Organisation"
  };

  const portalBids = mockBids.filter(bid => bid.portalId === portalId);

  const filteredBids = useMemo(() => {
    let filtered = portalBids;

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(bid =>
        bid.description.toLowerCase().includes(query) ||
        bid.organization.toLowerCase().includes(query) ||
        bid.ministry.toLowerCase().includes(query) ||
        bid.id.toLowerCase().includes(query)
      );
    }

    if (filterRating !== "all") {
      if (filterRating === "high") {
        filtered = filtered.filter(bid => bid.aiRating >= 4);
      } else if (filterRating === "moderate") {
        filtered = filtered.filter(bid => bid.aiRating === 3);
      } else if (filterRating === "low") {
        filtered = filtered.filter(bid => bid.aiRating <= 2);
      } else if (filterRating === "3plus") {
        filtered = filtered.filter(bid => bid.aiRating >= 3);
      } else if (filterRating === "5") {
        filtered = filtered.filter(bid => bid.aiRating === 5);
      } else if (filterRating === "closingsoon") {
        const oneWeekFromNow = new Date();
        oneWeekFromNow.setDate(oneWeekFromNow.getDate() + 7);
        filtered = filtered.filter(bid => {
          const closeDate = new Date(bid.closeDate);
          return closeDate <= oneWeekFromNow && closeDate >= new Date();
        });
      }
    }

    if (filterStatus !== "all") {
      filtered = filtered.filter(bid => bid.status === filterStatus);
    }

    if (filterMinistry !== "all") {
      filtered = filtered.filter(bid => bid.ministry === filterMinistry);
    }

    if (filterOrganization !== "all") {
      filtered = filtered.filter(bid => bid.organization === filterOrganization);
    }

    if (filterDepartment !== "all") {
      filtered = filtered.filter(bid => bid.department === filterDepartment);
    }

    if (filterLocation !== "all") {
      filtered = filtered.filter(bid => bid.location === filterLocation);
    }

    return filtered.sort((a, b) => b.aiRating - a.aiRating);
  }, [portalBids, searchQuery, filterRating, filterStatus, filterMinistry, filterOrganization, filterDepartment, filterLocation]);

  const getActiveFilters = () => {
    const filters = [];

    if (searchQuery) {
      filters.push({ type: 'search', label: `Search: "${searchQuery}"`, value: searchQuery });
    }

    if (filterRating !== 'all') {
      const ratingLabels: Record<string, string> = {
        '5': 'Score 5',
        'high': 'Score 4+',
        '3plus': 'Score 3+',
        'moderate': 'Score 3',
        'low': 'Score 0-2',
        'closingsoon': 'Closing Soon'
      };
      filters.push({ type: 'rating', label: ratingLabels[filterRating] || filterRating, value: filterRating });
    }

    if (filterStatus !== 'all') {
      const statusLabels: Record<string, string> = {
        'new': 'New Bids',
        'accepted': 'Accepted',
        'rejected': 'Rejected'
      };
      filters.push({ type: 'status', label: statusLabels[filterStatus], value: filterStatus });
    }

    if (filterMinistry !== 'all') {
      filters.push({ type: 'ministry', label: `Ministry: ${filterMinistry}`, value: filterMinistry });
    }

    if (filterOrganization !== 'all') {
      filters.push({ type: 'organization', label: `Org: ${filterOrganization}`, value: filterOrganization });
    }

    if (filterDepartment !== 'all') {
      filters.push({ type: 'department', label: `Dept: ${filterDepartment}`, value: filterDepartment });
    }

    if (filterLocation !== 'all') {
      filters.push({ type: 'location', label: `Location: ${filterLocation}`, value: filterLocation });
    }

    return filters;
  };

  const activeFilters = getActiveFilters();

  const removeFilter = (filterType: string) => {
    switch (filterType) {
      case 'search':
        setSearchQuery('');
        break;
      case 'rating':
        setFilterRating('all');
        break;
      case 'status':
        setFilterStatus('all');
        break;
      case 'ministry':
        setFilterMinistry('all');
        break;
      case 'organization':
        setFilterOrganization('all');
        break;
      case 'department':
        setFilterDepartment('all');
        break;
      case 'location':
        setFilterLocation('all');
        break;
    }
  };

  const clearAllFilters = () => {
    setSearchQuery('');
    setFilterRating('all');
    setFilterStatus('all');
    setFilterMinistry('all');
    setFilterOrganization('all');
    setFilterDepartment('all');
    setFilterLocation('all');
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-3xl font-bold text-gray-900">
            {portalNames[portalId as keyof typeof portalNames] || "Portal Bids"}
          </h1>
        </div>
        <p className="text-gray-600">{filteredBids.length} opportunities found</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search bids by description, organization, ministry..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <Button
            variant="secondary"
            onClick={() => setShowFilters(!showFilters)}
            className="gap-2"
          >
            <Filter className="w-4 h-4" />
            Filters
          </Button>
        </div>

        {activeFilters.length > 0 && (
          <div className="flex items-center justify-between gap-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              {activeFilters.map((filter, idx) => (
                <div
                  key={idx}
                  className="inline-flex items-center gap-1.5 bg-blue-50 border border-blue-200 rounded-md px-2.5 py-1 text-xs"
                >
                  <span className="text-blue-900 font-medium">{filter.label}</span>
                  <button
                    onClick={() => removeFilter(filter.type)}
                    className="text-blue-600 hover:text-blue-800 hover:bg-blue-100 rounded-full p-0.5 transition-colors"
                    aria-label="Remove filter"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={clearAllFilters}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
            >
              Clear All
            </button>
          </div>
        )}

        {showFilters && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">AI Rating</label>
                <select
                  value={filterRating}
                  onChange={(e) => setFilterRating(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Ratings</option>
                  <option value="5">Score 5</option>
                  <option value="high">Score 4+</option>
                  <option value="3plus">Score 3+</option>
                  <option value="moderate">Score 3 (Moderate)</option>
                  <option value="low">Score 0-2 (Low)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
                <select
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Status</option>
                  <option value="new">New Bids</option>
                  <option value="accepted">Accepted</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Ministry</label>
                <select
                  value={filterMinistry}
                  onChange={(e) => setFilterMinistry(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Ministries</option>
                  {Array.from(new Set(mockBids.filter(b => b.portalId === portalId).map(b => b.ministry))).map(ministry => (
                    <option key={ministry} value={ministry}>{ministry}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Organization</label>
                <select
                  value={filterOrganization}
                  onChange={(e) => setFilterOrganization(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Organizations</option>
                  {Array.from(new Set(mockBids.filter(b => b.portalId === portalId).map(b => b.organization))).map(org => (
                    <option key={org} value={org}>{org}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Department</label>
                <select
                  value={filterDepartment}
                  onChange={(e) => setFilterDepartment(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Departments</option>
                  {Array.from(new Set(mockBids.filter(b => b.portalId === portalId).map(b => b.department))).map(dept => (
                    <option key={dept} value={dept}>{dept}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Location</label>
                <select
                  value={filterLocation}
                  onChange={(e) => setFilterLocation(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Locations</option>
                  {Array.from(new Set(mockBids.filter(b => b.portalId === portalId).map(b => b.location))).map(loc => (
                    <option key={loc} value={loc}>{loc}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="pt-3 border-t border-gray-200">
              <label className="block text-sm font-medium text-gray-700 mb-2">Quick Filters</label>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => {
                    setFilterRating("all");
                    setFilterStatus("all");
                  }}
                  className="px-3 py-1.5 text-xs bg-blue-100 text-blue-700 rounded-lg hover:bg-blue-200 transition-colors"
                >
                  Total Bids
                </button>
                <button
                  onClick={() => {
                    setFilterRating("all");
                    setFilterStatus("new");
                  }}
                  className="px-3 py-1.5 text-xs bg-purple-100 text-purple-700 rounded-lg hover:bg-purple-200 transition-colors"
                >
                  New Bids
                </button>
                <button
                  onClick={() => {
                    setFilterRating("3plus");
                    setFilterStatus("all");
                  }}
                  className="px-3 py-1.5 text-xs bg-green-100 text-green-700 rounded-lg hover:bg-green-200 transition-colors"
                >
                  Score 3+
                </button>
                <button
                  onClick={() => {
                    setFilterRating("high");
                    setFilterStatus("all");
                  }}
                  className="px-3 py-1.5 text-xs bg-yellow-100 text-yellow-700 rounded-lg hover:bg-yellow-200 transition-colors"
                >
                  Score 4+
                </button>
                <button
                  onClick={() => {
                    setFilterRating("5");
                    setFilterStatus("all");
                  }}
                  className="px-3 py-1.5 text-xs bg-amber-100 text-amber-700 rounded-lg hover:bg-amber-200 transition-colors"
                >
                  Score 5
                </button>
                <button
                  onClick={() => {
                    setFilterRating("closingsoon");
                    setFilterStatus("all");
                  }}
                  className="px-3 py-1.5 text-xs bg-orange-100 text-orange-700 rounded-lg hover:bg-orange-200 transition-colors"
                >
                  Closing Soon
                </button>
                <button
                  onClick={() => {
                    setFilterRating("high");
                    setFilterStatus("new");
                  }}
                  className="px-3 py-1.5 text-xs bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors"
                >
                  High Priority
                </button>
                <button
                  onClick={clearAllFilters}
                  className="px-3 py-1.5 text-xs bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  Clear All
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="hidden lg:block bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Bid ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Organization</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Description</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Close Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">AI Rating</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filteredBids.map((bid) => (
                <BidTableRow key={bid.id} bid={bid} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="lg:hidden space-y-4">
        {filteredBids.map((bid) => (
          <BidCard key={bid.id} bid={bid} />
        ))}
      </div>
    </div>
  );
}

function BidTableRow({ bid }: { bid: Bid }) {
  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-4">
        <Link to={`/bid/${bid.id}`} className="text-blue-600 hover:text-blue-800 font-medium">
          {bid.id}
        </Link>
      </td>
      <td className="px-4 py-4">
        <div className="text-sm font-medium text-gray-900">{bid.organization}</div>
        <div className="text-xs text-gray-500">{bid.ministry}</div>
      </td>
      <td className="px-4 py-4">
        <div className="text-sm text-gray-900 line-clamp-2 max-w-md">{bid.description}</div>
      </td>
      <td className="px-4 py-4">
        <div className="text-sm text-gray-900">{format(new Date(bid.closeDate), 'MMM dd, yyyy')}</div>
      </td>
      <td className="px-4 py-4">
        <div className="flex items-center gap-1">
          <Star className={`w-4 h-4 ${bid.aiRating >= 4 ? 'text-yellow-500 fill-yellow-500' : 'text-gray-300'}`} />
          <span className={`font-semibold ${
            bid.aiRating >= 4 ? 'text-yellow-700' :
            bid.aiRating === 3 ? 'text-blue-700' :
            'text-gray-500'
          }`}>
            {bid.aiRating}/5
          </span>
        </div>
      </td>
      <td className="px-4 py-4">
        <StatusBadge status={bid.status} />
      </td>
      <td className="px-4 py-4">
        <Link to={`/bid/${bid.id}`}>
          <ChevronRight className="w-5 h-5 text-gray-400" />
        </Link>
      </td>
    </tr>
  );
}

function BidCard({ bid }: { bid: Bid }) {
  return (
    <Link
      to={`/bid/${bid.id}`}
      className="block bg-white rounded-xl border border-gray-200 p-4 hover:shadow-lg transition-shadow"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-blue-600 font-semibold mb-1">{bid.id}</div>
          <div className="text-sm text-gray-900 font-medium">{bid.organization}</div>
        </div>
        <StatusBadge status={bid.status} />
      </div>
      <p className="text-sm text-gray-600 line-clamp-2 mb-3">{bid.description}</p>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <Star className={`w-4 h-4 ${bid.aiRating >= 4 ? 'text-yellow-500 fill-yellow-500' : 'text-gray-300'}`} />
          <span className={`text-sm font-semibold ${
            bid.aiRating >= 4 ? 'text-yellow-700' :
            bid.aiRating === 3 ? 'text-blue-700' :
            'text-gray-500'
          }`}>
            {bid.aiRating}/5
          </span>
        </div>
        <div className="flex items-center gap-1 text-sm text-gray-500">
          <Calendar className="w-4 h-4" />
          {format(new Date(bid.closeDate), 'MMM dd')}
        </div>
      </div>
    </Link>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles = {
    new: 'bg-blue-100 text-blue-700',
    accepted: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700'
  };

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[status as keyof typeof styles]}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}
