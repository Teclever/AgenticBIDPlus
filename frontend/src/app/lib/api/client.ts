import axios, { AxiosError } from "axios";
import type { ApiError } from "../types";

const BASE_URL =
  import.meta.env.VITE_API_BASE && import.meta.env.VITE_API_BASE.length > 0
    ? import.meta.env.VITE_API_BASE
    : "";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

let redirectingToLogin = false;

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    if (error.response?.status === 401) {
      if (!redirectingToLogin && window.location.pathname !== "/login") {
        redirectingToLogin = true;
        window.location.href = "/login";
        setTimeout(() => { redirectingToLogin = false; }, 100);
      }
    }
    return Promise.reject(error);
  },
);

export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function isAuthError(status: number, code: string): boolean {
  return status === 401 || code === "unauthenticated" || code === "invalid_credentials";
}

export function axiosErrorToApiError(error: AxiosError<ApiError>): ApiRequestError {
  const status = error.response?.status ?? 0;
  const code = error.response?.data?.error?.code ?? "unknown";
  const message = error.response?.data?.error?.message ?? error.message;
  return new ApiRequestError(status, code, message);
}
