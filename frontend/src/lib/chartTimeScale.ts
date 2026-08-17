import type { IChartApi } from "lightweight-charts";

/** ~6 months of NSE daily bars (~22 trading days per month). */
export const DEFAULT_VISIBLE_TRADING_DAYS = 264;

function resolveVisibleBars(visibleBars?: number): number {
  return visibleBars ?? DEFAULT_VISIBLE_TRADING_DAYS;
}

/** Show the last N bars (right-aligned), e.g. scanner / default chart view. */
export function setDefaultChartVisibleRange(
  chart: IChartApi,
  barCount: number,
  options?: {
    visibleBars?: number;
    rightPaddingBars?: number;
  },
): void {
  if (barCount <= 0) return;

  const visibleBars = resolveVisibleBars(options?.visibleBars);
  const rightPaddingBars = options?.rightPaddingBars ?? 2;

  if (barCount <= visibleBars) {
    chart.timeScale().fitContent();
    return;
  }

  chart.timeScale().setVisibleLogicalRange({
    from: barCount - visibleBars,
    to: barCount - 1 + rightPaddingBars,
  });
}

/** Center on a bar while keeping a full-width window (slides at chart edges). */
export function setChartVisibleRangeCentered(
  chart: IChartApi,
  barCount: number,
  centerIndex: number,
  options?: {
    visibleBars?: number;
    rightPaddingBars?: number;
  },
): void {
  if (barCount <= 0) return;

  const visibleBars = resolveVisibleBars(options?.visibleBars);
  const rightPaddingBars = options?.rightPaddingBars ?? 2;

  if (barCount <= visibleBars) {
    chart.timeScale().fitContent();
    return;
  }

  const half = Math.floor(visibleBars / 2);
  let from = centerIndex - half;
  let to = from + visibleBars - 1;

  if (from < 0) {
    from = 0;
    to = visibleBars - 1;
  }
  if (to > barCount - 1) {
    to = barCount - 1;
    from = Math.max(0, to - visibleBars + 1);
  }

  chart.timeScale().setVisibleLogicalRange({
    from,
    to: to + rightPaddingBars,
  });
}

/** Defer until the chart has laid out (needed in flex panels e.g. momentum scanner). */
export function applyChartVisibleRange(apply: () => void): void {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      apply();
    });
  });
}
