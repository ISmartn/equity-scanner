import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import {
  AdvancedButton,
  FilterReset,
  PageToolbar,
  StatChip,
  ToolbarDivider,
} from "@/components/dense";
import { TimelineDatePicker } from "@/components/TimelineDatePicker";
import { FnoStarMark } from "@/components/FnoStarMark";
import { StockFundamentalsPanel } from "@/components/StockFundamentalsPanel";
import {
  FundamentalVerdictCard,
  MomentumVerdictCard,
} from "@/components/StockFundamentalsVerdicts";
import {
  fetchFno,
  fetchFundamentallyStrong,
  fetchFundamentalsMomentumPass,
  fetchGrimesChart,
  fetchGrimesDates,
  fetchGrimesKnowledge,
  fetchGrimesSummary,
  fetchTimelineStats,
  fetchStockFundamentals,
  syncStockFundamentals,
  type GrimesChartPayload,
  type GrimesFilter,
  type GrimesFundamentalFilter,
  type GrimesKnowledgeResponse,
  type GrimesListingFilter,
  type GrimesRegimeFilter,
  type GrimesScanRow,
  type GrimesSetupFilter,
  type GrimesSummaryResponse,
  type StockFundamentals,
} from "@/lib/api";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";
import { clampWeekday, localTodayIso } from "@/lib/dates";
import { GrimesAdvanced } from "./GrimesAdvanced";
import { GrimesChart } from "./GrimesChart";
import { GrimesScannerFilters, GrimesScannerTable } from "./GrimesScannerTable";

const PREFS_KEY = "trading.grimesLab.prefs";

type RightTab = "chart" | "guide" | "diagnostics" | "knowledge";
type LabPrefs = {
  listingFilter: GrimesListingFilter;
  regimeFilter: GrimesRegimeFilter;
  setupFilter: GrimesSetupFilter;
  fundamentalFilter: GrimesFundamentalFilter;
  /** Legacy single filter — migrated on load */
  filter?: GrimesFilter;
  overlays: { pivots: boolean; mas: boolean; setups: boolean; riskBox: boolean; keltner: boolean };
  weeklyOnly: boolean;
  showFundamentals: boolean;
  rightTab: RightTab;
  capitalInr: number;
  riskPctPerTrade: number;
  tickerQuery: string;
  tradeDate: string;
};

function migrateFilters(prefs: LabPrefs): Pick<LabPrefs, "listingFilter" | "regimeFilter" | "setupFilter"> {
  if (prefs.listingFilter && prefs.regimeFilter && prefs.setupFilter) {
    return {
      listingFilter: prefs.listingFilter,
      regimeFilter: prefs.regimeFilter,
      setupFilter: prefs.setupFilter,
    };
  }
  const legacy = prefs.filter ?? "all";
  const listing: GrimesListingFilter =
    legacy === "fno" || legacy === "non_fno" || legacy === "index_only" ? legacy : "all";
  let regime: GrimesRegimeFilter = "all";
  if (legacy === "trend") regime = "trend";
  else if (legacy === "range") regime = "TRADING_RANGE";
  else if (legacy === "squeeze") regime = "VOLATILITY_COMPRESSION";
  let setup: GrimesSetupFilter = "all";
  if (
    legacy === "continuation" ||
    legacy === "mean_reversion" ||
    legacy === "squeeze_breakout" ||
    legacy === "high_quality"
  ) {
    setup = legacy;
  }
  return { listingFilter: listing, regimeFilter: regime, setupFilter: setup };
}

const DEFAULT_PREFS: LabPrefs = {
  listingFilter: "all",
  regimeFilter: "all",
  setupFilter: "all",
  fundamentalFilter: "all",
  overlays: { pivots: true, mas: true, setups: true, riskBox: true, keltner: false },
  weeklyOnly: false,
  showFundamentals: true,
  rightTab: "chart",
  capitalInr: 1_000_000,
  riskPctPerTrade: 1,
  tickerQuery: "",
  tradeDate: "",
};

const REGIME_BADGE: Record<string, string> = {
  TREND_BULL: "bg-emerald-500/20 text-emerald-300",
  TREND_BEAR: "bg-rose-500/20 text-rose-300",
  VOLATILITY_COMPRESSION: "bg-amber-500/20 text-amber-200",
  TRADING_RANGE: "bg-slate-500/20 text-slate-300",
  CLIMACTIC_EXHAUSTION: "bg-orange-500/20 text-orange-200",
};

export function GrimesLabPage() {
  const initial = loadUiPrefs(PREFS_KEY, DEFAULT_PREFS) as LabPrefs;
  const migrated = migrateFilters({ ...DEFAULT_PREFS, ...initial });
  const [data, setData] = useState<GrimesSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listingFilter, setListingFilter] = useState<GrimesListingFilter>(migrated.listingFilter);
  const [regimeFilter, setRegimeFilter] = useState<GrimesRegimeFilter>(migrated.regimeFilter);
  const [setupFilter, setSetupFilter] = useState<GrimesSetupFilter>(migrated.setupFilter);
  const [fundamentalFilter, setFundamentalFilter] = useState<GrimesFundamentalFilter>(
    initial.fundamentalFilter ?? DEFAULT_PREFS.fundamentalFilter,
  );
  const [overlays, setOverlays] = useState(initial.overlays ?? DEFAULT_PREFS.overlays);
  const [weeklyOnly, setWeeklyOnly] = useState(Boolean(initial.weeklyOnly));
  const [showFundamentals, setShowFundamentals] = useState(
    initial.showFundamentals !== false,
  );
  const [rightTab, setRightTab] = useState<RightTab>(initial.rightTab ?? "chart");
  const [selected, setSelected] = useState<GrimesScanRow | null>(null);
  const [chart, setChart] = useState<GrimesChartPayload | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [knowledge, setKnowledge] = useState<GrimesKnowledgeResponse | null>(null);
  const [checklistOpen, setChecklistOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [capitalInr, setCapitalInr] = useState(
    typeof initial.capitalInr === "number" && initial.capitalInr >= 1_000
      ? initial.capitalInr
      : DEFAULT_PREFS.capitalInr,
  );
  const [riskPctPerTrade, setRiskPctPerTrade] = useState(
    typeof initial.riskPctPerTrade === "number" && initial.riskPctPerTrade > 0
      ? initial.riskPctPerTrade
      : DEFAULT_PREFS.riskPctPerTrade,
  );
  const [fnoSymbols, setFnoSymbols] = useState<string[]>([]);
  const fnoSymbolSet = useMemo(() => new Set(fnoSymbols), [fnoSymbols]);
  const [strongSymbols, setStrongSymbols] = useState<string[]>([]);
  const [momentumSymbols, setMomentumSymbols] = useState<string[]>([]);
  const strongSymbolSet = useMemo(() => new Set(strongSymbols), [strongSymbols]);
  const momentumSymbolSet = useMemo(() => new Set(momentumSymbols), [momentumSymbols]);
  const [tickerQuery, setTickerQuery] = useState(
    typeof initial.tickerQuery === "string" ? initial.tickerQuery : "",
  );
  const [tradeDate, setTradeDate] = useState(
    typeof initial.tradeDate === "string" ? initial.tradeDate : "",
  );
  const [scanDates, setScanDates] = useState<string[]>([]);
  const [candleMinDate, setCandleMinDate] = useState<string | null>(null);
  const [candleMaxDate, setCandleMaxDate] = useState<string | null>(null);
  const today = localTodayIso();
  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [fundamentalsLoading, setFundamentalsLoading] = useState(false);
  const [fundamentalsError, setFundamentalsError] = useState<string | null>(null);
  const [fundamentalsSyncing, setFundamentalsSyncing] = useState(false);

  const loadFundamentals = useCallback(async (ticker: string) => {
    setFundamentalsLoading(true);
    setFundamentalsError(null);
    try {
      const payload = await fetchStockFundamentals(ticker, true);
      setFundamentals(payload);
    } catch (err) {
      setFundamentals(null);
      setFundamentalsError(
        err instanceof Error ? err.message : `No fundamentals for ${ticker}`,
      );
    } finally {
      setFundamentalsLoading(false);
    }
  }, []);

  const handleSyncFundamentals = useCallback(async () => {
    const ticker = selected?.ticker?.trim().toUpperCase();
    if (!ticker || selected?.kind === "index") return;
    setFundamentalsSyncing(true);
    setFundamentalsError(null);
    try {
      await syncStockFundamentals([ticker], true);
      await loadFundamentals(ticker);
      const [strongRes, momentumRes] = await Promise.all([
        fetchFundamentallyStrong(),
        fetchFundamentalsMomentumPass(),
      ]);
      setStrongSymbols(strongRes.symbols);
      setMomentumSymbols(momentumRes.symbols);
    } catch (err) {
      setFundamentalsError(err instanceof Error ? err.message : String(err));
    } finally {
      setFundamentalsSyncing(false);
    }
  }, [selected, loadFundamentals]);

  const load = useCallback(async (refresh = false, date = tradeDate) => {
    if (!date) return;
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchGrimesSummary(refresh, date);
      setData(payload);
      if (payload.trade_date && payload.trade_date !== date) {
        setTradeDate(payload.trade_date);
      }
      if (payload.has_run && payload.trade_date) {
        setScanDates((prev) =>
          prev.includes(payload.trade_date!)
            ? prev
            : [...prev, payload.trade_date!].sort((a, b) => b.localeCompare(a)),
        );
      }
      setSelected((prev) => {
        if (prev && payload.results.some((r) => r.instrument_key === prev.instrument_key)) {
          return prev;
        }
        return payload.results[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Grimes lab");
    } finally {
      setLoading(false);
    }
  }, [tradeDate]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [statsRes, datesRes] = await Promise.all([
          fetchTimelineStats(),
          fetchGrimesDates(),
        ]);
        if (cancelled) return;
        setCandleMinDate(statsRes.min_trade_date);
        setCandleMaxDate(statsRes.max_trade_date);
        setScanDates(datesRes.dates);
        setTradeDate((current) => {
          if (current) {
            return clampWeekday(current, statsRes.min_trade_date, statsRes.max_trade_date || today);
          }
          const pick = datesRes.latest_with_scan || datesRes.latest_data_date || statsRes.max_trade_date || today;
          return clampWeekday(pick, statsRes.min_trade_date, statsRes.max_trade_date || today);
        });
      } catch {
        if (!cancelled) {
          setTradeDate((current) => current || today);
        }
      }
    })();
    void fetchGrimesKnowledge()
      .then(setKnowledge)
      .catch(() => setKnowledge(null));
    fetchFno()
      .then((r) => setFnoSymbols(r.symbols))
      .catch(() => setFnoSymbols([]));
    fetchFundamentallyStrong()
      .then((r) => setStrongSymbols(r.symbols))
      .catch(() => setStrongSymbols([]));
    fetchFundamentalsMomentumPass()
      .then((r) => setMomentumSymbols(r.symbols))
      .catch(() => setMomentumSymbols([]));
    return () => {
      cancelled = true;
    };
  }, [today]);

  useEffect(() => {
    if (!tradeDate) return;
    void load(false, tradeDate);
  }, [tradeDate, load]);

  useEffect(() => {
    saveUiPrefs(PREFS_KEY, {
      listingFilter,
      regimeFilter,
      setupFilter,
      fundamentalFilter,
      overlays,
      weeklyOnly,
      showFundamentals,
      rightTab,
      capitalInr,
      riskPctPerTrade,
      tickerQuery,
      tradeDate,
    } satisfies LabPrefs);
  }, [
    listingFilter,
    regimeFilter,
    setupFilter,
    fundamentalFilter,
    overlays,
    weeklyOnly,
    showFundamentals,
    rightTab,
    capitalInr,
    riskPctPerTrade,
    tickerQuery,
    tradeDate,
  ]);

  useEffect(() => {
    if (!selected) {
      setChart(null);
      return;
    }
    let cancelled = false;
    setChartLoading(true);
    setChartError(null);
    void fetchGrimesChart(selected.instrument_key, {
      accountSize: capitalInr,
      riskPct: riskPctPerTrade / 100,
      tradeDate: tradeDate || data?.trade_date,
    })
      .then((payload) => {
        if (!cancelled) setChart(payload);
      })
      .catch((err) => {
        if (!cancelled) {
          setChart(null);
          setChartError(err instanceof Error ? err.message : "Chart failed");
        }
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.instrument_key, capitalInr, riskPctPerTrade, tradeDate, data?.trade_date]);

  useEffect(() => {
    if (!selected || selected.kind === "index") {
      setFundamentals(null);
      setFundamentalsError(null);
      return;
    }
    void loadFundamentals(selected.ticker);
  }, [selected?.ticker, selected?.kind, loadFundamentals]);

  const summary = data?.summary;
  const display = chart ?? selected;
  const rows = (data?.results ?? []).filter((r) =>
    weeklyOnly ? r.weekly_aligned === true : true,
  );

  const activeFilterCount = [
    listingFilter !== "all",
    regimeFilter !== "all",
    setupFilter !== "all",
    fundamentalFilter !== "all",
    weeklyOnly,
  ].filter(Boolean).length;

  const resetFilters = () => {
    setListingFilter("all");
    setRegimeFilter("all");
    setSetupFilter("all");
    setFundamentalFilter("all");
    setWeeklyOnly(false);
  };

  const openAdvancedAt = (tab: RightTab) => {
    setRightTab(tab);
    setAdvancedOpen(true);
  };

  return (
    <div className="page-shell flex flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0 py-0 text-data-sm">
          {error}
        </Alert>
      ) : null}

      <PageToolbar
        right={<AdvancedButton onClick={() => setAdvancedOpen(true)} label="Lab options" />}
        below={
          <GrimesScannerFilters
            listingFilter={listingFilter}
            onListingFilterChange={setListingFilter}
            regimeFilter={regimeFilter}
            onRegimeFilterChange={setRegimeFilter}
            setupFilter={setupFilter}
            onSetupFilterChange={setSetupFilter}
            fundamentalFilter={fundamentalFilter}
            onFundamentalFilterChange={setFundamentalFilter}
            weeklyOnly={weeklyOnly}
            onWeeklyOnlyChange={setWeeklyOnly}
            trailing={<FilterReset count={activeFilterCount} onReset={resetFilters} />}
          />
        }
      >
        <span className="shrink-0 text-data-md font-semibold text-slate-100">Grimes framework</span>
        <TimelineDatePicker
          compact
          showLegend={false}
          value={tradeDate}
          onChange={setTradeDate}
          availableDates={
            scanDates.length
              ? scanDates
              : candleMaxDate
                ? [candleMaxDate]
                : []
          }
          markedDates={scanDates}
          markedLabel="Scan done"
          minDate={candleMinDate}
          maxDate={candleMaxDate || today}
          disabled={loading && !data}
        />
        {loading ? (
          <span className="shrink-0 text-data-xs text-sky-300">Scanning full universe (1–2 min)…</span>
        ) : data?.has_run === false ? (
          <span className="shrink-0 text-data-xs text-amber-300">No stored scan</span>
        ) : null}
        {summary && data?.has_run !== false ? (
          <>
            <ToolbarDivider />
            <StatChip label="Bull" value={summary.trend_bull} valueClassName="text-emerald-300" />
            <StatChip label="Bear" value={summary.trend_bear} valueClassName="text-rose-300" />
            <StatChip label="Sqz" value={summary.squeeze} hint="Volatility compression" valueClassName="text-amber-300" />
            <StatChip label="PB" value={summary.pullbacks} hint="Pullbacks" valueClassName="text-sky-300" />
          </>
        ) : null}
        {display ? (
          <>
            <ToolbarDivider />
            <div className="flex shrink-0 items-center gap-1.5">
              <span className="flex items-center gap-1">
                <span className="ticker">{display.ticker}</span>
                {display.kind === "index" ? (
                  <span className="text-[10px] font-semibold text-amber-300">IDX</span>
                ) : (
                  <FnoStarMark show={fnoSymbolSet.has(display.ticker.toUpperCase())} />
                )}
              </span>
              <span
                className={`rounded-full px-2 py-px text-data-xs font-medium ${
                  REGIME_BADGE[chart?.regime ?? selected?.regime ?? ""] ?? "bg-white/10 text-slate-300"
                }`}
              >
                {(chart?.regime ?? selected?.regime ?? "").replace(/_/g, " ")}
              </span>
              <span
                className={`rounded-full px-2 py-px text-data-xs ${
                  display.weekly_aligned
                    ? "bg-sky-500/15 text-sky-300"
                    : display.weekly_aligned === false
                      ? "bg-white/5 text-slate-400"
                      : "bg-white/5 text-slate-400"
                }`}
              >
                Weekly {display.weekly_ema_up ? "EMA↑" : display.weekly_ema_up === false ? "EMA↓" : "—"}
                {display.weekly_aligned === true ? " aligned" : ""}
              </span>
              {chart?.setup_type || selected?.setup_type ? (
                <span className="rounded-full bg-violet-500/15 px-2 py-px text-data-xs text-violet-200">
                  {(chart?.setup_type ?? selected?.setup_type)?.replace(/_/g, " ")}
                </span>
              ) : null}
            </div>
          </>
        ) : null}
      </PageToolbar>

      <div
        className={`grid min-h-0 flex-1 gap-1 ${
          showFundamentals
            ? "lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.05fr)_minmax(15rem,0.72fr)] xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)_minmax(17rem,0.75fr)]"
            : "lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]"
        }`}
      >
        <div className="min-h-0">
          <GrimesScannerTable
            rows={rows}
            listingFilter={listingFilter}
            onListingFilterChange={setListingFilter}
            regimeFilter={regimeFilter}
            onRegimeFilterChange={setRegimeFilter}
            setupFilter={setupFilter}
            onSetupFilterChange={setSetupFilter}
            fundamentalFilter={fundamentalFilter}
            onFundamentalFilterChange={setFundamentalFilter}
            strongSymbolSet={strongSymbolSet}
            momentumSymbolSet={momentumSymbolSet}
            selectedKey={selected?.instrument_key ?? null}
            onSelect={setSelected}
            fnoSymbolSet={fnoSymbolSet}
            tickerQuery={tickerQuery}
            onTickerQueryChange={setTickerQuery}
            emptyHint={
              data?.has_run === false && tradeDate
                ? `No scan for ${tradeDate}. Click Rescan to compute this session.`
                : undefined
            }
          />
        </div>
        <div className="flex min-h-0 flex-col gap-1">
          {chartError ? (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-data-sm text-rose-300">
              {chartError}
            </div>
          ) : null}
          <div className="flex shrink-0 items-center gap-2 rounded-lg border border-surface-border bg-surface-raised px-2 py-1">
            <div className="min-w-0 flex-1 text-data-xs text-slate-300">
              {chart?.risk_box ? (
                <span className="num font-normal">
                  {chart.risk_box.side.toUpperCase()} · entry {chart.risk_box.entry} · stop{" "}
                  {chart.risk_box.stop} ·{" "}
                  {chart.risk_box.sizing.valid ? (
                    <>
                      {chart.risk_box.sizing.shares.toLocaleString("en-IN")} sh · risk ₹
                      {chart.risk_box.sizing.risk_amount.toLocaleString("en-IN")} (
                      {riskPctPerTrade}% of ₹{capitalInr.toLocaleString("en-IN")} capital)
                    </>
                  ) : (
                    "size n/a"
                  )}
                </span>
              ) : (
                <span className="text-slate-400">No risk box on this bar</span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={() => setChecklistOpen(true)}
                className="rounded-md bg-white/5 px-2 py-0.5 text-data-xs text-slate-300 hover:text-slate-100"
              >
                Checklist
              </button>
              {(
                [
                  ["guide", "Guide"],
                  ["diagnostics", "MAE / MFE"],
                  ["knowledge", "Knowledge"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => openAdvancedAt(id)}
                  title={`Open ${label} in the Advanced panel`}
                  className="rounded-md bg-white/5 px-2 py-0.5 text-data-xs text-slate-300 hover:text-slate-100"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="min-h-0 flex-1">
            <GrimesChart
              data={chart}
              loading={chartLoading}
              overlays={overlays}
              highlightDate={tradeDate || data?.trade_date || chart?.as_of}
              chartGuideIntro={knowledge?.chart_guide?.intro}
              chartGuideSections={knowledge?.chart_guide?.sections}
            />
          </div>
        </div>
        {showFundamentals ? (
          <aside className="flex min-h-0 min-w-0 flex-col gap-1 overflow-hidden">
            {!selected || selected.kind === "index" ? (
              <div className="flex h-full min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-surface-border px-3 text-center text-data-sm text-slate-400">
                {selected?.kind === "index"
                  ? "Fundamentals are not available for the index."
                  : "Select an equity to view balance sheet, results, and verdicts."}
              </div>
            ) : (
              <div className="panel flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto p-1.5">
                <FundamentalVerdictCard verdict={fundamentals?.quality_verdict} compact />
                <MomentumVerdictCard verdict={fundamentals?.momentum_verdict} compact />
                <div className="min-h-[16rem] flex-1">
                  <StockFundamentalsPanel
                    data={fundamentals}
                    loading={fundamentalsLoading}
                    error={fundamentalsError}
                    syncing={fundamentalsSyncing}
                    onSync={() => void handleSyncFundamentals()}
                    compact
                    sidebar
                  />
                </div>
              </div>
            )}
          </aside>
        ) : null}
      </div>

      <GrimesAdvanced
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        rightTab={rightTab}
        data={data}
        tradeDate={tradeDate}
        loading={loading}
        hasScanDates={scanDates.length > 0}
        onRescan={() => void load(true, tradeDate)}
        overlays={overlays}
        setOverlays={setOverlays}
        capitalInr={capitalInr}
        setCapitalInr={setCapitalInr}
        riskPctPerTrade={riskPctPerTrade}
        setRiskPctPerTrade={setRiskPctPerTrade}
        showFundamentals={showFundamentals}
        setShowFundamentals={setShowFundamentals}
        knowledge={knowledge}
        chart={chart}
        checklistOpen={checklistOpen}
        setChecklistOpen={setChecklistOpen}
      />
    </div>
  );
}
