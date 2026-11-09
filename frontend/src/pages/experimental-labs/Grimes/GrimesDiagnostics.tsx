import type { GrimesChartPayload } from "@/lib/api";

type Props = { data: GrimesChartPayload | null };

export function GrimesDiagnostics({ data }: Props) {
  const trades = data?.paper_trades ?? [];
  const exp = data?.expectancy;
  const mc = data?.monte_carlo;
  const maxMae = Math.max(2, ...trades.map((t) => t.mae_r ?? 0));
  const maxMfe = Math.max(2, ...trades.map((t) => t.mfe_r ?? 0));
  const w = 420;
  const h = 260;
  const pad = { l: 36, r: 12, t: 16, b: 32 };
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const hist = exp?.histogram ?? [];
  const maxCount = Math.max(1, ...hist.map((b) => b.count));

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Paper n" value={exp?.n ? String(exp.n) : "—"} />
        <Stat
          label="Expectancy"
          value={exp?.expectancy != null ? `${exp.expectancy.toFixed(2)}R` : "—"}
          tone={(exp?.expectancy ?? 0) > 0 ? "pos" : "neg"}
        />
        <Stat
          label="Win rate"
          value={exp?.win_rate != null ? `${(exp.win_rate * 100).toFixed(0)}%` : "—"}
        />
        <Stat
          label="MC p-value"
          value={mc?.p_value != null ? mc.p_value.toFixed(3) : "—"}
          tone={mc?.p_value != null && mc.p_value < 0.1 ? "pos" : "muted"}
        />
      </div>
      {mc?.note ? <p className="text-data-xs text-slate-400">{mc.note}</p> : null}
      {mc?.observed_mean_fwd != null ? (
        <p className="text-data-xs text-slate-300">
          10-bar fwd mean {mc.observed_mean_fwd.toFixed(4)} vs random{" "}
          {mc.random_mean_fwd?.toFixed(4)} (z={mc.z_score?.toFixed(2)}, n={mc.n_patterns})
        </p>
      ) : null}

      <div>
        <h3 className="mb-1 text-[11px] font-medium text-slate-300">MAE vs MFE (paper trades)</h3>
        <p className="mb-1.5 text-data-xs text-slate-400">
          Tight stops show up as winners with MAE near 1R. Leaving profit on the table shows as MFE
          ≫ realized R.
        </p>
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-w-[520px] rounded-lg bg-[#121820]">
          <line
            x1={pad.l}
            y1={pad.t + ih}
            x2={pad.l + iw}
            y2={pad.t + ih}
            stroke="#2a3544"
          />
          <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + ih} stroke="#2a3544" />
          <text x={pad.l + iw / 2} y={h - 6} fill="#64748b" fontSize="10" textAnchor="middle">
            MAE (R)
          </text>
          <text
            x={12}
            y={pad.t + ih / 2}
            fill="#64748b"
            fontSize="10"
            textAnchor="middle"
            transform={`rotate(-90 12 ${pad.t + ih / 2})`}
          >
            MFE (R)
          </text>
          {trades.map((t, i) => {
            const x = pad.l + ((t.mae_r ?? 0) / maxMae) * iw;
            const y = pad.t + ih - ((t.mfe_r ?? 0) / maxMfe) * ih;
            const win = t.r > 0;
            return (
              <circle
                key={`${t.timestamp}-${i}`}
                cx={x}
                cy={y}
                r={3.2}
                fill={win ? "rgb(52 211 153)" : "rgb(251 113 133)"}
                fillOpacity={0.8}
              />
            );
          })}
        </svg>
      </div>

      <div>
        <h3 className="mb-1 text-[11px] font-medium text-slate-300">R-multiple distribution</h3>
        <div className="flex h-28 items-end gap-1 rounded-lg bg-[#121820] px-2 py-2">
          {hist.map((b) => (
            <div key={b.bin} className="flex min-w-0 flex-1 flex-col items-center justify-end">
              <div
                className="w-full rounded-t bg-sky-400/70"
                style={{ height: `${(b.count / maxCount) * 100}%`, minHeight: b.count ? 4 : 0 }}
              />
              <span className="mt-1 block w-full truncate text-center text-[10px] text-slate-400" title={b.bin}>{b.bin}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: string;
  tone?: "pos" | "neg" | "muted";
}) {
  const color =
    tone === "pos" ? "text-emerald-300" : tone === "neg" ? "text-rose-300" : "text-slate-100";
  return (
    <div className="rounded-lg border border-surface-border bg-[#121820] px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`num text-data-md ${color}`}>{value}</div>
    </div>
  );
}
