import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { StockFundamentalsPanel } from "@/components/StockFundamentalsPanel";
import { StockTickerSearch } from "@/components/StockTickerSearch";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import {
  fetchStockFundamentals,
  fetchTimelineCandles,
  syncStockFundamentals,
  type FundamentalQualityVerdict,
  type MomentumVerdict,
  type StockFundamentals,
  type TimelineCandlePoint,
} from "@/lib/api";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

const PREFS_KEY = "trading.stockResearch.prefs";
type Prefs = { ticker: string };
const DEFAULT_PREFS: Prefs = { ticker: "" };

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

function companyNameFromFundamentals(data: StockFundamentals | null): string | null {
  const profile = data?.profile;
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return null;
  const obj = profile as Record<string, unknown>;
  const nested =
    obj.data && typeof obj.data === "object" && !Array.isArray(obj.data)
      ? (obj.data as Record<string, unknown>)
      : obj;
  for (const key of ["company_name", "companyName", "name", "short_name"]) {
    const v = nested[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

function sectorFromFundamentals(data: StockFundamentals | null): string | null {
  const fromVerdict = data?.quality_verdict?.sector;
  if (typeof fromVerdict === "string" && fromVerdict.trim()) return fromVerdict.trim();
  const profile = data?.profile;
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return null;
  const obj = profile as Record<string, unknown>;
  const nested =
    obj.data && typeof obj.data === "object" && !Array.isArray(obj.data)
      ? (obj.data as Record<string, unknown>)
      : obj;
  const v = nested.sector ?? nested.industry;
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

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

function FundamentalVerdictCard({
  verdict,
}: {
  verdict: FundamentalQualityVerdict | null | undefined;
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
    <section className="rounded-lg border border-surface-border bg-surface/50 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Fundamental verdict</div>
          <div className={`mt-1 inline-flex rounded-md border px-2.5 py-1 text-sm font-medium ${tone.className}`}>
            {tone.label}
          </div>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-slate-300">{summary}</p>
        </div>
        {verdict?.sector && (
          <div className="text-right text-[11px] text-slate-500">
            Sector
            <div className="text-slate-300">{verdict.sector}</div>
          </div>
        )}
      </div>

      {failed.length > 0 && (
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

      {passed.length > 0 && (
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

      <div className="mt-3 grid gap-2 sm:grid-cols-4">
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
          <div key={label} className="rounded-md border border-surface-border/70 bg-surface/40 px-2 py-1.5">
            <div className="text-[10px] text-slate-500">{label}</div>
            <div className="font-mono text-xs text-slate-200">{formatMetric(value)}</div>
          </div>
        ))}
      </div>

      {skipped.length > 0 && (
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

function MomentumVerdictCard({
  verdict,
}: {
  verdict: MomentumVerdict | null | undefined;
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
    <section className="rounded-lg border border-surface-border bg-surface/50 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            Earnings momentum
          </div>
          <div className={`mt-1 inline-flex rounded-md border px-2.5 py-1 text-sm font-medium ${tone.className}`}>
            {tone.label}
          </div>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-slate-300">{summary}</p>
        </div>
        {typeof metrics.latest_period === "string" && metrics.latest_period && (
          <div className="text-right text-[11px] text-slate-500">
            Latest quarter
            <div className="text-slate-300">{metrics.latest_period}</div>
          </div>
        )}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
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
          <div key={label} className="rounded-md border border-surface-border/70 bg-surface/40 px-2 py-1.5">
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

      {quarters.length > 0 && (
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

      {failed.length > 0 && (
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

      {passed.length > 0 && (
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

export function StockResearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialPrefs = loadUiPrefs(PREFS_KEY, DEFAULT_PREFS);
  const paramTicker = (searchParams.get("ticker") || "").trim().toUpperCase();
  const [ticker, setTicker] = useState(paramTicker || initialPrefs.ticker || "");

  const [history, setHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [fundamentalsLoading, setFundamentalsLoading] = useState(false);
  const [fundamentalsError, setFundamentalsError] = useState<string | null>(null);
  const [fundamentalsSyncing, setFundamentalsSyncing] = useState(false);

  useEffect(() => {
    saveUiPrefs(PREFS_KEY, { ticker } satisfies Prefs);
  }, [ticker]);

  useEffect(() => {
    if (paramTicker && paramTicker !== ticker) {
      setTicker(paramTicker);
    }
    // Only react to URL ticker changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramTicker]);

  const loadChart = useCallback(async (symbol: string) => {
    setChartLoading(true);
    setChartError(null);
    try {
      const payload = await fetchTimelineCandles(symbol);
      setHistory(payload.history ?? []);
      setChartSource(payload.source ?? "local");
    } catch (exc) {
      setHistory([]);
      setChartError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setChartLoading(false);
    }
  }, []);

  const loadFundamentals = useCallback(async (symbol: string) => {
    setFundamentalsLoading(true);
    setFundamentalsError(null);
    try {
      const payload = await fetchStockFundamentals(symbol, true);
      setFundamentals(payload);
    } catch (exc) {
      setFundamentals(null);
      setFundamentalsError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setFundamentalsLoading(false);
    }
  }, []);

  useEffect(() => {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) {
      setHistory([]);
      setFundamentals(null);
      setChartError(null);
      setFundamentalsError(null);
      return;
    }
    void loadChart(symbol);
    void loadFundamentals(symbol);
  }, [ticker, loadChart, loadFundamentals]);

  const onTickerChange = (next: string) => {
    const symbol = next.trim().toUpperCase();
    setTicker(symbol);
    if (symbol) {
      setSearchParams({ ticker: symbol }, { replace: true });
    } else {
      setSearchParams({}, { replace: true });
    }
  };

  const handleSyncFundamentals = async () => {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return;
    setFundamentalsSyncing(true);
    setFundamentalsError(null);
    try {
      await syncStockFundamentals([symbol], true);
      await loadFundamentals(symbol);
    } catch (exc) {
      setFundamentalsError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setFundamentalsSyncing(false);
    }
  };

  const companyName = useMemo(() => companyNameFromFundamentals(fundamentals), [fundamentals]);
  const sector = useMemo(() => sectorFromFundamentals(fundamentals), [fundamentals]);
  const highlightDate = history.length ? history[history.length - 1].date : "";
  const lastClose = history.length ? history[history.length - 1].close : null;
  const lastMove = history.length ? history[history.length - 1].daily_return_pct ?? null : null;

  return (
    <main className="mx-auto flex min-h-[calc(100vh-7rem)] max-w-[1600px] flex-col gap-3 px-3 py-3 sm:px-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Stock Research</h1>
          <p className="max-w-2xl text-xs text-slate-500">
            Search a stock for price + RSI, company financials, quality verdict, and quarterly momentum.
          </p>
        </div>
        <div className="flex min-w-[16rem] flex-1 flex-wrap items-end justify-end gap-2 sm:max-w-md">
          <div className="min-w-[14rem] flex-1">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Stock</div>
            <StockTickerSearch
              value={ticker}
              onChange={onTickerChange}
              placeholder="Search ticker or company…"
            />
          </div>
          <button
            type="button"
            disabled={!ticker || fundamentalsSyncing}
            onClick={() => void handleSyncFundamentals()}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-surface-border bg-surface px-3 text-xs text-slate-300 hover:border-accent/40 disabled:opacity-50"
            title="Force-refresh fundamentals from Upstox"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${fundamentalsSyncing ? "animate-spin" : ""}`} />
            Sync
          </button>
        </div>
      </div>

      {!ticker ? (
        <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-surface-border px-4 py-16 text-center text-sm text-slate-500">
          Search a ticker to open its chart, results, and fundamental verdict.
        </div>
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.9fr)]">
          <section className="flex h-[32rem] flex-col gap-2 rounded-lg border border-surface-border bg-surface/30 p-2 lg:h-[36rem]">
            <div className="flex flex-wrap items-center justify-between gap-2 px-1">
              <div>
                <div className="text-sm font-medium text-slate-100">
                  {ticker}
                  {companyName ? <span className="text-slate-400"> · {companyName}</span> : null}
                </div>
                <div className="text-[11px] text-slate-500">
                  {sector ?? "—"}
                  {typeof lastClose === "number"
                    ? ` · ₹${lastClose.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
                    : ""}
                  {typeof lastMove === "number"
                    ? ` · ${lastMove >= 0 ? "+" : ""}${lastMove.toFixed(2)}%`
                    : ""}
                </div>
              </div>
            </div>
            {chartError && (
              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-200">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{chartError}</span>
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-hidden">
              <TimelineStockChart
                symbol={ticker}
                companyName={companyName}
                sector={sector}
                source={chartSource}
                history={history}
                highlightDate={highlightDate}
                highlightMovePct={lastMove}
                loading={chartLoading}
                fillHeight
                tailVisibleRange
                showRsi
              />
            </div>
          </section>

          <aside className="flex flex-col gap-3 lg:max-h-[calc(100vh-9rem)] lg:overflow-y-auto">
            <FundamentalVerdictCard verdict={fundamentals?.quality_verdict} />
            <MomentumVerdictCard verdict={fundamentals?.momentum_verdict} />
            <div className="min-h-[22rem]">
              <StockFundamentalsPanel
                data={fundamentals}
                loading={fundamentalsLoading}
                error={fundamentalsError}
                syncing={fundamentalsSyncing}
                onSync={() => void handleSyncFundamentals()}
                sidebar
              />
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
