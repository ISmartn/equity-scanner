import { Clip } from "@/components/dense";
import type { SectorQuadrant, SectorRotationRow } from "@/lib/api";

export type SectorTableFilter =
  | "all"
  | "stealth"
  | "price_action"
  | "improving"
  | "leading";

type SortKey = "surety_score" | "daily_change_pct" | "rs_ratio" | "name";

type Props = {
  sectors: SectorRotationRow[];
  filter: SectorTableFilter;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  selectedName: string | null;
  onSelect: (name: string) => void;
  onSort: (key: SortKey) => void;
};

function suretyTone(score: number): string {
  if (score >= 80) return "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
  if (score >= 50) return "bg-amber-500/20 text-amber-300 border-amber-500/40";
  return "bg-slate-500/20 text-slate-300 border-slate-500/40";
}

function quadrantTone(q: SectorQuadrant): string {
  if (q === "Leading") return "text-emerald-300";
  if (q === "Weakening") return "text-amber-300";
  if (q === "Lagging") return "text-rose-300";
  return "text-sky-300";
}

function fmtPct(v: number): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

export function SectorScanTable({
  sectors,
  filter,
  sortKey,
  sortDir,
  selectedName,
  onSelect,
  onSort,
}: Props) {
  const filtered = sectors.filter((s) => {
    if (filter === "stealth") return s.is_stealth_accumulation;
    if (filter === "price_action") return s.is_price_action_confirmed;
    if (filter === "improving") return s.quadrant === "Improving";
    if (filter === "leading") return s.quadrant === "Leading";
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "string" && typeof bv === "string") {
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    const an = Number(av ?? 0);
    const bn = Number(bv ?? 0);
    return sortDir === "asc" ? an - bn : bn - an;
  });

  const SortBtn = ({ k, label }: { k: SortKey; label: string }) => (
    <button
      type="button"
      onClick={() => onSort(k)}
      className="inline-flex items-center gap-0.5 hover:text-slate-200"
    >
      {label}
      {sortKey === k ? (sortDir === "desc" ? "↓" : "↑") : ""}
    </button>
  );

  return (
    <div className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="dt">
          <thead>
            <tr>
              <th>
                <SortBtn k="name" label="Sector" />
              </th>
              <th>Quadrant</th>
              <th className="text-right">
                <SortBtn k="daily_change_pct" label="Day %" />
              </th>
              <th className="text-right">
                <SortBtn k="rs_ratio" label="RS-R" />
              </th>
              <th className="text-right">RS-M</th>
              <th className="text-right">
                <SortBtn k="surety_score" label="Surety" />
              </th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-6 text-center text-slate-400">
                  No sectors match this filter.
                </td>
              </tr>
            ) : (
              sorted.map((s) => {
                const selected = selectedName === s.name;
                return (
                  <tr
                    key={s.name}
                    onClick={() => onSelect(s.name)}
                    className={`dt-row ${selected ? "dt-selected" : ""}`}
                  >
                    <td className="max-w-[14rem]">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <Clip className="font-semibold text-slate-100">{s.name}</Clip>
                        {s.category === "Official" ? (
                          <span className="shrink-0 rounded border border-amber-400/50 bg-amber-500/15 px-1 py-px text-[10px] font-semibold uppercase leading-3 tracking-wide text-amber-200">
                            Index
                          </span>
                        ) : (
                          <span className="shrink-0 rounded border border-slate-500/40 bg-slate-500/10 px-1 py-px text-[10px] uppercase leading-3 tracking-wide text-slate-300">
                            Theme
                          </span>
                        )}
                      </div>
                      <div className="text-data-xs text-slate-400">
                        {s.breadth_pct_above_50sma != null
                          ? `${s.breadth_pct_above_50sma.toFixed(0)}% >50SMA`
                          : s.category}
                      </div>
                    </td>
                    <td className={`font-medium ${quadrantTone(s.quadrant)}`}>
                      <div>{s.quadrant}</div>
                      {s.rotation_path ? (
                        <div
                          className={`text-[10px] font-normal ${
                            s.rotation_bias === "clockwise"
                              ? "text-amber-300/90"
                              : s.rotation_bias === "counter"
                                ? "text-emerald-300/90"
                                : "text-slate-400"
                          }`}
                        >
                          {s.rotation_path}
                        </div>
                      ) : (
                        <div className="text-[10px] font-normal text-slate-400">{s.next_probable_trend}</div>
                      )}
                    </td>
                    <td className={`num text-right ${s.daily_change_pct >= 0 ? "text-gain" : "text-loss"}`}>
                      {fmtPct(s.daily_change_pct)}
                    </td>
                    <td className="text-right text-slate-200">{s.rs_ratio.toFixed(1)}</td>
                    <td className="text-right text-slate-200">{s.rs_momentum.toFixed(1)}</td>
                    <td className="text-right">
                      <span
                        className={`inline-flex min-w-[2.25rem] justify-center rounded border px-1.5 py-px text-data-xs font-semibold tabular-nums ${suretyTone(
                          s.surety_score,
                        )}`}
                      >
                        {s.surety_score}
                      </span>
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {s.is_stealth_accumulation ? (
                          <span className="whitespace-nowrap rounded border border-violet-500/40 bg-violet-500/15 px-1 py-px text-[10px] leading-3 text-violet-300">
                            Stealth Inflow
                          </span>
                        ) : null}
                        {s.is_price_action_confirmed ? (
                          <span className="whitespace-nowrap rounded border border-emerald-500/40 bg-emerald-500/15 px-1 py-px text-[10px] leading-3 text-emerald-300">
                            Momentum Active
                          </span>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
