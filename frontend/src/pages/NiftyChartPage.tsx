import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { NiftyChart } from "@/components/NiftyChart";
import {
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  PageToolbar,
  StatChip,
  ToolbarDivider,
  pctTone,
} from "@/components/dense";
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
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

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

const NIFTY_PREFS_KEY = "trading.nifty.prefs";
type NiftyUiPrefs = {
  timeframe: NiftyTimeframe;
  rsiPeriod: number;
  showBollinger: boolean;
  showRsi: boolean;
};
const DEFAULT_NIFTY_PREFS: NiftyUiPrefs = {
  timeframe: "5m",
  rsiPeriod: DEFAULT_RSI_PERIOD,
  showBollinger: false,
  showRsi: true,
};

export function NiftyChartPage() {
  const initialPrefs = loadUiPrefs(NIFTY_PREFS_KEY, DEFAULT_NIFTY_PREFS);
  const initialTf = (TIMEFRAMES as readonly string[]).includes(initialPrefs.timeframe)
    ? initialPrefs.timeframe
    : "5m";
  const [timeframe, setTimeframe] = useState<NiftyTimeframe>(initialTf);
  const [candles, setCandles] = useState<NiftyCandlePoint[]>([]);
  const [stats, setStats] = useState<NiftyCandleStats | null>(null);
  const [coverage, setCoverage] = useState<NiftyCoverageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("Nifty 50");
  const [rsiPeriod, setRsiPeriod] = useState(Number(initialPrefs.rsiPeriod) || DEFAULT_RSI_PERIOD);
  const [rsiInput, setRsiInput] = useState(String(Number(initialPrefs.rsiPeriod) || DEFAULT_RSI_PERIOD));
  const [showBollinger, setShowBollinger] = useState(Boolean(initialPrefs.showBollinger));
  const [showRsi, setShowRsi] = useState(initialPrefs.showRsi !== false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    saveUiPrefs(NIFTY_PREFS_KEY, {
      timeframe,
      rsiPeriod,
      showBollinger,
      showRsi,
    } satisfies NiftyUiPrefs);
  }, [timeframe, rsiPeriod, showBollinger, showRsi]);

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
    <div className="page-shell flex flex-col gap-1 px-1.5 py-1 sm:px-2">
      <PageToolbar
        right={<AdvancedButton onClick={() => setAdvancedOpen(true)} label="Indicators & sync" />}
        below={
          syncing ? (
            <div className="flex items-center gap-2 text-data-xs text-sky-200">
              <RefreshCw className="h-3 w-3 animate-spin" />
              Syncing from Upstox…
              <div className="h-1 flex-1 overflow-hidden rounded bg-surface">
                <div className="h-full w-1/3 animate-pulse rounded bg-accent/70" />
              </div>
            </div>
          ) : undefined
        }
      >
        <h1 className="shrink-0 text-data-md font-semibold text-slate-100">{label} Chart</h1>
        <div className="flex shrink-0 rounded-md border border-surface-border bg-surface p-0.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              className={`rounded px-2 py-0.5 text-data-sm ${
                timeframe === tf
                  ? "bg-accent/15 text-accent"
                  : "text-slate-300 hover:text-slate-100"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
        <ToolbarDivider />
        <StatChip label="Bars" value={stats?.count?.toLocaleString("en-IN") ?? "—"} />
        <StatChip label="Last" value={formatNum(stats?.last_close)} />
        <StatChip label="High" value={formatNum(stats?.period_high)} hint="Period high" />
        <StatChip label="Low" value={formatNum(stats?.period_low)} hint="Period low" />
        <StatChip
          label="Return"
          value={formatPct(stats?.range_return_pct)}
          hint="Range return"
          valueClassName={pctTone(stats?.range_return_pct)}
        />
        {showRsi && (
          <StatChip
            label={`RSI(${rsiPeriod})`}
            value={
              <>
                {latestRsi != null ? latestRsi.toFixed(1) : "—"}
                {rsiLabel ? (
                  <span className="ml-1 text-data-xs font-normal text-slate-300">{rsiLabel}</span>
                ) : null}
              </>
            }
            valueClassName={rsiStatusClass}
          />
        )}
      </PageToolbar>

      {error && (
        <div className="shrink-0 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-data-sm text-rose-200">
          {error}
        </div>
      )}

      <section className="min-h-[320px] flex-1">
        {loading ? (
          <div className="flex h-full items-center justify-center rounded-lg border border-surface-border bg-surface text-data-sm text-slate-400">
            Loading {timeframe} candles…
          </div>
        ) : candles.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-surface-border bg-surface text-data-sm text-slate-300">
            <p>No {timeframe} data in the database yet.</p>
            <button
              type="button"
              disabled={syncing}
              onClick={() => onSync("current")}
              className="h-7 rounded-md border border-accent/40 bg-accent/10 px-2.5 text-data-sm text-accent disabled:opacity-50"
            >
              Sync {timeframe} from Upstox
            </button>
          </div>
        ) : (
          <NiftyChart
            candles={candles}
            timeframe={timeframe}
            fillHeight
            rsiPeriod={rsiPeriod}
            showRsi={showRsi}
            showBollinger={showBollinger}
          />
        )}
      </section>

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Chart settings"
        subtitle={`${label} · ${timeframe}`}
      >
        <AdvancedSection title="Chart overlays & panels">
          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-1.5 text-data-sm text-slate-200">
              <input
                type="checkbox"
                checked={showRsi}
                onChange={(e) => setShowRsi(e.target.checked)}
                className="rounded border-surface-border"
              />
              RSI
            </label>
            <div
              className={`flex items-center gap-1 pl-5 text-data-xs text-slate-300 ${showRsi ? "" : "opacity-40"}`}
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
                className="h-6 w-14 rounded border border-surface-border bg-surface px-1.5 text-data-sm text-slate-200 disabled:cursor-not-allowed"
              />
              <button
                type="button"
                disabled={!showRsi}
                onClick={applyRsiPeriod}
                className="h-6 rounded border border-surface-border px-1.5 text-data-sm text-slate-300 hover:border-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Apply
              </button>
            </div>
            <label className="flex items-center gap-1.5 text-data-sm text-slate-200">
              <input
                type="checkbox"
                checked={showBollinger}
                onChange={(e) => setShowBollinger(e.target.checked)}
                className="rounded border-surface-border"
              />
              Bollinger (20, 2σ)
            </label>
          </div>
        </AdvancedSection>

        <AdvancedSection title="Jobs">
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={syncing}
              onClick={() => onSync("current")}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-surface-border bg-surface px-2.5 text-data-sm text-slate-200 hover:border-accent/40 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
              Sync {timeframe}
            </button>
            <button
              type="button"
              disabled={syncing}
              onClick={() => onSync("all")}
              className="h-7 rounded-md border border-accent/40 bg-accent/10 px-2.5 text-data-sm text-accent hover:bg-accent/20 disabled:opacity-50"
            >
              Sync all TFs
            </button>
          </div>
        </AdvancedSection>

        <AdvancedSection title="Data">
          <p className="text-data-xs text-slate-300">
            Coverage:{" "}
            {coverageForTf
              ? `${coverageForTf.count.toLocaleString("en-IN")} bars · ${coverageForTf.min_ts ?? "—"} → ${coverageForTf.max_ts ?? "—"}`
              : "no local data yet"}
          </p>
          <p className="text-data-xs leading-relaxed text-slate-400">
            Multi-timeframe OHLC from local DB (`index_candles`). Sync pulls history from Upstox
            (1m / 3m / 5m / 10m / daily).
          </p>
        </AdvancedSection>
      </AdvancedDrawer>
    </div>
  );
}
