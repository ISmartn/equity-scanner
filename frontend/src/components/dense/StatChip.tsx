import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface StatChipProps {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  valueClassName?: string;
}

/** Inline label/value pair for one-line stat strips. */
export function StatChip({ label, value, hint, icon, valueClassName }: StatChipProps) {
  return (
    <div className="inline-flex shrink-0 items-baseline gap-1.5 whitespace-nowrap" title={hint}>
      {icon ? <span className="self-center">{icon}</span> : null}
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</span>
      <span className={cn("num text-data-md text-slate-100", valueClassName)}>{value}</span>
    </div>
  );
}
