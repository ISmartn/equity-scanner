import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { NiftyCandlePoint } from "@/lib/api";
import { bollingerBandsSeries, wildersRsiSeries } from "@/lib/indicators";

interface NiftyChartProps {
  candles: NiftyCandlePoint[];
  timeframe: string;
  height?: number;
  rsiPeriod?: number;
  showRsi?: boolean;
  showBollinger?: boolean;
  bbPeriod?: number;
  bbStdDev?: number;
}

function toChartTime(ts: string, daily: boolean): Time {
  if (daily) {
    return ts.slice(0, 10) as Time;
  }
  const ms = Date.parse(ts);
  if (Number.isNaN(ms)) {
    return ts.slice(0, 10) as Time;
  }
  return Math.floor(ms / 1000) as UTCTimestamp;
}

function formatPrice(value: number) {
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
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

function applyPaneMargins(
  chart: IChartApi,
  candleSeries: ISeriesApi<"Candlestick">,
  showRsi: boolean,
  hasRsiScale: boolean,
) {
  candleSeries.priceScale().applyOptions({
    scaleMargins: showRsi
      ? { top: 0.05, bottom: 0.38 }
      : { top: 0.06, bottom: 0.28 },
  });
  chart.priceScale("volume").applyOptions({
    scaleMargins: showRsi
      ? { top: 0.68, bottom: 0.22 }
      : { top: 0.8, bottom: 0 },
  });
  if (hasRsiScale) {
    chart.priceScale("rsi").applyOptions({
      visible: showRsi,
      scaleMargins: showRsi
        ? { top: 0.78, bottom: 0.02 }
        : { top: 1, bottom: 0 },
    });
  }
}

export function NiftyChart({
  candles,
  timeframe,
  height = 540,
  rsiPeriod = 19,
  showRsi = true,
  showBollinger = false,
  bbPeriod = 20,
  bbStdDev = 2,
}: NiftyChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const showRsiRef = useRef(showRsi);

  const daily = timeframe === "daily";

  const normalizedBars = useMemo(() => {
    const bars: {
      time: Time;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
    }[] = [];
    const seen = new Set<string>();
    for (const bar of candles) {
      const time = toChartTime(bar.ts, daily);
      const key = String(time);
      if (seen.has(key)) continue;
      seen.add(key);
      bars.push({
        time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: bar.volume ?? 0,
      });
    }
    return bars;
  }, [candles, daily]);

  const rsiPoints = useMemo(() => {
    if (!showRsi) return [] as LineData[];
    const period = Math.max(1, Math.min(200, rsiPeriod));
    const closes = normalizedBars.map((b) => b.close);
    const rsiValues = wildersRsiSeries(closes, period);
    const offset = closes.length - rsiValues.length;
    const points: LineData[] = [];
    for (let i = 0; i < rsiValues.length; i += 1) {
      points.push({ time: normalizedBars[offset + i].time, value: rsiValues[i] });
    }
    return points;
  }, [normalizedBars, rsiPeriod, showRsi]);

  const bbSeries = useMemo(() => {
    if (!showBollinger) {
      return { upper: [] as LineData[], middle: [] as LineData[], lower: [] as LineData[] };
    }
    const closes = normalizedBars.map((b) => b.close);
    const bands = bollingerBandsSeries(closes, bbPeriod, bbStdDev);
    const upper: LineData[] = [];
    const middle: LineData[] = [];
    const lower: LineData[] = [];
    for (let i = 0; i < bands.length; i += 1) {
      const pt = bands[i];
      if (!pt) continue;
      const time = normalizedBars[i].time;
      upper.push({ time, value: pt.upper });
      middle.push({ time, value: pt.middle });
      lower.push({ time, value: pt.lower });
    }
    return { upper, middle, lower };
  }, [normalizedBars, showBollinger, bbPeriod, bbStdDev]);

  const removeSeries = useCallback((chart: IChartApi, ref: { current: ISeriesApi<"Line"> | null }) => {
    if (ref.current) {
      chart.removeSeries(ref.current);
      ref.current = null;
    }
  }, []);

  // Create chart shell + OHLC/volume once per bar set / timeframe.
  useEffect(() => {
    if (!containerRef.current || !normalizedBars.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      rsiSeriesRef.current = null;
      bbUpperRef.current = null;
      bbMiddleRef.current = null;
      bbLowerRef.current = null;
    }

    const el = containerRef.current;
    const chart = createChart(el, {
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
        timeVisible: !daily,
        secondsVisible: false,
      },
      width: el.clientWidth,
      height,
    });

    const candleSeries = chart.addCandlestickSeries({
      priceScaleId: "right",
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      borderColor: "#2a3544",
    });

    const candleData: CandlestickData[] = normalizedBars.map((b) => ({
      time: b.time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    const volumeData: HistogramData[] = normalizedBars.map((b) => ({
      time: b.time,
      value: b.volume,
      color: b.close >= b.open ? "rgba(34, 197, 94, 0.45)" : "rgba(239, 68, 68, 0.45)",
    }));

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    applyPaneMargins(chart, candleSeries, showRsiRef.current, false);
    chart.timeScale().fitContent();

    const tooltip = document.createElement("div");
    tooltip.className =
      "pointer-events-none absolute z-10 hidden rounded border border-surface-border bg-surface/95 px-2 py-1 text-[11px] text-slate-200 shadow";
    el.style.position = "relative";
    el.appendChild(tooltip);
    tooltipRef.current = tooltip;

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
        tooltip.style.display = "none";
        return;
      }
      const ohlc = param.seriesData.get(candleSeries) as CandlestickData | undefined;
      if (!ohlc || ohlc.open == null) {
        tooltip.style.display = "none";
        return;
      }
      let rsiText = "";
      if (showRsiRef.current && rsiSeriesRef.current) {
        const rsi = param.seriesData.get(rsiSeriesRef.current) as LineData | undefined;
        if (rsi?.value != null) {
          rsiText = ` · RSI ${rsi.value.toFixed(1)}`;
        }
      }
      tooltip.style.display = "block";
      tooltip.style.left = `${Math.min(param.point.x + 12, el.clientWidth - 220)}px`;
      tooltip.style.top = `${Math.max(param.point.y - 56, 8)}px`;
      tooltip.innerHTML = `O ${formatPrice(ohlc.open)} · H ${formatPrice(ohlc.high)} · L ${formatPrice(ohlc.low)} · C ${formatPrice(ohlc.close)}${rsiText}`;
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      tooltip.remove();
      tooltipRef.current = null;
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      rsiSeriesRef.current = null;
      bbUpperRef.current = null;
      bbMiddleRef.current = null;
      bbLowerRef.current = null;
    };
  }, [normalizedBars, timeframe, height, daily]);

  // RSI panel — independent of Bollinger.
  useEffect(() => {
    showRsiRef.current = showRsi;
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries) return;

    applyPaneMargins(chart, candleSeries, showRsi, Boolean(rsiSeriesRef.current));

    if (showRsi) {
      if (!rsiSeriesRef.current) {
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
        rsiSeriesRef.current = rsiSeries;
        applyPaneMargins(chart, candleSeries, true, true);
      } else {
        rsiSeriesRef.current.applyOptions({
          visible: true,
          title: `RSI(${rsiPeriod})`,
        });
      }
      rsiSeriesRef.current.setData(rsiPoints);
    } else {
      if (rsiSeriesRef.current) {
        removeSeries(chart, rsiSeriesRef);
      }
      applyPaneMargins(chart, candleSeries, false, false);
    }
  }, [showRsi, rsiPoints, rsiPeriod, removeSeries, normalizedBars, height]);

  // Bollinger bands on price pane — independent of RSI.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (showBollinger) {
      if (!bbUpperRef.current) {
        bbUpperRef.current = chart.addLineSeries({
          color: "rgba(56, 189, 248, 0.75)",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          priceScaleId: "right",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "BB upper",
        });
        bbMiddleRef.current = chart.addLineSeries({
          color: "rgba(251, 191, 36, 0.85)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceScaleId: "right",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "BB mid",
        });
        bbLowerRef.current = chart.addLineSeries({
          color: "rgba(56, 189, 248, 0.75)",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          priceScaleId: "right",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "BB lower",
        });
      } else {
        bbUpperRef.current.applyOptions({ visible: true });
        bbMiddleRef.current?.applyOptions({ visible: true });
        bbLowerRef.current?.applyOptions({ visible: true });
      }
      bbUpperRef.current?.setData(bbSeries.upper);
      bbMiddleRef.current?.setData(bbSeries.middle);
      bbLowerRef.current?.setData(bbSeries.lower);
    } else {
      removeSeries(chart, bbUpperRef);
      removeSeries(chart, bbMiddleRef);
      removeSeries(chart, bbLowerRef);
    }
  }, [showBollinger, bbSeries, removeSeries, normalizedBars, height]);

  if (!candles.length) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-surface-border bg-surface text-sm text-slate-500"
        style={{ height }}
      >
        No candles loaded for this timeframe.
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full overflow-hidden rounded-lg border border-surface-border" />
  );
}
