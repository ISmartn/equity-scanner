import { Search } from "lucide-react";
import { useMemo, useState } from "react";

interface StockSelectorProps {
  title?: string;
  symbols: string[];
  value: string;
  onChange: (symbol: string) => void;
  loading?: boolean;
}

export function StockSelector({
  title = "Nifty 50",
  symbols,
  value,
  onChange,
  loading,
}: StockSelectorProps) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return symbols;
    return symbols.filter((s) => s.includes(q));
  }, [query, symbols]);

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          {title}
        </h3>
        <span className="text-xs text-slate-500">{symbols.length} stocks</span>
      </div>

      <div className="relative mb-3">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search symbol..."
          className="w-full rounded-lg border border-surface-border bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-accent/30 focus:ring-2"
        />
      </div>

      <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
        {loading && (
          <p className="px-2 py-6 text-center text-sm text-slate-500">Loading symbols...</p>
        )}
        {!loading &&
          filtered.map((symbol) => (
            <button
              key={symbol}
              type="button"
              onClick={() => onChange(symbol)}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                value === symbol
                  ? "bg-accent/20 font-medium text-accent"
                  : "text-slate-300 hover:bg-surface"
              }`}
            >
              {symbol}
            </button>
          ))}
      </div>
    </div>
  );
}
