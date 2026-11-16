import { useEffect, useMemo, useRef, useState } from 'react';
import { SymbolMark } from '@/order-flow/components/common/SymbolMark';
import { CaretLeftIcon, CaretRightIcon, CheckIcon, MinusIcon, XIcon } from '@/order-flow/assets/svg/icons';
import { expiryDisplay } from '@/order-flow/components/common/expiryDisplay';
import { fmtPrice } from '@/order-flow/utils/formatters';
import { candlesFromCloses } from './diagramModel';
import { MINUTE } from './flowChartModel';
import { useFlowFocus, type FocusState } from './flowFocus';
import { buildUpText, ChangeText, DotMeter, signedText, Spark, toneOf, windowCandles } from './FlowParts';
import { clockOf, compactUnits, levelText, type FlowLevel, type FlowStock, type MarketFlow } from './marketFlowModel';
import { useBox } from './useBox';

interface FlowPopupProps {
  flow: MarketFlow;
  /** On a desktop the detail opens over the other half of the column, on hover; elsewhere it is a sheet, on a tap. */
  mode: 'half' | 'sheet';
}

const SHOW_DELAY_MS = 70;
const HIDE_DELAY_MS = 90;

/**
 * The detail of one underlying: its future through the window with the
 * window's base, the zone and the option levels drawn in, and the reading in
 * figures. It follows the board's focus on its own (the board does not
 * re-render for it): a tile or card under the pointer shows it, a click pins
 * it with its links and a close button, Escape lets it go.
 *
 * On a desktop the hover preview takes the OTHER half of the right column (a
 * bullish tile's detail over the bearish half), so the chart and the line it
 * lights stay in view. A click opens the full detail over the whole column
 * (owner, 26 Oct 2026: "make the pop-up better"): a taller chart, every
 * conviction check in words, ← → to step through the side's list, and the
 * close and step controls in the app's own icons.
 */
export function FlowPopup({ flow, mode }: FlowPopupProps) {
  const focus = useFlowFocus();
  const [shown, setShownState] = useState<FocusState | null>(null);
  const shownRef = useRef<FocusState | null>(null);
  const timer = useRef(0);
  useEffect(() => {
    const setShown = (next: FocusState | null) => { shownRef.current = next; setShownState(next); };
    return focus.subscribe(state => {
      window.clearTimeout(timer.current);
      const wanted = state.symbol && (state.pinned || (mode === 'half' && state.origin !== 'chart')) ? state : null;
      // Leaving waits a beat too: crossing the gap between two tiles does not close and reopen it.
      if (!wanted) {
        if (shownRef.current?.pinned || state.symbol || state.sector) setShown(null);
        else if (shownRef.current) timer.current = window.setTimeout(() => setShown(null), HIDE_DELAY_MS);
        return;
      }
      // Moving from one tile to the next swaps at once; arriving from nowhere waits a beat, so a sweep across the board does not flash.
      if (shownRef.current || wanted.pinned) setShown(wanted);
      else timer.current = window.setTimeout(() => setShown(wanted), SHOW_DELAY_MS);
    });
  }, [focus, mode]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  // While a detail is pinned, ← and → step to the neighbour in its side's list.
  const step = useRef<(by: number) => void>(() => {});
  useEffect(() => {
    if (!shown?.pinned) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable]')) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); step.current(event.key === 'ArrowRight' ? 1 : -1); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [shown?.pinned]);

  const stock = useMemo(() => (shown?.symbol ? flow.stocks.find(item => item.symbol === shown.symbol) ?? null : null), [shown, flow.stocks]);
  if (!shown || !stock) return null;
  const full = shown.pinned && mode === 'half';
  const where = mode === 'sheet' ? 'is-sheet' : full ? 'is-full' : stock.side === 'bearish' ? 'is-top' : 'is-bottom';
  const list = stock.side === 'bullish' ? flow.bullish : stock.side === 'bearish' ? flow.bearish : null;
  const at = list ? list.findIndex(item => item.symbol === stock.symbol) : -1;
  const prev = list && at > 0 ? list[at - 1] : null;
  const next = list && at >= 0 && at < list.length - 1 ? list[at + 1] : null;
  step.current = by => { const target = by > 0 ? next : prev; if (target) focus.togglePin(target.symbol, 'key'); };
  return (
    <div className={`mf-popup ${where} ${toneOf(stock)}${shown.pinned ? ' is-pinned' : ''}`} role={shown.pinned ? 'dialog' : 'tooltip'} aria-label={`${stock.symbol} in detail`}>
      <header className="mf-popup__head">
        <SymbolMark symbol={stock.symbol} kind={stock.kind} size={30} showTitle={false} className="mf-logo mf-popup__logo" />
        <span className="mf-popup__id">
          <b>{stock.symbol}</b>
          <span>{stock.name}{stock.kind === 'stock' ? ` · ${stock.sectorLabel}` : ' · Index'}</span>
        </span>
        <span className="mf-popup__spark"><Spark stock={stock} width={64} height={22} /></span>
        <span className="mf-popup__price">
          <b>₹{fmtPrice(stock.fut?.price ?? stock.spot)}</b>
          <ChangeText value={stock.changePct} />
          {stock.fut && <span className={`mf-num ${toneOf(stock)}`}>{signedText(stock.fut.priceChange)}</span>}
        </span>
        {shown.pinned && (
          <span className="mf-popup__tools">
            {list && (
              <>
                <button type="button" className="mf-popup__tool" aria-label={prev ? `Previous: ${prev.symbol}` : 'No previous stock'} aria-keyshortcuts="ArrowLeft" title={prev ? `Previous: ${prev.symbol}` : undefined} disabled={!prev} onClick={() => step.current(-1)}><CaretLeftIcon size={16} /></button>
                <span className="mf-popup__count" aria-hidden="true">{at + 1}/{list.length}</span>
                <button type="button" className="mf-popup__tool" aria-label={next ? `Next: ${next.symbol}` : 'No next stock'} aria-keyshortcuts="ArrowRight" title={next ? `Next: ${next.symbol}` : undefined} disabled={!next} onClick={() => step.current(1)}><CaretRightIcon size={16} /></button>
              </>
            )}
            <button type="button" className="mf-popup__tool mf-popup__close" aria-label="Close the detail" aria-keyshortcuts="Escape" title="Close" onClick={() => focus.clear()}><XIcon size={16} /></button>
          </span>
        )}
      </header>
      <MiniChart stock={stock} window={flow.window} />
      <dl className="mf-popup__facts">
        <div><dt>Rank</dt><dd>{stock.rank != null && list ? <>#{stock.rank} <small>of {list.length} {stock.side === 'bullish' ? 'up' : 'down'}</small></> : <small>Flat, inside ±{flow.floorPct}%</small>}</dd></div>
        <div><dt>Build-up</dt><dd className={`mf-tone is-${stock.side ?? 'flat'}`}>{buildUpText(stock)}</dd></div>
        <div><dt>Conviction</dt><dd>{stock.checks.length ? <DotMeter checks={stock.checks} count /> : <small>—</small>}</dd></div>
        <div><dt>Open Interest</dt><dd><ChangeText value={stock.oiChangePct} digits={1} neutral />{stock.fut && <small> {compactUnits(stock.fut.oi)}</small>}</dd></div>
        <div><dt>Support</dt><dd className="is-put">{levelPair(stock.support, stock.support2, 'S')}</dd></div>
        <div><dt>Resistance</dt><dd className="is-call">{levelPair(stock.resistance, stock.resistance2, 'R')}</dd></div>
        <div className="is-wide"><dt>Zone</dt><dd>{stock.zone ? <>{fmtPrice(stock.zone.low)}–{fmtPrice(stock.zone.high)} <small>{clockOf(stock.zone.from)}–{clockOf(stock.zone.to)}</small></> : <small>None</small>}</dd></div>
      </dl>
      {full && stock.checks.length > 0 && (
        <section className="mf-popup__checks" aria-label="Why it ranks here">
          <h4>Why it ranks here</h4>
          <ul>
            {stock.checks.map(check => (
              <li key={check.id} className={check.pass == null ? 'is-unknown' : check.pass ? 'is-held' : 'is-open'}>
                <span className="mf-popup__mark" aria-hidden="true">{check.pass == null ? <MinusIcon size={12} /> : check.pass ? <CheckIcon size={12} /> : <XIcon size={12} />}</span>
                <span><b>{check.label}</b><small>{check.note}</small></span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {shown.pinned ? (
        <footer className="mf-popup__foot">
          <span>{pcrText(stock)}Levels from the {expiryDisplay(stock.expiry).label} expiry</span>
        </footer>
      ) : (
        <p className="mf-popup__hint">Click to keep it open · {pcrText(stock)}levels from the {expiryDisplay(stock.expiry).label} expiry</p>
      )}
    </div>
  );
}

const pcrText = (stock: FlowStock) => (stock.options.pcr != null ? `PCR ${stock.options.pcr.toFixed(2)} · ` : '');

const levelPair = (first: FlowLevel | null, second: FlowLevel | null, letter: string) => {
  if (!first) return <small>None</small>;
  return <>{letter}1 {levelText(first.strike)}{second && <small> · {letter}2 {levelText(second.strike)}</small>}</>;
};

/**
 * The future through the window: candles from its minute closes, the base as a dashed
 * rule (the previous close for the day, the window's first candle for 1h and
 * 15m), the zone as a box over its time and price, and the option levels as
 * rules labelled at the right when they sit near the session's range.
 */
function MiniChart({ stock, window: win }: { stock: FlowStock; window: MarketFlow['window'] }) {
  const [ref, box] = useBox<HTMLDivElement>();
  const candles = windowCandles(stock);
  const note = stock.futures === 'pending' ? 'Loading future…' : stock.futures === 'failed' ? 'Could not load future' : stock.futures === 'unavailable' ? 'No future listed for this underlying' : candles.length < 2 ? 'Too few minutes yet for a line' : null;
  const { width: w, height: h } = box;
  let body = null;
  if (!note && w > 0 && h > 0) {
    const pad = { top: 8, right: 80, bottom: 18, left: 6 };
    let low = Infinity;
    let high = -Infinity;
    for (const candle of candles) { low = Math.min(low, candle.close); high = Math.max(high, candle.close); }
    const base = stock.fut?.priceFrom ?? null;
    if (base != null) { low = Math.min(low, base); high = Math.max(high, base); }
    if (stock.zone) { low = Math.min(low, stock.zone.low); high = Math.max(high, stock.zone.high); }
    const range = Math.max(high - low, (stock.fut?.price ?? stock.spot) * 0.002);
    const levels: Array<[string, FlowLevel]> = [];
    for (const [name, level] of [['S1', stock.support], ['S2', stock.support2], ['R1', stock.resistance], ['R2', stock.resistance2]] as Array<[string, FlowLevel | null]>) {
      if (level && level.strike >= low - range * 0.6 && level.strike <= high + range * 0.6) levels.push([name, level]);
    }
    for (const [, level] of levels) { low = Math.min(low, level.strike); high = Math.max(high, level.strike); }
    const margin = (high - low) * 0.06 || range * 0.06;
    low -= margin; high += margin;
    const t0 = stock.fut?.from ?? candles[0].at;
    const t1 = candles[candles.length - 1].at + MINUTE;
    const x = (t: number) => pad.left + ((t - t0) / Math.max(1, t1 - t0)) * (w - pad.left - pad.right);
    const y = (price: number) => pad.top + (1 - (price - low) / (high - low)) * (h - pad.top - pad.bottom);
    const last = candles[candles.length - 1];
    // Candles from the minute closes: 5 minutes for a day, 1 minute for the short windows.
    const span = candles.length > 120 ? 5 : candles.length > 30 ? 2 : 1;
    const bars = candlesFromCloses(candles, span);
    const bw = Math.max(1.2, ((w - pad.left - pad.right) / Math.max(1, bars.length)) * 0.62);
    // Level tags are kept 12px apart at the right edge.
    const tags = [...levels.map(([name, level]) => ({ name: `${name} ${levelText(level.strike)}`, y: y(level.strike), cls: name.startsWith('S') ? 'is-put' : 'is-call' })),
      ...(base != null ? [{ name: win === 'day' ? `Prev ${fmtPrice(base)}` : `From ${fmtPrice(base)}`, y: y(base), cls: 'is-base' }] : [])].sort((a, b) => a.y - b.y);
    // Tags stay 14px apart (they touched at 12px: "Prev 1990.60" sat on "S2 1900").
    for (let i = 1; i < tags.length; i++) if (tags[i].y - tags[i - 1].y < 14) tags[i].y = tags[i - 1].y + 14;
    const ticks = [t0, t0 + (t1 - t0) / 2, t1];
    body = (
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${stock.symbol} future, ${candles.length} minutes, from ${fmtPrice(candles[0].close)} to ${fmtPrice(last.close)}`}>
        {stock.zone && stock.zone.to > t0 && (
          <rect className="mf-mini__zone" x={x(Math.max(t0, stock.zone.from))} width={Math.max(3, x(Math.min(t1, stock.zone.to)) - x(Math.max(t0, stock.zone.from)))}
            y={y(stock.zone.high)} height={Math.max(3, y(stock.zone.low) - y(stock.zone.high))} rx="2" />
        )}
        {levels.map(([name, level]) => <line key={name} className={`mf-mini__level ${name.startsWith('S') ? 'is-put' : 'is-call'}`} x1={pad.left} x2={w - pad.right + 4} y1={y(level.strike)} y2={y(level.strike)} />)}
        {base != null && <line className="mf-mini__base" x1={pad.left} x2={w - pad.right + 4} y1={y(base)} y2={y(base)} />}
        {bars.map(bar => {
          const cx = x(bar.at + (span * MINUTE) / 2);
          return (
            <g key={bar.at} className={bar.close >= bar.open ? 'is-up' : 'is-down'}>
              <line className="mf-mini__wick" x1={cx} x2={cx} y1={y(bar.high)} y2={y(bar.low)} />
              <rect className="mf-mini__body" x={cx - bw / 2} width={bw} y={y(Math.max(bar.open, bar.close))} height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))} />
            </g>
          );
        })}
        <circle className="mf-mini__dot" cx={x(last.at + MINUTE)} cy={y(last.close)} r="3" />
        {tags.map(tag => <text key={tag.name} className={`mf-mini__tag ${tag.cls}`} x={w - pad.right + 8} y={tag.y + 3.5}>{tag.name}</text>)}
        {ticks.map((t, i) => <text key={i} className="mf-mini__time" x={x(t)} y={h - 4} textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}>{clockOf(t)}</text>)}
      </svg>
    );
  }
  return <div className="mf-mini" ref={ref}>{note ? <p className="mf-mini__note">{note}</p> : body}</div>;
}
