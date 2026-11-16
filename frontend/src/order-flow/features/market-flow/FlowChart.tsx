import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { isMarketSessionTime } from '@/order-flow/lib/marketSession';
import { stackLabels } from './flowLayout';
import { bandOf, changeTicks, chartReach, chartSpan, endLabel, lineOf, MINUTE, namedLines, pathOf, timeTicks, type FlowLine } from './flowChartModel';
import { useFlowFocus, type FocusState } from './flowFocus';
import type { FlowSettings, FlowStock, MarketFlow } from './marketFlowModel';

/**
 * Through the day: every underlying's future as a line from nought at the
 * window's start, bulls fanning up and bears down. The largest moves each side
 * are bold and named at their ends (bull names stacked above the zero rule,
 * bear names below), NIFTY is the ink reference line, everything else is the
 * faint fan (or the middle 80% as a band). The zero rule runs on through the
 * label gutter to the board's divider: above it is the Bullish half, below it
 * the Bearish.
 *
 * The chart never re-renders on hover. Pointing finds the nearest line within
 * 12px from a per-minute table, moves the crosshair by hand and hands the
 * symbol to the board's focus, which lights the tile; the lit lines are drawn
 * into three overlay paths.
 */

export interface FlowChartProps {
  flow: MarketFlow;
  settings: Pick<FlowSettings, 'named' | 'lines'>;
  width: number;
  height: number;
  /** Height of the board's head row above the chart: the zero rule sits at the board's middle, level with the divider. */
  headH?: number;
}

const PAD_TOP = 10;
const AXIS_BOTTOM = 46;
const LEFT = 52;
const LABEL_H = 18;
const CHAR_W = 7.1;
const SNAP_PX = 12;
const clockFormat = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
const clock = (ms: number) => clockFormat.format(ms);

function useClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}
const axisPct = (value: number) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Number(Math.abs(value).toFixed(2))}%`;
const toneOf = (stock: FlowStock | undefined) => (stock?.side === 'bullish' ? 'up' : stock?.side === 'bearish' ? 'down' : 'flat');

export const FlowChart = memo(function FlowChart({ flow, settings, width, height, headH = 0 }: FlowChartProps) {
  const focus = useFlowFocus();
  const [t0, t1] = useMemo(() => chartSpan(flow), [flow]);
  const bySymbol = useMemo(() => new Map(flow.stocks.map(stock => [stock.symbol, stock])), [flow.stocks]);

  const lines = useMemo(() => {
    const out: FlowLine[] = [];
    for (const stock of flow.stocks) {
      if (stock.changePct == null) continue;
      const line = lineOf(stock, t0, t1);
      if (line) out.push(line);
    }
    return out;
  }, [flow.stocks, t0, t1]);
  const drawn = useMemo(() => new Set(lines.map(line => line.symbol)), [lines]);
  const index = drawn.has('NIFTY') ? bySymbol.get('NIFTY') ?? null : null;

  const perSide = settings.named ?? (width >= 900 ? 8 : width >= 520 ? 5 : 3);
  const named = useMemo(() => namedLines(flow, perSide, drawn, index?.symbol ?? null), [flow, perSide, drawn, index]);
  const keep = useMemo(() => new Set([...named.up, ...named.down].map(stock => stock.symbol).concat(index ? [index.symbol] : [])), [named, index]);

  // Geometry: the zero rule at the board's middle when the chart is on a desktop board, else the plot's middle.
  const labelled = [...named.up, ...named.down, ...(index ? [index] : [])];
  const gutter = Math.ceil(Math.max(8, ...labelled.map(stock => endLabel(stock.symbol, stock.changePct).length)) * CHAR_W + 22);
  const xT0 = LEFT;
  const xT1 = Math.max(xT0 + 120, width - gutter);
  const zeroY = headH > 0 ? (height - headH) / 2 : (PAD_TOP + height - AXIS_BOTTOM) / 2;
  const half = Math.max(40, Math.min(zeroY - PAD_TOP, height - AXIS_BOTTOM - zeroY));
  const plotTop = zeroY - half;
  const plotBottom = zeroY + half;

  const reach = useMemo(() => chartReach(lines, keep, flow.floorPct), [lines, keep, flow.floorPct]);
  const geo = useMemo(() => {
    const xOf = (ms: number) => xT0 + ((Math.max(t0, Math.min(t1, ms)) - t0) / Math.max(1, t1 - t0)) * (xT1 - xT0);
    const yOf = (pct: number) => zeroY - (Math.max(-reach, Math.min(reach, pct)) / reach) * half;
    return { xOf, yOf };
  }, [xT0, xT1, t0, t1, zeroY, reach, half]);

  // Every line's path, and the fan as one path per direction (three elements, not two hundred).
  const paths = useMemo(() => {
    const map = new Map<string, string>();
    for (const line of lines) map.set(line.symbol, pathOf(line, geo.xOf, geo.yOf));
    return map;
  }, [lines, geo]);
  const fan = useMemo(() => {
    const out = { up: '', down: '', flat: '' };
    if (settings.lines === 'band') return out;
    for (const line of lines) {
      if (keep.has(line.symbol)) continue;
      out[toneOf(bySymbol.get(line.symbol))] += paths.get(line.symbol) ?? '';
    }
    return out;
  }, [lines, keep, paths, bySymbol, settings.lines]);
  const band = useMemo(() => {
    if (settings.lines !== 'band') return null;
    const b = bandOf(lines, t0, t1);
    if (b.t.length < 2) return null;
    const upper = b.t.map((t, i) => `${i ? 'L' : 'M'}${geo.xOf(t).toFixed(1)},${geo.yOf(b.hi[i]).toFixed(1)}`).join('');
    const lower = b.t.map((_, i) => b.t.length - 1 - i).map(i => `L${geo.xOf(b.t[i]).toFixed(1)},${geo.yOf(b.lo[i]).toFixed(1)}`).join('');
    const median = b.t.map((t, i) => `${i ? 'L' : 'M'}${geo.xOf(t).toFixed(1)},${geo.yOf(b.mid[i]).toFixed(1)}`).join('');
    return { area: `${upper}${lower}Z`, median };
  }, [settings.lines, lines, t0, t1, geo]);

  // A per-minute table of every line's value, for the crosshair's nearest line.
  const table = useMemo(() => {
    const minutes = Math.max(1, Math.round((t1 - t0) / MINUTE));
    return lines.map(line => {
      const values = new Float32Array(minutes + 1).fill(Number.NaN);
      let j = 0;
      const first = Math.round((line.t[0] - t0) / MINUTE);
      const last = Math.round((line.t[line.t.length - 1] - t0) / MINUTE);
      for (let m = Math.max(0, first); m <= Math.min(minutes, last); m++) {
        const at = t0 + m * MINUTE;
        while (j + 1 < line.t.length && line.t[j + 1] <= at) j++;
        values[m] = line.v[j];
      }
      return { symbol: line.symbol, values };
    });
  }, [lines, t0, t1]);

  // Labels: the bull names stacked above the zero rule, the bear names below, each as near its line's end as the others allow.
  const labels = useMemo(() => {
    const endOf = (stock: FlowStock) => {
      const line = lines.find(item => item.symbol === stock.symbol);
      return line ? { x: geo.xOf(line.t[line.t.length - 1]), y: geo.yOf(line.v[line.v.length - 1]) } : null;
    };
    const upList = [...named.up, ...(index && (index.changePct ?? 0) >= 0 ? [index] : [])];
    const downList = [...named.down, ...(index && (index.changePct ?? 0) < 0 ? [index] : [])];
    const place = (list: FlowStock[], top: number, bottom: number) => {
      const anchors = list.map(stock => ({ stock, end: endOf(stock) })).filter((item): item is { stock: FlowStock; end: { x: number; y: number } } => item.end != null);
      const room = Math.max(1, Math.floor((bottom - top) / LABEL_H) + 1);
      const kept = anchors.slice(0, room);
      const ys = stackLabels(kept.map(item => ({ id: item.stock.symbol, y: Math.max(top, Math.min(bottom, item.end.y)) })), { height: LABEL_H, top, bottom });
      return kept.map(item => ({ ...item, y: ys.get(item.stock.symbol) ?? item.end.y }));
    };
    return [...place(upList, plotTop + 6, zeroY - 11), ...place(downList, zeroY + 11, plotBottom - 6)];
  }, [lines, named, index, geo, plotTop, plotBottom, zeroY]);

  const yTicks = changeTicks(reach, half, flow.window);
  const xTicks = useMemo(() => timeTicks(t0, t1, xT1 - xT0, flow.window), [t0, t1, xT1, xT0, flow.window]);
  const nowAt = Math.floor(useClock() / MINUTE) * MINUTE;
  const nowX = flow.window === 'day' && isMarketSessionTime(nowAt) && nowAt > t0 && nowAt < t1 ? geo.xOf(nowAt) : null;
  const tickClear = (t: number) => nowX == null || Math.abs(geo.xOf(t) - nowX) >= 36;

  // ── Focus: lit lines drawn into the overlay; the crosshair moved by hand ──
  const litRef = useRef<SVGGElement>(null);
  const crossRef = useRef<SVGGElement>(null);
  useEffect(() => focus.subscribe((state: FocusState) => {
    const g = litRef.current;
    if (!g) return;
    const ds = { up: '', down: '', flat: '' };
    if (state.symbol) {
      const d = paths.get(state.symbol);
      if (d) ds[toneOf(bySymbol.get(state.symbol))] = d;
    } else if (state.sector) {
      for (const stock of flow.stocks) if (stock.sector === state.sector) ds[toneOf(stock)] += paths.get(stock.symbol) ?? '';
    }
    for (const tone of ['up', 'down', 'flat'] as const) g.querySelector(`.is-${tone}`)?.setAttribute('d', ds[tone]);
    g.classList.toggle('is-sector', Boolean(state.sector));
  }), [focus, paths, bySymbol, flow.stocks]);

  const snapRef = useRef<string | null>(null);
  const move = (event: React.PointerEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    const cross = crossRef.current;
    if (!svg || !cross) return;
    const box = svg.getBoundingClientRect();
    const px = event.clientX - box.left;
    const py = event.clientY - box.top;
    const minutes = Math.round((t1 - t0) / MINUTE);
    const m = Math.max(0, Math.min(minutes, Math.round(((px - xT0) / Math.max(1, xT1 - xT0)) * minutes)));
    const at = t0 + m * MINUTE;
    const x = geo.xOf(at);
    let best: string | null = null;
    let bestDy = SNAP_PX + 1;
    let bestV = 0;
    for (const row of table) {
      const v = row.values[m];
      if (Number.isNaN(v)) continue;
      const dy = Math.abs(geo.yOf(v) - py);
      if (dy < bestDy || (dy === bestDy && keep.has(row.symbol))) { bestDy = dy; best = row.symbol; bestV = v; }
    }
    cross.style.display = '';
    const [vline, tag, tagText, dot, val, valText] = cross.children as unknown as SVGElement[];
    vline.setAttribute('x1', String(x)); vline.setAttribute('x2', String(x));
    const tw = 40;
    tag.setAttribute('x', String(Math.max(xT0, Math.min(xT1 - tw, x - tw / 2))));
    tagText.setAttribute('x', String(Math.max(xT0 + tw / 2, Math.min(xT1 - tw / 2, x))));
    tagText.textContent = clock(at);
    if (best) {
      const y = geo.yOf(bestV);
      const text = endLabel(best, bestV);
      const w = text.length * CHAR_W + 12;
      const left = x + 10 + w > xT1 ? x - 10 - w : x + 10;
      dot.setAttribute('cx', String(x)); dot.setAttribute('cy', String(y));
      dot.setAttribute('class', `mf-chart__cdot is-${toneOf(bySymbol.get(best))}`);
      val.setAttribute('x', String(left)); val.setAttribute('y', String(y - 10)); val.setAttribute('width', String(w));
      valText.setAttribute('x', String(left + 6)); valText.setAttribute('y', String(y + 4));
      valText.textContent = text;
      dot.style.display = ''; val.style.display = ''; valText.style.display = '';
    } else {
      dot.style.display = 'none'; val.style.display = 'none'; valText.style.display = 'none';
    }
    if (best !== snapRef.current) {
      snapRef.current = best;
      focus.hoverSymbol(best, 'chart');
    }
  };
  const leave = () => {
    if (crossRef.current) crossRef.current.style.display = 'none';
    snapRef.current = null;
    focus.hoverSymbol(null, 'chart');
  };
  const click = () => {
    if (snapRef.current) focus.togglePin(snapRef.current, 'chart');
    else focus.clear();
  };

  const legendN = Math.max(named.up.length, named.down.length);
  return (
    <div className="mf-chart" style={{ width, height }}>
      <svg className="mf-chart__svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label={`Through the day: ${lines.length} futures from nought at ${clock(t0)}. ${flow.bullish.length} up, ${flow.bearish.length} down. Largest up: ${named.up.slice(0, 3).map(stock => endLabel(stock.symbol, stock.changePct)).join(', ') || 'none'}. Largest down: ${named.down.slice(0, 3).map(stock => endLabel(stock.symbol, stock.changePct)).join(', ') || 'none'}.`}>
        <g className="mf-chart__axis">
          <rect className="mf-chart__floor" x={xT0} width={xT1 - xT0} y={geo.yOf(flow.floorPct)} height={Math.max(0, geo.yOf(-flow.floorPct) - geo.yOf(flow.floorPct))} />
          {yTicks.flatMap(value => [value, -value]).map(value => (
            <g key={value}>
              <line className="mf-chart__grid" x1={xT0} x2={xT1} y1={geo.yOf(value)} y2={geo.yOf(value)} />
              <text className="mf-chart__tick" x={xT0 - 8} y={geo.yOf(value) + 4} textAnchor="end">{axisPct(value)}</text>
            </g>
          ))}
          {xTicks.map((t, i) => (
            <g key={t}>
              <line className="mf-chart__grid is-time" x1={geo.xOf(t)} x2={geo.xOf(t)} y1={plotTop} y2={plotBottom} />
              {tickClear(t) && <text className="mf-chart__tick" x={geo.xOf(t)} y={plotBottom + 17} textAnchor={i === 0 && flow.window === 'day' ? 'start' : i === xTicks.length - 1 && flow.window === 'day' ? 'end' : 'middle'}>{clock(t)}</text>}
            </g>
          ))}
          <text className="mf-chart__tick is-zero" x={xT0 - 8} y={zeroY + 4} textAnchor="end">0%</text>
        </g>

        <g className="mf-fan">
          {band && <path className="mf-chart__band" d={band.area} />}
          {band && <path className="mf-chart__median" d={band.median} />}
          {fan.flat && <path className="mf-chart__faint is-flat" d={fan.flat} />}
          {fan.down && <path className="mf-chart__faint is-down" d={fan.down} />}
          {fan.up && <path className="mf-chart__faint is-up" d={fan.up} />}
        </g>
        <line className="mf-chart__zero" x1={xT0} x2={xT1} y1={zeroY} y2={zeroY} />
        <g className="mf-named">
          {[...named.down, ...named.up].map(stock => (
            <path key={stock.symbol} className={`mf-chart__bold is-${toneOf(stock)}`} data-sym={stock.symbol} d={paths.get(stock.symbol)} />
          ))}
          {index && <path className="mf-chart__bold is-index" data-sym={index.symbol} d={paths.get(index.symbol)} />}
        </g>
        <g className="mf-chart__lit" ref={litRef}>
          <path className="is-flat" /><path className="is-down" /><path className="is-up" />
        </g>
        <circle className="mf-chart__origin" cx={geo.xOf(t0)} cy={zeroY} r="3" />
        {nowX != null && (
          <g className="mf-chart__now">
            <line x1={nowX} x2={nowX} y1={plotTop} y2={plotBottom + 14} />
            <text className="mf-chart__now-label" x={nowX - 6} y={plotBottom + 17} textAnchor="end">{clock(nowAt)}</text>
          </g>
        )}

        <g className="mf-chart__labels">
          {labels.map(({ stock, end, y }) => (
            <g key={stock.symbol} className={`mf-chart__label is-${stock === index ? 'index' : toneOf(stock)}`} data-sym={stock.symbol}
              onPointerEnter={() => focus.hoverSymbol(stock.symbol, 'chart')} onPointerLeave={() => focus.hoverSymbol(null, 'chart')}
              onClick={() => focus.togglePin(stock.symbol, 'chart')}>
              <circle cx={end.x} cy={end.y} r="2.6" />
              <path className="mf-chart__leader" d={`M${end.x.toFixed(1)},${end.y.toFixed(1)}H${(xT1 + 3).toFixed(1)}L${(xT1 + 9).toFixed(1)},${y.toFixed(1)}H${(xT1 + 11).toFixed(1)}`} />
              <text x={xT1 + 13} y={y + 4}>{stock === index && index.symbol === 'NIFTY' ? 'NIFTY fut' : stock.symbol}<tspan dx="5">{endLabel('', stock.changePct).trim()}</tspan></text>
            </g>
          ))}
        </g>

        <g className="mf-chart__cross" ref={crossRef} style={{ display: 'none' }} aria-hidden="true">
          <line className="mf-chart__vline" y1={plotTop} y2={plotBottom} />
          <rect className="mf-chart__ttag" y={plotBottom + 4} width="40" height="18" rx="4" />
          <text className="mf-chart__ttext" y={plotBottom + 17} textAnchor="middle" />
          <circle className="mf-chart__cdot" r="3.5" />
          <rect className="mf-chart__vtag" height="20" rx="4" />
          <text className="mf-chart__vtext" />
        </g>
        <rect className="mf-chart__hit" x={xT0} y={plotTop} width={xT1 - xT0} height={plotBottom - plotTop}
          onPointerMove={move} onPointerLeave={leave} onClick={click} />
      </svg>
      <p className="mf-chart__legend" style={{ left: xT0 }}>
        <span><i className="is-up" aria-hidden="true" />Top {legendN} up</span>
        <span><i className="is-down" aria-hidden="true" />Top {legendN} down</span>
        {index && <span><i className="is-index" aria-hidden="true" />NIFTY</span>}
        <span><i className={settings.lines === 'band' ? 'is-band' : 'is-faint'} aria-hidden="true" />{settings.lines === 'band' ? 'Middle 80%' : 'Every other future'}</span>
        <span><i className="is-floor" aria-hidden="true" />Flat ±{flow.floorPct}%</span>
      </p>
    </div>
  );
});
