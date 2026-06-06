export type PortalId = "gem" | "hal" | "isro";

export interface User {
  id: number;
  email: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
  };
}

export interface PortalStats {
  portal: PortalId;
  windowDate: string;
  counts: {
    total: number;
    new: number;
    score3plus: number;
    score4plus: number;
    score5: number;
    highPriority: number;
    closingSoon: number;
    bidsClosingBy: number;
  };
}

export interface BidListItem {
  portal: PortalId;
  bidKey: string;
  bidId: string;
  title: string;
  buyer: string;
  rating: number | null;
  method: "model" | "keyword";
  eliminatedBy: string | null;
  autoRejected: boolean;
  userState: "new" | "accepted" | "rejected";
  bidStatus: "OPEN" | "EXTENDED" | "CLOSED";
  hasRestrictiveEligibility: boolean;
  summaryAvailable: boolean;
  closingDate: string | null;
  closingDateRaw: string;
}

export interface BidOverview {
  title: string | null;
  buyer: string | null;
  ministry: string | null;
  department: string | null;
  location: string | null;
  value: string | null;
  openingDateRaw: string | null;
  closingDate: string | null;
  closingDateRaw: string | null;
}

export interface BidSummary {
  available: boolean;
  status: string | null;
  markdown: string | null;
  coverage: string | null;
  unparsedDocuments: string[];
  model: string | null;
  generatedAt: string | null;
}

export interface BidDetail {
  portal: PortalId;
  bidKey: string;
  bidId: string;
  rating: number | null;
  rationale: string | null;
  method: "model" | "keyword";
  eliminatedBy: string | null;
  autoRejected: boolean;
  userState: "new" | "accepted" | "rejected";
  bidStatus: "OPEN" | "EXTENDED" | "CLOSED";
  hasRestrictiveEligibility: boolean;
  overview: BidOverview;
  summary: BidSummary;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export type BidFilter =
  | "all"
  | "new"
  | "score3plus"
  | "score4plus"
  | "score5"
  | "highpriority"
  | "closingsoon";

export interface NotificationItem {
  portal: PortalId;
  bidKey: string;
  bidId: string;
  description: string;
  matchedKeyword: string;
  closingDateRaw: string;
  firstSeen: string;
}

export interface ActivityItem {
  id: number;
  user: string;
  portal: PortalId;
  bidId: string;
  action: "accepted" | "rejected" | "disputed";
  detail: string | null;
  createdAt: string;
}
