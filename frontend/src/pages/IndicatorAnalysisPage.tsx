import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import {
  fetchIndicatorAnalysis,
  searchSymbols,
  type IndicatorAnalysisPayload,
  type IndicatorReading,
  type SymbolSearchResult,
} from "@/lib/api";
import {
  ActiveFilterChips,
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  Clip,
  PageToolbar,
  StatChip,
  ToolbarDivider,
  type ActiveFilterChip,
} from "@/components/dense";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

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
    <div className="mt-1 flex flex-wrap gap-1">
      {entries.slice(0, 6).map(([k, v]) => (
        <span
          key={k}
          className="rounded border border-surface-border bg-surface-elevated/40 px-1 text-data-xs text-slate-400"
        >
          {k.replace(/_/g, " ")}:{" "}
          <span className="num text-slate-200">
            {typeof v === "number" ? formatNum(v, Math.abs(v) >= 100 ? 1 : 2) : String(v)}
          </span>
        </span>
      ))}
    </div>
  );
}

const IA_PREFS_KEY = "trading.indicatorAnalysis.prefs";
type IaUiPrefs = {
  symbol: string;
  timeframe: string;
  rsiPeriod: number;
  filter: "all" | "computable" | "manual";
};
const DEFAULT_IA_PREFS: IaUiPrefs = {
  symbol: "NIFTY",
  timeframe: "daily",
  rsiPeriod: 14,
  filter: "all",
};

export function IndicatorAnalysisPage() {
  const initialPrefs = loadUiPrefs(IA_PREFS_KEY, DEFAULT_IA_PREFS);
  const [symbolInput, setSymbolInput] = useState(initialPrefs.symbol || "NIFTY");
  const [symbol, setSymbol] = useState((initialPrefs.symbol || "NIFTY").toUpperCase());
  const [timeframe, setTimeframe] = useState<string>(initialPrefs.timeframe || "daily");
  const [rsiPeriod, setRsiPeriod] = useState(Number(initialPrefs.rsiPeriod) || 14);
  const [filter, setFilter] = useState<"all" | "computable" | "manual">(
    initialPrefs.filter === "computable" || initialPrefs.filter === "manual" ? initialPrefs.filter : "all",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<IndicatorAnalysisPayload | null>(null);
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);

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
    saveUiPrefs(IA_PREFS_KEY, { symbol, timeframe, rsiPeriod, filter } satisfies IaUiPrefs);
  }, [symbol, timeframe, rsiPeriod, filter]);

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

  const advancedChips = useMemo(() => {
    const chips: ActiveFilterChip[] = [];
    if (isNifty && timeframe !== DEFAULT_IA_PREFS.timeframe) {
      chips.push({
        key: "tf",
        label: `TF ${timeframe}`,
        onRemove: () => setTimeframe(DEFAULT_IA_PREFS.timeframe),
      });
    }
    if (rsiPeriod !== DEFAULT_IA_PREFS.rsiPeriod) {
      chips.push({
        key: "rsi",
        label: `RSI ${rsiPeriod}`,
        onRemove: () => setRsiPeriod(DEFAULT_IA_PREFS.rsiPeriod),
      });
    }
    return chips;
  }, [isNifty, timeframe, rsiPeriod]);

  const toolbarBelow =
    suggestions.length > 0 || advancedChips.length > 0 ? (
      <div className="flex flex-col gap-1">
        {suggestions.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] uppercase tracking-wide text-slate-400">Matches</span>
            <button
              type="button"
              className="rounded border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-data-xs text-accent hover:bg-accent/20"
              onClick={() => applySymbol("NIFTY")}
            >
              NIFTY (index)
            </button>
            {suggestions.map((s) => (
              <button
                key={s.instrument_key}
                type="button"
                className="inline-flex max-w-[16rem] items-baseline gap-1 rounded border border-surface-border px-1.5 py-0.5 text-data-xs text-slate-300 hover:border-accent/40 hover:bg-white/5"
                onClick={() => applySymbol(s.symbol)}
              >
                <span className="ticker">{s.symbol}</span>
                <Clip title={s.name} className="text-slate-400">
                  {s.name}
                </Clip>
              </button>
            ))}
          </div>
        )}
        {advancedChips.length > 0 && <ActiveFilterChips chips={advancedChips} />}
      </div>
    ) : undefined;

  return (
    <div className="page-scroll space-y-1 px-1.5 py-1 sm:px-2">
      <PageToolbar
        right={
          <AdvancedButton
            onClick={() => setAdvancedOpen(true)}
            activeCount={advancedChips.length}
          />
        }
        below={toolbarBelow}
      >
        <h1 className="shrink-0 text-data-md font-semibold text-slate-100">Indicator Analysis</h1>
        <ToolbarDivider />
        <div className="relative shrink-0">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === "Enter") applySymbol(symbolInput);
            }}
            placeholder="NIFTY or RELIANCE"
            className="h-7 w-40 rounded-md border border-surface-border bg-surface pl-7 pr-2 text-data-sm text-slate-200"
          />
        </div>
        <button
          type="button"
          onClick={() => applySymbol(symbolInput)}
          className="h-7 shrink-0 rounded-md border border-surface-border px-2 text-data-sm text-slate-200 hover:border-accent/40"
        >
          Go
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-2.5 text-data-sm font-semibold text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
        <ToolbarDivider />
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-slate-400">Show</span>
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
            className={`h-7 shrink-0 rounded-md border px-2 text-data-sm ${
              filter === key
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-surface-border text-slate-300 hover:text-slate-100"
            }`}
          >
            {label}
          </button>
        ))}
      </PageToolbar>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-data-sm text-rose-200">
          {error}
        </div>
      )}

      {data && (
        <div className="panel flex items-center gap-3 overflow-x-auto px-2 py-1">
          <StatChip label="Instrument" value={data.label} hint={data.symbol} />
          <StatChip
            label="Last close"
            value={formatNum(data.last_bar.close)}
            hint={data.last_bar.ts ? String(data.last_bar.ts).slice(0, 16) : undefined}
          />
          <StatChip label="Bars" value={String(data.bar_count)} hint={`${data.timeframe} · ${data.source}`} />
          <StatChip
            label="Overall"
            value={
              <>
                <span className="capitalize">{overallLabel(data.overall_bias)}</span>
                <span className="ml-1 text-data-xs font-normal text-slate-300">
                  score {data.bias_score > 0 ? "+" : ""}
                  {data.bias_score}
                </span>
              </>
            }
            valueClassName={biasClass(data.overall_bias)
              .split(" ")
              .filter((c) => c.startsWith("text-"))
              .join(" ")}
          />
          <StatChip
            label="Bull / Bear"
            value={
              <>
                <span className="text-gain">{bullishCount}</span>
                <span className="text-slate-500"> / </span>
                <span className="text-loss">{bearishCount}</span>
              </>
            }
            hint="computable leans"
          />
          <StatChip label="Showing" value={`${indicators.length}`} valueClassName="text-slate-300" />
        </div>
      )}

      {loading && !data ? (
        <div className="panel flex h-48 items-center justify-center text-data-sm text-slate-400">
          Computing indicators…
        </div>
      ) : (
        <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {indicators.map((ind) => (
            <article key={ind.id} className="panel p-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-[10px] font-medium text-slate-400">#{ind.rank}</span>
                    <h2 className="min-w-0 text-data-md font-semibold text-slate-100">
                      <Clip title={ind.name}>{ind.name}</Clip>
                    </h2>
                  </div>
                  <p className="text-[10px] text-slate-400">
                    {ind.tweet_count} tweet mentions
                    {!ind.computable ? " · reference only" : ""}
                  </p>
                </div>
                <span className={`shrink-0 rounded border px-1.5 text-[10px] leading-4 capitalize ${biasClass(ind.bias)}`}>
                  {ind.bias.replace(/_/g, " ")}
                </span>
              </div>
              <MetricChips metrics={ind.metrics} />
              {ind.detail ? (
                <details className="group mt-1">
                  <summary className="cursor-pointer select-none text-[10px] uppercase tracking-wide text-slate-400 hover:text-slate-200">
                    Details
                  </summary>
                  <p className="mt-1 text-data-sm leading-relaxed text-slate-300">{ind.detail}</p>
                </details>
              ) : null}
            </article>
          ))}
        </div>
      )}

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Analysis settings"
        subtitle={symbol}
      >
        <AdvancedSection title="Filters">
          {isNifty ? (
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">Nifty timeframe</div>
              <div className="inline-flex rounded-md border border-surface-border bg-surface p-0.5">
                {NIFTY_TFS.map((tf) => (
                  <button
                    key={tf}
                    type="button"
                    onClick={() => setTimeframe(tf)}
                    className={`rounded px-2 py-0.5 text-data-sm ${
                      timeframe === tf ? "bg-accent/15 text-accent" : "text-slate-300 hover:text-slate-100"
                    }`}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-data-xs text-slate-400">Stocks use daily bars; timeframe applies to NIFTY only.</p>
          )}
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">RSI period</div>
            <input
              type="number"
              min={2}
              max={100}
              value={rsiPeriod}
              onChange={(e) => setRsiPeriod(Number(e.target.value) || 14)}
              className="h-7 w-16 rounded-md border border-surface-border bg-surface px-2 text-data-sm text-slate-200"
            />
          </div>
        </AdvancedSection>
        <AdvancedSection title="Help">
          <p className="leading-relaxed text-slate-300">
            Live readings for the toolkit ranked from @kyalashish tweets (Elliott, Time Cycle, Bollinger,
            Keltner, KST, Supertrend, Volume Profile, RSI, …). Computable indicators run on Nifty /
            stock OHLC; discretionary ones stay as reference.
          </p>
          <p className="text-data-xs text-slate-400">
            Ranked by tweet mention frequency · catalog from kyalashish_own_400
          </p>
        </AdvancedSection>
      </AdvancedDrawer>
    </div>
  );
}
