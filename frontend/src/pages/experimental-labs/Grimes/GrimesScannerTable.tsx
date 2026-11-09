import { useMemo, useRef, type ReactNode } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Clip } from "@/components/dense";
import { FnoStarMark } from "@/components/FnoStarMark";
import type {
  GrimesFundamentalFilter,
  GrimesListingFilter,
  GrimesRegimeFilter,
  GrimesScanRow,
  GrimesSetupFilter,
} from "@/lib/api";
import {
  EARNINGS_MOMENTUM_TOOLTIP,
  FUNDAMENTALLY_STRONG_TOOLTIP,
} from "@/lib/fundamentalsMeta";

type Props = {
  rows: GrimesScanRow[];
  listingFilter: GrimesListingFilter;
  onListingFilterChange: (f: GrimesListingFilter) => void;
  regimeFilter: GrimesRegimeFilter;
  onRegimeFilterChange: (f: GrimesRegimeFilter) => void;
  setupFilter: GrimesSetupFilter;
  onSetupFilterChange: (f: GrimesSetupFilter) => void;
  fundamentalFilter: GrimesFundamentalFilter;
  onFundamentalFilterChange: (f: GrimesFundamentalFilter) => void;
  strongSymbolSet: Set<string>;
  momentumSymbolSet: Set<string>;
  selectedKey: string | null;
  onSelect: (row: GrimesScanRow) => void;
  fnoSymbolSet: Set<string>;
  tickerQuery: string;
  onTickerQueryChange: (q: string) => void;
  emptyHint?: string;
};

export const LISTING_PILLS: { id: GrimesListingFilter; label: string }[] = [
  { id: "all", label: "All stocks" },
  { id: "fno", label: "F&O ★" },
  { id: "non_fno", label: "Non-F&O" },
  { id: "index_only", label: "Nifty IDX" },
];

export const REGIME_PILLS: { id: GrimesRegimeFilter; label: string }[] = [
  { id: "all", label: "All regimes" },
  { id: "trend", label: "Trend" },
  { id: "TREND_BULL", label: "Bull" },
  { id: "TREND_BEAR", label: "Bear" },
  { id: "TRADING_RANGE", label: "Range" },
  { id: "VOLATILITY_COMPRESSION", label: "Squeeze" },
  { id: "CLIMACTIC_EXHAUSTION", label: "Climax" },
];

export const SETUP_PILLS: { id: GrimesSetupFilter; label: string }[] = [
  { id: "all", label: "All setups" },
  { id: "continuation", label: "Continuation" },
  { id: "mean_reversion", label: "Mean rev" },
  { id: "squeeze_breakout", label: "Squeeze BO" },
  { id: "high_quality", label: "Quality≥70" },
];

export const FUNDAMENTAL_PILLS: { id: GrimesFundamentalFilter; label: string; title?: string }[] = [
  { id: "all", label: "All fundamentals" },
  { id: "strong", label: "Strong", title: FUNDAMENTALLY_STRONG_TOOLTIP },
  { id: "momentum", label: "Momentum", title: EARNINGS_MOMENTUM_TOOLTIP },
  {
    id: "strong_and_momentum",
    label: "Strong + Mom",
    title: `${FUNDAMENTALLY_STRONG_TOOLTIP} · ${EARNINGS_MOMENTUM_TOOLTIP}`,
  },
];

export function matchesListingFilter(
  row: GrimesScanRow,
  filter: GrimesListingFilter,
  fnoSymbolSet: Set<string>,
): boolean {
  if (filter === "fno") return row.kind === "equity" && fnoSymbolSet.has(row.ticker.toUpperCase());
  if (filter === "non_fno") return row.kind === "equity" && !fnoSymbolSet.has(row.ticker.toUpperCase());
  if (filter === "index_only") return row.kind === "index";
  return true;
}

export function matchesRegimeFilter(row: GrimesScanRow, filter: GrimesRegimeFilter): boolean {
  if (filter === "all") return true;
  if (filter === "trend") return row.regime === "TREND_BULL" || row.regime === "TREND_BEAR";
  return row.regime === filter;
}

export function matchesSetupFilter(row: GrimesScanRow, filter: GrimesSetupFilter): boolean {
  if (filter === "all") return true;
  if (filter === "continuation") return row.setup_group === "Trend Continuation";
  if (filter === "mean_reversion") return row.setup_group === "Mean Reversion";
  if (filter === "squeeze_breakout") return row.setup_group === "Squeeze Breakout";
  if (filter === "high_quality") return (row.quality_score || 0) >= 70;
  return true;
}

export function matchesFundamentalFilter(
  row: GrimesScanRow,
  filter: GrimesFundamentalFilter,
  strongSymbolSet: Set<string>,
  momentumSymbolSet: Set<string>,
): boolean {
  if (filter === "all") return true;
  if (row.kind === "index") return false;
  const ticker = row.ticker.toUpperCase();
  const isStrong = strongSymbolSet.has(ticker);
  const isMomentum = momentumSymbolSet.has(ticker);
  if (filter === "strong") return isStrong;
  if (filter === "momentum") return isMomentum;
  if (filter === "strong_and_momentum") return isStrong && isMomentum;
  return true;
}

function regimeShort(regime: string): string {
  if (regime === "TREND_BULL") return "Bull";
  if (regime === "TREND_BEAR") return "Bear";
  if (regime === "VOLATILITY_COMPRESSION") return "Squeeze";
  if (regime === "CLIMACTIC_EXHAUSTION") return "Climax";
  return "Range";
}

function regimeTone(regime: string): string {
  if (regime === "TREND_BULL") return "text-emerald-300";
  if (regime === "TREND_BEAR") return "text-rose-300";
  if (regime === "VOLATILITY_COMPRESSION") return "text-amber-300";
  if (regime === "CLIMACTIC_EXHAUSTION") return "text-orange-300";
  return "text-slate-400";
}

function qualityTone(score: number): string {
  if (score >= 70) return "text-emerald-300";
  if (score >= 50) return "text-amber-300";
  return "text-slate-400";
}

type FiltersProps = Pick<
  Props,
  | "listingFilter"
  | "onListingFilterChange"
  | "regimeFilter"
  | "onRegimeFilterChange"
  | "setupFilter"
  | "onSetupFilterChange"
  | "fundamentalFilter"
  | "onFundamentalFilterChange"
>;

const pillClass = (active: boolean) =>
  `rounded-full px-2.5 py-0.5 text-data-xs font-medium transition ${
    active
      ? "bg-accent/20 text-accent"
      : "bg-white/5 text-slate-300 hover:bg-white/10 hover:text-slate-100"
  }`;

const rowLabel = (text: string) => (
  <span className="shrink-0 self-center text-[10px] uppercase tracking-wide text-slate-400">
    {text}
  </span>
);

export function GrimesScannerFilters({
  listingFilter,
  onListingFilterChange,
  regimeFilter,
  onRegimeFilterChange,
  setupFilter,
  onSetupFilterChange,
  fundamentalFilter,
  onFundamentalFilterChange,
  weeklyOnly,
  onWeeklyOnlyChange,
  trailing,
}: FiltersProps & {
  weeklyOnly: boolean;
  onWeeklyOnlyChange: (value: boolean) => void;
  trailing?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-0.5">
      <div className="flex flex-wrap items-center gap-1">
        {rowLabel("List")}
        {LISTING_PILLS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onListingFilterChange(p.id)}
            className={pillClass(listingFilter === p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {rowLabel("Regime")}
        {REGIME_PILLS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onRegimeFilterChange(p.id)}
            className={pillClass(regimeFilter === p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {rowLabel("Setup")}
        {SETUP_PILLS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onSetupFilterChange(p.id)}
            className={pillClass(setupFilter === p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {rowLabel("Fund")}
        {FUNDAMENTAL_PILLS.map((p) => (
          <button
            key={p.id}
            type="button"
            title={p.title}
            onClick={() => onFundamentalFilterChange(p.id)}
            className={pillClass(fundamentalFilter === p.id)}
          >
            {p.label}
          </button>
        ))}
        {fundamentalFilter !== "all" ? (
          <span className="text-data-xs text-slate-400">cached filings · sync ticker for latest</span>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => onWeeklyOnlyChange(!weeklyOnly)}
        aria-pressed={weeklyOnly}
        className={pillClass(weeklyOnly)}
        title="Only rows whose weekly trend agrees with the daily setup"
      >
        Weekly aligned
      </button>
      {trailing}
    </div>
  );
}

export function GrimesScannerTable({
  rows,
  listingFilter,
  regimeFilter,
  setupFilter,
  fundamentalFilter,
  strongSymbolSet,
  momentumSymbolSet,
  selectedKey,
  onSelect,
  fnoSymbolSet,
  tickerQuery,
  onTickerQueryChange,
  emptyHint,
}: Props) {
  const parentRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = tickerQuery.trim().toUpperCase();
    return rows.filter((r) => {
      if (!matchesListingFilter(r, listingFilter, fnoSymbolSet)) return false;
      if (!matchesRegimeFilter(r, regimeFilter)) return false;
      if (!matchesSetupFilter(r, setupFilter)) return false;
      if (
        !matchesFundamentalFilter(r, fundamentalFilter, strongSymbolSet, momentumSymbolSet)
      ) {
        return false;
      }
      if (q && !r.ticker.toUpperCase().includes(q)) return false;
      return true;
    });
  }, [
    rows,
    listingFilter,
    regimeFilter,
    setupFilter,
    fundamentalFilter,
    strongSymbolSet,
    momentumSymbolSet,
    fnoSymbolSet,
    tickerQuery,
  ]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 36,
    overscan: 12,
  });

  return (
    <div className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-surface-border px-2 py-1">
        <h2 className="shrink-0 text-data-md font-semibold text-slate-100">Scanner</h2>
        <span className="text-data-xs tabular-nums text-slate-300">
          {filtered.length.toLocaleString("en-IN")} / {rows.length.toLocaleString("en-IN")}
        </span>
        <input
          type="search"
          value={tickerQuery}
          onChange={(e) => onTickerQueryChange(e.target.value)}
          placeholder="Search ticker…"
          className="ml-auto w-28 rounded-md border border-surface-border bg-[#121820] px-2 py-0.5 text-data-xs text-slate-200 placeholder:text-slate-500 sm:w-36"
        />
      </div>
      <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_4.2rem_minmax(0,1.1fr)_3.4rem_3.2rem] gap-1 border-b border-surface-border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        <span>Symbol</span>
        <span>Regime</span>
        <span>Setup</span>
        <span className="text-right">Q</span>
        <span className="text-right">Vol%</span>
      </div>
      <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-data-sm text-slate-400">
            {emptyHint || "No rows match this filter"}
          </div>
        ) : (
          <div className="relative w-full" style={{ height: `${virtualizer.getTotalSize()}px` }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const row = filtered[vRow.index];
              const selected = selectedKey === row.instrument_key;
              return (
                <button
                  key={row.instrument_key}
                  type="button"
                  onClick={() => onSelect(row)}
                  className={`absolute left-0 grid w-full grid-cols-[minmax(0,1fr)_4.2rem_minmax(0,1.1fr)_3.4rem_3.2rem] gap-1 border-b border-surface-border/50 px-2 text-left text-data-sm transition ${
                    selected ? "bg-accent/15" : "hover:bg-white/[0.04]"
                  }`}
                  style={{ height: `${vRow.size}px`, transform: `translateY(${vRow.start}px)` }}
                >
                  <span className="flex min-w-0 items-center gap-1">
                    <Clip className="ticker">{row.ticker}</Clip>
                    {row.kind === "index" ? (
                      <span className="shrink-0 text-[10px] font-semibold text-amber-300">IDX</span>
                    ) : (
                      <FnoStarMark show={fnoSymbolSet.has(row.ticker.toUpperCase())} />
                    )}
                  </span>
                  <span className={`flex items-center ${regimeTone(row.regime)}`}>
                    {regimeShort(row.regime)}
                  </span>
                  <span className="flex min-w-0 items-center">
                    <Clip className="text-slate-300">
                      {row.setup_type ? row.setup_type.replace(/_/g, " ") : "—"}
                    </Clip>
                  </span>
                  <span
                    className={`flex items-center justify-end num ${qualityTone(
                      row.quality_score,
                    )}`}
                  >
                    {row.quality_score}
                  </span>
                  <span className="flex items-center justify-end num text-slate-300">
                    {row.volatility_rank != null ? row.volatility_rank.toFixed(0) : "—"}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
