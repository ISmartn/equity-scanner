import { useCallback, useEffect, useState } from "react";
import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import { AppButton } from "@/components/mui/AppButton";
import {
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  PageToolbar,
  StatChip,
  ToolbarDivider,
} from "@/components/dense";
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
  const [advancedOpen, setAdvancedOpen] = useState(false);

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
    <div className="page-shell flex flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0 py-0 text-data-sm">
          {error}
        </Alert>
      ) : null}

      <PageToolbar right={<AdvancedButton onClick={() => setAdvancedOpen(true)} />}>
        <span className="shrink-0 text-data-md font-semibold text-slate-100">Elliott Wave Lab</span>
        <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1 text-[10px] font-semibold uppercase text-amber-200">
          Experimental
        </span>
        <ToolbarDivider />
        {summary ? (
          <>
            <StatChip label="W3" value={summary.wave_3_breakouts} hint="Wave 3 breakouts" valueClassName="text-sky-300" />
            <StatChip label="W4" value={summary.wave_4_dips} hint="Wave 4 dips" valueClassName="text-amber-300" />
            <StatChip label="Surety≥75" value={summary.high_surety} hint="High surety setups" valueClassName="text-emerald-300" />
          </>
        ) : null}
        {data ? (
          <StatChip label="Analyzed" value={`${data.analyzed}/${data.universe_size}`} />
        ) : null}
        {loading ? <span className="shrink-0 text-data-xs text-sky-300">Scanning…</span> : null}
      </PageToolbar>

      <div className="grid min-h-0 flex-1 gap-1 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1.1fr)]">
        <div className="min-h-0">
          <WaveScannerTable
            rows={data?.results ?? []}
            filter={filter}
            onFilterChange={setFilter}
            selectedKey={selected?.instrument_key ?? null}
            onSelect={setSelected}
          />
        </div>
        <div className="flex min-h-0 flex-col gap-1">
          {chartError ? (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-data-sm text-rose-300">
              {chartError}
            </div>
          ) : null}
          {beginnerGuide && (chart?.current_wave || selected?.current_wave) ? (
            <div className="shrink-0 rounded-lg border border-violet-500/25 bg-violet-500/10 px-2 py-1 text-data-sm text-violet-100">
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
      </div>

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Elliott Wave Lab"
        subtitle="Scan, summary & beginner guide"
      >
        <AdvancedSection title="Scan">
          <Alert severity="warning" className="py-0 text-data-xs">
            Experimental Feature: Models may repaint — Elliott / Neo-Wave counts are heuristic and can
            change as new pivots form. Local DB only; not investment advice.
          </Alert>
          <p className="text-data-xs text-slate-400">
            F&O underlyings + Nifty 50 · daily ZigZag (ATR×2.5) · impulse / zigzag rules
            {data ? ` · ${data.analyzed}/${data.universe_size} analyzed` : ""}
            {loading ? " · Scanning…" : ""}
          </p>
          <AppButton
            variant="outlined"
            size="small"
            startIcon={
              <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
            }
            onClick={() => void load(true)}
            disabled={loading}
          >
            Rescan
          </AppButton>
        </AdvancedSection>

        <AdvancedSection title="Summary">
          {summary ? (
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <StatChip label="W3 breakouts" value={summary.wave_3_breakouts} valueClassName="text-sky-300" />
              <StatChip label="W4 dips" value={summary.wave_4_dips} valueClassName="text-amber-300" />
              <StatChip label="Surety≥75" value={summary.high_surety} valueClassName="text-emerald-300" />
            </div>
          ) : (
            <p className="text-data-xs text-slate-400">{loading ? "Scanning…" : "No summary yet"}</p>
          )}
        </AdvancedSection>

        <AdvancedSection title="Beginner guide">
          <FormControlLabel
            className="mr-0"
            control={
              <Switch
                size="small"
                checked={beginnerGuide}
                onChange={(_e, checked) => setBeginnerGuide(checked)}
              />
            }
            label={
              <span className="text-data-xs text-slate-300">Show guide levels & wave chip on chart</span>
            }
          />
          <WaveBeginnerGuide guide={guideSource} price={displayPrice} />
        </AdvancedSection>
      </AdvancedDrawer>
    </div>
  );
}
