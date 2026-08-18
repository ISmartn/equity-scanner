import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { NiftyChart } from "@/components/NiftyChart";
import {
  fetchNiftyCandles,
  fetchNiftyStatus,
  syncNiftyCandles,
  type NiftyCandlePoint,
  type NiftyCandleStats,
  type NiftyCoverageRow,
  type NiftyTimeframe,
} from "@/lib/api";
import { rsiStatus, wildersRsiSeries } from "@/lib/indicators";

const TIMEFRAMES: NiftyTimeframe[] = ["1m", "3m", "5m", "10m", "daily"];
const DEFAULT_RSI_PERIOD = 19;

const LIMIT_BY_TF: Record<NiftyTimeframe, number> = {
  "1m": 2000,
  "3m": 2000,
  "5m": 2000,
  "10m": 2000,
  daily: 2000,
};

function formatNum(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function NiftyChartPage() {
  const [timeframe, setTimeframe] = useState<NiftyTimeframe>("5m");
  const [candles, setCandles] = useState<NiftyCandlePoint[]>([]);
  const [stats, setStats] = useState<NiftyCandleStats | null>(null);
  const [coverage, setCoverage] = useState<NiftyCoverageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("Nifty 50");
  const [rsiPeriod, setRsiPeriod] = useState(DEFAULT_RSI_PERIOD);
  const [rsiInput, setRsiInput] = useState(String(DEFAULT_RSI_PERIOD));
  const [showBollinger, setShowBollinger] = useState(false);
  const [showRsi, setShowRsi] = useState(true);

  const latestRsi = useMemo(() => {
    if (candles.length < rsiPeriod + 1) return null;
    const closes = candles.map((c) => c.close);
    const series = wildersRsiSeries(closes, rsiPeriod);
    return series.length ? series[series.length - 1] : null;
  }, [candles, rsiPeriod]);

  const rsiLabel = rsiStatus(latestRsi);

  const coverageForTf = useMemo(
    () => coverage.find((row) => row.timeframe === timeframe),
    [coverage, timeframe],
  );

  const refreshStatus = useCallback(async () => {
    const status = await fetchNiftyStatus();
    setCoverage(status.coverage);
    setLabel(status.instrument_label);
  }, []);

  const loadCandles = useCallback(async (tf: NiftyTimeframe) => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchNiftyCandles({
        timeframe: tf,
        limit: LIMIT_BY_TF[tf],
      });
      setCandles(payload.candles);
      setStats(payload.stats);
      setLabel(payload.instrument_label);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setCandles([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshStatus().catch(() => undefined);
  }, [refreshStatus]);

  useEffect(() => {
    void loadCandles(timeframe);
  }, [timeframe, loadCandles]);

  const onSync = async (scope: "current" | "all") => {
    setSyncing(true);
    setError(null);
    try {
      await syncNiftyCandles({
        timeframes: scope === "current" ? [timeframe] : TIMEFRAMES,
      });
      await refreshStatus();
      await loadCandles(timeframe);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSyncing(false);
    }
  };

  const applyRsiPeriod = () => {
    const p = Number(rsiInput);
    if (!Number.isFinite(p) || p < 1 || p > 200) {
      setError("RSI period must be between 1 and 200");
      return;
    }
    setError(null);
    setRsiPeriod(p);
  };

  const rsiStatusClass =
    rsiLabel === "Overbought"
      ? "text-rose-300"
      : rsiLabel === "Oversold"
        ? "text-emerald-300"
        : rsiLabel === "Warming"
          ? "text-amber-300"
          : "text-slate-300";

  return (
    <main className="mx-auto max-w-6xl space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">{label} Chart</h1>
          <p className="max-w-2xl text-xs text-slate-500">
            Multi-timeframe OHLC from local DB (`index_candles`). Sync pulls history from Upstox
            (1m / 3m / 5m / 10m / daily).
          </p>
          <p className="mt-1 text-[10px] text-slate-600">
            Coverage:{" "}
            {coverageForTf
              ? `${coverageForTf.count.toLocaleString("en-IN")} bars · ${coverageForTf.min_ts ?? "—"} → ${coverageForTf.max_ts ?? "—"}`
              : "no local data yet"}
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1 rounded-md border border-surface-border bg-surface px-2 py-1.5">
            <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
              Indicators
            </span>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={showRsi}
                  onChange={(e) => setShowRsi(e.target.checked)}
                  className="rounded border-surface-border"
                />
                RSI
              </label>
              <label className="flex items-center gap-1.5 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={showBollinger}
                  onChange={(e) => setShowBollinger(e.target.checked)}
                  className="rounded border-surface-border"
                />
                Bollinger (20, 2σ)
              </label>
              <div
                className={`flex items-center gap-1 text-[10px] text-slate-500 ${showRsi ? "" : "opacity-40"}`}
              >
                Period
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={rsiInput}
                  disabled={!showRsi}
                  onChange={(e) => setRsiInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") applyRsiPeriod();
                  }}
                  className="w-12 rounded border border-surface-border bg-surface px-1.5 py-0.5 text-xs text-slate-200 disabled:cursor-not-allowed"
                />
                <button
                  type="button"
                  disabled={!showRsi}
                  onClick={applyRsiPeriod}
                  className="rounded border border-surface-border px-1.5 py-0.5 text-xs text-slate-300 hover:border-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Apply
                </button>
              </div>
            </div>
          </div>
          <div className="flex rounded-md border border-surface-border bg-surface p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                onClick={() => setTimeframe(tf)}
                className={`rounded px-2.5 py-1.5 text-xs ${
                  timeframe === tf
                    ? "bg-accent/15 text-accent"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={syncing}
            onClick={() => onSync("current")}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-slate-200 hover:border-accent/40 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
            Sync {timeframe}
          </button>
          <button
            type="button"
            disabled={syncing}
            onClick={() => onSync("all")}
            className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            Sync all TFs
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      <div className={`grid grid-cols-2 gap-2 ${showRsi ? "sm:grid-cols-6" : "sm:grid-cols-5"}`}>
        <Stat label="Bars" value={stats?.count?.toLocaleString("en-IN") ?? "—"} />
        <Stat label="Last close" value={formatNum(stats?.last_close)} />
        <Stat label="Period high" value={formatNum(stats?.period_high)} />
        <Stat label="Period low" value={formatNum(stats?.period_low)} />
        <Stat label="Range return" value={formatPct(stats?.range_return_pct)} />
        {showRsi && (
          <Stat
            label={`RSI(${rsiPeriod})`}
            value={latestRsi != null ? latestRsi.toFixed(1) : "—"}
            valueClass={rsiStatusClass}
            sub={rsiLabel}
          />
        )}
      </div>

      {loading ? (
        <div className="flex h-[540px] items-center justify-center rounded-lg border border-surface-border bg-surface text-sm text-slate-500">
          Loading {timeframe} candles…
        </div>
      ) : candles.length === 0 ? (
        <div className="flex h-[540px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-surface-border bg-surface text-sm text-slate-400">
          <p>No {timeframe} data in the database yet.</p>
          <button
            type="button"
            disabled={syncing}
            onClick={() => onSync("current")}
            className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent disabled:opacity-50"
          >
            Sync {timeframe} from Upstox
          </button>
        </div>
      ) : (
        <NiftyChart
          candles={candles}
          timeframe={timeframe}
          height={540}
          rsiPeriod={rsiPeriod}
          showRsi={showRsi}
          showBollinger={showBollinger}
        />
      )}
    </main>
  );
}

function Stat({
  label,
  value,
  valueClass,
  sub,
}: {
  label: string;
  value: string;
  valueClass?: string;
  sub?: string;
}) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-0.5 text-sm font-medium ${valueClass ?? "text-slate-100"}`}>{value}</div>
      {sub ? <div className="text-[10px] text-slate-500">{sub}</div> : null}
    </div>
  );
}
