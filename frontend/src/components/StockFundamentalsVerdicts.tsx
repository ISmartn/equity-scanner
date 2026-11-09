import type { FundamentalQualityVerdict, MomentumVerdict } from "@/lib/api";

const CHECK_LABELS: Record<string, string> = {
  pat_growth: "Profit growth (PAT)",
  pat_positive: "Profitability (PAT)",
  opm: "Operating margin",
  roe_or_roce: "Return on capital",
  debt_to_equity: "Leverage (D/E)",
  interest_coverage: "Interest coverage",
  cfo_positive: "Operating cash flow",
  eps_positive: "Earnings per share",
};

const SKIP_REASON_LABELS: Record<string, string> = {
  unavailable: "Not reported in filings",
};

function formatSkipReason(raw: string): string {
  if (raw.startsWith("skipped_for_sector:")) {
    const sector = raw.slice("skipped_for_sector:".length);
    return `Not applied for ${sector} (D/E is a weak solvency proxy here)`;
  }
  return SKIP_REASON_LABELS[raw] ?? raw;
}

function formatMetric(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function formatActualThreshold(
  actual: number | null | undefined,
  threshold: number | null | undefined,
  unit?: string,
): string | null {
  if (actual == null && threshold == null) return null;
  const u = unit ?? "";
  const a = actual == null ? "—" : `${formatMetric(actual)}${u}`;
  const t = threshold == null ? "—" : `${formatMetric(threshold)}${u}`;
  return `${a} vs ${t}`;
}

function verdictTone(verdict: FundamentalQualityVerdict | null | undefined): {
  label: string;
  className: string;
} {
  const fallbackLabel = verdict?.label;
  if (!verdict?.available || verdict.pass == null) {
    return {
      label: fallbackLabel || "Insufficient data",
      className: "border-slate-500/40 bg-slate-500/10 text-slate-300",
    };
  }
  if (verdict.strong || verdict.pass) {
    return {
      label: fallbackLabel || "Fundamentally strong",
      className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    };
  }
  return {
    label: fallbackLabel || "Weak fundamentals",
    className: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  };
}

function momentumTone(verdict: MomentumVerdict | null | undefined): {
  label: string;
  className: string;
} {
  const fallbackLabel = verdict?.label;
  if (!verdict?.available || verdict.pass == null) {
    const mixed = fallbackLabel === "Mixed";
    return {
      label: fallbackLabel || "Insufficient quarterly data",
      className: mixed
        ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
        : "border-slate-500/40 bg-slate-500/10 text-slate-300",
    };
  }
  if (verdict.strong) {
    return {
      label: fallbackLabel || "Accelerating",
      className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    };
  }
  if (verdict.pass) {
    return {
      label: fallbackLabel || "Improving",
      className: "border-sky-500/40 bg-sky-500/10 text-sky-300",
    };
  }
  return {
    label: fallbackLabel || "Slowing",
    className: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  };
}

function formatSignedPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatMetric(value)}%`;
}

export function FundamentalVerdictCard({
  verdict,
  compact = false,
}: {
  verdict: FundamentalQualityVerdict | null | undefined;
  compact?: boolean;
}) {
  const tone = verdictTone(verdict);
  const reasons = verdict?.reasons ?? [];
  const failed = reasons.filter((r) => !r.ok);
  const passed = reasons.filter((r) => r.ok);
  const skipped = Object.entries(verdict?.skipped ?? {});
  const metrics = verdict?.metrics ?? {};
  const summary =
    verdict?.summary ||
    (!verdict?.available
      ? "No fundamentals loaded yet. Sync this ticker to build a quality view."
      : "Quality checks are still warming up.");

  return (
    <section
      className={`rounded-lg border border-surface-border bg-surface/50 ${compact ? "p-2" : "p-3"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Fundamental verdict</div>
          <div
            className={`mt-1 inline-flex rounded-md border px-2.5 py-1 ${compact ? "text-xs" : "text-sm"} font-medium ${tone.className}`}
          >
            {tone.label}
          </div>
          {!compact ? (
            <p className="mt-2 max-w-2xl text-xs leading-relaxed text-slate-300">{summary}</p>
          ) : (
            <p className="mt-1 text-[10px] leading-snug text-slate-400">{summary}</p>
          )}
        </div>
        {verdict?.sector && (
          <div className="text-right text-[11px] text-slate-500">
            Sector
            <div className="text-slate-300">{verdict.sector}</div>
          </div>
        )}
      </div>

      {!compact && failed.length > 0 && (
        <div className="mt-3 rounded-md border border-rose-500/25 bg-rose-500/5 p-2.5">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-rose-300/80">
            Why it falls short
          </div>
          <ul className="space-y-2">
            {failed.map((reason) => (
              <li key={reason.id} className="text-xs text-slate-200">
                <div className="font-medium text-rose-200">{reason.title}</div>
                <div className="mt-0.5 leading-relaxed text-slate-400">{reason.message}</div>
                {formatActualThreshold(reason.actual, reason.threshold, reason.unit) && (
                  <div className="mt-0.5 font-mono text-[10px] text-slate-500">
                    {formatActualThreshold(reason.actual, reason.threshold, reason.unit)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!compact && passed.length > 0 && (
        <div className="mt-3 rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2.5">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-emerald-300/80">
            What looks solid
          </div>
          <ul className="space-y-1.5">
            {passed.map((reason) => (
              <li key={reason.id} className="text-xs text-slate-300">
                <span className="font-medium text-emerald-200">{reason.title}: </span>
                <span className="text-slate-400">{reason.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={`mt-2 grid gap-2 ${compact ? "grid-cols-2" : "sm:grid-cols-4"}`}>
        {(
          [
            ["ROE %", metrics.roe],
            ["ROCE %", metrics.roce],
            ["PAT growth %", metrics.pat_growth_pct],
            ["OPM %", metrics.opm_pct],
            ["D/E", metrics.debt_to_equity],
            ["ICR", metrics.interest_coverage],
            ["EPS", metrics.eps],
            ["CFO", metrics.cfo],
          ] as const
        ).map(([label, value]) => (
          <div
            key={label}
            className="rounded-md border border-surface-border/70 bg-surface/40 px-2 py-1.5"
          >
            <div className="text-[10px] text-slate-500">{label}</div>
            <div className="font-mono text-xs text-slate-200">{formatMetric(value)}</div>
          </div>
        ))}
      </div>

      {!compact && skipped.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Not scored</div>
          <ul className="space-y-1">
            {skipped.map(([key, reason]) => (
              <li key={key} className="flex items-start justify-between gap-2 text-xs text-slate-500">
                <span>{CHECK_LABELS[key] ?? key}</span>
                <span className="max-w-[60%] text-right text-[10px] leading-snug">
                  {formatSkipReason(reason)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function MomentumVerdictCard({
  verdict,
  compact = false,
}: {
  verdict: MomentumVerdict | null | undefined;
  compact?: boolean;
}) {
  const tone = momentumTone(verdict);
  const metrics = verdict?.metrics ?? {};
  const quarters = verdict?.quarters ?? [];
  const reasons = verdict?.reasons ?? [];
  const failed = reasons.filter((r) => !r.ok);
  const passed = reasons.filter((r) => r.ok);
  const summary =
    verdict?.summary ||
    (!verdict?.available
      ? "Sync this ticker to load quarterly filings for a momentum read."
      : "Quarterly momentum is still warming up.");

  return (
    <section
      className={`rounded-lg border border-surface-border bg-surface/50 ${compact ? "p-2" : "p-3"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            Earnings momentum
          </div>
          <div
            className={`mt-1 inline-flex rounded-md border px-2.5 py-1 ${compact ? "text-xs" : "text-sm"} font-medium ${tone.className}`}
          >
            {tone.label}
          </div>
          {!compact ? (
            <p className="mt-2 max-w-2xl text-xs leading-relaxed text-slate-300">{summary}</p>
          ) : (
            <p className="mt-1 text-[10px] leading-snug text-slate-400">{summary}</p>
          )}
        </div>
        {typeof metrics.latest_period === "string" && metrics.latest_period && (
          <div className="text-right text-[11px] text-slate-500">
            Latest quarter
            <div className="text-slate-300">{metrics.latest_period}</div>
          </div>
        )}
      </div>

      <div className={`mt-2 grid gap-2 ${compact ? "grid-cols-2" : "sm:grid-cols-3"}`}>
        {(
          [
            ["PAT YoY", metrics.pat_yoy_pct],
            ["PAT QoQ", metrics.pat_qoq_pct],
            ["Revenue YoY", metrics.revenue_yoy_pct],
            ["Revenue QoQ", metrics.revenue_qoq_pct],
            ["OP QoQ", metrics.operating_profit_qoq_pct],
            ["PAT QoQ streak", metrics.pat_qoq_streak],
          ] as const
        ).map(([label, value]) => (
          <div
            key={label}
            className="rounded-md border border-surface-border/70 bg-surface/40 px-2 py-1.5"
          >
            <div className="text-[10px] text-slate-500">{label}</div>
            <div className="font-mono text-xs text-slate-200">
              {label.includes("streak")
                ? value == null
                  ? "—"
                  : String(value)
                : formatSignedPct(typeof value === "number" ? value : null)}
            </div>
          </div>
        ))}
      </div>

      {!compact && quarters.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-slate-500">
            Quarter vs prior quarter
          </div>
          <table className="w-full min-w-[22rem] border-collapse text-left text-[11px]">
            <thead>
              <tr className="text-slate-500">
                <th className="pb-1 pr-2 font-medium">Period</th>
                <th className="pb-1 pr-2 font-medium">Rev QoQ</th>
                <th className="pb-1 pr-2 font-medium">OP QoQ</th>
                <th className="pb-1 font-medium">PAT QoQ</th>
              </tr>
            </thead>
            <tbody>
              {quarters.map((row) => (
                <tr key={row.period} className="border-t border-surface-border/60 text-slate-300">
                  <td className="py-1 pr-2 font-medium text-slate-200">{row.period}</td>
                  <td className="py-1 pr-2 font-mono">{formatSignedPct(row.revenue_qoq_pct)}</td>
                  <td className="py-1 pr-2 font-mono">
                    {formatSignedPct(row.operating_profit_qoq_pct)}
                  </td>
                  <td className="py-1 font-mono">{formatSignedPct(row.net_profit_qoq_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!compact && failed.length > 0 && (
        <div className="mt-3 rounded-md border border-rose-500/25 bg-rose-500/5 p-2.5">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-rose-300/80">
            Soft prints
          </div>
          <ul className="space-y-1.5">
            {failed.map((reason) => (
              <li key={reason.id} className="text-xs text-slate-300">
                <span className="font-medium text-rose-200">{reason.title}: </span>
                <span className="text-slate-400">{reason.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!compact && passed.length > 0 && (
        <div className="mt-3 rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2.5">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-emerald-300/80">
            Constructive prints
          </div>
          <ul className="space-y-1.5">
            {passed.map((reason) => (
              <li key={reason.id} className="text-xs text-slate-300">
                <span className="font-medium text-emerald-200">{reason.title}: </span>
                <span className="text-slate-400">{reason.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
