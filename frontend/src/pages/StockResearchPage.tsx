import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, RefreshCw } from "lucide-react";
import {
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  Clip,
  PageToolbar,
  PctCell,
  StatChip,
  ToolbarDivider,
} from "@/components/dense";
import { StockFundamentalsPanel } from "@/components/StockFundamentalsPanel";
import {
  FundamentalVerdictCard,
  MomentumVerdictCard,
} from "@/components/StockFundamentalsVerdicts";
import { StockTickerSearch } from "@/components/StockTickerSearch";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import {
  fetchStockFundamentals,
  fetchTimelineCandles,
  syncStockFundamentals,
  type StockFundamentals,
  type TimelineCandlePoint,
} from "@/lib/api";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

const PREFS_KEY = "trading.stockResearch.prefs";
type Prefs = { ticker: string };
const DEFAULT_PREFS: Prefs = { ticker: "" };

function companyNameFromFundamentals(data: StockFundamentals | null): string | null {
  const profile = data?.profile;
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return null;
  const obj = profile as Record<string, unknown>;
  const nested =
    obj.data && typeof obj.data === "object" && !Array.isArray(obj.data)
      ? (obj.data as Record<string, unknown>)
      : obj;
  for (const key of ["company_name", "companyName", "name", "short_name"]) {
    const v = nested[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

function sectorFromFundamentals(data: StockFundamentals | null): string | null {
  const fromVerdict = data?.quality_verdict?.sector;
  if (typeof fromVerdict === "string" && fromVerdict.trim()) return fromVerdict.trim();
  const profile = data?.profile;
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return null;
  const obj = profile as Record<string, unknown>;
  const nested =
    obj.data && typeof obj.data === "object" && !Array.isArray(obj.data)
      ? (obj.data as Record<string, unknown>)
      : obj;
  const v = nested.sector ?? nested.industry;
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

export function StockResearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialPrefs = loadUiPrefs(PREFS_KEY, DEFAULT_PREFS);
  const paramTicker = (searchParams.get("ticker") || "").trim().toUpperCase();
  const [ticker, setTicker] = useState(paramTicker || initialPrefs.ticker || "");

  const [history, setHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [fundamentalsLoading, setFundamentalsLoading] = useState(false);
  const [fundamentalsError, setFundamentalsError] = useState<string | null>(null);
  const [fundamentalsSyncing, setFundamentalsSyncing] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    saveUiPrefs(PREFS_KEY, { ticker } satisfies Prefs);
  }, [ticker]);

  useEffect(() => {
    if (paramTicker && paramTicker !== ticker) {
      setTicker(paramTicker);
    }
    // Only react to URL ticker changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramTicker]);

  const loadChart = useCallback(async (symbol: string) => {
    setChartLoading(true);
    setChartError(null);
    try {
      const payload = await fetchTimelineCandles(symbol);
      setHistory(payload.history ?? []);
      setChartSource(payload.source ?? "local");
    } catch (exc) {
      setHistory([]);
      setChartError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setChartLoading(false);
    }
  }, []);

  const loadFundamentals = useCallback(async (symbol: string) => {
    setFundamentalsLoading(true);
    setFundamentalsError(null);
    try {
      const payload = await fetchStockFundamentals(symbol, true);
      setFundamentals(payload);
    } catch (exc) {
      setFundamentals(null);
      setFundamentalsError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setFundamentalsLoading(false);
    }
  }, []);

  useEffect(() => {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) {
      setHistory([]);
      setFundamentals(null);
      setChartError(null);
      setFundamentalsError(null);
      return;
    }
    void loadChart(symbol);
    void loadFundamentals(symbol);
  }, [ticker, loadChart, loadFundamentals]);

  const onTickerChange = (next: string) => {
    const symbol = next.trim().toUpperCase();
    setTicker(symbol);
    if (symbol) {
      setSearchParams({ ticker: symbol }, { replace: true });
    } else {
      setSearchParams({}, { replace: true });
    }
  };

  const handleSyncFundamentals = async () => {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return;
    setFundamentalsSyncing(true);
    setFundamentalsError(null);
    try {
      await syncStockFundamentals([symbol], true);
      await loadFundamentals(symbol);
    } catch (exc) {
      setFundamentalsError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setFundamentalsSyncing(false);
    }
  };

  const companyName = useMemo(() => companyNameFromFundamentals(fundamentals), [fundamentals]);
  const sector = useMemo(() => sectorFromFundamentals(fundamentals), [fundamentals]);
  const highlightDate = history.length ? history[history.length - 1].date : "";
  const lastClose = history.length ? history[history.length - 1].close : null;
  const lastMove = history.length ? history[history.length - 1].daily_return_pct ?? null : null;

  return (
    <main className="page-shell flex flex-col gap-1 overflow-y-auto px-1.5 py-1 sm:px-2 lg:overflow-hidden">
      <PageToolbar
        right={
          <>
            <div className="w-[14rem] sm:w-[18rem]">
              <StockTickerSearch
                compact
                value={ticker}
                onChange={onTickerChange}
                placeholder="Search ticker or company…"
              />
            </div>
            <AdvancedButton onClick={() => setAdvancedOpen(true)} label="More" />
          </>
        }
      >
        <h1 className="shrink-0 text-data-md font-semibold text-slate-100">Stock Research</h1>
        {ticker ? (
          <>
            <ToolbarDivider />
            <span className="ticker shrink-0">{ticker}</span>
            {companyName ? (
              <span className="max-w-[16rem] shrink-0 text-data-sm text-slate-300">
                <Clip>{companyName}</Clip>
              </span>
            ) : null}
            {sector ? <StatChip label="Sector" value={sector} valueClassName="text-data-sm font-medium text-slate-200" /> : null}
            {typeof lastClose === "number" ? (
              <StatChip
                label="Close"
                value={`₹${lastClose.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`}
              />
            ) : null}
            {typeof lastMove === "number" ? (
              <StatChip label="1D" value={<PctCell value={lastMove} />} />
            ) : null}
          </>
        ) : null}
      </PageToolbar>

      {!ticker ? (
        <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-surface-border px-4 py-8 text-center text-data-md text-slate-400">
          Search a ticker to open its chart, results, and fundamental verdict.
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-1.5 lg:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.9fr)] lg:grid-rows-[minmax(0,1fr)]">
          <section className="flex h-[28rem] min-h-0 flex-col gap-1 lg:h-auto">
            {chartError && (
              <div className="flex shrink-0 items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-data-xs text-amber-200">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{chartError}</span>
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-hidden">
              <TimelineStockChart
                symbol={ticker}
                companyName={companyName}
                sector={sector}
                source={chartSource}
                history={history}
                highlightDate={highlightDate}
                highlightMovePct={lastMove}
                loading={chartLoading}
                fillHeight
                tailVisibleRange
                showRsi
              />
            </div>
          </section>

          <aside className="flex min-h-0 flex-col gap-1.5 lg:overflow-y-auto">
            <FundamentalVerdictCard verdict={fundamentals?.quality_verdict} />
            <MomentumVerdictCard verdict={fundamentals?.momentum_verdict} />
            <div className="min-h-[22rem]">
              <StockFundamentalsPanel
                data={fundamentals}
                loading={fundamentalsLoading}
                error={fundamentalsError}
                syncing={fundamentalsSyncing}
                onSync={() => void handleSyncFundamentals()}
                sidebar
              />
            </div>
          </aside>
        </div>
      )}

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Stock research"
        subtitle={ticker || "No ticker selected"}
      >
        <AdvancedSection title="Jobs">
          <button
            type="button"
            disabled={!ticker || fundamentalsSyncing}
            onClick={() => void handleSyncFundamentals()}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-surface-border bg-surface px-3 text-data-sm text-slate-200 hover:border-accent/40 disabled:opacity-50"
            title="Force-refresh fundamentals from Upstox"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${fundamentalsSyncing ? "animate-spin" : ""}`} />
            Sync fundamentals
          </button>
          <p className="text-data-xs text-slate-400">Force-refresh fundamentals from Upstox for the selected ticker.</p>
        </AdvancedSection>
        <AdvancedSection title="Help">
          <p className="leading-relaxed text-slate-300">
            Search a stock for price + RSI, company financials, quality verdict, and quarterly momentum.
          </p>
        </AdvancedSection>
      </AdvancedDrawer>
    </main>
  );
}
