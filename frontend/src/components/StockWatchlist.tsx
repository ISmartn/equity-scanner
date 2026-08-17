import { Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { searchSymbols, type SymbolSearchResult } from "@/lib/api";
import {
  addWatchlistStock,
  getWatchlist,
  removeWatchlistStock,
  type WatchlistStock,
} from "@/lib/storage";

interface StockWatchlistProps {
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
}

export function StockWatchlist({ selectedSymbol, onSelect }: StockWatchlistProps) {
  const [watchlist, setWatchlist] = useState<WatchlistStock[]>(() => getWatchlist());
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const trimmedQuery = query.trim();

  useEffect(() => {
    if (trimmedQuery.length < 1) {
      setResults([]);
      setSearchError(null);
      return;
    }

    const timer = window.setTimeout(async () => {
      setSearching(true);
      setSearchError(null);
      try {
        const res = await searchSymbols(trimmedQuery, 12);
        setResults(res.results);
      } catch (err) {
        setResults([]);
        setSearchError(err instanceof Error ? err.message : "Search failed");
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => window.clearTimeout(timer);
  }, [trimmedQuery]);

  const watchlistSymbols = useMemo(() => new Set(watchlist.map((s) => s.symbol)), [watchlist]);

  const handleAdd = (result: SymbolSearchResult) => {
    const next = addWatchlistStock({
      symbol: result.symbol,
      name: result.name,
      instrumentKey: result.instrument_key,
    });
    setWatchlist(next);
    onSelect(result.symbol);
    setQuery("");
    setResults([]);
  };

  const handleRemove = (symbol: string) => {
    const next = removeWatchlistStock(symbol);
    setWatchlist(next);
  };

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          My stock list
        </h3>
        <span className="text-xs text-slate-500">{watchlist.length} saved</span>
      </div>

      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        Search any NSE equity and add it to your list for quick access on this page.
      </p>

      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search company or symbol..."
          className="w-full rounded-lg border border-surface-border bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-accent/30 focus:ring-2"
        />
      </div>

      {searching && trimmedQuery && (
        <p className="mb-2 text-xs text-slate-500">Searching...</p>
      )}
      {searchError && (
        <p className="mb-2 text-xs text-amber-400">{searchError}</p>
      )}

      {trimmedQuery && !searching && results.length > 0 && (
        <div className="mb-3 max-h-40 space-y-1 overflow-y-auto rounded-lg border border-surface-border bg-surface p-1">
          {results.map((result) => {
            const alreadyAdded = watchlistSymbols.has(result.symbol);
            return (
              <div
                key={result.symbol}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-raised"
              >
                <button
                  type="button"
                  onClick={() => onSelect(result.symbol)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="text-sm font-medium text-slate-200">{result.symbol}</div>
                  <div className="truncate text-xs text-slate-500">{result.name}</div>
                </button>
                <button
                  type="button"
                  disabled={alreadyAdded}
                  onClick={() => handleAdd(result)}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-xs text-slate-300 transition hover:border-accent/40 hover:text-white disabled:opacity-40"
                >
                  <Plus className="h-3 w-3" />
                  {alreadyAdded ? "Added" : "Add"}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {trimmedQuery && !searching && !searchError && results.length === 0 && (
        <p className="mb-3 text-xs text-slate-500">No matches for &quot;{trimmedQuery}&quot;</p>
      )}

      <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
        {watchlist.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-slate-500">
            No stocks saved yet. Search above to add one.
          </p>
        )}
        {watchlist.map((stock) => (
          <div
            key={stock.symbol}
            className={`flex items-center gap-2 rounded-lg px-2 py-2 transition ${
              selectedSymbol === stock.symbol
                ? "bg-accent/20"
                : "hover:bg-surface"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(stock.symbol)}
              className="min-w-0 flex-1 text-left"
            >
              <div
                className={`text-sm ${
                  selectedSymbol === stock.symbol
                    ? "font-medium text-accent"
                    : "text-slate-300"
                }`}
              >
                {stock.symbol}
              </div>
              <div className="truncate text-xs text-slate-500">{stock.name}</div>
            </button>
            <button
              type="button"
              onClick={() => handleRemove(stock.symbol)}
              className="rounded-md p-1 text-slate-500 transition hover:bg-red-500/10 hover:text-red-400"
              aria-label={`Remove ${stock.symbol}`}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
