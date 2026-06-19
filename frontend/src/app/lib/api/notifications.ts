import type { NotificationItem, PortalId } from "../types";
import { apiClient, axiosErrorToApiError } from "./client";
import type { AxiosError } from "axios";
import type { ApiError } from "../types";

export const notificationsApi = {
  list: async (search?: string) => {
    try {
      const res = await apiClient.get<{ items: NotificationItem[]; total: number; matched: number }>(
        "/api/notifications/auto-filtered",
        { params: search && search.trim() ? { search: search.trim() } : {} },
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  exportCsv: async (search?: string) => {
    try {
      const res = await apiClient.get("/api/notifications/auto-filtered/export.csv", {
        params: search && search.trim() ? { search: search.trim() } : {},
        responseType: "blob",
      });
      return res.data as Blob;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  count: async () => {
    try {
      const res = await apiClient.get<{ count: number }>(
        "/api/notifications/auto-filtered/count",
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  viewed: async () => {
    try {
      await apiClient.post("/api/notifications/auto-filtered/viewed");
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  saveAll: async () => {
    try {
      const res = await apiClient.post<{ accepted: number }>(
        "/api/notifications/auto-filtered/save-all",
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  dispute: async (portal: PortalId, bidKey: string, reason: string) => {
    try {
      const res = await apiClient.post<{ disputed: boolean }>(
        `/api/notifications/auto-filtered/${portal}/${encodeURIComponent(bidKey)}/dispute`,
        { reason },
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },
};
