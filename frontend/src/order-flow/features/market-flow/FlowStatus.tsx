import { Button } from '@/order-flow/components/common/Button';
import { describeDataAge } from './dataAge';
import { clockOf, type MarketFlow } from './marketFlowModel';

const dateFormat = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short' });

interface FlowStatusProps {
  flow: MarketFlow | null;
  /** The market file's own time; null until something has been read. */
  at: number | null;
  loading: boolean;
  /** What the server said when the market could not be read. */
  error?: string | null;
  /** Where the numbers come from: the demo market or a broker. */
  provider?: { id: string; label: string; alwaysLive: boolean } | null;
  futuresRead: number;
  futuresTotal: number;
  onRescan: () => void;
  /** Overridable for tests; the real clock otherwise. */
  now?: number;
}

/**
 * The board's one line of status: how the market split and of how many, and
 * the time the board stands for (the market file's, and the futures' last
 * minute). While futures are still loading the counts are marked as
 * updating, since a spot change stands in for each future not yet read. A
 * file from an earlier session says so.
 */
export function FlowStatus({ flow, at, loading, error, provider, futuresRead, futuresTotal, onRescan, now }: FlowStatusProps) {
  const source = provider ? (
    <span className={`mf-status__source${provider.alwaysLive ? ' is-demo' : ''}`}>
      <i aria-hidden="true" />{provider.id === 'recorded' || provider.id === 'archive' ? `${provider.label} · replay` : provider.alwaysLive ? `${provider.label} · live` : provider.label}
    </span>
  ) : null;
  if (!flow) {
    return (
      <p className="mf-status" role="status">
        {source}
        {error
          ? <span>{error} <Button size="S" intent="secondary" onClick={onRescan}>Try again</Button></span>
          : loading
            ? <span>Loading the market…</span>
            : <span>Could not load data. <Button size="S" intent="secondary" onClick={onRescan}>Try again</Button></span>}
      </p>
    );
  }
  const age = at != null ? describeDataAge(at, now) : null;
  const updating = futuresRead < futuresTotal || flow.provisional;
  const total = flow.futures.total;
  const stamp = at != null ? `${dateFormat.format(at)}, ${clockOf(at)}` : null;
  return (
    <p className={`mf-status${updating ? ' is-updating' : ''}`} role="status">
      {source}
      <span className="mf-status__counts">
        <b className="mf-tone is-bullish">{flow.bullish.length} up</b>
        <span aria-hidden="true"> · </span><span>{flow.rangebound.length} flat</span>
        <span aria-hidden="true"> · </span><b className="mf-tone is-bearish">{flow.bearish.length} down</b>
        <span> of {total}</span>
      </span>
      {updating ? (
        <span className="mf-status__load">
          <span className="mf-status__bar" aria-hidden="true"><i style={{ transform: `scaleX(${futuresRead / Math.max(1, futuresTotal)})` }} /></span>
          Updating · futures {futuresRead} of {futuresTotal}
        </span>
      ) : (
        <span className="mf-status__time">
          {stamp && <>As of {stamp}</>}
          {flow.futures.latestAt != null && <> · futures to {clockOf(flow.futures.latestAt)}</>}
          {flow.futures.failed > 0 && <> · <span className="mf-status__warn">{flow.futures.failed} could not load</span></>}
        </span>
      )}
      {/* A replay (the demo, a recorded day) says what it is in its source label instead. */}
      {age?.aged && !provider?.alwaysLive && <span className="mf-status__aged">{updating && stamp ? `As of ${stamp}, ` : ''}an earlier session</span>}
    </p>
  );
}
