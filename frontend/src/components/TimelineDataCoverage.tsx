import type { TimelineStats } from "@/lib/api";
import { describeTimelineCoverage } from "@/lib/timelineCoverage";
import { AlertCircle, CheckCircle2, Database } from "lucide-react";

interface TimelineDataCoverageProps {
  stats: TimelineStats | null;
  compact?: boolean;
}

const toneClass = {
  current: "text-emerald-400/90",
  behind: "text-amber-400/90",
  empty: "text-slate-500",
} as const;

export function TimelineDataCoverage({ stats, compact = false }: TimelineDataCoverageProps) {
  const { label, detail, tone } = describeTimelineCoverage(stats);
  const Icon = tone === "current" ? CheckCircle2 : tone === "behind" ? AlertCircle : Database;

  if (compact) {
    return (
      <span
        className={`inline-flex items-center gap-1 text-[11px] ${toneClass[tone]}`}
        title={detail}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span>{label}</span>
      </span>
    );
  }

  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-[11px] ${
        tone === "current"
          ? "border-emerald-500/20 bg-emerald-500/5"
          : tone === "behind"
            ? "border-amber-500/20 bg-amber-500/5"
            : "border-surface-border bg-surface/40"
      }`}
    >
      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${toneClass[tone]}`} />
      <div className="min-w-0">
        <div className={`font-medium ${toneClass[tone]}`}>{label}</div>
        <div className="text-slate-500">{detail}</div>
      </div>
    </div>
  );
}
