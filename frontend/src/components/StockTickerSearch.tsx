import { searchSymbols, type SymbolSearchResult } from "@/lib/api";
import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface StockTickerSearchProps {
  value: string;
  onChange: (ticker: string) => void;
  disabled?: boolean;
  compact?: boolean;
  placeholder?: string;
}

export function StockTickerSearch({
  value,
  onChange,
  disabled = false,
  compact = false,
  placeholder = "Search ticker…",
}: StockTickerSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const trimmedQuery = query.trim();

  useEffect(() => {
    if (!open || trimmedQuery.length < 1) {
      setResults([]);
      return;
    }

    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const res = await searchSymbols(trimmedQuery, 10);
        setResults(res.results);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);

    return () => window.clearTimeout(timer);
  }, [trimmedQuery, open]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = (symbol: string) => {
    onChange(symbol);
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  const handleClear = () => {
    onChange("");
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  const inputClass = compact
    ? "w-36 rounded-md border border-surface-border bg-surface py-1.5 pl-7 pr-7 text-xs outline-none ring-accent/30 focus:ring-2"
    : "w-full rounded-lg border border-surface-border bg-surface py-2 pl-9 pr-9 text-sm outline-none ring-accent/30 focus:ring-2";

  if (value) {
    return (
      <div className="flex items-center gap-1">
        <span
          className={`inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent/10 font-medium text-accent ${
            compact ? "px-2 py-1.5 text-xs" : "px-2.5 py-2 text-sm"
          }`}
        >
          {value}
          <button
            type="button"
            onClick={handleClear}
            disabled={disabled}
            className="rounded p-0.5 transition hover:bg-accent/20 disabled:opacity-50"
            aria-label="Clear stock search"
          >
            <X className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
          </button>
        </span>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <Search
        className={`pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-500 ${
          compact ? "h-3 w-3" : "h-4 w-4"
        }`}
      />
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && trimmedQuery) {
            handleSelect(trimmedQuery.toUpperCase());
          }
          if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        disabled={disabled}
        placeholder={placeholder}
        className={inputClass}
      />
      {open && trimmedQuery && (
        <div className="absolute left-0 top-full z-20 mt-1 min-w-[220px] overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-lg">
          {searching ? (
            <p className="px-3 py-2 text-xs text-slate-500">Searching…</p>
          ) : results.length > 0 ? (
            <ul className="max-h-48 overflow-y-auto py-1">
              {results.map((result) => (
                <li key={result.symbol}>
                  <button
                    type="button"
                    onClick={() => handleSelect(result.symbol)}
                    className="flex w-full flex-col px-3 py-1.5 text-left hover:bg-surface"
                  >
                    <span className="text-xs font-medium text-slate-200">{result.symbol}</span>
                    <span className="truncate text-[10px] text-slate-500">{result.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <button
              type="button"
              onClick={() => handleSelect(trimmedQuery.toUpperCase())}
              className="w-full px-3 py-2 text-left text-xs text-slate-300 hover:bg-surface"
            >
              Look up <span className="font-medium text-slate-100">{trimmedQuery.toUpperCase()}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
