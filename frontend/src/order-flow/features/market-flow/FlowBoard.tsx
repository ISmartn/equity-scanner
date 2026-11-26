import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from 'react';
import { CapsuleSegmented } from '@/order-flow/components/common/CapsuleSegmented';
import { FlowChart } from './FlowChart';
import { FlowDiagram } from './FlowDiagram';
import { FlowFocus, FlowFocusContext } from './flowFocus';
import { FlowPopup } from './FlowPopup';
import { FlowSectors } from './FlowSectors';
import { FlowHalf } from './FlowSide';
import type { FlowSettings, MarketFlow } from './marketFlowModel';
import { useBox } from './useBox';

/** diagram: the wide desktop's continuous flow (≥1280px); desktop: the compact board (1100–1279px). */
export type FlowLayout = 'diagram' | 'desktop' | 'tablet' | 'phone';
type Panel = 'chart' | 'bullish' | 'bearish';

interface FlowBoardProps {
  flow: MarketFlow | null;
  settings: Pick<FlowSettings, 'named' | 'lines'>;
  layout: FlowLayout;
  /** The status line, set in the chart's head on a desktop and above the board elsewhere. */
  status: ReactNode;
  /** The page's own controller, when something outside the board (the notification pane) drives the detail too. */
  focus?: FlowFocus;
}

/** The head row above the chart on a desktop; the chart's zero rule is placed from it, level with the divider. */
export const HEAD_H = 40;
const CHART_H: Record<'tablet' | 'phone', number> = { tablet: 440, phone: 340 };
const CHART_TITLE: Record<MarketFlow['window'], string> = { day: 'Through the day', '1h': 'The last hour', '15m': 'The last 15 minutes' };

/**
 * The board: one surface. On a desktop, the sectors rail and the chart on the
 * left, the Bullish half over the Bearish half on the right, the zero rule of
 * the chart running level with the divider between the halves (above it is
 * up, below it is down). A tablet stacks the chart over the two halves; a
 * phone shows one of the three at a time.
 *
 * The board holds the focus controller: tiles, lines, sectors, cards and the
 * detail all talk through it, and none of them re-renders the board.
 */
export function FlowBoard({ flow, settings, layout, status, focus: shared }: FlowBoardProps) {
  const own = useMemo(() => new FlowFocus(), []);
  const focus = shared ?? own;
  const [panel, setPanel] = useState<Panel>('chart');
  const [chartRef, chartBox] = useBox<HTMLDivElement>();
  const attach = useCallback((node: HTMLDivElement | null) => focus.attach(node), [focus]);

  // A re-dealt board may hold a different stock in a slot: mark the focus again.
  useLayoutEffect(() => { focus.refresh(); }, [focus, flow, panel]);
  // A new window or floor re-deals the sides: nothing stays pinned to a stock that may have moved.
  const win = flow?.window;
  const floor = flow?.floorPct;
  useEffect(() => { focus.clear(); }, [focus, win, floor]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') focus.clear(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [focus]);
  // A click on the board away from a stock, a sector or the detail lets a pinned detail go.
  const onClick = (event: React.MouseEvent) => {
    const target = event.target as HTMLElement;
    if (!target.closest('[data-sym], [data-sector], .mf-popup, .mf-chart__hit')) focus.clear();
  };

  if (layout === 'diagram') {
    return (
      <FlowFocusContext.Provider value={focus}>
        <div className="mf-board" data-layout="diagram" data-window={flow?.window} ref={attach} onClick={onClick}>
          {flow ? <FlowDiagram key={flow.window} flow={flow} settings={settings} status={status} /> : <DiagramSkeleton status={status} />}
        </div>
      </FlowFocusContext.Provider>
    );
  }

  const desktop = layout === 'desktop';
  const chartW = chartBox.width;
  const chartH = desktop ? chartBox.height : CHART_H[layout];
  const chart = (
    <div className="mf-chartcell" ref={chartRef}>
      {flow && chartW > 0 && chartH > 0
        ? <FlowChart key={flow.window} flow={flow} settings={settings} width={chartW} height={chartH} headH={desktop ? HEAD_H : 0} />
        : <div className="mf-skel is-chart" style={desktop ? undefined : { height: CHART_H[layout] }} aria-hidden="true" />}
    </div>
  );
  const half = (side: 'bullish' | 'bearish') => (flow
    ? <FlowHalf key={`${side}:${flow.window}`} side={side} stocks={flow[side]} featured={flow.featured[side].slice(0, 2)} holding={flow.featured[side].length === 0 && flow.futures.pending > 0}
      floorPct={flow.floorPct} total={flow[side].length} />
    : <SkeletonHalf side={side} />);
  const sectors = flow ? <FlowSectors sectors={flow.sectors} split={desktop} flow={desktop ? flow : undefined} /> : <div className="mf-sectors is-skeleton" aria-hidden="true" />;
  const popup = flow ? <FlowPopup flow={flow} mode={desktop ? 'half' : 'sheet'} /> : null;

  if (desktop) {
    return (
      <FlowFocusContext.Provider value={focus}>
        <div className="mf-board" data-layout="desktop" data-window={flow?.window} ref={attach} onClick={onClick}>
          <div className="mf-head">
            <h2 className="mf-head__title">{CHART_TITLE[flow?.window ?? 'day']}</h2>
            {status}
          </div>
          {chart}
          <div className="mf-side">
            {half('bullish')}
            {half('bearish')}
            {popup}
          </div>
          {/* After the lists in the tab order; placed left of the chart by the grid. */}
          <div className="mf-rail">{sectors}</div>
        </div>
      </FlowFocusContext.Provider>
    );
  }

  const switcher = (
    <CapsuleSegmented<Panel>
      options={[{ value: 'chart', label: 'Chart' }, { value: 'bullish', label: flow ? `Bullish ${flow.bullish.length}` : 'Bullish' }, { value: 'bearish', label: flow ? `Bearish ${flow.bearish.length}` : 'Bearish' }]}
      value={panel} onChange={setPanel} ariaLabel="Board panel" groupId="flow-panel" fill className="mf-switch" />
  );
  return (
    <FlowFocusContext.Provider value={focus}>
      <div className="mf-board" data-layout={layout} data-window={flow?.window} ref={attach} onClick={onClick}>
        <div className="mf-head">{status}</div>
        {layout === 'phone' && switcher}
        {(layout === 'tablet' || panel === 'chart') && (
          <section className="mf-chartwrap" aria-label={CHART_TITLE[flow?.window ?? 'day']}>
            <h2 className="mf-head__title">{CHART_TITLE[flow?.window ?? 'day']}</h2>
            {chart}
            {sectors}
          </section>
        )}
        {(layout === 'tablet' || panel === 'bullish') && half('bullish')}
        {(layout === 'tablet' || panel === 'bearish') && half('bearish')}
        {popup}
      </div>
    </FlowFocusContext.Provider>
  );
}

/** The diagram before anything is read: the status, two halves of quiet tiles. */
function DiagramSkeleton({ status }: { status: ReactNode }) {
  return (
    <div className="mf-dg is-skeleton">
      <div className="mf-dg__skelhead">{status}</div>
      <SkeletonHalf side="bullish" />
      <SkeletonHalf side="bearish" />
    </div>
  );
}

/** A half before anything is read: the same frame, quiet blocks for the tiles and cards. */
function SkeletonHalf({ side }: { side: 'bullish' | 'bearish' }) {
  return (
    <section className={`mf-half is-${side} is-skeleton`} aria-label={side === 'bullish' ? 'Bullish' : 'Bearish'}>
      <header className="mf-half__head"><h2 className="mf-half__title"><span className={`mf-tone is-${side}`}>{side === 'bullish' ? 'Bullish' : 'Bearish'}</span></h2></header>
      <div className="mf-tiles" aria-hidden="true">{Array.from({ length: 12 }, (_, i) => <span key={i} className="mf-tile is-skeleton" />)}</div>
      <div className="mf-featured" aria-hidden="true"><div className="mf-card is-holding" /><div className="mf-card is-holding" /></div>
    </section>
  );
}
