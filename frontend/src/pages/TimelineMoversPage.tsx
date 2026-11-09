import { TimelineDatePicker } from "@/components/TimelineDatePicker";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { CompanyNewsSidebar } from "@/components/news/CompanyNewsSidebar";
import { StockFundamentalsPanel } from "@/components/StockFundamentalsPanel";
import { StockTickerSearch } from "@/components/StockTickerSearch";
import { AppButton } from "@/components/mui";
import {
  AdvancedButton,
  Clip,
  FilterToggle,
  PageToolbar,
  PctCell,
  ToolbarDivider,
} from "@/components/dense";
import { TimelineMoversAdvanced } from "@/pages/timeline/TimelineMoversAdvanced";
import {
  cancelTimelineIngest,
  fetchFundamentallyStrong,
  fetchStockFundamentals,
  fetchTimelineCandles,
  fetchTimelineDates,
  fetchTimelineIngestStatus,
  fetchTimelineMovers,
  fetchTimelineSectors,
  fetchTimelineStats,
  ingestTimelineCandles,
  syncStockFundamentals,
  syncTimelineProfiles,
  reprofileTimelineStale,
  type StockFundamentals,
  type TimelineCandlePoint,
  type TimelineIngestStatus,
  type TimelineMoverRow,
  type TimelineStats,
} from "@/lib/api";
import { AlertTriangle, CalendarClock } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clampWeekday, localTodayIso, nearestWeekday } from "@/lib/dates";
import { FUNDAMENTALLY_STRONG_TOOLTIP } from "@/lib/fundamentalsMeta";
import RefreshIcon from "@mui/icons-material/Refresh";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { needsCandleSync } from "@/lib/timelineCoverage";
import { copyTextToClipboard, moversToExportJson } from "@/lib/timelineExport";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

const PAGE_SIZE = 50;

const TIMELINE_PREFS_KEY = "trading.timeline.prefs";
type TimelineUiPrefs = {
  tradeDate: string;
  sector: string;
  minMovePct: string;
  direction: "both" | "up" | "down";
  ticker: string;
  fundamentallyStrongOnly: boolean;
};
const DEFAULT_TIMELINE_PREFS: TimelineUiPrefs = {
  tradeDate: "",
  sector: "",
  minMovePct: "5",
  direction: "both",
  ticker: "",
  fundamentallyStrongOnly: false,
};

export function TimelineMoversPage() {
  const initialPrefs = loadUiPrefs(TIMELINE_PREFS_KEY, DEFAULT_TIMELINE_PREFS);
  const [stats, setStats] = useState<TimelineStats | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [dates, setDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState(initialPrefs.tradeDate);
  const [sector, setSector] = useState(initialPrefs.sector);
  const [minMovePct, setMinMovePct] = useState(initialPrefs.minMovePct || "5");
  const [direction, setDirection] = useState<"both" | "up" | "down">(initialPrefs.direction === "up" || initialPrefs.direction === "down" ? initialPrefs.direction : "both");
  const [ticker, setTicker] = useState(initialPrefs.ticker);
  const [fundamentallyStrongOnly, setFundamentallyStrongOnly] = useState(Boolean(initialPrefs.fundamentallyStrongOnly));
  const [strongSymbols, setStrongSymbols] = useState<string[]>([]);
  const strongSymbolSet = useMemo(() => new Set(strongSymbols), [strongSymbols]);
  const [page, setPage] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);

  const [rows, setRows] = useState<TimelineMoverRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedRow, setSelectedRow] = useState<TimelineMoverRow | null>(null);
  const [chartHistory, setChartHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

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

  useEffect(() => {
    saveUiPrefs(TIMELINE_PREFS_KEY, {
      tradeDate,
      sector,
      minMovePct,
      direction,
      ticker,
      fundamentallyStrongOnly,
    } satisfies TimelineUiPrefs);
  }, [tradeDate, sector, minMovePct, direction, ticker, fundamentallyStrongOnly]);

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

  const [syncing, setSyncing] = useState(false);
  const [reprofiling, setReprofiling] = useState(false);
  const [uptoDateRunning, setUptoDateRunning] = useState(false);
  const [ingestStopping, setIngestStopping] = useState(false);
  const [ingestStatus, setIngestStatus] = useState<TimelineIngestStatus | null>(null);
  const ingestPollRef = useRef<number | null>(null);
  const [exportRows, setExportRows] = useState<TimelineMoverRow[]>([]);
  const [exportJsonOpen, setExportJsonOpen] = useState(false);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [copyingJson, setCopyingJson] = useState(false);
  const [syncInfo, setSyncInfo] = useState<string | null>(null);

  const minMove = parseFloat(minMovePct);
  const filterInvalid = Number.isNaN(minMove) || minMove < 0;
  const today = nearestWeekday(localTodayIso());
  const latestDataDate = stats?.max_trade_date ?? null;
  const dateNeedsIngest =
    Boolean(tradeDate && latestDataDate && tradeDate > latestDataDate);
  const dataIsStale = stats != null && !stats.is_up_to_date;
  const candleSyncNeeded = needsCandleSync(stats);

  const loadMeta = useCallback(async (options?: { selectLatest?: boolean }) => {
    const [statsRes, sectorsRes, datesRes] = await Promise.all([
      fetchTimelineStats(),
      fetchTimelineSectors(),
      fetchTimelineDates(365),
    ]);
    setStats(statsRes);
    setSectors(sectorsRes.sectors);
    setDates(datesRes.dates);
    setTradeDate((current) => {
      const pick = (iso: string) => clampWeekday(iso, statsRes.min_trade_date, localTodayIso());
      if (options?.selectLatest) {
        const latest = datesRes.dates[0];
        if (latest) {
          const todayIso = nearestWeekday(localTodayIso());
          return datesRes.dates.includes(todayIso) ? pick(todayIso) : pick(latest);
        }
      }
      if (current) return pick(current);
      return pick(datesRes.dates[0] || statsRes.max_trade_date || localTodayIso());
    });
    window.dispatchEvent(new CustomEvent("timeline-stats-updated"));
    return datesRes.dates;
  }, []);

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

  const loadChart = useCallback(async (row: TimelineMoverRow) => {
    setSelectedRow(row);
    setChartLoading(true);
    setChartError(null);
    setFundamentals(null);
    setFundamentalsError(null);
    try {
      const payload = await fetchTimelineCandles(row.ticker);
      setChartHistory(payload.history);
      setChartSource(payload.source);
    } catch (err) {
      setChartHistory([]);
      setChartError(
        err instanceof Error ? err.message : `No chart data for ${row.ticker}`,
      );
    } finally {
      setChartLoading(false);
    }
    void loadFundamentals(row.ticker);
  }, [loadFundamentals]);

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

  const loadMovers = useCallback(async (opts?: { ticker?: string }) => {
    if (!tradeDate || filterInvalid) return;
    const activeTicker = opts?.ticker !== undefined ? opts.ticker : ticker;
    setLoading(true);
    setError(null);
    setCopyMessage(null);
    setHasSearched(true);
    setSelectedRow(null);
    setChartHistory([]);
    setChartError(null);
    setFundamentals(null);
    setFundamentalsError(null);
    try {
      const base = {
        tradeDate,
        ticker: activeTicker || undefined,
        sector: activeTicker ? undefined : sector || undefined,
        minMovePct: activeTicker ? 0 : minMove,
        direction: (activeTicker ? "both" : direction) as typeof direction,
      };

      let pageRows: TimelineMoverRow[];
      let pageTotal: number;
      let exportSource: TimelineMoverRow[];

      if (fundamentallyStrongOnly && !activeTicker) {
        const full = await fetchTimelineMovers({
          ...base,
          limit: 2000,
          offset: 0,
        });
        const filtered = full.results.filter((row) => {
          if (!strongSymbolSet.has(row.ticker.toUpperCase())) return false;
          const move = row.daily_return_pct;
          if (move == null || Number.isNaN(move)) return false;
          if (direction === "up") return move >= minMove;
          if (direction === "down") return move <= -minMove;
          return Math.abs(move) >= minMove;
        });
        const offset = page * PAGE_SIZE;
        pageRows = filtered.slice(offset, offset + PAGE_SIZE);
        pageTotal = filtered.length;
        exportSource = filtered;
      } else {
        const result = await fetchTimelineMovers({
          ...base,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        });
        pageRows = result.results;
        pageTotal = result.total;

        const exportLimit = Math.min(result.total, 2000);
        if (exportLimit <= PAGE_SIZE && page === 0) {
          exportSource = result.results;
        } else {
          const full = await fetchTimelineMovers({
            ...base,
            limit: exportLimit,
            offset: 0,
          });
          exportSource = full.results;
        }
        if (fundamentallyStrongOnly && activeTicker) {
          const keep = strongSymbolSet.has(activeTicker.toUpperCase());
          pageRows = keep ? pageRows : [];
          pageTotal = keep ? pageTotal : 0;
          exportSource = keep ? exportSource : [];
        }
      }

      setRows(pageRows);
      setTotal(pageTotal);
      setExportRows(exportSource);

      if (pageRows.length > 0) {
        void loadChart(pageRows[0]);
      }
    } catch (err) {
      setRows([]);
      setTotal(0);
      setError(err instanceof Error ? err.message : "Failed to load movers");
    } finally {
      setLoading(false);
    }
  }, [
    tradeDate,
    sector,
    ticker,
    minMove,
    direction,
    page,
    filterInvalid,
    loadChart,
    fundamentallyStrongOnly,
    strongSymbolSet,
  ]);

  useEffect(() => {
    loadMeta()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load timeline metadata"))
      .finally(() => setBootLoading(false));
  }, [loadMeta]);

  useEffect(() => {
    fetchFundamentallyStrong()
      .then((res) => setStrongSymbols(res.symbols))
      .catch(() => setStrongSymbols([]));
  }, []);

  useEffect(() => {
    setPage(0);
  }, [tradeDate, sector, ticker, minMovePct, direction, fundamentallyStrongOnly]);

  useEffect(() => {
    if (hasSearched && tradeDate && !filterInvalid) {
      loadMovers();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when page / filters change
  }, [
    page,
    fundamentallyStrongOnly,
    strongSymbols.length,
    direction,
    sector,
    minMove,
    tradeDate,
  ]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);

  const exportJson = useMemo(
    () => (exportRows.length ? moversToExportJson(exportRows) : "[]"),
    [exportRows],
  );

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

  const stopIngestPoll = useCallback(() => {
    if (ingestPollRef.current != null) {
      window.clearInterval(ingestPollRef.current);
      ingestPollRef.current = null;
    }
  }, []);

  const pollIngestStatus = useCallback(async () => {
    const status = await fetchTimelineIngestStatus();
    setIngestStatus(status);
    if (!status.running) {
      stopIngestPoll();
      setUptoDateRunning(false);
      setIngestStopping(false);
      const freshDates = await loadMeta({ selectLatest: true });
      if (hasSearched) await loadMovers();
      if (status.last_result && "processed" in status.last_result) {
        const r = status.last_result;
        const errCount = r.failed ?? 0;
        const errNote =
          errCount > 0
            ? ` Errors logged to ${status.error_log ?? "candle_ingest_errors.log"}.`
            : "";
        setSyncInfo(
          `Sync finished: ${r.success ?? 0} updated, ${r.skipped ?? 0} skipped, ${r.failed ?? 0} failed, ${r.total_bars ?? 0} bars written.${errNote}`,
        );
        if (errCount > 0 && status.recent_errors?.length) {
          const preview = status.recent_errors
            .slice(0, 3)
            .map((e) => `${e.ticker}: ${e.error}`)
            .join(" · ");
          setError(`Ingest errors (${errCount}): ${preview}`);
        }
      }
      void freshDates;
    }
  }, [stopIngestPoll, loadMeta, hasSearched, loadMovers]);

  const startIngestPoll = useCallback(() => {
    stopIngestPoll();
    void pollIngestStatus();
    ingestPollRef.current = window.setInterval(() => {
      void pollIngestStatus();
    }, 1500);
  }, [stopIngestPoll, pollIngestStatus]);

  useEffect(() => {
    let cancelled = false;
    fetchTimelineIngestStatus()
      .then((status) => {
        if (cancelled) return;
        setIngestStatus(status);
        if (status.running) {
          setUptoDateRunning(true);
          startIngestPoll();
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      stopIngestPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resume polling once on mount
  }, []);

  const ingestProgressPct = useMemo(() => {
    if (!ingestStatus?.total) return 0;
    return Math.min(100, Math.round((ingestStatus.processed / ingestStatus.total) * 100));
  }, [ingestStatus]);

  const handleTickerChange = (next: string) => {
    setTicker(next);
    setPage(0);
    if (tradeDate && !filterInvalid && (next || hasSearched)) {
      void loadMovers({ ticker: next });
    }
  };

  useEffect(() => {
    if (!ticker || !tradeDate || filterInvalid) return;
    loadMovers();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload selected stock when date changes
  }, [tradeDate]);

  const handleSearch = () => {
    if (page === 0) {
      loadMovers();
    } else {
      setPage(0);
    }
  };

  const handleSyncProfiles = async () => {
    setSyncing(true);
    setError(null);
    try {
      await syncTimelineProfiles();
      await loadMeta();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profile sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const handleReprofileStale = async () => {
    setReprofiling(true);
    setError(null);
    setSyncInfo(null);
    try {
      const result = await reprofileTimelineStale();
      await loadMeta();
      setSyncInfo(
        `Reprofiled: ${result.ingest_skip_marked} marked ingest-skip` +
          (result.instrument_tokens_migrated
            ? `, ${result.instrument_tokens_migrated} ISIN migrations`
            : "") +
          (result.ingest_skip_cleared ? `, ${result.ingest_skip_cleared} re-enabled` : "") +
          ".",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reprofile failed");
    } finally {
      setReprofiling(false);
    }
  };

  const handleUptoDate = async () => {
    setError(null);
    setSyncInfo(null);
    try {
      const fresh = await fetchTimelineStats();
      setStats(fresh);
      window.dispatchEvent(new CustomEvent("timeline-stats-updated"));

      if (!needsCandleSync(fresh)) {
        setSyncInfo(
          `Candle data is already current through ${fresh.max_trade_date} (target ${fresh.target_trade_date}).`,
        );
        return;
      }

      if (fresh.is_up_to_date) {
        setSyncInfo(
          `Session date is ${fresh.max_trade_date}. Updating ${fresh.symbols_behind_target.toLocaleString()} symbols still behind…`,
        );
      } else {
        setSyncInfo(
          `Updating candles from ${fresh.max_trade_date ?? "—"} toward ${fresh.target_trade_date}…`,
        );
      }

      setUptoDateRunning(true);
      await ingestTimelineCandles({
        sinceLast: true,
        refreshAll: true,
        backgroundRun: true,
        concurrency: 3,
      });
      startIngestPoll();
    } catch (err) {
      setUptoDateRunning(false);
      setError(err instanceof Error ? err.message : "Up-to-date sync failed");
    }
  };

  const handleStopIngest = async () => {
    setIngestStopping(true);
    setError(null);
    try {
      await cancelTimelineIngest();
      void pollIngestStatus();
    } catch (err) {
      setIngestStopping(false);
      setError(err instanceof Error ? err.message : "Failed to stop sync");
    }
  };

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const showIngestBar = uptoDateRunning && ingestStatus != null;

  return (
    <div className="page-shell flex flex-col lg:flex-row">
    <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error && (
        <div className="flex shrink-0 items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-data-sm text-red-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <PageToolbar
        right={<AdvancedButton onClick={() => setAdvancedOpen(true)} label="Data & jobs" />}
        below={
          showIngestBar && ingestStatus ? (
            <div className="space-y-1">
              {(
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-data-xs text-slate-300">
                    <span>
                      Updating stocks
                      {ingestStatus.current_ticker ? (
                        <>
                          {" · "}
                          <span className="font-semibold text-slate-100">{ingestStatus.current_ticker}</span>
                        </>
                      ) : null}
                      {(ingestStopping || ingestStatus.cancel_requested) && (
                        <span className="text-amber-400"> · Stopping…</span>
                      )}
                    </span>
                    <span className="tabular-nums">
                      {ingestStatus.processed.toLocaleString()}/{ingestStatus.total.toLocaleString()}
                      {ingestStatus.total > 0 ? ` (${ingestProgressPct}%)` : ""}
                      {ingestStatus.failed > 0 && (
                        <span className="text-loss"> · {ingestStatus.failed.toLocaleString()} failed</span>
                      )}
                    </span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-surface">
                    <div
                      className="h-full rounded-full bg-accent transition-all duration-300"
                      style={{ width: `${ingestProgressPct}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          ) : undefined
        }
      >
        <TimelineDatePicker
          compact
          value={tradeDate}
          onChange={setTradeDate}
          availableDates={dates}
          minDate={stats?.min_trade_date}
          maxDate={today}
          disabled={bootLoading}
        />
        {today !== tradeDate && (
          <AppButton
            size="small"
            className="shrink-0"
            disabled={bootLoading}
            onClick={() => setTradeDate(today)}
            title="Jump to today"
          >
            Today
          </AppButton>
        )}

        <ToolbarDivider />

        <StockTickerSearch
          compact
          value={ticker}
          onChange={handleTickerChange}
          disabled={bootLoading}
          placeholder="Ticker…"
        />

        <TextField
          type="number"
          label="Move ≥ %"
          value={minMovePct}
          onChange={(e) => setMinMovePct(e.target.value)}
          disabled={Boolean(ticker)}
          slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
          sx={{ width: 84, flexShrink: 0, opacity: ticker ? 0.5 : 1 }}
        />

        <FormControl sx={{ minWidth: 108, flexShrink: 0, opacity: ticker ? 0.5 : 1 }} disabled={Boolean(ticker)}>
          <InputLabel id="timeline-sector-label">Sector</InputLabel>
          <Select
            labelId="timeline-sector-label"
            label="Sector"
            value={sector}
            onChange={(e: SelectChangeEvent) => setSector(e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            {sectors.map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <ToggleButtonGroup
          exclusive
          value={direction}
          onChange={(_, value: typeof direction | null) => {
            if (value) setDirection(value);
          }}
          disabled={Boolean(ticker)}
          sx={{ flexShrink: 0, opacity: ticker ? 0.5 : 1 }}
        >
          {(["both", "up", "down"] as const).map((value) => (
            <ToggleButton key={value} value={value} sx={{ textTransform: "capitalize" }}>
              {value}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        <FilterToggle
          label="Fund. strong"
          selected={fundamentallyStrongOnly}
          onChange={setFundamentallyStrongOnly}
          disabled={Boolean(ticker)}
          title={ticker ? "Disabled while a stock is selected" : FUNDAMENTALLY_STRONG_TOOLTIP}
        />

        <AppButton
          variant="contained"
          size="small"
          className="shrink-0"
          startIcon={
            <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
          }
          onClick={handleSearch}
          disabled={loading || !tradeDate || filterInvalid}
        >
          Search
        </AppButton>
      </PageToolbar>

      <TimelineMoversAdvanced
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        stats={stats}
        tradeDate={tradeDate}
        dataIsStale={dataIsStale}
        candleSyncNeeded={candleSyncNeeded}
        syncing={syncing}
        reprofiling={reprofiling}
        uptoDateRunning={uptoDateRunning}
        ingestStopping={ingestStopping}
        ingestStatus={ingestStatus}
        ingestProgressPct={ingestProgressPct}
        onSyncProfiles={handleSyncProfiles}
        onReprofileStale={handleReprofileStale}
        onUptoDate={handleUptoDate}
        onStopIngest={handleStopIngest}
        syncInfo={syncInfo}
        showFundamentals={showFundamentals}
        onToggleFundamentals={toggleFundamentals}
        hasSearched={hasSearched}
        exportRowsCount={exportRows.length}
        exportJson={exportJson}
        copyingJson={copyingJson}
        copyMessage={copyMessage}
        onCopyJson={handleCopyJson}
        exportJsonOpen={exportJsonOpen}
        setExportJsonOpen={setExportJsonOpen}
      />

      {/* Movers list | chart | fundamentals */}
      <div
        className={`grid min-h-0 flex-1 grid-cols-1 gap-1 ${
          showFundamentals
            ? "lg:grid-cols-[minmax(15rem,19rem)_minmax(0,1fr)_minmax(16rem,22rem)] xl:grid-cols-[19rem_minmax(0,1fr)_minmax(18rem,24rem)]"
            : "lg:grid-cols-[minmax(15rem,19rem)_minmax(0,1fr)] xl:grid-cols-[19rem_minmax(0,1fr)]"
        }`}
      >
        <section className="panel flex min-h-0 min-w-0 flex-col">
          <div className="flex shrink-0 items-center justify-between gap-1 border-b border-surface-border px-2 py-1">
            <div className="flex min-w-0 items-baseline gap-2">
              <h2 className="shrink-0 text-data-md font-semibold text-slate-100">Daily movers</h2>
              <Clip className="text-data-xs tabular-nums text-slate-300">
                {!hasSearched
                  ? "Run a search"
                  : ticker
                    ? `${total ? "1 stock" : "No data"} · ${ticker} · ${tradeDate}`
                    : `${total.toLocaleString()} matches · ${tradeDate}`}
              </Clip>
            </div>
            {hasSearched && totalPages > 1 && (
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
                  {page + 1}/{totalPages}
                </span>
                <button
                  type="button"
                  disabled={page + 1 >= totalPages || loading}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded border border-surface-border px-1.5 leading-5 disabled:opacity-40"
                  aria-label="Next page"
                >
                  ›
                </button>
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="dt">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="text-right">Move</th>
                </tr>
              </thead>
              <tbody>
                {loading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="py-4 text-center text-slate-400">
                      Loading…
                    </td>
                  </tr>
                ) : !hasSearched ? (
                  <tr>
                    <td colSpan={2} className="py-4 text-center text-slate-400">
                      Set filters and search
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="py-3 text-center text-slate-300">
                      {dateNeedsIngest ? (
                        <div className="space-y-2">
                          <p>
                            No local data for <span className="text-slate-100">{tradeDate}</span>.
                            {latestDataDate ? (
                              <>
                                {" "}
                                Latest ingested trading day is{" "}
                                <span className="text-slate-100">{latestDataDate}</span>.
                              </>
                            ) : null}
                          </p>
                          <p className="text-data-xs text-slate-400">
                            Run Up-to-date to fetch missing days from Upstox (~30–60 min for all
                            stocks). Failures are logged per symbol.
                          </p>
                          <button
                            type="button"
                            onClick={handleUptoDate}
                            disabled={uptoDateRunning || (stats?.profile_count ?? 0) === 0}
                            className="inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent/10 px-2.5 py-1 text-data-xs font-medium text-sky-200 transition hover:bg-accent/20 disabled:opacity-50"
                          >
                            <CalendarClock className="h-3 w-3" />
                            {uptoDateRunning ? "Updating…" : "Run Up-to-date"}
                          </button>
                        </div>
                      ) : ticker ? (
                        `No candle data for ${ticker} on ${tradeDate}`
                      ) : (
                        "No matches for these filters"
                      )}
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => {
                    const isSelected = selectedRow?.ticker === row.ticker;
                    return (
                      <tr
                        key={`${row.ticker}-${row.trade_date}`}
                        onClick={() => loadChart(row)}
                        className={`dt-row ${isSelected ? "dt-selected" : ""}`}
                      >
                        <td className="max-w-[13rem]">
                          <div className="flex items-center gap-1">
                            <span className="ticker">{row.ticker}</span>
                            {strongSymbolSet.has(row.ticker.toUpperCase()) && (
                              <span
                                className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1 text-[10px] font-semibold leading-[14px] text-emerald-200"
                                title={FUNDAMENTALLY_STRONG_TOOLTIP}
                              >
                                Strong
                              </span>
                            )}
                          </div>
                          {row.company_name && (
                            <Clip className="text-data-xs text-slate-400">{row.company_name}</Clip>
                          )}
                        </td>
                        <td className="text-right align-top">
                          <PctCell value={row.daily_return_pct} />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel flex min-h-0 min-w-0 flex-col gap-1 p-1">
          {chartError && (
            <div className="flex shrink-0 items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-data-xs text-amber-200">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              <span>{chartError}</span>
            </div>
          )}
          <TimelineStockChart
            symbol={selectedRow?.ticker ?? ""}
            companyName={selectedRow?.company_name}
            source={chartSource}
            history={chartHistory}
            highlightDate={selectedRow?.trade_date ?? tradeDate}
            highlightMovePct={selectedRow?.daily_return_pct ?? null}
            loading={chartLoading}
            fillHeight
          />
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
              <div className="flex h-full min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-surface-border px-3 text-center text-data-sm text-slate-400">
                Select a stock to view fundamentals
              </div>
            )}
          </section>
        )}
      </div>
    </main>
    <CompanyNewsSidebar
      ticker={selectedRow?.ticker}
      companyName={selectedRow?.company_name}
      className="h-[min(45vh,26rem)] shrink-0 border-t lg:h-full lg:border-t-0"
    />
    </div>
  );
}
