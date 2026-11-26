import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BellIcon, XIcon } from '@/order-flow/assets/svg/icons';
import { CapsuleSegmented } from '@/order-flow/components/common/CapsuleSegmented';
import { fmtPrice } from '@/order-flow/utils/formatters';
import type { FlowFocus } from './flowFocus';
import { loadSignals, reconcileSignals, saveSignals, STALE_AFTER_MINUTES, type FlowSignal } from './flowSignals';
import { clockOf, type MarketFlow } from './marketFlowModel';
import { useSignalRecorder } from './signalRecorder';

type Filter = 'all' | 'buy' | 'sell' | 'stale';
const PANE_ID = 'mf-signals';

/** The session's trigger log, kept in this browser and rebuilt against every new reading of the board. */
export function useFlowSignals(flow: MarketFlow | null) {
  const [store, setStore] = useState(() => loadSignals() ?? { date: '', readAt: 0, signals: [] as FlowSignal[], dismissed: [] as string[] });
  useEffect(() => {
    if (!flow) return;
    setStore(current => {
      const base = current.date === flow.date ? current : { date: flow.date, readAt: 0, signals: [], dismissed: [] };
      const signals = reconcileSignals(base.signals, flow, Date.now(), base.dismissed);
      return base === current && signals === current.signals ? current : { ...base, signals };
    });
  }, [flow]);
  useEffect(() => { if (store.date) saveSignals(store); }, [store]);
  const markRead = useCallback(() => setStore(current => ({ ...current, readAt: Date.now() })), []);
  const clear = useCallback(() => setStore(current => ({ ...current, readAt: Date.now(), signals: [], dismissed: [...current.dismissed, ...current.signals.map(signal => signal.id)] })), []);
  const { failed } = useSignalRecorder(flow, store.date, store.signals);
  const unread = store.signals.reduce((n, signal) => n + (signal.updatedAt > store.readAt ? 1 : 0), 0);
  return { signals: store.signals, readAt: store.readAt, unread, markRead, clear, saveFailed: failed };
}

type Signals = ReturnType<typeof useFlowSignals>;

/** The bell in the page bar and the pane it opens: every buy, sell and stale trigger of the session, newest first. */
export function FlowSignals({ signals: log, focus }: { signals: Signals; focus: FlowFocus }) {
  const { signals, unread, markRead, clear, saveFailed } = log;
  const [open, setOpen] = useState(false);
  const [top, setTop] = useState(0);
  const [filter, setFilter] = useState<Filter>('all');
  const bellRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);

  // While the pane is open, what lands in it is read.
  useEffect(() => { if (open && unread > 0) markRead(); }, [open, unread, markRead]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const toggle = () => {
    if (!open) setTop(Math.round(bellRef.current?.getBoundingClientRect().bottom ?? 0) + 8);
    setOpen(!open);
  };
  const counts = useMemo(() => {
    const c = { all: signals.length, buy: 0, sell: 0, stale: 0 };
    for (const signal of signals) c[signal.state === 'stale' ? 'stale' : signal.kind]++;
    return c;
  }, [signals]);
  const shown = signals.filter(signal => filter === 'all' || (filter === 'stale' ? signal.state === 'stale' : signal.state === 'active' && signal.kind === filter));

  return (
    <>
      <button ref={bellRef} type="button" className={`mf-bell${unread ? ' has-unread' : ''}`} aria-label={unread ? `Notifications, ${unread} new` : 'Notifications'}
        aria-expanded={open} aria-controls={PANE_ID} title="Notifications" onClick={toggle}>
        <BellIcon size={18} />
        {unread > 0 && <span className="mf-bell__count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <aside id={PANE_ID} className="mf-signals" style={{ top }} aria-label="Notifications">
          <header className="mf-signals__head">
            <h2>Notifications</h2>
            {signals.length > 0 && <button type="button" className="mf-signals__clear" onClick={clear}>Clear</button>}
            <button type="button" className="mf-popup__tool" aria-label="Close notifications" onClick={close}><XIcon size={16} /></button>
          </header>
          <CapsuleSegmented<Filter> options={[
            { value: 'all', label: 'All', count: counts.all },
            { value: 'buy', label: 'Buy', count: counts.buy },
            { value: 'sell', label: 'Sell', count: counts.sell },
            { value: 'stale', label: 'Stale', count: counts.stale },
          ]} value={filter} onChange={setFilter} ariaLabel="Show" groupId="flow-signals" size="panel" fill className="mf-signals__filter" />
          {shown.length ? (
            <ol className="mf-signals__list">
              {shown.map(signal => <SignalRow key={signal.id} signal={signal} fresh={signal.updatedAt > log.readAt} focus={focus} />)}
            </ol>
          ) : (
            <p className="mf-signals__empty">
              {signals.length ? 'Nothing in this view.' : 'No triggers yet. A zone read on the bullish side is a buy, on the bearish side a sell.'}
            </p>
          )}
          <p className={`mf-signals__note${saveFailed ? ' is-warn' : ''}`}>
            {saveFailed ? 'Could not save to the server; trying again with the next reading. ' : 'Every trigger is saved on the server for backtests; Clear only empties this list. '}
          </p>
          <p className="mf-signals__note">
            Entry is the zone, the stop its far edge, the target the first option level past it. Stale once the side turns, the zone is replaced, the stop or target is hit, or after {STALE_AFTER_MINUTES} minutes.
          </p>
        </aside>
      )}
    </>
  );
}

/**
 * A row lights its stock on the board and opens the same detail a tile does
 * (hover or keyboard focus to preview, click to keep it open).
 */
function SignalRow({ signal, fresh, focus }: { signal: FlowSignal; fresh: boolean; focus: FlowFocus }) {
  const stale = signal.state === 'stale';
  const tone = signal.kind === 'buy' ? 'is-up' : 'is-down';
  const lit = useRef(false);
  const enter = () => { lit.current = true; focus.hoverSymbol(signal.symbol, 'tile'); };
  const leave = () => { if (lit.current) { lit.current = false; focus.hoverSymbol(null, 'tile'); } };
  // A row that goes away (filter, clear, the pane closing) under the pointer lets the detail go.
  useEffect(() => leave, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <li className={`mf-signal ${tone}${stale ? ' is-stale' : ''}${fresh ? ' is-fresh' : ''}`} tabIndex={0}
      aria-label={`${signal.symbol} ${stale ? 'stale' : signal.kind}: show detail`}
      onPointerEnter={enter} onPointerLeave={leave} onFocus={enter} onBlur={leave}
      onClick={() => focus.togglePin(signal.symbol, 'tile')}
      onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); focus.togglePin(signal.symbol, 'tile'); } }}>
      <div className="mf-signal__top">
        <span className={`mf-signal__kind ${stale ? 'is-stale' : tone}`}>{stale ? 'Stale' : signal.kind === 'buy' ? 'Buy' : 'Sell'}</span>
        <b className="mf-signal__sym">{signal.symbol}</b>
        {stale && <small className="mf-signal__was">was {signal.kind}</small>}
        <time className="mf-signal__time" dateTime={new Date(signal.triggeredAt).toISOString()} title="When the zone completed">{clockOf(signal.triggeredAt)}</time>
      </div>
      <dl className="mf-signal__levels">
        <div><dt>Entry</dt><dd>{fmtPrice(signal.entryLow)}–{fmtPrice(signal.entryHigh)}</dd></div>
        <div><dt>Stop</dt><dd className="is-stop">{fmtPrice(signal.stop)}</dd></div>
        <div><dt>Target</dt><dd className="is-target">{signal.target ? <>{fmtPrice(signal.target.price)} <small>{signal.target.name}</small></> : '—'}</dd></div>
      </dl>
      {stale && signal.staleReason && (
        <p className="mf-signal__why">{signal.staleReason}{signal.staleAt != null && <> · {clockOf(signal.staleAt)}</>}</p>
      )}
    </li>
  );
}
