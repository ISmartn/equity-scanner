import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Checkbox from "@mui/material/Checkbox";
import Collapse from "@mui/material/Collapse";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import DocumentScannerIcon from "@mui/icons-material/DocumentScanner";
import RefreshIcon from "@mui/icons-material/Refresh";
import { Star } from "lucide-react";
import { TimelineDataCoverage } from "@/components/TimelineDataCoverage";
import { TimelineDatePicker, FieldLabel } from "@/components/TimelineDatePicker";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { AppButton } from "@/components/mui/AppButton";
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
import {
  FUNDAMENTALLY_STRONG_TOOLTIP,
  fundamentalStrongFromDetails,
} from "@/lib/fundamentalsMeta";

const PAGE_SIZE = 80;
const ALL = "all";
type FnoGroupFilter = "all" | "fno" | "non_fno";

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
  const [stats, setStats] = useState<TimelineStats | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [scanDates, setScanDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState("");

  const [strategy, setStrategy] = useState<MybStrategy>("multi_year_breakout");
  const [lookbackYears, setLookbackYears] = useState(3);
  const [pullbackPct, setPullbackPct] = useState(15);
  const [matchMode, setMatchMode] = useState<MybMatchMode>("at_least");
  const [bandWidthPct, setBandWidthPct] = useState(5);
  const [trendFilter, setTrendFilter] = useState<MybTrendFilter>("all");
  const [showAdvancedTrend, setShowAdvancedTrend] = useState(false);
  const [shortMaPeriod, setShortMaPeriod] = useState(50);
  const [longMaPeriod, setLongMaPeriod] = useState(200);
  const [maType, setMaType] = useState<MybMaType>("sma");
  const [includeMultiYear, setIncludeMultiYear] = useState(true);
  const [includeAthPullback, setIncludeAthPullback] = useState(true);

  const [statusFilter, setStatusFilter] = useState<MybStatus | typeof ALL>(ALL);
  const [minScore, setMinScore] = useState("40");
  const [sector, setSector] = useState(ALL);
  const [sizeTier, setSizeTier] = useState<MybSizeTier>("all");
  const [fnoGroup, setFnoGroup] = useState<FnoGroupFilter>("all");
  const [fnoSymbols, setFnoSymbols] = useState<string[]>([]);
  const fnoSymbolSet = useMemo(() => new Set(fnoSymbols), [fnoSymbols]);
  const [fundamentallyStrongOnly, setFundamentallyStrongOnly] = useState(false);
  const [strongSymbols, setStrongSymbols] = useState<string[]>([]);
  const strongSymbolSet = useMemo(() => new Set(strongSymbols), [strongSymbols]);
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minRvol, setMinRvol] = useState("");
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

  return (
    <div className="mx-auto flex h-[calc(100dvh-6.5rem)] max-w-[1600px] flex-col gap-2 overflow-hidden px-2 py-2 sm:px-4">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0">
          {error}
        </Alert>
      ) : null}

      <div className="shrink-0 overflow-visible rounded-xl border border-surface-border bg-surface-raised px-2 py-1.5">
        <ToggleButtonGroup
          exclusive
          size="small"
          value={strategy}
          onChange={(_e, value: MybStrategy | null) => {
            if (value) setStrategy(value);
          }}
          className="mb-1.5 flex flex-wrap"
          sx={{ "& .MuiToggleButton-root": { textTransform: "none", fontSize: "0.7rem", px: 1.25 } }}
        >
          {STRATEGIES.map((s) => (
            <ToggleButton key={s.id} value={s.id} disabled={scanRunning}>
              {s.label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        <Stack direction="row" spacing={1} useFlexGap className="flex-wrap items-center">
          <TimelineDataCoverage stats={stats} compact />
          <div className="hidden h-5 w-px shrink-0 bg-surface-border sm:block" />
          <Stack spacing={0.25} className="overflow-visible">
            <FieldLabel className="!text-[9px]">Scan date</FieldLabel>
            <TimelineDatePicker
              compact
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
          </Stack>

          {showBreakoutControls ? (
            <Stack spacing={0.25}>
              <FieldLabel className="!text-[9px]">Lookback</FieldLabel>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={lookbackYears}
                onChange={(_e, value: number | null) => {
                  if (value) setLookbackYears(value);
                }}
                sx={{ height: 30 }}
              >
                {[2, 3, 5].map((y) => (
                  <ToggleButton key={y} value={y} className="!px-2 !text-[10px] !normal-case">
                    {y}Y
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Stack>
          ) : null}

          {showPullbackControls ? (
            <>
              <Stack spacing={0.25} className="min-w-[170px] max-w-[240px] flex-1">
                <FieldLabel className="!text-[9px]">
                  Min pullback ≥ {pullbackPct}% from ATH
                </FieldLabel>
                <Slider
                  size="small"
                  value={pullbackPct}
                  min={5}
                  max={90}
                  step={1}
                  valueLabelDisplay="auto"
                  onChange={(_e, v) => setPullbackPct(v as number)}
                  sx={{ py: 0.5 }}
                />
              </Stack>
              <TextField
                select
                size="small"
                label="Match"
                value={matchMode}
                onChange={(e) => setMatchMode(e.target.value as MybMatchMode)}
                sx={{ minWidth: 120, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
                slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
              >
                <MenuItem value="at_least">At least X%</MenuItem>
                <MenuItem value="at_most">At most X%</MenuItem>
                <MenuItem value="band">X% ± band</MenuItem>
              </TextField>
              {matchMode === "band" ? (
                <TextField
                  size="small"
                  label="Band ±%"
                  type="number"
                  value={bandWidthPct}
                  onChange={(e) => setBandWidthPct(Number(e.target.value) || 0)}
                  sx={{ width: 88, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
                  slotProps={{
                    htmlInput: { min: 0, max: 40, step: 1 },
                    inputLabel: { sx: { fontSize: "0.7rem" } },
                  }}
                />
              ) : null}
              <Stack spacing={0.25}>
                <FieldLabel className="!text-[9px]">Trend</FieldLabel>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={trendFilter}
                  onChange={(_e, value: MybTrendFilter | null) => {
                    if (value) setTrendFilter(value);
                  }}
                  sx={{ height: 30 }}
                >
                  <ToggleButton value="all" className="!px-2 !text-[10px] !normal-case">
                    Any
                  </ToggleButton>
                  <ToggleButton value="uptrend" className="!px-2 !text-[10px] !normal-case">
                    Uptrend
                  </ToggleButton>
                  <ToggleButton value="downtrend" className="!px-2 !text-[10px] !normal-case">
                    Downtrend
                  </ToggleButton>
                </ToggleButtonGroup>
              </Stack>
              <AppButton
                size="small"
                variant="text"
                onClick={() => setShowAdvancedTrend((v) => !v)}
              >
                {showAdvancedTrend ? "Hide MA" : "MA settings"}
              </AppButton>
            </>
          ) : null}

          {strategy === "custom" ? (
            <Stack direction="row" spacing={0.5} className="items-center">
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={includeMultiYear}
                    onChange={(e) => setIncludeMultiYear(e.target.checked)}
                  />
                }
                label={<span className="text-[10px] text-slate-300">Multi-year</span>}
              />
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={includeAthPullback}
                    onChange={(e) => setIncludeAthPullback(e.target.checked)}
                  />
                }
                label={<span className="text-[10px] text-slate-300">ATH pullback</span>}
              />
            </Stack>
          ) : null}

          <AppButton
            variant="contained"
            size="small"
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
            size="small"
            className="shrink-0"
            onClick={handleRunScanMonth}
            disabled={scanRunning || bootLoading || !tradeDate}
            title={
              tradeDate
                ? `Scan every weekday in ${tradeDate.slice(0, 7)} through ${tradeDate}`
                : "Scan whole month"
            }
          >
            Month
          </AppButton>
          <AppButton
            size="small"
            className="shrink-0"
            onClick={handleRunScanLast7}
            disabled={scanRunning || bootLoading || !tradeDate}
            title={tradeDate ? `Scan the 7 weekdays before ${tradeDate}` : "Scan last 7 days"}
          >
            −7d
          </AppButton>

          <AppButton
            variant="outlined"
            size="small"
            startIcon={
              <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
            }
            onClick={() => void loadResults()}
            disabled={loading || !tradeDate || filterInvalid}
          >
            Load
          </AppButton>
        </Stack>

        <Collapse in={showPullbackControls && showAdvancedTrend}>
          <Stack
            direction="row"
            spacing={1}
            useFlexGap
            className="mt-1.5 flex-wrap items-center border-t border-surface-border pt-1.5"
          >
            <Typography className="text-[9px] uppercase tracking-wide text-slate-500">
              Trend MAs
            </Typography>
            <TextField
              select
              size="small"
              label="Type"
              value={maType}
              onChange={(e) => setMaType(e.target.value as MybMaType)}
              sx={{ minWidth: 90, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
              slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
            >
              <MenuItem value="sma">SMA</MenuItem>
              <MenuItem value="ema">EMA</MenuItem>
            </TextField>
            <TextField
              size="small"
              label="Short"
              type="number"
              value={shortMaPeriod}
              onChange={(e) => setShortMaPeriod(Number(e.target.value) || 50)}
              sx={{ width: 80, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
              slotProps={{
                htmlInput: { min: 5, max: 100 },
                inputLabel: { sx: { fontSize: "0.7rem" } },
              }}
            />
            <TextField
              size="small"
              label="Long"
              type="number"
              value={longMaPeriod}
              onChange={(e) => setLongMaPeriod(Number(e.target.value) || 200)}
              sx={{ width: 80, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
              slotProps={{
                htmlInput: { min: 20, max: 300 },
                inputLabel: { sx: { fontSize: "0.7rem" } },
              }}
            />
            <Typography className="text-[9px] text-slate-500">
              Uptrend = price &gt; {longMaPeriod} {maType.toUpperCase()}, short &gt; long, RSI ≥ 45.
              Downtrend = opposite stack, RSI ≤ 50. Re-run scan after changing MAs.
            </Typography>
          </Stack>
        </Collapse>

        <Stack
          direction="row"
          spacing={1}
          useFlexGap
          className="mt-1.5 flex-wrap items-center border-t border-surface-border pt-1.5"
        >
          <Typography className="text-[9px] uppercase tracking-wide text-slate-500">
            Global
          </Typography>
          <TextField
            select
            size="small"
            label="Size"
            value={sizeTier}
            onChange={(e) => setSizeTier(e.target.value as MybSizeTier)}
            sx={{ minWidth: 100, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          >
            <MenuItem value="all">All sizes</MenuItem>
            <MenuItem value="large">Large (≥₹50Cr)</MenuItem>
            <MenuItem value="mid">Mid (≥₹10Cr)</MenuItem>
            <MenuItem value="small">Small (≥₹5Cr)</MenuItem>
          </TextField>
          <TextField
            select
            size="small"
            label="Sector"
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            sx={{ minWidth: 140, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          >
            <MenuItem value={ALL}>All sectors</MenuItem>
            {sectors.map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Listing"
            value={fnoGroup}
            onChange={(e) => setFnoGroup(e.target.value as FnoGroupFilter)}
            sx={{ minWidth: 120, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          >
            <MenuItem value="all">All</MenuItem>
            <MenuItem value="fno">F&O ★</MenuItem>
            <MenuItem value="non_fno">Non-F&O</MenuItem>
          </TextField>
          <FormControlLabel
            className="!mr-0"
            control={
              <Checkbox
                size="small"
                checked={fundamentallyStrongOnly}
                onChange={(e) => setFundamentallyStrongOnly(e.target.checked)}
              />
            }
            label={
              <span className="text-[10px] text-slate-300" title={FUNDAMENTALLY_STRONG_TOOLTIP}>
                Strong Fund
              </span>
            }
          />
          <TextField
            size="small"
            label="Min ₹"
            value={minPrice}
            onChange={(e) => setMinPrice(e.target.value)}
            sx={{ width: 80, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          />
          <TextField
            size="small"
            label="Max ₹"
            value={maxPrice}
            onChange={(e) => setMaxPrice(e.target.value)}
            sx={{ width: 80, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          />
          <TextField
            size="small"
            label="Min RVOL"
            value={minRvol}
            onChange={(e) => setMinRvol(e.target.value)}
            sx={{ width: 88, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          />
          <TextField
            select
            size="small"
            label="Status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as MybStatus | typeof ALL)}
            sx={{ minWidth: 110, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          >
            <MenuItem value={ALL}>All</MenuItem>
            {showBreakoutControls ? (
              <>
                <MenuItem value="breakout">Breakout</MenuItem>
                <MenuItem value="near">Near</MenuItem>
              </>
            ) : null}
            {showPullbackControls ? <MenuItem value="pullback">Pullback</MenuItem> : null}
          </TextField>
          <TextField
            size="small"
            label="Min score"
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
            sx={{ width: 88, "& .MuiInputBase-root": { fontSize: "0.75rem", height: 30 } }}
            slotProps={{ inputLabel: { sx: { fontSize: "0.7rem" } } }}
          />
        </Stack>

        <Typography variant="caption" className="mt-1 block text-[9px] text-slate-500">
          {strategyMeta?.blurb}{" "}
          {showPullbackControls
            ? `Condition: % pullback = (ATH − LTP) / ATH × 100 ${
                matchMode === "band"
                  ? `∈ ${pullbackPct}% ± ${bandWidthPct}%`
                  : matchMode === "at_most"
                    ? `≤ ${pullbackPct}%`
                    : `≥ ${pullbackPct}%`
              }. Trend filter updates the table without re-scan; change min pullback / MAs then Run scan.`
            : showBreakoutControls
              ? `Close vs prior ${lookbackYears}Y high (fresh = Breakout; within 3% below = Near).`
              : null}{" "}
          Size tiers use 20d avg turnover. Listing filter uses the NSE F&O universe (★ = F&O).
          Strong Fund: {FUNDAMENTALLY_STRONG_TOOLTIP}.
        </Typography>

        {scanRunning && scanStatus ? (
          <div className="mt-1.5 space-y-1 border-t border-surface-border pt-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2 text-[9px] text-slate-400">
              <span>
                {scanStatus.batch_mode === "month"
                  ? "Batch · month"
                  : scanStatus.batch_mode === "last_7"
                    ? "Batch · −7d"
                    : "Scanning"}
                {scanStatus.batch_day_total ? (
                  <>
                    {" · "}
                    <span className="font-medium text-slate-200">
                      {scanStatus.batch_day_index}/{scanStatus.batch_day_total}
                    </span>
                  </>
                ) : null}
                {scanStatus.strategy ? (
                  <>
                    {" · "}
                    <span className="font-medium text-slate-200">{scanStatus.strategy}</span>
                  </>
                ) : null}
                {scanStatus.trade_date ? (
                  <>
                    {" · "}
                    <span className="font-medium text-slate-200">{scanStatus.trade_date}</span>
                  </>
                ) : null}
                {scanStatus.current_ticker ? (
                  <>
                    {" · "}
                    <span className="font-medium text-slate-200">{scanStatus.current_ticker}</span>
                  </>
                ) : null}
              </span>
              <span className="tabular-nums">
                {scanStatus.processed.toLocaleString()}/{scanStatus.total.toLocaleString()}
                {scanStatus.total > 0 ? ` (${activeProgressPct}%)` : ""}
                {" · "}
                {scanStatus.alerts_count.toLocaleString()} alerts
              </span>
            </div>
            <LinearProgress
              variant="determinate"
              value={activeProgressPct}
              className="h-1 rounded-full"
              sx={{ bgcolor: "background.default", borderRadius: 999 }}
            />
          </div>
        ) : null}
      </div>

      <div className="grid min-h-0 flex-1 gap-2 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.9fr)]">
        <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
          <div className="flex items-center justify-between border-b border-surface-border px-2 py-1.5">
            <Typography className="text-[11px] font-medium text-slate-200">
              Results
              {scanAlertsCount != null ? (
                <span className="ml-1 text-slate-500">({total.toLocaleString()} shown)</span>
              ) : null}
              {loading ? <span className="ml-2 text-[9px] text-slate-500">Updating…</span> : null}
            </Typography>
            <div className="flex items-center gap-1">
              <AppButton
                size="small"
                disabled={page <= 0 || loading}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                Prev
              </AppButton>
              <span className="px-1 text-[10px] tabular-nums text-slate-400">
                {page + 1}/{pageCount}
              </span>
              <AppButton
                size="small"
                disabled={page + 1 >= pageCount || loading}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </AppButton>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse text-left text-[11px]">
              <thead className="sticky top-0 z-10 bg-surface-raised text-[9px] uppercase tracking-wide text-slate-500">
                <tr className="border-b border-surface-border">
                  <th className="px-2 py-2">Ticker</th>
                  {isPullbackView ? (
                    <>
                      <th className="px-2 py-2 text-right">LTP</th>
                      <th className="px-2 py-2 text-right">ATH</th>
                      <th className="px-2 py-2 text-right">% Below ATH</th>
                      <th className="px-2 py-2">Trend</th>
                      <th className="px-2 py-2 text-right">vs 200</th>
                      <th className="px-2 py-2 text-right">vs 50</th>
                      <th className="px-2 py-2 text-right">RSI</th>
                      <th className="px-2 py-2 text-right">Score</th>
                    </>
                  ) : (
                    <>
                      <th className="px-2 py-2">Status</th>
                      <th className="px-2 py-2 text-right">Base yrs</th>
                      <th className="px-2 py-2 text-right">Resistance</th>
                      <th className="px-2 py-2 text-right">Vs high</th>
                      <th className="px-2 py-2 text-right">RVOL</th>
                      <th className="px-2 py-2 text-right">Score</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {noScanYet ? (
                  <tr>
                    <td colSpan={colSpan} className="px-3 py-8 text-center text-slate-500">
                      No scan for {tradeDate} yet. Configure filters and click Run scan.
                    </td>
                  </tr>
                ) : rows.length === 0 && hasLoaded && !loading ? (
                  <tr>
                    <td colSpan={colSpan} className="px-3 py-8 text-center text-slate-500">
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
                        className={`cursor-pointer border-b border-surface-border/70 hover:bg-white/5 ${
                          active ? "bg-white/10" : ""
                        }`}
                      >
                        <td className="px-2 py-1.5">
                          <div className="flex items-center gap-1">
                            <div className="font-medium text-slate-100">{row.ticker}</div>
                            <FnoStarMark show={fnoSymbolSet.has(row.ticker)} />
                            {(fundamentalStrongFromDetails(row.details) === true ||
                              strongSymbolSet.has(row.ticker.toUpperCase())) && (
                              <span
                                className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1 py-px text-[8px] font-medium text-emerald-300"
                                title={FUNDAMENTALLY_STRONG_TOOLTIP}
                              >
                                Strong
                              </span>
                            )}
                          </div>
                          <div className="text-[9px] text-slate-500">
                            {row.sector || row.company_name || "—"}
                          </div>
                        </td>
                        {isPullbackView ? (
                          <>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              {fmtPrice(row.close_price)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              <div>{fmtPrice(row.prior_high)}</div>
                              <div className="text-[9px] text-slate-500">
                                {row.prior_high_date || "—"}
                              </div>
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums font-semibold text-rose-300">
                              {fmtBelowAth(drop)}
                            </td>
                            <td className="px-2 py-1.5">
                              <span
                                className={`inline-flex max-w-[140px] truncate rounded border px-1.5 py-0.5 text-[9px] font-medium ${trendTone(
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
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              <span title={`vs ${longPeriod} MA`}>
                                {fmtPct(detailNum(row, "dist_long_ma_pct"))}
                              </span>
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              <span title={`vs ${shortPeriod} MA`}>
                                {fmtPct(detailNum(row, "dist_short_ma_pct"))}
                              </span>
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              {row.rsi14 != null ? row.rsi14.toFixed(0) : "—"}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums font-medium text-slate-100">
                              {row.score.toFixed(0)}
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="px-2 py-1.5">
                              <span
                                className={`inline-flex rounded border px-1.5 py-0.5 text-[9px] font-medium capitalize ${statusTone(
                                  row.status,
                                )}`}
                              >
                                {row.status}
                              </span>
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              {row.years_since_high != null
                                ? row.years_since_high.toFixed(1)
                                : "—"}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              <div>{fmtPrice(row.prior_high)}</div>
                              <div className="text-[9px] text-slate-500">
                                {row.lookback_years ? `${row.lookback_years}Y` : "ATH"} ·{" "}
                                {row.prior_high_date || "—"}
                              </div>
                            </td>
                            <td
                              className={`px-2 py-1.5 text-right tabular-nums ${
                                row.status === "pullback"
                                  ? "text-rose-300"
                                  : (row.breakout_pct ?? 0) >= 0
                                    ? "text-emerald-300"
                                    : "text-amber-300"
                              }`}
                            >
                              {row.status === "pullback"
                                ? fmtBelowAth(row.drop_from_ath_pct)
                                : fmtPct(row.breakout_pct)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                              {row.rvol20 != null ? row.rvol20.toFixed(2) : "—"}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums font-medium text-slate-100">
                              {row.score.toFixed(0)}
                            </td>
                          </>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
          {selected ? (
            <>
              <div className="border-b border-surface-border px-3 py-2">
                <Typography className="text-[12px] font-medium text-slate-100">
                  <span className="inline-flex items-center gap-1">
                    {selected.ticker}
                    <FnoStarMark show={fnoSymbolSet.has(selected.ticker)} />
                  </span>
                  <span className="ml-2 text-[10px] font-normal text-slate-500">
                    {selected.company_name || selected.sector || ""}
                  </span>
                </Typography>
                <Typography className="mt-0.5 text-[10px] text-slate-400">
                  {selected.status === "pullback" || isPullbackView ? (
                    <>
                      ATH {fmtPrice(selected.prior_high)} · LTP {fmtPrice(selected.close_price)} ·{" "}
                      <span className="font-medium text-rose-300">
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
                      {fmtPct(selected.breakout_pct)}) · RVOL{" "}
                      {selected.rvol20 != null ? selected.rvol20.toFixed(2) : "—"}
                    </>
                  )}
                </Typography>
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
            <div className="flex flex-1 items-center justify-center text-[11px] text-slate-500">
              Select a row to view the chart
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
