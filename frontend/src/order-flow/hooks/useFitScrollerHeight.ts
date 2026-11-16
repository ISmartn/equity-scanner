import { useLayoutEffect, type RefObject } from 'react';

/**
 * Sizes a page to the room its scroll container really has.
 *
 * Writes `--ui-page-fit-h` on `page`: the scroller's visible height less the
 * space already used above the page (the page bar). A page that takes this as
 * its min-height ends exactly at the bottom of the window, so a chart that
 * grows into the rest of the column leaves its legend and scope line on screen
 * rather than below the fold. A fixed offset in CSS cannot do this: the header
 * is a different height in each shell.
 *
 * `enabled` false (a phone, full screen) removes the property and the page
 * keeps its own CSS sizing.
 */
export function useFitScrollerHeight(page: RefObject<HTMLElement | null>, enabled: boolean): void {
  useLayoutEffect(() => {
    const node = page.current;
    if (!node) return undefined;
    const scroller = node.closest<HTMLElement>('.dashboard-body');
    if (!enabled || !scroller) { node.style.removeProperty('--ui-page-fit-h'); return undefined; }
    const measure = () => {
      const above = node.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      const fit = Math.floor(scroller.clientHeight - above);
      if (fit > 0) node.style.setProperty('--ui-page-fit-h', `${fit}px`);
    };
    measure();
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
    observer?.observe(scroller);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
      node.style.removeProperty('--ui-page-fit-h');
    };
  }, [page, enabled]);
}
