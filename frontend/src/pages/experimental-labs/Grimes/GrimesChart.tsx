import { useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { GrimesChartGuideSection, GrimesChartPayload } from "@/lib/api";
import { istChartLocalization, istTimeScaleOptions } from "@/lib/chartTime";
import { wildersRsiSeries } from "@/lib/indicators";
import { GrimesChartLegend } from "./GrimesChartLegend";

type OverlayFlags = {
  pivots: boolean;
  mas: boolean;
  setups: boolean;
  riskBox: boolean;
  keltner: boolean;
};

type Props = {
  data: GrimesChartPayload | null;
  loading: boolean;
  overlays: OverlayFlags;
  chartGuideIntro?: string;
  chartGuideSections?: GrimesChartGuideSection[];
  /** Session date to mark on the chart and read indicators for. */
  highlightDate?: string | null;
  rsiPeriod?: number;
};

/** Per-bar indicator values used by the tooltip and the selected-date strip. */
type BarView = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  movePct: number | null;
  ema20: number | null;
  sma50: number | null;
  kcUpper: number | null;
  kcLower: number | null;
  rsi: number | null;
  setups: string[];
};

const SETUP_COLOR: Record<string, string> = {
  TREND_PULLBACK: "#34d399",
  COMPLEX_PULLBACK: "#38bdf8",
  VOL_SQUEEZE: "#fbbf24",
  FAILED_BREAKOUT: "#fb7185",
  CLIMACTIC_EXHAUSTION: "#fb923c",
  ABSORPTION: "#c084fc",
};

const SETUP_SHORT: Record<string, string> = {
  TREND_PULLBACK: "PB",
  COMPLEX_PULLBACK: "ABC",
  VOL_SQUEEZE: "NR7",
  FAILED_BREAKOUT: "FT",
  CLIMACTIC_EXHAUSTION: "CLX",
  ABSORPTION: "ABS",
};

/** LW charts: circle | square | arrowUp | arrowDown (no native diamond). */
function setupMarkerShape(
  type: string,
  side?: string,
): "circle" | "arrowUp" | "arrowDown" {
  if (type === "TREND_PULLBACK" || type === "FAILED_BREAKOUT" || type === "CLIMACTIC_EXHAUSTION") {
    return side === "short" ? "arrowDown" : "arrowUp";
  }
  return "circle";
}

function pivotLabel(label: string | null | undefined, kind: string): string {
  if (label) return label;
  return kind === "high" ? "H" : "L";
}

function mergeMarker(
  map: Map<string, SeriesMarker<Time>>,
  time: string,
  incoming: SeriesMarker<Time>,
) {
  const key = String(time);
  const prev = map.get(key);
  if (!prev) {
    map.set(key, incoming);
    return;
  }
  const prevText = prev.text ?? "";
  const nextText = incoming.text ?? "";
  const combined = prevText && nextText && prevText !== nextText ? `${prevText}·${nextText}` : nextText || prevText;
  map.set(key, {
    ...incoming,
    text: combined.length > 12 ? combined.slice(0, 11) + "…" : combined,
  });
}

const REGIME_LABEL: Record<string, string> = {
  TREND_BULL: "Bull trend",
  TREND_BEAR: "Bear trend",
  TRADING_RANGE: "Trading range",
  VOLATILITY_COMPRESSION: "Volatility squeeze",
  CLIMACTIC_EXHAUSTION: "Climactic exhaustion",
};

function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function formatVolume(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (value >= 1e7) return `${(value / 1e7).toFixed(2)} Cr`;
  if (value >= 1e5) return `${(value / 1e5).toFixed(2)} L`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)} K`;
  return value.toLocaleString("en-IN");
}

function formatMovePct(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function timeToDateString(time: Time): string | null {
  if (typeof time === "string") return time;
  if (typeof time === "number") return new Date(time * 1000).toISOString().slice(0, 10);
  if (time && typeof time === "object" && "year" in time) {
    const { year, month, day } = time;
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }
  return null;
}

function seriesByDate(points: Array<{ time: string; value: number }>): Map<string, number> {
  return new Map(points.map((p) => [p.time, p.value]));
}

function buildBarViews(data: GrimesChartPayload, rsiPeriod: number): Map<string, BarView> {
  const ema = seriesByDate(data.ema20);
  const sma = seriesByDate(data.sma50);
  const kcUp = seriesByDate(data.kc_upper);
  const kcLow = seriesByDate(data.kc_lower);

  const setups = new Map<string, string[]>();
  for (const s of data.history_setups) {
    const label = SETUP_SHORT[s.type] ?? s.type.replace(/_/g, " ");
    const list = setups.get(s.timestamp) ?? [];
    if (!list.includes(label)) list.push(label);
    setups.set(s.timestamp, list);
  }

  const rsiValues = wildersRsiSeries(
    data.candles.map((c) => c.close),
    rsiPeriod,
  );
  const rsiOffset = data.candles.length - rsiValues.length;

  const out = new Map<string, BarView>();
  data.candles.forEach((c, i) => {
    const rsiIndex = i - rsiOffset;
    out.set(c.date, {
      ...c,
      movePct: c.open ? ((c.close - c.open) / c.open) * 100 : null,
      ema20: ema.get(c.date) ?? null,
      sma50: sma.get(c.date) ?? null,
      kcUpper: kcUp.get(c.date) ?? null,
      kcLower: kcLow.get(c.date) ?? null,
      rsi: rsiIndex >= 0 ? (rsiValues[rsiIndex] ?? null) : null,
      setups: setups.get(c.date) ?? [],
    });
  });
  return out;
}

export function GrimesChart({
  data,
  loading,
  overlays,
  chartGuideIntro,
  chartGuideSections,
  highlightDate,
  rsiPeriod = 14,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const period = Math.max(2, Math.min(200, rsiPeriod));
  const barViews = useMemo(
    () => (data ? buildBarViews(data, period) : new Map<string, BarView>()),
    [data, period],
  );

  /** Selected session, or the last traded bar on/before it. */
  const markedDate = useMemo(() => {
    const candles = data?.candles ?? [];
    if (!candles.length) return null;
    if (!highlightDate) return candles[candles.length - 1].date;
    if (barViews.has(highlightDate)) return highlightDate;
    for (let i = candles.length - 1; i >= 0; i -= 1) {
      if (candles[i].date <= highlightDate) return candles[i].date;
    }
    return candles[candles.length - 1].date;
  }, [highlightDate, barViews, data]);

  const markedBar = markedDate ? (barViews.get(markedDate) ?? null) : null;

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
      grid: { vertLines: { color: "#2a3544" }, horzLines: { color: "#2a3544" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2a3544" },
      timeScale: { borderColor: "#2a3544", ...istTimeScaleOptions(false) },
      localization: istChartLocalization(),
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

    if (overlays.mas && data.ema20.length) {
      const ema = chart.addLineSeries({
        color: "#38bdf8",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: "20 EMA",
      });
      ema.setData(data.ema20.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    if (overlays.mas && data.sma50.length) {
      const sma = chart.addLineSeries({
        color: "#fbbf24",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: "50 SMA",
      });
      sma.setData(data.sma50.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    if (overlays.keltner && data.kc_upper.length) {
      const up = chart.addLineSeries({
        color: "rgba(148,163,184,0.45)",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
        title: "KC+",
      });
      up.setData(data.kc_upper.map((p) => ({ time: p.time as Time, value: p.value })));
      const dn = chart.addLineSeries({
        color: "rgba(148,163,184,0.45)",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
        title: "KC-",
      });
      dn.setData(data.kc_lower.map((p) => ({ time: p.time as Time, value: p.value })));
    }

    const markerMap = new Map<string, SeriesMarker<Time>>();

    if (overlays.pivots) {
      for (const p of data.pivots) {
        const isHigh = p.kind === "high";
        mergeMarker(markerMap, p.timestamp, {
          time: p.timestamp as Time,
          position: isHigh ? "aboveBar" : "belowBar",
          shape: "circle",
          color: isHigh ? "#94a3b8" : "#64748b",
          text: pivotLabel(p.label, p.kind),
          size: 1,
        });
      }
    }

    if (overlays.setups) {
      const byTime = new Map<string, { labels: string[]; type: string; side?: string }>();
      for (const s of data.history_setups) {
        const label = SETUP_SHORT[s.type] ?? s.type.slice(0, 3);
        const cur = byTime.get(s.timestamp) ?? { labels: [], type: s.type, side: s.side };
        if (!cur.labels.includes(label)) cur.labels.push(label);
        cur.type = s.type;
        cur.side = s.side;
        byTime.set(s.timestamp, cur);
      }
      for (const [time, meta] of byTime) {
        const shape = setupMarkerShape(meta.type, meta.side);
        const isArrowDown = shape === "arrowDown";
        mergeMarker(markerMap, time, {
          time: time as Time,
          position: isArrowDown ? "aboveBar" : "belowBar",
          shape,
          color: SETUP_COLOR[meta.type] ?? "#e2e8f0",
          text: meta.labels.join("+"),
          size: shape === "circle" ? 2 : 1,
        });
      }
    }

    const marked = markedDate ? barViews.get(markedDate) : undefined;
    if (marked) {
      const isUp = (marked.movePct ?? 0) >= 0;
      mergeMarker(markerMap, marked.date, {
        time: marked.date as Time,
        position: "aboveBar",
        shape: isUp ? "arrowUp" : "arrowDown",
        color: isUp ? "#22c55e" : "#ef4444",
        size: 1,
      });
    }

    candles.setMarkers(
      [...markerMap.values()].sort((a, b) => String(a.time).localeCompare(String(b.time))),
    );

    if (overlays.riskBox && data.risk_box) {
      const rb = data.risk_box;
      candles.createPriceLine({
        price: rb.entry,
        color: "rgba(56,189,248,0.9)",
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "Entry",
      });
      candles.createPriceLine({
        price: rb.stop,
        color: "rgba(251,113,133,0.9)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Stop",
      });
      const t1 = rb.targets["1"] ?? rb.targets["1.0"];
      const t2 = rb.targets["2"] ?? rb.targets["2.0"];
      const t3 = rb.targets["3"] ?? rb.targets["3.0"];
      if (t1 != null) {
        candles.createPriceLine({
          price: t1,
          color: "rgba(52,211,153,0.55)",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: "1R",
        });
      }
      if (t2 != null) {
        candles.createPriceLine({
          price: t2,
          color: "rgba(52,211,153,0.7)",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: "2R",
        });
      }
      if (t3 != null) {
        candles.createPriceLine({
          price: t3,
          color: "rgba(16,185,129,0.85)",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: "3R",
        });
      }
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const hideTooltip = () => {
      const tip = tooltipRef.current;
      if (tip) tip.style.display = "none";
    };

    const row = (label: string, value: string, color: string) =>
      `<div><span style="color:#64748b">${label} </span><span style="font-family:monospace;color:${color}">${value}</span></div>`;

    chart.subscribeCrosshairMove((param) => {
      const tip = tooltipRef.current;
      const wrap = wrapperRef.current;
      if (!tip || !wrap) return;
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
      const bar = dateStr ? barViews.get(dateStr) : undefined;
      if (!bar) {
        hideTooltip();
        return;
      }

      const moveColor = (bar.movePct ?? 0) >= 0 ? "#4ade80" : "#f87171";
      tip.innerHTML =
        `<div style="font-size:10px;color:#94a3b8;margin-bottom:4px">${bar.date}` +
        (bar.date === markedDate ? ` · <span style="color:#38bdf8">selected</span>` : "") +
        `</div>` +
        `<div style="font-size:11px;line-height:1.5">` +
        row("Close", formatPrice(bar.close), "#f1f5f9") +
        row("Move", formatMovePct(bar.movePct), moveColor) +
        row("20 EMA", formatPrice(bar.ema20), "#38bdf8") +
        row("50 SMA", formatPrice(bar.sma50), "#fbbf24") +
        (bar.kcUpper != null && bar.kcLower != null
          ? row("Keltner", `${formatPrice(bar.kcLower)} – ${formatPrice(bar.kcUpper)}`, "#cbd5f5")
          : "") +
        (bar.rsi != null ? row(`RSI(${period})`, bar.rsi.toFixed(1), "#c4b5fd") : "") +
        row("Volume", formatVolume(bar.volume), "#38bdf8") +
        (bar.setups.length ? row("Setup", bar.setups.join(" + "), "#34d399") : "") +
        `</div>`;

      const maxX = wrap.clientWidth - tip.offsetWidth - 8;
      const maxY = wrap.clientHeight - tip.offsetHeight - 8;
      tip.style.left = `${Math.max(8, Math.min(param.point.x + 12, maxX))}px`;
      tip.style.top = `${Math.max(8, Math.min(param.point.y - 10, maxY))}px`;
      tip.style.display = "block";
    });

    const onResize = () => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: Math.max(containerRef.current.clientHeight, 280),
      });
    };
    window.addEventListener("resize", onResize);
    return () => {
      hideTooltip();
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [
    data,
    barViews,
    markedDate,
    period,
    overlays.pivots,
    overlays.mas,
    overlays.setups,
    overlays.riskBox,
    overlays.keltner,
  ]);

  return (
    <div className="panel relative flex h-full min-h-[280px] flex-col overflow-hidden">
      <GrimesChartLegend
        chartGuideIntro={chartGuideIntro}
        chartGuideSections={chartGuideSections}
      />
      {data?.ticker ? (
        <div className="pointer-events-none absolute left-2 top-2 z-20 max-w-[min(70%,22rem)] rounded-lg border border-surface-border/80 bg-[#121820]/90 px-2.5 py-1.5 shadow-lg backdrop-blur-sm">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-[14px] font-semibold tracking-tight text-slate-100">
              {data.ticker}
            </span>
            {data.kind === "index" ? (
              <span className="text-[10px] font-medium uppercase text-amber-300">Index</span>
            ) : null}
            <span className="text-[11px] tabular-nums text-slate-300">
              ₹
              {data.price.toLocaleString("en-IN", {
                maximumFractionDigits: 2,
              })}
            </span>
          </div>
          {data.company_name ? (
            <p className="truncate text-[11px] leading-snug text-slate-400" title={data.company_name}>
              {data.company_name}
            </p>
          ) : null}
          <p className="mt-0.5 text-[10px] text-slate-400">
            {REGIME_LABEL[data.regime] ?? data.regime.replace(/_/g, " ")} · as of {data.as_of}
          </p>
        </div>
      ) : null}
      {loading ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a2332]/70 text-[12px] text-slate-400">
          Loading structure…
        </div>
      ) : null}
      {!loading && !data?.candles.length ? (
        <div className="flex h-full items-center justify-center text-[12px] text-slate-400">
          Select a symbol
        </div>
      ) : (
        <>
          <div ref={wrapperRef} className="relative min-h-0 flex-1">
            <div ref={containerRef} className="absolute inset-0" />
            <div
              ref={tooltipRef}
              className="pointer-events-none absolute z-30 hidden min-w-[150px] rounded-lg border border-surface-border bg-[#121820]/95 px-2.5 py-2 shadow-lg backdrop-blur-sm"
              style={{ display: "none" }}
            />
          </div>
          {markedBar ? (
            <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-surface-border/60 px-2.5 py-1.5 text-[11px] text-slate-400">
              <span className="font-medium text-slate-300">{markedBar.date}</span>
              <span>
                Close <span className="font-mono text-slate-200">{formatPrice(markedBar.close)}</span>
              </span>
              <span>
                Move{" "}
                <span
                  className={`font-mono ${
                    (markedBar.movePct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {formatMovePct(markedBar.movePct)}
                </span>
              </span>
              <span>
                20 EMA <span className="font-mono text-sky-400">{formatPrice(markedBar.ema20)}</span>
              </span>
              <span>
                50 SMA <span className="font-mono text-amber-300">{formatPrice(markedBar.sma50)}</span>
              </span>
              {markedBar.kcUpper != null && markedBar.kcLower != null ? (
                <span>
                  Keltner{" "}
                  <span className="font-mono text-slate-300">
                    {formatPrice(markedBar.kcLower)} – {formatPrice(markedBar.kcUpper)}
                  </span>
                </span>
              ) : null}
              {markedBar.rsi != null ? (
                <span>
                  RSI({period}){" "}
                  <span className="font-mono text-violet-300">{markedBar.rsi.toFixed(1)}</span>
                </span>
              ) : null}
              <span>
                Volume <span className="font-mono text-sky-400">{formatVolume(markedBar.volume)}</span>
              </span>
              {markedBar.setups.length ? (
                <span>
                  Setup{" "}
                  <span className="font-mono text-emerald-300">{markedBar.setups.join(" + ")}</span>
                </span>
              ) : null}
              <span className="text-slate-400">
                O {formatPrice(markedBar.open)} · H {formatPrice(markedBar.high)} · L{" "}
                {formatPrice(markedBar.low)}
              </span>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
