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
      <div className="rounded-lg border border-dashed border-surface-border px-3 py-3 text-data-sm text-slate-400">
        Select a symbol to see beginner guidance.
      </div>
    );
  }

  const trendUp = guide.trend === "Uptrend";

  return (
    <div className="flex min-h-0 flex-col">
      <div className="shrink-0 pb-1.5">
        <h3 className="text-[12px] font-semibold text-slate-100">Beginner guide</h3>
        <p className="text-[10px] text-slate-400">Plain English — experimental, can repaint</p>
      </div>

      <div className="min-h-0 flex-1 space-y-2 text-data-sm">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-surface-border/80 bg-black/20 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Current wave</div>
            <div className="mt-0.5 font-medium text-violet-200">{guide.current_wave}</div>
          </div>
          <div className="rounded-lg border border-surface-border/80 bg-black/20 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Trend</div>
            <div
              className={`mt-0.5 font-medium ${trendUp ? "text-emerald-300" : guide.trend === "Downtrend" ? "text-rose-300" : "text-slate-300"}`}
            >
              {guide.trend}
            </div>
            <div className="mt-0.5 text-data-xs text-slate-400">{guide.trend_plain}</div>
          </div>
        </div>

        <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-wide text-sky-400/80">What may come next</div>
          <p className="mt-1 leading-relaxed text-slate-200">{guide.what_next}</p>
        </div>

        <div className="rounded-lg border border-surface-border/80 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">In simple words</div>
          <p className="mt-1 leading-relaxed text-slate-300">{guide.plain_summary}</p>
          {price != null ? (
            <p className="mt-1 text-data-xs text-slate-400">
              Last close ≈ ₹{price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
            </p>
          ) : null}
        </div>

        {guide.levels.length ? (
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">
              Levels to watch (nearest first)
            </div>
            <ul className="space-y-1">
              {guide.levels.map((lv) => (
                <li
                  key={`${lv.label}-${lv.price}`}
                  className="flex flex-wrap items-baseline gap-x-2 rounded border border-surface-border/60 px-2 py-1"
                >
                  <span className={`num ${roleTone(lv.role)}`}>
                    ₹{lv.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                  </span>
                  <span className="text-slate-200">{lv.label}</span>
                  <span className="text-[10px] uppercase text-slate-400">{lv.role}</span>
                  <span className="w-full text-data-xs text-slate-400">{lv.note}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {guide.glossary.length ? (
          <details className="rounded-lg border border-surface-border/60 px-2 py-1">
            <summary className="cursor-pointer text-data-xs font-medium text-slate-300">
              Mini glossary
            </summary>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-data-xs text-slate-400">
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
