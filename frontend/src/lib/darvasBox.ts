import type { CandlePoint } from "@/lib/api";
import {
  type MoveFilterOptions,
  isHighlighted,
  pctFromPrevClose,
} from "@/lib/moveFilter";

export type DarvasBoxDirection = "up" | "down";

export interface DarvasBox {
  startIndex: number;
  endIndex: number;
  startDate: string;
  endDate: string;
  top: number;
  bottom: number;
  direction: DarvasBoxDirection;
}

const CONFIRM_DAYS = 3;
export const DEFAULT_DARVAS_LOOKBACK_DAYS = 30;

/** Classic Darvas boxes (3-day confirmation, breakout/breakdown). */
export function computeDarvasBoxes(candles: CandlePoint[]): DarvasBox[] {
  const boxes: DarvasBox[] = [];
  const n = candles.length;
  if (n < CONFIRM_DAYS + 1) return boxes;

  let i = 0;

  while (i < n) {
    let boxTop = candles[i].high;
    let boxBottom = candles[i].low;
    let topIdx = i;
    let daysWithoutNewHigh = 0;
    let boxConfirmed = false;
    let j = i + 1;
    let closed = false;

    while (j < n) {
      const bar = candles[j];

      if (bar.high > boxTop) {
        boxTop = bar.high;
        topIdx = j;
        daysWithoutNewHigh = 0;
        boxBottom = bar.low;
        boxConfirmed = false;
      } else {
        daysWithoutNewHigh += 1;
        if (daysWithoutNewHigh >= CONFIRM_DAYS) {
          boxConfirmed = true;
        }
      }

      if (boxConfirmed) {
        if (bar.low < boxBottom) {
          boxes.push({
            startIndex: topIdx,
            endIndex: j,
            startDate: candles[topIdx].date,
            endDate: candles[j].date,
            top: boxTop,
            bottom: boxBottom,
            direction: "down",
          });
          i = j;
          closed = true;
          break;
        }

        if (bar.close > boxTop) {
          boxes.push({
            startIndex: topIdx,
            endIndex: j,
            startDate: candles[topIdx].date,
            endDate: candles[j].date,
            top: boxTop,
            bottom: boxBottom,
            direction: "up",
          });
          i = j;
          closed = true;
          break;
        }
      }

      boxBottom = Math.min(boxBottom, bar.low);
      j += 1;
    }

    if (!closed) {
      if (boxConfirmed) {
        boxes.push({
          startIndex: topIdx,
          endIndex: n - 1,
          startDate: candles[topIdx].date,
          endDate: candles[n - 1].date,
          top: boxTop,
          bottom: boxBottom,
          direction: "up",
        });
      }
      break;
    }
  }

  return boxes;
}

/**
 * Darvas-style consolidation box for each day that matches the move filter.
 * Box spans from the recent high (top) through the filter-match day (breakout).
 */
export function computeDarvasBoxesForFilterMatches(
  history: CandlePoint[],
  options: MoveFilterOptions,
  lookback = DEFAULT_DARVAS_LOOKBACK_DAYS,
): DarvasBox[] {
  const boxes: DarvasBox[] = [];

  for (let i = 1; i < history.length; i++) {
    if (!isHighlighted(history[i], i, history, options)) continue;

    const pct = pctFromPrevClose(history[i], i, history);
    if (pct === null) continue;

    const start = Math.max(0, i - lookback);
    let topIdx = start;
    let boxTop = history[start].high;

    for (let k = start; k <= i; k++) {
      if (history[k].high > boxTop) {
        boxTop = history[k].high;
        topIdx = k;
      }
    }

    let boxBottom = history[topIdx].low;
    for (let k = topIdx; k <= i; k++) {
      boxBottom = Math.min(boxBottom, history[k].low);
    }

    boxes.push({
      startIndex: topIdx,
      endIndex: i,
      startDate: history[topIdx].date,
      endDate: history[i].date,
      top: boxTop,
      bottom: boxBottom,
      direction: pct >= 0 ? "up" : "down",
    });
  }

  return boxes;
}
