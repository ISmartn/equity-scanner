import type { SectorConstituentRow, SectorConstituentsResponse } from "@/lib/api";

type Props = {
  sectorName: string | null;
  data: SectorConstituentsResponse | null;
  loading: boolean;
  error: string | null;
};

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function pctTone(v: number | null | undefined): string {
  if (v == null) return "text-slate-500";
  if (v > 0) return "text-emerald-300";
  if (v < 0) return "text-rose-300";
  return "text-slate-400";
}

function Row({ row }: { row: SectorConstituentRow }) {
  return (
    <tr className="border-b border-surface-border/60 hover:bg-white/[0.03]">
      <td className="px-2 py-1.5">
        <div className="text-[11px] font-medium text-slate-100">{row.ticker}</div>
        {row.company_name ? (
          <div className="max-w-[160px] truncate text-[9px] text-slate-500">{row.company_name}</div>
        ) : null}
      </td>
      <td className="px-2 py-1.5 text-right text-[11px] tabular-nums text-slate-300">
        {row.close.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
      </td>
      <td className={`px-2 py-1.5 text-right text-[11px] tabular-nums ${pctTone(row.change_1d_pct)}`}>
        {fmtPct(row.change_1d_pct)}
      </td>
      <td className={`px-2 py-1.5 text-right text-[11px] tabular-nums ${pctTone(row.change_5d_pct)}`}>
        {fmtPct(row.change_5d_pct)}
      </td>
      <td className={`px-2 py-1.5 text-right text-[11px] tabular-nums ${pctTone(row.change_20d_pct)}`}>
        {fmtPct(row.change_20d_pct)}
      </td>
      <td className={`px-2 py-1.5 text-right text-[11px] tabular-nums ${pctTone(row.vs_sector_1d_pct)}`}>
        {fmtPct(row.vs_sector_1d_pct)}
      </td>
      <td className="px-2 py-1.5 text-center text-[10px]">
        {row.above_50sma == null ? (
          <span className="text-slate-600">—</span>
        ) : row.above_50sma ? (
          <span className="text-emerald-400">Above</span>
        ) : (
          <span className="text-rose-400">Below</span>
        )}
      </td>
    </tr>
  );
}

export function SectorConstituentsPanel({ sectorName, data, loading, error }: Props) {
  if (!sectorName) {
    return (
      <div className="flex h-full min-h-[140px] items-center justify-center rounded-xl border border-dashed border-surface-border bg-surface-raised px-3 text-[11px] text-slate-500">
        Click a sector on the RRG or table to see constituent stocks
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-surface-border px-3 py-2">
        <h3 className="text-[12px] font-medium text-slate-100">{sectorName}</h3>
        <span className="text-[10px] text-slate-500">
          {data
            ? `${data.count} stocks · sector 1d ${fmtPct(data.sector_change_1d_pct)}${
                data.as_of ? ` · ${data.as_of}` : ""
              }`
            : loading
              ? "Loading stocks…"
              : "Constituents"}
        </span>
        {data?.source ? (
          <span className="ml-auto text-[9px] uppercase tracking-wide text-slate-600">
            {data.source === "index_candles" ? "official index + stocks" : data.source}
          </span>
        ) : null}
      </div>

      {error ? (
        <div className="px-3 py-2 text-[11px] text-rose-300">{error}</div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-auto">
        {loading && !data ? (
          <div className="px-3 py-6 text-center text-[11px] text-slate-500">Loading…</div>
        ) : !data?.constituents.length ? (
          <div className="px-3 py-6 text-center text-[11px] text-slate-500">
            No constituent prices available for this sector
          </div>
        ) : (
          <table className="w-full min-w-[520px] border-collapse text-left">
            <thead className="sticky top-0 z-10 bg-surface-raised text-[9px] uppercase tracking-wide text-slate-500">
              <tr className="border-b border-surface-border">
                <th className="px-2 py-1.5 font-medium">Stock</th>
                <th className="px-2 py-1.5 text-right font-medium">Close</th>
                <th className="px-2 py-1.5 text-right font-medium">1d</th>
                <th className="px-2 py-1.5 text-right font-medium">5d</th>
                <th className="px-2 py-1.5 text-right font-medium">20d</th>
                <th className="px-2 py-1.5 text-right font-medium">vs Sec</th>
                <th className="px-2 py-1.5 text-center font-medium">50 SMA</th>
              </tr>
            </thead>
            <tbody>
              {data.constituents.map((row) => (
                <Row key={row.ticker} row={row} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
