import { useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { MtfRsiChartPoint } from "@/lib/api";
import { istChartLocalization, istTimeScaleOptions } from "@/lib/chartTime";

const TF_COLORS: Record<string, string> = {
  "1": "#38bdf8",
  "3": "#a78bfa",
  "5": "#34d399",
  "10": "#fbbf24",
  "15": "#fb7185",
};

interface MtfRsiChartProps {
  series: Record<string, MtfRsiChartPoint[]>;
  visibleTfs: number[];
  height?: number;
}

export function MtfRsiChart({ series, visibleTfs, height = 320 }: MtfRsiChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<Map<string, ISeriesApi<"Line">>>(new Map());

  const dataKey = useMemo(() => {
    const parts: string[] = [];
    for (const tf of visibleTfs) {
      const pts = series[String(tf)] ?? [];
      const last = pts[pts.length - 1];
      parts.push(`${tf}:${pts.length}:${last?.v ?? ""}:${last?.t ?? ""}`);
    }
    return parts.join("|");
  }, [series, visibleTfs]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
      },
      localization: istChartLocalization(),
      grid: {
        vertLines: { color: "rgba(42, 53, 68, 0.7)" },
        horzLines: { color: "rgba(42, 53, 68, 0.7)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "#2a3544",
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#2a3544",
        ...istTimeScaleOptions(true),
      },
      width: containerRef.current.clientWidth,
      height,
    });

    chartRef.current = chart;
    const seriesMap = new Map<string, ISeriesApi<"Line">>();
    seriesRefs.current = seriesMap;

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = new Map();
    };
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const existing = seriesRefs.current;
    const wanted = new Set(visibleTfs.map(String));
    wanted.add("__guides__");

    for (const key of [...existing.keys()]) {
      if (!wanted.has(key)) {
        chart.removeSeries(existing.get(key)!);
        existing.delete(key);
      }
    }

    for (const tf of visibleTfs) {
      const key = String(tf);
      let line = existing.get(key);
      if (!line) {
        line = chart.addLineSeries({
          color: TF_COLORS[key] ?? "#94a3b8",
          lineWidth: 2,
          title: `${tf}m`,
          priceLineVisible: false,
          lastValueVisible: true,
        });
        existing.set(key, line);
      }

      const pts = series[key] ?? [];
      const data: LineData[] = pts.map((p) => ({
        time: p.t as UTCTimestamp,
        value: p.v,
      }));
      const deduped: LineData[] = [];
      let lastT: Time | null = null;
      for (const row of data) {
        if (row.time === lastT) {
          deduped[deduped.length - 1] = row;
        } else {
          deduped.push(row);
          lastT = row.time;
        }
      }
      line.setData(deduped);
    }

    const guideKey = "__guides__";
    let guides = existing.get(guideKey);
    const anyPts = visibleTfs
      .map((tf) => series[String(tf)] ?? [])
      .find((pts) => pts.length >= 2);
    if (anyPts && anyPts.length >= 2) {
      if (!guides) {
        guides = chart.addLineSeries({
          color: "transparent",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        existing.set(guideKey, guides);
        guides.createPriceLine({
          price: 70,
          color: "rgba(251, 113, 133, 0.55)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "OB",
        });
        guides.createPriceLine({
          price: 30,
          color: "rgba(52, 211, 153, 0.55)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "OS",
        });
        guides.createPriceLine({
          price: 50,
          color: "rgba(148, 163, 184, 0.35)",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: false,
          title: "",
        });
      }
      guides.setData([
        { time: anyPts[0].t as UTCTimestamp, value: 50 },
        { time: anyPts[anyPts.length - 1].t as UTCTimestamp, value: 50 },
      ]);
    }

    chart.priceScale("right").applyOptions({
      autoScale: true,
    });
    try {
      chart.timeScale().fitContent();
    } catch {
      /* ignore */
    }
  }, [dataKey, series, visibleTfs]);

  const hasData = visibleTfs.some((tf) => (series[String(tf)]?.length ?? 0) > 0);

  return (
    <div className="relative w-full">
      <div ref={containerRef} className="w-full" style={{ height }} />
      {!hasData && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-slate-500">
          No RSI series yet — load seed or start the stream.
        </div>
      )}
    </div>
  );
}
