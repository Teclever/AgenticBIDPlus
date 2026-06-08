import { http, HttpResponse, delay } from "msw";
import authMe from "./fixtures/auth-me.json";
import gemStats from "./fixtures/portal-gem-stats.json";
import gemBids from "./fixtures/portal-gem-bids.json";
import bidDetailScore5 from "./fixtures/bid-detail-score5.json";
import bidDetailFiltered from "./fixtures/bid-detail-filtered.json";
import notificationsFixture from "./fixtures/notifications.json";
import activityFixture from "./fixtures/activity.json";
import type { BidDetail, BidListItem, NotificationItem } from "../app/lib/types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

let sessionUser: { id: number; email: string } | null = null;
let notificationItems: NotificationItem[] = [...notificationsFixture.items];
let generatedSummaries = new Map<string, BidDetail["summary"]>();

function jsonError(status: number, code: string, message: string) {
  return HttpResponse.json({ error: { code, message } }, { status });
}

function halStats() {
  return {
    portal: "hal",
    windowDate: gemStats.windowDate,
    counts: {
      total: 139,
      new: 28,
      scoreBelow4: 19,
      scoreExact4: 10,
      scoreExact5: 8,
      highPriority: 14,
      closingSoon: 6,
      closingSoonActionable: 5,
    },
  };
}

function isroStats() {
  return {
    portal: "isro",
    windowDate: gemStats.windowDate,
    counts: {
      total: 155,
      new: 32,
      scoreBelow4: 23,
      scoreExact4: 11,
      scoreExact5: 9,
      highPriority: 16,
      closingSoon: 7,
      closingSoonActionable: 6,
    },
  };
}

function filterBids(
  items: BidListItem[],
  filter: string | null,
  status: string | null,
  search: string | null,
): BidListItem[] {
  let result = [...items];

  if (search) {
    const q = search.toLowerCase();
    result = result.filter(
      (b) =>
        b.title.toLowerCase().includes(q) ||
        b.buyer.toLowerCase().includes(q) ||
        b.bidId.toLowerCase().includes(q),
    );
  }

  if (status) {
    result = result.filter((b) => b.userState === status);
  }

  switch (filter) {
    case "new":
      result = result.filter((b) => b.userState === "new");
      break;
    case "score1to3":
      result = result.filter((b) => { const r = b.rating ?? -1; return r >= 1 && r <= 3; });
      break;
    case "score4":
      result = result.filter((b) => b.rating === 4);
      break;
    case "score5":
      result = result.filter((b) => b.rating === 5);
      break;
    case "highpriority":
      // accepted, closing within 10 days
      result = result.filter((b) => b.userState === "accepted");
      break;
    case "closingsoon":
      // score 3–5, not rejected, closing within 10 days
      result = result.filter((b) => (b.rating ?? -1) >= 3 && b.userState !== "rejected");
      break;
    case "closingactionable":
      // score 5 OR accepted, closing within 10 days
      result = result.filter((b) => b.rating === 5 || b.userState === "accepted");
      break;
  }

  return result.sort((a, b) => (b.rating ?? -1) - (a.rating ?? -1));
}

function getBidDetail(bidKey: string): BidDetail | null {
  const decoded = decodeURIComponent(bidKey);
  if (decoded === bidDetailScore5.bidKey) {
    const generated = generatedSummaries.get(decoded);
    return generated
      ? { ...bidDetailScore5, summary: generated }
      : (bidDetailScore5 as BidDetail);
  }
  if (decoded === bidDetailFiltered.bidKey) {
    return bidDetailFiltered as BidDetail;
  }
  const listItem = gemBids.items.find((b) => b.bidKey === decoded);
  if (!listItem) return null;

  return {
    portal: listItem.portal,
    bidKey: listItem.bidKey,
    bidId: listItem.bidId,
    rating: listItem.rating,
    rationale:
      listItem.method === "keyword"
        ? null
        : "Moderate relevance based on title and buyer context.",
    method: listItem.method,
    eliminatedBy: listItem.eliminatedBy,
    autoRejected: listItem.autoRejected,
    userState: listItem.userState,
    bidStatus: listItem.bidStatus,
    hasRestrictiveEligibility: listItem.hasRestrictiveEligibility,
    overview: {
      title: listItem.title,
      buyer: listItem.buyer,
      ministry: "Department of Space",
      department: null,
      location: null,
      value: null,
      openingDateRaw: null,
      closingDate: listItem.closingDate,
      closingDateRaw: listItem.closingDateRaw,
    },
    summary: {
      available: listItem.summaryAvailable,
      status: listItem.summaryAvailable ? "ok" : null,
      markdown: listItem.summaryAvailable
        ? (bidDetailScore5.summary.markdown as string)
        : null,
      coverage: listItem.summaryAvailable ? "full" : null,
      unparsedDocuments: [],
      model: listItem.summaryAvailable ? "claude-sonnet-4-6" : null,
      generatedAt: listItem.summaryAvailable ? "2026-06-06T04:12:00Z" : null,
    },
  };
}

export const handlers = [
  http.post(`${API_BASE}/api/auth/login`, async ({ request }) => {
    const body = (await request.json()) as {
      email: string;
      password: string;
    };
    if (!body.email?.endsWith("@teclever.com")) {
      return jsonError(422, "non_teclever_email", "Email must be on the teclever domain");
    }
    if (!body.password) {
      return jsonError(401, "invalid_credentials", "Invalid credentials");
    }
    sessionUser = { id: 1, email: body.email };
    return HttpResponse.json({ user: sessionUser });
  }),

  http.post(`${API_BASE}/api/auth/logout`, () => {
    sessionUser = null;
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API_BASE}/api/auth/me`, () => {
    if (!sessionUser) {
      return jsonError(401, "unauthenticated", "Not authenticated");
    }
    return HttpResponse.json(sessionUser ?? authMe);
  }),

  http.get(`${API_BASE}/api/portals/:portal/stats`, ({ params }) => {
    const portal = params.portal as string;
    if (portal === "gem") return HttpResponse.json(gemStats);
    if (portal === "hal") return HttpResponse.json(halStats());
    if (portal === "isro") return HttpResponse.json(isroStats());
    return jsonError(404, "not_found", "Portal not found");
  }),

  http.get(`${API_BASE}/api/portals/:portal/bids`, ({ request, params }) => {
    const portal = params.portal as string;
    if (portal !== "gem") {
      return HttpResponse.json({ items: [], page: 1, pageSize: 50, total: 0 });
    }
    const url = new URL(request.url);
    const filter = url.searchParams.get("filter");
    const status = url.searchParams.get("status");
    const search = url.searchParams.get("search");
    const page = Number(url.searchParams.get("page") ?? 1);
    const pageSize = Number(url.searchParams.get("pageSize") ?? 50);

    const filtered = filterBids(
      gemBids.items as BidListItem[],
      filter,
      status,
      search,
    );
    const start = (page - 1) * pageSize;
    const items = filtered.slice(start, start + pageSize);

    return HttpResponse.json({
      items,
      page,
      pageSize,
      total: filtered.length,
    });
  }),

  http.get(`${API_BASE}/api/portals/:portal/bids/:bidKey`, ({ params }) => {
    const detail = getBidDetail(params.bidKey as string);
    if (!detail) return jsonError(404, "not_found", "Bid not found");
    return HttpResponse.json(detail);
  }),

  http.post(
    `${API_BASE}/api/portals/:portal/bids/:bidKey/generate-summary`,
    async ({ params }) => {
      const decoded = decodeURIComponent(params.bidKey as string);
      const detail = getBidDetail(params.bidKey as string);
      if (!detail) return jsonError(404, "not_found", "Bid not found");
      if (detail.bidStatus === "CLOSED") {
        return jsonError(422, "bid_closed", "Bid is closed");
      }

      await delay(1500);

      const summary: BidDetail["summary"] = {
        available: true,
        status: "ok",
        markdown: `## Generated Summary\n\nOn-demand summary for **${detail.overview.title}**.\n\n## Technical Scope\n- Scope extracted from staged documents\n- Implementation and commissioning requirements apply\n\n## Eligibility\n- Standard government procurement terms`,
        coverage: "full",
        unparsedDocuments: [],
        model: "claude-sonnet-4-6",
        generatedAt: new Date().toISOString(),
      };
      generatedSummaries.set(decoded, summary);
      return HttpResponse.json({ summary });
    },
  ),

  http.post(
    `${API_BASE}/api/portals/:portal/bids/:bidKey/disposition`,
    async ({ request, params }) => {
      const body = (await request.json()) as { action: string };
      return HttpResponse.json({ userState: body.action });
    },
  ),

  http.get(`${API_BASE}/api/notifications/auto-filtered`, () => {
    return HttpResponse.json({
      items: notificationItems,
      total: notificationItems.length,
    });
  }),

  http.get(`${API_BASE}/api/notifications/auto-filtered/count`, () => {
    return HttpResponse.json({ count: notificationItems.length });
  }),

  http.post(`${API_BASE}/api/notifications/auto-filtered/viewed`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${API_BASE}/api/notifications/auto-filtered/save-all`, () => {
    const count = notificationItems.length;
    notificationItems = [];
    return HttpResponse.json({ accepted: count });
  }),

  http.post(
    `${API_BASE}/api/notifications/auto-filtered/:portal/:bidKey/dispute`,
    async ({ request, params }) => {
      const decoded = decodeURIComponent(params.bidKey as string);
      const exists = notificationItems.some((n) => n.bidKey === decoded);
      if (!exists) {
        return jsonError(404, "not_found", "Bid already handled or not in queue");
      }
      await request.json();
      notificationItems = notificationItems.filter((n) => n.bidKey !== decoded);
      return HttpResponse.json({ disputed: true });
    },
  ),

  http.get(`${API_BASE}/api/activity`, ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get("page") ?? 1);
    const pageSize = Number(url.searchParams.get("pageSize") ?? 50);
    return HttpResponse.json({
      ...activityFixture,
      page,
      pageSize,
    });
  }),
];
