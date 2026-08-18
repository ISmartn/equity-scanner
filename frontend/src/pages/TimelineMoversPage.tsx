import { TimelineDatePicker } from "@/components/TimelineDatePicker";
import { TimelineDataCoverage } from "@/components/TimelineDataCoverage";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { CompanyNewsSidebar } from "@/components/news/CompanyNewsSidebar";
import { StockFundamentalsPanel } from "@/components/StockFundamentalsPanel";
import { StockTickerSearch } from "@/components/StockTickerSearch";
import { AppButton, FieldLabel } from "@/components/mui";
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
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CalendarClock,
  ClipboardCopy,
  Database,
  PanelRightClose,
  PanelRightOpen,
  Square,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clampWeekday, localTodayIso, nearestWeekday } from "@/lib/dates";
import { FUNDAMENTALLY_STRONG_TOOLTIP } from "@/lib/fundamentalsMeta";
import RefreshIcon from "@mui/icons-material/Refresh";
import Checkbox from "@mui/material/Checkbox";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { needsCandleSync } from "@/lib/timelineCoverage";
import { copyTextToClipboard, moversToExportJson } from "@/lib/timelineExport";

const PAGE_SIZE = 50;

function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function TimelineMoversPage() {
  const [stats, setStats] = useState<TimelineStats | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [dates, setDates] = useState<string[]>([]);
  const [tradeDate, setTradeDate] = useState("");
  const [sector, setSector] = useState("");
  const [minMovePct, setMinMovePct] = useState("5");
  const [direction, setDirection] = useState<"both" | "up" | "down">("both");
  const [ticker, setTicker] = useState("");
  const [fundamentallyStrongOnly, setFundamentallyStrongOnly] = useState(false);
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

  return (
    <div className="flex h-[calc(100dvh-7.25rem)] min-h-0 flex-col lg:flex-row">
    <main className="mx-auto flex min-h-0 min-w-0 max-w-[1920px] flex-1 flex-col gap-2 overflow-hidden px-3 py-2 sm:px-4">
      {syncInfo && (
        <div className="flex shrink-0 items-start gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-1.5 text-xs text-sky-100">
          <Database className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{syncInfo}</span>
        </div>
      )}

      {error && (
        <div className="flex shrink-0 items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Horizontal filter bar — no scroll */}
      <div className="shrink-0 rounded-xl border border-surface-border bg-surface-raised px-3 py-2">
        <div className="mb-2">
          <TimelineDataCoverage stats={stats} />
        </div>
        <Stack direction="row" spacing={1} useFlexGap className="flex-wrap items-end">
          <Stack spacing={0.5}>
            <FieldLabel>Date</FieldLabel>
            <Stack direction="row" spacing={0.75} className="items-center">
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
                  disabled={bootLoading}
                  onClick={() => setTradeDate(today)}
                  title="Jump to today"
                >
                  Today
                </AppButton>
              )}
              {dataIsStale && (
                <Typography variant="caption" className="text-amber-400/90">
                  Behind target {stats?.target_trade_date}
                </Typography>
              )}
            </Stack>
          </Stack>

          <Stack spacing={0.5}>
            <FieldLabel>Stock</FieldLabel>
            <StockTickerSearch
              compact
              value={ticker}
              onChange={handleTickerChange}
              disabled={bootLoading}
              placeholder="Ticker…"
            />
          </Stack>

          <TextField
            size="small"
            type="number"
            label="Move ≥ %"
            value={minMovePct}
            onChange={(e) => setMinMovePct(e.target.value)}
            disabled={Boolean(ticker)}
            slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
            sx={{ width: 96, opacity: ticker ? 0.5 : 1 }}
          />

          <FormControl size="small" sx={{ minWidth: 100, opacity: ticker ? 0.5 : 1 }} disabled={Boolean(ticker)}>
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

          <Stack spacing={0.5} sx={{ opacity: ticker ? 0.5 : 1 }}>
            <FieldLabel>Direction</FieldLabel>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={direction}
              onChange={(_, value: typeof direction | null) => {
                if (value) setDirection(value);
              }}
              disabled={Boolean(ticker)}
            >
              {(["both", "up", "down"] as const).map((value) => (
                <ToggleButton key={value} value={value} sx={{ textTransform: "capitalize", px: 1.25 }}>
                  {value}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Stack>

          <FormControlLabel
            className="!mr-0 self-end"
            sx={{ opacity: ticker ? 0.5 : 1, height: 40 }}
            control={
              <Checkbox
                size="small"
                checked={fundamentallyStrongOnly}
                onChange={(e) => setFundamentallyStrongOnly(e.target.checked)}
                disabled={Boolean(ticker)}
              />
            }
            label={
              <span className="text-[10px] text-slate-300" title={FUNDAMENTALLY_STRONG_TOOLTIP}>
                Strong Fund
              </span>
            }
          />

          <AppButton
            variant="contained"
            size="small"
            startIcon={
              <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
            }
            onClick={handleSearch}
            disabled={loading || !tradeDate || filterInvalid}
          >
            Search
          </AppButton>

          <Stack direction="row" spacing={0.75} className="ml-auto items-center">
            {stats && (
              <span className="hidden items-center gap-1 text-[11px] text-slate-400 sm:flex">
                <Database className="h-3.5 w-3.5" />
                {stats.symbols_at_max_date.toLocaleString()}/{stats.profile_count.toLocaleString()}
              </span>
            )}
            <AppButton
              size="small"
              onClick={handleSyncProfiles}
              disabled={syncing || reprofiling || uptoDateRunning}
              title="Sync NSE profiles"
            >
              {syncing ? "Syncing…" : "Sync"}
            </AppButton>
            <AppButton
              size="small"
              onClick={handleReprofileStale}
              disabled={syncing || reprofiling || uptoDateRunning}
              title="Refresh profiles, migrate ISINs, skip delisted symbols in ingest"
              className="hover:border-amber-500/40 hover:text-amber-200"
            >
              {reprofiling ? "Reprofiling…" : "Reprofile"}
            </AppButton>
            <AppButton
              size="small"
              variant={uptoDateRunning ? "outlined" : "contained"}
              color={uptoDateRunning ? "error" : "primary"}
              onClick={uptoDateRunning ? handleStopIngest : handleUptoDate}
              disabled={
                syncing ||
                reprofiling ||
                ingestStopping ||
                (!uptoDateRunning && (stats?.profile_count ?? 0) === 0)
              }
              title={
                uptoDateRunning
                  ? "Stop candle sync after the current symbol"
                  : candleSyncNeeded
                    ? `Fetch missing candles through ${stats?.target_trade_date ?? "today"}`
                    : `Data current through ${stats?.max_trade_date ?? "—"}`
              }
              startIcon={
                uptoDateRunning ? (
                  <Square className={`h-3 w-3 ${ingestStopping ? "animate-pulse" : ""}`} />
                ) : (
                  <CalendarClock className="h-3.5 w-3.5" />
                )
              }
            >
              {uptoDateRunning
                ? ingestStopping || ingestStatus?.cancel_requested
                  ? "Stopping…"
                  : "Stop"
                : candleSyncNeeded
                  ? "Up-to-date"
                  : "Current"}
            </AppButton>
          </Stack>
        </Stack>

        {uptoDateRunning && ingestStatus && (
          <div className="mt-2 space-y-1.5 border-t border-surface-border pt-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
              <span>
                Updating stocks
                {ingestStatus.current_ticker ? (
                  <>
                    {" · "}
                    <span className="font-medium text-slate-200">{ingestStatus.current_ticker}</span>
                  </>
                ) : null}
              </span>
              <span className="tabular-nums">
                {ingestStatus.processed.toLocaleString()} / {ingestStatus.total.toLocaleString()}
                {ingestStatus.total > 0 ? ` (${ingestProgressPct}%)` : ""}
              </span>
              {(ingestStopping || ingestStatus.cancel_requested) && (
                <span className="text-amber-400">Stopping after current symbol…</span>
              )}
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${ingestProgressPct}%` }}
              />
            </div>
            <div className="flex flex-wrap gap-3 text-[10px] text-slate-500">
              {ingestStatus.success > 0 && (
                <span className="text-emerald-400">
                  {ingestStatus.success.toLocaleString()} new bars
                </span>
              )}
              {(ingestStatus.empty ?? 0) > 0 && (
                <span className="text-amber-400/90">
                  {(ingestStatus.empty ?? 0).toLocaleString()} no new data
                </span>
              )}
              <span>{ingestStatus.skipped.toLocaleString()} skipped</span>
              {ingestStatus.failed > 0 && (
                <span className="text-red-400">{ingestStatus.failed.toLocaleString()} failed</span>
              )}
              <span>{ingestStatus.total_bars.toLocaleString()} bars written</span>
              <span className="text-slate-600">3 parallel connections</span>
            </div>
            {ingestStatus.recent_errors && ingestStatus.recent_errors.length > 0 && (
              <div className="max-h-20 overflow-y-auto rounded border border-red-500/20 bg-red-500/5 px-2 py-1 text-[9px] text-red-200/90">
                {ingestStatus.recent_errors.slice(0, 8).map((row) => (
                  <div key={row.ticker} className="truncate">
                    <span className="font-medium text-red-100">{row.ticker}</span>: {row.error}
                  </div>
                ))}
                {ingestStatus.failed > ingestStatus.recent_errors.length && (
                  <div className="text-red-300/80">
                    +{(ingestStatus.failed - ingestStatus.recent_errors.length).toLocaleString()} more in{" "}
                    {ingestStatus.error_log ?? "candle_ingest_errors.log"}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Movers list | chart | fundamentals */}
      <div
        className={`grid min-h-0 flex-1 grid-cols-1 gap-2 ${
          showFundamentals
            ? "lg:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)_minmax(16rem,22rem)] xl:grid-cols-[17rem_minmax(0,1fr)_minmax(18rem,24rem)]"
            : "lg:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)] xl:grid-cols-[17rem_minmax(0,1fr)]"
        }`}
      >
        <section className="flex min-h-0 min-w-0 flex-col rounded-xl border border-surface-border bg-surface-raised/60 lg:max-w-[18rem] xl:max-w-[20rem]">
          <div className="flex shrink-0 items-center justify-between gap-1 border-b border-surface-border px-2 py-1.5">
            <div className="min-w-0">
              <h2 className="text-[11px] font-semibold text-slate-100">Daily movers</h2>
              <p className="truncate text-[9px] text-slate-500">
                {!hasSearched
                  ? "Run a search"
                  : ticker
                    ? `${total ? "1 stock" : "No data"} · ${ticker} · ${tradeDate}`
                    : `${total.toLocaleString()} matches · ${tradeDate}`}
              </p>
            </div>
            {hasSearched && (
              <div className="flex shrink-0 items-center gap-0.5 text-[9px] text-slate-400">
                <button
                  type="button"
                  disabled={!exportRows.length || copyingJson}
                  onClick={handleCopyJson}
                  title="Copy all search results as JSON"
                  className="inline-flex items-center gap-1 rounded border border-surface-border px-1.5 py-0.5 text-slate-300 transition hover:border-accent/40 hover:text-slate-100 disabled:opacity-40"
                >
                  <ClipboardCopy className={`h-3 w-3 ${copyingJson ? "animate-pulse" : ""}`} />
                  JSON
                </button>
                {page + 1}/{totalPages}
                <button
                  type="button"
                  disabled={page <= 0 || loading}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className="rounded border border-surface-border px-1.5 py-0.5 disabled:opacity-40"
                >
                  ‹
                </button>
                <button
                  type="button"
                  disabled={page + 1 >= totalPages || loading}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded border border-surface-border px-1.5 py-0.5 disabled:opacity-40"
                >
                  ›
                </button>
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 z-10 bg-surface-raised text-[9px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-2 py-1">Ticker</th>
                  <th className="px-2 py-1 text-right">Move</th>
                </tr>
              </thead>
              <tbody>
                {loading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-2 py-4 text-center text-[11px] text-slate-500">
                      Loading…
                    </td>
                  </tr>
                ) : !hasSearched ? (
                  <tr>
                    <td colSpan={2} className="px-2 py-4 text-center text-[11px] text-slate-500">
                      Set filters and search
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-2 py-3 text-center text-[11px] text-slate-500">
                      {dateNeedsIngest ? (
                        <div className="space-y-2">
                          <p>
                            No local data for <span className="text-slate-300">{tradeDate}</span>.
                            {latestDataDate ? (
                              <>
                                {" "}
                                Latest ingested trading day is{" "}
                                <span className="text-slate-300">{latestDataDate}</span>.
                              </>
                            ) : null}
                          </p>
                          <p className="text-[10px] text-slate-600">
                            Run Up-to-date to fetch missing days from Upstox (~30–60 min for all
                            stocks). Failures are logged per symbol.
                          </p>
                          <button
                            type="button"
                            onClick={handleUptoDate}
                            disabled={uptoDateRunning || (stats?.profile_count ?? 0) === 0}
                            className="inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent/10 px-2.5 py-1 text-[11px] font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50"
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
                    const move = row.daily_return_pct ?? 0;
                    const isUp = move >= 0;
                    const isSelected = selectedRow?.ticker === row.ticker;
                    return (
                      <tr
                        key={`${row.ticker}-${row.trade_date}`}
                        onClick={() => loadChart(row)}
                        className={`cursor-pointer border-t border-surface-border/60 transition ${
                          isSelected
                            ? "bg-accent/10 hover:bg-accent/15"
                            : "hover:bg-surface/40"
                        }`}
                      >
                        <td className="px-2 py-1 text-[11px] font-medium text-slate-100">
                          <div className="flex items-center gap-1">
                            <span>{row.ticker}</span>
                            {strongSymbolSet.has(row.ticker.toUpperCase()) && (
                              <span
                                className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1 py-px text-[8px] font-medium text-emerald-300"
                                title={FUNDAMENTALLY_STRONG_TOOLTIP}
                              >
                                Strong
                              </span>
                            )}
                          </div>
                        </td>
                        <td
                          className={`px-2 py-1 text-right tabular-nums text-[10px] font-medium ${
                            isUp ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          <span className="inline-flex items-center justify-end gap-0.5">
                            {isUp ? (
                              <ArrowUp className="h-2.5 w-2.5" />
                            ) : (
                              <ArrowDown className="h-2.5 w-2.5" />
                            )}
                            {formatPct(row.daily_return_pct)}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {copyMessage && (
            <p className="shrink-0 border-t border-surface-border px-3 py-1 text-[10px] text-emerald-400">
              {copyMessage}
            </p>
          )}

          {hasSearched && exportRows.length > 0 && (
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
                  className="h-36 w-full resize-none border-t border-surface-border bg-surface px-3 py-2 font-mono text-[10px] leading-relaxed text-slate-300 outline-none"
                />
              )}
            </div>
          )}
        </section>

        <section className="flex min-h-0 min-w-0 flex-col gap-1 rounded-xl border border-surface-border bg-surface-raised/30 p-1">
          <div className="flex shrink-0 items-center justify-end px-1">
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
          </div>
          {chartError && (
            <div className="flex shrink-0 items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
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
              <div className="flex h-full min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-surface-border px-3 text-center text-xs text-slate-500">
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
