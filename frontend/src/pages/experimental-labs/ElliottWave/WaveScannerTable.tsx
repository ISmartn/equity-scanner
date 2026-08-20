import { useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ElliottWaveFilter, ElliottWaveRow } from "@/lib/api";

type Props = {
  rows: ElliottWaveRow[];
  filter: ElliottWaveFilter;
  onFilterChange: (f: ElliottWaveFilter) => void;
  selectedKey: string | null;
  onSelect: (row: ElliottWaveRow) => void;
};

function suretyTone(score: number): string {
  if (score >= 75) return "text-emerald-300";
  if (score >= 50) return "text-amber-300";
  return "text-slate-400";
}

function matchesFilter(row: ElliottWaveRow, filter: ElliottWaveFilter): boolean {
  if (filter === "wave3") return row.phase === "Wave 3 Breakout";
  if (filter === "wave4") return row.phase === "Wave 4 Dip";
  if (filter === "high_surety") return (row.surety_score || 0) >= 75;
  return true;
}

export function WaveScannerTable({
  rows,
  filter,
  onFilterChange,
  selectedKey,
  onSelect,
}: Props) {
  const parentRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(
    () => rows.filter((r) => matchesFilter(r, filter)),
    [rows, filter],
  );

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 36,
    overscan: 12,
  });

  const pills: { id: ElliottWaveFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "wave3", label: "Wave 3 Breakouts" },
    { id: "wave4", label: "Wave 4 Dips" },
    { id: "high_surety", label: "High Surety (>75)" },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-surface-border px-2 py-2">
        {pills.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onFilterChange(p.id)}
            className={`rounded-full px-2.5 py-1 text-[10px] font-medium transition ${
              filter === p.id
                ? "bg-accent/20 text-accent"
                : "bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200"
            }`}
          >
            {p.label}
          </button>
        ))}
        <span className="ml-auto self-center text-[10px] text-slate-500">
          {filtered.length} / {rows.length}
        </span>
      </div>

      <div className="grid shrink-0 grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_4.5rem_5rem_5rem] gap-1 border-b border-surface-border px-2 py-1.5 text-[9px] uppercase tracking-wide text-slate-500">
        <span>Symbol</span>
        <span>Phase</span>
        <span className="text-right">Surety</span>
        <span className="text-right">Inv Risk</span>
        <span className="text-right">Price</span>
      </div>

      <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-8 text-center text-[11px] text-slate-500">
            No rows match this filter
          </div>
        ) : (
          <div
            className="relative w-full"
            style={{ height: `${virtualizer.getTotalSize()}px` }}
          >
            {virtualizer.getVirtualItems().map((vRow) => {
              const row = filtered[vRow.index];
              const selected = selectedKey === row.instrument_key;
              return (
                <button
                  key={row.instrument_key}
                  type="button"
                  onClick={() => onSelect(row)}
                  className={`absolute left-0 grid w-full grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_4.5rem_5rem_5rem] gap-1 border-b border-surface-border/50 px-2 text-left text-[11px] transition ${
                    selected ? "bg-accent/15" : "hover:bg-white/[0.04]"
                  }`}
                  style={{
                    height: `${vRow.size}px`,
                    transform: `translateY(${vRow.start}px)`,
                  }}
                >
                  <span className="flex items-center truncate font-medium text-slate-100">
                    {row.ticker}
                    {row.kind === "index" ? (
                      <span className="ml-1 text-[8px] text-amber-300">IDX</span>
                    ) : null}
                  </span>
                  <span className="flex items-center truncate text-slate-300">{row.phase}</span>
                  <span
                    className={`flex items-center justify-end tabular-nums font-semibold ${suretyTone(
                      row.surety_score,
                    )}`}
                  >
                    {row.surety_score.toFixed(0)}
                  </span>
                  <span className="flex items-center justify-end tabular-nums text-slate-400">
                    {row.invalidation_risk_pct != null
                      ? `${row.invalidation_risk_pct.toFixed(1)}%`
                      : "—"}
                  </span>
                  <span className="flex items-center justify-end tabular-nums text-slate-200">
                    {row.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
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
