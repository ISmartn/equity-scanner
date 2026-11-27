import { useEffect, useMemo, useRef, useState } from 'react';
import { PageBar } from '@/order-flow/components/chrome/PageBar';
import { CapsuleSegmented } from '@/order-flow/components/common/CapsuleSegmented';
import { useFitScrollerHeight } from '@/order-flow/hooks/useFitScrollerHeight';
import { useMediaQuery } from '@/order-flow/hooks/useMediaQuery';
import type { Underlying } from '@/order-flow/lib/underlyings';
import { FlowBoard, type FlowLayout } from './FlowBoard';
import { FlowFocus } from './flowFocus';
import { FlowSignals, useFlowSignals } from './FlowSignals';
import { FlowStatus } from './FlowStatus';
import { DEFAULT_FLOW_SETTINGS, type FlowSettings } from './marketFlowModel';
import { inUniverse, loadUniverse, saveUniverse, type FlowUniverse } from './nifty50';
import { useMarketFlow } from './useMarketFlow';

/*
 * The workspace stylesheet chain, in the order the other pages import it:
 * the shared tokens (`oi-design` publishes --dash-* and the numeric ramp),
 * this page's own sheet, then the page finish last so it never needs
 * !important.
 */
import '@/order-flow/styles/oi-design-tokens.css';
import './market-flow.css';
import '../underlying/pages-finish.css';

/**
 * Order Flow. Every F&O underlying, read from its future: the day's flow as
 * one chart on the left (bulls rising above the zero rule, bears falling
 * below it), the Bullish half over the Bearish half on the right, each a grid
 * of small tiles ranked by the move and one or two large cards. Hovering a
 * tile lights its line and opens its detail; hovering a line lights its tile.
 *
 * The page keeps nothing of its own. The market file and the futures are the
 * Options Scanner's reads (useMarketFlow), the build-up words are the
 * scanner's, the levels are the chain's open interest. The one choice, the
 * NIFTY 50 or every F&O underlying, is remembered in this browser.
 */

/** The board always reads the whole day, every line drawn, at the day's own floor. */
const SETTINGS: FlowSettings = DEFAULT_FLOW_SETTINGS;
const CHART = { named: SETTINGS.named, lines: SETTINGS.lines };

interface MarketFlowPageProps {
  universe: Underlying[];
}

const UNIVERSES: Array<{ value: FlowUniverse; label: string; title: string }> = [
  { value: 'nifty50', label: 'Nifty 50', title: 'The NIFTY 50 constituents' },
  { value: 'fno', label: 'All F&O', title: 'Every F&O underlying: stocks and indices' },
];

export function MarketFlowPage({ universe }: MarketFlowPageProps) {
  const [scope, setScope] = useState<FlowUniverse>(loadUniverse);
  const pageRef = useRef<HTMLDivElement>(null);
  const wider = useMediaQuery('(min-width: 1280px)');
  const wide = useMediaQuery('(min-width: 1100px)');
  const phone = useMediaQuery('(max-width: 768px)');
  const layout: FlowLayout = wider ? 'diagram' : wide ? 'desktop' : phone ? 'phone' : 'tablet';
  // A desktop board is the window's height; the other layouts scroll the page.
  const fits = layout === 'desktop' || layout === 'diagram';
  useFitScrollerHeight(pageRef, fits);
  useEffect(() => { saveUniverse(scope); }, [scope]);

  const shown = useMemo(() => universe.filter(item => inUniverse(item.symbol, scope)), [universe, scope]);
  const { flow, market, loading, error, provider, futuresRead, futuresTotal, rescan } = useMarketFlow(shown, SETTINGS);
  const signals = useFlowSignals(flow);
  // One focus for the page: the board's tiles and the notification pane light the same detail.
  const focus = useMemo(() => new FlowFocus(), []);

  const pageActions = (
    <>
      <CapsuleSegmented options={UNIVERSES} value={scope} onChange={setScope} ariaLabel="Underlyings" groupId="flow-universe" size="page" className="ui-flow-universe" />
      <FlowSignals signals={signals} focus={focus} flow={flow} />
    </>
  );

  return (
    <div className="ui-flow oi-design" data-window="day" data-universe={scope} data-layout={layout} data-fit={fits ? 'true' : undefined} ref={pageRef}>
      <h1 className="is-visually-hidden">Order Flow</h1>
      <PageBar current="Order Flow" crumbs={false} className="oi-design ui-flow-pagebar">{pageActions}</PageBar>
      <FlowBoard key={scope} focus={focus} flow={flow} settings={CHART} layout={layout}
        status={<FlowStatus flow={flow} at={market?.at ?? null} loading={loading} error={error} provider={provider} futuresRead={futuresRead} futuresTotal={futuresTotal} onRescan={rescan} />} />
    </div>
  );
}
