import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import {
  fetchIndicatorAnalysis,
  searchSymbols,
  type IndicatorAnalysisPayload,
  type IndicatorReading,
  type SymbolSearchResult,
} from "@/lib/api";

const NIFTY_TFS = ["daily", "10m", "5m", "3m", "1m"] as const;

function biasClass(bias: string): string {
  switch (bias) {
    case "bullish":
    case "lean_bullish":
    case "oversold":
    case "neutral_bull":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "bearish":
    case "lean_bearish":
    case "overbought":
    case "neutral_bear":
      return "border-rose-500/40 bg-rose-500/10 text-rose-300";
    case "compressing":
    case "expanding":
    case "warming":
      return "border-amber-500/40 bg-amber-500/10 text-amber-300";
    case "manual":
    case "unavailable":
      return "border-slate-600/50 bg-slate-800/40 text-slate-400";
    default:
      return "border-surface-border bg-surface text-slate-300";
  }
}

function overallLabel(bias: string): string {
  return bias.replace(/_/g, " ");
}

function formatNum(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function MetricChips({ metrics }: { metrics: IndicatorReading["metrics"] }) {
  const entries = Object.entries(metrics || {}).filter(([, v]) => {
    if (v == null) return false;
    if (typeof v === "object") return false;
    return true;
  });
  if (!entries.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {entries.slice(0, 6).map(([k, v]) => (
        <span
          key={k}
          className="rounded border border-surface-border bg-surface-elevated/40 px-1.5 py-0.5 text-[10px] text-slate-400"
        >
          {k.replace(/_/g, " ")}:{" "}
          <span className="text-slate-200">
            {typeof v === "number" ? formatNum(v, Math.abs(v) >= 100 ? 1 : 2) : String(v)}
          </span>
        </span>
      ))}
    </div>
  );
}

export function IndicatorAnalysisPage() {
  const [symbolInput, setSymbolInput] = useState("NIFTY");
  const [symbol, setSymbol] = useState("NIFTY");
  const [timeframe, setTimeframe] = useState<string>("daily");
  const [rsiPeriod, setRsiPeriod] = useState(14);
  const [filter, setFilter] = useState<"all" | "computable" | "manual">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<IndicatorAnalysisPayload | null>(null);
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([]);

  const isNifty = symbol.toUpperCase() === "NIFTY" || symbol.toUpperCase() === "NIFTY50";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchIndicatorAnalysis({
        symbol,
        timeframe: isNifty ? timeframe : "daily",
        limit: 400,
        rsiPeriod,
      });
      setData(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe, rsiPeriod, isNifty]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const q = symbolInput.trim();
    if (q.length < 2 || q.toUpperCase() === "NIFTY") {
      setSuggestions([]);
      return;
    }
    const t = window.setTimeout(() => {
      void searchSymbols(q, 8)
        .then((res) => setSuggestions(res.results))
        .catch(() => setSuggestions([]));
    }, 250);
    return () => window.clearTimeout(t);
  }, [symbolInput]);

  const applySymbol = (raw: string) => {
    const next = raw.trim().toUpperCase() || "NIFTY";
    setSymbolInput(next);
    setSymbol(next);
    setSuggestions([]);
  };

  const indicators = useMemo(() => {
    const list = data?.indicators ?? [];
    if (filter === "computable") return list.filter((i) => i.computable);
    if (filter === "manual") return list.filter((i) => !i.computable);
    return list;
  }, [data, filter]);

  const bullishCount = useMemo(
    () =>
      (data?.indicators ?? []).filter((i) =>
        ["bullish", "lean_bullish", "neutral_bull", "oversold"].includes(i.bias),
      ).length,
    [data],
  );
  const bearishCount = useMemo(
    () =>
      (data?.indicators ?? []).filter((i) =>
        ["bearish", "lean_bearish", "neutral_bear", "overbought"].includes(i.bias),
      ).length,
    [data],
  );

  return (
    <main className="mx-auto max-w-6xl space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Indicator Analysis</h1>
          <p className="max-w-2xl text-xs text-slate-500">
            Live readings for the toolkit ranked from @kyalashish tweets (Elliott, Time Cycle, Bollinger,
            Keltner, KST, Supertrend, Volume Profile, RSI, …). Computable indicators run on Nifty /
            stock OHLC; discretionary ones stay as reference.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div className="relative">
            <label className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">Symbol</label>
            <div className="flex items-center gap-1">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
                <input
                  value={symbolInput}
                  onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") applySymbol(symbolInput);
                  }}
                  placeholder="NIFTY or RELIANCE"
                  className="w-40 rounded-md border border-surface-border bg-surface py-1.5 pl-7 pr-2 text-xs text-slate-200"
                />
                {suggestions.length > 0 && (
                  <div className="absolute z-20 mt-1 max-h-48 w-56 overflow-auto rounded-md border border-surface-border bg-surface shadow-lg">
                    <button
                      type="button"
                      className="block w-full px-2 py-1.5 text-left text-xs text-accent hover:bg-accent/10"
                      onClick={() => applySymbol("NIFTY")}
                    >
                      NIFTY (index)
                    </button>
                    {suggestions.map((s) => (
                      <button
                        key={s.instrument_key}
                        type="button"
                        className="block w-full px-2 py-1.5 text-left text-xs text-slate-300 hover:bg-white/5"
                        onClick={() => applySymbol(s.symbol)}
                      >
                        <span className="font-medium text-slate-100">{s.symbol}</span>
                        <span className="ml-1 text-slate-500">{s.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => applySymbol(symbolInput)}
                className="rounded-md border border-surface-border px-2 py-1.5 text-xs text-slate-300 hover:border-accent/40"
              >
                Go
              </button>
            </div>
          </div>

          {isNifty && (
            <div>
              <label className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">TF</label>
              <div className="flex rounded-md border border-surface-border bg-surface p-0.5">
                {NIFTY_TFS.map((tf) => (
                  <button
                    key={tf}
                    type="button"
                    onClick={() => setTimeframe(tf)}
                    className={`rounded px-2 py-1 text-xs ${
                      timeframe === tf ? "bg-accent/15 text-accent" : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">RSI period</label>
            <input
              type="number"
              min={2}
              max={100}
              value={rsiPeriod}
              onChange={(e) => setRsiPeriod(Number(e.target.value) || 14)}
              className="w-16 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
            />
          </div>

          <button
            type="button"
            disabled={loading}
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {data && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Stat label="Instrument" value={data.label} sub={data.symbol} />
          <Stat
            label="Last close"
            value={formatNum(data.last_bar.close)}
            sub={data.last_bar.ts ? String(data.last_bar.ts).slice(0, 16) : undefined}
          />
          <Stat label="Bars" value={String(data.bar_count)} sub={`${data.timeframe} · ${data.source}`} />
          <Stat
            label="Overall"
            value={overallLabel(data.overall_bias)}
            valueClass={biasClass(data.overall_bias).split(" ").filter((c) => c.startsWith("text-")).join(" ")}
            sub={`score ${data.bias_score > 0 ? "+" : ""}${data.bias_score}`}
          />
          <Stat label="Bull vs Bear" value={`${bullishCount} / ${bearishCount}`} sub="computable leans" />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Show</span>
        {(
          [
            ["all", "All"],
            ["computable", "Live readings"],
            ["manual", "Manual / reference"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={`rounded-md border px-2.5 py-1 text-xs ${
              filter === key
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-surface-border text-slate-400 hover:text-slate-200"
            }`}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-slate-600">
          Ranked by tweet mention frequency · catalog from kyalashish_own_400
        </span>
      </div>

      {loading && !data ? (
        <div className="flex h-48 items-center justify-center rounded-lg border border-surface-border bg-surface text-sm text-slate-500">
          Computing indicators…
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {indicators.map((ind) => (
            <article
              key={ind.id}
              className="rounded-lg border border-surface-border bg-surface p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium text-slate-500">#{ind.rank}</span>
                    <h2 className="text-sm font-medium text-slate-100">{ind.name}</h2>
                  </div>
                  <p className="mt-0.5 text-[10px] text-slate-500">
                    {ind.tweet_count} tweet mentions
                    {!ind.computable ? " · reference only" : ""}
                  </p>
                </div>
                <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] capitalize ${biasClass(ind.bias)}`}>
                  {ind.bias.replace(/_/g, " ")}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-slate-300">{ind.detail}</p>
              <MetricChips metrics={ind.metrics} />
            </article>
          ))}
        </div>
      )}
    </main>
  );
}

function Stat({
  label,
  value,
  valueClass,
  sub,
}: {
  label: string;
  value: string;
  valueClass?: string;
  sub?: string;
}) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-0.5 text-sm font-medium capitalize ${valueClass ?? "text-slate-100"}`}>{value}</div>
      {sub ? <div className="truncate text-[10px] text-slate-500">{sub}</div> : null}
    </div>
  );
}
