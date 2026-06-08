import type { User } from "../types";
import { apiClient, ApiRequestError, axiosErrorToApiError } from "./client";
import type { AxiosError } from "axios";
import type { ApiError } from "../types";

export const authApi = {
  me: async () => {
    try {
      const res = await apiClient.get<User>("/api/auth/me");
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  login: async (email: string, password: string, rememberMe: boolean) => {
    try {
      const res = await apiClient.post<{ user: User }>("/api/auth/login", {
        email,
        password,
        rememberMe,
      });
      return res.data;
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },

  logout: async () => {
    try {
      await apiClient.post("/api/auth/logout");
    } catch (e) {
      throw axiosErrorToApiError(e as AxiosError<ApiError>);
    }
  },
};

export { ApiRequestError };
