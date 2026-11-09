import { Clip, PctCell } from "@/components/dense";
import type { SectorConstituentRow, SectorConstituentsResponse } from "@/lib/api";

type Props = {
  sectorName: string | null;
  data: SectorConstituentsResponse | null;
  loading: boolean;
  error: string | null;
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
};

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function Row({
  row,
  selected,
  onSelect,
}: {
  row: SectorConstituentRow;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <tr onClick={onSelect} className={`dt-row ${selected ? "dt-selected" : ""}`}>
      <td className="max-w-[12rem]">
        <div className="ticker">{row.ticker}</div>
        {row.company_name ? (
          <Clip className="text-data-xs text-slate-400">{row.company_name}</Clip>
        ) : null}
      </td>
      <td className="text-right text-slate-200">
        {row.close.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
      </td>
      <td className="text-right">
        <PctCell value={row.change_1d_pct} />
      </td>
      <td className="text-right">
        <PctCell value={row.change_5d_pct} />
      </td>
      <td className="text-right">
        <PctCell value={row.change_20d_pct} />
      </td>
      <td className="text-right">
        <PctCell value={row.vs_sector_1d_pct} />
      </td>
      <td className="text-center">
        {row.above_50sma == null ? (
          <span className="text-slate-500">—</span>
        ) : row.above_50sma ? (
          <span className="text-gain">Above</span>
        ) : (
          <span className="text-loss">Below</span>
        )}
      </td>
    </tr>
  );
}

export function SectorConstituentsPanel({
  sectorName,
  data,
  loading,
  error,
  selectedTicker,
  onSelectTicker,
}: Props) {
  if (!sectorName) {
    return (
      <div className="flex h-full min-h-[140px] items-center justify-center rounded-lg border border-dashed border-surface-border bg-surface-raised px-3 text-data-sm text-slate-400">
        Click a sector on the RRG or table to see constituent stocks
      </div>
    );
  }

  return (
    <div className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex shrink-0 items-baseline gap-2 border-b border-surface-border px-2 py-1">
        <h3 className="shrink-0 text-data-md font-semibold text-slate-100">{sectorName}</h3>
        <Clip className="text-data-xs text-slate-300">
          {data
            ? `${data.count} stocks · sector 1d ${fmtPct(data.sector_change_1d_pct)}${
                data.as_of ? ` · ${data.as_of}` : ""
              } · click a stock for chart`
            : loading
              ? "Loading stocks…"
              : "Constituents"}
        </Clip>
        {data?.source ? (
          <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-slate-400">
            {data.source === "index_candles" ? "official index + stocks" : data.source}
          </span>
        ) : null}
      </div>

      {error ? (
        <div className="px-2 py-1 text-data-sm text-loss">{error}</div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-auto">
        {loading && !data ? (
          <div className="px-3 py-4 text-center text-data-sm text-slate-400">Loading…</div>
        ) : !data?.constituents.length ? (
          <div className="px-3 py-4 text-center text-data-sm text-slate-400">
            No constituent prices available for this sector
          </div>
        ) : (
          <table className="dt min-w-[520px]">
            <thead>
              <tr>
                <th>Stock</th>
                <th className="text-right">Close</th>
                <th className="text-right">1d</th>
                <th className="text-right">5d</th>
                <th className="text-right">20d</th>
                <th className="text-right">vs Sec</th>
                <th className="text-center">50 SMA</th>
              </tr>
            </thead>
            <tbody>
              {data.constituents.map((row) => (
                <Row
                  key={row.ticker}
                  row={row}
                  selected={selectedTicker === row.ticker}
                  onSelect={() => onSelectTicker(row.ticker)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
