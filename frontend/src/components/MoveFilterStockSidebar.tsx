import { Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { searchSymbols, type SymbolSearchResult } from "@/lib/api";
import {
  addWatchlistStock,
  getWatchlist,
  removeWatchlistStock,
  type WatchlistStock,
} from "@/lib/storage";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

type StockTab = "nifty" | "fno" | "watchlist" | "search";
const MOVE_SIDEBAR_PREFS = "trading.moveFilter.sidebar";
const SIDEBAR_TABS: StockTab[] = ["nifty", "fno", "watchlist", "search"];

interface MoveFilterStockSidebarProps {
  symbol: string;
  onSymbolChange: (symbol: string) => void;
  niftySymbols: string[];
  fnoSymbols: string[];
  loadingSymbols?: boolean;
  loadingFno?: boolean;
}

export function MoveFilterStockSidebar({
  symbol,
  onSymbolChange,
  niftySymbols,
  fnoSymbols,
  loadingSymbols = false,
  loadingFno = false,
}: MoveFilterStockSidebarProps) {
  const initialTab = loadUiPrefs(MOVE_SIDEBAR_PREFS, { tab: "nifty" as StockTab }).tab;
  const [tab, setTab] = useState<StockTab>(SIDEBAR_TABS.includes(initialTab) ? initialTab : "nifty");
  const [query, setQuery] = useState("");
  const [watchlist, setWatchlist] = useState<WatchlistStock[]>(() => getWatchlist());
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const listSymbols = useMemo(() => {
    const q = query.trim().toUpperCase();
    const source =
      tab === "nifty" ? niftySymbols : tab === "fno" ? fnoSymbols : watchlist.map((w) => w.symbol);
    if (!q || tab === "search" || tab === "watchlist") return source;
    return source.filter((s) => s.includes(q));
  }, [tab, query, niftySymbols, fnoSymbols, watchlist]);

  useEffect(() => {
    saveUiPrefs(MOVE_SIDEBAR_PREFS, { tab });
  }, [tab]);

  useEffect(() => {
    if (tab !== "search") return;
    const trimmed = query.trim();
    if (trimmed.length < 1) {
      setSearchResults([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const res = await searchSymbols(trimmed, 20);
        setSearchResults(res.results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, tab]);

  const watchlistFiltered = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return watchlist;
    return watchlist.filter(
      (w) => w.symbol.includes(q) || (w.name || "").toUpperCase().includes(q),
    );
  }, [watchlist, query]);

  const addToWatchlist = (result: SymbolSearchResult) => {
    setWatchlist(
      addWatchlistStock({
        symbol: result.symbol,
        name: result.name,
        instrumentKey: result.instrument_key,
      }),
    );
    onSymbolChange(result.symbol);
  };

  const countLabel =
    tab === "nifty"
      ? niftySymbols.length
      : tab === "fno"
        ? fnoSymbols.length
        : tab === "watchlist"
          ? watchlist.length
          : searchResults.length;

  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised lg:w-[15.5rem] xl:w-[17rem]">
      <div className="shrink-0 border-b border-surface-border px-2.5 py-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Stocks
          </h2>
          <span className="text-[10px] tabular-nums text-slate-500">{countLabel}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {(
            [
              ["nifty", "Nifty"],
              ["fno", "F&O"],
              ["watchlist", "List"],
              ["search", "Search"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => {
                setTab(id);
                setQuery("");
              }}
              className={`rounded-md px-2 py-0.5 text-[10px] transition ${
                tab === id
                  ? "bg-accent/20 font-medium text-accent"
                  : "text-slate-500 hover:bg-surface hover:text-slate-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="relative mt-1.5">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={tab === "search" ? "Search NSE…" : "Filter…"}
            className="w-full rounded-md border border-surface-border bg-surface py-1.5 pl-7 pr-2 text-xs outline-none ring-accent/30 focus:ring-2"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {(tab === "nifty" && loadingSymbols) || (tab === "fno" && loadingFno) ? (
          <p className="px-2 py-8 text-center text-xs text-slate-500">Loading…</p>
        ) : tab === "search" ? (
          <>
            {searching && <p className="px-2 py-3 text-xs text-slate-500">Searching…</p>}
            {!searching && query.trim() && searchResults.length === 0 && (
              <p className="px-2 py-3 text-xs text-slate-500">No matches</p>
            )}
            {!query.trim() && (
              <p className="px-2 py-6 text-center text-xs text-slate-500">
                Type to search any NSE equity
              </p>
            )}
            {searchResults.map((result) => (
              <div
                key={result.symbol}
                className={`flex items-center gap-1 rounded-md px-2 py-1.5 ${
                  symbol === result.symbol ? "bg-accent/15" : "hover:bg-surface"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSymbolChange(result.symbol)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="truncate text-xs font-medium text-slate-200">{result.name}</div>
                  <div className="font-mono text-[10px] text-slate-500">{result.symbol}</div>
                </button>
                <button
                  type="button"
                  onClick={() => addToWatchlist(result)}
                  className="shrink-0 rounded border border-surface-border p-1 text-slate-400 hover:border-accent/40 hover:text-slate-200"
                  title="Add to watchlist"
                >
                  <Plus className="h-3 w-3" />
                </button>
              </div>
            ))}
          </>
        ) : tab === "watchlist" ? (
          <>
            {watchlistFiltered.length === 0 && (
              <p className="px-2 py-6 text-center text-xs text-slate-500">
                No saved stocks. Use Search to add.
              </p>
            )}
            {watchlistFiltered.map((stock) => (
              <div
                key={stock.symbol}
                className={`flex items-center gap-1 rounded-md px-2 py-1.5 ${
                  symbol === stock.symbol ? "bg-accent/15" : "hover:bg-surface"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSymbolChange(stock.symbol)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div
                    className={`truncate text-xs ${
                      symbol === stock.symbol ? "font-medium text-accent" : "text-slate-200"
                    }`}
                  >
                    {stock.name || stock.symbol}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500">{stock.symbol}</div>
                </button>
                <button
                  type="button"
                  onClick={() => setWatchlist(removeWatchlistStock(stock.symbol))}
                  className="rounded p-1 text-slate-500 hover:bg-red-500/10 hover:text-red-400"
                  aria-label={`Remove ${stock.symbol}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </>
        ) : listSymbols.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-slate-500">No matches</p>
        ) : (
          listSymbols.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onSymbolChange(s)}
              className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition ${
                symbol === s
                  ? "bg-accent/20 font-medium text-accent"
                  : "text-slate-300 hover:bg-surface"
              }`}
            >
              {s}
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
