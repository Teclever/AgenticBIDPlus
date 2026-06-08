import type { SystemAlert } from "../types";
import { apiClient, axiosErrorToApiError } from "./client";
import type { AxiosError } from "axios";
import type { ApiError } from "../types";

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
