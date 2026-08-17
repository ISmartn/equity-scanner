import { AlertTriangle, Cpu, Database, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { CompanyNewsSidebar } from "@/components/news/CompanyNewsSidebar";
import { ModelPicker } from "@/components/ModelPicker";
import { ForecastChart } from "@/components/ForecastChart";
import { IntervalPicker } from "@/components/IntervalPicker";
import { StockSelector } from "@/components/StockSelector";
import {
  fetchForecast,
  fetchModels,
  fetchNifty50,
  type ForecastModelId,
  type ForecastPayload,
  type Interval,
} from "@/lib/api";
import {
  getForecastSettings,
  setForecastSettings,
} from "@/lib/storage";

const initialForecastSettings = getForecastSettings();

export function ForecastPage() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState(initialForecastSettings.symbol);
  const [interval, setInterval] = useState<Interval>(initialForecastSettings.interval);
  const [model, setModel] = useState(initialForecastSettings.model);
  const [models, setModels] = useState<ForecastModelId[]>([]);
  const [forecast, setForecast] = useState<ForecastPayload | null>(null);
  const [loadingSymbols, setLoadingSymbols] = useState(true);
  const [loadingForecast, setLoadingForecast] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const saved = getForecastSettings();
    fetchModels()
      .then((res) => {
        setModels(res.models);
        const defaultModel = res.models.find((m) => m.default && m.available)?.id
          ?? res.models.find((m) => m.available)?.id;
        const preferred = res.models.some((m) => m.id === saved.model && m.available)
          ? saved.model
          : defaultModel;
        if (preferred) setModel(preferred);
      })
      .catch(() => {});
    fetchNifty50()
      .then((res) => {
        setSymbols(res.symbols);
        const persisted = getForecastSettings().symbol;
        if (persisted) {
          setSymbol(persisted);
          return;
        }
        if (res.symbols.length && !res.symbols.includes(symbol)) {
          setSymbol(res.symbols[0]);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingSymbols(false));
  }, []);

  useEffect(() => {
    setForecastSettings({ symbol, interval, model });
  }, [symbol, interval, model]);

  const runForecast = useCallback(async () => {
    setLoadingForecast(true);
    setError(null);
    try {
      const result = await fetchForecast(symbol, interval, model);
      setForecast(result);
    } catch (err) {
      setForecast(null);
      setError(err instanceof Error ? err.message : "Forecast failed");
    } finally {
      setLoadingForecast(false);
    }
  }, [symbol, interval, model]);

  return (
    <div className="flex h-[calc(100dvh-7.25rem)] min-h-0 flex-col lg:flex-row">
      <main className="mx-auto grid min-h-0 min-w-0 flex-1 gap-6 overflow-y-auto px-4 py-6 sm:px-6 lg:max-w-none lg:grid-cols-[280px_1fr]">
        <aside className="space-y-4">
          <StockSelector
            symbols={symbols}
            value={symbol}
            onChange={setSymbol}
            loading={loadingSymbols}
          />

          <div className="rounded-2xl border border-surface-border bg-surface-raised p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Forecast model
            </h3>
            <ModelPicker models={models} value={model} onChange={setModel} />
          </div>

          <div className="rounded-2xl border border-surface-border bg-surface-raised p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Timeframe
            </h3>
            <IntervalPicker value={interval} onChange={setInterval} />
          </div>

          <button
            type="button"
            onClick={runForecast}
            disabled={loadingForecast || loadingSymbols}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent-muted disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${loadingForecast ? "animate-spin" : ""}`} />
            Run Forecast
          </button>
        </aside>

        <section className="space-y-4">
          {error && (
            <div className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <ForecastChart data={forecast} loading={loadingForecast} />

          {forecast && (
            <div className="grid gap-4 sm:grid-cols-3">
              <MetricCard
                icon={<Database className="h-4 w-4 text-sky-400" />}
                label="History"
                value={`${forecast.history_bars} ${forecast.interval} bars`}
                hint={`${forecast.lookback_years} years from ${forecast.source.toUpperCase()}`}
              />
              <MetricCard
                icon={<Cpu className="h-4 w-4 text-violet-400" />}
                label="Context window"
                value={`${forecast.context_length} bars`}
                hint={`${forecast.horizon}-step horizon`}
              />
              <MetricCard
                icon={<ShieldAlert className="h-4 w-4 text-amber-400" />}
                label="Uncertainty spread"
                value={`${forecast.spread_pct.toFixed(1)}%`}
                hint="Avg 80% band width vs last close"
              />
            </div>
          )}

          <div className="rounded-2xl border border-surface-border bg-surface-raised/60 p-4 text-sm leading-relaxed text-slate-400">
            <strong className="text-slate-200">Risk note:</strong> TimesFM outputs a median path
            plus quantile bands — not a guaranteed price target. A wider 80% interval usually
            signals higher uncertainty (volatility, events, or regime change). Always treat
            forecasts as scenario guidance, not trade signals.
          </div>
        </section>
      </main>

      <CompanyNewsSidebar
        ticker={symbol}
        companyName={symbol}
        className="h-[min(50vh,28rem)] shrink-0 border-t lg:h-full lg:border-t-0"
      />
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
        {icon}
        {label}
      </div>
      <div className="text-lg font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{hint}</div>
    </div>
  );
}
