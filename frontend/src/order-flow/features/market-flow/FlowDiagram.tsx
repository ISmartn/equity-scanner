import { memo, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { useReducedMotion } from 'motion/react';
import { fmtPrice } from '@/order-flow/utils/formatters';
import { candlesFromCloses, compressedScale, compressedTicks, drawnValues, gateRows, sCurve, sCurveOn } from './diagramModel';
import { chartReach, chartSpan, endLabel, lineOf, MINUTE, namedLines, pathOf, provisionalLine, timeTicks, type FlowLine } from './flowChartModel';
import { useFlowFocus, type FocusState } from './flowFocus';
import { BuildMark, buildUpText, ChangeText, DotMeter, heatStyle, pctText, TickFlash, signedText, Spark, toneOf, windowCandles, shortSector } from './FlowParts';
import { SymbolMark } from '@/order-flow/components/common/SymbolMark';
import { FlowPopup } from './FlowPopup';
import { demoFeatured } from './demoFeatured';
import { levelText, type FlowSector, type FlowSettings, type FlowStock, type MarketFlow } from './marketFlowModel';
import { useBox } from './useBox';

/**
 * Order Flow on a wide desktop: one continuous diagram, read left to right.
 *
 *   distribution strip
 *   fan chart ─▶ gate ─▶ curves ─▶ small tiles · tall tiles ─▶ large cards
 *
 * Every future's line leaves nought at the window's start and fans out on a
 * compressed scale (the crowd near nought spreads, the large moves still fit).
 * At the window's end each line runs into the gate, where the gate's height
 * is shared by count: the up names in rank order at the top, the flat ones in
 * the grey funnel, the down names at the bottom with the largest lowest. From
 * the gate a thin curve carries each line on to its own tile; the strongest
 * readings go on to a tall tile with their option open interest by strike and
 * a large card. The chart's zero rule bends up into the divider between the
 * halves. Sector pills sit over the chart's left side, each with a faint line
 * at its median.
 *
 * Everything is placed by arithmetic from the board's size (no measuring of
 * tiles), so the curves meet their tiles exactly and nothing shifts as the
 * futures arrive. Hover never re-renders: the focus controller lights the
 * elements and the lit path (line, gate run, curve, card joint) is drawn into
 * an overlay by hand.
 */

interface FlowDiagramProps {
  flow: MarketFlow;
  settings: Pick<FlowSettings, 'named' | 'lines'>;
  status: ReactNode;
}

const PAD = 12;
const STRIP_H = 92;
const AXIS_H = 26;
const GATE_W = 72;
/** The room between the fan's end and the gate, where each line bends to its row. */
/** The run-in from the chart's last minute to the tunnel: long enough that the lines visibly converge. */
const GATE_GAP = 64;
const CONN_W = 92;
const LEFT_AXIS = 44;
const TILE_GAP = 5;
const SNAP_PX = 10;
const clockFormat = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
const clock = (ms: number) => clockFormat.format(ms);

/** The clock, refreshed through the session so the current-minute line keeps up. */
function useClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}
const tone = (stock: FlowStock | undefined) => (stock?.side === 'bullish' ? 'up' : stock?.side === 'bearish' ? 'down' : 'flat');

interface Box { x: number; y: number; w: number; h: number }

/** The board's columns and rows, from its size. */
export function diagramLayout(W: number, H: number) {
  const wide = W >= 1680;
  const cardsW = wide ? Math.min(440, Math.round(W * 0.22)) : Math.round(Math.max(270, Math.min(320, W * 0.21)));
  const tallW = wide ? 156 : W < 1500 ? 114 : 124;
  const smallW = wide ? 112 : W < 1500 ? 94 : 96;
  const cardsX = W - PAD - cardsW;
  const tallX = cardsX - 12 - tallW;
  const smallX0 = tallX - 8 - (3 * smallW + 2 * TILE_GAP);
  const gateR = smallX0 - CONN_W;
  const gateL = gateR - GATE_W;
  const xT0 = PAD + LEFT_AXIS;
  const xT1 = gateL - GATE_GAP;
  const plotTop = PAD + STRIP_H + 8;
  const plotBottom = H - PAD - AXIS_H;
  const zeroY = (plotTop + plotBottom) / 2;
  const midY = H / 2;
  // The halves stand clear of the bar between them.
  const halves = { bullish: { top: PAD, bottom: midY - 9 }, bearish: { top: midY + 9, bottom: H - PAD } };
  const perHalf = H >= 980 ? 3 : 2;
  return { W, H, cardsW, cardsX, tallW, tallX, smallW, smallX0, gateL, gateR, xT0, xT1, plotTop, plotBottom, zeroY, midY, halves, perHalf };
}
type Layout = ReturnType<typeof diagramLayout>;

/** The small tiles' boxes in a half: three columns, whole rows; the up half fills from the top, the down half from the bottom. */
function smallBoxes(layout: Layout, side: 'bullish' | 'bearish', count: number): { boxes: Box[]; rows: number } {
  const { top, bottom } = layout.halves[side];
  const height = bottom - top;
  const rows = Math.max(1, Math.floor((height + TILE_GAP) / (44 + TILE_GAP)));
  let h = (height - (rows - 1) * TILE_GAP) / rows;
  // Few names: the tiles grow (up to 84px) rather than leave empty rows.
  const needed = Math.ceil(count / 3);
  if (count > 0 && needed < rows) h = Math.min(84, (height - (needed - 1) * TILE_GAP) / needed);
  const boxes: Box[] = [];
  for (let i = 0; i < count; i++) {
    const row = Math.floor(i / 3);
    const col = i % 3;
    const y = side === 'bullish' ? top + row * (h + TILE_GAP) : bottom - h - row * (h + TILE_GAP);
    boxes.push({ x: layout.smallX0 + col * (layout.smallW + TILE_GAP), y, w: layout.smallW, h });
  }
  return { boxes, rows };
}

/** The tall tiles' and cards' rows in a half, top to bottom. */
function featureBoxes(layout: Layout, side: 'bullish' | 'bearish'): Array<{ tall: Box; card: Box }> {
  const { top, bottom } = layout.halves[side];
  const n = layout.perHalf;
  const h = (bottom - top - (n - 1) * 8) / n;
  return Array.from({ length: n }, (_, i) => {
    const y = top + i * (h + 8);
    return { tall: { x: layout.tallX, y, w: layout.tallW, h }, card: { x: layout.cardsX, y, w: layout.cardsW, h } };
  });
}

export const FlowDiagram = memo(function FlowDiagram({ flow, settings, status }: FlowDiagramProps) {
  const [boardRef, box] = useBox<HTMLDivElement>();
  const ready = box.width > 900 && box.height > 300;
  return (
    <div className="mf-dg" ref={boardRef}>
      {ready ? <DiagramBody flow={flow} settings={settings} status={status} W={box.width} H={box.height} /> : <div className="mf-skel is-diagram" aria-hidden="true" />}
    </div>
  );
});

function DiagramBody({ flow, settings, status, W, H }: FlowDiagramProps & { W: number; H: number }) {
  const focus = useFlowFocus();
  // Motion (owner, 26 Oct 2026: bring OrderBlock's animation in, in our
  // theme): a halo at the origin, comets along the lead paths, a breathing
  // "now" edge. SMIL motion cannot be stopped from CSS, so the comets are
  // not drawn at all for a reader who asked for reduced motion.
  const calm = useReducedMotion() ?? false;
  const pathId = `mf-lead-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const layout = useMemo(() => diagramLayout(W, H), [W, H]);
  const { xT0, xT1, gateL, gateR, plotTop, plotBottom, zeroY } = layout;
  const half = (plotBottom - plotTop) / 2;
  // The pills take less of a narrow chart.
  const pillW = xT1 - xT0 < 460 ? 112 : 132;
  const [t0, t1] = useMemo(() => chartSpan(flow), [flow]);
  const bySymbol = useMemo(() => new Map(flow.stocks.map(stock => [stock.symbol, stock])), [flow.stocks]);

  // ── Tiles: the small ones (every name on the side but the featured), the tall ones and the cards ──
  const sides = useMemo(() => (['bullish', 'bearish'] as const).map(side => {
    const real = flow.featured[side].slice(0, layout.perHalf);
    // While the futures are read, demo cards on the side's real leaders hold the slots, with their own paths.
    const demo = real.length === 0 && flow.futures.pending > 0;
    const featured = demo ? demoFeatured(flow[side], side, layout.perHalf) : real;
    const lead = new Set(featured.map(stock => stock.symbol));
    const rest = flow[side].filter(stock => !lead.has(stock.symbol));
    const { rows } = smallBoxes(layout, side, 0);
    // As many tiles as the half holds; names past that take no tile, and so no line (see `lines`).
    const shown = Math.min(rest.length, rows * 3);
    const { boxes } = smallBoxes(layout, side, shown);
    return { side, demo, featured, shownList: rest.slice(0, shown), boxes, features: featureBoxes(layout, side) };
  }), [flow, layout]);
  // Who has a card on the board: only they get a path to a card.
  const carded = useMemo(() => new Set(sides.flatMap(({ shownList, featured }) => [...shownList, ...featured].map(stock => stock.symbol))), [sides]);

  // ── Lines, scale, gate ──
  const lines = useMemo(() => {
    const out: Array<FlowLine & { raw: number[]; provisional?: boolean }> = [];
    for (const stock of flow.stocks) {
      if (stock.changePct == null) continue;
      // Every drawn line ends somewhere: on its card, or (flat names and NIFTY without a card) in the bar
      // between the halves. A name with neither a card nor a flat reading is not drawn at all.
      if (!carded.has(stock.symbol) && stock.side !== 'rangebound' && stock.symbol !== 'NIFTY') continue;
      const line = lineOf(stock, t0, t1);
      // Drawn with bad prints removed and lightly smoothed; the crosshair and the figures keep the raw change.
      if (line) out.push({ ...line, v: drawnValues(line.v), raw: line.v });
      // No future read yet: a provisional path from the open to the spot's move, so every tile has its
      // path from the start. Drawn dashed, kept off the crosshair, replaced when the future lands.
      else if (stock.side) {
        const guess = provisionalLine(stock.symbol, stock.changePct, t0, t1);
        out.push({ ...guess, raw: guess.v, provisional: true });
      }
    }
    return out;
  }, [flow.stocks, carded, t0, t1]);
  const drawn = useMemo(() => new Set(lines.map(line => line.symbol)), [lines]);
  // Only a line read from its future can be named in bold or stand as the index: never a provisional one.
  const read = useMemo(() => new Set(lines.filter(line => !line.provisional).map(line => line.symbol)), [lines]);
  const index = read.has('NIFTY') ? bySymbol.get('NIFTY') ?? null : null;
  const named = useMemo(() => namedLines(flow, settings.named ?? 5, read, index?.symbol ?? null), [flow, settings.named, read, index]);
  const keep = useMemo(() => new Set([...named.up, ...named.down].map(stock => stock.symbol)), [named]);
  // The reach is read from the drawn (filtered) lines, so one bad print cannot squash the fan.
  const reach = useMemo(() => chartReach(lines, keep, flow.floorPct) / 1.08 * 1.04, [lines, keep, flow.floorPct]);
  const yOf = useMemo(() => compressedScale(reach, zeroY, half), [reach, zeroY, half]);
  const xOf = useMemo(() => (ms: number) => xT0 + ((Math.max(t0, Math.min(t1, ms)) - t0) / Math.max(1, t1 - t0)) * (xT1 - xT0), [xT0, xT1, t0, t1]);



  // The tunnels carry only the names with a tile or a card: every path that goes through ends on one.
  // Flat names, and NIFTY when it has no card, run into the bar on the zero line.
  const gate = useMemo(() => {
    const has = (stock: FlowStock) => drawn.has(stock.symbol) && carded.has(stock.symbol);
    const toBar = flow.stocks.filter(stock => drawn.has(stock.symbol) && !carded.has(stock.symbol)).map(stock => stock.symbol);
    return gateRows(flow.bullish.filter(has).map(s => s.symbol), toBar, flow.bearish.filter(has).map(s => s.symbol), plotTop, plotBottom);
  }, [flow, drawn, carded, plotTop, plotBottom]);


  // ── Paths: each line with its run into the gate; the curve on to its tile; the card joint ──
  const paths = useMemo(() => {
    const line = new Map<string, string>();
    const conn = new Map<string, string>();
    // Each line's run from its last minute through the tunnel: the stream's first leg.
    const runIn = new Map<string, string>();
    for (const item of lines) {
      const row = gate.rows.get(item.symbol);
      let d = pathOf(item, xOf, yOf);
      if (row != null) {
        const xEnd = xOf(item.t[item.t.length - 1]);
        const yEnd = yOf(item.v[item.v.length - 1]);
        const run = `${sCurveOn(xEnd, yEnd, gateL, row, 0.5)}L${gateR.toFixed(1)},${row.toFixed(1)}`;
        d += run;
        runIn.set(item.symbol, `M${xEnd.toFixed(1)},${yEnd.toFixed(1)}${run}`);
      }
      line.set(item.symbol, d);
    }
    for (const { shownList, boxes, featured, features } of sides) {
      shownList.forEach((stock, i) => {
        const row = gate.rows.get(stock.symbol);
        const b = boxes[i];
        if (row == null || !b) return;
        conn.set(stock.symbol, sCurve(gateR, row, b.x, b.y + b.h / 2, 0.5));
      });
      featured.forEach((stock, i) => {
        const row = gate.rows.get(stock.symbol);
        const f = features[i];
        if (!f) return;
        const yc = f.tall.y + Math.min(26, f.tall.h / 2);
        const joint = `M${(f.tall.x + f.tall.w).toFixed(1)},${yc.toFixed(1)}H${f.card.x.toFixed(1)}`;
        conn.set(stock.symbol, `${row == null ? '' : sCurve(gateR, row, f.tall.x, yc, 0.45)}${joint}`);
      });
    }
    return { line, conn, runIn };
  }, [lines, gate, xOf, yOf, xT1, gateL, gateR, sides]);

  const fan = useMemo(() => {
    const out = { up: '', down: '', flat: '', pendingUp: '', pendingDown: '' };
    for (const item of lines) {
      if (keep.has(item.symbol) || item.symbol === index?.symbol) continue;
      const t = tone(bySymbol.get(item.symbol));
      const d = paths.line.get(item.symbol) ?? '';
      if (item.provisional && t !== 'flat') out[t === 'up' ? 'pendingUp' : 'pendingDown'] += d;
      else out[t] += d;
    }
    return out;
  }, [lines, keep, index, bySymbol, paths]);
  // The streams: light that runs from each line's end through its tunnel and on to its tile.
  const streams = useMemo(() => {
    const out = { up: '', down: '' };
    for (const item of lines) {
      const t = tone(bySymbol.get(item.symbol));
      if (t === 'flat') continue;
      out[t] += (paths.runIn.get(item.symbol) ?? '') + (paths.conn.get(item.symbol) ?? '');
    }
    return out;
  }, [lines, paths, bySymbol]);
  const connectors = useMemo(() => {
    const out = { up: '', down: '' };
    for (const [symbol, d] of paths.conn) out[tone(bySymbol.get(symbol)) === 'down' ? 'down' : 'up'] += d;
    return out;
  }, [paths, bySymbol]);

  // ── Per-minute table for the crosshair's nearest line ──
  const table = useMemo(() => {
    const minutes = Math.max(1, Math.round((t1 - t0) / MINUTE));
    return lines.filter(item => !item.provisional).map(item => {
      const values = new Float32Array(minutes + 1).fill(Number.NaN);
      const raw = new Float32Array(minutes + 1).fill(Number.NaN);
      let j = 0;
      const first = Math.round((item.t[0] - t0) / MINUTE);
      const last = Math.round((item.t[item.t.length - 1] - t0) / MINUTE);
      for (let m = Math.max(0, first); m <= Math.min(minutes, last); m++) {
        while (j + 1 < item.t.length && item.t[j + 1] <= t0 + m * MINUTE) j++;
        values[m] = item.v[j];
        raw[m] = item.raw[j];
      }
      return { symbol: item.symbol, values, raw };
    });
  }, [lines, t0, t1]);

  // ── Lit path, drawn by hand on focus ──
  const litRef = useRef<SVGGElement>(null);
  useEffect(() => focus.subscribe((state: FocusState) => {
    const g = litRef.current;
    if (!g) return;
    let d = '';
    let t = 'flat';
    if (state.symbol) {
      d = (paths.line.get(state.symbol) ?? '') + (paths.conn.get(state.symbol) ?? '');
      t = tone(bySymbol.get(state.symbol));
    } else if (state.sector) {
      for (const stock of flow.stocks) if (stock.sector === state.sector) d += paths.line.get(stock.symbol) ?? '';
    }
    for (const path of Array.from(g.children)) path.setAttribute('d', d);
    g.setAttribute('class', `mf-dg__lit is-${t}${state.sector ? ' is-sector' : ''}`);
  }), [focus, paths, bySymbol, flow.stocks]);

  // ── Crosshair ──
  const crossRef = useRef<SVGGElement>(null);
  const snapRef = useRef<string | null>(null);
  const move = (event: React.PointerEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    const cross = crossRef.current;
    if (!svg || !cross) return;
    const rect = svg.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const minutes = Math.round((t1 - t0) / MINUTE);
    const m = Math.max(0, Math.min(minutes, Math.round(((px - xT0) / Math.max(1, xT1 - xT0)) * minutes)));
    const at = t0 + m * MINUTE;
    const x = xOf(at);
    let best: string | null = null;
    let bestDy = SNAP_PX + 1;
    let bestV = 0;
    let bestRaw = 0;
    for (const row of table) {
      const v = row.values[m];
      if (Number.isNaN(v)) continue;
      const dy = Math.abs(yOf(v) - py);
      if (dy < bestDy) { bestDy = dy; best = row.symbol; bestV = v; bestRaw = row.raw[m]; }
    }
    cross.style.display = '';
    const [vline, tag, tagText, val, valText] = Array.from(cross.children) as SVGElement[];
    vline.setAttribute('x1', String(x)); vline.setAttribute('x2', String(x));
    tag.setAttribute('x', String(x - 20)); tagText.setAttribute('x', String(x)); tagText.textContent = clock(at);
    if (best) {
      const y = yOf(bestV);
      const text = endLabel(best, bestRaw);
      const w = text.length * 6.9 + 12;
      const left = x + 10 + w > xT1 ? x - 10 - w : x + 10;
      val.setAttribute('x', String(left)); val.setAttribute('y', String(y - 10)); val.setAttribute('width', String(w));
      valText.setAttribute('x', String(left + 6)); valText.setAttribute('y', String(y + 4)); valText.textContent = text;
      val.style.display = ''; valText.style.display = '';
    } else { val.style.display = 'none'; valText.style.display = 'none'; }
    if (best !== snapRef.current) { snapRef.current = best; focus.hoverSymbol(best, 'chart'); }
  };
  const leave = () => {
    if (crossRef.current) crossRef.current.style.display = 'none';
    snapRef.current = null;
    focus.hoverSymbol(null, 'chart');
  };

  // ── Axes ──
  const yTicks = compressedTicks(reach, half);
  const xTicks = useMemo(() => timeTicks(t0, t1, xT1 - xT0, flow.window), [t0, t1, xT1, xT0, flow.window]);
  // The current minute, while it still sits inside the session the axis spans.
  const nowAt = Math.floor(useClock() / MINUTE) * MINUTE;
  const nowX = nowAt > t0 && nowAt < t1 ? xOf(nowAt) : null;
  const tickClear = (t: number) => nowX == null || Math.abs(xOf(t) - nowX) >= 36;
  const zeroDividerX = layout.smallX0 - 10;
  const sCurvePath = `M${xT0},${zeroY}H${gateR + 8}${sCurveOn(gateR + 8, zeroY, zeroDividerX, layout.midY, 0.5)}H${W - PAD}`;
  const funnel = gate.downStart > gate.upEnd
    ? `M${xT1 - 40},${yOf(flow.floorPct)}C${xT1},${yOf(flow.floorPct)} ${gateL - 10},${gate.upEnd} ${gateL},${gate.upEnd}L${gateR},${gate.upEnd + 8}L${gateR},${gate.downStart - 8}L${gateL},${gate.downStart}C${gateL - 10},${gate.downStart} ${xT1},${yOf(-flow.floorPct)} ${xT1 - 40},${yOf(-flow.floorPct)}Z`
    : '';


  return (
    <>
      <svg className="mf-dg__under" width={W} height={H} role="img"
        aria-label={`${lines.length} futures from nought at ${clock(t0)}: ${flow.bullish.length} up, ${flow.rangebound.length} flat, ${flow.bearish.length} down. Each line runs on to its tile.`}>
        <rect className="mf-dg__spine is-up" x={PAD} y={plotTop} width="4" height={Math.max(0, zeroY - plotTop)} rx="2" />
        <rect className="mf-dg__spine is-down" x={PAD} y={zeroY} width="4" height={Math.max(0, plotBottom - zeroY)} rx="2" />
        <rect className="mf-dg__floor" x={xT0} width={xT1 - xT0} y={yOf(flow.floorPct)} height={yOf(-flow.floorPct) - yOf(flow.floorPct)} />
        {yTicks.flatMap(v => [v, -v]).map(v => (
          <g key={v}>
            <line className="mf-dg__grid" x1={xT0} x2={xT1} y1={yOf(v)} y2={yOf(v)} />
            <text className="mf-dg__tick" x={xT0 - 8} y={yOf(v) + 4} textAnchor="end">{v > 0 ? '+' : '−'}{Math.abs(v)}%</text>
          </g>
        ))}
        <text className="mf-dg__tick is-zero" x={xT0 - 8} y={zeroY + 4} textAnchor="end">0%</text>
        {xTicks.map((t, i) => (
          <g key={t}>
            <line className="mf-dg__grid is-time" x1={xOf(t)} x2={xOf(t)} y1={plotTop} y2={plotBottom} />
            {tickClear(t) && <text className="mf-dg__tick" x={xOf(t)} y={plotBottom + 17} textAnchor={i === 0 && flow.window === 'day' ? 'start' : i === xTicks.length - 1 && flow.window === 'day' ? 'end' : 'middle'}>{clock(t)}</text>}
          </g>
        ))}
      </svg>
      {/* The fan, the curves and the medians on a layer of their own: dimming them on hover is a composited fade, not a repaint. */}
      <svg className="mf-dg__under mf-dg__fan" width={W} height={H} aria-hidden="true">
        <g>
          <SectorLines sectors={flow.sectors} yOf={yOf} x0={xT0 + pillW + 8} x1={xT1} />
          {funnel && (
            <>
              {/* The funnel fades in from the chart, so the flat names pour into it rather than hit a grey slab. */}
              <defs>
                <linearGradient id={`${pathId}-funnel`} x1={xT1 - 40} x2={gateR} y1="0" y2="0" gradientUnits="userSpaceOnUse">
                  <stop offset="0" className="mf-dg__funnel-stop is-from" />
                  <stop offset="1" className="mf-dg__funnel-stop is-to" />
                </linearGradient>
              </defs>
              <path className="mf-dg__funnel" d={funnel} fill={`url(#${pathId}-funnel)`} style={{ fill: `url(#${pathId}-funnel)` }} />
            </>
          )}
          <path className="mf-dg__faint is-flat" d={fan.flat} />
          <path className="mf-dg__faint is-down" d={fan.down} />
          <path className="mf-dg__faint is-up" d={fan.up} />
          <path className="mf-dg__pending is-up" d={fan.pendingUp} />
          <path className="mf-dg__pending is-down" d={fan.pendingDown} />
          {[...named.down, ...named.up].map((stock, i) => (
            <path key={stock.symbol} id={`${pathId}-${i}`} className={`mf-dg__bold is-${tone(stock)}`} d={paths.line.get(stock.symbol)}
              pathLength={1} style={{ '--i': i } as React.CSSProperties} />
          ))}
          {index && <path className="mf-dg__bold is-index" data-sym={index.symbol} d={paths.line.get(index.symbol)} />}
          <path className="mf-dg__conn is-up" d={connectors.up} />
          <path className="mf-dg__conn is-down" d={connectors.down} />
        </g>
      </svg>
      {/* What moves lives in its own layer, so a frame repaints the light, not the thousands of lines under it. */}
      {!calm && (
        <svg className="mf-dg__under mf-dg__motion" width={W} height={H} aria-hidden="true">
          <path className="mf-dg__stream is-up" d={streams.up} />
          <path className="mf-dg__stream is-down" d={streams.down} />
          {/* A comet runs each lead path, from the open to its tile, at its own pace. */}
          {[...named.down, ...named.up].map((stock, i) => (
            <circle key={stock.symbol} className={`mf-dg__comet is-${tone(stock)}`} r="2.4">
              <animateMotion dur={`${7 + (i % 4) * 1.3}s`} begin={`${-((i * 1.7) % 7).toFixed(1)}s`} repeatCount="indefinite" calcMode="linear">
                <mpath href={`#${pathId}-${i}`} />
              </animateMotion>
            </circle>
          ))}
        </svg>
      )}
      <svg className="mf-dg__under mf-dg__frame" width={W} height={H} aria-hidden="true">
        <GateFrame x0={gateL} x1={gateR} top={plotTop} upEnd={gate.upEnd} downStart={gate.downStart} bottom={plotBottom} />
        <g className="mf-dg__dots">
          {sides.flatMap(({ shownList, featured }) => [...shownList, ...featured]).map(stock => {
            const row = gate.rows.get(stock.symbol);
            return row == null ? null : <circle key={stock.symbol} className={`is-${tone(stock)}`} data-sym={stock.symbol} cx={gateR - 6} cy={row} r="1.8" />;
          })}
        </g>
        {/* The bar between the halves: the zero line, carried on between the bullish and bearish tiles. */}
        <path className="mf-dg__bar" d={sCurvePath} />
        <path className="mf-dg__zero" d={sCurvePath} />
        {/* The "now" edge breathes; each lead path's last reading pulses on it. */}
        <line className="mf-dg__now" x1={xT1} x2={xT1} y1={plotTop} y2={plotBottom} />
        {/* A light rule just after the current minute, so the rest of the session reads as still ahead. */}
        {nowX != null && (
          <g className="mf-dg__clock">
            <line x1={nowX} x2={nowX} y1={plotTop} y2={plotBottom + 14} />
            <text x={nowX - 6} y={plotBottom + 17} textAnchor="end">{clock(nowAt)}</text>
          </g>
        )}
        {[...named.down, ...named.up].map(stock => {
          const item = lines.find(l => l.symbol === stock.symbol);
          if (!item) return null;
          return <circle key={stock.symbol} className={`mf-dg__live is-${tone(stock)}`} cx={xOf(item.t[item.t.length - 1])} cy={yOf(item.v[item.v.length - 1])} r="2.6" />;
        })}
        {/* The origin: every path starts here, so it carries a halo and a slow ring. */}
        <g className="mf-dg__origin" transform={`translate(${xT0},${zeroY})`}>
          <circle className="is-halo" r="11" />
          <circle className="is-ring" r="15" />
        </g>
        <circle className="mf-dg__node" cx={xT0} cy={zeroY} r="3.5" />
        <circle className="mf-dg__node" cx={gateR + 8} cy={zeroY} r="3.5" />
        <circle className="mf-dg__node" cx={zeroDividerX} cy={layout.midY} r="4" />
      </svg>

      <FlowStrip flow={flow} status={status} width={gateR - PAD} />
      <SectorPills sectors={flow.sectors} yOf={yOf} top={plotTop} bottom={plotBottom} zeroY={zeroY} x={xT0 + 6} pillW={pillW} />

      {sides.map(({ side, demo, shownList, boxes, featured, features }) => (
        <section key={side} className={`mf-dg-half is-${side}`} aria-label={`${side === 'bullish' ? 'Bullish' : 'Bearish'} ${flow[side].length}`}>
          {flow[side].length === 0 && (
            <p className="mf-half__empty" style={{ position: 'absolute', left: layout.smallX0, top: layout.halves[side].top + 8 }}>None {side === 'bullish' ? 'up' : 'down'} more than {flow.floorPct}%</p>
          )}
          <DiagramTiles side={side} stocks={shownList} boxes={boxes} total={flow[side].length} />
          {featured.map((stock, i) => features[i] && (
            <div key={stock.symbol}>
              <TallTile stock={stock} side={side} box={features[i].tall} demo={demo} />
              <DiagramCard stock={stock} side={side} box={features[i].card} demo={demo} />
            </div>
          ))}
        </section>
      ))}


      <div className="mf-dg__popzone" style={{ left: layout.smallX0 - 4, width: layout.tallX + layout.tallW - layout.smallX0 + 8, top: 0, height: H }}>
        <FlowPopup flow={flow} mode="half" />
      </div>

      <svg className="mf-dg__over" width={W} height={H}>
        <g className="mf-dg__lit" ref={litRef}><path className="is-halo" /><path className="is-line" /><path className="is-dash" /></g>
        <g className="mf-chart__cross" ref={crossRef} style={{ display: 'none' }} aria-hidden="true">
          <line className="mf-chart__vline" y1={plotTop} y2={plotBottom} />
          <rect className="mf-chart__ttag" y={plotBottom + 4} width="40" height="18" rx="4" />
          <text className="mf-chart__ttext" y={plotBottom + 17} textAnchor="middle" />
          <rect className="mf-chart__vtag" height="20" rx="4" />
          <text className="mf-chart__vtext" />
        </g>
        <rect className="mf-chart__hit" x={xT0 + pillW + 8} y={plotTop} width={Math.max(0, xT1 - xT0 - pillW - 8)} height={plotBottom - plotTop}
          onPointerMove={move} onPointerLeave={leave} onClick={() => (snapRef.current ? focus.togglePin(snapRef.current, 'chart') : focus.clear())} />
      </svg>
      {index && (() => {
        const item = lines.find(line => line.symbol === index.symbol);
        if (!item) return null;
        const y = yOf(item.v[item.v.length - 1]);
        return (
          <button type="button" className="mf-dg__indexbtn" data-sym={index.symbol}
            style={{ left: Math.max(PAD, xT1 - 156), top: Math.max(plotTop, y - 24) }}
            onClick={event => { event.stopPropagation(); focus.togglePin(index.symbol, 'tile'); }}>
            NIFTY {pctText(index.changePct)}
          </button>
        );
      })()}
    </>
  );
}

function GateFrame({ x0, x1, top, upEnd, downStart, bottom }: { x0: number; x1: number; top: number; upEnd: number; downStart: number; bottom: number }) {
  const bracket = (y0: number, y1: number, cls: string) => {
    if (y1 - y0 < 4) return null;
    const k = 7;
    return (
      <g className={`mf-dg__gate ${cls}`}>
        <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} />
        {/* A light that sweeps through the tunnel, the way the market moves through it. */}
        <rect className="mf-dg__sweep" x={x0} y={y0} width={Math.min(18, (x1 - x0) / 3)} height={y1 - y0} style={{ '--gw': `${x1 - x0}px` } as React.CSSProperties} />
        <path d={`M${x0 + k},${y0}H${x0}V${y1}H${x0 + k}M${x1 - k},${y0}H${x1}V${y1}H${x1 - k}`} />
      </g>
    );
  };
  return <>{bracket(top, upEnd, 'is-up')}{bracket(downStart, bottom, 'is-down')}</>;
}

const SectorLines = memo(function SectorLines({ sectors, yOf, x0, x1 }: { sectors: readonly FlowSector[]; yOf: (pct: number) => number; x0: number; x1: number }) {
  return <g className="mf-dg__medians">{sectors.filter(s => s.changePct != null).map(s => <line key={s.id} data-sector={s.id} x1={x0} x2={x1} y1={yOf(s.changePct ?? 0)} y2={yOf(s.changePct ?? 0)} />)}</g>;
});

/** The sector pills over the chart's left side: up sectors from the top, down sectors from the bottom, leader to laggard. */
const SectorPills = memo(function SectorPills({ sectors, top, bottom, zeroY, x, pillW }: { sectors: readonly FlowSector[]; yOf: (pct: number) => number; top: number; bottom: number; zeroY: number; x: number; pillW: number }) {
  const focus = useFlowFocus();
  const measured = sectors.filter(s => s.changePct != null);
  const up = measured.filter(s => (s.changePct ?? 0) >= 0);
  const down = measured.filter(s => (s.changePct ?? 0) < 0);
  // One pitch for all: the up pills stack from the top, the down pills from the bottom, and they meet wherever the count puts them.
  const pitch = Math.min(27, (bottom - top) / Math.max(1, measured.length));
  const pitchUp = pitch;
  const pitchDown = pitch;
  void zeroY;
  const pill = (sector: FlowSector, y: number, h: number, slot: number) => {
    const total = Math.max(1, sector.count);
    const pct = sector.changePct ?? 0;
    return (
      <li key={slot} style={{ top: y, height: h, '--i': slot } as React.CSSProperties}>
        <button type="button" className={`mf-pill ${pct > 0.0049 ? 'is-up' : pct < -0.0049 ? 'is-down' : 'is-flat'}`} data-sector={sector.id} style={heatStyle(sector.changePct, 3)}
          aria-label={`${sector.label}: median ${pctText(sector.changePct)}; ${sector.bullish} up, ${sector.bearish} down, ${sector.rangebound} flat of ${sector.count}`}
          onPointerEnter={event => { if (event.pointerType !== 'touch') focus.hoverSector(sector.id); }}
          onPointerLeave={event => { if (event.pointerType !== 'touch') focus.hoverSector(null); }}
          onFocus={() => focus.hoverSector(sector.id)} onBlur={() => focus.hoverSector(null)}
          onClick={() => focus.togglePinSector(sector.id)}>
          <span className="mf-pill__row"><span className="mf-pill__name" data-ui-tip={sector.label} data-ui-tip-when={shortSector(sector.label) === sector.label ? 'cut' : undefined}>{shortSector(sector.label)}</span><span className="mf-pill__pct">{pctText(sector.changePct)}</span></span>
          {h >= 22 && (
            <span className="mf-pill__bar" aria-hidden="true">
              {Array.from({ length: Math.min(total, 14) }, (_, i) => {
                const share = (i + 0.5) / Math.min(total, 14);
                const cls = share <= sector.bullish / total ? 'is-up' : share >= 1 - sector.bearish / total ? 'is-down' : 'is-flat';
                return <i key={i} className={cls} />;
              })}
            </span>
          )}
        </button>
      </li>
    );
  };
  return (
    <nav className="mf-pills" aria-label="Sectors, leader to laggard" style={{ left: x, ['--pill-w' as string]: `${pillW}px` }}>
      <ul>
        {up.map((s, i) => pill(s, top + i * pitchUp, pitchUp - 3, i))}
        {down.map((s, i) => pill(s, bottom - (down.length - i) * pitchDown, pitchDown - 3, up.length + i))}
      </ul>
    </nav>
  );
});

/** The distribution strip above the chart: every move as a dot, stacked where they crowd, with the status and the leading and lagging sectors. */
const FlowStrip = memo(function FlowStrip({ flow, status, width }: { flow: MarketFlow; status: ReactNode; width: number }) {
  const measured = flow.stocks.filter(stock => stock.changePct != null);
  const abs = measured.map(stock => Math.abs(stock.changePct ?? 0)).sort((a, b) => a - b);
  const reach = Math.max(1, abs[Math.floor(abs.length * 0.98)] ?? 1);
  const w = width - 196;
  const x0 = 6;
  const mid = x0 + w / 2;
  const xOf = (v: number) => mid + (Math.max(-reach, Math.min(reach, v)) / reach) * (w / 2 - 4);
  const bins = new Map<number, number>();
  const dots = measured.map(stock => {
    const b = Math.round(xOf(stock.changePct ?? 0) / 4.2);
    const level = bins.get(b) ?? 0;
    bins.set(b, level + 1);
    return { stock, x: b * 4.2, level };
  });
  const tallest = Math.max(1, ...bins.values());
  const pitch = Math.min(4.2, 44 / tallest);
  const sectors = flow.sectors.filter(s => s.changePct != null);
  const lead = sectors[0];
  const lag = sectors[sectors.length - 1];
  const index = flow.stocks.find(stock => stock.symbol === 'NIFTY' && stock.changePct != null);
  return (
    <figure className="mf-strip" style={{ left: PAD, top: PAD, width, height: STRIP_H }} aria-label={`Spread of moves: ${flow.bullish.length} up, ${flow.rangebound.length} flat, ${flow.bearish.length} down`}>
      <div className="mf-strip__head">{status}</div>
      <svg width={w + 12} height={62} aria-hidden="true">
        <line className="mf-strip__base" x1={x0} x2={x0 + w} y1={50} y2={50} />
        <line className="mf-strip__zero" x1={mid} x2={mid} y1={2} y2={54} />
        {dots.map(({ stock, x, level }) => <circle key={stock.symbol} className={`is-${tone(stock)}`} cx={x} cy={47 - level * pitch} r={1.9} />)}
        {index && <path className="mf-strip__index" transform={`translate(${xOf(index.changePct ?? 0)},50)`} d="M0,-4.5L4.5,0L0,4.5L-4.5,0Z" />}
        <text className="mf-strip__tick" x={x0} y={61} textAnchor="start">{pctText(-reach, 1)}</text>
        <text className="mf-strip__tick" x={mid} y={61} textAnchor="middle">0</text>
        <text className="mf-strip__tick" x={x0 + w} y={61} textAnchor="end">{pctText(reach, 1)}</text>
      </svg>
      <div className="mf-strip__side">
        <span><b className="mf-tone is-bullish">▲ Bullish <span key={flow.bullish.length} className="mf-pop">{flow.bullish.length}</span></b>  <b className="mf-tone is-bearish">▼ Bearish <span key={flow.bearish.length} className="mf-pop">{flow.bearish.length}</span></b></span>
        {lead && <span className="mf-strip__sec">Leading <b>{lead.label}</b> {pctText(lead.changePct)}</span>}
        {lag && lag !== lead && <span className="mf-strip__sec">Lagging <b>{lag.label}</b> {pctText(lag.changePct)}</span>}
      </div>
    </figure>
  );
});

/** The small tiles of a half, placed by the layout; keyed by slot so they never shift while the futures arrive. */
const DiagramTiles = memo(function DiagramTiles({ side, stocks, boxes, total }: { side: 'bullish' | 'bearish'; stocks: readonly FlowStock[]; boxes: Box[]; total: number }) {
  const focus = useFlowFocus();
  const symbolAt = (target: EventTarget | null) => (target as HTMLElement | null)?.closest<HTMLElement>('[data-tile]')?.dataset.sym ?? null;
  return (
    <div className="mf-dg-tiles" role="group" aria-label={`${side === 'bullish' ? 'Bullish' : 'Bearish'}, ranked by move`}
      onPointerOver={event => { if (event.pointerType === 'touch') return; const s = symbolAt(event.target); if (s) focus.hoverSymbol(s, 'tile'); }}
      onPointerOut={event => { if (event.pointerType === 'touch') return; if (!symbolAt(event.relatedTarget)) focus.hoverSymbol(null, 'tile'); }}
      onFocus={event => { const s = symbolAt(event.target); if (s) focus.hoverSymbol(s, 'key'); }}
      onBlur={event => { if (!symbolAt(event.relatedTarget)) focus.hoverSymbol(null, 'key'); }}
      onClick={event => { const s = symbolAt(event.target); if (s) focus.togglePin(s, 'tile'); }}
      onKeyDown={event => {
        const tiles = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-tile]'));
        const at = tiles.indexOf(document.activeElement as HTMLButtonElement);
        if (at < 0) return;
        const step = side === 'bullish' ? 3 : -3;
        const next = { ArrowRight: at + 1, ArrowLeft: at - 1, ArrowDown: at + step, ArrowUp: at - step, Home: 0, End: tiles.length - 1 }[event.key];
        if (next == null) return;
        event.preventDefault();
        const target = tiles[Math.max(0, Math.min(tiles.length - 1, next))];
        for (const tile of tiles) tile.tabIndex = tile === target ? 0 : -1;
        target.focus();
      }}>
      {stocks.map((stock, slot) => {
        const b = boxes[slot];
        if (!b) return null;
        const spot = stock.source !== 'futures';
        // A short tile gives its symbol the whole first line (LAURUSLABS was
        // cut to "LAURUS…" beside a full-height profile) and carries the
        // profile on the second line, after the move.
        const inline = b.h < 58;
        return (
          <button key={slot} type="button" className={`mf-tile is-dg ${toneOf(stock)}${spot ? ' is-spot' : ''}${inline ? ' is-inline' : ''}`} data-tile="" data-sym={stock.symbol} data-sector={stock.sector}
            tabIndex={slot === 0 ? 0 : -1} style={{ left: b.x, top: b.y, width: b.w, height: b.h, '--i': slot, ...heatStyle(stock.changePct) } as React.CSSProperties}
            aria-label={`${stock.symbol}, ${side === 'bullish' ? 'up' : 'down'} ${pctText(Math.abs(stock.changePct ?? 0)).replace(/^\+/, '')}${spot ? ' on the spot' : ''}, ${buildUpText(stock)}, rank ${stock.rank} of ${total}`}>
            <TickFlash value={stock.changePct} />
            <span className="mf-tile__main">
              <span className="mf-tile__id"><SymbolMark symbol={stock.symbol} kind={stock.kind} size={14} showTitle={false} className="mf-logo" /><span className="mf-tile__sym" data-ui-tip={stock.symbol} data-ui-tip-when="cut">{stock.symbol}</span></span>
              <span className="mf-tile__row"><ChangeText value={stock.changePct} className="mf-tile__pct" /><BuildMark stock={stock} />{inline && <MiniProfile stock={stock} height={14} />}</span>
              {b.h >= 58 && <span className={`mf-tile__bu mf-tone is-${side}`}>{spot ? 'Spot only' : buildUpText(stock)}</span>}
              {b.h >= 72 && !spot && <Spark stock={stock} width={b.w - 46} height={12} />}
            </span>
            {!inline && <MiniProfile stock={stock} height={b.h - 10} />}
          </button>
        );
      })}
    </div>
  );
});

/** A few bars of option open interest by strike around spot (puts and calls), spot marked: the small tile's profile. */
function MiniProfile({ stock, height }: { stock: FlowStock; height: number }) {
  const all = stock.profile;
  if (all.length < 2) return <span className="mf-miniprof is-empty" />;
  // The five strikes nearest spot.
  const nearest = [...all].sort((a, b) => Math.abs(a.strike - stock.spot) - Math.abs(b.strike - stock.spot)).slice(0, 5).sort((a, b) => a.strike - b.strike);
  const largest = Math.max(1, ...nearest.map(row => row.put + row.call));
  const w = 22;
  const rh = Math.min(7, height / nearest.length);
  const top = (height - rh * nearest.length) / 2;
  return (
    <svg className="mf-miniprof" width={w} height={height} aria-hidden="true">
      {nearest.map((row, i) => {
        const y = top + (nearest.length - 1 - i) * rh;
        const put = (row.put / largest) * w;
        const call = (row.call / largest) * w;
        return (
          <g key={row.strike}>
            <rect className="is-put" x={w - put - call} y={y + 0.5} width={put} height={rh - 1.5} />
            <rect className="is-call" x={w - call} y={y + 0.5} width={call} height={rh - 1.5} />
          </g>
        );
      })}
    </svg>
  );
}


/** A tall tile: the strongest reading with its option open interest by strike around spot (puts and calls), spot tagged. */
const TallTile = memo(function TallTile({ stock, side, box, demo = false }: { stock: FlowStock; side: 'bullish' | 'bearish'; box: Box; demo?: boolean }) {
  const focus = useFlowFocus();
  const rows = stock.profile;
  const largest = Math.max(1, ...rows.map(row => Math.max(row.put, row.call)));
  const head = 64;
  const ph = Math.max(10, box.h - head - 8);
  const rh = rows.length ? ph / rows.length : 0;
  const pw = box.w - 16;
  let spotY: number | null = null;
  if (rows.length >= 2) {
    const lo = rows[0].strike;
    const hi = rows[rows.length - 1].strike;
    spotY = ph - ((stock.spot - lo) / Math.max(1e-9, hi - lo)) * (ph - rh) - rh / 2;
  }
  return (
    <button type="button" className={`mf-tall ${toneOf(stock)}${demo ? ' is-demo' : ''}`} data-sym={stock.symbol} data-sector={stock.sector} style={{ left: box.x, top: box.y, width: box.w, height: box.h, ...heatStyle(stock.changePct) }}
      aria-label={`${stock.symbol}: ${pctText(stock.changePct)}, ${buildUpText(stock)}; option open interest by strike around spot`}
      onPointerEnter={event => { if (event.pointerType !== 'touch') focus.hoverSymbol(stock.symbol, 'card'); }}
      onPointerLeave={event => { if (event.pointerType !== 'touch') focus.hoverSymbol(null, 'card'); }}
      onClick={() => focus.togglePin(stock.symbol, 'card')}>
      <TickFlash value={stock.changePct} />
      <span className="mf-tall__head">
        <span className="mf-tall__id"><SymbolMark symbol={stock.symbol} kind={stock.kind} size={18} showTitle={false} className="mf-logo" /><b className="mf-tall__sym">{stock.symbol}</b></span>
        <span className="mf-tall__row"><ChangeText value={stock.changePct} /><DotMeter checks={stock.checks} /></span>
        <span className={`mf-tall__bu mf-tone is-${side}`}>{buildUpText(stock)}</span>
      </span>
      {rows.length >= 2 && (
        <svg className="mf-tall__profile" width={pw} height={ph} aria-hidden="true">
          {rows.map((row, i) => {
            const y = ph - (i + 1) * rh;
            const put = (row.put / largest) * (pw / 2 - 2);
            const call = (row.call / largest) * (pw / 2 - 2);
            return (
              <g key={row.strike}>
                <rect className="is-put" x={pw / 2 - put} y={y + 0.5} width={put} height={Math.max(1, rh - 1.5)} />
                <rect className="is-call" x={pw / 2} y={y + 0.5} width={call} height={Math.max(1, rh - 1.5)} />
              </g>
            );
          })}
          <line className="mf-tall__axis" x1={pw / 2} x2={pw / 2} y1={0} y2={ph} />
          {spotY != null && <>
            <line className="mf-tall__spot" x1={0} x2={pw} y1={spotY} y2={spotY} />
            <rect className="mf-tall__tag" x={pw - 50} y={spotY - 8} width={50} height={16} rx="3" />
            <text className="mf-tall__tagtext" x={pw - 25} y={spotY + 4} textAnchor="middle">{fmtPrice(stock.spot)}</text>
          </>}
        </svg>
      )}
    </button>
  );
});

/** A large card: side badge, conviction ring, the move, price, support / zone / resistance, the range bar, and 5-minute candles with the levels. */
const DiagramCard = memo(function DiagramCard({ stock, side, box, demo = false }: { stock: FlowStock; side: 'bullish' | 'bearish'; box: Box; demo?: boolean }) {
  const focus = useFlowFocus();
  const held = stock.checks.filter(check => check.pass).length;
  const counted = stock.checks.filter(check => check.pass != null).length;
  const chartW = Math.round(box.w * (box.w < 300 ? 0.46 : 0.54));
  const chartH = Math.max(40, box.h - 20 - 34);
  const compact = box.h < 172;
  return (
    <article className={`mf-dgcard ${toneOf(stock)}${demo ? ' is-demo' : ''}`} data-sym={stock.symbol} data-sector={stock.sector} style={{ left: box.x, top: box.y, width: box.w, height: box.h, ...heatStyle(stock.changePct) }}>
      <TickFlash value={stock.changePct} />
      <button type="button" className="mf-dgcard__main" aria-label={`${stock.symbol}: ${pctText(stock.changePct)}, ${buildUpText(stock)}. Open the detail.`}
        onPointerEnter={event => { if (event.pointerType !== 'touch') focus.hoverSymbol(stock.symbol, 'card'); }}
        onPointerLeave={event => { if (event.pointerType !== 'touch') focus.hoverSymbol(null, 'card'); }}
        onFocus={() => focus.hoverSymbol(stock.symbol, 'key')} onBlur={() => focus.hoverSymbol(null, 'key')}
        onClick={() => focus.togglePin(stock.symbol, 'card')}>
        <span className="mf-dgcard__left">
          <span className="mf-dgcard__id"><SymbolMark symbol={stock.symbol} kind={stock.kind} size={22} showTitle={false} className="mf-logo" /><b>{stock.symbol}</b>{demo && <span className="mf-demo" data-ui-tip="Demo: the line and futures figures are a sample until this stock's future is read">Demo</span>}<small>{stock.sectorLabel}</small></span>
          <span className="mf-dgcard__badges">
            <span className={`mf-badge is-${side}`}>{side === 'bullish' ? 'Bullish' : 'Bearish'}</span>
            <Ring held={held} counted={counted} />
          </span>
          <ChangeText value={stock.changePct} className="mf-dgcard__pct" />
          <span className="mf-dgcard__price">₹{fmtPrice(stock.fut?.price ?? stock.spot)} <span className={`mf-tone is-${side}`}>{signedText(stock.fut?.priceChange)}</span></span>
          {!compact && <RangeBar stock={stock} />}
        </span>
        <span className="mf-dgcard__chart"><CandleChart stock={stock} width={chartW} height={chartH} /></span>
        <span className="mf-dgcard__levels">
          <span><i>Support</i><b>{stock.support ? levelText(stock.support.strike) : '—'}</b></span>
          <span><i>Zone</i><b>{stock.zone ? `${fmtPrice(stock.zone.low)}–${fmtPrice(stock.zone.high)}` : '—'}</b></span>
          <span><i>Resistance</i><b>{stock.resistance ? levelText(stock.resistance.strike) : '—'}</b></span>
        </span>
      </button>
    </article>
  );
});

function Ring({ held, counted }: { held: number; counted: number }) {
  const r = 11;
  const c = 2 * Math.PI * r;
  const share = counted ? held / counted : 0;
  return (
    <span className="mf-ring" role="img" aria-label={counted ? `Conviction: ${held} of ${counted}` : 'Conviction: not measured yet'}>
      <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
        <circle className="mf-ring__track" cx="15" cy="15" r={r} />
        <circle className="mf-ring__arc" cx="15" cy="15" r={r} strokeDasharray={`${c * share} ${c}`} transform="rotate(-90 15 15)" />
        <text x="15" y="18.5" textAnchor="middle">{counted ? `${held}/${counted}` : '—'}</text>
      </svg>
    </span>
  );
}

/** Spot between support and resistance, the zone marked on the way. */
function RangeBar({ stock }: { stock: FlowStock }) {
  const { support, resistance, spot, zone } = stock;
  if (!support || !resistance || resistance.strike <= support.strike) return <span className="mf-range is-empty" />;
  const at = (price: number) => Math.max(0, Math.min(100, ((price - support.strike) / (resistance.strike - support.strike)) * 100));
  return (
    <span className="mf-range" role="img" aria-label={`Spot ${fmtPrice(spot)} between support ${levelText(support.strike)} and resistance ${levelText(resistance.strike)}`}>
      {zone && <i className="mf-range__zone" style={{ left: `${at(zone.low)}%`, width: `${Math.max(1.5, at(zone.high) - at(zone.low))}%` }} />}
      <i className="mf-range__spot" style={{ left: `${at(spot)}%` }} />
    </span>
  );
}

/** 5-minute candles from the minute closes, with the base (previous close or window start), the zone and S1/R1. */
export function CandleChart({ stock, width, height, levels = true }: { stock: FlowStock; width: number; height: number; levels?: boolean }) {
  const minute = windowCandles(stock);
  if (minute.length < 3) return <span className="mf-candles is-empty">{stock.futures === 'pending' ? 'Loading future…' : stock.futures === 'failed' ? 'Could not load future' : 'No line yet'}</span>;
  const span = minute.length > 120 ? 5 : minute.length > 30 ? 2 : 1;
  const candles = candlesFromCloses(minute, span);
  const right = levels ? 46 : 4;
  const pad = { top: 6, bottom: 6, left: 2 };
  let low = Math.min(...candles.map(c => c.low));
  let high = Math.max(...candles.map(c => c.high));
  const base = stock.fut?.priceFrom ?? null;
  if (base != null) { low = Math.min(low, base); high = Math.max(high, base); }
  const range = Math.max(high - low, (stock.fut?.price ?? stock.spot) * 0.002);
  const lv: Array<[string, number, string]> = [];
  if (levels) {
    if (stock.support && stock.support.strike >= low - range * 0.5) lv.push(['S1', stock.support.strike, 'is-put']);
    if (stock.resistance && stock.resistance.strike <= high + range * 0.5) lv.push(['R1', stock.resistance.strike, 'is-call']);
  }
  for (const [, price] of lv) { low = Math.min(low, price); high = Math.max(high, price); }
  const m = (high - low) * 0.06 || range * 0.06;
  low -= m; high += m;
  const w = width - right - pad.left;
  const cw = w / candles.length;
  const y = (p: number) => pad.top + (1 - (p - low) / (high - low)) * (height - pad.top - pad.bottom);
  const x = (i: number) => pad.left + i * cw + cw / 2;
  const t0 = candles[0].at;
  const t1 = candles[candles.length - 1].at + span * MINUTE;
  const xt = (t: number) => pad.left + ((t - t0) / Math.max(1, t1 - t0)) * w;
  return (
    <svg className="mf-candles" width={width} height={height} aria-hidden="true">
      {stock.zone && stock.zone.to > t0 && (
        <rect className="mf-candles__zone" x={xt(Math.max(t0, stock.zone.from))} width={Math.max(3, xt(Math.min(t1, stock.zone.to)) - xt(Math.max(t0, stock.zone.from)))} y={y(stock.zone.high)} height={Math.max(3, y(stock.zone.low) - y(stock.zone.high))} rx="1.5" />
      )}
      {base != null && <line className="mf-candles__base" x1={pad.left} x2={pad.left + w} y1={y(base)} y2={y(base)} />}
      {lv.map(([name, price, cls]) => (
        <g key={name} className={cls}>
          <line className="mf-candles__level" x1={pad.left} x2={pad.left + w + 4} y1={y(price)} y2={y(price)} />
          <text className="mf-candles__tag" x={pad.left + w + 7} y={y(price) + 3.5}>{name} {levelText(price)}</text>
        </g>
      ))}
      {candles.map((c, i) => {
        const upC = c.close >= c.open;
        return (
          <g key={c.at} className={upC ? 'is-up' : 'is-down'}>
            <line className="mf-candles__wick" x1={x(i)} x2={x(i)} y1={y(c.high)} y2={y(c.low)} />
            <rect className="mf-candles__body" x={x(i) - Math.max(0.6, cw * 0.32)} width={Math.max(1.2, cw * 0.64)} y={y(Math.max(c.open, c.close))} height={Math.max(1, Math.abs(y(c.open) - y(c.close)))} />
          </g>
        );
      })}
      <circle className="mf-candles__last" cx={x(candles.length - 1)} cy={y(candles[candles.length - 1].close)} r="2.5" />
    </svg>
  );
}
