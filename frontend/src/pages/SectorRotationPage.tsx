import { useCallback, useEffect, useMemo, useState } from "react";
import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { TimelineStockChart } from "@/components/TimelineStockChart";
import { RRGScatterChart } from "@/components/sectorRotation/RRGScatterChart";
import { SectorConstituentsPanel } from "@/components/sectorRotation/SectorConstituentsPanel";
import {
  SectorScanTable,
  type SectorTableFilter,
} from "@/components/sectorRotation/SectorScanTable";
import { AppButton } from "@/components/mui/AppButton";
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

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchSectorRotation(refresh);
      setData(payload);
      setSelectedName((prev) => {
        if (prev && payload.sectors.some((s) => s.name === prev)) return prev;
        return payload.sectors[0]?.name ?? null;
      });
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

  return (
    <div className="mx-auto flex h-[calc(100dvh-6.5rem)] max-w-[1600px] flex-col gap-2 overflow-hidden px-2 py-2 sm:px-4">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0">
          {error}
        </Alert>
      ) : null}

      <div className="shrink-0 rounded-xl border border-surface-border bg-surface-raised px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div>
            <Typography className="text-[13px] font-semibold text-slate-100">
              Sector Rotation & Themes
            </Typography>
            <Typography className="text-[10px] text-slate-500">
              Benchmark {data?.benchmark ?? "Nifty 50"}
              {data?.benchmark_as_of ? ` · as of ${data.benchmark_as_of}` : ""}
              {loading ? " · Updating…" : ""}
              {" · "}
              <span className="text-amber-200/90">◆ Official index</span>
              {" · "}
              <span className="text-slate-400">● Theme</span>
            </Typography>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
            {summary ? (
              <>
                <span>
                  <span className="font-medium text-slate-200">{summary.total}</span> sectors
                </span>
                <span className="text-emerald-300">Leading {summary.leading}</span>
                <span className="text-sky-300">Improving {summary.improving}</span>
                <span className="text-violet-300">Stealth {summary.stealth_accumulation}</span>
                <span className="text-amber-300">PA {summary.price_action_confirmed}</span>
              </>
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
          </div>
        </div>

        <ToggleButtonGroup
          exclusive
          size="small"
          value={filter}
          onChange={(_e, value: SectorTableFilter | null) => {
            if (value) setFilter(value);
          }}
          className="mt-2 flex flex-wrap"
          sx={{ "& .MuiToggleButton-root": { textTransform: "none", fontSize: "0.7rem", px: 1.25 } }}
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="stealth">Stealth Accumulation</ToggleButton>
          <ToggleButton value="price_action">Price Action</ToggleButton>
          <ToggleButton value="improving">Next Bullish</ToggleButton>
          <ToggleButton value="leading">Leading</ToggleButton>
        </ToggleButtonGroup>
      </div>

      <div className="grid min-h-0 flex-1 gap-2 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.2fr)]">
        <div className="min-h-0">
          {showStockChart ? (
            <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
              <div className="flex shrink-0 items-center gap-2 border-b border-surface-border px-3 py-1.5">
                <button
                  type="button"
                  onClick={() => setSelectedTicker(null)}
                  className="text-[10px] text-sky-300 hover:text-sky-200"
                >
                  ← RRG
                </button>
                <Typography className="text-[12px] font-medium text-slate-100">
                  {selectedTicker}
                  {selectedStock?.company_name ? (
                    <span className="ml-2 text-[10px] font-normal text-slate-500">
                      {selectedStock.company_name}
                    </span>
                  ) : null}
                </Typography>
                {selectedStock?.change_1d_pct != null ? (
                  <span
                    className={`ml-auto text-[11px] tabular-nums ${
                      selectedStock.change_1d_pct >= 0 ? "text-emerald-300" : "text-rose-300"
                    }`}
                  >
                    {selectedStock.change_1d_pct >= 0 ? "+" : ""}
                    {selectedStock.change_1d_pct.toFixed(2)}%
                  </span>
                ) : null}
              </div>
              {chartError ? (
                <div className="px-3 py-1.5 text-[11px] text-rose-300">{chartError}</div>
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
        <div className="flex min-h-0 flex-col gap-2">
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
          {selected ? (
            <div className="shrink-0 rounded-xl border border-surface-border bg-surface-raised px-3 py-1.5">
              <Typography className="text-[11px] font-medium text-slate-100">
                {selected.name}
                {selected.category === "Official" ? (
                  <span className="ml-1.5 rounded border border-amber-400/50 bg-amber-500/15 px-1 py-px text-[8px] font-semibold uppercase tracking-wide text-amber-200">
                    Index
                  </span>
                ) : (
                  <span className="ml-1.5 rounded border border-slate-500/40 bg-slate-500/10 px-1 py-px text-[8px] uppercase tracking-wide text-slate-400">
                    Theme
                  </span>
                )}
                <span className="ml-2 text-[10px] font-normal text-slate-500">
                  surety {selected.surety_score} · {selected.quadrant}
                  {selected.rotation_path ? ` · ${selected.rotation_path}` : ""}
                </span>
              </Typography>
              <Typography className="mt-0.5 text-[10px] text-slate-400">
                {selected.rotation_note}
                {selected.rs_momentum_delta_5d != null || selected.rs_ratio_delta_5d != null ? (
                  <span className="ml-1 text-slate-500">
                    (RS{" "}
                    {selected.rs_ratio_delta_5d != null && selected.rs_ratio_delta_5d >= 0 ? "+" : ""}
                    {selected.rs_ratio_delta_5d?.toFixed(1) ?? "—"} · Mom{" "}
                    {selected.rs_momentum_delta_5d != null && selected.rs_momentum_delta_5d >= 0
                      ? "+"
                      : ""}
                    {selected.rs_momentum_delta_5d?.toFixed(1) ?? "—"} / 5d)
                  </span>
                ) : null}
              </Typography>
            </div>
          ) : null}
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
    </div>
  );
}
