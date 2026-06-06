import { format, parseISO, isValid } from "date-fns";
import type { BidFilter } from "./types";

export function formatWindowDate(isoDate: string): string {
  try {
    return format(parseISO(isoDate), "d MMM yyyy");
  } catch {
    return isoDate;
  }
}

export function formatClosingDate(value: string | null, raw: string): string {
  if (value) {
    try {
      const d = parseISO(value);
      if (isValid(d)) return format(d, "MMM dd, yyyy");
    } catch {
      /* fall through */
    }
  }
  return raw;
}

export function formatDateTime(iso: string): { date: string; time: string } {
  const d = parseISO(iso);
  return {
    date: format(d, "MMM dd, yyyy"),
    time: format(d, "hh:mm a"),
  };
}

export const FILTER_LABELS: Record<BidFilter, string> = {
  all: "All bids",
  new: "New bids",
  score3plus: "Score 3+ bids",
  score4plus: "Score 4+ bids",
  score5: "Score 5 bids",
  highpriority: "High Priority bids",
  closingsoon: "Closing Soon bids",
};

export function bidDetailPath(portal: string, bidKey: string): string {
  return `/portal/${portal}/bid/${encodeURIComponent(bidKey)}`;
}
