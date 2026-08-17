import { useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type CandlestickData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { DarvasBoxPrimitive } from "@/components/DarvasBoxPrimitive";
import type { CandlePoint } from "@/lib/api";
import { setDefaultChartVisibleRange } from "@/lib/chartTimeScale";
import { computeDarvasBoxesForFilterMatches } from "@/lib/darvasBox";
import { computeThreeGreenStreakBoxes } from "@/lib/candlePatterns";
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

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
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
  }, [history, options, filteredDarvasBoxes, darvasEnabled, threeGreenEnabled, threeGreenBoxes, fillHeight]);

  if (loading) {
    return (
      <div
        className={`flex items-center justify-center rounded-2xl border border-surface-border bg-surface-raised ${
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
        className={`flex items-center justify-center rounded-2xl border border-dashed border-surface-border bg-surface-raised/50 ${
          fillHeight ? "h-full min-h-[16rem]" : "h-[480px]"
        }`}
      >
        <p className="text-sm text-slate-500">Select a stock to view daily moves</p>
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col rounded-2xl border border-surface-border bg-surface-raised ${
        fillHeight ? "h-full min-h-0 p-3" : "p-4 sm:p-6"
      }`}
    >
      <div className="mb-2 flex shrink-0 flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold sm:text-xl">{symbol}</h2>
          <p className="text-xs text-slate-400 sm:text-sm">
            Daily · {historyBars} bars · {lookbackYears}Y · {source.toUpperCase()}
          </p>
        </div>
        <div className="flex flex-wrap gap-4 text-right sm:gap-6">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Latest close</div>
            <div className="font-mono text-base text-white sm:text-lg">{formatPrice(latestClose)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Marked days</div>
            <div className="font-mono text-base text-yellow-400 sm:text-lg">{highlightCount}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Darvas</div>
            <div className="font-mono text-base text-sky-400 sm:text-lg">
              {darvasEnabled ? filteredDarvasBoxes.length : "—"}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Green streaks</div>
            <div className="font-mono text-base text-lime-400 sm:text-lg">
              {threeGreenEnabled ? threeGreenBoxes.length : "—"}
            </div>
          </div>
        </div>
      </div>

      <div
        ref={containerRef}
        className={`w-full overflow-hidden rounded-lg ${fillHeight ? "min-h-0 flex-1" : ""}`}
      />

      <div className="mt-2 flex shrink-0 flex-wrap gap-3 text-[10px] text-slate-500 sm:gap-4 sm:text-xs">
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
    </div>
  );
}
