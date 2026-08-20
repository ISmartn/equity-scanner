import { useCallback, useEffect, useState } from "react";
import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";
import { AppButton } from "@/components/mui/AppButton";
import {
  fetchElliottWaveChart,
  fetchElliottWaveSummary,
  type ElliottWaveChartPayload,
  type ElliottWaveFilter,
  type ElliottWaveRow,
  type ElliottWaveSummaryResponse,
} from "@/lib/api";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";
import { WaveBeginnerGuide } from "./WaveBeginnerGuide";
import { WaveChartRenderer } from "./WaveChartRenderer";
import { WaveScannerTable } from "./WaveScannerTable";

const PREFS_KEY = "trading.elliottWaveLab.prefs";
type LabPrefs = { filter: ElliottWaveFilter; beginnerGuide: boolean };
const DEFAULT_PREFS: LabPrefs = { filter: "all", beginnerGuide: false };

export function ElliottWaveLabPage() {
  const initial = loadUiPrefs(PREFS_KEY, DEFAULT_PREFS);
  const [data, setData] = useState<ElliottWaveSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ElliottWaveFilter>(
    initial.filter === "wave3" ||
      initial.filter === "wave4" ||
      initial.filter === "high_surety"
      ? initial.filter
      : "all",
  );
  const [beginnerGuide, setBeginnerGuide] = useState(Boolean(initial.beginnerGuide));
  const [selected, setSelected] = useState<ElliottWaveRow | null>(null);
  const [chart, setChart] = useState<ElliottWaveChartPayload | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchElliottWaveSummary(refresh);
      setData(payload);
      setSelected((prev) => {
        if (prev && payload.results.some((r) => r.instrument_key === prev.instrument_key)) {
          return prev;
        }
        return payload.results[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Elliott Wave lab");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    saveUiPrefs(PREFS_KEY, { filter, beginnerGuide } satisfies LabPrefs);
  }, [filter, beginnerGuide]);

  useEffect(() => {
    if (!selected) {
      setChart(null);
      return;
    }
    let cancelled = false;
    setChartLoading(true);
    setChartError(null);
    void fetchElliottWaveChart(selected.instrument_key)
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
  }, [selected?.instrument_key]);

  const summary = data?.summary;
  const guideSource = chart?.guide ?? null;
  const displayPrice = chart?.candles?.length
    ? chart.candles[chart.candles.length - 1]?.close
    : selected?.price;

  return (
    <div className="mx-auto flex h-[calc(100dvh-6.5rem)] max-w-[1600px] flex-col gap-2 overflow-hidden px-2 py-2 sm:px-4">
      <Alert severity="warning" className="shrink-0">
        Experimental Feature: Models may repaint — Elliott / Neo-Wave counts are heuristic and can
        change as new pivots form. Local DB only; not investment advice.
      </Alert>

      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0">
          {error}
        </Alert>
      ) : null}

      <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-xl border border-surface-border bg-surface-raised px-3 py-2">
        <div>
          <Typography className="text-[13px] font-semibold text-slate-100">
            Elliott Wave Lab
          </Typography>
          <Typography className="text-[10px] text-slate-500">
            F&O underlyings + Nifty 50 · daily ZigZag (ATR×2.5) · impulse / zigzag rules
            {data ? ` · ${data.analyzed}/${data.universe_size} analyzed` : ""}
            {loading ? " · Scanning…" : ""}
          </Typography>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
          {summary ? (
            <>
              <span className="text-sky-300">W3 {summary.wave_3_breakouts}</span>
              <span className="text-amber-300">W4 {summary.wave_4_dips}</span>
              <span className="text-emerald-300">Surety≥75 {summary.high_surety}</span>
            </>
          ) : null}
          <FormControlLabel
            className="ml-1 mr-0"
            control={
              <Switch
                size="small"
                checked={beginnerGuide}
                onChange={(_e, checked) => setBeginnerGuide(checked)}
              />
            }
            label={
              <span className="text-[11px] text-slate-300">Beginner guide</span>
            }
          />
          <AppButton
            size="small"
            startIcon={
              <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
            }
            onClick={() => void load(true)}
            disabled={loading}
          >
            Rescan
          </AppButton>
        </div>
      </div>

      <div
        className={`grid min-h-0 flex-1 gap-2 ${
          beginnerGuide
            ? "lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1fr)_minmax(0,0.85fr)]"
            : "lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1.1fr)]"
        }`}
      >
        <div className="min-h-0">
          <WaveScannerTable
            rows={data?.results ?? []}
            filter={filter}
            onFilterChange={setFilter}
            selectedKey={selected?.instrument_key ?? null}
            onSelect={setSelected}
          />
        </div>
        <div className="flex min-h-0 flex-col gap-2">
          {chartError ? (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
              {chartError}
            </div>
          ) : null}
          {beginnerGuide && (chart?.current_wave || selected?.current_wave) ? (
            <div className="shrink-0 rounded-lg border border-violet-500/25 bg-violet-500/10 px-3 py-1.5 text-[11px] text-violet-100">
              <span className="font-medium">
                {chart?.current_wave ?? selected?.current_wave}
              </span>
              <span className="mx-1.5 text-violet-400/80">·</span>
              <span
                className={
                  (chart?.trend ?? selected?.trend) === "Uptrend"
                    ? "text-emerald-300"
                    : (chart?.trend ?? selected?.trend) === "Downtrend"
                      ? "text-rose-300"
                      : "text-slate-300"
                }
              >
                {chart?.trend ?? selected?.trend}
              </span>
            </div>
          ) : null}
          <div className="min-h-0 flex-1">
            <WaveChartRenderer
              data={chart}
              loading={chartLoading}
              showGuideLevels={beginnerGuide}
            />
          </div>
        </div>
        {beginnerGuide ? (
          <div className="min-h-0">
            <WaveBeginnerGuide guide={guideSource} price={displayPrice} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
