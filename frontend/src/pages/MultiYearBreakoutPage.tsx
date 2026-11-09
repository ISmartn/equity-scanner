import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import LinearProgress from "@mui/material/LinearProgress";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import DocumentScannerIcon from "@mui/icons-material/DocumentScanner";
import RefreshIcon from "@mui/icons-material/Refresh";
import { Star } from "lucide-react";
import { TimelineDatePicker } from "@/components/TimelineDatePicker";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { AppButton } from "@/components/mui/AppButton";
import {
  AdvancedButton,
  Clip,
  PageToolbar,
  PctCell,
  ToolbarDivider,
  pctTone,
} from "@/components/dense";
import { MultiYearBreakoutAdvanced, type FnoGroupFilter } from "@/pages/breakout/MultiYearBreakoutAdvanced";
import { MultiYearBreakoutFilters } from "@/pages/breakout/MultiYearBreakoutFilters";
import {
  fetchFno,
  fetchFundamentallyStrong,
  fetchMybDates,
  fetchMybResults,
  fetchMybStatus,
  fetchTimelineCandles,
  fetchTimelineSectors,
  fetchTimelineStats,
  runMybScan,
  type MybBatchMode,
  type MybMaType,
  type MybMatchMode,
  type MybScanStatus,
  type MybSignal,
  type MybSizeTier,
  type MybStatus,
  type MybStrategy,
  type MybTrendFilter,
  type TimelineCandlePoint,
  type TimelineStats,
} from "@/lib/api";
import { clampWeekday, localTodayIso } from "@/lib/dates";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";
import {
  FUNDAMENTALLY_STRONG_TOOLTIP,
  fundamentalStrongFromDetails,
} from "@/lib/fundamentalsMeta";

const PAGE_SIZE = 80;
const ALL = "all";

const MYB_PREFS_KEY = "trading.myb.prefs";
type MybUiPrefs = {
  tradeDate: string;
  strategy: MybStrategy;
  lookbackYears: number;
  pullbackPct: number;
  matchMode: MybMatchMode;
  bandWidthPct: number;
  trendFilter: MybTrendFilter;
  showAdvancedTrend: boolean;
  shortMaPeriod: number;
  longMaPeriod: number;
  maType: MybMaType;
  includeMultiYear: boolean;
  includeAthPullback: boolean;
  statusFilter: string;
  minScore: string;
  sector: string;
  sizeTier: MybSizeTier;
  fnoGroup: FnoGroupFilter;
  fundamentallyStrongOnly: boolean;
  minPrice: string;
  maxPrice: string;
  minRvol: string;
};
const DEFAULT_MYB_PREFS: MybUiPrefs = {
  tradeDate: "",
  strategy: "multi_year_breakout",
  lookbackYears: 3,
  pullbackPct: 15,
  matchMode: "at_least",
  bandWidthPct: 5,
  trendFilter: "all",
  showAdvancedTrend: false,
  shortMaPeriod: 50,
  longMaPeriod: 200,
  maType: "sma",
  includeMultiYear: true,
  includeAthPullback: true,
  statusFilter: ALL,
  minScore: "40",
  sector: ALL,
  sizeTier: "all",
  fnoGroup: "all",
  fundamentallyStrongOnly: false,
  minPrice: "",
  maxPrice: "",
  minRvol: "",
};


function mergeSortedDates(existing: string[], additions: string[]): string[] {
  if (!additions.length) return existing;
  return [...new Set([...existing, ...additions.filter(Boolean)])].sort((a, b) =>
    b.localeCompare(a),
  );
}

function FnoStarMark({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span title="F&O stock" aria-label="F&O stock">
      <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400" aria-hidden />
    </span>
  );
}

const STRATEGIES: { id: MybStrategy; label: string; blurb: string }[] = [
  {
    id: "multi_year_breakout",
    label: "Multi-Year Breakout",
    blurb: "Fresh or near break of a dormant multi-year high with volume confirmation.",
  },
  {
    id: "ath_pullback",
    label: "Pullback from ATH",
    blurb: "Stocks down at least X% from ATH, with optional uptrend / downtrend filter.",
  },
  {
    id: "custom",
    label: "Custom Filters",
    blurb: "Combine multi-year and ATH pullback conditions with shared global filters.",
  },
];

function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

function fmtBelowAth(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `−${Math.abs(value).toFixed(digits)}%`;
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function fmtCr(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `₹${(value / 10_000_000).toFixed(1)} Cr`;
}

function statusTone(status: MybStatus): string {
  if (status === "breakout") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
  if (status === "pullback") return "bg-sky-500/15 text-sky-300 border-sky-500/40";
  return "bg-amber-500/15 text-amber-300 border-amber-500/40";
}

function trendTone(trend: string | undefined): string {
  if (trend === "uptrend") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
  if (trend === "downtrend") return "bg-rose-500/15 text-rose-300 border-rose-500/40";
  return "bg-slate-500/15 text-slate-300 border-slate-500/40";
}

function detailStr(row: MybSignal, key: string): string | undefined {
  const v = row.details?.[key];
  return typeof v === "string" ? v : undefined;
}

function detailNum(row: MybSignal, key: string): number | null {
  const v = row.details?.[key];
  return typeof v === "number" && !Number.isNaN(v) ? v : null;
}

export function MultiYearBreakoutPage() {
  const today = localTodayIso();
  const initialPrefs = loadUiPrefs(MYB_PREFS_KEY, DEFAULT_MYB_PREFS);
  const [stats, setStats] = useState<TimelineStats | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [scanDates, setScanDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState(initialPrefs.tradeDate);

  const [strategy, setStrategy] = useState<MybStrategy>(initialPrefs.strategy);
  const [lookbackYears, setLookbackYears] = useState(Number(initialPrefs.lookbackYears) || 3);
  const [pullbackPct, setPullbackPct] = useState(Number(initialPrefs.pullbackPct) || 15);
  const [matchMode, setMatchMode] = useState<MybMatchMode>(initialPrefs.matchMode);
  const [bandWidthPct, setBandWidthPct] = useState(Number(initialPrefs.bandWidthPct) || 5);
  const [trendFilter, setTrendFilter] = useState<MybTrendFilter>(initialPrefs.trendFilter);
  const [showAdvancedTrend, setShowAdvancedTrend] = useState(Boolean(initialPrefs.showAdvancedTrend));
  const [shortMaPeriod, setShortMaPeriod] = useState(Number(initialPrefs.shortMaPeriod) || 50);
  const [longMaPeriod, setLongMaPeriod] = useState(Number(initialPrefs.longMaPeriod) || 200);
  const [maType, setMaType] = useState<MybMaType>(initialPrefs.maType);
  const [includeMultiYear, setIncludeMultiYear] = useState(initialPrefs.includeMultiYear !== false);
  const [includeAthPullback, setIncludeAthPullback] = useState(initialPrefs.includeAthPullback !== false);

  const [statusFilter, setStatusFilter] = useState<MybStatus | typeof ALL>(
    (initialPrefs.statusFilter as MybStatus | typeof ALL) || ALL,
  );
  const [minScore, setMinScore] = useState(initialPrefs.minScore || "40");
  const [sector, setSector] = useState(initialPrefs.sector || ALL);
  const [sizeTier, setSizeTier] = useState<MybSizeTier>(initialPrefs.sizeTier || "all");
  const [fnoGroup, setFnoGroup] = useState<FnoGroupFilter>(
    initialPrefs.fnoGroup === "fno" || initialPrefs.fnoGroup === "non_fno" ? initialPrefs.fnoGroup : "all",
  );
  const [fnoSymbols, setFnoSymbols] = useState<string[]>([]);
  const fnoSymbolSet = useMemo(() => new Set(fnoSymbols), [fnoSymbols]);
  const [fundamentallyStrongOnly, setFundamentallyStrongOnly] = useState(Boolean(initialPrefs.fundamentallyStrongOnly));
  const [strongSymbols, setStrongSymbols] = useState<string[]>([]);
  const strongSymbolSet = useMemo(() => new Set(strongSymbols), [strongSymbols]);
  const [minPrice, setMinPrice] = useState(initialPrefs.minPrice || "");
  const [maxPrice, setMaxPrice] = useState(initialPrefs.maxPrice || "");
  const [minRvol, setMinRvol] = useState(initialPrefs.minRvol || "");
  const [page, setPage] = useState(0);

  const [rows, setRows] = useState<MybSignal[]>([]);
  const [total, setTotal] = useState(0);
  const [scanAlertsCount, setScanAlertsCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  const [scanRunning, setScanRunning] = useState(false);
  const [scanStatus, setScanStatus] = useState<MybScanStatus | null>(null);
  const scanPollRef = useRef<number | null>(null);

  const [selected, setSelected] = useState<MybSignal | null>(null);
  const [chartHistory, setChartHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [chartLoading, setChartLoading] = useState(false);

  const minScoreNum = Number(minScore);
  const minPriceNum = minPrice.trim() === "" ? undefined : Number(minPrice);
  const maxPriceNum = maxPrice.trim() === "" ? undefined : Number(maxPrice);
  const minRvolNum = minRvol.trim() === "" ? undefined : Number(minRvol);
  const filterInvalid =
    Number.isNaN(minScoreNum) ||
    minScoreNum < 0 ||
    (minPriceNum != null && Number.isNaN(minPriceNum)) ||
    (maxPriceNum != null && Number.isNaN(maxPriceNum)) ||
    (minRvolNum != null && Number.isNaN(minRvolNum));

  const showBreakoutControls = strategy === "multi_year_breakout" || strategy === "custom";
  const showPullbackControls = strategy === "ath_pullback" || strategy === "custom";
  const isPullbackView = strategy === "ath_pullback";
  const effectiveLookback = strategy === "ath_pullback" ? 0 : lookbackYears;

  const loadMeta = useCallback(async () => {
    const [statsRes, sectorsRes, datesRes] = await Promise.all([
      fetchTimelineStats(),
      fetchTimelineSectors(),
      fetchMybDates(strategy),
    ]);
    setStats(statsRes);
    setSectors(sectorsRes.sectors);
    setScanDates(datesRes.dates);
    setTradeDate((current) => {
      if (current) return current;
      const pick = (iso: string) => clampWeekday(iso, statsRes.min_trade_date, today);
      return pick(datesRes.dates[0] || datesRes.latest_data_date || statsRes.max_trade_date || today);
    });
  }, [today, strategy]);

  useEffect(() => {
    saveUiPrefs(MYB_PREFS_KEY, {
      tradeDate,
      strategy,
      lookbackYears,
      pullbackPct,
      matchMode,
      bandWidthPct,
      trendFilter,
      showAdvancedTrend,
      shortMaPeriod,
      longMaPeriod,
      maType,
      includeMultiYear,
      includeAthPullback,
      statusFilter,
      minScore,
      sector,
      sizeTier,
      fnoGroup,
      fundamentallyStrongOnly,
      minPrice,
      maxPrice,
      minRvol,
    } satisfies MybUiPrefs);
  }, [
    tradeDate, strategy, lookbackYears, pullbackPct, matchMode, bandWidthPct, trendFilter,
    showAdvancedTrend, shortMaPeriod, longMaPeriod, maType, includeMultiYear, includeAthPullback,
    statusFilter, minScore, sector, sizeTier, fnoGroup, fundamentallyStrongOnly, minPrice, maxPrice, minRvol,
  ]);

  const applyClientFilters = useCallback(
    (items: MybSignal[]) => {
      let next = items;
      if (fnoGroup !== "all") {
        next = next.filter((row) => {
          const isFno = fnoSymbolSet.has(row.ticker.toUpperCase());
          return fnoGroup === "fno" ? isFno : !isFno;
        });
      }
      if (fundamentallyStrongOnly) {
        next = next.filter((row) => {
          const fromDetails = fundamentalStrongFromDetails(row.details);
          if (fromDetails != null) return fromDetails;
          return strongSymbolSet.has(row.ticker.toUpperCase());
        });
      }
      return next;
    },
    [fnoGroup, fnoSymbolSet, fundamentallyStrongOnly, strongSymbolSet],
  );

  const fetchResultsPage = useCallback(async () => {
    const base = {
      tradeDate,
      strategy,
      lookbackYears: effectiveLookback,
      status: statusFilter,
      minScore: minScoreNum,
      sector: sector === ALL ? undefined : sector,
      sizeTier,
      trend: showPullbackControls ? trendFilter : undefined,
      minPrice: minPriceNum,
      maxPrice: maxPriceNum,
      minRvol: minRvolNum,
    } as const;

    const needsClientFilter = fnoGroup !== "all" || fundamentallyStrongOnly;
    if (!needsClientFilter) {
      return fetchMybResults({
        ...base,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
    }

    const full = await fetchMybResults({
      ...base,
      limit: 2000,
      offset: 0,
    });
    const filtered = applyClientFilters(full.results);
    const offset = page * PAGE_SIZE;
    return {
      ...full,
      total: filtered.length,
      results: filtered.slice(offset, offset + PAGE_SIZE),
    };
  }, [
    tradeDate,
    strategy,
    effectiveLookback,
    statusFilter,
    minScoreNum,
    sector,
    sizeTier,
    trendFilter,
    showPullbackControls,
    minPriceNum,
    maxPriceNum,
    minRvolNum,
    page,
    fnoGroup,
    fundamentallyStrongOnly,
    applyClientFilters,
  ]);

  const loadResults = useCallback(async () => {
    if (!tradeDate || filterInvalid) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetchResultsPage();
      setRows(res.results);
      setTotal(res.total);
      setScanAlertsCount(res.scan_alerts_count ?? null);
      setHasLoaded(true);
      setSelected((prev) => {
        if (!res.results.length) return null;
        if (prev && res.results.some((r) => r.id === prev.id)) return prev;
        return res.results[0];
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load results");
    } finally {
      setLoading(false);
    }
  }, [tradeDate, filterInvalid, fetchResultsPage]);

  const stopPoll = useCallback(() => {
    if (scanPollRef.current != null) {
      window.clearInterval(scanPollRef.current);
      scanPollRef.current = null;
    }
  }, []);

  const pollStatus = useCallback(async () => {
    const status = await fetchMybStatus();
    setScanStatus(status);

    if (status.batch_dates?.length && status.batch_day_index && status.batch_day_index > 1) {
      const done = status.batch_dates.slice(0, status.batch_day_index - 1);
      setScanDates((prev) => mergeSortedDates(prev, done));
    }

    if (!status.running) {
      stopPoll();
      setScanRunning(false);
      await loadMeta();
      if (status.trade_date) setTradeDate(status.trade_date);
      if (status.strategy && STRATEGIES.some((s) => s.id === status.strategy)) {
        setStrategy(status.strategy as MybStrategy);
      }
      const last = status.last_result;
      if (last && typeof last === "object") {
        const scanned = last.dates_scanned;
        if (Array.isArray(scanned)) {
          setScanDates((prev) =>
            mergeSortedDates(
              prev,
              scanned.filter((d): d is string => typeof d === "string"),
            ),
          );
        }
      }
      setPage(0);
      void loadResults();
    }
  }, [stopPoll, loadMeta, loadResults]);

  const startPoll = useCallback(() => {
    stopPoll();
    void pollStatus();
    scanPollRef.current = window.setInterval(() => {
      void pollStatus();
    }, 1500);
  }, [stopPoll, pollStatus]);

  useEffect(() => {
    loadMeta()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load metadata"))
      .finally(() => setBootLoading(false));
  }, [loadMeta]);

  useEffect(() => {
    fetchFno()
      .then((res) => setFnoSymbols(res.symbols))
      .catch(() => setFnoSymbols([]));
    fetchFundamentallyStrong()
      .then((res) => setStrongSymbols(res.symbols))
      .catch(() => setStrongSymbols([]));
  }, []);

  useEffect(() => {
    fetchMybStatus()
      .then((status) => {
        setScanStatus(status);
        if (status.running) {
          setScanRunning(true);
          startPoll();
        }
      })
      .catch(() => undefined);
    return () => stopPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setPage(0);
    setStatusFilter(ALL);
  }, [strategy]);

  useEffect(() => {
    setPage(0);
  }, [
    tradeDate,
    lookbackYears,
    statusFilter,
    minScore,
    sector,
    sizeTier,
    fnoGroup,
    fundamentallyStrongOnly,
    trendFilter,
    minPrice,
    maxPrice,
    minRvol,
  ]);

  useEffect(() => {
    if (!tradeDate || bootLoading) return;
    void loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    tradeDate,
    strategy,
    effectiveLookback,
    statusFilter,
    minScoreNum,
    sector,
    sizeTier,
    fnoGroup,
    fundamentallyStrongOnly,
    fnoSymbols.length,
    strongSymbols.length,
    trendFilter,
    minPriceNum,
    maxPriceNum,
    minRvolNum,
    page,
    bootLoading,
  ]);

  useEffect(() => {
    if (!selected) {
      setChartHistory([]);
      return;
    }
    let cancelled = false;
    setChartLoading(true);
    fetchTimelineCandles(selected.ticker)
      .then((payload) => {
        if (cancelled) return;
        setChartHistory(payload.history);
        setChartSource(payload.source);
      })
      .catch(() => {
        if (!cancelled) setChartHistory([]);
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.ticker]);

  const startScan = useCallback(
    async (batch: MybBatchMode) => {
      if (!tradeDate || scanRunning) return;
      if (strategy === "custom" && !includeMultiYear && !includeAthPullback) {
        setError("Custom mode needs at least one of Multi-Year or ATH Pullback enabled.");
        return;
      }
      setError(null);
      setScanRunning(true);
      try {
        await runMybScan({
          tradeDate,
          strategy,
          lookbackYears,
          pullbackPct,
          matchMode,
          bandWidthPct,
          // Scan with all trends so UI trend toggle can filter without re-scan
          trendFilter: "all",
          shortMaPeriod,
          longMaPeriod,
          maType,
          includeMultiYear,
          includeAthPullback,
          sector: sector === ALL ? undefined : sector,
          sizeTier,
          minPrice: minPriceNum,
          maxPrice: maxPriceNum,
          minRvol: minRvolNum,
          backgroundRun: true,
          concurrency: 8,
          batch,
        });
        startPoll();
      } catch (err) {
        setScanRunning(false);
        setError(err instanceof Error ? err.message : "Failed to start scan");
      }
    },
    [
      tradeDate,
      scanRunning,
      strategy,
      includeMultiYear,
      includeAthPullback,
      lookbackYears,
      pullbackPct,
      matchMode,
      bandWidthPct,
      shortMaPeriod,
      longMaPeriod,
      maType,
      sector,
      sizeTier,
      minPriceNum,
      maxPriceNum,
      minRvolNum,
      startPoll,
    ],
  );

  const handleRunScan = () => void startScan("single");
  const handleRunScanMonth = () => void startScan("month");
  const handleRunScanLast7 = () => void startScan("last_7");

  const progressPct = useMemo(() => {
    if (!scanStatus?.total) return 0;
    return Math.min(100, Math.round((scanStatus.processed / scanStatus.total) * 100));
  }, [scanStatus]);

  const batchProgressPct = useMemo(() => {
    if (!scanStatus?.batch_day_total) return progressPct;
    const dayIndex = Math.max(0, (scanStatus.batch_day_index ?? 1) - 1);
    const dayFraction = (progressPct || 0) / 100;
    return Math.min(
      100,
      Math.round(((dayIndex + dayFraction) / scanStatus.batch_day_total) * 100),
    );
  }, [scanStatus, progressPct]);

  const activeProgressPct = scanStatus?.batch_day_total ? batchProgressPct : progressPct;

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const noScanYet = hasLoaded && !loading && scanAlertsCount == null && !scanDates.includes(tradeDate);
  const strategyMeta = STRATEGIES.find((s) => s.id === strategy);
  const colSpan = isPullbackView ? 9 : 7;

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const activeFilterCount = [
    statusFilter !== ALL,
    minScore !== DEFAULT_MYB_PREFS.minScore,
    sector !== ALL,
    sizeTier !== "all",
    fnoGroup !== "all",
    fundamentallyStrongOnly,
    Boolean(minPrice.trim()),
    Boolean(maxPrice.trim()),
    Boolean(minRvol.trim()),
  ].filter(Boolean).length;

  const resetFilters = () => {
    setStatusFilter(ALL);
    setMinScore(DEFAULT_MYB_PREFS.minScore);
    setSector(ALL);
    setSizeTier("all");
    setFnoGroup("all");
    setFundamentallyStrongOnly(false);
    setMinPrice("");
    setMaxPrice("");
    setMinRvol("");
  };

  const showProgress = scanRunning && scanStatus;

  return (
    <div className="page-shell flex flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0 py-0 text-data-sm">
          {error}
        </Alert>
      ) : null}

      <PageToolbar
        right={<AdvancedButton onClick={() => setAdvancedOpen(true)} label="Scan options" />}
        below={
          <div className="space-y-1">
            <MultiYearBreakoutFilters
              showBreakoutControls={showBreakoutControls}
              showPullbackControls={showPullbackControls}
              sectors={sectors}
              statusFilter={statusFilter}
              setStatusFilter={setStatusFilter}
              minScore={minScore}
              setMinScore={setMinScore}
              sector={sector}
              setSector={setSector}
              sizeTier={sizeTier}
              setSizeTier={setSizeTier}
              fnoGroup={fnoGroup}
              setFnoGroup={setFnoGroup}
              fundamentallyStrongOnly={fundamentallyStrongOnly}
              setFundamentallyStrongOnly={setFundamentallyStrongOnly}
              minPrice={minPrice}
              setMinPrice={setMinPrice}
              maxPrice={maxPrice}
              setMaxPrice={setMaxPrice}
              minRvol={minRvol}
              setMinRvol={setMinRvol}
              activeCount={activeFilterCount}
              onReset={resetFilters}
            />
            {showProgress ? (
                <div className="flex items-center gap-2 text-data-xs text-slate-300">
                  <span className="shrink-0">
                    {scanStatus.batch_mode === "month"
                      ? "Batch · month"
                      : scanStatus.batch_mode === "last_7"
                        ? "Batch · −7d"
                        : "Scanning"}
                    {scanStatus.batch_day_total ? (
                      <span className="num ml-1 text-slate-100">
                        {scanStatus.batch_day_index}/{scanStatus.batch_day_total}
                      </span>
                    ) : null}
                  </span>
                  <LinearProgress
                    variant="determinate"
                    value={activeProgressPct}
                    className="h-1 min-w-0 flex-1 rounded-full"
                    sx={{ bgcolor: "background.default", borderRadius: 999 }}
                  />
                  <span className="num shrink-0 text-slate-100">{activeProgressPct}%</span>
                </div>
              ) : null}
          </div>
        }
      >
        <ToggleButtonGroup
          exclusive
          value={strategy}
          onChange={(_e, value: MybStrategy | null) => {
            if (value) setStrategy(value);
          }}
          sx={{ flexShrink: 0, "& .MuiToggleButton-root": { textTransform: "none" } }}
        >
          {STRATEGIES.map((s) => (
            <ToggleButton key={s.id} value={s.id} disabled={scanRunning} title={s.blurb}>
              {s.label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        <ToolbarDivider />

        <TimelineDatePicker
          compact
          showLegend={false}
          value={tradeDate}
          onChange={setTradeDate}
          availableDates={
            scanDates.length
              ? scanDates
              : stats
                ? ([stats.max_trade_date].filter(Boolean) as string[])
                : []
          }
          markedDates={scanDates}
          markedLabel="Scan done"
          minDate={stats?.min_trade_date}
          maxDate={today}
          disabled={bootLoading}
        />

        {showBreakoutControls ? (
          <ToggleButtonGroup
            exclusive
            value={lookbackYears}
            onChange={(_e, value: number | null) => {
              if (value) setLookbackYears(value);
            }}
            sx={{ flexShrink: 0 }}
            title="Lookback"
          >
            {[2, 3, 5].map((y) => (
              <ToggleButton key={y} value={y} className="!normal-case">
                {y}Y
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        ) : null}

        {showPullbackControls ? (
          <ToggleButtonGroup
            exclusive
            value={trendFilter}
            onChange={(_e, value: MybTrendFilter | null) => {
              if (value) setTrendFilter(value);
            }}
            sx={{ flexShrink: 0 }}
            title="Trend"
          >
            <ToggleButton value="all" className="!normal-case">Any</ToggleButton>
            <ToggleButton value="uptrend" className="!normal-case">Uptrend</ToggleButton>
            <ToggleButton value="downtrend" className="!normal-case">Downtrend</ToggleButton>
          </ToggleButtonGroup>
        ) : null}

        {showPullbackControls ? (
          <span className="shrink-0 whitespace-nowrap text-data-xs text-slate-300" title="Edit in Advanced">
            Pullback{" "}
            <span className="num text-slate-100">
              {matchMode === "band"
                ? `${pullbackPct}% ± ${bandWidthPct}%`
                : matchMode === "at_most"
                  ? `≤ ${pullbackPct}%`
                  : `≥ ${pullbackPct}%`}
            </span>
          </span>
        ) : null}

        <ToolbarDivider />

        <AppButton
          variant="contained"
          size="small"
          className="shrink-0"
          startIcon={
            <DocumentScannerIcon
              fontSize="small"
              className={scanRunning ? "animate-pulse" : undefined}
            />
          }
          onClick={handleRunScan}
          disabled={scanRunning || bootLoading || !tradeDate}
        >
          {scanRunning && !scanStatus?.batch_mode ? "Scanning…" : "Run scan"}
        </AppButton>
        <AppButton
          variant="outlined"
          size="small"
          className="shrink-0"
          startIcon={
            <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
          }
          onClick={() => void loadResults()}
          disabled={loading || !tradeDate || filterInvalid}
        >
          Load
        </AppButton>
      </PageToolbar>

      <div className="grid min-h-0 flex-1 gap-1 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.9fr)]">
        <section className="panel flex min-h-0 flex-col overflow-hidden">
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-surface-border px-2 py-1">
            <div className="flex min-w-0 items-baseline gap-2">
              <h2 className="shrink-0 text-data-md font-semibold text-slate-100">Results</h2>
              {scanAlertsCount != null ? (
                <span className="truncate text-data-xs tabular-nums text-slate-300">
                  {total.toLocaleString()} shown · {tradeDate}
                </span>
              ) : null}
              {loading ? <span className="shrink-0 text-data-xs text-slate-400">Updating…</span> : null}
            </div>
            <div className="flex shrink-0 items-center gap-1 text-data-xs text-slate-300">
              <button
                type="button"
                disabled={page <= 0 || loading}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="rounded border border-surface-border px-1.5 leading-5 disabled:opacity-40"
                aria-label="Previous page"
              >
                ‹
              </button>
              <span className="tabular-nums">
                {page + 1}/{pageCount}
              </span>
              <button
                type="button"
                disabled={page + 1 >= pageCount || loading}
                onClick={() => setPage((p) => p + 1)}
                className="rounded border border-surface-border px-1.5 leading-5 disabled:opacity-40"
                aria-label="Next page"
              >
                ›
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="dt">
              <thead>
                <tr>
                  <th>Ticker</th>
                  {isPullbackView ? (
                    <>
                      <th className="text-right">LTP</th>
                      <th className="text-right">ATH</th>
                      <th className="text-right">% Below ATH</th>
                      <th>Trend</th>
                      <th className="text-right">vs 200</th>
                      <th className="text-right">vs 50</th>
                      <th className="text-right">RSI</th>
                      <th className="text-right">Score</th>
                    </>
                  ) : (
                    <>
                      <th>Status</th>
                      <th className="text-right">Base yrs</th>
                      <th className="text-right">Resistance</th>
                      <th className="text-right">Vs high</th>
                      <th className="text-right">RVOL</th>
                      <th className="text-right">Score</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {noScanYet ? (
                  <tr>
                    <td colSpan={colSpan} className="py-6 text-center text-slate-300">
                      No scan for {tradeDate} yet. Configure filters and click Run scan.
                    </td>
                  </tr>
                ) : rows.length === 0 && hasLoaded && !loading ? (
                  <tr>
                    <td colSpan={colSpan} className="py-6 text-center text-slate-300">
                      No names matched these filters.
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => {
                    const active = selected?.id === row.id;
                    const drop = row.drop_from_ath_pct;
                    const trend = detailStr(row, "trend");
                    const trendLabel = detailStr(row, "trend_label") || trend || "—";
                    const longPeriod = detailNum(row, "long_period") ?? 200;
                    const shortPeriod = detailNum(row, "short_period") ?? 50;
                    return (
                      <tr
                        key={row.id}
                        onClick={() => setSelected(row)}
                        className={`dt-row ${active ? "dt-selected" : ""}`}
                      >
                        <td className="max-w-[13rem]">
                          <div className="flex items-center gap-1">
                            <span className="ticker">{row.ticker}</span>
                            <FnoStarMark show={fnoSymbolSet.has(row.ticker)} />
                            {(fundamentalStrongFromDetails(row.details) === true ||
                              strongSymbolSet.has(row.ticker.toUpperCase())) && (
                              <span
                                className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1 text-[10px] font-semibold leading-[14px] text-emerald-200"
                                title={FUNDAMENTALLY_STRONG_TOOLTIP}
                              >
                                Strong
                              </span>
                            )}
                          </div>
                          <Clip className="text-data-xs text-slate-400">
                            {row.sector || row.company_name || "—"}
                          </Clip>
                        </td>
                        {isPullbackView ? (
                          <>
                            <td className="text-right text-slate-200">{fmtPrice(row.close_price)}</td>
                            <td className="text-right text-slate-200">
                              <div>{fmtPrice(row.prior_high)}</div>
                              <div className="text-data-xs text-slate-400">{row.prior_high_date || "—"}</div>
                            </td>
                            <td className="num text-right text-loss">{fmtBelowAth(drop)}</td>
                            <td>
                              <span
                                className={`inline-flex rounded border px-1.5 py-px text-[10px] font-medium ${trendTone(
                                  trend,
                                )}`}
                                title={trendLabel}
                              >
                                {trend === "uptrend"
                                  ? "Uptrend"
                                  : trend === "downtrend"
                                    ? "Downtrend"
                                    : "Mixed"}
                              </span>
                            </td>
                            <td className="text-right">
                              <span title={`vs ${longPeriod} MA`}>
                                <PctCell value={detailNum(row, "dist_long_ma_pct")} />
                              </span>
                            </td>
                            <td className="text-right">
                              <span title={`vs ${shortPeriod} MA`}>
                                <PctCell value={detailNum(row, "dist_short_ma_pct")} />
                              </span>
                            </td>
                            <td className="text-right text-slate-200">
                              {row.rsi14 != null ? row.rsi14.toFixed(0) : "—"}
                            </td>
                            <td className="num text-right text-data-md text-slate-100">{row.score.toFixed(0)}</td>
                          </>
                        ) : (
                          <>
                            <td>
                              <span
                                className={`inline-flex rounded border px-1.5 py-px text-[10px] font-medium capitalize ${statusTone(
                                  row.status,
                                )}`}
                              >
                                {row.status}
                              </span>
                            </td>
                            <td className="text-right text-slate-200">
                              {row.years_since_high != null
                                ? row.years_since_high.toFixed(1)
                                : "—"}
                            </td>
                            <td className="text-right text-slate-200">
                              <div>{fmtPrice(row.prior_high)}</div>
                              <div className="text-data-xs text-slate-400">
                                {row.lookback_years ? `${row.lookback_years}Y` : "ATH"} ·{" "}
                                {row.prior_high_date || "—"}
                              </div>
                            </td>
                            <td
                              className={`num text-right ${
                                row.status === "pullback"
                                  ? "text-loss"
                                  : (row.breakout_pct ?? 0) >= 0
                                    ? "text-gain"
                                    : "text-amber-300"
                              }`}
                            >
                              {row.status === "pullback"
                                ? fmtBelowAth(row.drop_from_ath_pct)
                                : fmtPct(row.breakout_pct)}
                            </td>
                            <td className="text-right text-slate-200">
                              {row.rvol20 != null ? row.rvol20.toFixed(2) : "—"}
                            </td>
                            <td className="num text-right text-data-md text-slate-100">{row.score.toFixed(0)}</td>
                          </>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel flex min-h-0 flex-col overflow-hidden">
          {selected ? (
            <>
              <div className="shrink-0 border-b border-surface-border px-2 py-1">
                <div className="flex min-w-0 items-baseline gap-2">
                  <span className="inline-flex shrink-0 items-center gap-1">
                    <span className="ticker">{selected.ticker}</span>
                    <FnoStarMark show={fnoSymbolSet.has(selected.ticker)} />
                  </span>
                  <Clip className="text-data-xs text-slate-400">
                    {selected.company_name || selected.sector || ""}
                  </Clip>
                </div>
                <div className="mt-0.5 text-data-xs text-slate-300">
                  {selected.status === "pullback" || isPullbackView ? (
                    <>
                      ATH {fmtPrice(selected.prior_high)} · LTP {fmtPrice(selected.close_price)} ·{" "}
                      <span className="num text-loss">
                        {fmtBelowAth(selected.drop_from_ath_pct)}
                      </span>{" "}
                      · {detailStr(selected, "trend_label") || "—"} · RSI{" "}
                      {selected.rsi14 != null ? selected.rsi14.toFixed(0) : "—"} · turnover{" "}
                      {fmtCr(selected.avg_turnover_inr)}
                    </>
                  ) : (
                    <>
                      {selected.lookback_years}Y high {fmtPrice(selected.prior_high)} on{" "}
                      {selected.prior_high_date || "—"} · close {fmtPrice(selected.close_price)} (
                      <span className={`num ${pctTone(selected.breakout_pct)}`}>{fmtPct(selected.breakout_pct)}</span>) · RVOL{" "}
                      {selected.rvol20 != null ? selected.rvol20.toFixed(2) : "—"}
                    </>
                  )}
                </div>
              </div>
              <div className="min-h-0 flex-1 p-1">
                <TimelineStockChart
                  symbol={selected.ticker}
                  companyName={selected.company_name}
                  sector={selected.sector}
                  source={chartSource}
                  history={chartHistory}
                  highlightDate={selected.trade_date}
                  highlightMovePct={
                    selected.drop_from_ath_pct != null &&
                    (selected.status === "pullback" || isPullbackView)
                      ? -selected.drop_from_ath_pct
                      : (selected.breakout_pct ?? null)
                  }
                  loading={chartLoading}
                  fillHeight
                  tailVisibleRange
                />
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-data-sm text-slate-400">
              Select a row to view the chart
            </div>
          )}
        </section>
      </div>

      <MultiYearBreakoutAdvanced
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        tradeDate={tradeDate}
        stats={stats}
        strategy={strategy}
        strategyBlurb={strategyMeta?.blurb}
        showBreakoutControls={showBreakoutControls}
        showPullbackControls={showPullbackControls}
        lookbackYears={lookbackYears}
        scanRunning={scanRunning}
        bootLoading={bootLoading}
        onRunScanMonth={handleRunScanMonth}
        onRunScanLast7={handleRunScanLast7}
        scanStatus={scanStatus}
        activeProgressPct={activeProgressPct}
        pullbackPct={pullbackPct}
        setPullbackPct={setPullbackPct}
        matchMode={matchMode}
        setMatchMode={setMatchMode}
        bandWidthPct={bandWidthPct}
        setBandWidthPct={setBandWidthPct}
        showAdvancedTrend={showAdvancedTrend}
        setShowAdvancedTrend={setShowAdvancedTrend}
        maType={maType}
        setMaType={setMaType}
        shortMaPeriod={shortMaPeriod}
        setShortMaPeriod={setShortMaPeriod}
        longMaPeriod={longMaPeriod}
        setLongMaPeriod={setLongMaPeriod}
        includeMultiYear={includeMultiYear}
        setIncludeMultiYear={setIncludeMultiYear}
        includeAthPullback={includeAthPullback}
        setIncludeAthPullback={setIncludeAthPullback}
      />
    </div>
  );
}
