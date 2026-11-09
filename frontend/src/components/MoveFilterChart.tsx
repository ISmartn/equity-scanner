import { useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
  type LineWidth,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { DarvasBoxPrimitive } from "@/components/DarvasBoxPrimitive";
import type { CandlePoint } from "@/lib/api";
import { setDefaultChartVisibleRange } from "@/lib/chartTimeScale";
import { computeDarvasBoxesForFilterMatches } from "@/lib/darvasBox";
import { computeThreeGreenStreakBoxes } from "@/lib/candlePatterns";
import { emaSeries, rsiStatus, wildersRsiSeries } from "@/lib/indicators";
import {
  isHighlighted,
  isNegativeMove,
  isPositiveMove,
  pctFromPrevClose,
  type MoveFilterOptions,
} from "@/lib/moveFilter";

interface MoveFilterChartProps {
  symbol: string;
  source: string;
  history: CandlePoint[];
  historyBars: number;
  lookbackYears: number;
  latestClose: number;
  positiveThreshold: number | null;
  negativeThreshold: number | null;
  positiveEnabled: boolean;
  negativeEnabled: boolean;
  threeGreenEnabled: boolean;
  darvasEnabled: boolean;
  darvasLookbackDays: number;
  loading?: boolean;
  /** Fill parent height instead of fixed 480px chart. */
  fillHeight?: boolean;
  emaInputs: string[];
  emaEnabled: boolean[];
  onEmaInput: (index: number, value: string) => void;
  onEmaEnabled: (index: number, enabled: boolean) => void;
  showRsi: boolean;
  rsiInput: string;
  onShowRsi: (enabled: boolean) => void;
  onRsiInput: (value: string) => void;
}

const EMA_COLORS = ["#fbbf24", "#38bdf8", "#c084fc", "#fb923c", "#f8fafc"];
const EMA_WIDTHS: LineWidth[] = [1, 1, 2, 2, 2];

function parsePeriod(raw: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const period = Number(raw);
  if (!Number.isInteger(period) || period < min || period > max) return null;
  return period;
}

function addRsiGuides(series: ISeriesApi<"Line">) {
  series.createPriceLine({
    price: 70,
    color: "rgba(251, 113, 133, 0.55)",
    lineWidth: 1,
    lineStyle: LineStyle.Dashed,
    axisLabelVisible: true,
    title: "70",
  });
  series.createPriceLine({
    price: 30,
    color: "rgba(52, 211, 153, 0.55)",
    lineWidth: 1,
    lineStyle: LineStyle.Dashed,
    axisLabelVisible: true,
    title: "30",
  });
  series.createPriceLine({
    price: 50,
    color: "rgba(148, 163, 184, 0.3)",
    lineWidth: 1,
    lineStyle: LineStyle.Dotted,
    axisLabelVisible: false,
    title: "",
  });
}

function buildEmaLine(history: CandlePoint[], period: number): LineData[] {
  const values = emaSeries(
    history.map((candle) => candle.close),
    period,
  );
  const points: LineData[] = [];
  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (value == null) continue;
    points.push({ time: toChartTime(history[i].date), value });
  }
  return points;
}

function buildRsiLine(history: CandlePoint[], period: number): LineData[] {
  const closes = history.map((candle) => candle.close);
  const values = wildersRsiSeries(closes, period);
  const offset = closes.length - values.length;
  const points: LineData[] = [];
  for (let i = 0; i < values.length; i += 1) {
    points.push({ time: toChartTime(history[offset + i].date), value: values[i] });
  }
  return points;
}

function formatPrice(value: number) {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function toChartTime(dateStr: string): Time {
  return dateStr as Time;
}

function filterOptions(
  positiveThreshold: number | null,
  negativeThreshold: number | null,
  positiveEnabled: boolean,
  negativeEnabled: boolean,
): MoveFilterOptions {
  return {
    positiveThreshold,
    negativeThreshold,
    positiveEnabled,
    negativeEnabled,
  };
}

function buildMarkers(history: CandlePoint[], options: MoveFilterOptions): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];

  for (let i = 1; i < history.length; i++) {
    const candle = history[i];
    const pct = pctFromPrevClose(candle, i, history);
    if (pct === null) continue;

    const positive = isPositiveMove(pct, options);
    const negative = isNegativeMove(pct, options);

    if (!positive && !negative) continue;

    markers.push({
      time: toChartTime(candle.date),
      position: "aboveBar",
      shape: positive ? "arrowUp" : "arrowDown",
      color: positive ? "#22c55e" : "#ef4444",
      size: 1.5,
      text: `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`,
    });
  }

  return markers;
}

export function MoveFilterChart({
  symbol,
  source,
  history,
  historyBars,
  lookbackYears,
  latestClose,
  positiveThreshold,
  negativeThreshold,
  positiveEnabled,
  negativeEnabled,
  threeGreenEnabled,
  darvasEnabled,
  darvasLookbackDays,
  loading,
  fillHeight = false,
  emaInputs,
  emaEnabled,
  onEmaInput,
  onEmaEnabled,
  showRsi,
  rsiInput,
  onShowRsi,
  onRsiInput,
}: MoveFilterChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const options = useMemo(
    () =>
      filterOptions(
        positiveThreshold,
        negativeThreshold,
        positiveEnabled,
        negativeEnabled,
      ),
    [positiveThreshold, negativeThreshold, positiveEnabled, negativeEnabled],
  );

  const highlightCount = useMemo(() => {
    if (!history.length) return 0;
    return history.filter((c, i) => isHighlighted(c, i, history, options)).length;
  }, [history, options]);

  const threeGreenBoxes = useMemo(() => {
    if (!threeGreenEnabled || !history.length) return [];
    return computeThreeGreenStreakBoxes(history);
  }, [history, threeGreenEnabled]);

  const filteredDarvasBoxes = useMemo(() => {
    if (!darvasEnabled) return [];
    return computeDarvasBoxesForFilterMatches(history, options, darvasLookbackDays);
  }, [history, options, darvasEnabled, darvasLookbackDays]);

  const emaOverlays = useMemo(
    () =>
      emaInputs.map((raw, index) => {
        const period = parsePeriod(raw, 1, 500);
        const enabled = emaEnabled[index] !== false;
        const points = enabled && period != null && history.length ? buildEmaLine(history, period) : [];
        return {
          period,
          enabled,
          color: EMA_COLORS[index] ?? "#94a3b8",
          width: EMA_WIDTHS[index] ?? 1,
          points,
          invalid: enabled && period == null,
        };
      }),
    [emaInputs, emaEnabled, history],
  );

  const rsiPeriod = showRsi ? parsePeriod(rsiInput, 1, 200) : null;
  const rsiPoints = useMemo(
    () => (rsiPeriod != null && history.length ? buildRsiLine(history, rsiPeriod) : []),
    [history, rsiPeriod],
  );
  const latestRsi = rsiPoints.length ? rsiPoints[rsiPoints.length - 1].value : null;
  const latestRsiStatus = showRsi ? rsiStatus(latestRsi) : null;

  useEffect(() => {
    if (!containerRef.current || !history.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#1a2332" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#2a3544" },
        horzLines: { color: "#2a3544" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2a3544" },
      timeScale: {
        borderColor: "#2a3544",
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: fillHeight
        ? Math.max(240, containerRef.current.clientHeight || 420)
        : 420,
    });

    const showRsiPane = showRsi && rsiPoints.length > 0;

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    candleSeries.priceScale().applyOptions({
      scaleMargins: showRsiPane
        ? { top: 0.04, bottom: 0.28 }
        : { top: 0.06, bottom: 0.06 },
    });

    const darvasPrimitive = new DarvasBoxPrimitive();
    candleSeries.attachPrimitive(darvasPrimitive);

    const candleData: CandlestickData[] = history.map((c) => ({
      time: toChartTime(c.date),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    candleSeries.setData(candleData);
    candleSeries.setMarkers(buildMarkers(history, options));

    for (const overlay of emaOverlays) {
      if (!overlay.enabled || overlay.period == null || !overlay.points.length) continue;
      const series = chart.addLineSeries({
        color: overlay.color,
        lineWidth: overlay.width,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
        title: `EMA ${overlay.period}`,
      });
      series.setData(overlay.points);
    }

    if (showRsiPane && rsiPeriod != null) {
      const rsiSeries = chart.addLineSeries({
        color: "#a78bfa",
        lineWidth: 2,
        priceScaleId: "rsi",
        title: `RSI(${rsiPeriod})`,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      chart.priceScale("rsi").applyOptions({
        borderColor: "#2a3544",
        autoScale: false,
        visible: true,
        scaleMargins: { top: 0.78, bottom: 0.02 },
      });
      rsiSeries.applyOptions({
        autoscaleInfoProvider: () => ({
          priceRange: { minValue: 0, maxValue: 100 },
        }),
      });
      addRsiGuides(rsiSeries);
      rsiSeries.setData(rsiPoints);
    }

    setDefaultChartVisibleRange(chart, history.length);

    const chartBoxes = [
      ...filteredDarvasBoxes.map((box) => ({
        startTime: toChartTime(box.startDate),
        endTime: toChartTime(box.endDate),
        top: box.top,
        bottom: box.bottom,
        direction: box.direction,
        variant: "darvas" as const,
      })),
      ...threeGreenBoxes.map((box) => ({
        startTime: toChartTime(box.startDate),
        endTime: toChartTime(box.endDate),
        top: box.top,
        bottom: box.bottom,
        direction: "up" as const,
        variant: "greenStreak" as const,
      })),
    ];
    darvasPrimitive.setBoxes(chartBoxes);

    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          ...(fillHeight
            ? { height: Math.max(240, containerRef.current.clientHeight || 240) }
            : {}),
        });
      }
    };

    window.addEventListener("resize", handleResize);
    let resizeObserver: ResizeObserver | null = null;
    if (fillHeight && typeof ResizeObserver !== "undefined" && containerRef.current) {
      resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      window.removeEventListener("resize", handleResize);
      resizeObserver?.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [
    history,
    options,
    filteredDarvasBoxes,
    darvasEnabled,
    threeGreenEnabled,
    threeGreenBoxes,
    fillHeight,
    emaOverlays,
    showRsi,
    rsiPeriod,
    rsiPoints,
  ]);

  if (loading) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg border border-surface-border bg-surface-raised ${
          fillHeight ? "h-full min-h-[16rem]" : "h-[480px]"
        }`}
      >
        <div className="text-center">
          <div className="mx-auto mb-3 h-10 w-10 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm text-slate-400">Loading 5Y history from Upstox...</p>
        </div>
      </div>
    );
  }

  if (!history.length) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg border border-dashed border-surface-border bg-surface-raised/50 ${
          fillHeight ? "h-full min-h-[16rem]" : "h-[480px]"
        }`}
      >
        <p className="text-data-md text-slate-400">Select a stock to view daily moves</p>
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col rounded-lg border border-surface-border bg-surface-raised ${
        fillHeight ? "h-full min-h-0 p-1.5" : "p-2"
      }`}
    >
      <div className="mb-1 flex shrink-0 flex-wrap items-end justify-between gap-2 px-0.5">
        <div>
          <h2 className="text-base font-semibold leading-tight text-slate-100">{symbol}</h2>
          <p className="text-data-xs text-slate-300">
            Daily · {historyBars} bars · {lookbackYears}Y · {source.toUpperCase()}
          </p>
        </div>
        <div className="flex flex-wrap gap-3 text-right">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Latest close</div>
            <div className="num font-mono text-data-md text-white">{formatPrice(latestClose)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Marked days</div>
            <div className="num font-mono text-data-md text-yellow-400">{highlightCount}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Darvas</div>
            <div className="num font-mono text-data-md text-sky-400">
              {darvasEnabled ? filteredDarvasBoxes.length : "—"}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Green streaks</div>
            <div className="num font-mono text-data-md text-lime-400">
              {threeGreenEnabled ? threeGreenBoxes.length : "—"}
            </div>
          </div>
          {showRsi && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                RSI({rsiPeriod ?? (rsiInput || "?")})
              </div>
              <div
                className={`num font-mono text-data-md ${
                  latestRsiStatus === "Overbought"
                    ? "text-rose-300"
                    : latestRsiStatus === "Oversold"
                      ? "text-emerald-300"
                      : "text-violet-300"
                }`}
              >
                {latestRsi != null ? latestRsi.toFixed(1) : "—"}
                {latestRsiStatus && latestRsiStatus !== "Warming" ? (
                  <span className="ml-1 text-[10px] font-normal text-slate-400">{latestRsiStatus}</span>
                ) : null}
              </div>
            </div>
          )}
        </div>
      </div>

      <div
        ref={containerRef}
        className={`w-full overflow-hidden rounded-lg ${fillHeight ? "min-h-0 flex-1" : ""}`}
      />

      <div className="mt-1 flex shrink-0 flex-wrap gap-3 px-0.5 text-data-xs text-slate-300">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" />
          Bullish
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-red-500" />
          Bearish
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-emerald-400">▲</span>
          Up move
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-red-400">▼</span>
          Down move
        </span>
        {threeGreenEnabled && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-6 rounded-sm border border-lime-400/70 bg-lime-400/15" />
            3+ green streak
          </span>
        )}
        {darvasEnabled && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-6 rounded-sm border border-sky-500/60 bg-sky-500/15" />
            Darvas box
          </span>
        )}
      </div>

      <div className="mt-1 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 px-0.5 text-data-xs text-slate-300">
        <span className="text-[10px] uppercase tracking-wide text-slate-400">EMA</span>
        {emaInputs.map((raw, index) => {
          const overlay = emaOverlays[index];
          const enabled = emaEnabled[index] !== false;
          return (
            <label key={index} className="inline-flex items-center gap-1" title={`EMA ${raw || "?"}`}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => onEmaEnabled(index, event.target.checked)}
                className="h-3 w-3 rounded border-surface-border"
                aria-label={`Show EMA ${index + 1}`}
              />
              <span
                className="inline-block h-0.5 w-3.5 rounded-full"
                style={{ backgroundColor: overlay?.color ?? "#94a3b8" }}
              />
              <input
                type="number"
                min={1}
                max={500}
                value={raw}
                disabled={!enabled}
                onChange={(event) => onEmaInput(index, event.target.value)}
                className={`w-14 rounded border bg-surface px-1 py-0.5 text-data-xs tabular-nums text-slate-200 outline-none disabled:opacity-40 ${
                  overlay?.invalid ? "border-amber-500/70" : "border-surface-border"
                }`}
                aria-label={`EMA ${index + 1} period`}
              />
            </label>
          );
        })}

        <span className="h-3 w-px bg-surface-border" aria-hidden />

        <label className="inline-flex items-center gap-1">
          <input
            type="checkbox"
            checked={showRsi}
            onChange={(event) => onShowRsi(event.target.checked)}
            className="h-3 w-3 rounded border-surface-border"
            aria-label="Show RSI"
          />
          <span className="inline-block h-0.5 w-3.5 rounded-full bg-violet-400" />
          RSI
          <input
            type="number"
            min={1}
            max={200}
            value={rsiInput}
            disabled={!showRsi}
            onChange={(event) => onRsiInput(event.target.value)}
            className={`w-12 rounded border bg-surface px-1 py-0.5 text-data-xs tabular-nums text-slate-200 outline-none disabled:opacity-40 ${
              showRsi && rsiPeriod == null ? "border-amber-500/70" : "border-surface-border"
            }`}
            aria-label="RSI period"
          />
        </label>
        {emaOverlays.some((overlay) => overlay.invalid) && (
          <span className="text-amber-400">EMA period must be 1–500</span>
        )}
        {showRsi && rsiPeriod == null && (
          <span className="text-amber-400">RSI period must be 1–200</span>
        )}
      </div>
    </div>
  );
}
