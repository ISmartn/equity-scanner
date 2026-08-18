import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, Bell, BellOff, Radio, RefreshCw, TrendingUp, Zap } from "lucide-react";
import {
  evaluateOiMomentum,
  exportOiMomentumAlerts,
  fetchOiMomentumAlerts,
  fetchOiStreamStatus,
  startOiMomentumStream,
  stopOiMomentumStream,
  type OiMomentumAlertRecord,
  type OiMomentumEvaluation,
  type OiMomentumResponse,
  type OiStreamStatus,
} from "@/lib/api";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";
import {
  notifyUserAlert,
  requestBrowserNotifyPermission,
  unlockAlertAudio,
} from "@/lib/alertNotify";

const OI_ALERTS_KEY = "oi-momentum-system-alerts";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY"] as const;
const WINDOW_OPTIONS_REST = [
  { label: "3 min", sec: 180 },
  { label: "5 min", sec: 300 },
] as const;

const WINDOW_OPTIONS_LIVE = [
  { label: "30s scalp (high noise)", sec: 30 },
  { label: "1 min (live)", sec: 60 },
  { label: "2 min (live)", sec: 120 },
  { label: "3 min", sec: 180 },
  { label: "5 min", sec: 300 },
] as const;

function formatWindowLabel(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec % 60 === 0) return `${sec / 60}m`;
  return `${sec}s`;
}

function formatAlertTime(unixSec: number): string {
  return new Date(unixSec * 1000).toLocaleString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "short",
  });
}

function handleOiAlertNotify(
  result: OiMomentumResponse,
  symbol: string,
) {
  const event = result.alert_event;
  if (!event?.is_new) return;

  const isStrong = event.notify_alert === "strong";
  const phaseLabel = event.notify_phase === "early" ? "early" : "confirmed";
  notifyUserAlert({
    title: `${symbol} OI ${isStrong ? "strong" : "mild"} (${phaseLabel})`,
    body: event.record.message,
    tone: isStrong ? "bullish" : "warning",
    tag: `oi-momentum-${event.record.id}`,
  });
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function alertStyles(alert: OiMomentumEvaluation["alert"]): string {
  switch (alert) {
    case "strong":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "mild":
      return "border-amber-500/40 bg-amber-500/10 text-amber-300";
    case "warming":
      return "border-sky-500/40 bg-sky-500/10 text-sky-300";
    default:
      return "border-surface-border bg-surface text-slate-300";
  }
}

function alertIcon(alert: OiMomentumEvaluation["alert"]) {
  switch (alert) {
    case "strong":
      return <Zap className="h-5 w-5 shrink-0" />;
    case "mild":
      return <AlertTriangle className="h-5 w-5 shrink-0" />;
    case "warming":
      return <Activity className="h-5 w-5 shrink-0" />;
    default:
      return <TrendingUp className="h-5 w-5 shrink-0" />;
  }
}

const OI_PREFS_KEY = "trading.oiMomentum.prefs";
type OiUiPrefs = {
  symbol: string;
  windowSec: number;
  autoPoll: boolean;
  pollIntervalSec: number;
};
const DEFAULT_OI_PREFS: OiUiPrefs = {
  symbol: "NIFTY",
  windowSec: 180,
  autoPoll: true,
  pollIntervalSec: 60,
};

export function OiMomentumPage() {
  const initialPrefs = loadUiPrefs(OI_PREFS_KEY, DEFAULT_OI_PREFS);
  const [symbol, setSymbol] = useState<string>(
    (SYMBOLS as readonly string[]).includes(initialPrefs.symbol) ? initialPrefs.symbol : "NIFTY",
  );
  const [windowSec, setWindowSec] = useState(Number(initialPrefs.windowSec) || 180);
  const [streamLive, setStreamLive] = useState(false);
  const [streamStatus, setStreamStatus] = useState<OiStreamStatus | null>(null);
  const [streamBusy, setStreamBusy] = useState(false);
  const [autoPoll, setAutoPoll] = useState(initialPrefs.autoPoll !== false);
  const [pollIntervalSec, setPollIntervalSec] = useState(Number(initialPrefs.pollIntervalSec) || 60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<OiMomentumResponse | null>(null);
  const [alertRecords, setAlertRecords] = useState<OiMomentumAlertRecord[]>([]);
  const [alertsOn, setAlertsOn] = useState(() => localStorage.getItem(OI_ALERTS_KEY) !== "0");
  const timerRef = useRef<number | null>(null);

  const isScalpMode = streamLive && windowSec <= 30;
  const effectivePollSec = isScalpMode ? 5 : streamLive ? 10 : pollIntervalSec;
  const windowOptions = streamLive ? WINDOW_OPTIONS_LIVE : WINDOW_OPTIONS_REST;

  const poll = useCallback(async () => {
    setError(null);
    try {
      const result = await evaluateOiMomentum({
        symbol,
        windowSec,
        source: streamLive ? "auto" : "auto",
      });
      setPayload(result);
      if (result.stream) setStreamStatus(result.stream);
      if (alertsOn) {
        handleOiAlertNotify(result, symbol);
      }
      if (result.alert_event?.is_new) {
        setAlertRecords((prev) => {
          const next = [result.alert_event!.record, ...prev.filter((r) => r.id !== result.alert_event!.record.id)];
          return next.slice(0, 50);
        });
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [symbol, windowSec, streamLive, alertsOn]);

  const loadAlertHistory = useCallback(async () => {
    try {
      const { records } = await fetchOiMomentumAlerts({ symbol, limit: 50 });
      setAlertRecords(records);
    } catch {
      /* ignore */
    }
  }, [symbol]);

  useEffect(() => {
    localStorage.setItem(OI_ALERTS_KEY, alertsOn ? "1" : "0");
  }, [alertsOn]);

  useEffect(() => {
    saveUiPrefs(OI_PREFS_KEY, {
      symbol,
      windowSec,
      autoPoll,
      pollIntervalSec,
    } satisfies OiUiPrefs);
  }, [symbol, windowSec, autoPoll, pollIntervalSec]);

  useEffect(() => {
    loadAlertHistory();
  }, [loadAlertHistory]);

  const evaluation = payload?.evaluation;

  const refreshStreamStatus = useCallback(async () => {
    try {
      const status = await fetchOiStreamStatus(symbol);
      if ("status" in status) {
        setStreamStatus(status);
        setStreamLive(status.status === "connected" || status.status === "connecting");
      }
    } catch {
      /* ignore */
    }
  }, [symbol]);

  const toggleStream = async () => {
    setStreamBusy(true);
    setError(null);
    try {
      if (streamLive) {
        const stopped = await stopOiMomentumStream(symbol);
        setStreamStatus(stopped);
        setStreamLive(false);
        if (windowSec < 180) setWindowSec(180);
      } else {
        const started = await startOiMomentumStream(symbol);
        setStreamStatus(started);
        setStreamLive(started.status === "connected" || started.status === "connecting");
        if (windowSec >= 180) setWindowSec(120);
        await poll();
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setStreamBusy(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    refreshStreamStatus().finally(() => poll());
  }, [poll, refreshStreamStatus]);

  useEffect(() => {
    if (streamLive && streamStatus?.status === "connecting") {
      const t = window.setInterval(refreshStreamStatus, 2000);
      return () => window.clearInterval(t);
    }
  }, [streamLive, streamStatus?.status, refreshStreamStatus]);

  useEffect(() => {
    if (!autoPoll) {
      if (timerRef.current != null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    timerRef.current = window.setInterval(poll, effectivePollSec * 1000);
    return () => {
      if (timerRef.current != null) {
        window.clearInterval(timerRef.current);
      }
    };
  }, [autoPoll, effectivePollSec, poll]);

  const toggleAlerts = async () => {
    unlockAlertAudio();
    if (!alertsOn) {
      await requestBrowserNotifyPermission();
    }
    setAlertsOn((on) => !on);
  };

  const exportAlerts = async () => {
    unlockAlertAudio();
    const data = await exportOiMomentumAlerts({ symbol, limit: 500 });
    downloadJson(`oi-momentum-alerts-${symbol}-${Date.now()}.json`, data.records);
  };

  return (
    <main className="mx-auto max-w-6xl space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">OI Support Momentum</h1>
          <p className="max-w-2xl text-xs text-slate-500">
            Rolling ATM support-zone scanner. REST poll (60s) or Upstox WebSocket live OI on zone strikes.
            Live mode supports 30s scalp through 5m windows — shorter = faster, noisier.
          </p>
          {payload?.source && (
            <p className="mt-1 text-[10px] text-slate-600">
              Data source:{" "}
              <span className="text-slate-400">
                {payload.source === "websocket" ? "WebSocket (live OI)" : "REST option-chain poll"}
              </span>
              {streamStatus?.tick_count != null && streamLive && (
                <span> · {streamStatus.tick_count.toLocaleString()} ticks</span>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
            Symbol
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
            Window
            <select
              value={windowSec}
              onChange={(e) => setWindowSec(Number(e.target.value))}
              className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
            >
              {windowOptions.map((opt) => (
                <option key={opt.sec} value={opt.sec}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          {!streamLive && (
          <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
            Poll every
            <select
              value={pollIntervalSec}
              onChange={(e) => setPollIntervalSec(Number(e.target.value))}
              className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
            >
              <option value={45}>45s</option>
              <option value={60}>60s</option>
              <option value={90}>90s</option>
            </select>
          </label>
          )}
          {streamLive && (
            <span className="self-end pb-1.5 text-[10px] text-emerald-400/80">
              Live refresh ~{effectivePollSec}s
              {isScalpMode ? " · snapshots ~3s" : " · snapshots ~5s"}
            </span>
          )}
          <button
            type="button"
            onClick={toggleAlerts}
            title="System alerts: sound + browser notification on new mild/strong signals"
            className={`inline-flex items-center gap-1.5 self-end rounded-md border px-3 py-1.5 text-xs ${
              alertsOn
                ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                : "border-surface-border bg-surface text-slate-400 hover:border-accent/40"
            }`}
          >
            {alertsOn ? <Bell className="h-3.5 w-3.5" /> : <BellOff className="h-3.5 w-3.5" />}
            {alertsOn ? "Alerts on" : "Alerts off"}
          </button>
          <label className="flex items-center gap-2 self-end pb-1 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={autoPoll}
              onChange={(e) => setAutoPoll(e.target.checked)}
              className="rounded border-surface-border"
            />
            Auto poll
          </label>
          <button
            type="button"
            onClick={toggleStream}
            disabled={streamBusy}
            className={`inline-flex items-center gap-1.5 self-end rounded-md border px-3 py-1.5 text-xs ${
              streamLive
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-surface-border bg-surface text-slate-200 hover:border-accent/40"
            }`}
          >
            <Radio className={`h-3.5 w-3.5 ${streamLive ? "animate-pulse" : ""}`} />
            {streamBusy ? "…" : streamLive ? `Live (${streamStatus?.status ?? "…"})` : "Start live OI"}
          </button>
          <button
            type="button"
            onClick={() => {
              unlockAlertAudio();
              setLoading(true);
              poll();
            }}
            disabled={loading}
            className="inline-flex items-center gap-1.5 self-end rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-slate-200 hover:border-accent/40"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Poll now
          </button>
          <button
            type="button"
            onClick={exportAlerts}
            className="inline-flex items-center gap-1.5 self-end rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-slate-200 hover:border-accent/40"
          >
            Export alerts
          </button>
        </div>
      </div>

      {isScalpMode && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
          <span className="font-medium">Scalp mode (30s, live only)</span>
          {" — "}
          High noise; volume/surge gates scaled for the short window. Prefer 1–3m for confirmation.
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {evaluation && (
        <div className={`flex gap-3 rounded-lg border px-4 py-3 ${alertStyles(evaluation.alert)}`}>
          {alertIcon(evaluation.alert)}
          <div>
            <p className="text-sm font-medium uppercase tracking-wide">{evaluation.alert}</p>
            <p className="mt-1 text-sm">{evaluation.message}</p>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="rounded-lg border border-surface-border bg-surface-raised/40 p-4 lg:col-span-1">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Spot & ATM zone</h2>
          {evaluation ? (
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-500">Spot</dt>
                <dd className="font-mono text-slate-100">{evaluation.spot.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Raw ATM</dt>
                <dd className="font-mono text-slate-200">{evaluation.raw_atm.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Smoothed ATM</dt>
                <dd className="font-mono text-accent">{evaluation.smoothed_atm.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Strike step</dt>
                <dd className="font-mono text-slate-200">{evaluation.strike_step}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Zone strikes</dt>
                <dd className="font-mono text-slate-200">
                  {evaluation.metrics.strikes.map((s) => s.toLocaleString("en-IN")).join(", ")}
                </dd>
              </div>
              {payload?.expiry && (
                <div className="flex justify-between">
                  <dt className="text-slate-500">Expiry</dt>
                  <dd className="font-mono text-slate-200">{payload.expiry}</dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="mt-3 text-sm text-slate-500">Waiting for first poll…</p>
          )}
        </section>

        <section className="rounded-lg border border-surface-border bg-surface-raised/40 p-4 lg:col-span-1">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Rolling window ({formatWindowLabel(windowSec)})
          </h2>
          {evaluation ? (
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-500">Put OI Δ (zone)</dt>
                <dd className="font-mono text-emerald-400">+{evaluation.metrics.zone_put_addition.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Call OI Δ (zone)</dt>
                <dd className="font-mono text-rose-300">{evaluation.metrics.zone_call_unwinding.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Put vol Δ (zone)</dt>
                <dd className="font-mono text-slate-200">+{evaluation.metrics.zone_put_volume_delta.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">Zone put OI</dt>
                <dd className="font-mono text-slate-200">{evaluation.metrics.total_zone_put_oi.toLocaleString("en-IN")}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">PCR momentum</dt>
                <dd className="font-mono text-slate-200">
                  {evaluation.metrics.pcr_momentum != null ? evaluation.metrics.pcr_momentum.toFixed(2) : "—"}
                </dd>
              </div>
            </dl>
          ) : null}
          {payload?.history && (
            <p className="mt-3 text-[10px] text-slate-500">
              Snapshots stored: {payload.history.count}
              {payload.history.oldest_age_sec != null &&
                ` · oldest ${Math.round(payload.history.oldest_age_sec)}s ago`}
            </p>
          )}
        </section>

        <section className="rounded-lg border border-surface-border bg-surface-raised/40 p-4 lg:col-span-1">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Gates</h2>
          {evaluation ? (
            <ul className="mt-3 space-y-2 text-sm">
              <GateRow
                label={`Put surge (>${((evaluation.put_surge_threshold_pct ?? 0.02) * 100).toFixed(1)}% zone OI)`}
                pass={evaluation.metrics.rapid_put_surge}
              />
              <GateRow label="Call unwind" pass={evaluation.metrics.call_unwind} />
              <GateRow
                label="OI/volume ratio in band"
                pass={evaluation.metrics.volume_confirmed}
              />
              {evaluation.signal_quality && (
                <>
                  <GateRow label="Price aligned" pass={evaluation.signal_quality.price_aligned} />
                  <GateRow label="No strike rotation" pass={!evaluation.signal_quality.strike_rotation} />
                  {evaluation.signal_quality.suppress_reason && (
                    <li className="text-[10px] text-amber-400/90">
                      Suppressed: {evaluation.signal_quality.suppress_reason.replace("_", " ")}
                    </li>
                  )}
                </>
              )}
              <GateRow
                label="PCR momentum ≥ 2"
                pass={
                  evaluation.metrics.pcr_momentum != null && evaluation.metrics.pcr_momentum >= 2
                }
              />
            </ul>
          ) : null}
          {payload?.note && <p className="mt-4 text-[10px] leading-relaxed text-slate-500">{payload.note}</p>}
        </section>
      </div>

      {evaluation?.strike_details?.length ? (
        <section className="overflow-x-auto rounded-lg border border-surface-border">
          <div className="border-b border-surface-border bg-surface-raised/60 px-3 py-2 text-[10px] text-slate-500">
            Strike deltas vs{" "}
            {evaluation.baseline_mode === "full"
              ? `${formatWindowLabel(evaluation.target_window_sec)} baseline`
              : evaluation.baseline_mode === "partial"
                ? `last poll (${evaluation.baseline_age_sec ?? "?"}s ago)`
                : "— (need 2+ polls)"}
          </div>
          <table className="min-w-full text-left text-xs">
            <thead className="bg-surface-raised/60 text-slate-400">
              <tr>
                <th className="px-3 py-2">Strike</th>
                <th className="px-3 py-2">Put OI</th>
                <th className="px-3 py-2">Call OI</th>
                <th className="px-3 py-2">Put OI Δ</th>
                <th className="px-3 py-2">Call OI Δ</th>
                <th className="px-3 py-2">Put vol Δ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-slate-200">
              {evaluation.strike_details.map((row) => (
                <tr key={row.strike_price}>
                  <td className="px-3 py-2 font-mono">{row.strike_price.toLocaleString("en-IN")}</td>
                  <td className="px-3 py-2 font-mono">{row.put_oi.toLocaleString("en-IN")}</td>
                  <td className="px-3 py-2 font-mono">{row.call_oi.toLocaleString("en-IN")}</td>
                  <td className="px-3 py-2 font-mono text-emerald-400">
                    {row.put_oi_delta != null ? row.put_oi_delta.toLocaleString("en-IN") : "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-rose-300">
                    {row.call_oi_delta != null ? row.call_oi_delta.toLocaleString("en-IN") : "—"}
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {row.put_volume_delta != null ? row.put_volume_delta.toLocaleString("en-IN") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="rounded-lg border border-surface-border bg-surface-raised/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Alert log ({alertRecords.length})
          </h2>
          <p className="text-[10px] text-slate-500">
            Records spot, OI, and strike context on each new mild/strong signal (backend JSONL + export).
          </p>
        </div>
        {alertRecords.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">No recorded alerts yet for {symbol}.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {alertRecords.map((row) => (
              <details
                key={row.id}
                className="rounded-md border border-surface-border bg-surface/40 px-3 py-2 text-xs"
              >
                <summary className="cursor-pointer list-none text-slate-200">
                  <span className="font-medium uppercase text-amber-300">{row.notify_alert}</span>
                  <span className="text-slate-500"> · {row.notify_phase}</span>
                  <span className="text-slate-500"> · {formatAlertTime(row.recorded_at)}</span>
                  <span className="text-slate-400">
                    {" "}
                    · spot {row.price_action.spot.toLocaleString("en-IN")}
                    {row.price_action.spot_delta != null && (
                      <span className={row.price_action.spot_delta >= 0 ? " text-emerald-400" : " text-rose-300"}>
                        {" "}
                        ({row.price_action.spot_delta >= 0 ? "+" : ""}
                        {row.price_action.spot_delta.toFixed(1)})
                      </span>
                    )}
                    {" "}
                    · put Δ +{row.zone_metrics.zone_put_addition.toLocaleString("en-IN")}
                  </span>
                </summary>
                <p className="mt-2 text-slate-400">{row.message}</p>
                {row.signal_quality && (
                  <p className="mt-1 text-[10px] text-slate-500">
                    Quality: price {row.signal_quality.price_aligned ? "aligned" : "diverged"}
                    {" · "}
                    rotation {row.signal_quality.strike_rotation ? "yes" : "no"}
                    {row.gates?.oi_volume_ratio != null && (
                      <> · OI/vol {Number(row.gates.oi_volume_ratio).toFixed(4)}</>
                    )}
                  </p>
                )}
                <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  <MetricChip label="Spot @ baseline" value={row.price_action.spot_at_baseline?.toLocaleString("en-IN") ?? "—"} />
                  <MetricChip
                    label="Spot Δ %"
                    value={
                      row.price_action.spot_delta_pct != null
                        ? `${row.price_action.spot_delta_pct >= 0 ? "+" : ""}${row.price_action.spot_delta_pct}%`
                        : "—"
                    }
                  />
                  <MetricChip label="ATM zone" value={String(row.price_action.smoothed_atm)} />
                  <MetricChip label="Window" value={formatWindowLabel(row.window_sec)} />
                </div>
                {row.spot_trail.length > 1 && (
                  <p className="mt-2 font-mono text-[10px] text-slate-500">
                    Spot trail: {row.spot_trail.map((p) => p.spot.toFixed(1)).join(" → ")}
                  </p>
                )}
              </details>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function MetricChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-surface-border/60 bg-surface-raised/30 px-2 py-1.5">
      <p className="text-[10px] text-slate-500">{label}</p>
      <p className="font-mono text-slate-200">{value}</p>
    </div>
  );
}

function GateRow({ label, pass }: { label: string; pass: boolean }) {
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="text-slate-400">{label}</span>
      <span className={pass ? "text-emerald-400" : "text-slate-500"}>{pass ? "yes" : "no"}</span>
    </li>
  );
}
