import { memo, useRef, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { fmtPrice } from '@/order-flow/utils/formatters';
import { useFlowFocus } from './flowFocus';
import { SymbolMark } from '@/order-flow/components/common/SymbolMark';
import { demoFeatured } from './demoFeatured';
import { BuildMark, buildUpText, ChangeText, DotMeter, heatStyle, pctText, TickFlash, signedText, Spark, toneOf } from './FlowParts';
import { levelText, type FlowStock } from './marketFlowModel';

export type HalfSide = 'bullish' | 'bearish';

interface FlowHalfProps {
  side: HalfSide;
  /** Every underlying on the side, by the size of the move (the model's order). */
  stocks: readonly FlowStock[];
  featured: readonly FlowStock[];
  /** The futures are still loading: the large cards are held, their room kept. */
  holding: boolean;
  floorPct: number;
  /** The count read across the whole board, for the rank's "of". */
  total: number;
}

const TITLE: Record<HalfSide, string> = { bullish: 'Bullish', bearish: 'Bearish' };
const WORD: Record<HalfSide, string> = { bullish: 'up', bearish: 'down' };

/**
 * One half of the right column: the side's heading and count, every
 * underlying as a small tile ranked by its move (the order the chart's line
 * ends stand in), then the side's one or two large cards. Tiles keep their
 * slot as the futures arrive (the slot, not the stock, is the element), so
 * the grid never shifts while it fills in.
 *
 * Hover, focus and click go through the board's focus by delegation: one set
 * of listeners for the grid, none per tile.
 */
export const FlowHalf = memo(function FlowHalf({ side, stocks, featured, holding, floorPct, total }: FlowHalfProps) {
  const focus = useFlowFocus();
  const gridRef = useRef<HTMLDivElement>(null);
  const symbolAt = (target: EventTarget | null) => (target as HTMLElement | null)?.closest<HTMLElement>('[data-tile]')?.dataset.sym ?? null;

  const over = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'touch') return;
    const symbol = symbolAt(event.target);
    if (symbol) focus.hoverSymbol(symbol, 'tile');
  };
  const out = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'touch') return;
    const to = symbolAt(event.relatedTarget);
    if (!to) focus.hoverSymbol(null, 'tile');
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const tiles = Array.from(gridRef.current?.querySelectorAll<HTMLButtonElement>('[data-tile]') ?? []);
    const at = tiles.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    const top = tiles[0]?.offsetTop ?? 0;
    const cols = Math.max(1, tiles.filter(tile => tile.offsetTop === top).length);
    const next = { ArrowRight: at + 1, ArrowLeft: at - 1, ArrowDown: at + cols, ArrowUp: at - cols, Home: 0, End: tiles.length - 1 }[event.key];
    if (next == null) return;
    event.preventDefault();
    const target = tiles[Math.max(0, Math.min(tiles.length - 1, next))];
    for (const tile of tiles) tile.tabIndex = tile === target ? 0 : -1;
    target.focus();
  };

  const headId = `flow-${side}-heading`;
  return (
    <section className={`mf-half is-${side}`} aria-labelledby={headId}>
      <header className="mf-half__head">
        <h2 id={headId} className="mf-half__title"><span className={`mf-tone is-${side}`}>{TITLE[side]} <b className="mf-half__count">{stocks.length}</b></span></h2>
        <p className="mf-half__sub">Ranked by move</p>
        <p className="mf-half__key" aria-hidden="true">
          <span><i className="mf-mark is-opened" />{side === 'bullish' ? 'Long build-up' : 'Short build-up'}</span>
          <span><i className="mf-mark is-closed" />{side === 'bullish' ? 'Short covering' : 'Long unwinding'}</span>
        </p>
      </header>
      {stocks.length === 0 ? (
        <p className="mf-half__empty">None {WORD[side]} more than {floorPct}%</p>
      ) : (
        <div className="mf-tiles" ref={gridRef} role="group" aria-label={`${TITLE[side]}, ranked by move`}
          onPointerOver={over} onPointerOut={out} onKeyDown={onKeyDown}
          onFocus={event => { const symbol = symbolAt(event.target); if (symbol) focus.hoverSymbol(symbol, 'key'); }}
          onBlur={event => { if (!symbolAt(event.relatedTarget)) focus.hoverSymbol(null, 'key'); }}
          onClick={event => { const symbol = symbolAt(event.target); if (symbol) focus.togglePin(symbol, 'tile'); }}>
          {/* Keyed by slot: a slot keeps its element while the ranking fills in. */}
          {stocks.map((stock, slot) => <FlowTile key={slot} stock={stock} first={slot === 0} side={side} total={total} />)}
        </div>
      )}
      {(featured.length > 0 || (holding && stocks.length > 0)) && (
        <div className="mf-featured" aria-label={`${TITLE[side]}: the strongest readings`}>
          {featured.length > 0
            ? featured.map(stock => <FlowCard key={stock.symbol} stock={stock} side={side} />)
            : demoFeatured(stocks, side, 2).map(stock => <FlowCard key={`demo:${stock.symbol}`} stock={stock} side={side} demo />)}
        </div>
      )}
    </section>
  );
});

const FlowTile = memo(function FlowTile({ stock, first, side, total }: { stock: FlowStock; first: boolean; side: HalfSide; total: number }) {
  const spot = stock.source !== 'futures';
  const label = `${stock.symbol}, ${WORD[side]} ${pctText(Math.abs(stock.changePct ?? 0)).replace(/^\+/, '')}${spot ? ' on the spot' : ''}, ${buildUpText(stock)}, rank ${stock.rank} of ${total}`;
  return (
    <button type="button" className={`mf-tile ${toneOf(stock)}${spot ? ' is-spot' : ''}`} data-tile="" data-sym={stock.symbol} data-sector={stock.sector}
      tabIndex={first ? 0 : -1} style={heatStyle(stock.changePct)} aria-label={label}>
      <TickFlash value={stock.changePct} />
      <span className="mf-tile__row">
        <SymbolMark symbol={stock.symbol} kind={stock.kind} size={14} showTitle={false} className="mf-logo" />
        <span className="mf-tile__sym" data-ui-tip={stock.symbol} data-ui-tip-when="cut">{stock.symbol}</span>
        <span className="mf-tile__rk">{stock.rank}</span>
      </span>
      <span className="mf-tile__row">
        <ChangeText value={stock.changePct} className="mf-tile__pct" />
        <BuildMark stock={stock} />
        <span className="mf-tile__spark">{spot ? <small>spot</small> : <Spark stock={stock} width={34} height={12} />}</span>
      </span>
    </button>
  );
});

/** A large card: the reading in full at a glance, with the day's line and the levels either side of spot. */
export const FlowCard = memo(function FlowCard({ stock, side, demo = false }: { stock: FlowStock; side: HalfSide; demo?: boolean }) {
  const focus = useFlowFocus();
  const price = stock.fut?.price ?? stock.spot;
  return (
    <article className={`mf-card ${toneOf(stock)}${demo ? ' is-demo' : ''}`} data-sym={stock.symbol} data-sector={stock.sector} style={heatStyle(stock.changePct)}>
      <TickFlash value={stock.changePct} />
      <button type="button" className="mf-card__main" aria-label={`${stock.symbol}: ${WORD[side]} ${pctText(Math.abs(stock.changePct ?? 0)).replace(/^\+/, '')}, ${buildUpText(stock)}. Open the detail.`}
        onPointerEnter={event => { if (event.pointerType !== 'touch') focus.hoverSymbol(stock.symbol, 'card'); }}
        onPointerLeave={event => { if (event.pointerType !== 'touch') focus.hoverSymbol(null, 'card'); }}
        onFocus={() => focus.hoverSymbol(stock.symbol, 'key')} onBlur={() => focus.hoverSymbol(null, 'key')}
        onClick={() => focus.togglePin(stock.symbol, 'card')}>
        <span className="mf-card__head">
          <SymbolMark symbol={stock.symbol} kind={stock.kind} size={22} showTitle={false} className="mf-logo" />
          <b className="mf-card__sym">{stock.symbol}</b>
          {demo && <span className="mf-demo" data-ui-tip="Demo: the line and futures figures are a sample until this stock's future is read">Demo</span>}
          <DotMeter checks={stock.checks} count />
        </span>
        <span className="mf-card__figs">
          <ChangeText value={stock.changePct} className="mf-card__pct" />
          <span className="mf-card__meta">
            <span className="mf-card__price">₹{fmtPrice(price)} <span className={`mf-tone is-${side}`}>{signedText(stock.fut?.priceChange)}</span></span>
            <span className={`mf-card__bu mf-tone is-${side}`}>{buildUpText(stock)}</span>
          </span>
        </span>
        <span className="mf-card__spark"><Spark stock={stock} width={240} height={34} base zone fluid /></span>
        <span className="mf-card__levels">
          <span><i>Support</i><b>{stock.support ? levelText(stock.support.strike) : '—'}</b></span>
          <span><i>Zone</i><b>{stock.zone ? `${fmtPrice(stock.zone.low)}–${fmtPrice(stock.zone.high)}` : '—'}</b></span>
          <span><i>Resistance</i><b>{stock.resistance ? levelText(stock.resistance.strike) : '—'}</b></span>
        </span>
      </button>
    </article>
  );
});
