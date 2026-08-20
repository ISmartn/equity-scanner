import type { ElliottWaveGuide } from "@/lib/api";

type Props = {
  guide: ElliottWaveGuide | null | undefined;
  price?: number | null;
};

function roleTone(role: string): string {
  if (role === "target") return "text-sky-300";
  if (role === "support") return "text-emerald-300";
  if (role === "resistance") return "text-amber-300";
  if (role === "invalidation") return "text-rose-300";
  return "text-slate-300";
}

export function WaveBeginnerGuide({ guide, price }: Props) {
  if (!guide) {
    return (
      <div className="rounded-xl border border-dashed border-surface-border bg-surface-raised px-3 py-4 text-[11px] text-slate-500">
        Select a symbol to see beginner guidance.
      </div>
    );
  }

  const trendUp = guide.trend === "Uptrend";

  return (
    <div className="flex max-h-full min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="shrink-0 border-b border-surface-border px-3 py-2">
        <h3 className="text-[12px] font-semibold text-slate-100">Beginner guide</h3>
        <p className="text-[9px] text-slate-500">Plain English — experimental, can repaint</p>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-auto px-3 py-2.5 text-[11px]">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-surface-border/80 bg-black/20 px-2.5 py-2">
            <div className="text-[9px] uppercase tracking-wide text-slate-500">Current wave</div>
            <div className="mt-0.5 font-medium text-violet-200">{guide.current_wave}</div>
          </div>
          <div className="rounded-lg border border-surface-border/80 bg-black/20 px-2.5 py-2">
            <div className="text-[9px] uppercase tracking-wide text-slate-500">Trend</div>
            <div
              className={`mt-0.5 font-medium ${trendUp ? "text-emerald-300" : guide.trend === "Downtrend" ? "text-rose-300" : "text-slate-300"}`}
            >
              {guide.trend}
            </div>
            <div className="mt-0.5 text-[10px] text-slate-500">{guide.trend_plain}</div>
          </div>
        </div>

        <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 px-2.5 py-2">
          <div className="text-[9px] uppercase tracking-wide text-sky-400/80">What may come next</div>
          <p className="mt-1 leading-relaxed text-slate-200">{guide.what_next}</p>
        </div>

        <div className="rounded-lg border border-surface-border/80 px-2.5 py-2">
          <div className="text-[9px] uppercase tracking-wide text-slate-500">In simple words</div>
          <p className="mt-1 leading-relaxed text-slate-300">{guide.plain_summary}</p>
          {price != null ? (
            <p className="mt-1 text-[10px] text-slate-500">
              Last close ≈ ₹{price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
            </p>
          ) : null}
        </div>

        {guide.levels.length ? (
          <div>
            <div className="mb-1 text-[9px] uppercase tracking-wide text-slate-500">
              Levels to watch (nearest first)
            </div>
            <ul className="space-y-1">
              {guide.levels.map((lv) => (
                <li
                  key={`${lv.label}-${lv.price}`}
                  className="flex flex-wrap items-baseline gap-x-2 rounded border border-surface-border/60 px-2 py-1"
                >
                  <span className={`font-medium ${roleTone(lv.role)}`}>
                    ₹{lv.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                  </span>
                  <span className="text-slate-200">{lv.label}</span>
                  <span className="text-[9px] uppercase text-slate-600">{lv.role}</span>
                  <span className="w-full text-[10px] text-slate-500">{lv.note}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {guide.glossary.length ? (
          <details className="rounded-lg border border-surface-border/60 px-2.5 py-1.5">
            <summary className="cursor-pointer text-[10px] font-medium text-slate-400">
              Mini glossary
            </summary>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[10px] text-slate-500">
              {guide.glossary.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </div>
  );
}
