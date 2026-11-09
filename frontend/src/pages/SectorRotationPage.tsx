import { useCallback, useEffect, useMemo, useState } from "react";
import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { RRGScatterChart } from "@/components/sectorRotation/RRGScatterChart";
import { SectorConstituentsPanel } from "@/components/sectorRotation/SectorConstituentsPanel";
import {
  SectorScanTable,
  type SectorTableFilter,
} from "@/components/sectorRotation/SectorScanTable";
import { AppButton } from "@/components/mui/AppButton";
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
import {
  fetchSectorRotation,
  fetchSectorRotationConstituents,
  fetchTimelineCandles,
  type SectorConstituentRow,
  type SectorConstituentsResponse,
  type SectorRotationResponse,
  type SectorRotationRow,
  type TimelineCandlePoint,
} from "@/lib/api";

type SortKey = "surety_score" | "daily_change_pct" | "rs_ratio" | "name";

const FILTER_KEY = "trading.sectorRotation.filter";
const SORT_KEY = "trading.sectorRotation.sortKey";
const SORT_DIR_KEY = "trading.sectorRotation.sortDir";

const FILTERS: SectorTableFilter[] = [
  "all",
  "stealth",
  "price_action",
  "improving",
  "leading",
];
const SORT_KEYS: SortKey[] = ["surety_score", "daily_change_pct", "rs_ratio", "name"];

function readFilter(): SectorTableFilter {
  try {
    const v = localStorage.getItem(FILTER_KEY);
    if (v && (FILTERS as string[]).includes(v)) return v as SectorTableFilter;
  } catch {
    /* ignore */
  }
  return "all";
}

function readSortKey(): SortKey {
  try {
    const v = localStorage.getItem(SORT_KEY);
    if (v && (SORT_KEYS as string[]).includes(v)) return v as SortKey;
  } catch {
    /* ignore */
  }
  return "surety_score";
}

function readSortDir(): "asc" | "desc" {
  try {
    const v = localStorage.getItem(SORT_DIR_KEY);
    if (v === "asc" || v === "desc") return v;
  } catch {
    /* ignore */
  }
  return "desc";
}

export function SectorRotationPage() {
  const [data, setData] = useState<SectorRotationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SectorTableFilter>(readFilter);
  const [sortKey, setSortKey] = useState<SortKey>(readSortKey);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(readSortDir);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [constituents, setConstituents] = useState<SectorConstituentsResponse | null>(null);
  const [constituentsLoading, setConstituentsLoading] = useState(false);
  const [constituentsError, setConstituentsError] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartHistory, setChartHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartSource, setChartSource] = useState("local");
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const [syncNote, setSyncNote] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    if (refresh) setSyncNote(null);
    try {
      const payload = await fetchSectorRotation(refresh);
      setData(payload);
      setSelectedName((prev) => {
        if (prev && payload.sectors.some((s) => s.name === prev)) return prev;
        return payload.sectors[0]?.name ?? null;
      });
      const sync = payload.benchmark_sync;
      if (sync) {
        if (sync.status === "unauthorized") {
          setSyncNote(
            "Benchmark candles could not be synced — add your Upstox token in Settings, then refresh again.",
          );
        } else if (sync.status === "failed") {
          setSyncNote(`Benchmark sync failed: ${sync.detail ?? "unknown error"}`);
        } else if (sync.upserted > 0) {
          setSyncNote(`Synced ${sync.upserted} new ${payload.benchmark} bars.`);
        } else {
          setSyncNote("Benchmark already up to date.");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sector rotation");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    try {
      localStorage.setItem(FILTER_KEY, filter);
    } catch {
      /* ignore */
    }
  }, [filter]);

  useEffect(() => {
    try {
      localStorage.setItem(SORT_KEY, sortKey);
      localStorage.setItem(SORT_DIR_KEY, sortDir);
    } catch {
      /* ignore */
    }
  }, [sortKey, sortDir]);

  useEffect(() => {
    if (!selectedName) {
      setConstituents(null);
      setConstituentsError(null);
      setSelectedTicker(null);
      return;
    }
    const requestName = selectedName;
    let cancelled = false;
    setConstituentsLoading(true);
    setConstituentsError(null);
    setConstituents((prev) => (prev?.sector === requestName ? prev : null));
    setSelectedTicker(null);

    void fetchSectorRotationConstituents(requestName)
      .then((payload) => {
        if (!cancelled) setConstituents(payload);
      })
      .catch((err) => {
        if (!cancelled) {
          setConstituents(null);
          setConstituentsError(
            err instanceof Error ? err.message : "Failed to load constituents",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setConstituentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedName]);

  useEffect(() => {
    if (!selectedTicker) {
      setChartHistory([]);
      setChartError(null);
      return;
    }
    let cancelled = false;
    setChartLoading(true);
    setChartError(null);
    void fetchTimelineCandles(selectedTicker)
      .then((payload) => {
        if (cancelled) return;
        setChartHistory(payload.history);
        setChartSource(payload.source);
      })
      .catch((err) => {
        if (cancelled) return;
        setChartHistory([]);
        setChartError(err instanceof Error ? err.message : "Failed to load chart");
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTicker]);

  const selected: SectorRotationRow | null = useMemo(() => {
    if (!data || !selectedName) return null;
    return data.sectors.find((s) => s.name === selectedName) ?? null;
  }, [data, selectedName]);

  const selectedStock: SectorConstituentRow | null = useMemo(() => {
    if (!selectedTicker || !constituents) return null;
    return constituents.constituents.find((c) => c.ticker === selectedTicker) ?? null;
  }, [constituents, selectedTicker]);

  const highlightDate =
    constituents?.as_of ??
    chartHistory[chartHistory.length - 1]?.date ??
    "";

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  };

  const handleSelectSector = (name: string) => {
    setSelectedName(name);
  };

  const summary = data?.summary;
  const showStockChart = Boolean(selectedTicker);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  return (
    <div className="page-shell flex flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0 py-0 text-data-sm">
          {error}
        </Alert>
      ) : null}

      <PageToolbar
        right={
          <>
            {data?.benchmark_stale ? (
              <button
                type="button"
                onClick={() => setAdvancedOpen(true)}
                title={`RS is ${data.rs_lag_days}d behind prices — open Advanced to sync`}
                className="inline-flex h-7 shrink-0 items-center rounded-md border border-amber-500/50 bg-amber-500/15 px-2 text-data-xs font-semibold text-amber-200 hover:bg-amber-500/25"
              >
                Benchmark stale
              </button>
            ) : null}
            <AdvancedButton onClick={() => setAdvancedOpen(true)} label="Details" />
          </>
        }
        below={
          syncNote && !advancedOpen ? (
            <div className="flex items-center justify-between gap-2 text-data-xs text-sky-100">
              <span>{syncNote}</span>
              <button
                type="button"
                onClick={() => setSyncNote(null)}
                className="shrink-0 text-sky-300 hover:text-white"
                aria-label="Dismiss sync note"
              >
                Dismiss
              </button>
            </div>
          ) : undefined
        }
      >
        <h1 className="shrink-0 text-data-md font-semibold text-slate-100" title="Sector Rotation & Themes">
          Sector Rotation
        </h1>
        <ToolbarDivider />
        <ToggleButtonGroup
          exclusive
          value={filter}
          onChange={(_e, value: SectorTableFilter | null) => {
            if (value) setFilter(value);
          }}
          sx={{ flexShrink: 0, "& .MuiToggleButton-root": { textTransform: "none" } }}
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="stealth">Stealth Accumulation</ToggleButton>
          <ToggleButton value="price_action">Price Action</ToggleButton>
          <ToggleButton value="improving">Next Bullish</ToggleButton>
          <ToggleButton value="leading">Leading</ToggleButton>
        </ToggleButtonGroup>
        {summary ? (
          <>
            <ToolbarDivider />
            <StatChip label="Sectors" value={summary.total} />
            <StatChip label="Leading" value={summary.leading} valueClassName="text-emerald-300" />
            <StatChip label="Improving" value={summary.improving} valueClassName="text-sky-300" />
            <StatChip label="Stealth" value={summary.stealth_accumulation} valueClassName="text-violet-300" />
            <StatChip label="PA" hint="Price action confirmed" value={summary.price_action_confirmed} valueClassName="text-amber-300" />
          </>
        ) : null}
        {loading ? <span className="shrink-0 text-data-xs text-slate-400">Updating…</span> : null}
      </PageToolbar>

      <div className="grid min-h-0 flex-1 gap-1 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.2fr)]">
        <div className="min-h-0">
          {showStockChart ? (
            <div className="panel flex h-full min-h-0 flex-col overflow-hidden">
              <div className="flex shrink-0 items-center gap-2 border-b border-surface-border px-2 py-1">
                <button
                  type="button"
                  onClick={() => setSelectedTicker(null)}
                  className="shrink-0 text-data-xs text-sky-300 hover:text-sky-200"
                >
                  ← RRG
                </button>
                <span className="ticker shrink-0">{selectedTicker}</span>
                {selectedStock?.company_name ? (
                  <Clip className="text-data-xs text-slate-400">{selectedStock.company_name}</Clip>
                ) : null}
                {selectedStock?.change_1d_pct != null ? (
                  <PctCell value={selectedStock.change_1d_pct} className="ml-auto shrink-0 text-data-sm" />
                ) : null}
              </div>
              {chartError ? (
                <div className="px-2 py-1 text-data-sm text-loss">{chartError}</div>
              ) : null}
              <div className="min-h-0 flex-1 p-1">
                <TimelineStockChart
                  symbol={selectedTicker ?? ""}
                  companyName={selectedStock?.company_name}
                  sector={selectedName}
                  source={chartSource}
                  history={chartHistory}
                  highlightDate={highlightDate}
                  highlightMovePct={selectedStock?.change_1d_pct ?? null}
                  loading={chartLoading}
                  fillHeight
                  tailVisibleRange
                />
              </div>
            </div>
          ) : (
            <RRGScatterChart
              sectors={data?.sectors ?? []}
              selectedName={selectedName}
              onSelect={handleSelectSector}
            />
          )}
        </div>
        <div className="flex min-h-0 flex-col gap-1">
          <div className="min-h-0 flex-[0.95]">
            <SectorScanTable
              sectors={data?.sectors ?? []}
              filter={filter}
              sortKey={sortKey}
              sortDir={sortDir}
              selectedName={selectedName}
              onSelect={handleSelectSector}
              onSort={handleSort}
            />
          </div>
          <div className="min-h-[220px] flex-[1.15]">
            <SectorConstituentsPanel
              sectorName={selectedName}
              data={constituents}
              loading={constituentsLoading}
              error={constituentsError}
              selectedTicker={selectedTicker}
              onSelectTicker={setSelectedTicker}
            />
          </div>
        </div>
      </div>

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Sector rotation details"
        subtitle={`Benchmark ${data?.benchmark ?? "Nifty 50"}`}
      >
        {selected ? (
          <AdvancedSection title="Selected sector">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-data-md font-semibold text-slate-100">{selected.name}</span>
              {selected.category === "Official" ? (
                <span className="rounded border border-amber-400/50 bg-amber-500/15 px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-200">
                  Index
                </span>
              ) : (
                <span className="rounded border border-slate-500/40 bg-slate-500/10 px-1 py-px text-[10px] uppercase tracking-wide text-slate-300">
                  Theme
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <StatChip label="Surety" value={selected.surety_score} />
              <StatChip label="Quadrant" value={selected.quadrant} />
              {selected.rotation_path ? <StatChip label="Path" value={selected.rotation_path} /> : null}
            </div>
            <p className="text-data-sm leading-relaxed text-slate-200">
              {selected.rotation_note}
              {selected.rs_momentum_delta_5d != null || selected.rs_ratio_delta_5d != null ? (
                <span className="ml-1 text-slate-400">
                  (RS{" "}
                  {selected.rs_ratio_delta_5d != null && selected.rs_ratio_delta_5d >= 0 ? "+" : ""}
                  {selected.rs_ratio_delta_5d?.toFixed(1) ?? "—"} · Mom{" "}
                  {selected.rs_momentum_delta_5d != null && selected.rs_momentum_delta_5d >= 0
                    ? "+"
                    : ""}
                  {selected.rs_momentum_delta_5d?.toFixed(1) ?? "—"} / 5d)
                </span>
              ) : null}
            </p>
          </AdvancedSection>
        ) : null}

        <AdvancedSection title="Data">
          <div className="space-y-0.5 text-data-xs text-slate-300">
            <div>
              Benchmark <span className="text-slate-100">{data?.benchmark ?? "Nifty 50"}</span>
            </div>
            {data?.price_as_of ? (
              <div>
                Prices as of <span className="num text-slate-100">{data.price_as_of}</span>
              </div>
            ) : null}
            {data?.rs_as_of ? (
              <div>
                RS as of <span className="num text-slate-100">{data.rs_as_of}</span>
              </div>
            ) : null}
          </div>
          {data?.benchmark_stale ? (
            <Alert severity="warning" className="py-0 text-data-xs">
              {data.benchmark} candles end {data.benchmark_as_of}, but sector prices run to{" "}
              {data.price_as_of}. RS ratio, momentum and quadrants are as of {data.rs_as_of} (
              {data.rs_lag_days}d behind). Refresh with an Upstox token to sync the benchmark.
            </Alert>
          ) : null}
          {syncNote ? (
            <Alert severity="info" onClose={() => setSyncNote(null)} className="py-0 text-data-xs">
              {syncNote}
            </Alert>
          ) : null}
          <AppButton
            size="small"
            startIcon={
              <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
            }
            onClick={() => void load(true)}
            disabled={loading}
          >
            Refresh
          </AppButton>
        </AdvancedSection>

        <AdvancedSection title="Help" defaultOpen={false}>
          <div className="flex flex-wrap gap-3 text-data-xs">
            <span className="text-amber-200/90">◆ Official index</span>
            <span className="text-slate-300">● Theme</span>
          </div>
        </AdvancedSection>
      </AdvancedDrawer>
    </div>
  );
}
