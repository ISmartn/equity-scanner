import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Crosshair } from "lucide-react";
import { PageToolbar, PctCell, StatChip, ToolbarDivider } from "@/components/dense";
import { startLiveScan, stopLiveScan } from "@/lib/api";
import {
  buildSetupWatchlist,
  fetchSetupAlerts,
  fetchSetupFilings,
  fetchSetupLive,
  fetchSetupReport,
  fetchSetupWatchlist,
  sendSetupTestAlert,
  type HealthState,
  type SetupAlert,
  type SetupFilings,
  type SetupList,
  type SetupLive,
  type SetupLiveRow,
  type SetupLiveState,
  type SetupModel,
  type SetupReport,
  type SetupRow,
  type SetupWatchlist,
} from "@/lib/earlySetupApi";

type Tab = "watchlist" | "filings" | "resolved" | "alerts" | "results";
type ListFilter = "all" | SetupList;

const FEED_BUSY = new Set(["starting", "connecting", "connected", "reconnecting"]);
const STATE_ORDER: Record<SetupLiveState, number> = {
  breakout: 0,
  crossed_light: 1,
  testing: 2,
  near: 3,
  gapped: 4,
  extended: 5,
  waiting: 6,
  failed: 7,
};
const HEALTH_WORD: Record<HealthState, string> = { green: "Healthy", amber: "Mixed", red: "Weak" };
const HEALTH_CLASS: Record<HealthState, string> = { green: "text-gain", amber: "text-amber-300", red: "text-loss" };
const TH = "px-2 py-1.5 font-medium";
const TABLE_HEAD = "sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400";
const CARD = "overflow-auto rounded-lg border border-surface-border bg-surface-raised";
const BADGE = "ml-1 rounded px-1 text-[10px] font-semibold";

function price(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function dayAndTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function stateClass(state: string | undefined): string {
  const plain = (state ?? "").replace(/^weekly_/, "");
  if (plain === "breakout" || plain === "preopen_above") return "text-gain";
  if (plain === "testing" || plain === "crossed_light" || plain === "preopen_near") return "text-amber-300";
  if (plain === "near") return "text-sky-300";
  if (plain === "failed" || plain === "gapped" || plain === "preopen_fail" || plain === "preopen_gap") return "text-loss";
  return "text-slate-400";
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : "Request failed";
}

// What a high or a low reading of each feature means, in plain words: [high, low].
const READINGS: Record<string, [string, string]> = {
  dist_to_pivot_pct: ["far from the pivot", "close to the pivot"],
  tightness_pctile: ["wide range", "tight range"],
  atr_ratio: ["volatility expanding", "volatility shrinking"],
  vol_dryup: ["volume picking up", "volume drying up"],
  updown_vol_log: ["more volume on up days", "more volume on down days"],
  rs_pctile: ["stronger than the market", "weaker than the market"],
  rs_new_high: ["relative strength at a high", "relative strength off its high"],
  close_tight_pct: ["loose closes", "tight closes"],
  ret20_pct: ["already up over 20 sessions", "flat over 20 sessions"],
  higher_lows: ["higher lows", "no higher lows"],
  pct_from_52w_high: ["far below the 52-week high", "near the 52-week high"],
  sector_accel: ["group already running ahead of the market", "group not yet running"],
  oi_build: ["futures OI building", "futures OI falling"],
  deliv_pct_5d: ["high delivery share", "low delivery share"],
  deliv_trend: ["delivery share rising", "delivery share falling"],
  group_heat: ["industry group making new highs", "industry group quiet"],
  market_breadth: ["healthy market", "weak market"],
  market_breadth_chg: ["market improving", "market worsening"],
};

/** The three readings that moved this stock's score the most. "+" raised it, "−" lowered it. */
function whyListed(row: SetupRow, weights: Map<string, number>): string {
  const parts = Object.entries(row.features.contributions ?? {})
    .filter(([name, value]) => Math.abs(value) >= 0.1 && READINGS[name])
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 3)
    .map(([name, value]) => {
      // A push in the weight's own direction means the reading is above average.
      const high = value * (weights.get(name) ?? 0) > 0;
      return `${value > 0 ? "+" : "−"} ${READINGS[name][high ? 0 : 1]}`;
    });
  return parts.length ? parts.join(" · ") : "Average on the readings that count";
}

function scoreStatus(model: SetupModel | undefined): { value: string; hint: string } {
  if (!model) return { value: "—", hint: "" };
  if (!model.fitted) {
    return {
      value: "Starting weights",
      hint: "Set from NSE data for February 2025 to November 2026 and not tested on anything later. Run npm run setups:fit to derive and test them on your own candles.",
    };
  }
  const verdict = model.metrics?.test.verdict;
  return {
    value: verdict === "ranks" ? "Fitted, ranks" : "Fitted, unproven",
    hint:
      verdict === "ranks"
        ? "On sessions the fit never saw, the top fifth by score beat the rest."
        : "On sessions the fit never saw, the top fifth by score did not reliably beat the rest.",
  };
}

export function EarlySetupPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>(() => {
    const asked = new URLSearchParams(window.location.search).get("tab");
    return asked === "filings" || asked === "resolved" || asked === "alerts" || asked === "results" ? asked : "watchlist";
  });
  const [watchlist, setWatchlist] = useState<SetupWatchlist | null>(null);
  const [resolved, setResolved] = useState<SetupRow[]>([]);
  const [live, setLive] = useState<SetupLive | null>(null);
  const [alerts, setAlerts] = useState<SetupAlert[]>([]);
  const [report, setReport] = useState<SetupReport | null>(null);
  const [filings, setFilings] = useState<SetupFilings | null>(null);
  const [filingsWatchOnly, setFilingsWatchOnly] = useState(false);
  const [listFilter, setListFilter] = useState<ListFilter>("all");
  const [reportList, setReportList] = useState<SetupList>("daily");
  const [maxPositions, setMaxPositions] = useState(10);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadWatchlist = useCallback(async () => {
    try {
      setWatchlist(await fetchSetupWatchlist("active"));
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);

  useEffect(() => {
    void loadWatchlist();
    const timer = window.setInterval(() => void loadWatchlist(), 60_000);
    return () => window.clearInterval(timer);
  }, [loadWatchlist]);

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        const next = await fetchSetupLive();
        if (!cancelled) setLive(next);
      } catch {
        /* the watchlist request reports a down backend */
      }
    };
    void pull();
    const timer = window.setInterval(() => void pull(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        if (tab === "alerts") {
          const next = await fetchSetupAlerts();
          if (!cancelled) setAlerts(next.rows);
        } else if (tab === "filings") {
          const next = await fetchSetupFilings(filingsWatchOnly);
          if (!cancelled) setFilings(next);
        } else if (tab === "results") {
          setReport(null);
          const next = await fetchSetupReport(reportList, maxPositions);
          if (!cancelled) setReport(next);
        } else if (tab === "resolved") {
          const next = await fetchSetupWatchlist("all");
          if (!cancelled) setResolved(next.rows.filter((row) => row.status !== "active"));
        }
      } catch (err) {
        if (!cancelled) setError(message(err));
      }
    };
    void pull();
    if (tab !== "alerts" && tab !== "filings") return () => void (cancelled = true);
    const timer = window.setInterval(() => void pull(), tab === "filings" ? 20_000 : 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [tab, filingsWatchOnly, reportList, maxPositions]);

  const feedRunning = live ? FEED_BUSY.has(live.status) : false;
  const liveByKey = useMemo(() => {
    const map = new Map<string, SetupLiveRow>();
    for (const row of live?.rows ?? []) {
      map.set(`${row.symbol}:${row.list}`, row);
      // One base on both lists is one live row; let the weekly entry show it too.
      if (row.also_weekly) map.set(`${row.symbol}:weekly`, row);
    }
    return map;
  }, [live]);
  const weights = useMemo(
    () => new Map((watchlist?.model.features ?? []).map((item) => [item.name, item.weight])),
    [watchlist],
  );

  const rows = useMemo(() => {
    const list = (watchlist?.rows ?? []).filter((row) => listFilter === "all" || row.timeframe === listFilter);
    const rank = (row: SetupRow) => {
      const now = liveByKey.get(`${row.ticker}:${row.timeframe}`);
      return now ? STATE_ORDER[now.state] : 8;
    };
    list.sort((a, b) => rank(a) - rank(b) || (b.score ?? 0) - (a.score ?? 0));
    return list;
  }, [watchlist, liveByKey, listFilter]);

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const onBuild = () =>
    run(async () => {
      const result = await buildSetupWatchlist();
      await loadWatchlist();
      if (result.status === "current") return `Already current through ${result.processed_through}.`;
      if (result.status === "updated") return `Updated through ${result.processed_through}.`;
      return result.message ?? "Nothing to update.";
    });

  const onFeed = () =>
    run(async () => {
      if (feedRunning) {
        await stopLiveScan();
        return "Feed stopped.";
      }
      await startLiveScan();
      return "Feed starting. Watchlist stocks appear here once prices arrive.";
    });

  const onTestAlert = () =>
    run(async () => {
      await sendSetupTestAlert();
      return "Test message sent to Telegram.";
    });

  const byList = watchlist?.counts_by_list;
  const dailyActive = byList?.daily.active ?? 0;
  const weeklyActive = byList?.weekly.active ?? 0;
  const counts = watchlist?.counts ?? {};
  const model = watchlist?.model;
  const health = watchlist?.health ?? null;
  const score = scoreStatus(model);
  const onFeedCount = rows.filter((row) => liveByKey.has(`${row.ticker}:${row.timeframe}`)).length;

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-2 p-2">
      <PageToolbar
        right={
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => void onBuild()}
              disabled={busy}
              className="h-7 rounded-md border border-surface-border bg-surface px-2.5 text-data-xs font-semibold text-slate-200 disabled:opacity-40"
            >
              Update list
            </button>
            <button
              type="button"
              onClick={() => void onFeed()}
              disabled={busy}
              className="h-7 rounded-md bg-accent px-2.5 text-data-xs font-semibold text-white disabled:opacity-40"
            >
              {feedRunning ? "Stop feed" : "Start feed"}
            </button>
          </div>
        }
      >
        <span className="inline-flex items-center gap-1 text-data-xs font-semibold text-slate-100">
          <Crosshair className={`h-3.5 w-3.5 ${live?.status === "connected" ? "text-gain" : "text-slate-400"}`} />
          Setups before the break
        </span>
        <ToolbarDivider />
        <StatChip
          label="Market"
          value={health ? `${HEALTH_WORD[health.state]} · ${pct(health.pct_above_50, 0)}` : "—"}
          valueClassName={health ? HEALTH_CLASS[health.state] : undefined}
          hint={
            health
              ? `${health.label}. ${pct(health.pct_above_50, 0)} of ${health.stocks} stocks are above their 50-day average on ${health.trade_date}; ${health.new_highs} at new 20-day highs, ${health.new_lows} at new lows.`
              : "Shown once the list has been built."
          }
        />
        <StatChip label="In a base" value={`${dailyActive} daily · ${weeklyActive} weekly`} />
        <StatChip label="Through" value={watchlist?.processed_through ?? "—"} />
        <StatChip label="Feed" value={live?.status ?? "stopped"} />
        <StatChip label="On feed" value={feedRunning ? `${onFeedCount}/${rows.length}` : "—"} />
        <StatChip label="Score" value={score.value} hint={score.hint} />
        <StatChip label="Telegram" value={live?.telegram_configured ? "On" : "Off"} />
      </PageToolbar>

      {error ? (
        <div className="rounded-md border border-loss/40 bg-loss/10 px-2 py-1 text-data-xs text-loss">{error}</div>
      ) : null}
      {live?.watchlist_behind ? (
        <div className="rounded-md border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-data-xs text-amber-200">
          The list has not been updated through {live.watchlist_behind}, so pivots and stops may be out of date. Load
          that day's candles and press Update list.
        </div>
      ) : null}
      {health && health.state !== "green" ? (
        <div className="rounded-md border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-data-xs text-amber-200">
          The market reading is {HEALTH_WORD[health.state].toLowerCase()}: {pct(health.pct_above_50, 0)} of stocks are
          above their 50-day average. In past data, setups triggered in a market like this did worse than in a healthy
          one. See Results.
        </div>
      ) : null}
      {notice ? (
        <div className="rounded-md border border-surface-border bg-surface px-2 py-1 text-data-xs text-slate-300">{notice}</div>
      ) : null}

      <div className="flex flex-wrap items-center gap-1">
        {(
          [
            ["watchlist", `Watchlist ${counts.active ?? 0}`],
            ["filings", "Filings"],
            ["resolved", `Resolved ${(counts.triggered ?? 0) + (counts.failed ?? 0) + (counts.expired ?? 0)}`],
            ["alerts", `Alerts ${live?.alerts_raised ?? 0}`],
            ["results", "Results"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${
              tab === id ? "border-accent/50 bg-accent/15 text-sky-200" : "border-surface-border text-slate-400"
            }`}
          >
            {label}
          </button>
        ))}
        <span className="text-[10px] text-slate-500">
          These stocks have not broken out. The plan is a buy order above the pivot with the stop at the base low, not a
          buy now.
        </span>
      </div>

      {tab === "watchlist" ? (
        <>
          <div className="flex flex-wrap items-center gap-1 text-[10px] text-slate-500">
            {(
              [
                ["all", `Both lists ${dailyActive + weeklyActive}`],
                ["daily", `Daily ${dailyActive}`],
                ["weekly", `Weekly ${weeklyActive}`],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setListFilter(id)}
                className={`rounded-md border px-2 py-0.5 font-semibold uppercase ${
                  listFilter === id ? "border-accent/50 bg-accent/15 text-sky-200" : "border-surface-border text-slate-400"
                }`}
              >
                {label}
              </button>
            ))}
            <span>
              Daily: a quiet range under the 20-day high. Weekly: a tight three weeks under a ten-week high set at least
              two weeks ago.
            </span>
          </div>
          <div className={CARD}>
            <table className="w-full min-w-[1320px] border-collapse text-left text-data-xs">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className={TH}>Now</th>
                  <th className={TH}>Symbol</th>
                  <th className={`${TH} text-right`}>Price</th>
                  <th className={`${TH} text-right`}>Buy above</th>
                  <th className={`${TH} text-right`}>Stop</th>
                  <th className={`${TH} text-right`}>To pivot</th>
                  <th className={`${TH} text-right`}>Risk</th>
                  <th className={`${TH} text-right`}>Vol pace</th>
                  <th className={`${TH} text-right`}>Score</th>
                  <th className={`${TH} text-right`}>Days</th>
                  <th className={TH}>Industry group</th>
                  <th className={TH}>Why</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="px-2 py-6 text-center text-slate-500">
                      No stock is in a base on this list. Load daily candles, then press Update list.
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => {
                    const now = liveByKey.get(`${row.ticker}:${row.timeframe}`);
                    const auction = row.preopen;
                    const distance = now ? now.distance_pct : row.distance_pct;
                    const members = row.features.group_members;
                    const broke = row.features.group_broke;
                    return (
                      <tr
                        key={row.id}
                        className="cursor-pointer border-t border-surface-border/70 hover:bg-white/5"
                        onClick={() => navigate(`/stock-research?ticker=${encodeURIComponent(row.ticker)}`)}
                      >
                        <td className={`px-2 py-1 font-semibold ${stateClass(now?.state ?? auction?.state)}`}>
                          {now ? now.state_label : auction ? auction.label : feedRunning ? "Not on feed" : "—"}
                          {now?.stale ? <span className="ml-1 text-[10px] text-slate-500">stale</span> : null}
                          {!now && auction ? (
                            <span className="ml-1 text-[10px] font-normal text-slate-400">
                              pre-open {price(auction.iep)}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-2 py-1 font-semibold text-slate-100" title={row.company_name ?? undefined}>
                          {row.ticker}
                          {row.timeframe === "weekly" ? (
                            <span className={`${BADGE} bg-white/10 text-slate-300`} title="On the weekly list">
                              W
                            </span>
                          ) : null}
                          {(row.flags ?? []).map((flag) => (
                            <span key={flag.flag} className={`${BADGE} bg-loss/20 text-loss`} title={flag.detail ?? undefined}>
                              {flag.label}
                            </span>
                          ))}
                          {row.event ? (
                            <span className={`${BADGE} bg-sky-300/15 text-sky-200`} title={row.event.detail ?? undefined}>
                              {row.event.purpose} {row.event.event_date.slice(5)}
                            </span>
                          ) : null}
                          {row.filing ? (
                            <span
                              className={`${BADGE} bg-amber-300/15 text-amber-200`}
                              title={`${row.filing.size?.headline ?? row.filing.subject ?? ""} ${row.filing.size_text ?? ""}`}
                            >
                              {row.filing.category_label} {clock(row.filing.published_at)}
                            </span>
                          ) : null}
                          {row.large_buy ? (
                            <span
                              className={`${BADGE} bg-gain/15 text-gain`}
                              title={`${row.large_buy.client} bought ${row.large_buy.quantity.toLocaleString("en-IN")} shares at ${price(row.large_buy.price)} on ${row.large_buy.trade_date}, with no sale the same day`}
                            >
                              Large buy {row.large_buy.trade_date.slice(5)}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">{price(now ? now.ltp : row.last_close)}</td>
                        <td className="px-2 py-1 text-right tabular-nums text-sky-200">{price(row.pivot)}</td>
                        <td className="px-2 py-1 text-right tabular-nums text-loss">{price(row.stop)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{pct(distance, 2)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{pct(row.risk_pct)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">
                          {now?.session_rvol == null ? "—" : `${now.session_rvol.toFixed(1)}×`}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">{row.score?.toFixed(0) ?? "—"}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{row.days_in_base}</td>
                        <td className="max-w-[220px] px-2 py-1 text-slate-300">
                          {row.sector ?? "—"}
                          {members ? (
                            <span className="ml-1 text-[10px] text-slate-500" title="Stocks in this group that closed at a new 20-day high in the last five sessions">
                              {broke ?? 0} of {members} at new highs
                            </span>
                          ) : null}
                        </td>
                        <td className="max-w-[340px] px-2 py-1 text-slate-300">{now ? now.reason : whyListed(row, weights)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {tab === "filings" ? (
        <FilingsTab filings={filings} watchOnly={filingsWatchOnly} onWatchOnly={setFilingsWatchOnly} />
      ) : null}

      {tab === "resolved" ? (
        <div className={CARD}>
          <table className="w-full min-w-[960px] border-collapse text-left text-data-xs">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className={TH}>Outcome</th>
                <th className={TH}>Symbol</th>
                <th className={TH}>List</th>
                <th className={TH}>Listed</th>
                <th className={TH}>Resolved</th>
                <th className={`${TH} text-right`}>Pivot</th>
                <th className={`${TH} text-right`}>Entry</th>
                <th className={`${TH} text-right`}>Close that day</th>
                <th className={`${TH} text-right`}>Close vs entry</th>
                <th className={`${TH} text-right`}>Score when listed</th>
              </tr>
            </thead>
            <tbody>
              {resolved.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-2 py-6 text-center text-slate-500">
                    Nothing has resolved yet.
                  </td>
                </tr>
              ) : (
                resolved.map((row) => {
                  const crossed = row.status === "triggered";
                  const outcome = crossed
                    ? row.held_above_pivot
                      ? "Crossed and held"
                      : "Crossed, closed back under"
                    : row.status === "failed"
                      ? "Lost the base low"
                      : "Drifted out";
                  const move =
                    crossed && row.resolved_price && row.resolved_close
                      ? (row.resolved_close / row.resolved_price - 1) * 100
                      : null;
                  return (
                    <tr key={row.id} className="border-t border-surface-border/70">
                      <td
                        className={`px-2 py-1 font-semibold ${
                          crossed && row.held_above_pivot ? "text-gain" : row.status === "failed" ? "text-loss" : "text-slate-300"
                        }`}
                      >
                        {outcome}
                      </td>
                      <td className="px-2 py-1 font-semibold text-slate-100">{row.ticker}</td>
                      <td className="px-2 py-1 capitalize text-slate-400">{row.timeframe}</td>
                      <td className="px-2 py-1 tabular-nums text-slate-300">{row.first_seen}</td>
                      <td className="px-2 py-1 tabular-nums text-slate-300">{row.resolved_date ?? "—"}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{price(row.pivot)}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{crossed ? price(row.resolved_price) : "—"}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{price(row.resolved_close)}</td>
                      <td className="px-2 py-1 text-right">{move == null ? "—" : <PctCell value={move} />}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{row.first_score?.toFixed(0) ?? "—"}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "alerts" ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-data-xs text-slate-300">
            {live?.telegram_configured ? (
              <>
                <span>
                  Alerts go to your Telegram chat: the 9:08 pre-open reading, live pivot tests and breaks while the feed
                  runs, and filings on watchlist stocks.
                </span>
                <button
                  type="button"
                  onClick={() => void onTestAlert()}
                  disabled={busy}
                  className="h-6 rounded-md border border-surface-border bg-surface px-2 text-[10px] font-semibold text-slate-200 disabled:opacity-40"
                >
                  Send test message
                </button>
              </>
            ) : (
              <span>
                Telegram is off, so alerts are only listed here. To get them on your phone, set TELEGRAM_BOT_TOKEN and
                TELEGRAM_ALERT_CHAT_ID in .env and restart the backend.
              </span>
            )}
          </div>
          <div className={CARD}>
            <table className="w-full min-w-[820px] border-collapse text-left text-data-xs">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className={TH}>Time</th>
                  <th className={TH}>Symbol</th>
                  <th className={TH}>Alert</th>
                  <th className={`${TH} text-right`}>Price</th>
                  <th className={`${TH} text-right`}>Pivot</th>
                  <th className={`${TH} text-right`}>Stop</th>
                  <th className={`${TH} text-right`}>Vol pace</th>
                  <th className={TH}>Telegram</th>
                </tr>
              </thead>
              <tbody>
                {alerts.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-2 py-6 text-center text-slate-500">
                      No alerts yet. They fire at 9:08 from the opening auction, and when a watchlist stock tests or
                      crosses its pivot during market hours.
                    </td>
                  </tr>
                ) : (
                  alerts.map((alert) => (
                    <tr key={alert.id} className="border-t border-surface-border/70" title={alert.message ?? undefined}>
                      <td className="px-2 py-1 tabular-nums text-slate-300">{dayAndTime(alert.created_at)}</td>
                      <td className="px-2 py-1 font-semibold text-slate-100">{alert.ticker}</td>
                      <td className={`px-2 py-1 font-semibold ${stateClass(alert.state)}`}>
                        {alert.message?.split("\n")[0]?.split(" — ")[1] ?? alert.state}
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums">{price(alert.price)}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-sky-200">{price(alert.pivot)}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-loss">{price(alert.stop)}</td>
                      <td className="px-2 py-1 text-right tabular-nums">
                        {alert.session_rvol == null ? "—" : `${alert.session_rvol.toFixed(1)}×`}
                      </td>
                      <td className="px-2 py-1 text-slate-400">
                        {alert.state.includes("preopen") ? "In the 9:08 summary" : alert.delivered ? "Sent" : "Not sent"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {tab === "results" ? (
        <Results
          report={report}
          model={model ?? null}
          list={reportList}
          onList={setReportList}
          maxPositions={maxPositions}
          onMaxPositions={setMaxPositions}
        />
      ) : null}
    </div>
  );
}

function FilingsTab({
  filings,
  watchOnly,
  onWatchOnly,
}: {
  filings: SetupFilings | null;
  watchOnly: boolean;
  onWatchOnly: (value: boolean) => void;
}) {
  const moves = filings?.typical_moves;
  const minCases = filings?.min_cases ?? 30;
  const reader =
    filings?.poller.sizing === "ai"
      ? "Each filing is read by the AI model for its size."
      : filings?.poller.sizing === "rules"
        ? "Sizes come from simple rules (rupee amounts in the document). Set GEMINI_API_KEY to have a model read results and headlines too."
        : "Reading filings for size is off.";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-data-xs text-slate-300">
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={watchOnly} onChange={(event) => onWatchOnly(event.target.checked)} />
          Watchlist stocks only
        </label>
        <span className={filings?.poller.running && !filings.poller.last_error ? "text-slate-400" : "text-amber-200"}>
          {!filings
            ? "Loading…"
            : !filings.poller.running
              ? "The NSE reader is off. Restart the backend without SETUP_FILINGS_POLL=0 to turn it on."
              : filings.poller.last_error
                ? `NSE did not answer the last read (${filings.poller.last_error}). It keeps retrying.`
                : `Read from NSE every minute. Telegram alerts go out for ${
                    filings.poller.scope === "all" ? "every stock" : "watchlist stocks"
                  }${filings.telegram_configured ? "" : " once Telegram is set up"}. ${reader}`}
        </span>
      </div>

      {moves?.rows.some((row) => row.filings > 0) ? (
        <div className={CARD}>
          <table className="w-full min-w-[820px] border-collapse text-left text-data-xs">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className={TH}>What stocks did around each kind of filing</th>
                <th className={`${TH} text-right`}>Cases</th>
                <th className={`${TH} text-right`}>Day of the news</th>
                <th className={`${TH} text-right`}>Of which at the open</th>
                <th className={`${TH} text-right`}>Next 5 sessions</th>
                <th className={`${TH} text-right`}>Beat similar stocks</th>
              </tr>
            </thead>
            <tbody>
              {moves.rows.map((row) => {
                const enough = row.measured >= minCases;
                return (
                  <tr key={row.category} className="border-t border-surface-border/70">
                    <td className="px-2 py-1 text-slate-100">{row.label}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{row.filings}</td>
                    {enough ? (
                      <>
                        <td className="px-2 py-1 text-right tabular-nums">{signed(row.avg_react_rel_pct)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{signed(row.avg_gap_rel_pct)}</td>
                        <td className="px-2 py-1 text-right">
                          {row.avg_after5_rel_pct == null ? "—" : <PctCell value={row.avg_after5_rel_pct} />}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">{pct(row.positive_after5_pct, 0)}</td>
                      </>
                    ) : (
                      <td colSpan={4} className="px-2 py-1 text-right text-slate-500">
                        Too few cases to quote
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="px-2 py-1 text-[10px] text-slate-500">
            Filings from {moves.from} to {moves.to}. Every figure is the stock's move minus the average move of stocks
            of similar liquidity over the same stretch; the last column is the share that did better than the median
            such stock. "Day of the news" is the first session that could show it, close to close.
            "Next 5 sessions" starts from the first price you could trade at after reading it, so it is what was left
            for a fast reader.
          </p>
        </div>
      ) : (
        <p className="text-[10px] text-slate-500">
          To see what stocks did after each kind of filing, load history with npm run setups:filings-history.
        </p>
      )}

      <div className={CARD}>
        <table className="w-full min-w-[1080px] border-collapse text-left text-data-xs">
          <thead className={TABLE_HEAD}>
            <tr>
              <th className={TH}>Published</th>
              <th className={TH}>Symbol</th>
              <th className={TH}>Kind</th>
              <th className={TH}>Size</th>
              <th className={TH}>Filing</th>
              <th className={TH}>Document</th>
            </tr>
          </thead>
          <tbody>
            {!filings?.rows.length ? (
              <tr>
                <td colSpan={6} className="px-2 py-6 text-center text-slate-500">
                  No price-moving filings in the last 48 hours{watchOnly ? " for watchlist stocks" : ""}.
                </td>
              </tr>
            ) : (
              filings.rows.map((filing) => {
                const impact = filing.size?.impact;
                return (
                  <tr key={filing.seq_id} className="border-t border-surface-border/70 align-top">
                    <td className="whitespace-nowrap px-2 py-1 tabular-nums text-slate-300">{dayAndTime(filing.published_at)}</td>
                    <td className="px-2 py-1 font-semibold text-slate-100" title={filing.company_name ?? undefined}>
                      {filing.ticker}
                      {filing.on_watchlist ? (
                        <span className={`${BADGE} bg-accent/20 text-sky-200`}>watchlist</span>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1 text-amber-200">{filing.category_label}</td>
                    <td className="max-w-[260px] px-2 py-1 text-slate-300">
                      {impact ? (
                        <span
                          className={`mr-1 font-semibold capitalize ${
                            impact === "high" ? (filing.size?.direction === "negative" ? "text-loss" : "text-gain") : "text-slate-300"
                          }`}
                          title={filing.size?.basis ? `Judged by ${filing.size.basis}` : undefined}
                        >
                          {impact}
                        </span>
                      ) : null}
                      {filing.size_text ?? (filing.sized ? (impact ? "" : "No number stated") : "Not read yet")}
                    </td>
                    <td className="max-w-[560px] px-2 py-1 text-slate-300">
                      <span className="text-slate-100">{filing.size?.headline ?? filing.subject}</span>
                      {!filing.size?.headline && filing.summary ? ` — ${filing.summary.slice(0, 220)}` : ""}
                    </td>
                    <td className="px-2 py-1">
                      {filing.url ? (
                        <a href={filing.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
                          Open
                        </a>
                      ) : (
                        "—"
                      )}
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

function Results({
  report,
  model,
  list,
  onList,
  maxPositions,
  onMaxPositions,
}: {
  report: SetupReport | null;
  model: SetupModel | null;
  list: SetupList;
  onList: (value: SetupList) => void;
  maxPositions: number;
  onMaxPositions: (value: number) => void;
}) {
  const controls = (
    <div className="flex flex-wrap items-center gap-2 text-data-xs text-slate-300">
      {(["daily", "weekly"] as const).map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onList(id)}
          className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${
            list === id ? "border-accent/50 bg-accent/15 text-sky-200" : "border-surface-border text-slate-400"
          }`}
        >
          {id} list
        </button>
      ))}
      <label className="inline-flex items-center gap-1">
        Most positions at once
        <select
          value={maxPositions}
          onChange={(event) => onMaxPositions(Number(event.target.value))}
          className="rounded border border-surface-border bg-surface px-1 py-0.5 text-slate-100"
        >
          {[5, 10, 15, 20].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
  if (!report) {
    return (
      <div className="flex flex-col gap-2">
        {controls}
        <div className="px-2 py-6 text-center text-data-xs text-slate-500">Working through the trades…</div>
      </div>
    );
  }
  if (!report.setups) {
    return (
      <div className="flex flex-col gap-2">
        {controls}
        <div className="px-2 py-6 text-center text-data-xs text-slate-500">
          {report.message ?? "No setups recorded yet."} To replay past months, run npm run setups:build -- --rebuild
          --from-date YYYY-MM-DD.
        </div>
      </div>
    );
  }
  const after = report.after_breakout;
  const main = report.exits?.find((row) => row.rule === report.main_rule);
  const test = model?.metrics?.test;
  return (
    <div className="flex flex-col gap-2 text-data-xs text-slate-300">
      {controls}
      <div className="flex flex-wrap gap-1.5">
        <StatChip label="Setups" value={report.setups} hint={`${report.since} to ${report.through}`} />
        <StatChip label="Crossed the pivot" value={pct(report.pivot_crossed_pct)} />
        <StatChip label="Crossed and closed above" value={pct(report.held_above_pivot_pct)} />
        <StatChip label="Closed back under, of those that crossed" value={pct(after?.closed_back_under_pivot_pct)} />
        <StatChip label="Lost the base low" value={pct(report.failed_rate_pct)} />
        <StatChip
          label="Close vs pivot entry on the day"
          value={signed(after?.avg_lead_pct)}
          hint="Positive: entering at the pivot was earlier and cheaper than buying that day's close"
        />
      </div>
      {main && main.avg_pct != null ? (
        <p className={`max-w-4xl ${main.avg_pct > 0 ? "text-slate-300" : "text-amber-200"}`}>
          Taking every setup on this list ({main.label.toLowerCase()}, stop at the base low, {report.cost_pct}% costs)
          returned {signed(main.avg_pct)} a trade on average over {main.trades} trades, and {pct(main.win_rate_pct)} of
          them made money.{" "}
          {main.avg_pct > 0
            ? "That is before your own slippage and judgement."
            : "Traded mechanically, this list has lost money over this period. The tables below show where it did better and worse."}
        </p>
      ) : null}

      {report.exits?.length ? (
        <div className={CARD}>
          <table className="w-full min-w-[980px] border-collapse text-left">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className={TH}>Exit rule</th>
                <th className={`${TH} text-right`}>Trades</th>
                <th className={`${TH} text-right`}>Average</th>
                <th className={`${TH} text-right`}>Typical</th>
                <th className={`${TH} text-right`}>Made money</th>
                <th className={`${TH} text-right`}>Stopped out</th>
                <th className={`${TH} text-right`}>Sessions held</th>
                <th className={`${TH} text-right`}>Account, {report.max_positions} positions</th>
                <th className={`${TH} text-right`}>Worst fall</th>
              </tr>
            </thead>
            <tbody>
              {report.exits.map((row) => (
                <tr key={row.rule} className="border-t border-surface-border/70">
                  <td className="px-2 py-1 text-slate-100">
                    {row.label}
                    {row.still_open ? <span className="ml-1 text-slate-500">{row.still_open} still open</span> : null}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">{row.trades}</td>
                  <td className="px-2 py-1 text-right">{row.avg_pct == null ? "—" : <PctCell value={row.avg_pct} />}</td>
                  <td className="px-2 py-1 text-right">{row.median_pct == null ? "—" : <PctCell value={row.median_pct} />}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{pct(row.win_rate_pct)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{pct(row.stopped_pct)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{row.avg_sessions?.toFixed(1) ?? "—"}</td>
                  <td className="px-2 py-1 text-right">
                    {row.portfolio.return_pct == null ? "—" : <PctCell value={row.portfolio.return_pct} />}
                    <span className="ml-1 text-slate-500">{row.portfolio.trades_taken} taken</span>
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">{signed(row.portfolio.max_drawdown_pct, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-2 py-1 text-[10px] text-slate-500">
            Per trade, after costs. "Typical" is the middle trade. The account takes the highest scores when more setups
            trigger than it has room for, puts an equal share in each, and books results when a trade closes, so the
            worst fall leaves out swings inside open trades.
          </p>
        </div>
      ) : null}

      <div className="grid gap-2 lg:grid-cols-2">
        {report.by_health?.some((row) => row.trades > 0) ? (
          <div className={CARD}>
            <table className="w-full border-collapse text-left">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className={TH}>Market the evening before</th>
                  <th className={`${TH} text-right`}>Trades</th>
                  <th className={`${TH} text-right`}>Average</th>
                  <th className={`${TH} text-right`}>Made money</th>
                </tr>
              </thead>
              <tbody>
                {report.by_health.map((row) => (
                  <tr key={row.state} className="border-t border-surface-border/70">
                    <td className={`px-2 py-1 font-semibold ${HEALTH_CLASS[row.state]}`}>{HEALTH_WORD[row.state]}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{row.trades}</td>
                    <td className="px-2 py-1 text-right">{row.avg_pct == null ? "—" : <PctCell value={row.avg_pct} />}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{pct(row.win_rate_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {report.by_score?.length ? (
          <div className={CARD}>
            <table className="w-full border-collapse text-left">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className={TH}>Score when listed</th>
                  <th className={`${TH} text-right`}>Setups</th>
                  <th className={`${TH} text-right`}>Crossed and held</th>
                  <th className={`${TH} text-right`}>Trades</th>
                  <th className={`${TH} text-right`}>Average</th>
                  <th className={`${TH} text-right`}>Made money</th>
                </tr>
              </thead>
              <tbody>
                {report.by_score.map((bucket) => (
                  <tr key={bucket.bucket} className="border-t border-surface-border/70">
                    <td className="px-2 py-1 text-slate-100">
                      {bucket.bucket}{" "}
                      <span className="text-slate-500">
                        {bucket.score_from.toFixed(0)}–{bucket.score_to.toFixed(0)}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">{bucket.setups}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{pct(bucket.held_above_pivot_pct)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{bucket.trades}</td>
                    <td className="px-2 py-1 text-right">{bucket.avg_pct == null ? "—" : <PctCell value={bucket.avg_pct} />}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{pct(bucket.win_rate_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="rounded-lg border border-surface-border bg-surface-raised p-2">
        <div className="font-semibold text-slate-100">
          Score:{" "}
          {model?.fitted ? `fitted on your candles (${model.fitted_at?.slice(0, 10)})` : "starting weights, not fitted to your data"}
        </div>
        {model?.fitted && test?.top_fifth && test.rest ? (
          <p className="mt-1 text-slate-400">
            On sessions the fit never saw ({model.metrics?.test_from} to {model.metrics?.test_to}), the top fifth by score
            returned {signed(test.top_fifth.avg_pct)} a trade against {signed(test.rest.avg_pct)} for the rest
            {test.spread_low_pct != null
              ? `, a gap of ${signed(test.spread_pct)} (likely range ${signed(test.spread_low_pct)} to ${signed(test.spread_high_pct)})`
              : ""}
            . {test.verdict === "ranks" ? "The whole range is above zero, so the score is ranking setups." : "The range includes zero, so the score has not shown it can rank setups."}
          </p>
        ) : (
          <p className="mt-1 text-slate-400">
            The starting weights count four readings that pointed the same way in two separate periods of NSE data from
            February 2025 to November 2026: nearness to the 52-week high, an industry group making new highs, a healthy
            market, and a group that has not already run ahead. They have not been tested on later data. The score table
            above includes the period they were set on, so it flatters them. Run npm run setups:fit to derive and test
            weights on your own candles.
          </p>
        )}
      </div>
    </div>
  );
}
