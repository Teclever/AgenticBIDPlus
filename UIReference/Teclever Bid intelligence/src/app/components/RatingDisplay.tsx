import { Badge } from "./ui/badge";

interface RatingDisplayProps {
  rating: number | null;
  method: "model" | "keyword";
  eliminatedBy?: string | null;
  compact?: boolean;
}

export function RatingDisplay({ rating, method, eliminatedBy, compact }: RatingDisplayProps) {
  const isFiltered = method === "keyword";

  if (isFiltered) {
    return (
      <div>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-gray-700">0</span>
          <Badge variant="outline" className="bg-amber-50 text-amber-800 border-amber-300 text-xs">
            Filtered
          </Badge>
        </div>
        {eliminatedBy && (
          <p className={`text-amber-700 ${compact ? "text-xs mt-0.5" : "text-sm mt-1"}`}>
            {eliminatedBy}
          </p>
        )}
      </div>
    );
  }

  return (
    <span className="font-semibold text-gray-900">
      {rating ?? "—"}
    </span>
  );
}
