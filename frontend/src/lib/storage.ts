const STORAGE_KEY = "timesfm_upstox_token";

export function getUpstoxToken(): string {
  return localStorage.getItem(STORAGE_KEY) || "";
}

export function setUpstoxToken(token: string): void {
  if (token.trim()) {
    localStorage.setItem(STORAGE_KEY, token.trim());
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

const WATCHLIST_KEY = "timesfm_move_filter_watchlist";
const MOVE_FILTER_SETTINGS_KEY = "timesfm_move_filter_settings";
const FORECAST_SETTINGS_KEY = "timesfm_forecast_settings";

export interface WatchlistStock {
  symbol: string;
  name: string;
  instrumentKey?: string;
}

export function getWatchlist(): WatchlistStock[] {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WatchlistStock[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function setWatchlist(stocks: WatchlistStock[]): void {
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(stocks));
}

export function addWatchlistStock(stock: WatchlistStock): WatchlistStock[] {
  const normalized = stock.symbol.trim().toUpperCase();
  const existing = getWatchlist();
  if (existing.some((s) => s.symbol === normalized)) {
    return existing;
  }
  const next = [...existing, { ...stock, symbol: normalized }];
  setWatchlist(next);
  return next;
}

export function removeWatchlistStock(symbol: string): WatchlistStock[] {
  const normalized = symbol.trim().toUpperCase();
  const next = getWatchlist().filter((s) => s.symbol !== normalized);
  setWatchlist(next);
  return next;
}

export interface MoveFilterSettings {
  symbol: string;
  positiveEnabled: boolean;
  negativeEnabled: boolean;
  positiveInput: string;
  negativeInput: string;
  threeGreenEnabled: boolean;
  darvasEnabled: boolean;
  darvasLookbackInput: string;
}

export const DEFAULT_MOVE_FILTER_SETTINGS: MoveFilterSettings = {
  symbol: "RELIANCE",
  positiveEnabled: true,
  negativeEnabled: true,
  positiveInput: "2",
  negativeInput: "2",
  threeGreenEnabled: false,
  darvasEnabled: true,
  darvasLookbackInput: "30",
};

export function getMoveFilterSettings(): MoveFilterSettings {
  try {
    const raw = localStorage.getItem(MOVE_FILTER_SETTINGS_KEY);
    if (!raw) return DEFAULT_MOVE_FILTER_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<MoveFilterSettings>;
    return {
      ...DEFAULT_MOVE_FILTER_SETTINGS,
      ...parsed,
      symbol: (parsed.symbol ?? DEFAULT_MOVE_FILTER_SETTINGS.symbol).trim().toUpperCase(),
    };
  } catch {
    return DEFAULT_MOVE_FILTER_SETTINGS;
  }
}

export function setMoveFilterSettings(settings: MoveFilterSettings): void {
  localStorage.setItem(MOVE_FILTER_SETTINGS_KEY, JSON.stringify(settings));
}

export type ForecastInterval = "daily" | "weekly" | "monthly";

export interface ForecastSettings {
  symbol: string;
  interval: ForecastInterval;
  model: string;
}

export const DEFAULT_FORECAST_SETTINGS: ForecastSettings = {
  symbol: "RELIANCE",
  interval: "daily",
  model: "timesfm-2.5",
};

export function getForecastSettings(): ForecastSettings {
  try {
    const raw = localStorage.getItem(FORECAST_SETTINGS_KEY);
    if (!raw) return DEFAULT_FORECAST_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<ForecastSettings>;
    return {
      ...DEFAULT_FORECAST_SETTINGS,
      ...parsed,
      symbol: (parsed.symbol ?? DEFAULT_FORECAST_SETTINGS.symbol).trim().toUpperCase(),
    };
  } catch {
    return DEFAULT_FORECAST_SETTINGS;
  }
}

export function setForecastSettings(settings: ForecastSettings): void {
  localStorage.setItem(FORECAST_SETTINGS_KEY, JSON.stringify(settings));
}
