import { AlertTriangle, Cpu, Database, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CompanyNewsSidebar } from "@/components/news/CompanyNewsSidebar";
import {
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  PageToolbar,
  StatChip,
  ToolbarDivider,
} from "@/components/dense";
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
  const [advancedOpen, setAdvancedOpen] = useState(false);

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
    <div className="page-shell flex flex-col lg:flex-row">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
        <PageToolbar right={<AdvancedButton onClick={() => setAdvancedOpen(true)} label="Model info" />}>
          <StockSelector
            compact
            symbols={symbols}
            value={symbol}
            onChange={setSymbol}
            loading={loadingSymbols}
          />
          <ModelPicker compact models={models} value={model} onChange={setModel} />
          <IntervalPicker compact value={interval} onChange={setInterval} />
          <button
            type="button"
            onClick={runForecast}
            disabled={loadingForecast || loadingSymbols}
            className="inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-md bg-accent px-3 text-data-sm font-semibold text-white transition hover:bg-accent-muted disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loadingForecast ? "animate-spin" : ""}`} />
            Run Forecast
          </button>
          {forecast && (
            <>
              <ToolbarDivider />
              <StatChip
                icon={<Database className="h-3.5 w-3.5 text-sky-400" />}
                label="History"
                value={`${forecast.history_bars} ${forecast.interval}`}
                hint={`${forecast.lookback_years} years from ${forecast.source.toUpperCase()}`}
              />
              <StatChip
                icon={<Cpu className="h-3.5 w-3.5 text-violet-400" />}
                label="Context"
                value={`${forecast.context_length} bars`}
                hint={`${forecast.horizon}-step horizon`}
              />
              <StatChip
                icon={<ShieldAlert className="h-3.5 w-3.5 text-amber-400" />}
                label="Spread"
                value={`${forecast.spread_pct.toFixed(1)}%`}
                hint="Avg 80% band width vs last close"
                valueClassName="text-amber-200"
              />
            </>
          )}
        </PageToolbar>

        {error && (
          <div className="flex shrink-0 items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-data-sm text-red-100">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <section className="min-h-[320px] flex-1">
          <ForecastChart data={forecast} loading={loadingForecast} fillHeight />
        </section>
      </main>

      <CompanyNewsSidebar
        ticker={symbol}
        companyName={symbol}
        className="h-[min(50vh,28rem)] shrink-0 border-t lg:h-full lg:border-t-0"
      />

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Forecast details"
        subtitle={symbol}
      >
        <AdvancedSection title="Models">
          <ModelPicker models={models} value={model} onChange={setModel} />
        </AdvancedSection>
        <AdvancedSection title="Timeframes">
          <IntervalPicker value={interval} onChange={setInterval} />
        </AdvancedSection>
        <AdvancedSection title="Risk note">
          <p className="leading-relaxed text-slate-300">
            <strong className="text-slate-100">Risk note:</strong> TimesFM outputs a median path
            plus quantile bands — not a guaranteed price target. A wider 80% interval usually
            signals higher uncertainty (volatility, events, or regime change). Always treat
            forecasts as scenario guidance, not trade signals.
          </p>
        </AdvancedSection>
      </AdvancedDrawer>
    </div>
  );
}
