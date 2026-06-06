import type {
  ActivityItem,
  ApiError,
  BidDetail,
  BidFilter,
  BidListItem,
  NotificationItem,
  Paginated,
  PortalId,
  PortalStats,
  User,
} from "./types";

// Empty = same-origin (FastAPI on :8000, or Vite dev proxy on :5173/:5174).
// Only set VITE_API_BASE when the API is on a different explicit host.
const API_BASE =
  import.meta.env.VITE_API_BASE && import.meta.env.VITE_API_BASE.length > 0
    ? import.meta.env.VITE_API_BASE
    : "";

let redirectingToLogin = false;

function redirectToLogin() {
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  const onLogin = window.location.pathname === "/login";
  if (!onLogin) {
    window.location.href = "/login";
  }
  setTimeout(() => {
    redirectingToLogin = false;
  }, 100);
}

export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(res: Response): Promise<ApiRequestError> {
  try {
    const body = (await res.json()) as ApiError;
    return new ApiRequestError(
      res.status,
      body.error?.code ?? "unknown",
      body.error?.message ?? res.statusText,
    );
  } catch {
    return new ApiRequestError(res.status, "unknown", res.statusText);
  }
}

export function isAuthError(status: number, code: string): boolean {
  return status === 401 || code === "unauthenticated" || code === "invalid_credentials";
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { skipAuthRedirect?: boolean },
): Promise<T> {
  const { skipAuthRedirect, ...fetchInit } = init ?? {};
  const url = `${API_BASE}${path}`;
  const headers = new Headers(fetchInit.headers);
  if (fetchInit.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, {
    ...fetchInit,
    credentials: "include",
    headers,
  });

  if (!res.ok) {
    const err = await parseError(res);
    if (!skipAuthRedirect && isAuthError(err.status, err.code)) {
      redirectToLogin();
    }
    throw err;
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export const authApi = {
  me: () => apiFetch<User>("/api/auth/me"),
  login: (email: string, password: string, rememberMe: boolean) =>
    apiFetch<{ user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, rememberMe }),
      skipAuthRedirect: true,
    }),
  logout: () =>
    apiFetch<void>("/api/auth/logout", { method: "POST" }),
};

export const portalApi = {
  stats: (portal: PortalId) =>
    apiFetch<PortalStats>(`/api/portals/${portal}/stats`),
  bids: (
    portal: PortalId,
    params: {
      page?: number;
      pageSize?: number;
      search?: string;
      filter?: BidFilter;
      status?: string;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    qs.set("page", String(params.page ?? 1));
    qs.set("pageSize", String(params.pageSize ?? 50));
    if (params.search) qs.set("search", params.search);
    if (params.filter && params.filter !== "all") qs.set("filter", params.filter);
    if (params.status && params.status !== "all") qs.set("status", params.status);
    const query = qs.toString();
    return apiFetch<Paginated<BidListItem>>(
      `/api/portals/${portal}/bids${query ? `?${query}` : ""}`,
    );
  },
  bidDetail: (portal: PortalId, bidKey: string) =>
    apiFetch<BidDetail>(
      `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}`,
    ),
  generateSummary: (portal: PortalId, bidKey: string) =>
    apiFetch<{ summary: BidDetail["summary"] }>(
      `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/generate-summary`,
      { method: "POST" },
    ),
  disposition: (portal: PortalId, bidKey: string, action: "accepted" | "rejected") =>
    apiFetch<{ userState: string }>(
      `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/disposition`,
      { method: "POST", body: JSON.stringify({ action }) },
    ),
};

export const notificationsApi = {
  list: () =>
    apiFetch<{ items: NotificationItem[]; total: number }>(
      "/api/notifications/auto-filtered",
    ),
  count: () =>
    apiFetch<{ count: number }>("/api/notifications/auto-filtered/count"),
  viewed: () =>
    apiFetch<void>("/api/notifications/auto-filtered/viewed", { method: "POST" }),
  saveAll: () =>
    apiFetch<{ accepted: number }>(
      "/api/notifications/auto-filtered/save-all",
      { method: "POST" },
    ),
  dispute: (portal: PortalId, bidKey: string, reason: string) =>
    apiFetch<{ disputed: boolean }>(
      `/api/notifications/auto-filtered/${portal}/${encodeURIComponent(bidKey)}/dispute`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
};

export const activityApi = {
  list: (page = 1, pageSize = 50) =>
    apiFetch<Paginated<ActivityItem>>(
      `/api/activity?page=${page}&pageSize=${pageSize}`,
    ),
};
