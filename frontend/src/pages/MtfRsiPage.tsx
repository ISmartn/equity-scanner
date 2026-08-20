import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Database, Radio, RefreshCw } from "lucide-react";
import { NiftyChart } from "@/components/NiftyChart";
import {
  fetchMtfRsiCandles,
  fetchMtfRsiChart,
  fetchMtfRsiSnapshot,
  fetchMtfRsiStatus,
  seedMtfRsi,
  setMtfRsiPeriod,
  startMtfRsiStream,
  stopMtfRsiStream,
  type MtfRsiCandlePoint,
  type MtfRsiChartPayload,
  type MtfRsiSnapshot,
  type MtfRsiStatus,
} from "@/lib/api";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

const RSI_TF_COLORS: Record<number, string> = {
  1: "#38bdf8",
  3: "#a78bfa",
  5: "#34d399",
  10: "#fbbf24",
  15: "#fb7185",
};

const RSI_PRESETS = [9, 14, 21, 50] as const;
const ALL_TFS = [1, 3, 5, 10, 15] as const;
const POLL_MS_LIVE = 1000;
const POLL_MS_IDLE = 5000;
/** Rare check while closed — mainly to notice session open / stream state. */
const POLL_MS_CLOSED = 60_000;
/** Heavy OHLC/RSI series — avoid refetching multi-year payloads every tick. */
const CHART_POLL_MS_LIVE = 30_000;

function statusClass(status: string): string {
  switch (status) {
    case "Overbought":
      return "border-rose-500/40 bg-rose-500/10 text-rose-300";
    case "Oversold":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "Warming":
      return "border-amber-500/40 bg-amber-500/10 text-amber-300";
    default:
      return "border-surface-border bg-surface text-slate-300";
  }
}

function formatTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      day: "2-digit",
      month: "short",
    });
  } catch {
    return iso;
  }
}

const MTF_PREFS_KEY = "trading.mtfRsi.prefs";
type MtfUiPrefs = { rsiPeriod: number; priceTf: number; visibleRsiTfs: number[] };
const DEFAULT_MTF_PREFS: MtfUiPrefs = {
  rsiPeriod: 14,
  priceTf: 5,
  visibleRsiTfs: [...ALL_TFS],
};

export function MtfRsiPage() {
  const initialPrefs = loadUiPrefs(MTF_PREFS_KEY, DEFAULT_MTF_PREFS);
  const [rsiPeriod, setRsiPeriod] = useState(Number(initialPrefs.rsiPeriod) || 14);
  const [customPeriod, setCustomPeriod] = useState(String(Number(initialPrefs.rsiPeriod) || 14));
  const initialPriceTf = (ALL_TFS as readonly number[]).includes(Number(initialPrefs.priceTf))
    ? Number(initialPrefs.priceTf)
    : 5;
  const [priceTf, setPriceTf] = useState(initialPriceTf);
  const [visibleRsiTfs, setVisibleRsiTfs] = useState<number[]>(
    Array.isArray(initialPrefs.visibleRsiTfs) && initialPrefs.visibleRsiTfs.length
      ? initialPrefs.visibleRsiTfs.filter((n) => (ALL_TFS as readonly number[]).includes(n))
      : [...ALL_TFS],
  );
  const [priceCandles, setPriceCandles] = useState<MtfRsiCandlePoint[]>([]);
  const [rsiChart, setRsiChart] = useState<MtfRsiChartPayload | null>(null);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<MtfRsiStatus | null>(null);
  const [snapshot, setSnapshot] = useState<MtfRsiSnapshot | null>(null);
  const timerRef = useRef<number | null>(null);
  const chartTimerRef = useRef<number | null>(null);
  const priceTfRef = useRef(priceTf);
  priceTfRef.current = priceTf;

  const refreshCharts = useCallback(async () => {
    try {
      const [candlesPayload, chartPayload] = await Promise.all([
        fetchMtfRsiCandles(priceTfRef.current),
        fetchMtfRsiChart(),
      ]);
      setPriceCandles(candlesPayload.candles ?? []);
      setRsiChart(chartPayload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  const refresh = useCallback(async (opts?: { charts?: boolean }) => {
    try {
      const [st, snap] = await Promise.all([fetchMtfRsiStatus(), fetchMtfRsiSnapshot()]);
      setStatus(st);
      setSnapshot(snap);
      const connected = st.status === "connected" || st.status === "connecting";
      setLive(connected);
      if (typeof st.rsi_period === "number") {
        setRsiPeriod(st.rsi_period);
        setCustomPeriod(String(st.rsi_period));
      }
      if (opts?.charts !== false) {
        await refreshCharts();
      }
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [refreshCharts]);

  useEffect(() => {
    void refresh({ charts: true });
  }, [refresh]);

  useEffect(() => {
    saveUiPrefs(MTF_PREFS_KEY, { rsiPeriod, priceTf, visibleRsiTfs } satisfies MtfUiPrefs);
  }, [rsiPeriod, priceTf, visibleRsiTfs]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await fetchMtfRsiCandles(priceTf);
        if (!cancelled) setPriceCandles(payload.candles ?? []);
      } catch {
        if (!cancelled) setPriceCandles([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [priceTf]);

  const toggleRsiTf = (tf: number) => {
    setVisibleRsiTfs((prev) => {
      if (prev.includes(tf)) {
        if (prev.length === 1) return prev;
        return prev.filter((x) => x !== tf);
      }
      return [...prev, tf].sort((a, b) => a - b);
    });
  };

  const rsiOverlays = useMemo(() => {
    const series = rsiChart?.series ?? {};
    return visibleRsiTfs.map((tf) => ({
      key: `${tf}m`,
      title: `${tf}m`,
      color: RSI_TF_COLORS[tf] ?? "#94a3b8",
      points: series[String(tf)] ?? [],
    }));
  }, [rsiChart, visibleRsiTfs]);

  const market = status?.market ?? snapshot?.market;
  const marketOpen = market?.is_open ?? true;

  useEffect(() => {
    const ms =
      market?.is_open === false
        ? POLL_MS_CLOSED
        : live
          ? POLL_MS_LIVE
          : POLL_MS_IDLE;
    timerRef.current = window.setInterval(() => {
      void refresh({ charts: false });
    }, ms);
    return () => {
      if (timerRef.current != null) window.clearInterval(timerRef.current);
    };
  }, [live, market?.is_open, refresh]);

  useEffect(() => {
    if (!live || market?.is_open === false) {
      if (chartTimerRef.current != null) {
        window.clearInterval(chartTimerRef.current);
        chartTimerRef.current = null;
      }
      return;
    }
    chartTimerRef.current = window.setInterval(() => {
      void refreshCharts();
    }, CHART_POLL_MS_LIVE);
    return () => {
      if (chartTimerRef.current != null) window.clearInterval(chartTimerRef.current);
    };
  }, [live, market?.is_open, refreshCharts]);

  const toggleStream = async () => {
    setBusy(true);
    setError(null);
    try {
      if (live) {
        const st = await stopMtfRsiStream();
        setStatus(st);
        setLive(false);
      } else {
        const st = await startMtfRsiStream({ rsiPeriod });
        setStatus(st);
        setLive(st.status === "connected" || st.status === "connecting");
        if (st.snapshot) setSnapshot(st.snapshot);
      }
      await refresh({ charts: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const loadSeed = async (forceRefresh = false) => {
    setBusy(true);
    setError(null);
    try {
      const st = await seedMtfRsi({ rsiPeriod, forceRefresh });
      setStatus(st);
      if (st.snapshot) setSnapshot(st.snapshot);
      await refresh({ charts: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const applyPeriod = async (period: number) => {
    if (!Number.isFinite(period) || period < 1 || period > 200) {
      setError("RSI period must be between 1 and 200");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setRsiPeriod(period);
      setCustomPeriod(String(period));
      if (live || status?.seeded) {
        const snap = await setMtfRsiPeriod(period);
        setSnapshot(snap);
        const [candlesPayload, chartPayload] = await Promise.all([
          fetchMtfRsiCandles(priceTfRef.current),
          fetchMtfRsiChart(),
        ]);
        setPriceCandles(candlesPayload.candles ?? []);
        setRsiChart(chartPayload);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const frames = snapshot?.timeframes ?? {};
  const tfKeys = Object.keys(frames)
    .map(Number)
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b);

  const feedStatus = status?.status ?? snapshot?.feed_status ?? "stopped";
  const ltp = snapshot?.ltp;
  const modeNote = status?.mode_note ?? snapshot?.mode_note;

  return (
    <main className="mx-auto max-w-5xl space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Multi-TF RSI</h1>
          <p className="max-w-2xl text-xs text-slate-500">
            Live Nifty 50 RSI across 1m / 3m / 5m / 10m / 15m. Candles are stored in
            SQLite <code className="text-slate-500">index_candles</code>. First seed
            pulls ~3 years; later updates only fetch from the last saved bar forward.
          </p>
          <p className="mt-1 text-[10px] text-slate-600">
            Feed: <span className="text-slate-400">{feedStatus}</span>
            {status?.seeded ? " · seed ready" : " · not seeded"}
            {status?.lookback_years != null
              ? ` · ~${status.lookback_years}y history`
              : " · ~3y history"}
            {status?.reconnect_attempts ? ` · reconnects ${status.reconnect_attempts}` : ""}
            {market ? ` · ${market.label}` : ""}
            {priceCandles.length ? ` · chart bars ${priceCandles.length.toLocaleString("en-IN")}` : ""}
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-0.5 text-[10px] text-slate-500">
            RSI period
            <div className="flex items-center gap-1">
              {RSI_PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  disabled={busy}
                  onClick={() => applyPeriod(p)}
                  className={`rounded-md border px-2 py-1.5 text-xs ${
                    rsiPeriod === p
                      ? "border-accent/50 bg-accent/10 text-accent"
                      : "border-surface-border bg-surface text-slate-300 hover:border-accent/40"
                  }`}
                >
                  {p}
                </button>
              ))}
              <input
                type="number"
                min={1}
                max={200}
                value={customPeriod}
                onChange={(e) => setCustomPeriod(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyPeriod(Number(customPeriod));
                }}
                className="w-16 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => applyPeriod(Number(customPeriod))}
                className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-300 hover:border-accent/40"
              >
                Apply
              </button>
            </div>
          </div>

          <button
            type="button"
            onClick={() => refresh({ charts: true })}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-slate-300 hover:border-accent/40"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>

          <button
            type="button"
            onClick={() => loadSeed(false)}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-slate-200 hover:border-accent/40"
            title="First run downloads ~3y into SQLite index_candles. Later runs only fetch from the last DB bar forward."
          >
            <Database className="h-3.5 w-3.5" />
            {busy ? "Updating…" : "Update seed"}
          </button>
          <button
            type="button"
            onClick={() => loadSeed(true)}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-slate-400 hover:border-accent/40"
            title="Re-download the full ~3y history from Upstox and upsert into index_candles"
          >
            {busy ? "…" : "Full 3y refresh"}
          </button>

          <button
            type="button"
            onClick={toggleStream}
            disabled={busy}
            className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs ${
              live
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-surface-border bg-surface text-slate-200 hover:border-accent/40"
            }`}
          >
            <Radio className="h-3.5 w-3.5" />
            {busy ? "…" : live ? "Stop stream" : "Start stream"}
          </button>
        </div>
      </div>

      {modeNote && (
        <div
          className={`rounded-md border px-3 py-2 text-xs ${
            marketOpen
              ? "border-sky-500/30 bg-sky-500/10 text-sky-200"
              : "border-amber-500/30 bg-amber-500/10 text-amber-100"
          }`}
        >
          {modeNote}
          {!marketOpen && (
            <span className="mt-1 block text-[11px] text-amber-200/80">
              Use <strong>Load seed</strong> for the last session chart/table. Stream may connect but
              values stay static until ticks resume (NSE ~09:15–15:30 IST).
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-surface-border bg-surface/60 px-4 py-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Instrument</div>
          <div className="mt-1 text-sm text-slate-100">
            {status?.instrument_label ?? snapshot?.instrument_label ?? "Nifty 50"}
          </div>
        </div>
        <div className="rounded-lg border border-surface-border bg-surface/60 px-4 py-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">LTP</div>
          <div className="mt-1 font-mono text-lg text-slate-100">
            {typeof ltp === "number" ? ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}
          </div>
          {!snapshot?.live_ticks && snapshot?.seed_ts && (
            <div className="mt-0.5 text-[10px] text-slate-500">from seed {formatTs(snapshot.seed_ts)}</div>
          )}
        </div>
        <div className="rounded-lg border border-surface-border bg-surface/60 px-4 py-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Active RSI</div>
          <div className="mt-1 flex items-center gap-2 text-sm text-slate-100">
            <Activity className="h-4 w-4 text-accent" />
            RSI({snapshot?.rsi_period ?? rsiPeriod})
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">{formatTs(snapshot?.ts)}</div>
        </div>
      </section>

      <section className="rounded-lg border border-surface-border bg-surface/40 p-3">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div className="text-xs font-medium text-slate-200">
            Nifty · multi-TF RSI({snapshot?.rsi_period ?? rsiPeriod})
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wide text-slate-500">Nifty TF</span>
              {ALL_TFS.map((tf) => {
                const on = priceTf === tf;
                return (
                  <button
                    key={`price-${tf}`}
                    type="button"
                    onClick={() => setPriceTf(tf)}
                    className={`rounded-md border px-2 py-1 text-[10px] ${
                      on
                        ? "border-accent/40 bg-accent/10 text-accent"
                        : "border-surface-border bg-surface text-slate-500"
                    }`}
                  >
                    {tf}m
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wide text-slate-500">RSI TFs</span>
              {ALL_TFS.map((tf) => {
                const on = visibleRsiTfs.includes(tf);
                return (
                  <button
                    key={`rsi-${tf}`}
                    type="button"
                    onClick={() => toggleRsiTf(tf)}
                    className={`rounded-md border px-2 py-1 text-[10px] ${
                      on
                        ? "border-transparent text-slate-900"
                        : "border-surface-border bg-surface text-slate-500"
                    }`}
                    style={
                      on
                        ? {
                            backgroundColor: RSI_TF_COLORS[tf] ?? "#94a3b8",
                            color: "#0f172a",
                          }
                        : undefined
                    }
                    title={on ? `Hide ${tf}m RSI` : `Show ${tf}m RSI`}
                  >
                    {tf}m
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        {priceCandles.length > 0 ? (
          <NiftyChart
            candles={priceCandles}
            timeframe={`${priceTf}m`}
            height={520}
            rsiPeriod={snapshot?.rsi_period ?? rsiPeriod}
            showRsi={visibleRsiTfs.length > 0}
            rsiOverlays={rsiOverlays}
            showBollinger={false}
          />
        ) : (
          <div className="flex h-[520px] items-center justify-center text-xs text-slate-500">
            No candles yet — load seed or start the stream.
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-lg border border-surface-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface/80 text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Timeframe</th>
              <th className="px-4 py-2 font-medium text-right">RSI</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium text-right">Buffer</th>
              <th className="px-4 py-2 font-medium text-right">Active close</th>
            </tr>
          </thead>
          <tbody>
            {loading && tfKeys.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-xs text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : tfKeys.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-xs text-slate-500">
                  Load seed or start the stream to populate RSI.
                </td>
              </tr>
            ) : (
              tfKeys.map((tf) => {
                const row = frames[String(tf)];
                const rsi = row?.rsi;
                const st = row?.status ?? "Warming";
                return (
                  <tr key={tf} className="border-t border-surface-border/80">
                    <td className="px-4 py-3 font-medium text-slate-200">{tf}m</td>
                    <td className="px-4 py-3 text-right font-mono text-slate-100">
                      {typeof rsi === "number" ? rsi.toFixed(2) : "n/a"}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-md border px-2 py-0.5 text-xs ${statusClass(st)}`}>
                        {st}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-400">{row?.buffer ?? 0}</td>
                    <td className="px-4 py-3 text-right font-mono text-slate-400">
                      {typeof row?.active_close === "number"
                        ? row.active_close.toLocaleString("en-IN", { maximumFractionDigits: 2 })
                        : "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </section>

      <p className="text-[10px] text-slate-600">
        Chart times are IST. History is stored in SQLite{" "}
        <code className="text-slate-500">index_candles</code> (UI may show last ~100k bars).
        Existing JSON under <code className="text-slate-500">data/mtf_rsi_cache/</code> is
        imported once if the DB is empty.
      </p>
    </main>
  );
}
