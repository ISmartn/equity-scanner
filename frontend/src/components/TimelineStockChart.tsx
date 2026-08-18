import { useEffect, useMemo, useRef } from "react";
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
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { VcpOverlayPrimitive } from "@/components/VcpOverlayPrimitive";
import type { TimelineCandlePoint } from "@/lib/api";
import { applyChartVisibleRange, setChartVisibleRangeCentered, setDefaultChartVisibleRange } from "@/lib/chartTimeScale";
import { wildersRsiSeries } from "@/lib/indicators";
import type { VcpOverlayData } from "@/lib/vcpOverlay";

export interface ChartNewsMarker {
  date: string;
  sentiment?: string | null;
  label?: string | null;
}

interface TimelineStockChartProps {
  symbol: string;
  companyName?: string | null;
  sector?: string | null;
  marketCap?: string | null;
  source: string;
  history: TimelineCandlePoint[];
  highlightDate: string;
  highlightMovePct: number | null;
  loading?: boolean;
  fillHeight?: boolean;
  /** Show the last N bars instead of centering on the highlight (better for scanner). */
  tailVisibleRange?: boolean;
  /** VCP contraction bands + pivot line (null hides overlay). */
  vcpOverlay?: VcpOverlayData | null;
  /** Extra news/event markers (in addition to highlight). */
  extraMarkers?: ChartNewsMarker[];
  /** Wilder RSI pane under price/volume (default on). */
  showRsi?: boolean;
  rsiPeriod?: number;
}

function formatPrice(value: number) {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function formatVolume(value: number) {
  if (value >= 1e7) return `${(value / 1e7).toFixed(2)} Cr`;
  if (value >= 1e5) return `${(value / 1e5).toFixed(2)} L`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)} K`;
  return value.toLocaleString("en-IN");
}

function movePctForBar(bar: TimelineCandlePoint): number | null {
  if (bar.daily_return_pct != null) return bar.daily_return_pct;
  if (!bar.open) return null;
  return ((bar.close - bar.open) / bar.open) * 100;
}

function formatMovePct(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function timeToDateString(time: Time): string | null {
  if (typeof time === "string") return time;
  if (typeof time === "number") {
    return new Date(time * 1000).toISOString().slice(0, 10);
  }
  if (time && typeof time === "object" && "year" in time) {
    const { year, month, day } = time;
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }
  return null;
}

function sentimentMarkerColor(sentiment?: string | null): string {
  if (sentiment === "bullish") return "#22c55e";
  if (sentiment === "bearish") return "#ef4444";
  return "#38bdf8";
}

function buildHighlightMarker(
  highlightDate: string,
  bar: TimelineCandlePoint | undefined,
  movePct: number | null,
  extraMarkers: ChartNewsMarker[] = [],
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  const seen = new Set<string>();

  if (highlightDate && bar) {
    const isUp = (movePct ?? movePctForBar(bar) ?? 0) >= 0;
    markers.push({
      time: toChartTime(highlightDate),
      position: "aboveBar",
      shape: isUp ? "arrowUp" : "arrowDown",
      color: isUp ? "#22c55e" : "#ef4444",
      size: 0.85,
    });
    seen.add(highlightDate);
  }

  for (const m of extraMarkers) {
    if (!m.date || seen.has(m.date)) continue;
    seen.add(m.date);
    markers.push({
      time: toChartTime(m.date),
      position: "belowBar",
      shape: "circle",
      color: sentimentMarkerColor(m.sentiment),
      size: 0.6,
      text: m.label || undefined,
    });
  }

  return markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function volumeBarColor(bar: TimelineCandlePoint, isHighlight: boolean): string {
  if (isHighlight) return bar.close >= bar.open ? "#4ade80" : "#f87171";
  return bar.close >= bar.open ? "rgba(34, 197, 94, 0.45)" : "rgba(239, 68, 68, 0.45)";
}

function toChartTime(dateStr: string): Time {
  return dateStr as Time;
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

function buildRsiLineData(history: TimelineCandlePoint[], period: number): LineData[] {
  const closes = history.map((c) => c.close);
  const values = wildersRsiSeries(closes, period);
  const offset = closes.length - values.length;
  const points: LineData[] = [];
  for (let i = 0; i < values.length; i += 1) {
    points.push({ time: toChartTime(history[offset + i].date), value: values[i] });
  }
  return points;
}

export function TimelineStockChart({
  symbol,
  companyName,
  sector,
  marketCap,
  source,
  history,
  highlightDate,
  highlightMovePct,
  loading,
  fillHeight = false,
  tailVisibleRange = false,
  vcpOverlay = null,
  extraMarkers = [],
  showRsi = true,
  rsiPeriod = 14,
}: TimelineStockChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const vcpPrimitiveRef = useRef<VcpOverlayPrimitive | null>(null);

  const highlightBar = history.find((c) => c.date === highlightDate);
  const period = Math.max(1, Math.min(200, rsiPeriod));
  const rsiPoints = useMemo(
    () => (showRsi ? buildRsiLineData(history, period) : []),
    [history, period, showRsi],
  );
  const latestRsi = rsiPoints.length ? rsiPoints[rsiPoints.length - 1].value : null;
  const highlightRsi =
    showRsi && highlightDate
      ? (rsiPoints.find((p) => String(p.time) === highlightDate)?.value ?? null)
      : null;

  useEffect(() => {
    if (!containerRef.current || !history.length) return;

    const selectedBar = history.find((c) => c.date === highlightDate);
    const barByDate = new Map(history.map((c) => [c.date, c]));
    const rsiLine = showRsi ? buildRsiLineData(history, period) : [];
    const rsiByDate = new Map(rsiLine.map((p) => [String(p.time), p.value]));

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const el = containerRef.current;
    const chartHeight = Math.max(el.clientHeight, 200);

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
        timeVisible: true,
        secondsVisible: false,
      },
      width: el.clientWidth,
      height: chartHeight,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    candleSeries.priceScale().applyOptions({
      scaleMargins: showRsi ? { top: 0.05, bottom: 0.38 } : { top: 0.06, bottom: 0.28 },
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: showRsi ? { top: 0.68, bottom: 0.22 } : { top: 0.78, bottom: 0 },
    });

    const candleData: CandlestickData[] = history.map((c) => ({
      time: toChartTime(c.date),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const volumeData: HistogramData[] = history.map((c) => ({
      time: toChartTime(c.date),
      value: c.volume,
      color: volumeBarColor(c, c.date === highlightDate),
    }));

    const vcpPrimitive = new VcpOverlayPrimitive();
    candleSeries.attachPrimitive(vcpPrimitive);
    vcpPrimitiveRef.current = vcpPrimitive;

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    candleSeries.setMarkers(
      buildHighlightMarker(highlightDate, selectedBar, highlightMovePct, extraMarkers),
    );
    vcpPrimitive.setOverlay(vcpOverlay);

    if (showRsi && rsiLine.length) {
      const rsiSeries = chart.addLineSeries({
        color: "#a78bfa",
        lineWidth: 2,
        priceScaleId: "rsi",
        title: `RSI(${period})`,
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
      rsiSeries.setData(rsiLine);
    }

    const highlightIndex = history.findIndex((c) => c.date === highlightDate);

    const applyVisibleRange = () => {
      if (tailVisibleRange || highlightIndex < 0) {
        setDefaultChartVisibleRange(chart, history.length);
      } else {
        setChartVisibleRangeCentered(chart, history.length, highlightIndex);
      }
    };

    applyChartVisibleRange(applyVisibleRange);

    chartRef.current = chart;

    const hideTooltip = () => {
      const tip = tooltipRef.current;
      if (tip) tip.style.display = "none";
    };

    const showTooltip = (html: string, x: number, y: number) => {
      const tip = tooltipRef.current;
      const wrap = wrapperRef.current;
      if (!tip || !wrap) return;

      const maxX = wrap.clientWidth - tip.offsetWidth - 8;
      const maxY = wrap.clientHeight - tip.offsetHeight - 8;
      const left = Math.max(8, Math.min(x + 12, maxX));
      const top = Math.max(8, Math.min(y - 10, maxY));

      tip.innerHTML = html;
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
      tip.style.display = "block";
    };

    chart.subscribeCrosshairMove((param) => {
      if (
        !param.time ||
        !param.point ||
        param.point.x < 0 ||
        param.point.y < 0 ||
        param.point.x > el.clientWidth ||
        param.point.y > el.clientHeight
      ) {
        hideTooltip();
        return;
      }

      const dateStr = timeToDateString(param.time);
      if (!dateStr) {
        hideTooltip();
        return;
      }

      const bar = barByDate.get(dateStr);
      if (!bar) {
        hideTooltip();
        return;
      }

      const move = movePctForBar(bar);
      const moveColor = (move ?? 0) >= 0 ? "#4ade80" : "#f87171";
      const rsiVal = rsiByDate.get(dateStr);
      const rsiHtml =
        rsiVal != null
          ? `<div><span style="color:#64748b">RSI(${period}) </span><span style="font-family:monospace;color:#c4b5fd">${rsiVal.toFixed(1)}</span></div>`
          : "";

      showTooltip(
        `<div style="font-size:10px;color:#94a3b8;margin-bottom:4px">${dateStr}</div>` +
          `<div style="font-size:12px;line-height:1.5">` +
          `<div><span style="color:#64748b">Close </span><span style="font-family:monospace;color:#f1f5f9">${formatPrice(bar.close)}</span></div>` +
          `<div><span style="color:#64748b">Move </span><span style="font-family:monospace;color:${moveColor}">${formatMovePct(move)}</span></div>` +
          `<div><span style="color:#64748b">Volume </span><span style="font-family:monospace;color:#38bdf8">${formatVolume(bar.volume)}</span></div>` +
          rsiHtml +
          `</div>`,
        param.point.x,
        param.point.y,
      );
    });

    const resize = () => {
      if (!containerRef.current || !chartRef.current) return;
      const nextHeight = Math.max(containerRef.current.clientHeight, 200);
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: nextHeight,
      });
      if (containerRef.current.clientWidth > 0) {
        applyVisibleRange();
      }
    };

    const observer = new ResizeObserver(resize);
    observer.observe(el);
    window.addEventListener("resize", resize);

    return () => {
      hideTooltip();
      observer.disconnect();
      window.removeEventListener("resize", resize);
      vcpPrimitiveRef.current = null;
      chart.remove();
      chartRef.current = null;
    };
  }, [history, highlightDate, highlightMovePct, tailVisibleRange, extraMarkers, showRsi, period]);

  useEffect(() => {
    vcpPrimitiveRef.current?.setOverlay(vcpOverlay ?? null);
  }, [vcpOverlay]);

  const shellClass = fillHeight
    ? "flex h-full min-h-0 flex-col rounded-2xl border border-surface-border bg-surface-raised p-3"
    : "rounded-2xl border border-surface-border bg-surface-raised p-4 sm:p-6";

  if (loading) {
    return (
      <div className={`${shellClass} items-center justify-center`}>
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm text-slate-400">Loading chart…</p>
        </div>
      </div>
    );
  }

  if (!history.length) {
    return (
      <div
        className={`${shellClass} items-center justify-center border-dashed bg-surface-raised/50`}
      >
        <p className="text-center text-sm text-slate-500">
          {symbol ? `No chart data for ${symbol}` : "Select a stock from the results table"}
        </p>
      </div>
    );
  }

  const latest = history[history.length - 1];

  return (
    <div className={shellClass}>
      <div className="mb-2 flex shrink-0 flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold">{symbol}</h2>
          <p className="truncate text-xs text-slate-400">
            {companyName ?? "—"}
            {sector ? ` · ${sector}` : ""} · {history.length} bars · {source.toUpperCase()}
          </p>
        </div>
        <div className="flex shrink-0 gap-4 text-right">
          {marketCap && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Sector mcap</div>
              <div className="font-mono text-sm text-slate-200">{marketCap}</div>
            </div>
          )}
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Latest close</div>
            <div className="font-mono text-sm text-white">{formatPrice(latest.close)}</div>
          </div>
          {latestRsi != null && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500">RSI({period})</div>
              <div className="font-mono text-sm text-violet-300">{latestRsi.toFixed(1)}</div>
            </div>
          )}
          {highlightBar && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500">
                Move · {highlightDate}
              </div>
              <div
                className={`font-mono text-sm ${
                  (highlightMovePct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {highlightMovePct == null
                  ? "—"
                  : `${highlightMovePct >= 0 ? "+" : ""}${highlightMovePct.toFixed(2)}%`}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={fillHeight ? "relative min-h-0 flex-1" : "relative"}>
        <div
          ref={wrapperRef}
          className={`relative w-full ${fillHeight ? "h-full min-h-[200px]" : "h-[420px]"}`}
        >
          <div ref={containerRef} className="absolute inset-0 overflow-hidden rounded-lg" />
          <div
            ref={tooltipRef}
            className="pointer-events-none absolute z-20 hidden min-w-[140px] rounded-lg border border-surface-border bg-surface-raised/95 px-2.5 py-2 shadow-lg backdrop-blur-sm"
            style={{ display: "none" }}
          />
        </div>
      </div>

      {highlightBar && (
        <div className="mt-2 flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-surface-border/60 pt-2 text-[11px] text-slate-400">
          <span className="font-medium text-slate-300">{highlightDate}</span>
          <span>
            Close{" "}
            <span className="font-mono text-slate-200">{formatPrice(highlightBar.close)}</span>
          </span>
          <span>
            Move{" "}
            <span
              className={`font-mono ${
                (highlightMovePct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {highlightMovePct == null
                ? "—"
                : `${highlightMovePct >= 0 ? "+" : ""}${highlightMovePct.toFixed(2)}%`}
            </span>
          </span>
          {highlightRsi != null && (
            <span>
              RSI({period}){" "}
              <span className="font-mono text-violet-300">{highlightRsi.toFixed(1)}</span>
            </span>
          )}
          <span>
            Volume{" "}
            <span className="font-mono text-sky-400">{formatVolume(highlightBar.volume)}</span>
            <span className="ml-1 text-slate-500">
              ({highlightBar.volume.toLocaleString("en-IN")} shares)
            </span>
          </span>
          <span className="text-slate-500">
            O {formatPrice(highlightBar.open)} · H {formatPrice(highlightBar.high)} · L{" "}
            {formatPrice(highlightBar.low)}
          </span>
        </div>
      )}

      {vcpOverlay && (
        <div className="mt-1.5 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
          <span className="font-medium text-slate-400">VCP overlay</span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-3 rounded-sm border border-sky-400/50 bg-sky-400/15" />
            20d range
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-3 rounded-sm border border-amber-400/50 bg-amber-400/15" />
            10d
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-3 rounded-sm border border-orange-400/60 bg-orange-400/20" />
            5d
          </span>
          <span className="inline-flex items-center gap-1">
            <span
              className={`h-0.5 w-4 border-t border-dashed ${
                vcpOverlay.breakout ? "border-emerald-400" : "border-amber-400"
              }`}
            />
            Pivot ₹{vcpOverlay.pivotHigh.toFixed(2)}
          </span>
          {vcpOverlay.stage && (
            <span>
              Stage <span className="text-slate-300">{vcpOverlay.stage}</span>
            </span>
          )}
          <span>
            Base depth{" "}
            <span className="font-mono text-slate-300">{vcpOverlay.baseDepthPct.toFixed(1)}%</span>
          </span>
          <span>
            Vol{" "}
            <span className={vcpOverlay.volumeDry ? "text-emerald-400" : "text-amber-300"}>
              {vcpOverlay.volumeDry ? "dry" : "elevated"}
            </span>
          </span>
        </div>
      )}
    </div>
  );
}
