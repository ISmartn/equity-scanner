import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { ElliottWaveChartPayload } from "@/lib/api";

type Props = {
  data: ElliottWaveChartPayload | null;
  loading: boolean;
  showGuideLevels?: boolean;
};

/** Distinct colors per wave number / letter */
const WAVE_COLORS: Record<string, string> = {
  "0": "#94a3b8",
  "1": "#38bdf8", // sky — Wave 1
  "2": "#fbbf24", // amber — Wave 2
  "3": "#c084fc", // purple — Wave 3 (often strongest)
  "4": "#34d399", // emerald — Wave 4
  "5": "#fb7185", // rose — Wave 5
  A: "#38bdf8",
  B: "#fbbf24",
  C: "#c084fc",
  "C-end": "#fb7185",
};

const WAVE_LEGEND_IMPULSE = [
  { id: "1", color: WAVE_COLORS["1"] },
  { id: "2", color: WAVE_COLORS["2"] },
  { id: "3", color: WAVE_COLORS["3"] },
  { id: "4", color: WAVE_COLORS["4"] },
  { id: "5", color: WAVE_COLORS["5"] },
] as const;

const WAVE_LEGEND_ZIGZAG = [
  { id: "A", color: WAVE_COLORS.A },
  { id: "B", color: WAVE_COLORS.B },
  { id: "C", color: WAVE_COLORS.C },
] as const;

function segmentWaveId(endLabel: string): string {
  if (endLabel === "C-end") return "C";
  return endLabel;
}

function displayLabel(label: string): string {
  if (label === "0") return "0";
  if (label === "C-end") return "C";
  return label;
}

export function WaveChartRenderer({ data, loading, showGuideLevels = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || !data?.candles.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
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
      timeScale: { borderColor: "#2a3544", timeVisible: false },
      width: el.clientWidth,
      height: Math.max(el.clientHeight, 280),
    });

    const candles = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candles.setData(
      data.candles.map((c) => ({
        time: c.date as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    // Dim full ZigZag so labeled waves stay readable
    if (data.zigzag_path.length >= 2) {
      const zigzag = chart.addLineSeries({
        color: "rgba(148, 163, 184, 0.35)",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
        title: "ZigZag",
      });
      zigzag.setData(
        data.zigzag_path.map((p) => ({
          time: p.time as Time,
          value: p.price,
        })),
      );
    }

    const path = data.wave_path;
    if (path.length >= 2) {
      // One colored segment per wave (pivot i-1 → pivot i)
      for (let i = 1; i < path.length; i += 1) {
        const from = path[i - 1];
        const to = path[i];
        const waveId = segmentWaveId(to.label);
        const color = WAVE_COLORS[waveId] ?? WAVE_COLORS[to.label] ?? "#a78bfa";
        const seg = chart.addLineSeries({
          color,
          lineWidth: 3,
          priceLineVisible: false,
          lastValueVisible: false,
          title: `W${displayLabel(to.label)}`,
        });
        seg.setData([
          { time: from.time as Time, value: from.price },
          { time: to.time as Time, value: to.price },
        ]);
      }

      // Labeled markers at each wave pivot
      const markers: SeriesMarker<Time>[] = path.map((p) => {
        const waveId = segmentWaveId(p.label);
        const color = WAVE_COLORS[waveId] ?? WAVE_COLORS[p.label] ?? "#e2e8f0";
        const isPeak = p.type === "PEAK";
        const text = displayLabel(p.label);
        return {
          time: p.time as Time,
          position: isPeak ? "aboveBar" : "belowBar",
          shape: isPeak ? "arrowDown" : "arrowUp",
          color,
          text: text === "0" ? "Start" : text,
          size: 2,
        };
      });
      // lightweight-charts requires markers sorted by time
      markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
      candles.setMarkers(markers);
    }

    if (data.invalidation_price != null) {
      candles.createPriceLine({
        price: data.invalidation_price,
        color: "rgba(251, 113, 133, 0.9)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Invalidation",
      });
    }

    if (showGuideLevels && data.guide?.levels?.length) {
      for (const lv of data.guide.levels.slice(0, 6)) {
        if (data.invalidation_price != null && Math.abs(lv.price - data.invalidation_price) < 1e-6) {
          continue;
        }
        const color =
          lv.role === "target"
            ? "rgba(56, 189, 248, 0.55)"
            : lv.role === "support"
              ? "rgba(52, 211, 153, 0.5)"
              : lv.role === "resistance"
                ? "rgba(251, 191, 36, 0.5)"
                : "rgba(251, 113, 133, 0.55)";
        candles.createPriceLine({
          price: lv.price,
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: lv.label.length > 18 ? `${lv.label.slice(0, 16)}…` : lv.label,
        });
      }
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const onResize = () => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: Math.max(containerRef.current.clientHeight, 280),
      });
    };
    const observer = new ResizeObserver(onResize);
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, showGuideLevels]);

  if (loading) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-xl border border-surface-border bg-surface-raised text-[12px] text-slate-500">
        Loading chart…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-xl border border-dashed border-surface-border bg-surface-raised text-[12px] text-slate-500">
        Select a symbol to view wave overlays
      </div>
    );
  }

  const isZigzag = data.pattern === "zigzag";
  const legend = isZigzag ? WAVE_LEGEND_ZIGZAG : WAVE_LEGEND_IMPULSE;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-surface-border px-3 py-2">
        <h3 className="text-[13px] font-semibold text-slate-100">{data.ticker}</h3>
        <span className="text-[10px] text-slate-500">
          {data.phase} · surety {data.surety_score.toFixed(0)}
          {data.invalidation_price != null
            ? ` · inv ₹${data.invalidation_price.toLocaleString("en-IN")}`
            : ""}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-[9px] text-slate-400">
          {legend.map((w) => (
            <span key={w.id} className="inline-flex items-center gap-1">
              <span
                className="inline-block h-2 w-3 rounded-sm"
                style={{ backgroundColor: w.color }}
              />
              <span className="font-semibold" style={{ color: w.color }}>
                {isZigzag ? w.id : `W${w.id}`}
              </span>
            </span>
          ))}
        </div>
      </div>
      <div ref={containerRef} className="min-h-[280px] flex-1" />
    </div>
  );
}
