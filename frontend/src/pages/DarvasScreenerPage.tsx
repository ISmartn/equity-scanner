import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { Bookmark, Box, Search, Star, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TimelineDatePicker } from "@/components/TimelineDatePicker";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { AppButton } from "@/components/mui";
import {
  Clip,
  FilterReset,
  FilterRow,
  FilterToggle,
  PageToolbar,
  ToolbarDivider,
  filterToggleGroupSx,
} from "@/components/dense";
import {
  fetchScannerDates,
  fetchScannerResults,
  fetchTimelineCandles,
  fetchTimelineSectors,
  type ScannerPatternSignal,
  type TimelineCandlePoint,
} from "@/lib/api";
import { computeDarvasBoxes } from "@/lib/darvasBox";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

const PREFS_KEY = "trading.darvasScreener.prefs";
const WATCHLIST_KEY = "trading.darvasScreener.watchlist";
const NOTES_KEY = "trading.darvasScreener.notes";
const ALL = "all";

type StatusFilter = "all" | "setup" | "trigger";

interface DarvasPrefs extends Record<string, unknown> {
  tradeDate: string;
  search: string;
  sector: string;
  minScore: string;
  status: StatusFilter;
  macroOnly: boolean;
  boxOnly: boolean;
  dryVolumeOnly: boolean;
}

const DEFAULT_PREFS: DarvasPrefs = {
  tradeDate: "",
  search: "",
  sector: ALL,
  minScore: "70",
  status: "all",
  macroOnly: false,
  boxOnly: false,
  dryVolumeOnly: false,
};

function readStringList(key: string): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function readNotes(): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(NOTES_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function detailNumber(row: ScannerPatternSignal, key: string): number | null {
  const value = row.details[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function detailBoolean(row: ScannerPatternSignal, key: string): boolean {
  return row.details[key] === true;
}

function formatPct(value: number | null): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatPrice(value: number | null): string {
  if (value == null) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function StatusPill({ row }: { row: ScannerPatternSignal }) {
  const trigger = row.triggered_today;
  return (
    <span
      className={`rounded border px-1.5 py-px text-[10px] font-medium ${
        trigger
          ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
          : "border-amber-500/40 bg-amber-500/15 text-amber-300"
      }`}
    >
      {trigger ? "Breakout" : "Coil"}
    </span>
  );
}

export function DarvasScreenerPage() {
  const initial = loadUiPrefs(PREFS_KEY, DEFAULT_PREFS);
  const [tradeDate, setTradeDate] = useState(initial.tradeDate);
  const [search, setSearch] = useState(initial.search);
  const [sector, setSector] = useState(initial.sector);
  const [minScore, setMinScore] = useState(initial.minScore);
  const [status, setStatus] = useState<StatusFilter>(initial.status);
  const [macroOnly, setMacroOnly] = useState(initial.macroOnly);
  const [boxOnly, setBoxOnly] = useState(initial.boxOnly);
  const [dryVolumeOnly, setDryVolumeOnly] = useState(initial.dryVolumeOnly);
  const [scanDates, setScanDates] = useState<string[]>([]);
  const [refinedDates, setRefinedDates] = useState<string[]>([]);
  const [sectors, setSectors] = useState<string[]>([]);
  const [rows, setRows] = useState<ScannerPatternSignal[]>([]);
  const [selected, setSelected] = useState<ScannerPatternSignal | null>(null);
  const [history, setHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [loading, setLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState(() => readStringList(WATCHLIST_KEY));
  const [notes, setNotes] = useState<Record<string, string>>(() => readNotes());
  const minScoreNumber = Number(minScore);
  const minScoreInvalid = !Number.isFinite(minScoreNumber) || minScoreNumber < 0 || minScoreNumber > 100;

  useEffect(() => {
    saveUiPrefs(PREFS_KEY, {
      tradeDate,
      search,
      sector,
      minScore,
      status,
      macroOnly,
      boxOnly,
      dryVolumeOnly,
    } satisfies DarvasPrefs);
  }, [tradeDate, search, sector, minScore, status, macroOnly, boxOnly, dryVolumeOnly]);

  useEffect(() => {
    Promise.all([fetchScannerDates(), fetchTimelineSectors()])
      .then(([dates, sectorResult]) => {
        setScanDates(dates.dates);
        setRefinedDates(dates.refined_dates ?? []);
        setSectors(sectorResult.sectors);
        setTradeDate((current) => current || dates.latest_with_alerts || dates.dates[0] || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load scanner metadata"));
  }, []);

  const loadChart = useCallback(async (row: ScannerPatternSignal) => {
    setSelected(row);
    setChartLoading(true);
    setChartError(null);
    try {
      const payload = await fetchTimelineCandles(row.ticker);
      setHistory(payload.history);
      setChartSource(payload.source);
    } catch (err) {
      setHistory([]);
      setChartError(err instanceof Error ? err.message : `No chart data for ${row.ticker}`);
    } finally {
      setChartLoading(false);
    }
  }, []);

  const loadResults = useCallback(async () => {
    if (!tradeDate || minScoreInvalid) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchScannerResults({
        tradeDate,
        pattern: "darvas_pre_setup",
        minScore: minScoreNumber,
        sector: sector === ALL ? undefined : sector,
        macroPassOnly: macroOnly,
        limit: 2000,
        sort: "setup_first",
      });
      setRows(response.results);
      const nextSelected =
        response.results.find((row) => row.ticker === selected?.ticker) ?? response.results[0] ?? null;
      if (nextSelected) {
        void loadChart(nextSelected);
      } else {
        setSelected(null);
        setHistory([]);
      }
    } catch (err) {
      setRows([]);
      setSelected(null);
      setHistory([]);
      setError(err instanceof Error ? err.message : "Failed to load Darvas results");
    } finally {
      setLoading(false);
    }
  }, [tradeDate, minScoreInvalid, minScoreNumber, sector, macroOnly, selected?.ticker, loadChart]);

  useEffect(() => {
    if (!tradeDate || minScoreInvalid) return;
    const timer = window.setTimeout(() => void loadResults(), 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tradeDate, sector, macroOnly, minScoreNumber, minScoreInvalid]);

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (query && !`${row.ticker} ${row.company_name ?? ""}`.toLowerCase().includes(query)) return false;
      if (status === "trigger" && !row.triggered_today) return false;
      if (status === "setup" && !row.setup_ready) return false;
      if (boxOnly && !detailBoolean(row, "darvas_box_like")) return false;
      if (dryVolumeOnly && !detailBoolean(row, "volume_dry")) return false;
      return true;
    });
  }, [rows, search, status, boxOnly, dryVolumeOnly]);

  const boxes = useMemo(() => computeDarvasBoxes(history), [history]);
  const selectedPivot = selected ? detailNumber(selected, "pivot_high_20d") : null;
  const selectedDistance = selected ? detailNumber(selected, "distance_to_pivot_pct") : null;
  const selectedRange = selected ? detailNumber(selected, "range_10d_pct") : null;
  const selectedPre20d = selected ? detailNumber(selected, "pre_20d_return_pct") : null;

  const toggleWatchlist = (ticker: string) => {
    setWatchlist((current) => {
      const next = current.includes(ticker)
        ? current.filter((item) => item !== ticker)
        : [...current, ticker];
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next));
      return next;
    });
  };

  const updateNote = (ticker: string, note: string) => {
    setNotes((current) => {
      const next = { ...current, [ticker]: note };
      localStorage.setItem(NOTES_KEY, JSON.stringify(next));
      return next;
    });
  };

  const activeFilterCount = [
    sector !== ALL,
    minScore !== DEFAULT_PREFS.minScore,
    status !== "all",
    macroOnly,
    boxOnly,
    dryVolumeOnly,
  ].filter(Boolean).length;

  const resetFilters = () => {
    setSector(ALL);
    setMinScore(DEFAULT_PREFS.minScore);
    setStatus("all");
    setMacroOnly(false);
    setBoxOnly(false);
    setDryVolumeOnly(false);
  };

  return (
    <main className="page-shell flex flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error && <Alert severity="error" className="shrink-0 py-0 text-data-sm">{error}</Alert>}

      <PageToolbar
        below={
          <FilterRow>
            <ToggleButtonGroup
              exclusive
              value={status}
              onChange={(_event, value: StatusFilter | null) => value && setStatus(value)}
              sx={filterToggleGroupSx}
              aria-label="State"
            >
              <ToggleButton value="all">All states</ToggleButton>
              <ToggleButton value="setup">Coils</ToggleButton>
              <ToggleButton value="trigger">Breakouts</ToggleButton>
            </ToggleButtonGroup>
            <ToolbarDivider />
            <FilterToggle label="Stage 2" selected={macroOnly} onChange={setMacroOnly} title="Minervini Stage-2 trend template" />
            <FilterToggle label="Box-like" selected={boxOnly} onChange={setBoxOnly} />
            <FilterToggle label="Dry volume" selected={dryVolumeOnly} onChange={setDryVolumeOnly} />
            <ToolbarDivider />
            <TextField
              select
              label="Sector"
              value={sector}
              onChange={(event) => setSector(event.target.value)}
              sx={{ width: 170, flexShrink: 0 }}
            >
              <MenuItem value={ALL}>All sectors</MenuItem>
              {sectors.map((item) => <MenuItem key={item} value={item}>{item}</MenuItem>)}
            </TextField>
            <TextField
              type="number"
              label="Min score"
              value={minScore}
              error={minScoreInvalid}
              onChange={(event) => setMinScore(event.target.value)}
              slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
              sx={{ width: 84, flexShrink: 0 }}
            />
            <FilterReset count={activeFilterCount} onReset={resetFilters} />
          </FilterRow>
        }
      >
        <span className="inline-flex shrink-0 items-center gap-1.5" title="Higher lows · contraction · pivot proximity · volume">
          <Box className="h-4 w-4 text-accent" />
          <h1 className="text-data-md font-semibold text-slate-100">Darvas</h1>
        </span>
        <ToolbarDivider />
        <TimelineDatePicker
          compact
          showLegend={false}
          value={tradeDate}
          onChange={setTradeDate}
          availableDates={scanDates}
          markedDates={scanDates}
          markedLabel="Scan done"
          accentMarkedDates={refinedDates}
          accentMarkedLabel="Darvas scan available"
        />
        <TextField
          label="Symbol"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          slotProps={{ input: { startAdornment: <Search className="mr-1 h-3.5 w-3.5 text-slate-400" /> } }}
          sx={{ width: 145, flexShrink: 0 }}
        />
        <AppButton
          size="small"
          variant="contained"
          className="shrink-0"
          startIcon={<RefreshIcon className={loading ? "animate-spin" : undefined} />}
          disabled={loading || !tradeDate || minScoreInvalid}
          onClick={() => void loadResults()}
        >
          Reload
        </AppButton>
      </PageToolbar>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-1 lg:grid-cols-[minmax(36rem,1.15fr)_minmax(0,1.85fr)]">
        <section className="panel flex min-h-0 flex-col overflow-hidden">
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-surface-border px-2 py-1">
            <div className="flex min-w-0 items-baseline gap-2">
              <h2 className="shrink-0 text-data-md font-semibold text-slate-100">Darvas candidates</h2>
              <span className="truncate text-data-xs tabular-nums text-slate-300">
                {filteredRows.length} matches · {tradeDate || "select a date"}
              </span>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1 text-data-xs text-slate-300">
              <Bookmark className="h-3.5 w-3.5" /> {watchlist.length} saved
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="dt">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>State</th>
                  <th className="text-right">Score</th>
                  <th className="text-right">Pivot</th>
                  <th className="text-right">Distance</th>
                  <th className="text-right">10d range</th>
                  <th>Signals</th>
                </tr>
              </thead>
              <tbody>
                {loading && !rows.length ? (
                  <tr><td colSpan={7} className="py-4 text-center text-slate-400">Loading Darvas scans…</td></tr>
                ) : !filteredRows.length ? (
                  <tr><td colSpan={7} className="py-4 text-center text-slate-400">No Darvas candidates match these filters.</td></tr>
                ) : filteredRows.map((row) => {
                  const active = selected?.ticker === row.ticker;
                  const saved = watchlist.includes(row.ticker);
                  return (
                    <tr
                      key={`${row.trade_date}-${row.ticker}`}
                      onClick={() => void loadChart(row)}
                      className={`dt-row ${active ? "dt-selected" : ""}`}
                    >
                      <td className="max-w-[12rem]">
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            aria-label={saved ? `Remove ${row.ticker} from watchlist` : `Add ${row.ticker} to watchlist`}
                            onClick={(event) => { event.stopPropagation(); toggleWatchlist(row.ticker); }}
                          >
                            <Star className={`h-3.5 w-3.5 ${saved ? "fill-amber-400 text-amber-400" : "text-slate-500"}`} />
                          </button>
                          <span className="ticker">{row.ticker}</span>
                        </div>
                        <Clip className="text-data-xs text-slate-400">{row.company_name ?? row.sector ?? ""}</Clip>
                      </td>
                      <td><StatusPill row={row} /></td>
                      <td className="num text-right text-data-md text-slate-100">{row.score.toFixed(1)}</td>
                      <td className="text-right text-slate-200">{formatPrice(detailNumber(row, "pivot_high_20d"))}</td>
                      <td className="text-right text-slate-200">{formatPct(detailNumber(row, "distance_to_pivot_pct"))}</td>
                      <td className="text-right text-slate-200">{formatPct(detailNumber(row, "range_10d_pct"))}</td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {detailBoolean(row, "darvas_box_like") && <span className="rounded bg-sky-500/15 px-1 text-[10px] leading-[14px] text-sky-300">Box</span>}
                          {detailBoolean(row, "volatility_contraction") && <span className="rounded bg-violet-500/15 px-1 text-[10px] leading-[14px] text-violet-300">VCP</span>}
                          {detailBoolean(row, "volume_dry") && <span className="rounded bg-amber-500/15 px-1 text-[10px] leading-[14px] text-amber-300">Dry</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="flex min-h-0 flex-col gap-1 overflow-hidden">
          {chartError && <Alert severity="warning" className="shrink-0 py-0 text-data-sm">{chartError}</Alert>}
          {selected && (
            <div className="panel shrink-0 px-2 py-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-data-sm">
                <span className="inline-flex items-center gap-1.5">
                  <TrendingUp className="h-3.5 w-3.5 text-accent" />
                  <span className="ticker">{selected.ticker}</span>
                </span>
                <StatusPill row={selected} />
                <span className="text-slate-400">Score <span className="num text-slate-100">{selected.score.toFixed(1)}</span></span>
                <span className="text-slate-400">Pivot <span className="num text-slate-100">{formatPrice(selectedPivot)}</span></span>
                <span className="text-slate-400">Distance <span className="num text-slate-100">{formatPct(selectedDistance)}</span></span>
                <span className="text-slate-400">10d range <span className="num text-slate-100">{formatPct(selectedRange)}</span></span>
                <span className="text-slate-400">20d move <span className="num text-slate-100">{formatPct(selectedPre20d)}</span></span>
              </div>
            </div>
          )}
          <div className="min-h-[260px] flex-1">
            <TimelineStockChart
              symbol={selected?.ticker ?? ""}
              companyName={selected?.company_name}
              sector={selected?.sector}
              source={chartSource}
              history={history}
              highlightDate={selected?.trade_date ?? tradeDate}
              highlightMovePct={selected?.daily_return_pct ?? null}
              loading={chartLoading}
              fillHeight
              tailVisibleRange
              darvasBoxes={boxes}
            />
          </div>
          {selected && (
            <TextField
              multiline
              minRows={1}
              maxRows={3}
              label={`Research note · ${selected.ticker}`}
              value={notes[selected.ticker] ?? ""}
              onChange={(event) => updateNote(selected.ticker, event.target.value)}
              placeholder="Record entry conditions, risk, or follow-up notes…"
              className="shrink-0"
            />
          )}
        </section>
      </div>
    </main>
  );
}
