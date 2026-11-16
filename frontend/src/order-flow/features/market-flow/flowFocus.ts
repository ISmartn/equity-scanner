import { createContext, useContext } from 'react';

/**
 * The board's focus, kept out of React state: hovering a tile, a line or a
 * sector must not re-render the board. The controller marks the elements
 * that carry the focused symbol or sector (`data-sym`, `data-sector`) with
 * `is-lit` and the board with `has-focus`, and tells the two listeners that
 * draw something of their own: the chart (its lit lines) and the popup.
 *
 * Hover is transient; a click pins (the popup stays, the lines stay lit)
 * until Escape, a second click or a click elsewhere.
 */

export type FocusOrigin = 'tile' | 'chart' | 'sector' | 'card' | 'key';

export interface FocusState {
  symbol: string | null;
  sector: string | null;
  origin: FocusOrigin | null;
  pinned: boolean;
}

type Listener = (state: FocusState) => void;

const EMPTY: FocusState = { symbol: null, sector: null, origin: null, pinned: false };

export class FlowFocus {
  private root: HTMLElement | null = null;
  private lit: Element[] = [];
  private hover: FocusState = EMPTY;
  private pin: FocusState = EMPTY;
  private listeners = new Set<Listener>();
  private applied = '';

  attach(root: HTMLElement | null): void {
    this.root = root;
    this.applied = '';
    this.apply();
  }

  get state(): FocusState {
    return this.hover.symbol || this.hover.sector ? this.hover : this.pin;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => { this.listeners.delete(listener); };
  }

  /** Pointer or keyboard over a symbol; null when it leaves. */
  hoverSymbol(symbol: string | null, origin: FocusOrigin): void {
    this.hover = symbol ? { symbol, sector: null, origin, pinned: false } : EMPTY;
    this.apply();
  }

  hoverSector(sector: string | null): void {
    this.hover = sector ? { symbol: null, sector, origin: 'sector', pinned: false } : EMPTY;
    this.apply();
  }

  /** A click: pins the symbol, or lets it go when it is already pinned. */
  togglePin(symbol: string, origin: FocusOrigin): void {
    this.pin = this.pin.symbol === symbol ? EMPTY : { symbol, sector: null, origin, pinned: true };
    this.hover = EMPTY;
    this.apply();
  }

  togglePinSector(sector: string): void {
    this.pin = this.pin.sector === sector ? EMPTY : { symbol: null, sector, origin: 'sector', pinned: true };
    this.hover = EMPTY;
    this.apply();
  }

  clear(): void {
    this.pin = EMPTY;
    this.hover = EMPTY;
    this.apply();
  }

  get pinned(): FocusState { return this.pin; }

  /** Re-marks the elements after the board re-renders: a slot may now hold a different symbol. */
  refresh(): void {
    this.applied = '';
    this.apply();
  }

  private apply(): void {
    const state = this.state;
    const key = `${state.symbol ?? ''}|${state.sector ?? ''}|${state.pinned ? 1 : 0}|${state.origin ?? ''}`;
    if (key === this.applied) return;
    this.applied = key;
    for (const element of this.lit) element.classList.remove('is-lit');
    this.lit = [];
    const root = this.root;
    if (root) {
      const selector = state.symbol ? `[data-sym="${cssEscape(state.symbol)}"]` : state.sector ? `[data-sector="${cssEscape(state.sector)}"]` : null;
      if (selector) {
        this.lit = Array.from(root.querySelectorAll(selector));
        for (const element of this.lit) element.classList.add('is-lit');
      }
      root.classList.toggle('has-focus', Boolean(selector));
      root.dataset.focusKind = state.sector ? 'sector' : state.symbol ? 'symbol' : '';
    }
    for (const listener of this.listeners) listener(state);
  }
}

const cssEscape = (value: string) => (typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(value) : value.replace(/["\\]/g, '\\$&'));

export const FlowFocusContext = createContext<FlowFocus | null>(null);

export function useFlowFocus(): FlowFocus {
  const focus = useContext(FlowFocusContext);
  if (!focus) throw new Error('useFlowFocus outside the board');
  return focus;
}
