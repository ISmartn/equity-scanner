// Setup watchlist: stocks still inside a base, before the breakout.

export type SetupStatus = "active" | "triggered" | "failed" | "expired";
export type SetupList = "daily" | "weekly";
export type HealthState = "green" | "amber" | "red";

export type SetupLiveState =
  | "breakout"
  | "crossed_light"
  | "testing"
  | "near"
  | "gapped"
  | "extended"
  | "waiting"
  | "failed";

export interface FilingSize {
  headline?: string | null;
  direction?: "positive" | "negative" | "neutral" | null;
  amount_cr?: number | null;
  size_pct?: number | null;
  sales_yoy_pct?: number | null;
  profit_yoy_pct?: number | null;
  impact?: "high" | "medium" | "low" | null;
  basis?: string | null;
  read_by?: "ai" | "rules";
}

export interface SetupFiling {
  seq_id: string;
  ticker: string;
  company_name: string | null;
  category: string;
  category_label: string;
  subject: string | null;
  summary: string | null;
  url: string | null;
  filed_at: string;
  published_at: string;
  alerted: number;
  delivered: number;
  sized: number;
  impact: string | null;
  size: FilingSize | null;
  size_text: string | null;
  on_watchlist?: boolean;
}

export interface PreopenRow {
  ticker: string;
  timeframe: SetupList;
  iep: number;
  pivot: number;
  stop: number;
  gap_to_pivot_pct: number;
  qty_pct: number | null;
  state: string;
  label: string;
}

export interface SetupRow {
  id: number;
  ticker: string;
  company_name: string | null;
  sector: string | null;
  timeframe: SetupList;
  status: SetupStatus;
  first_seen: string;
  last_seen: string;
  days_in_base: number;
  pivot: number;
  stop: number;
  last_close: number | null;
  score: number | null;
  first_score: number | null;
  distance_pct?: number;
  risk_pct?: number;
  resolved_date: string | null;
  resolved_price: number | null;
  resolved_close: number | null;
  held_above_pivot?: boolean;
  features: Record<string, number> & { contributions?: Record<string, number> };
  /** Latest price-moving NSE filing in the last 24 hours. */
  filing?: SetupFiling | null;
  /** Nearest dated event in the next 5 days: results, a board meeting, or an ex-date. */
  event?: { event_date: string; purpose: string; detail: string | null } | null;
  flags?: { flag: string; label: string; detail: string | null }[];
  /** Latest large buy in the last 10 days by a client that did not also sell that day. */
  large_buy?: { trade_date: string; client: string; quantity: number; price: number; kind: string } | null;
  /** Today's opening-auction reading, when the stock is set to open near its pivot or stop. */
  preopen?: PreopenRow | null;
}

export interface MarketHealth {
  trade_date: string;
  stocks: number;
  pct_above_50: number | null;
  new_highs: number | null;
  new_lows: number | null;
  breadth_chg: number | null;
  state: HealthState;
  label: string;
}

export interface TradeGroup {
  trades: number;
  avg_pct?: number;
  median_pct?: number;
  win_rate_pct?: number;
}

export interface ScoreTest {
  all: TradeGroup;
  top_fifth?: TradeGroup;
  rest?: TradeGroup;
  spread_pct?: number | null;
  spread_low_pct?: number;
  spread_high_pct?: number;
  verdict: "ranks" | "no_evidence" | "too_few_trades" | "too_few_days";
}

export interface SetupModel {
  fitted: boolean;
  fitted_at: string | null;
  metrics: {
    test_from: string | null;
    test_to: string | null;
    kept?: string[];
    test: ScoreTest;
  } | null;
  features: { name: string; label: string; weight: number }[];
}

export interface SetupWatchlist {
  processed_through: string | null;
  counts: Partial<Record<SetupStatus, number>>;
  counts_by_list: Record<SetupList, Partial<Record<SetupStatus, number>>>;
  rows: SetupRow[];
  model: SetupModel;
  health: MarketHealth | null;
}

export interface SetupLiveRow {
  symbol: string;
  list: SetupList;
  also_weekly?: boolean;
  ltp: number;
  pivot: number;
  stop: number;
  distance_pct: number;
  risk_pct: number;
  session_rvol: number | null;
  state: SetupLiveState;
  state_label: string;
  reason: string;
  stale: boolean;
}

export interface SetupLive {
  status: string;
  session_date: string | null;
  ranked_at: number | null;
  stale: boolean;
  rows: SetupLiveRow[];
  alerts_raised: number;
  alerts_delivered: number;
  telegram_configured: boolean;
  watchlist_sync: { status: string; message?: string; processed_through?: string } | null;
  /** Set when the list has not been processed through this completed session. */
  watchlist_behind: string | null;
}

export interface SetupAlert {
  id: number;
  session_date: string;
  ticker: string;
  state: string;
  price: number | null;
  pivot: number | null;
  stop: number | null;
  session_rvol: number | null;
  message: string | null;
  delivered: number;
  created_at: string;
}

export interface TypicalMove {
  category: string;
  label: string;
  filings: number;
  measured: number;
  avg_react_pct: number | null;
  avg_react_rel_pct: number | null;
  avg_gap_rel_pct: number | null;
  avg_after5_pct: number | null;
  avg_after5_rel_pct: number | null;
  positive_after5_pct: number | null;
}

export interface SetupFilings {
  rows: SetupFiling[];
  poller: {
    running: boolean;
    last_ok_at: number | null;
    last_error: string | null;
    scope: string;
    sizing: "ai" | "rules" | "off";
  };
  telegram_configured: boolean;
  typical_moves: { computed_at: string; from: string; to: string; rows: TypicalMove[] } | null;
  min_cases: number;
}

export interface ExitResult {
  rule: string;
  label: string;
  trades: number;
  still_open: number;
  avg_pct: number | null;
  median_pct: number | null;
  win_rate_pct: number | null;
  avg_sessions: number | null;
  stopped_pct: number | null;
  portfolio: { trades_taken: number; skipped: number; return_pct: number | null; max_drawdown_pct: number | null };
}

export interface SetupScoreBucket {
  bucket: string;
  score_from: number;
  score_to: number;
  setups: number;
  pivot_crossed_pct: number | null;
  held_above_pivot_pct: number | null;
  trades: number;
  avg_pct: number | null;
  win_rate_pct: number | null;
}

export interface SetupReport {
  setups: number;
  timeframe: SetupList;
  message?: string;
  since?: string;
  through?: string;
  resolved?: number;
  counts?: Record<SetupStatus, number>;
  pivot_crossed_pct?: number | null;
  held_above_pivot_pct?: number | null;
  failed_rate_pct?: number | null;
  median_sessions_to_cross?: number | null;
  after_breakout?: {
    pivot_crosses: number;
    avg_lead_pct: number | null;
    closed_back_under_pivot_pct: number | null;
  };
  cost_pct?: number;
  max_positions?: number;
  main_rule?: string;
  exits?: ExitResult[];
  by_health?: { state: HealthState; trades: number; avg_pct: number | null; win_rate_pct: number | null }[];
  by_score?: SetupScoreBucket[];
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* body was plain text */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function fetchSetupWatchlist(status: SetupStatus | "all" = "active"): Promise<SetupWatchlist> {
  return json(await fetch(`/api/early-setup/watchlist?status=${status}&list=all&limit=400`));
}

export async function fetchSetupLive(): Promise<SetupLive> {
  return json(await fetch("/api/early-setup/live"));
}

export async function fetchSetupAlerts(): Promise<{ rows: SetupAlert[]; telegram_configured: boolean }> {
  return json(await fetch("/api/early-setup/alerts?limit=200"));
}

export async function fetchSetupFilings(watchlistOnly: boolean): Promise<SetupFilings> {
  return json(await fetch(`/api/early-setup/filings?hours=48&watchlist_only=${watchlistOnly}`));
}

export async function fetchSetupReport(list: SetupList, maxPositions: number): Promise<SetupReport> {
  return json(await fetch(`/api/early-setup/report?list=${list}&max_positions=${maxPositions}`));
}

export async function buildSetupWatchlist(): Promise<{ status: string; message?: string; processed_through?: string }> {
  return json(await fetch("/api/early-setup/build", { method: "POST" }));
}

export async function sendSetupTestAlert(): Promise<{ delivered: boolean }> {
  return json(await fetch("/api/early-setup/alerts/test", { method: "POST" }));
}
