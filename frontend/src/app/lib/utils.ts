import { ApiRequestError } from "./api";

export function getErrorMessage(error: unknown, fallback = "An error occurred"): string {
  if (!error) return fallback;
  if (error instanceof ApiRequestError) return error.message || fallback;
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

export function isErrorCode(error: unknown, code: string): boolean {
  if (error instanceof ApiRequestError) return error.code === code;
  return false;
}

export function formatDateSafe(
  date: string | null | undefined,
  formatter: (d: Date) => string,
  fallback = "N/A",
): string {
  if (!date) return fallback;
  try {
    const parsed = new Date(date);
    if (isNaN(parsed.getTime())) return date;
    return formatter(parsed);
  } catch {
    return date;
  }
}

export function toNumber(value: number | null | undefined, fallback = 0): number {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "number" && !isNaN(value)) return value;
  return fallback;
}

export function toString(value: string | null | undefined, fallback = ""): string {
  if (value === null || value === undefined) return fallback;
  return String(value);
}

export function toArray<T>(value: T[] | null | undefined): T[] {
  if (Array.isArray(value)) return value;
  return [];
}
