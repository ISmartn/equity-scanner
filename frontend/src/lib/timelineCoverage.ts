import type { TimelineStats } from "@/lib/api";

export function describeTimelineCoverage(stats: TimelineStats | null): {
  label: string;
  detail: string;
  tone: "current" | "behind" | "empty";
} {
  if (!stats?.max_trade_date) {
    return {
      label: "No candle data",
      detail: "Run Sync profiles, then Up-to-date",
      tone: "empty",
    };
  }

  const through = stats.max_trade_date;
  const target = stats.target_trade_date ?? through;
  const atMax = stats.symbols_at_max_date ?? stats.symbols_with_data;
  const total = stats.profile_count;
  const behind = stats.symbols_behind_target ?? 0;
  const ingestSkip = stats.ingest_skip_count ?? 0;

  if (stats.is_up_to_date) {
    const skipNote =
      ingestSkip > 0
        ? ` · ${ingestSkip} delisted (ingest skipped)`
        : "";
    return {
      label: `Data through ${through}`,
      detail:
        behind > 0
          ? `${atMax.toLocaleString()}/${total.toLocaleString()} at latest session · ${behind} symbol${behind === 1 ? "" : "s"} behind${skipNote}`
          : `${atMax.toLocaleString()}/${total.toLocaleString()} symbols at latest session${skipNote}`,
      tone: behind > 0 ? "behind" : "current",
    };
  }

  return {
    label: `Data through ${through}`,
    detail: `Target ${target} · ${behind.toLocaleString()} symbol${behind === 1 ? "" : "s"} need update`,
    tone: "behind",
  };
}

export function needsCandleSync(stats: TimelineStats | null): boolean {
  if (!stats?.max_trade_date) return true;
  if (!stats.is_up_to_date) return true;
  return (stats.symbols_behind_target ?? 0) > 0;
}
