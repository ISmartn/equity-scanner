import { useEffect, useRef, type RefObject } from 'react';

interface OutsideDismissOptions {
  /** Triggers outside the panel own their click toggle; never close them early. */
  triggers?: readonly RefObject<HTMLElement | null>[];
}

/** Close anchored panels without swallowing the action the reader clicked. */
export function useOutsideDismiss(
  open: boolean,
  boundary: RefObject<HTMLElement | null>,
  onClose: () => void,
  { triggers = [] }: OutsideDismissOptions = {},
) {
  const latest = useRef({ onClose, triggers });
  latest.current = { onClose, triggers };

  useEffect(() => {
    if (!open) return;
    let pointerTarget: EventTarget | null = null;
    const isInside = (event: Event) => {
      const panel = boundary.current;
      const target = event.target;
      if (!panel || !(target instanceof Node)) return true;
      const path = event.composedPath();
      if (panel.contains(target) || path.includes(panel)) return true;
      if (latest.current.triggers.some(trigger => trigger.current?.contains(target))) return true;

      // An embedded workspace's settings live in its body, while its trigger
      // lives in the owning frame header. Let that one trigger toggle once.
      const frame = panel.closest('.tw-widget');
      if (frame && target instanceof Element && target.closest('[data-widget-settings-trigger]')
        && frame === target.closest('.tw-widget')) return true;

      // Both desktop and phone triggers can point at this panel. Its click
      // must toggle once, rather than closing on pointerdown then reopening.
      if (target instanceof Element && panel.id && target.closest('[aria-controls]')
        ?.getAttribute('aria-controls')?.split(/\s+/).includes(panel.id)) return true;

      // Controls can render their menu under body/fullscreenElement. Follow
      // their accessible ownership instead of treating that portal as outside.
      const roots: Element[] = [panel];
      const visited = new Set<Element>(roots);
      for (const root of roots) {
        for (const control of root.querySelectorAll('[aria-controls], [aria-owns]')) {
          const ids = `${control.getAttribute('aria-controls') ?? ''} ${control.getAttribute('aria-owns') ?? ''}`.trim().split(/\s+/);
          for (const id of ids) {
            const owned = document.getElementById(id);
            if (!owned || visited.has(owned)) continue;
            if (owned.contains(target) || path.includes(owned)) return true;
            visited.add(owned);
            roots.push(owned);
          }
        }
      }
      // A nested modal editor may replace its triggering menu. Once it owns
      // focus, its controls remain usable even if that trigger has unmounted.
      const activeDialog = document.activeElement?.closest('[role="dialog"], [role="menu"], [role="listbox"]');
      return !!activeDialog && !panel.contains(activeDialog) && activeDialog.contains(target);
    };
    const onPointer = (event: PointerEvent) => {
      pointerTarget = event.target;
      if (!isInside(event)) latest.current.onClose();
    };
    const onClick = (event: MouseEvent) => {
      // Keyboard/programmatic clicks have no pointerdown. The ordinary click
      // following a pointerdown has already been handled, including portals.
      if (event.target === pointerTarget) return;
      if (!isInside(event)) latest.current.onClose();
    };
    document.addEventListener('pointerdown', onPointer, true);
    document.addEventListener('click', onClick, true);
    return () => {
      document.removeEventListener('pointerdown', onPointer, true);
      document.removeEventListener('click', onClick, true);
    };
  }, [open, boundary]);
}
