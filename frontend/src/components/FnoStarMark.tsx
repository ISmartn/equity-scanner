import { Star } from "lucide-react";

/** Amber ★ — same marker as Momentum Scanner / Multi-Year Breakout. */
export function FnoStarMark({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span title="F&O stock" aria-label="F&O stock">
      <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400" aria-hidden />
    </span>
  );
}
