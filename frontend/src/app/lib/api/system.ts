import type { SystemAlert, ScrapeRun } from "../types";
import { apiClient, axiosErrorToApiError } from "./client";
import type { AxiosError } from "axios";
import type { ApiError } from "../types";

export interface ActiveGeneration {
  portal: string;
  bidKey: string;
  bidId: string;
  startedAt: string;
}

export const generatingApi = {
  get: async (): Promise<{ active: ActiveGeneration | null }> => {
    try {
      const res = await apiClient.get<{ active: ActiveGeneration | null }>("/api/generating");
      return res.data;
    } catch {
      // Fail silently — a stale banner is better than a broken UI
      return { active: null };
    }
  },
};

export const scrapeRunsApi = {
  list: async (limit = 3): Promise<{ runs: ScrapeRun[] }> => {
    try {
      const res = await apiClient.get<{ runs: ScrapeRun[] }>(`/api/scrape-runs?limit=${limit}`);
      return res.data;
    } catch {
      return { runs: [] };
    }
  },
};

export const systemAlertsApi = {
  list: async (includeCleared = false) => {
    try {
      const res = await apiClient.get<{ items: SystemAlert[] }>(
        `/api/system-alerts${includeCleared ? "?includeCleared=true" : ""}`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  retry: async (alertType: string, portal: string | null) => {
    try {
      const res = await apiClient.post<{ cleared: number; portal: string | null }>(
        "/api/system-alerts/retry",
        { alertType, portal },
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },
};
