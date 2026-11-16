/**
 * The four things design contract §8 requires of a dialog, in one place, for
 * the whole app.
 *
 *  1. Escape closes.
 *  2. Focus moves INTO the dialog on open.
 *  3. Tab and Shift+Tab cycle inside it.
 *  4. Focus returns to whatever opened it — a modal that dumps the caret at the
 *     top of the document has moved the reader, which is worse than never
 *     having moved focus at all.
 *
 * This exists because an audit found the floor implemented THREE times —
 * `oi-spurts/useDialog`, `open-interest/useOiDialog`, and an inline effect in
 * TimeSwitch — and, predictably, absent from every overlay whose author did not
 * happen to import one of them. The PCR and Straddle "Series" menus and the
 * Open Interest As-of and Custom-window panels all declared `role="dialog"`
 * with none of the four: on those, Tab walked out of a declared modal, and
 * Escape did nothing because the page's only key handler was bound to a
 * different menu. The failure mode is always the same shape — somebody writes
 * `role="dialog"` without importing anything — so the fix is one import that is
 * obvious to reach for.
 *
 * Two details here are load-bearing and were learned the hard way, so do not
 * "simplify" them back:
 *
 * - The focusable query is NOT filtered by `offsetParent`. That property is
 *   null for every descendant of a `position: fixed` layer in some engines and
 *   for everything in jsdom, so filtering on it yields a trap that silently
 *   finds nothing focusable — a trap that does not trap, and one no test can
 *   catch.
 * - Focus is restored only if it is still inside the dialog (or nowhere). If
 *   the reader has already clicked something else, yanking them back is the
 *   same defect this hook exists to prevent.
 */

import { useEffect, useRef, type RefObject } from 'react';
import { isComposingKey } from '@/order-flow/lib/keyboardShortcuts';
import { useOutsideDismiss } from './useOutsideDismiss';

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])', 'select:not([disabled])',
  'textarea:not([disabled])', 'summary', '[tabindex]:not([tabindex="-1"])',
].join(',');

function dialogTabStops(node: HTMLElement): HTMLElement[] {
  return Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(element => {
    if (element.closest('[hidden], [inert]') || (element.tabIndex < 0 && !(element.tagName === 'SUMMARY' && !element.hasAttribute('tabindex')))) return false;
    for (let ancestor = element.parentElement; ancestor && ancestor !== node; ancestor = ancestor.parentElement) {
      if (ancestor instanceof HTMLDetailsElement && !ancestor.open && ancestor.querySelector(':scope > summary') !== element) return false;
    }
    return true;
  });
}

/**
 * The control that opens `dialog`, found by `aria-controls` pointing at the
 * dialog's id. A panel that mounts with focus already on <body> (it was
 * re-created while open, e.g. leaving full screen moves it to another host)
 * has no better opener to go back to than the button that names it.
 */
function openerOf(dialog: HTMLElement | null): HTMLElement | null {
  const id = dialog?.id;
  if (!id) return null;
  for (const candidate of document.querySelectorAll<HTMLElement>('[aria-controls]')) {
    if (candidate.getAttribute('aria-controls') === id && !dialog?.contains(candidate)) return candidate;
  }
  return null;
}

export interface DialogOptions<T extends HTMLElement> {
  /**
   * Freeze the page behind. A full-height sheet over a scrolling page is two
   * scrollers fighting for one finger. Default true; pass false for an
   * anchored panel that is visually attached to something the reader may still
   * want to scroll.
   */
  lockScroll?: boolean;
  /** Supply your own ref when the element is already held by the caller. */
  ref?: RefObject<T | null>;
  /** Anchored Customise panels close on an outside press, without consuming it. */
  dismissOutside?: boolean;
  /** Reading drawers start on their heading container before tabbing to controls. */
  initialFocus?: 'control' | 'container';
}

/**
 * @param open Whether the dialog is currently mounted/visible. Everything is a
 *   no-op while false, so this is safe to call unconditionally.
 * @returns The ref to put on the dialog container. Give that container
 *   `tabIndex={-1}` so it can hold focus when it has no focusable children.
 */
export function useDialog<T extends HTMLElement>(
  open: boolean,
  onClose: () => void,
  { lockScroll = true, ref: suppliedRef, dismissOutside = false, initialFocus = 'control' }: DialogOptions<T> = {},
): RefObject<T | null> {
  const ownRef = useRef<T | null>(null);
  const ref = suppliedRef ?? ownRef;
  useOutsideDismiss(open && dismissOutside, ref, onClose);
  const restoreTo = useRef<HTMLElement | null>(null);

  // The page re-creates `onClose` on every render; depending on it directly
  // would re-run the whole effect — and re-steal focus — on every keystroke.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) {
      restoreTo.current = null;
      return undefined;
    }
    // The opener is whatever held focus BEFORE focus moved in. A re-run of this
    // effect while the panel already holds focus (StrictMode's mount-unmount-
    // mount in development, a re-mount while open) must not record a control
    // inside the dialog as the opener, or Escape would "return" to a node that
    // is gone and focus would fall to the page body.
    const before = document.activeElement;
    if (!restoreTo.current || !restoreTo.current.isConnected || !(before instanceof HTMLElement && ref.current?.contains(before))) {
      // Never <body>, and never a control inside the dialog itself: neither is
      // somewhere focus can usefully return to. Fall back to the opener that
      // `aria-controls` names.
      const usable = before instanceof HTMLElement && before !== document.body && !ref.current?.contains(before);
      restoreTo.current = usable ? before : openerOf(ref.current);
    }

    const node = ref.current;
    // Prefer the first real control; fall back to the container, which carries
    // tabIndex={-1} for exactly this.
    const first = node ? dialogTabStops(node)[0] : undefined;
    (initialFocus === 'container' ? node : first ?? node)?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isComposingKey(event)) return;
      // A portalled child selector/editor owns Escape and Tab while focused.
      const activeDialog = document.activeElement?.closest('[role="dialog"]');
      if (activeDialog && activeDialog !== ref.current) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab' || !ref.current) return;
      // TAB STOPS, not everything focusable. A roving radiogroup (contract §8)
      // parks every unchecked radio at tabIndex -1; those still match
      // `button:not([disabled])`, so they used to be eligible as the head or
      // tail. With the tail a parked radio, Tab from the real last stop (the
      // checked radio) matched neither end, was not prevented, and walked
      // straight out of the dialog.
      const items = dialogTabStops(ref.current);
      if (items.length === 0) {
        // Nothing to move to — keep the caret inside rather than letting Tab
        // walk out into the page underneath.
        event.preventDefault();
        ref.current.focus();
        return;
      }
      const head = items[0];
      const tail = items[items.length - 1];
      const active = document.activeElement;
      // Focus can sit on a parked element — arrow keys move it there without
      // making it a tab stop. Step to the nearest real stop in the direction of
      // travel, wrapping at the ends, so the trap holds from there too.
      if (active instanceof HTMLElement && active !== ref.current && ref.current.contains(active) && !items.includes(active)) {
        event.preventDefault();
        const next = event.shiftKey
          ? [...items].reverse().find(element => active.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_PRECEDING)
          : items.find(element => active.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING);
        (next ?? (event.shiftKey ? tail : head)).focus();
        return;
      }
      if (event.shiftKey && (active === head || active === ref.current)) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && active === tail) {
        event.preventDefault();
        head.focus();
      }
    };

    document.addEventListener('keydown', onKey, true);
    const previousOverflow = document.body.style.overflow;
    if (lockScroll) document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKey, true);
      if (lockScroll) document.body.style.overflow = previousOverflow;
      const active = document.activeElement;
      if (!active || active === document.body || ref.current?.contains(active)) {
        // `isConnected` guards the case where the trigger has itself been
        // unmounted by the same state change that closed this.
        if (restoreTo.current?.isConnected) restoreTo.current.focus();
      }
    };
    // `onClose` is held in a ref above; `ref` identity is stable.
  }, [open, lockScroll, initialFocus]);

  return ref;
}
