import type { ActivityItem, Paginated } from "../types";
import { apiClient, axiosErrorToApiError } from "./client";
import type { AxiosError } from "axios";
import type { ApiError } from "../types";

export const activityApi = {
  list: async (page = 1, pageSize = 50) => {
    try {
      const res = await apiClient.get<Paginated<ActivityItem>>(
        `/api/activity?page=${page}&pageSize=${pageSize}`,
      );
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },
};
