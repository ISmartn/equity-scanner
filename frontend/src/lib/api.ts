import { getUpstoxToken } from "./storage";

export type Interval = "daily" | "weekly" | "monthly";
export type ForecastModelKind = "timesfm-2.5" | "timesfm-fin";

export interface ForecastModelId {
  id: ForecastModelKind;
  label: string;
  description: string;
  available: boolean;
  default: boolean;
}

export interface CandlePoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  pct_change?: number | null;
}

export interface CandlesPayload {
  symbol: string;
  interval: Interval;
  source: "upstox" | "nse";
  lookback_years: number;
  history_bars: number;
  history: CandlePoint[];
  latest_close: number;
}

export interface ForecastPayload {
  symbol: string;
  interval: Interval;
  source: "upstox" | "nse";
  model: ForecastModelKind;
  model_label: string;
  horizon: number;
  device: string;
  context_length: number;
  lookback_years: number;
  history_bars: number;
  history: CandlePoint[];
  forecast_dates: string[];
  median: number[];
  lower: number[];
  upper: number[];
  latest_close: number;
  spread_pct: number;
}

export interface Nifty50Response {
  symbols: string[];
  count: number;
}

export type FnoResponse = Nifty50Response;

export interface ModelsResponse {
  models: ForecastModelId[];
}

export interface SymbolSearchResult {
  symbol: string;
  name: string;
  instrument_key: string;
}

export interface SymbolSearchResponse {
  query: string;
  results: SymbolSearchResult[];
  count: number;
}

function authHeaders(): HeadersInit {
  const token = getUpstoxToken();
  return token ? { "x-upstox-access-token": token } : {};
}

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function fetchNifty50(): Promise<Nifty50Response> {
  const res = await fetch("/api/nifty50");
  return parseJson(res);
}

export async function fetchFno(): Promise<FnoResponse> {
  const res = await fetch("/api/fno");
  return parseJson(res);
}

export async function fetchModels(): Promise<ModelsResponse> {
  const res = await fetch("/api/models");
  return parseJson(res);
}

export async function searchSymbols(query: string, limit = 15): Promise<SymbolSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const res = await fetch(`/api/symbols/search?${params}`);
  return parseJson(res);
}

export async function fetchCandles(
  symbol: string,
  interval: Interval = "daily",
): Promise<CandlesPayload> {
  const params = new URLSearchParams({ symbol, interval });
  const res = await fetch(`/api/candles?${params}`, {
    headers: authHeaders(),
  });
  return parseJson(res);
}

export async function fetchForecast(
  symbol: string,
  interval: Interval,
  model?: string,
  horizon?: number,
): Promise<ForecastPayload> {
  const params = new URLSearchParams({ symbol, interval });
  if (model) params.set("model", model);
  if (horizon) params.set("horizon", String(horizon));

  const res = await fetch(`/api/forecast?${params}`, {
    headers: authHeaders(),
  });
  return parseJson(res);
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch("/api/health");
    return res.ok;
  } catch {
    return false;
  }
}

export interface HealthTimelineStats {
  profile_count: number;
  symbols_with_data: number;
  candle_count: number;
  max_trade_date?: string | null;
  target_trade_date?: string | null;
  is_up_to_date?: boolean;
}

export interface HealthResponse {
  status: string;
  timeline?: HealthTimelineStats;
}

export async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return null;
    return parseJson<HealthResponse>(res);
  } catch {
    return null;
  }
}

export interface TimelineStats {
  db_path: string;
  profile_count: number;
  candle_count: number;
  sector_count: number;
  symbols_with_data: number;
  min_trade_date: string | null;
  max_trade_date: string | null;
  target_trade_date: string;
  is_up_to_date: boolean;
  symbols_at_max_date: number;
  symbols_behind_target: number;
  ingest_skip_count?: number;
  institutional_flow_count?: number;
  derivative_snapshot_count?: number;
}

export interface TimelineMoverRow {
  ticker: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  trade_date: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  volume: number | null;
  daily_return_pct: number | null;
  source: string | null;
}

export interface TimelineMoversResponse {
  trade_date: string;
  sector: string | null;
  min_move_pct: number;
  direction: string;
  total: number;
  limit: number;
  offset: number;
  results: TimelineMoverRow[];
}

export interface TimelineIngestResult {
  processed: number;
  success: number;
  failed: number;
  skipped?: number;
  empty?: number;
  total_bars: number;
  from_date?: string;
  to_date?: string;
  message?: string;
  status?: string;
  mode?: string;
  since_last?: boolean;
  concurrency?: number;
  error_log?: string;
  errors?: Record<string, string>;
  results?: Array<{ ticker: string; status: string; error?: string }>;
}

export interface TimelineIngestStatus {
  running: boolean;
  mode: string | null;
  total: number;
  processed: number;
  success: number;
  failed: number;
  skipped: number;
  empty?: number;
  total_bars: number;
  cancel_requested?: boolean;
  current_ticker: string | null;
  last_result: TimelineIngestResult | { error: string } | null;
  recent_errors?: Array<{ ticker: string; error: string }>;
  error_log?: string;
}

export interface TimelineCandlePoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  daily_return_pct?: number | null;
  source?: string | null;
}

export interface TimelineCandlesPayload {
  symbol: string;
  source: string;
  history_bars: number;
  from_date: string | null;
  to_date: string | null;
  history: TimelineCandlePoint[];
}

export async function fetchTimelineStats(): Promise<TimelineStats> {
  const res = await fetch("/api/timeline/stats");
  return parseJson(res);
}

export async function fetchTimelineSectors(): Promise<{ sectors: string[]; count: number }> {
  const res = await fetch("/api/timeline/sectors");
  return parseJson(res);
}

export async function fetchTimelineDates(limit = 365): Promise<{ dates: string[]; count: number }> {
  const res = await fetch(`/api/timeline/dates?limit=${limit}`);
  return parseJson(res);
}

export async function fetchTimelineMovers(params: {
  tradeDate: string;
  sector?: string;
  ticker?: string;
  minMovePct?: number;
  direction?: "both" | "up" | "down";
  limit?: number;
  offset?: number;
}): Promise<TimelineMoversResponse> {
  const search = new URLSearchParams({ trade_date: params.tradeDate });
  if (params.ticker) search.set("ticker", params.ticker);
  if (params.sector) search.set("sector", params.sector);
  if (params.minMovePct != null) search.set("min_move_pct", String(params.minMovePct));
  if (params.direction) search.set("direction", params.direction);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const res = await fetch(`/api/timeline/movers?${search}`);
  return parseJson(res);
}

export async function fetchTimelineCandles(symbol: string): Promise<TimelineCandlesPayload> {
  const params = new URLSearchParams({ symbol });
  const res = await fetch(`/api/timeline/candles?${params}`);
  return parseJson(res);
}

export async function syncTimelineProfiles(): Promise<{
  profiles_upserted: number;
  total_mainboard: number;
  sectors_assigned: number;
}> {
  const res = await fetch("/api/timeline/sync-profiles", { method: "POST" });
  return parseJson(res);
}

export async function reprofileTimelineStale(): Promise<{
  profiles_upserted: number;
  ingest_skip_marked: number;
  ingest_skip_cleared: number;
  instrument_tokens_migrated: number;
  marked_tickers: string[];
}> {
  const res = await fetch("/api/timeline/reprofile-stale", { method: "POST" });
  return parseJson(res);
}

export async function ingestTimelineCandles(body: {
  years?: number;
  days?: number;
  limit?: number;
  tickers?: string[];
  refreshAll?: boolean;
  sinceLast?: boolean;
  bootstrapDays?: number;
  source?: "auto" | "upstox" | "nse";
  backgroundRun?: boolean;
  concurrency?: number;
  requestDelaySec?: number;
}): Promise<TimelineIngestResult> {
  const params = new URLSearchParams();
  if (body.backgroundRun !== undefined) {
    params.set("background_run", String(body.backgroundRun));
  }
  const res = await fetch(`/api/timeline/ingest?${params}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      years: body.years ?? 2,
      days: body.days,
      limit: body.limit,
      tickers: body.tickers,
      refresh_all: body.refreshAll ?? false,
      since_last: body.sinceLast ?? false,
      bootstrap_days: body.bootstrapDays ?? 30,
      source: body.source ?? "auto",
      concurrency: body.concurrency ?? 3,
      request_delay_sec: body.requestDelaySec ?? 0.35,
    }),
  });
  return parseJson(res);
}

export async function fetchTimelineIngestStatus(): Promise<TimelineIngestStatus> {
  const res = await fetch("/api/timeline/ingest/status");
  return parseJson(res);
}

export async function cancelTimelineIngest(): Promise<{ status: string; message: string }> {
  const res = await fetch("/api/timeline/ingest/cancel", { method: "POST" });
  return parseJson(res);
}

export interface StockFundamentals {
  ticker: string;
  isin: string | null;
  updated_at: string;
  cached: boolean;
  profile: Record<string, unknown> | null;
  balance_sheet: Record<string, unknown> | unknown[] | null;
  cash_flow: Record<string, unknown> | unknown[] | null;
  income_statement: Record<string, unknown> | unknown[] | null;
  share_holdings: Record<string, unknown> | unknown[] | null;
  key_ratios: Record<string, unknown> | unknown[] | null;
  corporate_actions: Record<string, unknown> | unknown[] | null;
  competitors: Record<string, unknown> | unknown[] | null;
  partial_errors?: string[];
}

export interface SyncFundamentalsResult {
  requested: number;
  success: number;
  failed: number;
  tickers_synced: string[];
  errors: Record<string, string>;
}

export async function fetchStockFundamentals(
  ticker: string,
  fetchIfMissing = true,
): Promise<StockFundamentals> {
  const params = new URLSearchParams({
    ticker,
    fetch_if_missing: String(fetchIfMissing),
  });
  const res = await fetch(`/api/timeline/fundamentals?${params}`, {
    headers: authHeaders(),
  });
  return parseJson(res);
}

export async function syncStockFundamentals(
  tickers: string[],
  force = true,
): Promise<SyncFundamentalsResult> {
  const res = await fetch("/api/timeline/sync-fundamentals", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({ tickers, force }),
  });
  return parseJson(res);
}

export type ScannerPatternId =
  | "vcp"
  | "high_tight_flag"
  | "pocket_pivot"
  | "pocket_pivot_setup"
  | "inside_bar_cluster"
  | "power_gap"
  | "tight_range_near_pivot";

export interface ScannerPatternSignal {
  ticker: string;
  company_name: string | null;
  sector: string | null;
  trade_date: string;
  pattern_type: ScannerPatternId;
  macro_pass: boolean;
  score: number;
  triggered_today: boolean;
  setup_ready: boolean;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
  daily_return_pct?: number | null;
  details: Record<string, unknown>;
}

export interface ScannerResultsResponse {
  trade_date: string;
  total: number;
  limit: number;
  offset: number;
  scan_alerts_count?: number | null;
  results: ScannerPatternSignal[];
}

export interface ScannerStatus {
  running: boolean;
  total: number;
  processed: number;
  alerts_count: number;
  current_ticker: string | null;
  trade_date: string | null;
  batch_mode?: "month" | "last_7" | null;
  batch_dates?: string[] | null;
  batch_day_index?: number;
  batch_day_total?: number;
  last_result: Record<string, unknown> | null;
}

export type ScannerBatchMode = "single" | "month" | "last_7";
export type ScannerSortMode = "score" | "setup_first";
export type ScannerScanMode = "confirmation" | "early_setup";

export async function fetchScannerDates(): Promise<{
  dates: string[];
  refined_dates?: string[];
  engine_version?: string | null;
  count: number;
  latest_data_date: string | null;
  latest_with_alerts?: string | null;
}> {
  const res = await fetch("/api/scanner/dates?limit=365");
  return parseJson(res);
}

export async function fetchScannerPatterns(): Promise<{
  patterns: { id: ScannerPatternId; label: string; type: string }[];
}> {
  const res = await fetch("/api/scanner/patterns");
  return parseJson(res);
}

export async function runScanner(body: {
  tradeDate?: string;
  backgroundRun?: boolean;
  batch?: ScannerBatchMode;
}): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  if (body.backgroundRun !== undefined) {
    params.set("background_run", String(body.backgroundRun));
  }
  const res = await fetch(`/api/scanner/run?${params}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trade_date: body.tradeDate,
      batch: body.batch ?? "single",
    }),
  });
  return parseJson(res);
}

export async function fetchScannerStatus(): Promise<ScannerStatus> {
  const res = await fetch("/api/scanner/status");
  return parseJson(res);
}

export async function ensureScannerDerivatives(params: {
  tradeDate: string;
  tickers: string[];
}): Promise<{
  trade_date: string;
  requested: number;
  fno_tickers: string[];
  already_present: string[];
  synced: string[];
  failed: { symbol: string; error: string }[];
  skipped_not_fno?: string[];
  skipped_no_profile?: string[];
}> {
  const res = await fetch("/api/scanner/ensure-derivatives", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      trade_date: params.tradeDate,
      tickers: params.tickers,
    }),
  });
  return parseJson(res);
}

export async function fetchScannerResults(params: {
  tradeDate: string;
  pattern?: ScannerPatternId;
  patterns?: ScannerPatternId[];
  excludePatterns?: ScannerPatternId[];
  minScore?: number;
  sector?: string;
  triggeredOnly?: boolean;
  setupOnly?: boolean;
  macroPassOnly?: boolean;
  fundamentalPassOnly?: boolean;
  maxPre20dReturn?: number;
  maxSignalDayReturn?: number;
  sort?: ScannerSortMode;
  limit?: number;
  offset?: number;
}): Promise<ScannerResultsResponse> {
  const search = new URLSearchParams({ trade_date: params.tradeDate });
  if (params.pattern) search.set("pattern", params.pattern);
  if (params.patterns?.length) {
    for (const p of params.patterns) search.append("patterns", p);
  }
  if (params.excludePatterns?.length) {
    for (const p of params.excludePatterns) search.append("exclude_patterns", p);
  }
  if (params.minScore != null) search.set("min_score", String(params.minScore));
  if (params.sector) search.set("sector", params.sector);
  if (params.triggeredOnly) search.set("triggered_only", "true");
  if (params.setupOnly) search.set("setup_only", "true");
  if (params.macroPassOnly) search.set("macro_pass_only", "true");
  if (params.fundamentalPassOnly) search.set("fundamental_pass_only", "true");
  if (params.maxPre20dReturn != null) {
    search.set("max_pre_20d_return", String(params.maxPre20dReturn));
  }
  if (params.maxSignalDayReturn != null) {
    search.set("max_signal_day_return", String(params.maxSignalDayReturn));
  }
  if (params.sort) search.set("sort", params.sort);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const res = await fetch(`/api/scanner/results?${search}`);
  return parseJson(res);
}

export interface InstitutionalFlowRow {
  flow_type: string;
  data_type: string;
  interval_code: string;
  record_ts: number;
  buy_amount: number | null;
  sell_amount: number | null;
  net_amount: number | null;
  buy_contracts: number | null;
  sell_contracts: number | null;
  oi_contracts: number | null;
  oi_amount: number | null;
  synced_at: string;
}

export interface InstitutionalFlowsResponse {
  interval: string;
  count: number;
  results: InstitutionalFlowRow[];
}

export interface DerivativeSnapshotSummary {
  instrument_key: string;
  symbol: string;
  expiry: string;
  trade_date: string;
  total_call_oi: number | null;
  total_put_oi: number | null;
  spot_close: number | null;
  pcr: number | null;
  max_pain_strike: number | null;
  synced_at: string;
}

export interface DerivativeSnapshotsResponse {
  trade_date: string | null;
  count: number;
  results: DerivativeSnapshotSummary[];
}

export interface DerivativeSnapshotDetail extends DerivativeSnapshotSummary {
  oi_payload?: Record<string, unknown>;
  change_oi_payload?: Record<string, unknown>;
  pcr_payload?: Record<string, unknown>;
  max_pain_payload?: Record<string, unknown>;
}

export async function fetchInstitutionalFlows(params?: {
  flowType?: "FII" | "DII";
  dataType?: string;
  interval?: "1D" | "1M";
  limit?: number;
}): Promise<InstitutionalFlowsResponse> {
  const search = new URLSearchParams();
  if (params?.flowType) search.set("flow_type", params.flowType);
  if (params?.dataType) search.set("data_type", params.dataType);
  if (params?.interval) search.set("interval", params.interval);
  if (params?.limit != null) search.set("limit", String(params.limit));
  const res = await fetch(`/api/market-info/flows?${search}`);
  return parseJson(res);
}

export async function fetchDerivativeSnapshots(params?: {
  tradeDate?: string;
  symbol?: string;
  limit?: number;
}): Promise<DerivativeSnapshotsResponse> {
  const search = new URLSearchParams();
  if (params?.tradeDate) search.set("trade_date", params.tradeDate);
  if (params?.symbol) search.set("symbol", params.symbol);
  if (params?.limit != null) search.set("limit", String(params.limit));
  const res = await fetch(`/api/market-info/derivatives?${search}`);
  return parseJson(res);
}

export async function fetchDerivativeDetail(
  symbol: string,
  tradeDate: string,
): Promise<DerivativeSnapshotDetail> {
  const search = new URLSearchParams({ symbol, trade_date: tradeDate });
  const res = await fetch(`/api/market-info/derivatives/detail?${search}`);
  return parseJson(res);
}

export async function syncMarketInfo(body?: {
  tradeDate?: string;
  expiry?: string;
  symbols?: string[];
  flows?: boolean;
  derivatives?: boolean;
  flowInterval?: "1D" | "1M";
  includeIndices?: boolean;
  includeStocks?: boolean;
  stockLimit?: number;
}): Promise<Record<string, unknown>> {
  const res = await fetch("/api/market-info/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      trade_date: body?.tradeDate,
      expiry: body?.expiry,
      symbols: body?.symbols,
      flows: body?.flows ?? true,
      derivatives: body?.derivatives ?? true,
      flow_interval: body?.flowInterval ?? "1D",
      include_indices: body?.includeIndices ?? true,
      include_stocks: body?.includeStocks ?? true,
      stock_limit: body?.stockLimit ?? 5,
    }),
  });
  return parseJson(res);
}

export interface OiMomentumMetrics {
  strikes: number[];
  zone_put_addition: number;
  zone_call_unwinding: number;
  zone_put_volume_delta: number;
  total_zone_put_oi: number;
  rapid_put_surge: boolean;
  call_unwind: boolean;
  volume_confirmed: boolean;
  pcr_momentum: number | null;
  oi_volume_ratio?: number | null;
}

export interface OiMomentumSignalQuality {
  strike_rotation: boolean;
  price_aligned: boolean;
  spot_delta_pts?: number;
  oi_volume_ratio?: number | null;
  notify_eligible: boolean;
  suppress_reason?: string | null;
}

export interface OiMomentumStrikeDetail {
  strike_price: number;
  put_oi: number;
  call_oi: number;
  put_volume: number;
  call_volume: number;
  put_oi_delta: number | null;
  call_oi_delta: number | null;
  put_volume_delta: number | null;
}

export interface OiMomentumEvaluation {
  alert: "strong" | "mild" | "neutral" | "warming";
  message: string;
  spot: number;
  raw_atm: number;
  smoothed_atm: number;
  strike_step: number;
  window_sec: number;
  target_window_sec: number;
  baseline_mode: "none" | "partial" | "full";
  baseline_age_sec: number | null;
  warming: boolean;
  put_surge_threshold_pct?: number;
  min_put_volume_threshold?: number;
  signal_quality?: OiMomentumSignalQuality;
  metrics: OiMomentumMetrics;
  strike_details: OiMomentumStrikeDetail[];
}

export interface OiMomentumAlertRecord {
  id: string;
  recorded_at: number;
  symbol: string;
  source: string;
  expiry?: string | null;
  window_sec: number;
  notify_alert: "strong" | "mild";
  notify_phase: "full" | "early";
  evaluation_alert: string;
  baseline_mode: string;
  message: string;
  price_action: {
    spot: number;
    spot_at_baseline: number | null;
    spot_delta: number | null;
    spot_delta_pct: number | null;
    raw_atm: number;
    smoothed_atm: number;
    captured_at: number;
    baseline_captured_at: number | null;
  };
  zone_metrics: OiMomentumMetrics;
  gates: Record<string, unknown>;
  signal_quality?: OiMomentumSignalQuality;
  strike_details: OiMomentumStrikeDetail[];
  baseline_oi: OiMomentumStrikeDetail[];
  current_oi: OiMomentumStrikeDetail[];
  spot_trail: Array<{ captured_at: number; spot: number; smoothed_atm: number }>;
}

export interface OiMomentumAlertEvent {
  is_new: boolean;
  notify_alert: "strong" | "mild";
  notify_phase: "full" | "early";
  dedup_key: string;
  record: OiMomentumAlertRecord;
}

export interface OiMomentumResponse {
  symbol: string;
  expiry: string;
  source?: "rest_poll" | "websocket";
  polled_at: number;
  stream?: OiStreamStatus;
  history: {
    count: number;
    oldest_age_sec: number | null;
    newest_age_sec: number | null;
    smoothed_atm?: number;
  };
  evaluation: OiMomentumEvaluation;
  alert_event?: OiMomentumAlertEvent | null;
  note: string;
}

export async function fetchOiMomentumAlerts(params?: {
  symbol?: string;
  limit?: number;
}): Promise<{ count: number; records: OiMomentumAlertRecord[] }> {
  const search = new URLSearchParams();
  if (params?.symbol) search.set("symbol", params.symbol);
  if (params?.limit != null) search.set("limit", String(params.limit));
  const qs = search.toString();
  const res = await fetch(`/api/oi-momentum/alerts${qs ? `?${qs}` : ""}`);
  return parseJson(res);
}

export async function exportOiMomentumAlerts(params?: {
  symbol?: string;
  limit?: number;
}): Promise<{ path: string; count: number; records: OiMomentumAlertRecord[] }> {
  const search = new URLSearchParams();
  if (params?.symbol) search.set("symbol", params.symbol);
  if (params?.limit != null) search.set("limit", String(params.limit));
  const qs = search.toString();
  const res = await fetch(`/api/oi-momentum/alerts/export${qs ? `?${qs}` : ""}`);
  return parseJson(res);
}

export async function evaluateOiMomentum(params: {
  symbol: string;
  windowSec?: number;
  expiry?: string;
  source?: "auto" | "rest" | "websocket";
}): Promise<OiMomentumResponse> {
  const search = new URLSearchParams({ symbol: params.symbol });
  if (params.windowSec != null) search.set("window_sec", String(params.windowSec));
  if (params.expiry) search.set("expiry", params.expiry);
  if (params.source) search.set("source", params.source);
  const res = await fetch(`/api/oi-momentum/evaluate?${search}`, {
    headers: authHeaders(),
  });
  return parseJson(res);
}

export interface OiStreamStatus {
  symbol: string;
  expiry?: string;
  status: "stopped" | "connecting" | "connected" | "error";
  error?: string | null;
  tick_count?: number;
  last_tick_at?: number | null;
  spot?: number | null;
  zone_strikes?: number[];
  subscribed_keys?: string[];
}

export async function startOiMomentumStream(symbol: string): Promise<OiStreamStatus> {
  const res = await fetch("/api/oi-momentum/stream/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ symbol }),
  });
  return parseJson(res);
}

export async function stopOiMomentumStream(symbol: string): Promise<OiStreamStatus> {
  const search = new URLSearchParams({ symbol });
  const res = await fetch(`/api/oi-momentum/stream/stop?${search}`, {
    method: "POST",
    headers: authHeaders(),
  });
  return parseJson(res);
}

export async function fetchOiStreamStatus(symbol?: string): Promise<OiStreamStatus | { sessions: OiStreamStatus[] }> {
  const search = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  const res = await fetch(`/api/oi-momentum/stream/status${search}`);
  return parseJson(res);
}

// --- News Impact (Telegram / Redbox) ---------------------------------------

export interface NewsReaction {
  event_id: number;
  horizon: string;
  return_pct: number | null;
  rel_return_pct: number | null;
  close_price: number | null;
  trade_date: string | null;
}

export interface NewsEvent {
  id: number;
  message_pk: number;
  ticker: string | null;
  company_name_matched: string | null;
  match_confidence: number | null;
  event_date: string | null;
  sentiment: string | null;
  themes: string[];
  summary: string | null;
  gemini_extract: Record<string, unknown> | null;
  outlook: {
    bias?: string;
    expected_horizon?: string | null;
    typical_move_pct?: number | null;
    confidence?: number;
    rationale?: string | null;
    risks?: string[];
    sample_size?: number;
  } | null;
  status: string;
  message_text?: string | null;
  posted_at?: string | null;
  channel_key?: string | null;
  telegram_message_id?: number | null;
  reactions?: NewsReaction[];
}

export interface NewsStats {
  message_count: number;
  unprocessed_messages: number;
  event_count: number;
  linked_events: number;
  events_with_reactions: number;
  channels: string[];
  gemini_enabled: boolean;
  channel_meta: Array<{
    channel_key: string;
    title?: string | null;
    last_message_id?: number | null;
    last_synced_at?: string | null;
  }>;
  sync: { running: boolean; mode: string | null; error: string | null };
  live?: {
    status: string;
    running: boolean;
    error: string | null;
    started_at: string | null;
    stopped_at: string | null;
    last_event_at: string | null;
    catch_up: boolean;
  };
  monitors?: Array<{ key: string; label: string; keywords: string[] }>;
}

export interface NewsImpactAggregates {
  event_count: number;
  overall: Record<string, { count: number; avg_return_pct: number | null; win_rate: number | null }>;
  by_sentiment: Record<
    string,
    Record<string, { count: number; avg_return_pct: number | null; win_rate: number | null }>
  >;
}

export async function fetchNewsStats(): Promise<NewsStats> {
  const res = await fetch("/api/news/stats");
  return parseJson(res);
}

export interface TelegramNewsMessage {
  id: number;
  channel_key: string;
  channel_id: string | null;
  message_id: number;
  posted_at: string;
  text: string | null;
  processed: number;
  event_count: number;
  primary_ticker: string | null;
  sentiment: string | null;
  event_status: string | null;
  monitor_topics?: string[];
}

export async function fetchNewsMessages(params?: {
  channel?: string;
  topic?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; limit: number; offset: number; results: TelegramNewsMessage[] }> {
  const search = new URLSearchParams();
  if (params?.channel) search.set("channel", params.channel);
  if (params?.topic) search.set("topic", params.topic);
  search.set("limit", String(params?.limit ?? 50));
  search.set("offset", String(params?.offset ?? 0));
  const res = await fetch(`/api/news/messages?${search}`);
  return parseJson(res);
}

export async function syncNews(body?: {
  backfill?: boolean;
  limit?: number;
  process?: boolean;
}): Promise<unknown> {
  const res = await fetch("/api/news/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      backfill: body?.backfill ?? false,
      limit: body?.limit ?? 500,
      process: body?.process ?? true,
    }),
  });
  return parseJson(res);
}

export async function startNewsLive(body?: {
  catch_up?: boolean;
  process?: boolean;
}): Promise<NonNullable<NewsStats["live"]>> {
  const res = await fetch("/api/news/live/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      catch_up: body?.catch_up ?? true,
      process: body?.process ?? true,
    }),
  });
  return parseJson(res);
}

export async function stopNewsLive(): Promise<NonNullable<NewsStats["live"]>> {
  const res = await fetch("/api/news/live/stop", { method: "POST" });
  return parseJson(res);
}

export async function fetchNewsLiveStatus(): Promise<NonNullable<NewsStats["live"]>> {
  const res = await fetch("/api/news/live/status");
  return parseJson(res);
}

export async function fetchNewsEvents(params: {
  ticker?: string;
  sentiment?: string;
  status?: string;
  fromDate?: string;
  toDate?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; limit: number; offset: number; results: NewsEvent[] }> {
  const search = new URLSearchParams();
  if (params.ticker) search.set("ticker", params.ticker);
  if (params.sentiment) search.set("sentiment", params.sentiment);
  if (params.status) search.set("status", params.status);
  if (params.fromDate) search.set("from_date", params.fromDate);
  if (params.toDate) search.set("to_date", params.toDate);
  search.set("limit", String(params.limit ?? 50));
  search.set("offset", String(params.offset ?? 0));
  const res = await fetch(`/api/news/events?${search}`);
  return parseJson(res);
}

export async function fetchNewsEvent(id: number): Promise<NewsEvent> {
  const res = await fetch(`/api/news/events/${id}`);
  return parseJson(res);
}

export async function patchNewsEvent(
  id: number,
  body: { ticker?: string; status?: string; sentiment?: string; company_name_matched?: string },
): Promise<NewsEvent> {
  const res = await fetch(`/api/news/events/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson(res);
}

export async function fetchNewsOutlook(id: number): Promise<NewsEvent> {
  const res = await fetch(`/api/news/events/${id}/outlook`, { method: "POST" });
  return parseJson(res);
}

export async function fetchTickerNewsImpact(ticker: string, limit = 50): Promise<{
  ticker: string;
  company_name: string | null;
  total: number;
  events: NewsEvent[];
  aggregates: NewsImpactAggregates;
  markers: Array<{
    event_id: number;
    date: string;
    sentiment: string | null;
    summary: string | null;
    t1: number | null;
    t3: number | null;
  }>;
}> {
  const search = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`/api/news/ticker/${encodeURIComponent(ticker)}/impact?${search}`);
  return parseJson(res);
}

export async function classifyNewsSentimentApi(text: string): Promise<{
  sentiment: string;
  confidence: number;
  source?: string;
}> {
  const res = await fetch("/api/news/classify-sentiment", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return parseJson(res);
}

/* ── Multi-year breakout / ATH pullback screener ─────────────────────── */

export type MybStrategy = "multi_year_breakout" | "ath_pullback" | "custom";
export type MybStatus = "breakout" | "near" | "pullback";
export type MybSizeTier = "all" | "large" | "mid" | "small";
export type MybMatchMode = "at_least" | "at_most" | "band";
export type MybTrendFilter = "all" | "uptrend" | "downtrend";
export type MybMaType = "sma" | "ema";

export interface MybSignal {
  id: number;
  run_id: number;
  trade_date: string;
  ticker: string;
  sector?: string | null;
  company_name?: string | null;
  strategy?: MybStrategy | string;
  status: MybStatus;
  lookback_years: number;
  prior_high: number;
  prior_high_date?: string | null;
  years_since_high?: number | null;
  close_price: number;
  breakout_pct?: number | null;
  drop_from_ath_pct?: number | null;
  rvol20?: number | null;
  rsi14?: number | null;
  avg_turnover_inr?: number | null;
  score: number;
  details?: Record<string, unknown>;
}

export interface MybScanStatus {
  running: boolean;
  trade_date?: string | null;
  strategy?: string | null;
  lookback_years?: number | null;
  processed: number;
  total: number;
  alerts_count: number;
  current_ticker?: string | null;
  last_result: Record<string, unknown> | null;
}

export async function fetchMybDates(strategy?: MybStrategy): Promise<{
  dates: string[];
  count: number;
  latest_data_date: string | null;
}> {
  const search = new URLSearchParams({ limit: "365" });
  if (strategy) search.set("strategy", strategy);
  const res = await fetch(`/api/multi-year-breakout/dates?${search}`);
  return parseJson(res);
}

export async function fetchMybStatus(): Promise<MybScanStatus> {
  const res = await fetch("/api/multi-year-breakout/status");
  return parseJson(res);
}

export async function runMybScan(body: {
  tradeDate?: string;
  strategy?: MybStrategy;
  lookbackYears?: number;
  pullbackPct?: number;
  matchMode?: MybMatchMode;
  bandWidthPct?: number;
  trendFilter?: MybTrendFilter;
  shortMaPeriod?: number;
  longMaPeriod?: number;
  maType?: MybMaType;
  includeMultiYear?: boolean;
  includeAthPullback?: boolean;
  sector?: string;
  sizeTier?: MybSizeTier;
  minPrice?: number;
  maxPrice?: number;
  minRvol?: number;
  concurrency?: number;
  backgroundRun?: boolean;
}): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  if (body.backgroundRun !== undefined) {
    params.set("background_run", String(body.backgroundRun));
  }
  const res = await fetch(`/api/multi-year-breakout/run?${params}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trade_date: body.tradeDate ?? null,
      strategy: body.strategy ?? "multi_year_breakout",
      lookback_years: body.lookbackYears ?? 3,
      pullback_pct: body.pullbackPct ?? 15,
      match_mode: body.matchMode ?? "at_least",
      band_width_pct: body.bandWidthPct ?? 5,
      trend_filter: body.trendFilter ?? "all",
      short_ma_period: body.shortMaPeriod ?? 50,
      long_ma_period: body.longMaPeriod ?? 200,
      ma_type: body.maType ?? "sma",
      include_multi_year: body.includeMultiYear ?? true,
      include_ath_pullback: body.includeAthPullback ?? true,
      sector: body.sector ?? null,
      size_tier: body.sizeTier ?? "all",
      min_price: body.minPrice ?? null,
      max_price: body.maxPrice ?? null,
      min_rvol: body.minRvol ?? null,
      concurrency: body.concurrency ?? 4,
    }),
  });
  return parseJson(res);
}

export async function fetchMybResults(params: {
  tradeDate: string;
  strategy?: MybStrategy;
  lookbackYears?: number;
  status?: MybStatus | "all";
  minScore?: number;
  sector?: string;
  sizeTier?: MybSizeTier;
  trend?: MybTrendFilter;
  minPrice?: number;
  maxPrice?: number;
  minRvol?: number;
  limit?: number;
  offset?: number;
}): Promise<{
  trade_date: string;
  strategy?: string;
  lookback_years?: number;
  params?: Record<string, unknown>;
  total: number;
  count: number;
  scan_alerts_count?: number | null;
  results: MybSignal[];
}> {
  const search = new URLSearchParams({ trade_date: params.tradeDate });
  if (params.strategy) search.set("strategy", params.strategy);
  if (params.lookbackYears != null) search.set("lookback_years", String(params.lookbackYears));
  if (params.status && params.status !== "all") search.set("status", params.status);
  if (params.minScore != null && params.minScore > 0) {
    search.set("min_score", String(params.minScore));
  }
  if (params.sector) search.set("sector", params.sector);
  if (params.sizeTier && params.sizeTier !== "all") search.set("size_tier", params.sizeTier);
  if (params.trend && params.trend !== "all") search.set("trend", params.trend);
  if (params.minPrice != null) search.set("min_price", String(params.minPrice));
  if (params.maxPrice != null) search.set("max_price", String(params.maxPrice));
  if (params.minRvol != null) search.set("min_rvol", String(params.minRvol));
  search.set("limit", String(params.limit ?? 100));
  search.set("offset", String(params.offset ?? 0));
  const res = await fetch(`/api/multi-year-breakout/results?${search}`);
  return parseJson(res);
}

// --- Multi-timeframe RSI (Nifty 50 live) ------------------------------------

export interface MtfRsiMarketInfo {
  is_open: boolean;
  reason: string;
  label: string;
  now_ist: string;
  session_open: string;
  session_close: string;
  timezone: string;
}

export interface MtfRsiFrame {
  rsi: number | null;
  status: "Overbought" | "Oversold" | "Neutral" | "Warming" | string;
  buffer: number;
  active_close?: number | null;
  active_open_ts?: string | null;
}

export interface MtfRsiSnapshot {
  ltp: number | null;
  ts: string | null;
  seed_ts?: string | null;
  rsi_period: number;
  timeframes: Record<string, MtfRsiFrame>;
  feed_status?: string;
  seeded?: boolean;
  instrument_key?: string;
  instrument_label?: string;
  market?: MtfRsiMarketInfo;
  mode_note?: string;
  live_ticks?: boolean;
}

export interface MtfRsiStatus {
  status: string;
  seeded: boolean;
  instrument_key: string;
  instrument_label: string;
  rsi_period: number;
  timeframes: number[];
  error?: string | null;
  reconnect_attempts?: number;
  snapshot?: MtfRsiSnapshot | null;
  market?: MtfRsiMarketInfo;
  mode_note?: string;
}

export async function fetchMtfRsiStatus(): Promise<MtfRsiStatus> {
  const res = await fetch("/api/mtf-rsi/status");
  return parseJson(res);
}

export async function fetchMtfRsiSnapshot(): Promise<MtfRsiSnapshot> {
  const res = await fetch("/api/mtf-rsi/snapshot");
  return parseJson(res);
}

export async function startMtfRsiStream(params?: {
  rsiPeriod?: number;
  forceRefresh?: boolean;
}): Promise<MtfRsiStatus> {
  const res = await fetch("/api/mtf-rsi/stream/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      rsi_period: params?.rsiPeriod ?? 14,
      force_refresh: params?.forceRefresh ?? false,
    }),
  });
  return parseJson(res);
}

export async function stopMtfRsiStream(): Promise<MtfRsiStatus> {
  const res = await fetch("/api/mtf-rsi/stream/stop", {
    method: "POST",
    headers: authHeaders(),
  });
  return parseJson(res);
}

export async function setMtfRsiPeriod(rsiPeriod: number): Promise<MtfRsiSnapshot> {
  const res = await fetch("/api/mtf-rsi/rsi-period", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ rsi_period: rsiPeriod }),
  });
  return parseJson(res);
}

export interface MtfRsiChartPoint {
  t: number;
  v: number;
}

export interface MtfRsiChartPayload {
  rsi_period: number;
  series: Record<string, MtfRsiChartPoint[]>;
  ltp?: number | null;
  ts?: string | null;
  market?: MtfRsiMarketInfo;
  mode_note?: string;
  seeded?: boolean;
  feed_status?: string;
  instrument_label?: string;
}

export async function fetchMtfRsiChart(timeframe?: number): Promise<MtfRsiChartPayload> {
  const search = timeframe != null ? `?timeframe=${timeframe}` : "";
  const res = await fetch(`/api/mtf-rsi/chart${search}`);
  return parseJson(res);
}

export async function seedMtfRsi(params?: {
  rsiPeriod?: number;
  forceRefresh?: boolean;
}): Promise<MtfRsiStatus> {
  const res = await fetch("/api/mtf-rsi/seed", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      rsi_period: params?.rsiPeriod ?? 14,
      force_refresh: params?.forceRefresh ?? false,
    }),
  });
  return parseJson(res);
}
