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
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 z-10 bg-surface-raised text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2">
                <SortBtn k="name" label="Sector" />
              </th>
              <th className="px-2 py-2">Quadrant</th>
              <th className="px-2 py-2 text-right">
                <SortBtn k="daily_change_pct" label="Day %" />
              </th>
              <th className="px-2 py-2 text-right">
                <SortBtn k="rs_ratio" label="RS-R" />
              </th>
              <th className="px-2 py-2 text-right">RS-M</th>
              <th className="px-2 py-2 text-right">
                <SortBtn k="surety_score" label="Surety" />
              </th>
              <th className="px-2 py-2">Flags</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-[11px] text-slate-500">
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
                    className={`cursor-pointer border-t border-surface-border/70 transition ${
                      selected ? "bg-accent/10 hover:bg-accent/15" : "hover:bg-white/5"
                    }`}
                  >
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <div className="text-[11px] font-medium text-slate-100">{s.name}</div>
                        {s.category === "Official" ? (
                          <span className="shrink-0 rounded border border-amber-400/50 bg-amber-500/15 px-1 py-px text-[8px] font-semibold uppercase tracking-wide text-amber-200">
                            Index
                          </span>
                        ) : (
                          <span className="shrink-0 rounded border border-slate-500/40 bg-slate-500/10 px-1 py-px text-[8px] uppercase tracking-wide text-slate-400">
                            Theme
                          </span>
                        )}
                      </div>
                      <div className="text-[9px] text-slate-500">
                        {s.breadth_pct_above_50sma != null
                          ? `${s.breadth_pct_above_50sma.toFixed(0)}% >50SMA`
                          : s.category}
                      </div>
                    </td>
                    <td className={`px-2 py-1.5 text-[10px] font-medium ${quadrantTone(s.quadrant)}`}>
                      <div>{s.quadrant}</div>
                      {s.rotation_path ? (
                        <div
                          className={`text-[8px] font-normal ${
                            s.rotation_bias === "clockwise"
                              ? "text-amber-300/90"
                              : s.rotation_bias === "counter"
                                ? "text-emerald-300/90"
                                : "text-slate-500"
                          }`}
                        >
                          {s.rotation_path}
                        </div>
                      ) : (
                        <div className="text-[8px] font-normal text-slate-500">{s.next_probable_trend}</div>
                      )}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums text-[11px] ${
                        s.daily_change_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {fmtPct(s.daily_change_pct)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-[11px] text-slate-300">
                      {s.rs_ratio.toFixed(1)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-[11px] text-slate-300">
                      {s.rs_momentum.toFixed(1)}
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <span
                        className={`inline-flex min-w-[2.25rem] justify-center rounded border px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${suretyTone(
                          s.surety_score,
                        )}`}
                      >
                        {s.surety_score}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {s.is_stealth_accumulation ? (
                          <span className="rounded border border-violet-500/40 bg-violet-500/15 px-1 py-px text-[8px] text-violet-300">
                            Stealth Inflow
                          </span>
                        ) : null}
                        {s.is_price_action_confirmed ? (
                          <span className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1 py-px text-[8px] text-emerald-300">
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
