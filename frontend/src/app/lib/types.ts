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
    accepted: number;
    scoreBelow4New: number;
    scoreBelow4Accepted: number;
    scoreExact4New: number;
    scoreExact4Accepted: number;
    scoreExact5New: number;
    scoreExact5Accepted: number;
    highPriority: number;
    closingSoon: number;
    closingSoonActionable: number;
    singleTender: number;
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
  isSingleTender: boolean;
  singleTenderOrg: string | null;
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

export interface T1aFlag {
  tier: "T1a";
  label: string;
  clause: string;
}

export interface T1bFlag {
  tier: "T1b";
  label: string;
  models: string;
}

export interface T2Flag {
  tier: "T2";
  label: string;
}

export type CriticalFlag = T1aFlag | T1bFlag | T2Flag;

export interface BidSummary {
  available: boolean;
  status: string | null;
  markdown: string | null;
  coverage: string | null;
  unparsedDocuments: string[];
  criticalFlags: CriticalFlag[];
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
  isSingleTender: boolean;
  singleTenderOrg: string | null;
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
  | "filtered"
  | "score1to3"
  | "score4"
  | "score5"
  | "highpriority"
  | "closingsoon"
  | "closingactionable"
  | "singletender";

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
  bidKey: string;
  action: "accepted" | "rejected" | "disputed" | "reset";
  detail: string | null;
  createdAt: string;
}

export type AlertStatus = "active" | "retry_failed" | "cleared";

export interface PortalRunSummary {
  portal: string;
  status: string;
  newCount: number;
  scoredCount: number;
  keywordScoredCount: number;
  modelScoredCount: number;
  summarizedCount: number;
  errorSummary: string | null;
}

export interface ScrapeRun {
  id: number;
  startedAt: string;
  finishedAt: string | null;
  status: string;
  newCount: number;
  updatedCount: number;
  closedCount: number;
  scoredCount: number;
  summarizedCount: number;
  localExtractedCount: number;
  summaryFailedCount: number;
  errorSummary: string | null;
  portals: PortalRunSummary[];
}

export interface DocumentItem {
  filename: string;
  sizeKb: number;
}

export interface SystemAlert {
  id: number;
  alertType: string;
  portal: string | null;
  bidRefs: string[];
  reason: string;
  status: AlertStatus;
  retryCount: number;
  raisedAt: string;
  clearedAt: string | null;
  lastRetryAt: string | null;
  lastRetryError: string | null;
}
