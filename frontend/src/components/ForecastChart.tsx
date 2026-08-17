import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type CandlestickData,
  type LineData,
  type Time,
} from "lightweight-charts";
import type { ForecastPayload } from "@/lib/api";
import { DEFAULT_VISIBLE_TRADING_DAYS } from "@/lib/chartTimeScale";

interface ForecastChartProps {
  data: ForecastPayload | null;
  loading?: boolean;
}

function formatPrice(value: number) {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function toChartTime(dateStr: string): Time {
  return dateStr as Time;
}

export function ForecastChart({ data, loading }: ForecastChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || !data) return;

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
      height: 420,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const upperSeries = chart.addLineSeries({
      color: "rgba(239, 68, 68, 0.35)",
      lineWidth: 1,
      lineStyle: 2,
      title: "80% upper",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const lowerSeries = chart.addLineSeries({
      color: "rgba(239, 68, 68, 0.35)",
      lineWidth: 1,
      lineStyle: 2,
      title: "80% lower",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const medianSeries = chart.addLineSeries({
      color: "#f87171",
      lineWidth: 2,
      lineStyle: 2,
      title: "Median forecast",
      priceLineVisible: false,
    });

    const candleData: CandlestickData[] = data.history.map((c) => ({
      time: toChartTime(c.date),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const lastCandle = data.history.length > 0 ? data.history[data.history.length - 1] : undefined;
    const medianData: LineData[] = [];
    const upperData: LineData[] = [];
    const lowerData: LineData[] = [];

    if (lastCandle) {
      const bridgeTime = toChartTime(lastCandle.date);
      medianData.push({ time: bridgeTime, value: lastCandle.close });
      upperData.push({ time: bridgeTime, value: lastCandle.close });
      lowerData.push({ time: bridgeTime, value: lastCandle.close });
    }

    data.forecast_dates.forEach((date, idx) => {
      const time = toChartTime(date);
      medianData.push({ time, value: data.median[idx] });
      upperData.push({ time, value: data.upper[idx] });
      lowerData.push({ time, value: data.lower[idx] });
    });

    candleSeries.setData(candleData);
    medianSeries.setData(medianData);
    upperSeries.setData(upperData);
    lowerSeries.setData(lowerData);

    const historyBars = data.history.length;
    const forecastBars = data.forecast_dates.length;
    const visibleBars = DEFAULT_VISIBLE_TRADING_DAYS;
    if (historyBars <= visibleBars) {
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().setVisibleLogicalRange({
        from: historyBars - visibleBars,
        to: historyBars - 1 + forecastBars,
      });
    }

    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  if (loading) {
    return (
      <div className="flex h-[480px] items-center justify-center rounded-2xl border border-surface-border bg-surface-raised">
        <div className="text-center">
          <div className="mx-auto mb-3 h-10 w-10 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm text-slate-400">Loading 5Y history & running TimesFM...</p>
          <p className="mt-1 text-xs text-slate-500">First run downloads model weights</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-[480px] items-center justify-center rounded-2xl border border-dashed border-surface-border bg-surface-raised/50">
        <p className="text-sm text-slate-500">Select a stock and click Run Forecast to load TimesFM</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-surface-border bg-surface-raised p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{data.symbol}</h2>
          <p className="text-sm capitalize text-slate-400">
            {data.interval} · {data.history_bars} bars · {data.lookback_years}Y ·{" "}
            {data.model_label}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase tracking-wide text-slate-500">Latest close</div>
          <div className="font-mono text-lg text-white">{formatPrice(data.latest_close)}</div>
        </div>
      </div>

      <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />

      <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" />
          Bullish candle
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-red-500" />
          Bearish candle
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-red-400" />
          TimesFM median + 80% band
        </span>
        <span>Scroll/zoom on chart · Device: {data.device}</span>
      </div>
    </div>
  );
}
