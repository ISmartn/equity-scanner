import { TimelineDatePicker } from "@/components/TimelineDatePicker";
import { TimelineDataCoverage } from "@/components/TimelineDataCoverage";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { CompanyNewsSidebar } from "@/components/news/CompanyNewsSidebar";
import { StockFundamentalsPanel } from "@/components/StockFundamentalsPanel";
import { AppButton } from "@/components/mui";
import {
  fetchScannerDates,
  fetchScannerResults,
  fetchScannerStatus,
  ensureScannerDerivatives,
  fetchFno,
  fetchFundamentallyStrong,
  fetchStockFundamentals,
  fetchTimelineCandles,
  fetchTimelineSectors,
  fetchTimelineStats,
  runScanner,
  syncStockFundamentals,
  type ScannerBatchMode,
  type ScannerPatternId,
  type ScannerPatternSignal,
  type ScannerScanMode,
  type StockFundamentals,
  type TimelineCandlePoint,
} from "@/lib/api";
import { clampWeekday, localTodayIso, nearestWeekday } from "@/lib/dates";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";
import RefreshIcon from "@mui/icons-material/Refresh";
import DocumentScannerIcon from "@mui/icons-material/DocumentScanner";
import Alert from "@mui/material/Alert";
import Checkbox from "@mui/material/Checkbox";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import InputLabel from "@mui/material/InputLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  copyTextToClipboard,
  describeScannerWhy,
  EARLY_SETUP_PATTERNS,
  fundamentalPassFromRow,
  foOverlayTone,
  formatSignalMovePct,
  pre20dReturnFromRow,
  SCANNER_PATTERN_LABELS,
  scannerToExportJson,
  signalDayMovePct,
  signalStatus,
  statusLabel,
  timingClassFromRow,
  timingClassLabel,
  type ScannerSignalStatus,
  type TimingClass,
} from "@/lib/scannerExport";
import { extractProfileMarketCap, extractProfileSector, FUNDAMENTALLY_STRONG_TOOLTIP, fundamentalStrongFromDetails } from "@/lib/fundamentalsMeta";
import { computeVcpOverlay } from "@/lib/vcpOverlay";
import {
  AlertTriangle,
  ClipboardCopy,
  Layers,
  Newspaper,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Star,
  TrendingUp,
} from "lucide-react";

const PAGE_SIZE = 80;
const ALL_FILTER = "all";
type FnoGroupFilter = "all" | "fno" | "non_fno";

const SCANNER_PREFS_KEY = "trading.scanner.prefs";
type ScannerUiPrefs = {
  tradeDate: string;
  scanMode: ScannerScanMode;
  pattern: string;
  sector: string;
  fnoGroup: FnoGroupFilter;
  minScore: string;
  triggeredOnly: boolean;
  setupOnly: boolean;
  macroPassOnly: boolean;
  fundamentalPassOnly: boolean;
  fundamentallyStrongOnly: boolean;
};
const DEFAULT_SCANNER_PREFS: ScannerUiPrefs = {
  tradeDate: "",
  scanMode: "confirmation",
  pattern: ALL_FILTER,
  sector: ALL_FILTER,
  fnoGroup: "all",
  minScore: "70",
  triggeredOnly: false,
  setupOnly: false,
  macroPassOnly: false,
  fundamentalPassOnly: false,
  fundamentallyStrongOnly: false,
};

function mergeSortedDates(existing: string[], additions: string[]): string[] {
  if (!additions.length) return existing;
  return [...new Set([...existing, ...additions.filter(Boolean)])].sort((a, b) =>
    b.localeCompare(a),
  );
}

function scanDatesFromStatus(status: Awaited<ReturnType<typeof fetchScannerStatus>>): string[] {
  const dates: string[] = [];

  if (!status.running) {
    if (status.trade_date) dates.push(status.trade_date);

    const result = status.last_result;
    if (result && typeof result === "object") {
      const tradeDate = result.trade_date;
      if (typeof tradeDate === "string") dates.push(tradeDate);
      const batchDates = result.dates_scanned;
      if (Array.isArray(batchDates)) {
        dates.push(...batchDates.filter((d): d is string => typeof d === "string"));
      }
    }
    return dates;
  }

  if (status.batch_dates?.length && status.batch_day_index && status.batch_day_index > 1) {
    dates.push(...status.batch_dates.slice(0, status.batch_day_index - 1));
  }

  return dates;
}

/** Short labels for filter dropdown only */
const PATTERN_FILTER_LABELS: Record<ScannerPatternId, string> = {
  vcp: "VCP",
  high_tight_flag: "HTF",
  pocket_pivot: "Pocket Pivot",
  pocket_pivot_setup: "PP Setup",
  inside_bar_cluster: "Inside Bar",
  power_gap: "Power Gap",
  tight_range_near_pivot: "Tight Range",
  darvas_pre_setup: "Darvas Setup",
};

function formatScore(value: number): string {
  return value.toFixed(1);
}

function FnoStarMark({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span title="F&O stock" aria-label="F&O stock">
      <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400" aria-hidden />
    </span>
  );
}

function StatusBadge({ status }: { status: ScannerSignalStatus }) {
  const tone =
    status === "trigger"
      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
      : status === "setup"
        ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
        : "border-slate-500/40 bg-slate-500/10 text-slate-400";
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[9px] font-medium ${tone}`}>
      {statusLabel(status)}
    </span>
  );
}

function TimingBadge({ timing }: { timing: TimingClass | null }) {
  if (!timing) {
    return <span className="text-[9px] text-slate-600">—</span>;
  }
  const tone =
    timing === "early"
      ? "border-sky-500/40 bg-sky-500/15 text-sky-300"
      : timing === "extended"
        ? "border-red-500/40 bg-red-500/15 text-red-300"
        : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[9px] font-medium ${tone}`}>
      {timingClassLabel(timing)}
    </span>
  );
}

function GatePill({
  kind,
  pass,
  stateOverride,
  titleOverride,
}: {
  kind: "macro" | "fund" | "fo";
  pass: boolean | null;
  stateOverride?: string;
  titleOverride?: string;
}) {
  const short = kind === "macro" ? "Macro" : kind === "fund" ? "Fund" : "FO";
  const state =
    stateOverride ??
    (kind === "fo" && pass === false ? "warn" : pass === true ? "pass" : pass === false ? "fail" : "n/a");
  const title =
    titleOverride ??
    (kind === "macro"
      ? pass === true
        ? "Minervini trend template met (price > SMA50 > SMA150 > SMA200, 52w position OK)"
        : pass === false
          ? "Macro trend template not met — Stage-2 uptrend criteria failed"
          : "Macro trend not evaluated"
      : kind === "fund"
        ? pass === true
          ? "Fundamentals pass — ROE ≥ 15% and ROCE ≥ 12% (when available)"
          : pass === false
            ? "Fundamentals fail — below ROE/ROCE thresholds"
            : "Fundamentals not cached or ratios missing"
        : pass === true
          ? "F&O confirms — long build-up (price ↑, option OI ↑) or supportive PCR shift"
          : pass === false
            ? "F&O caution — short covering or fragile OI structure"
            : "F&O overlay n/a — sync derivative snapshots (--all-fno) for this symbol");
  const tone =
    kind === "fo" && state === "neutral"
      ? "border-sky-500/30 bg-sky-500/10 text-sky-300"
      : kind === "fo" && pass === false
      ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
      : pass === true
        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
        : pass === false
          ? "border-red-500/30 bg-red-500/10 text-red-300"
          : "border-surface-border bg-surface/50 text-slate-500";
  return (
    <span
      className={`inline-block rounded border px-1 py-px text-[8px] leading-tight ${tone}`}
      title={title}
    >
      {short} {state}
    </span>
  );
}

function needsFoDerivativeSync(row: ScannerPatternSignal): boolean {
  const fo = row.details?.fo_overlay as Record<string, unknown> | undefined;
  if (!fo) return true;
  return fo.available !== true && fo.reason === "no_derivative_snapshot";
}

function foGateDisplay(row: ScannerPatternSignal): {
  pass: boolean | null;
  state: string;
  title: string;
} {
  const fo = row.details?.fo_overlay as Record<string, unknown> | undefined;
  if (!fo || fo.available !== true) {
    return {
      pass: null,
      state: "n/a",
      title:
        fo?.reason === "no_derivative_snapshot"
          ? "No option-chain snapshot for this date — auto-sync on load or run market-info sync"
          : "F&O overlay n/a — derivative data not loaded for this symbol/date",
    };
  }
  if (fo.would_reject === true) {
    return {
      pass: false,
      state: "warn",
      title: "F&O short build-up — would reject on fresh scan",
    };
  }
  const tone = foOverlayTone(row);
  if (tone === "confirm") {
    return {
      pass: true,
      state: "pass",
      title: "F&O confirms — long build-up (price ↑, option OI ↑) or supportive PCR shift",
    };
  }
  if (tone === "caution") {
    return {
      pass: false,
      state: "warn",
      title: "F&O caution — short covering or fragile OI structure",
    };
  }
  return {
    pass: null,
    state: "neutral",
    title: "F&O data loaded — neutral OI/price mix (no strong institutional signal)",
  };
}

function MoveCell({ value }: { value: number | null }) {
  if (value == null || Number.isNaN(value)) {
    return <span className="text-slate-500">—</span>;
  }
  const tone = value >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <span className={`tabular-nums font-medium ${tone}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

export function MomentumScannerPage() {
  const initialPrefs = loadUiPrefs(SCANNER_PREFS_KEY, DEFAULT_SCANNER_PREFS);
  const [stats, setStats] = useState<Awaited<ReturnType<typeof fetchTimelineStats>> | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [scanDates, setScanDates] = useState<string[]>([]);
  const [refinedScanDates, setRefinedScanDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState(initialPrefs.tradeDate);
  const [scanMode, setScanMode] = useState<ScannerScanMode>(
    initialPrefs.scanMode === "early_setup" ? "early_setup" : "confirmation",
  );
  const [pattern, setPattern] = useState<ScannerPatternId | typeof ALL_FILTER>(
    (initialPrefs.pattern as ScannerPatternId | typeof ALL_FILTER) || ALL_FILTER,
  );
  const [sector, setSector] = useState(initialPrefs.sector || ALL_FILTER);
  const [fnoGroup, setFnoGroup] = useState<FnoGroupFilter>(
    initialPrefs.fnoGroup === "fno" || initialPrefs.fnoGroup === "non_fno"
      ? initialPrefs.fnoGroup
      : "all",
  );
  const [minScore, setMinScore] = useState(initialPrefs.minScore || "70");
  const [triggeredOnly, setTriggeredOnly] = useState(Boolean(initialPrefs.triggeredOnly));
  const [setupOnly, setSetupOnly] = useState(Boolean(initialPrefs.setupOnly));
  const [macroPassOnly, setMacroPassOnly] = useState(Boolean(initialPrefs.macroPassOnly));
  const [fundamentalPassOnly, setFundamentalPassOnly] = useState(
    Boolean(initialPrefs.fundamentalPassOnly),
  );
  const [fundamentallyStrongOnly, setFundamentallyStrongOnly] = useState(
    Boolean(initialPrefs.fundamentallyStrongOnly),
  );
  const [strongSymbols, setStrongSymbols] = useState<string[]>([]);
  const strongSymbolSet = useMemo(() => new Set(strongSymbols), [strongSymbols]);
  const [page, setPage] = useState(0);

  const [rows, setRows] = useState<ScannerPatternSignal[]>([]);
  const [exportRows, setExportRows] = useState<ScannerPatternSignal[]>([]);
  const [total, setTotal] = useState(0);
  const [scanAlertsCount, setScanAlertsCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [copyingJson, setCopyingJson] = useState(false);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [exportJsonOpen, setExportJsonOpen] = useState(false);

  const [selectedRow, setSelectedRow] = useState<ScannerPatternSignal | null>(null);
  const [chartHistory, setChartHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [foSyncing, setFoSyncing] = useState(false);
  const [foSyncNote, setFoSyncNote] = useState<string | null>(null);

  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [fundamentalsLoading, setFundamentalsLoading] = useState(false);
  const [fundamentalsError, setFundamentalsError] = useState<string | null>(null);
  const [fundamentalsSyncing, setFundamentalsSyncing] = useState(false);
  const [showFundamentals, setShowFundamentals] = useState(() => {
    try {
      return localStorage.getItem("trading.showFundamentals") !== "false";
    } catch {
      return true;
    }
  });
  const [showCompanyNews, setShowCompanyNews] = useState(() => {
    try {
      return localStorage.getItem("trading.showCompanyNews") !== "false";
    } catch {
      return true;
    }
  });
  const [fnoSymbols, setFnoSymbols] = useState<string[]>([]);
  const fnoSymbolSet = useMemo(() => new Set(fnoSymbols), [fnoSymbols]);

  const toggleFundamentals = useCallback(() => {
    setShowFundamentals((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("trading.showFundamentals", String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const toggleCompanyNews = useCallback(() => {
    setShowCompanyNews((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("trading.showCompanyNews", String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const [showVcpOverlay, setShowVcpOverlay] = useState(() => {
    try {
      return localStorage.getItem("trading.scannerVcpOverlay") !== "false";
    } catch {
      return true;
    }
  });

  const toggleVcpOverlay = useCallback(() => {
    setShowVcpOverlay((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("trading.scannerVcpOverlay", String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const [scanRunning, setScanRunning] = useState(false);
  const [scanStatus, setScanStatus] = useState<Awaited<ReturnType<typeof fetchScannerStatus>> | null>(null);
  const scanPollRef = useRef<number | null>(null);
  const loadRequestRef = useRef(0);

  const today = nearestWeekday(localTodayIso());
  const minScoreNum = parseFloat(minScore);
  const filterInvalid = Number.isNaN(minScoreNum) || minScoreNum < 0;
  const earlySetupMode = scanMode === "early_setup";
  const filtersActive =
    earlySetupMode ||
    pattern !== ALL_FILTER ||
    sector !== ALL_FILTER ||
    fnoGroup !== "all" ||
    minScoreNum > 0 ||
    triggeredOnly ||
    setupOnly ||
    macroPassOnly ||
    fundamentalPassOnly ||
    fundamentallyStrongOnly;

  const resultsQuery = useMemo(() => {
    const shared = {
      tradeDate,
      sector: sector === ALL_FILTER ? undefined : sector,
      macroPassOnly,
      fundamentalPassOnly,
    };
    if (earlySetupMode) {
      return {
        ...shared,
        minScore: 75,
        setupOnly: true,
        triggeredOnly: false,
        patterns: EARLY_SETUP_PATTERNS,
        maxPre20dReturn: 20,
        maxSignalDayReturn: 2,
        sort: "setup_first" as const,
      };
    }
    return {
      ...shared,
      minScore: minScoreNum,
      setupOnly,
      triggeredOnly,
      pattern: pattern === ALL_FILTER ? undefined : pattern,
      sort: "score" as const,
    };
  }, [
    tradeDate,
    sector,
    macroPassOnly,
    fundamentalPassOnly,
    earlySetupMode,
    minScoreNum,
    setupOnly,
    triggeredOnly,
    pattern,
  ]);

  const loadMeta = useCallback(async () => {
    const [statsRes, sectorsRes, datesRes] = await Promise.all([
      fetchTimelineStats(),
      fetchTimelineSectors(),
      fetchScannerDates(),
    ]);
    setStats(statsRes);
    setSectors(sectorsRes.sectors);
    setScanDates(datesRes.dates);
    setRefinedScanDates(datesRes.refined_dates ?? []);
    setTradeDate((current) => {
      if (current) return current;
      const pick = (iso: string) => clampWeekday(iso, statsRes.min_trade_date, today);
      const defaultDate =
        datesRes.latest_with_alerts ||
        datesRes.dates[0] ||
        statsRes.max_trade_date ||
        today;
      return pick(defaultDate);
    });
  }, [today]);

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

  const ensureFoDerivatives = useCallback(
    async (tickers: string[], asOfDate: string): Promise<boolean> => {
      const unique = [...new Set(tickers.map((t) => t.toUpperCase()))].filter((t) =>
        fnoSymbolSet.has(t),
      );
      if (!unique.length) return false;
      setFoSyncing(true);
      setFoSyncNote(null);
      try {
        const result = await ensureScannerDerivatives({
          tradeDate: asOfDate,
          tickers: unique,
        });
        if (result.synced.length > 0) {
          setFoSyncNote(`Fetched F&O data for ${result.synced.join(", ")}`);
          return true;
        }
        if (result.failed.length > 0) {
          setFoSyncNote(`F&O sync failed for ${result.failed.map((f) => f.symbol).join(", ")}`);
        }
        return false;
      } catch (err) {
        setFoSyncNote(
          err instanceof Error ? err.message : "Could not fetch F&O derivative data",
        );
        return false;
      } finally {
        setFoSyncing(false);
      }
    },
    [fnoSymbolSet],
  );

  const loadChart = useCallback(async (row: ScannerPatternSignal) => {
    let activeRow = row;
    if (fnoSymbolSet.has(row.ticker) && needsFoDerivativeSync(row)) {
      const synced = await ensureFoDerivatives([row.ticker], row.trade_date);
      if (synced) {
        try {
          const refreshed = await fetchScannerResults({
            ...resultsQuery,
            limit: PAGE_SIZE,
            offset: page * PAGE_SIZE,
          });
          setRows(refreshed.results);
          activeRow =
            refreshed.results.find(
              (r) => r.ticker === row.ticker && r.pattern_type === row.pattern_type,
            ) ?? row;
        } catch {
          /* keep original row */
        }
      }
    }
    setSelectedRow(activeRow);
    setChartLoading(true);
    setChartError(null);
    setFundamentals(null);
    setFundamentalsError(null);
    try {
      const payload = await fetchTimelineCandles(activeRow.ticker);
      setChartHistory(payload.history);
      setChartSource(payload.source);
    } catch (err) {
      setChartHistory([]);
      setChartError(err instanceof Error ? err.message : `No chart data for ${activeRow.ticker}`);
    } finally {
      setChartLoading(false);
    }
    void loadFundamentals(activeRow.ticker);
  }, [
    loadFundamentals,
    fnoSymbolSet,
    ensureFoDerivatives,
    resultsQuery,
    page,
  ]);

  const applyClientFilters = useCallback(
    (items: ScannerPatternSignal[]) => {
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

  const fetchResultsPage = useCallback(async (pageOverride?: number) => {
    const activePage = pageOverride ?? page;
    const needsClientFilter = fnoGroup !== "all" || fundamentallyStrongOnly;
    if (!needsClientFilter) {
      return fetchScannerResults({
        ...resultsQuery,
        limit: PAGE_SIZE,
        offset: activePage * PAGE_SIZE,
      });
    }
    // F&O / strong membership is known client-side — fetch a wide window then filter/paginate.
    const full = await fetchScannerResults({
      ...resultsQuery,
      limit: 2000,
      offset: 0,
    });
    const filtered = applyClientFilters(full.results);
    const offset = activePage * PAGE_SIZE;
    return {
      ...full,
      total: filtered.length,
      results: filtered.slice(offset, offset + PAGE_SIZE),
    };
  }, [resultsQuery, page, fnoGroup, fundamentallyStrongOnly, applyClientFilters]);

  const handleSyncFundamentals = useCallback(async () => {
    if (!selectedRow) return;
    setFundamentalsSyncing(true);
    setFundamentalsError(null);
    try {
      await syncStockFundamentals([selectedRow.ticker], true);
      await loadFundamentals(selectedRow.ticker);
    } catch (err) {
      setFundamentalsError(err instanceof Error ? err.message : "Fundamentals sync failed");
    } finally {
      setFundamentalsSyncing(false);
    }
  }, [selectedRow, loadFundamentals]);

  const loadResults = useCallback(async (pageOverride?: number) => {
    if (!tradeDate || filterInvalid) return;
    const requestId = ++loadRequestRef.current;
    const activePage = pageOverride ?? page;
    setLoading(true);
    setError(null);
    setCopyMessage(null);
    try {
      let result = await fetchResultsPage(pageOverride);
      if (requestId !== loadRequestRef.current) return;

      setHasLoaded(true);
      setRows(result.results);
      setTotal(result.total);
      setScanAlertsCount(result.scan_alerts_count ?? null);

      const fnoNeedingSync = result.results
        .filter((r) => fnoSymbolSet.has(r.ticker) && needsFoDerivativeSync(r))
        .map((r) => r.ticker);
      if (fnoNeedingSync.length > 0) {
        const synced = await ensureFoDerivatives(fnoNeedingSync, tradeDate);
        if (requestId !== loadRequestRef.current) return;
        if (synced) {
          result = await fetchResultsPage(pageOverride);
          if (requestId !== loadRequestRef.current) return;
          setRows(result.results);
          setTotal(result.total);
          setScanAlertsCount(result.scan_alerts_count ?? null);
        }
      }

      if (fnoGroup !== "all" || fundamentallyStrongOnly) {
        const full = await fetchScannerResults({
          ...resultsQuery,
          limit: 2000,
          offset: 0,
        });
        if (requestId !== loadRequestRef.current) return;
        setExportRows(applyClientFilters(full.results));
      } else {
        const exportLimit = Math.min(result.total, 2000);
        if (exportLimit <= PAGE_SIZE && activePage === 0) {
          setExportRows(result.results);
        } else {
          const full = await fetchScannerResults({
            ...resultsQuery,
            limit: exportLimit,
            offset: 0,
          });
          if (requestId !== loadRequestRef.current) return;
          setExportRows(full.results);
        }
      }
      if (result.results.length > 0) {
        const first = result.results[0];
        const refreshedFirst =
          result.results.find(
            (r) => r.ticker === first.ticker && r.pattern_type === first.pattern_type,
          ) ?? first;
        void loadChart(refreshedFirst);
      } else {
        setSelectedRow(null);
        setChartHistory([]);
        setFundamentals(null);
        setFundamentalsError(null);
      }
    } catch (err) {
      if (requestId !== loadRequestRef.current) return;
      setRows([]);
      setExportRows([]);
      setTotal(0);
      setScanAlertsCount(null);
      setError(err instanceof Error ? err.message : "Failed to load scanner results");
    } finally {
      if (requestId === loadRequestRef.current) {
        setLoading(false);
      }
    }
  }, [
    tradeDate,
    pattern,
    minScoreNum,
    sector,
    triggeredOnly,
    setupOnly,
    macroPassOnly,
    fundamentalPassOnly,
    fundamentallyStrongOnly,
    page,
    filterInvalid,
    loadChart,
    fetchResultsPage,
    fnoSymbolSet,
    fnoGroup,
    applyClientFilters,
    ensureFoDerivatives,
    resultsQuery,
  ]);

  const stopScanPoll = useCallback(() => {
    if (scanPollRef.current != null) {
      window.clearInterval(scanPollRef.current);
      scanPollRef.current = null;
    }
  }, []);

  const pollScanStatus = useCallback(async () => {
    const status = await fetchScannerStatus();
    setScanStatus(status);
    const statusScanDates = scanDatesFromStatus(status);
    if (statusScanDates.length) {
      setScanDates((prev) => mergeSortedDates(prev, statusScanDates));
    }
    if (!status.running) {
      stopScanPoll();
      setScanRunning(false);
      await loadMeta();
      const batchFinished =
        status.last_result &&
        typeof status.last_result === "object" &&
        "batch" in status.last_result &&
        status.last_result.batch != null;
      if (status.trade_date && !batchFinished) {
        setTradeDate(status.trade_date);
      }
      setPage(0);
      void loadResults();
    }
  }, [stopScanPoll, loadMeta, loadResults]);

  const startScanPoll = useCallback(() => {
    stopScanPoll();
    void pollScanStatus();
    scanPollRef.current = window.setInterval(() => {
      void pollScanStatus();
    }, 1500);
  }, [stopScanPoll, pollScanStatus]);

  useEffect(() => {
    loadMeta()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load metadata"))
      .finally(() => setBootLoading(false));
  }, [loadMeta]);

  useEffect(() => {
    saveUiPrefs(SCANNER_PREFS_KEY, {
      tradeDate,
      scanMode,
      pattern,
      sector,
      fnoGroup,
      minScore,
      triggeredOnly,
      setupOnly,
      macroPassOnly,
      fundamentalPassOnly,
      fundamentallyStrongOnly,
    } satisfies ScannerUiPrefs);
  }, [
    tradeDate,
    scanMode,
    pattern,
    sector,
    fnoGroup,
    minScore,
    triggeredOnly,
    setupOnly,
    macroPassOnly,
    fundamentalPassOnly,
    fundamentallyStrongOnly,
  ]);

  useEffect(() => {
    fetchFno()
      .then((res) => setFnoSymbols(res.symbols))
      .catch(() => setFnoSymbols([]));
    fetchFundamentallyStrong()
      .then((res) => setStrongSymbols(res.symbols))
      .catch(() => setStrongSymbols([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchScannerStatus()
      .then((status) => {
        if (cancelled) return;
        setScanStatus(status);
        if (status.running) {
          setScanRunning(true);
          startScanPoll();
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      stopScanPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setPage(0);
  }, [
    tradeDate,
    pattern,
    sector,
    fnoGroup,
    minScore,
    triggeredOnly,
    setupOnly,
    macroPassOnly,
    fundamentalPassOnly,
    fundamentallyStrongOnly,
    scanMode,
  ]);

  useEffect(() => {
    if (bootLoading || !tradeDate || filterInvalid) return;
    void loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    bootLoading,
    tradeDate,
    page,
    scanMode,
    resultsQuery,
    fnoGroup,
    fundamentallyStrongOnly,
    fnoSymbols.length,
    strongSymbols.length,
  ]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);
  const exportJson = useMemo(
    () => (exportRows.length ? scannerToExportJson(exportRows) : "[]"),
    [exportRows],
  );
  const scanProgressPct = useMemo(() => {
    if (!scanStatus?.total) return 0;
    return Math.min(100, Math.round((scanStatus.processed / scanStatus.total) * 100));
  }, [scanStatus]);

  const batchProgressPct = useMemo(() => {
    if (!scanStatus?.batch_day_total) return scanProgressPct;
    const dayIndex = Math.max(0, (scanStatus.batch_day_index ?? 1) - 1);
    const dayFraction = scanStatus.total > 0 ? scanStatus.processed / scanStatus.total : 0;
    return Math.min(
      100,
      Math.round(((dayIndex + dayFraction) / scanStatus.batch_day_total) * 100),
    );
  }, [scanStatus, scanProgressPct]);

  const activeProgressPct = scanStatus?.batch_day_total ? batchProgressPct : scanProgressPct;

  const startScan = useCallback(
    async (batch: ScannerBatchMode) => {
      if (!tradeDate) return;
      setScanRunning(true);
      setError(null);
      try {
        await runScanner({
          tradeDate,
          backgroundRun: true,
          batch,
        });
        startScanPoll();
      } catch (err) {
        setScanRunning(false);
        setError(err instanceof Error ? err.message : "Scanner failed to start");
      }
    },
    [tradeDate, startScanPoll],
  );

  const handleRunScan = () => void startScan("single");
  const handleRunScanMonth = () => void startScan("month");
  const handleRunScanLast7 = () => void startScan("last_7");

  const handleCopyJson = async () => {
    if (!exportRows.length) return;
    setCopyingJson(true);
    setCopyMessage(null);
    try {
      await copyTextToClipboard(exportJson);
      setCopyMessage(`Copied ${exportRows.length} rows to clipboard`);
      setExportJsonOpen(true);
    } catch (err) {
      setCopyMessage(err instanceof Error ? err.message : "Copy failed");
    } finally {
      setCopyingJson(false);
    }
  };

  const handleSearch = () => {
    if (page !== 0) {
      setPage(0);
      return;
    }
    void loadResults(0);
  };

  const noScanForDate =
    hasLoaded && !loading && total === 0 && scanAlertsCount == null && !scanDates.includes(tradeDate);
  const scanHadNoAlerts =
    hasLoaded && !loading && total === 0 && scanAlertsCount === 0 && scanDates.includes(tradeDate);
  const filteredOutAllAlerts =
    hasLoaded &&
    !loading &&
    total === 0 &&
    scanAlertsCount != null &&
    scanAlertsCount > 0 &&
    filtersActive;

  const chartSector = useMemo(() => {
    if (fundamentals?.profile) {
      return extractProfileSector(fundamentals.profile) ?? selectedRow?.sector ?? null;
    }
    return selectedRow?.sector ?? null;
  }, [fundamentals, selectedRow?.sector]);

  const chartMarketCap = useMemo(
    () => (fundamentals?.profile ? extractProfileMarketCap(fundamentals.profile) : null),
    [fundamentals],
  );

  const selectedWhy = useMemo(
    () => (selectedRow ? describeScannerWhy(selectedRow) : null),
    [selectedRow],
  );

  const selectedMovePct = useMemo(
    () => (selectedRow ? signalDayMovePct(selectedRow) : null),
    [selectedRow],
  );

  const vcpOverlay = useMemo(() => {
    if (!showVcpOverlay || !selectedRow || selectedRow.pattern_type !== "vcp") return null;
    const asOf = selectedRow.trade_date;
    if (!asOf || !chartHistory.length) return null;
    return computeVcpOverlay(chartHistory, asOf, selectedRow.details);
  }, [showVcpOverlay, selectedRow, chartHistory]);

  return (
    <div className="flex h-[calc(100dvh-6.5rem)] min-h-0 flex-col lg:flex-row">
    <main className="mx-auto flex min-h-0 min-w-0 max-w-[1920px] flex-1 flex-col gap-1.5 overflow-hidden px-3 py-1.5 sm:px-4">
      {error && (
        <Alert severity="error" className="shrink-0 text-xs">
          {error}
        </Alert>
      )}

      <div className="shrink-0 overflow-x-auto rounded-xl border border-surface-border bg-surface-raised px-2 py-1.5 [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5">
        <div className="flex w-max max-w-none flex-nowrap items-center gap-2">
          <TimelineDataCoverage stats={stats} compact />
          <div className="h-5 w-px shrink-0 bg-surface-border" />
          <TimelineDatePicker
            compact
            showLegend={false}
            value={tradeDate}
            onChange={setTradeDate}
            availableDates={scanDates.length ? scanDates : stats ? [stats.max_trade_date].filter(Boolean) as string[] : []}
            markedDates={scanDates}
            markedLabel="Scan done"
            accentMarkedDates={refinedScanDates}
            accentMarkedLabel="Rescanned · Darvas included"
            minDate={stats?.min_trade_date}
            maxDate={today}
            disabled={bootLoading}
          />
          {(scanDates.length > 0 || refinedScanDates.length > 0) && (
            <span className="inline-flex shrink-0 flex-nowrap items-center gap-2 whitespace-nowrap text-[9px] text-slate-500">
              <span className="inline-flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-sm bg-emerald-400" />
                Scan done
              </span>
              {refinedScanDates.length > 0 ? (
                <span className="inline-flex items-center gap-1">
                  <span className="inline-block h-2 w-2 rounded-sm bg-sky-400" />
                  Rescanned · Darvas
                </span>
              ) : null}
            </span>
          )}

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
            size="small"
            className="shrink-0"
            onClick={handleRunScanMonth}
            disabled={scanRunning || bootLoading || !tradeDate}
            title={`Scan every weekday in ${tradeDate.slice(0, 7)} through ${tradeDate}`}
          >
            Month
          </AppButton>
          <AppButton
            size="small"
            className="shrink-0"
            onClick={handleRunScanLast7}
            disabled={scanRunning || bootLoading || !tradeDate}
            title={`Scan the 7 weekdays before ${tradeDate}`}
          >
            −7d
          </AppButton>

          <div className="h-5 w-px shrink-0 bg-surface-border" />

          <ToggleButtonGroup
            exclusive
            size="small"
            value={scanMode}
            onChange={(_e, value: ScannerScanMode | null) => {
              if (value) setScanMode(value);
            }}
            sx={{ height: 30, flexShrink: 0 }}
          >
            <ToggleButton value="confirmation" className="!px-2 !text-[10px] !normal-case">
              Confirmation
            </ToggleButton>
            <ToggleButton value="early_setup" className="!px-2 !text-[10px] !normal-case">
              Early setup
            </ToggleButton>
          </ToggleButtonGroup>

          <AppButton
            variant="outlined"
            size="small"
            className="shrink-0"
            startIcon={
              <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
            }
            onClick={handleSearch}
            disabled={loading || !tradeDate || filterInvalid}
          >
            Load
          </AppButton>

          {earlySetupMode && (
            <Typography variant="caption" className="shrink-0 whitespace-nowrap text-[9px] text-sky-300/90">
              Early: setup · ≤20% 20d · ≤2% day
            </Typography>
          )}
        </div>

        {scanRunning && scanStatus && (
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
        )}
      </div>

      <div
        className={`grid min-h-0 flex-1 grid-cols-1 gap-1.5 ${
          showFundamentals
            ? "lg:grid-cols-[minmax(30rem,2.4fr)_minmax(0,2.6fr)_minmax(15rem,1fr)] xl:grid-cols-[minmax(34rem,2.5fr)_minmax(0,2.5fr)_minmax(17rem,1fr)]"
            : "lg:grid-cols-[minmax(32rem,2.3fr)_minmax(0,2.7fr)] xl:grid-cols-[minmax(38rem,2.4fr)_minmax(0,2.6fr)]"
        }`}
      >
        <section className="flex min-h-0 min-w-0 flex-col rounded-xl border border-surface-border bg-surface-raised/60">
          <div className="shrink-0 border-b border-surface-border px-2.5 py-2">
            <div className="mb-2 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-slate-100">Pattern alerts</h2>
                <p className="truncate text-[10px] text-slate-500">
                  {!hasLoaded && !loading
                    ? "Loading…"
                    : !hasLoaded
                      ? "Load results or run a scan"
                      : `${total.toLocaleString()} matches · ${tradeDate}`}
                </p>
              </div>
              {hasLoaded && (
                <div className="flex shrink-0 items-center gap-1 text-[10px] text-slate-400">
                  <button
                    type="button"
                    disabled={!exportRows.length || copyingJson}
                    onClick={handleCopyJson}
                    title="Copy all matching results as JSON"
                    className="inline-flex items-center gap-1 rounded border border-surface-border px-2 py-1 text-slate-300 transition hover:border-accent/40 hover:text-slate-100 disabled:opacity-40"
                  >
                    <ClipboardCopy className={`h-3.5 w-3.5 ${copyingJson ? "animate-pulse" : ""}`} />
                    JSON
                  </button>
                  <span className="tabular-nums">
                    {page + 1}/{totalPages}
                  </span>
                  <button
                    type="button"
                    disabled={page <= 0 || loading}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    className="rounded border border-surface-border px-2 py-1 disabled:opacity-40"
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    disabled={page + 1 >= totalPages || loading}
                    onClick={() => setPage((p) => p + 1)}
                    className="rounded border border-surface-border px-2 py-1 disabled:opacity-40"
                  >
                    ›
                  </button>
                </div>
              )}
            </div>

            <div className="overflow-x-auto">
              <Stack
                direction="row"
                spacing={1}
                useFlexGap
                className="min-w-max flex-nowrap items-end"
              >
              <FormControl size="small" sx={{ minWidth: 108, flexShrink: 0 }} disabled={earlySetupMode}>
                <InputLabel id="scanner-pattern-label">Pattern</InputLabel>
                <Select
                  labelId="scanner-pattern-label"
                  label="Pattern"
                  value={pattern}
                  onChange={(e: SelectChangeEvent) =>
                    setPattern(e.target.value as ScannerPatternId | typeof ALL_FILTER)
                  }
                >
                  <MenuItem value={ALL_FILTER}>All</MenuItem>
                  {Object.entries(PATTERN_FILTER_LABELS).map(([id, label]) => (
                    <MenuItem key={id} value={id}>
                      {label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              <TextField
                size="small"
                type="number"
                label="Min score"
                value={earlySetupMode ? "75" : minScore}
                onChange={(e) => setMinScore(e.target.value)}
                disabled={earlySetupMode}
                slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
                sx={{ width: 88, flexShrink: 0 }}
              />

              <FormControl size="small" sx={{ minWidth: 96, flexShrink: 0 }} disabled={earlySetupMode}>
                <InputLabel id="scanner-sector-label">Sector</InputLabel>
                <Select
                  labelId="scanner-sector-label"
                  label="Sector"
                  value={sector}
                  onChange={(e: SelectChangeEvent) => setSector(e.target.value)}
                >
                  <MenuItem value={ALL_FILTER}>All</MenuItem>
                  {sectors.map((s) => (
                    <MenuItem key={s} value={s}>
                      {s}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              <Stack spacing={0.25} className="shrink-0">
                <Typography variant="caption" className="!text-[9px] text-slate-500">
                  Listing
                </Typography>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={fnoGroup}
                  onChange={(_e, value: FnoGroupFilter | null) => {
                    if (value) setFnoGroup(value);
                  }}
                  sx={{ height: 30, flexShrink: 0 }}
                >
                  <ToggleButton value="all" className="!px-2 !text-[10px] !normal-case">
                    All
                  </ToggleButton>
                  <ToggleButton
                    value="fno"
                    className="!px-2 !text-[10px] !normal-case"
                    title="NSE F&O stocks only"
                  >
                    F&O ★
                  </ToggleButton>
                  <ToggleButton
                    value="non_fno"
                    className="!px-2 !text-[10px] !normal-case"
                    title="Cash / non-F&O stocks only"
                  >
                    Non-F&O
                  </ToggleButton>
                </ToggleButtonGroup>
              </Stack>

              <FormGroup row sx={{ gap: 0, mr: 0.5, flexShrink: 0, flexWrap: "nowrap", opacity: earlySetupMode ? 0.5 : 1 }}>
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={earlySetupMode || triggeredOnly}
                      disabled={earlySetupMode}
                      onChange={(e) => setTriggeredOnly(e.target.checked)}
                    />
                  }
                  label={<Typography variant="caption">Trigger</Typography>}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={earlySetupMode || setupOnly}
                      disabled={earlySetupMode}
                      onChange={(e) => setSetupOnly(e.target.checked)}
                    />
                  }
                  label={<Typography variant="caption">Setup</Typography>}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={macroPassOnly}
                      onChange={(e) => setMacroPassOnly(e.target.checked)}
                    />
                  }
                  label={<Typography variant="caption">Macro</Typography>}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={fundamentallyStrongOnly}
                      onChange={(e) => setFundamentallyStrongOnly(e.target.checked)}
                    />
                  }
                  label={
                    <Typography
                      variant="caption"
                      title={FUNDAMENTALLY_STRONG_TOOLTIP}
                      className="whitespace-nowrap"
                    >
                      Strong
                    </Typography>
                  }
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={fundamentalPassOnly}
                      onChange={(e) => setFundamentalPassOnly(e.target.checked)}
                    />
                  }
                  label={
                    <Typography variant="caption" title="Legacy ROE ≥ 15% and ROCE ≥ 12% gate">
                      Fund
                    </Typography>
                  }
                />
              </FormGroup>
              </Stack>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full text-left">
              <thead className="sticky top-0 z-10 bg-surface-raised text-[10px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-2.5 py-2">
                    Ticker
                    <span className="ml-1 font-normal normal-case text-slate-600" title="F&O stocks marked with ★">
                      ★
                    </span>
                  </th>
                  <th className="px-2 py-2">Pattern</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Timing</th>
                  <th className="px-2 py-2 text-right">20d</th>
                  <th className="px-2 py-2 text-right">Move</th>
                  <th className="px-2 py-2 text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {loading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-2 py-4 text-center text-[11px] text-slate-500">
                      Loading…
                    </td>
                  </tr>
                ) : !hasLoaded && !loading ? (
                  <tr>
                    <td colSpan={7} className="px-2 py-4 text-center text-[11px] text-slate-500">
                      Loading scan results…
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-2 py-3 text-center text-[11px] text-slate-500">
                      {noScanForDate ? (
                        <div className="space-y-2">
                          <p>No scan for {tradeDate}. Click Run scan first.</p>
                          <button
                            type="button"
                            onClick={handleRunScan}
                            disabled={scanRunning}
                            className="inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent/10 px-2.5 py-1 text-[11px] font-medium text-accent"
                          >
                            <DocumentScannerIcon sx={{ fontSize: 12 }} />
                            Run scan
                          </button>
                        </div>
                      ) : scanHadNoAlerts ? (
                        <p>
                          Scan completed for {tradeDate} with no pattern alerts. Try an earlier scan
                          date (marked on the calendar) or run a new scan.
                        </p>
                      ) : filteredOutAllAlerts ? (
                        <p>
                          Scan found {scanAlertsCount.toLocaleString()} alerts on {tradeDate}, but
                          none match these filters. Lower min score or clear pattern/sector filters.
                        </p>
                      ) : (
                        "No matches for these filters"
                      )}
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => {
                    const isSelected = selectedRow?.ticker === row.ticker && selectedRow?.pattern_type === row.pattern_type;
                    const status = signalStatus(row);
                    const timing = timingClassFromRow(row);
                    const pre20d = pre20dReturnFromRow(row);
                    const fundPass = fundamentalPassFromRow(row);
                    const movePct = signalDayMovePct(row);
                    return (
                      <tr
                        key={`${row.ticker}-${row.pattern_type}`}
                        onClick={() => loadChart(row)}
                        className={`cursor-pointer border-t border-surface-border/60 transition ${
                          isSelected
                            ? "bg-accent/10 hover:bg-accent/15"
                            : "hover:bg-surface/40"
                        }`}
                      >
                        <td className="px-2.5 py-2 align-top">
                          <div className="flex items-center gap-1">
                            <div className="text-xs font-medium text-slate-100">{row.ticker}</div>
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
                          {row.sector && (
                            <div className="truncate text-[10px] text-slate-500">{row.sector}</div>
                          )}
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            <GatePill kind="macro" pass={row.macro_pass} />
                            <GatePill kind="fund" pass={fundPass} />
                            {fnoSymbolSet.has(row.ticker) && (() => {
                              const fo = foGateDisplay(row);
                              return (
                                <GatePill
                                  kind="fo"
                                  pass={fo.pass}
                                  stateOverride={fo.state}
                                  titleOverride={fo.title}
                                />
                              );
                            })()}
                          </div>
                        </td>
                        <td className="px-2 py-2 align-top text-[11px] leading-snug text-slate-300">
                          {SCANNER_PATTERN_LABELS[row.pattern_type]}
                        </td>
                        <td className="px-2 py-2 align-top">
                          <StatusBadge status={status} />
                        </td>
                        <td className="px-2 py-2 align-top">
                          <TimingBadge timing={timing} />
                        </td>
                        <td className="px-2 py-2 align-top text-right text-[11px]">
                          <MoveCell value={pre20d} />
                        </td>
                        <td className="px-2 py-2 align-top text-right text-[11px]">
                          <MoveCell value={movePct} />
                        </td>
                        <td className="px-2 py-2 align-top text-right tabular-nums text-xs font-medium text-slate-200">
                          {formatScore(row.score)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {selectedRow && selectedWhy && (
            <div className="shrink-0 border-t border-surface-border bg-surface/40 px-2.5 py-2">
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-100">
                  {selectedRow.ticker}
                  <FnoStarMark show={fnoSymbolSet.has(selectedRow.ticker)} />
                </span>
                <span className="text-[10px] text-slate-500">
                  {SCANNER_PATTERN_LABELS[selectedRow.pattern_type]}
                </span>
                <StatusBadge status={signalStatus(selectedRow)} />
                <TimingBadge timing={timingClassFromRow(selectedRow)} />
                <span className={`text-[10px] tabular-nums ${selectedMovePct != null && selectedMovePct >= 0 ? "text-emerald-400" : selectedMovePct != null ? "text-red-400" : "text-slate-400"}`}>
                  {formatSignalMovePct(selectedMovePct)}
                </span>
                <span className="text-[10px] tabular-nums text-slate-400">{formatScore(selectedRow.score)}</span>
              </div>
              <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Why</p>
              <p className="mt-0.5 max-h-24 overflow-y-auto text-[10px] leading-relaxed text-slate-300">
                {selectedWhy}
              </p>
            </div>
          )}

          {copyMessage && (
            <p className="shrink-0 border-t border-surface-border px-3 py-1 text-[10px] text-emerald-400">
              {copyMessage}
            </p>
          )}

          {hasLoaded && exportRows.length > 0 && (
            <div className="shrink-0 border-t border-surface-border">
              <button
                type="button"
                onClick={() => setExportJsonOpen((v) => !v)}
                className="flex w-full items-center justify-between px-3 py-1.5 text-[10px] text-slate-400 hover:text-slate-200"
              >
                <span>Export JSON ({exportRows.length} rows)</span>
                <span>{exportJsonOpen ? "Hide" : "Show"}</span>
              </button>
              {exportJsonOpen && (
                <textarea
                  readOnly
                  value={exportJson}
                  onFocus={(e) => e.target.select()}
                  className="h-28 w-full resize-none border-t border-surface-border bg-surface px-3 py-2 font-mono text-[10px] leading-relaxed text-slate-300 outline-none"
                />
              )}
            </div>
          )}
        </section>

        <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-1 rounded-xl border border-surface-border bg-surface-raised/30 p-1">
          <div className="flex shrink-0 items-center justify-end gap-1 px-1">
            <button
              type="button"
              onClick={toggleVcpOverlay}
              disabled={selectedRow?.pattern_type !== "vcp"}
              title={
                selectedRow?.pattern_type !== "vcp"
                  ? "Select a VCP signal to show contraction bands"
                  : showVcpOverlay
                    ? "Hide VCP overlay"
                    : "Show VCP overlay (20d / 10d / 5d ranges + pivot)"
              }
              className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] transition disabled:cursor-not-allowed disabled:opacity-40 ${
                showVcpOverlay && selectedRow?.pattern_type === "vcp"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                  : "border-surface-border text-slate-400 hover:border-amber-500/30 hover:text-slate-200"
              }`}
            >
              <Layers className="h-3 w-3" />
              VCP overlay
            </button>
            <button
              type="button"
              onClick={toggleFundamentals}
              title={showFundamentals ? "Hide fundamentals panel" : "Show fundamentals panel"}
              className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] transition ${
                showFundamentals
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-surface-border text-slate-400 hover:border-accent/30 hover:text-slate-200"
              }`}
            >
              {showFundamentals ? (
                <PanelRightClose className="h-3 w-3" />
              ) : (
                <PanelRightOpen className="h-3 w-3" />
              )}
              Fundamentals
            </button>
            <button
              type="button"
              onClick={toggleCompanyNews}
              title={showCompanyNews ? "Hide company news" : "Show company news"}
              className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] transition ${
                showCompanyNews
                  ? "border-sky-500/40 bg-sky-500/10 text-sky-200"
                  : "border-surface-border text-slate-400 hover:border-sky-500/30 hover:text-slate-200"
              }`}
            >
              <Newspaper className="h-3 w-3" />
              News
            </button>
          </div>
          {selectedRow && (
            <div className="flex shrink-0 flex-wrap items-center gap-1.5 rounded-lg border border-surface-border bg-surface-raised/60 px-2 py-1 text-[10px] text-slate-300">
              <TrendingUp className="h-3 w-3 text-accent" />
              <span className="inline-flex items-center gap-1 font-medium text-slate-100">
                {selectedRow.ticker}
                <FnoStarMark show={fnoSymbolSet.has(selectedRow.ticker)} />
              </span>
              <StatusBadge status={signalStatus(selectedRow)} />
              <TimingBadge timing={timingClassFromRow(selectedRow)} />
              <span className="text-slate-500">·</span>
              <span className="truncate">{SCANNER_PATTERN_LABELS[selectedRow.pattern_type]}</span>
              <span className="text-slate-500">·</span>
              <span className={selectedMovePct != null && selectedMovePct >= 0 ? "text-emerald-400" : selectedMovePct != null ? "text-red-400" : ""}>
                {formatSignalMovePct(selectedMovePct)}
              </span>
              <span className="text-slate-500">·</span>
              <span>{formatScore(selectedRow.score)}</span>
            </div>
          )}
          {(foSyncing || foSyncNote) && (
            <div
              className={`flex shrink-0 items-start gap-2 rounded-lg border px-2 py-1 text-[11px] ${
                foSyncing
                  ? "border-sky-500/30 bg-sky-500/10 text-sky-200"
                  : "border-surface-border bg-surface/40 text-slate-400"
              }`}
            >
              {foSyncing ? (
                <RefreshCw className="mt-0.5 h-3 w-3 shrink-0 animate-spin" />
              ) : null}
              <span>{foSyncing ? "Fetching F&O derivative data from Upstox…" : foSyncNote}</span>
            </div>
          )}
          {chartError && (
            <div className="flex shrink-0 items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              <span>{chartError}</span>
            </div>
          )}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="min-h-[160px] min-h-0 flex-1">
              <TimelineStockChart
                symbol={selectedRow?.ticker ?? ""}
                companyName={selectedRow?.company_name}
                sector={chartSector}
                marketCap={chartMarketCap}
                source={chartSource}
                history={chartHistory}
                highlightDate={selectedRow?.trade_date ?? tradeDate}
                highlightMovePct={selectedMovePct}
                loading={chartLoading}
                fillHeight
                tailVisibleRange
                vcpOverlay={vcpOverlay}
              />
            </div>
          </div>
        </section>

        {showFundamentals && (
          <section className="flex min-h-0 min-w-0 flex-col lg:max-w-[24rem]">
            {selectedRow ? (
              <StockFundamentalsPanel
                data={fundamentals}
                loading={fundamentalsLoading}
                error={fundamentalsError}
                syncing={fundamentalsSyncing}
                onSync={handleSyncFundamentals}
                compact
                sidebar
              />
            ) : (
              <div className="flex h-full min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-surface-border px-3 text-center text-xs text-slate-500">
                Select a stock to view fundamentals
              </div>
            )}
          </section>
        )}
      </div>
    </main>
    {showCompanyNews ? (
      <CompanyNewsSidebar
        ticker={selectedRow?.ticker}
        companyName={selectedRow?.company_name}
        className="h-[min(45vh,26rem)] shrink-0 border-t lg:h-full lg:border-t-0"
      />
    ) : null}
    </div>
  );
}
