import { cn } from "@/lib/cn";

interface PctCellProps {
  value: number | null | undefined;
  digits?: number;
  className?: string;
}

export function pctTone(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "text-slate-400";
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-slate-300";
}

export function PctCell({ value, digits = 2, className }: PctCellProps) {
  if (value == null || Number.isNaN(value)) {
    return <span className={cn("text-slate-500", className)}>—</span>;
  }
  return (
    <span className={cn("num", pctTone(value), className)}>
      {value > 0 ? "+" : ""}
      {value.toFixed(digits)}%
    </span>
  );
}
