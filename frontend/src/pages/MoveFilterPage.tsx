import { AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { MoveFilterChart } from "@/components/MoveFilterChart";
import { MoveFilterStockSidebar } from "@/components/MoveFilterStockSidebar";
import { MoveFilterToolbar } from "@/components/MoveFilterToolbar";
import { fetchCandles, fetchFno, fetchNifty50, type CandlesPayload } from "@/lib/api";
import { DEFAULT_DARVAS_LOOKBACK_DAYS } from "@/lib/darvasBox";
import {
  DEFAULT_MOVE_FILTER_SETTINGS,
  getMoveFilterSettings,
  getWatchlist,
  setMoveFilterSettings,
} from "@/lib/storage";

const initialSettings = getMoveFilterSettings();

export function MoveFilterPage() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [fnoSymbols, setFnoSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState(initialSettings.symbol);
  const [data, setData] = useState<CandlesPayload | null>(null);
  const [loadingSymbols, setLoadingSymbols] = useState(true);
  const [loadingFnoSymbols, setLoadingFnoSymbols] = useState(true);
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [positiveEnabled, setPositiveEnabled] = useState(initialSettings.positiveEnabled);
  const [negativeEnabled, setNegativeEnabled] = useState(initialSettings.negativeEnabled);
  const [positiveInput, setPositiveInput] = useState(initialSettings.positiveInput);
  const [negativeInput, setNegativeInput] = useState(initialSettings.negativeInput);
  const [threeGreenEnabled, setThreeGreenEnabled] = useState(initialSettings.threeGreenEnabled);

  const [darvasEnabled, setDarvasEnabled] = useState(initialSettings.darvasEnabled);
  const [darvasLookbackInput, setDarvasLookbackInput] = useState(
    initialSettings.darvasLookbackInput || String(DEFAULT_DARVAS_LOOKBACK_DAYS),
  );

  const positiveThreshold = positiveEnabled ? parseFloat(positiveInput) : null;
  const negativeThreshold = negativeEnabled ? parseFloat(negativeInput) : null;
  const darvasLookbackDays = darvasEnabled
    ? parseInt(darvasLookbackInput, 10)
    : DEFAULT_DARVAS_LOOKBACK_DAYS;

  useEffect(() => {
    fetchNifty50()
      .then((res) => {
        setSymbols(res.symbols);
        const persisted = getMoveFilterSettings().symbol;
        if (persisted) {
          setSymbol(persisted);
          return;
        }
        const saved = getWatchlist().map((s) => s.symbol);
        const preferred = saved.includes(symbol)
          ? symbol
          : res.symbols.includes(symbol)
            ? symbol
            : saved[0] ?? res.symbols[0];
        if (preferred) setSymbol(preferred);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingSymbols(false));

    fetchFno()
      .then((res) => setFnoSymbols(res.symbols))
      .catch((err) => setError((prev) => prev ?? err.message))
      .finally(() => setLoadingFnoSymbols(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot once
  }, []);

  useEffect(() => {
    setMoveFilterSettings({
      symbol,
      positiveEnabled,
      negativeEnabled,
      positiveInput,
      negativeInput,
      threeGreenEnabled,
      darvasEnabled,
      darvasLookbackInput,
    });
  }, [
    symbol,
    positiveEnabled,
    negativeEnabled,
    positiveInput,
    negativeInput,
    threeGreenEnabled,
    darvasEnabled,
    darvasLookbackInput,
  ]);

  const loadCandles = useCallback(async () => {
    setLoadingCandles(true);
    setError(null);
    try {
      const result = await fetchCandles(symbol, "daily");
      setData(result);
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "Failed to load candles");
    } finally {
      setLoadingCandles(false);
    }
  }, [symbol]);

  useEffect(() => {
    if (!loadingSymbols && symbol) {
      loadCandles();
    }
  }, [symbol, loadingSymbols, loadCandles]);

  const filterInvalid =
    (positiveEnabled && (positiveThreshold === null || Number.isNaN(positiveThreshold))) ||
    (negativeEnabled && (negativeThreshold === null || Number.isNaN(negativeThreshold)));

  const darvasLookbackInvalid =
    darvasEnabled &&
    (Number.isNaN(darvasLookbackDays) || darvasLookbackDays < 5 || darvasLookbackDays > 252);

  const handleResetFilters = () => {
    setPositiveEnabled(false);
    setNegativeEnabled(false);
    setThreeGreenEnabled(false);
    setDarvasEnabled(false);
    setPositiveInput(DEFAULT_MOVE_FILTER_SETTINGS.positiveInput);
    setNegativeInput(DEFAULT_MOVE_FILTER_SETTINGS.negativeInput);
    setDarvasLookbackInput(DEFAULT_MOVE_FILTER_SETTINGS.darvasLookbackInput);
  };

  return (
    <main className="mx-auto flex h-[calc(100dvh-7.25rem)] min-h-0 max-w-[1920px] flex-col gap-2 overflow-hidden px-3 py-2 sm:px-4 lg:flex-row">
      <div className="h-[40vh] shrink-0 lg:h-full lg:w-auto">
        <MoveFilterStockSidebar
          symbol={symbol}
          onSymbolChange={setSymbol}
          niftySymbols={symbols}
          fnoSymbols={fnoSymbols}
          loadingSymbols={loadingSymbols}
          loadingFno={loadingFnoSymbols}
        />
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden">
        <MoveFilterToolbar
          positiveEnabled={positiveEnabled}
          negativeEnabled={negativeEnabled}
          threeGreenEnabled={threeGreenEnabled}
          darvasEnabled={darvasEnabled}
          positiveInput={positiveInput}
          negativeInput={negativeInput}
          darvasLookbackInput={darvasLookbackInput}
          onPositiveEnabled={setPositiveEnabled}
          onNegativeEnabled={setNegativeEnabled}
          onThreeGreenEnabled={setThreeGreenEnabled}
          onDarvasEnabled={setDarvasEnabled}
          onPositiveInput={setPositiveInput}
          onNegativeInput={setNegativeInput}
          onDarvasLookbackInput={setDarvasLookbackInput}
          onResetFilters={handleResetFilters}
          filterInvalid={filterInvalid}
          darvasLookbackInvalid={darvasLookbackInvalid}
          loadingCandles={loadingCandles}
          onRefresh={loadCandles}
        />

        {error && (
          <div className="flex shrink-0 items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised/30 p-1">
          <MoveFilterChart
            symbol={data?.symbol ?? symbol}
            source={data?.source ?? "upstox"}
            history={data?.history ?? []}
            historyBars={data?.history_bars ?? 0}
            lookbackYears={data?.lookback_years ?? 5}
            latestClose={data?.latest_close ?? 0}
            positiveThreshold={filterInvalid ? null : positiveThreshold}
            negativeThreshold={filterInvalid ? null : negativeThreshold}
            positiveEnabled={positiveEnabled && !filterInvalid}
            negativeEnabled={negativeEnabled && !filterInvalid}
            threeGreenEnabled={threeGreenEnabled}
            darvasEnabled={darvasEnabled && !darvasLookbackInvalid}
            darvasLookbackDays={
              darvasLookbackInvalid ? DEFAULT_DARVAS_LOOKBACK_DAYS : darvasLookbackDays
            }
            loading={loadingCandles}
            fillHeight
          />
        </section>
      </div>
    </main>
  );
}
