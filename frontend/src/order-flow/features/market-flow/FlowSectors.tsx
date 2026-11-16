import { memo, type ReactNode } from 'react';
import { useFlowFocus } from './flowFocus';
import { pctText } from './FlowParts';
import type { FlowSector, MarketFlow } from './marketFlowModel';

interface FlowSectorsProps {
  /** Leader to laggard: the model's order. */
  sectors: readonly FlowSector[];
  /** The whole board, for the spread of moves above the rail (desktop). */
  flow?: MarketFlow;
  /** On a desktop the rail is split at the zero rule: sectors up above it, sectors down below it. */
  split: boolean;
}

/**
 * The sectors, leader to laggard by the median move of their underlyings:
 * the name, the median, and a bar as long as the move against the largest.
 * On a desktop board the rail stands left of the chart and is split at the
 * zero rule, so the sectors that rose sit level with the Bullish half and
 * those that fell with the Bearish. Hover lights a sector's lines and tiles;
 * a click keeps them lit.
 */
export const FlowSectors = memo(function FlowSectors({ sectors, split, flow }: FlowSectorsProps) {
  const focus = useFlowFocus();
  const measured = sectors.filter(sector => sector.changePct != null);
  const largest = Math.max(0.01, ...measured.map(sector => Math.abs(sector.changePct ?? 0)));
  // Keyed by place in the ranking, not by sector: a row keeps its element as the ranking settles, so nothing shifts.
  const row = (sector: FlowSector, slot: number) => {
    const pct = sector.changePct ?? 0;
    const tone = pct > 0.0049 ? 'is-up' : pct < -0.0049 ? 'is-down' : 'is-flat';
    return (
      <li key={slot}>
        <button type="button" className={`mf-sector ${tone}`} data-sector={sector.id}
          aria-label={`${sector.label}: median ${pctText(sector.changePct)}; ${sector.bullish} up, ${sector.bearish} down, ${sector.rangebound} flat of ${sector.count}`}
          onPointerEnter={event => { if (event.pointerType !== 'touch') focus.hoverSector(sector.id); }}
          onPointerLeave={event => { if (event.pointerType !== 'touch') focus.hoverSector(null); }}
          onFocus={() => focus.hoverSector(sector.id)} onBlur={() => focus.hoverSector(null)}
          onClick={() => focus.togglePinSector(sector.id)}>
          <i className="mf-sector__bar" style={{ width: `${(Math.abs(pct) / largest) * 100}%` }} aria-hidden="true" />
          <span className="mf-sector__name">{sector.label}</span>
          <span className="mf-sector__pct">{pctText(sector.changePct)}</span>
        </button>
      </li>
    );
  };
  const list = (items: readonly FlowSector[], label: string, empty: ReactNode) => (
    <ul className="mf-sectors__list" aria-label={label}>{items.length ? items.map(row) : <li className="mf-sectors__none">{empty}</li>}</ul>
  );
  if (!split) {
    return (
      <nav className="mf-sectors" aria-label="Sectors, leader to laggard">
        <h3 className="mf-sectors__title">Sectors <small>median move</small></h3>
        {list(measured, 'Sectors', 'Not measured yet')}
      </nav>
    );
  }
  const up = measured.filter(sector => (sector.changePct ?? 0) >= 0);
  const down = measured.filter(sector => (sector.changePct ?? 0) < 0);
  return (
    <nav className="mf-sectors is-split" aria-label="Sectors, leader to laggard">
      <div className="mf-sectors__half is-up">
        {flow && <FlowSpread flow={flow} />}
        {/* The title rides with the list down to the zero rule. */}
        <div className="mf-sectors__end">
          <h3 className="mf-sectors__title">Sectors <small>median move</small></h3>
          {list(up, 'Sectors up', 'None up')}
        </div>
      </div>
      <div className="mf-sectors__half is-down">{list(down, 'Sectors down', 'None down')}</div>
    </nav>
  );
});

const SPREAD_W = 160;
/** How far the histogram reaches either side, by window: the ends gather everything past it. */
const SPREAD_REACH: Record<MarketFlow['window'], number> = { day: 5, '1h': 1.5, '15m': 0.6 };
const SPREAD_H = 46;

/**
 * The spread of every move on the board as a small histogram, twenty bins
 * from −5% to +5% for the day (±1.5% an hour, ±0.6% 15 minutes; the ends
 * gather everything past them), toned by the
 * side each bin falls on, with the up / flat / down split under it.
 */
function FlowSpread({ flow }: { flow: MarketFlow }) {
  const reach = SPREAD_REACH[flow.window];
  const bins = Array.from({ length: 20 }, () => 0);
  const step = (reach * 2) / bins.length;
  for (const stock of flow.stocks) {
    if (stock.changePct == null) continue;
    const at = Math.max(0, Math.min(bins.length - 1, Math.floor((stock.changePct + reach) / step)));
    bins[at]++;
  }
  const tallest = Math.max(1, ...bins);
  const w = SPREAD_W / bins.length;
  const total = flow.bullish.length + flow.bearish.length + flow.rangebound.length;
  const share = (n: number) => `${(n / Math.max(1, total)) * 100}%`;
  return (
    <figure className="mf-spread" aria-label={`Spread of moves: ${flow.bullish.length} up, ${flow.rangebound.length} flat, ${flow.bearish.length} down`}>
      <figcaption className="mf-spread__title">Spread of moves</figcaption>
      <svg width="100%" height={SPREAD_H + 12} viewBox={`0 0 ${SPREAD_W} ${SPREAD_H + 12}`} preserveAspectRatio="none" aria-hidden="true">
        {bins.map((count, i) => {
          const mid = -reach + (i + 0.5) * step;
          const tone = mid >= flow.floorPct ? 'is-up' : mid <= -flow.floorPct ? 'is-down' : 'is-flat';
          const h = count ? Math.max(1.5, (count / tallest) * SPREAD_H) : 0;
          return <rect key={i} className={tone} x={i * w + 0.5} width={w - 1} y={SPREAD_H - h} height={h} rx="1" />;
        })}
        <line x1={SPREAD_W / 2} x2={SPREAD_W / 2} y1="0" y2={SPREAD_H + 2} />
      </svg>
      <div className="mf-spread__axis" aria-hidden="true"><span>−{reach}%</span><span>0</span><span>+{reach}%</span></div>
      <div className="mf-spread__bar" aria-hidden="true">
        <i className="is-up" style={{ width: share(flow.bullish.length) }} />
        <i className="is-flat" style={{ width: share(flow.rangebound.length) }} />
        <i className="is-down" style={{ width: share(flow.bearish.length) }} />
      </div>
    </figure>
  );
}
