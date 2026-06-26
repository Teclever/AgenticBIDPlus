import type { BidDetail, BidFilter, BidListItem, BidSummary, DocumentItem, KeywordWatchStats, Paginated, PortalId, PortalStats } from "../types";
import { apiClient, axiosErrorToApiError } from "./client";
import type { AxiosError } from "axios";
import type { ApiError } from "../types";

export const portalApi = {
  stats: async (portal: PortalId) => {
    try {
      const res = await apiClient.get<PortalStats>(`/api/portals/${portal}/stats`);
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  keywordWatchStats: async () => {
    try {
      const res = await apiClient.get<KeywordWatchStats>(`/api/keyword-watch/stats`);
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  bids: async (
    portal: PortalId,
    params: {
      page?: number;
      pageSize?: number;
      search?: string[];
      filter?: BidFilter;
      status?: string;
      discoverySource?: string;
      discoveryCategory?: string;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    qs.set("page", String(params.page ?? 1));
    qs.set("pageSize", String(params.pageSize ?? 50));
    for (const term of params.search ?? []) {
      if (term.trim()) qs.append("search", term.trim());
    }
    if (params.filter && params.filter !== "all") qs.set("filter", params.filter);
    if (params.status && params.status !== "all") qs.set("status", params.status);
    if (params.discoverySource) qs.set("discoverySource", params.discoverySource);
    if (params.discoveryCategory) qs.set("discoveryCategory", params.discoveryCategory);
    try {
      const res = await apiClient.get<Paginated<BidListItem>>(
        `/api/portals/${portal}/bids?${qs.toString()}`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  bulkDisposition: async (portal: PortalId, bidKeys: string[], action: "accepted" | "rejected") => {
    try {
      const res = await apiClient.post<{ updated: number; missing: string[] }>(
        `/api/portals/${portal}/bids/bulk-disposition`,
        { bidKeys, action },
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  bidDetail: async (portal: PortalId, bidKey: string) => {
    try {
      const res = await apiClient.get<BidDetail>(
        `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  generateSummary: async (portal: PortalId, bidKey: string) => {
    try {
      const res = await apiClient.post<BidSummary>(
        `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/generate-summary`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  listDocuments: async (portal: PortalId, bidKey: string): Promise<{ documents: DocumentItem[] }> => {
    try {
      const res = await apiClient.get<{ documents: DocumentItem[] }>(
        `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/documents`,
      );
      return res.data;
    } catch {
      return { documents: [] };
    }
  },

  fetchDocuments: async (portal: PortalId, bidKey: string): Promise<{ documents: DocumentItem[] }> => {
    try {
      const res = await apiClient.post<{ documents: DocumentItem[] }>(
        `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/documents/fetch`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  documentDownloadUrl: (portal: PortalId, bidKey: string): string =>
    `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/documents/download`,

  promote: async (portal: PortalId, bidKey: string) => {
    try {
      const res = await apiClient.post<BidDetail>(
        `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/promote`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  disposition: async (portal: PortalId, bidKey: string, action: "accepted" | "rejected" | "reset") => {
    try {
      const res = await apiClient.post<{ userState: string }>(
        `/api/portals/${portal}/bids/${encodeURIComponent(bidKey)}/disposition`,
        { action },
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },
};
