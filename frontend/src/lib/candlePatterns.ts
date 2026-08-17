import type { CandlePoint } from "@/lib/api";

export function isGreenCandle(candle: CandlePoint): boolean {
  return candle.close > candle.open;
}

export interface GreenStreakBox {
  startIndex: number;
  endIndex: number;
  startDate: string;
  endDate: string;
  top: number;
  bottom: number;
}

/** One box per run of 3+ consecutive green (close > open) candles. */
export function computeThreeGreenStreakBoxes(history: CandlePoint[]): GreenStreakBox[] {
  const boxes: GreenStreakBox[] = [];
  let streakStart = -1;
  let streakLen = 0;

  const flush = (end: number) => {
    if (streakLen < 3) return;

    let top = history[streakStart].high;
    let bottom = history[streakStart].low;
    for (let j = streakStart; j <= end; j++) {
      top = Math.max(top, history[j].high);
      bottom = Math.min(bottom, history[j].low);
    }

    boxes.push({
      startIndex: streakStart,
      endIndex: end,
      startDate: history[streakStart].date,
      endDate: history[end].date,
      top,
      bottom,
    });
  };

  for (let i = 0; i < history.length; i++) {
    if (isGreenCandle(history[i])) {
      if (streakLen === 0) streakStart = i;
      streakLen += 1;
    } else {
      if (streakLen > 0) flush(i - 1);
      streakStart = -1;
      streakLen = 0;
    }
  }

  if (streakLen > 0) flush(history.length - 1);

  return boxes;
}

/** Indices of candles that belong to a run of 3+ consecutive green (close > open) days. */
export function indicesInThreeGreenStreak(history: CandlePoint[]): Set<number> {
  const marked = new Set<number>();
  for (const box of computeThreeGreenStreakBoxes(history)) {
    for (let i = box.startIndex; i <= box.endIndex; i++) {
      marked.add(i);
    }
  }
  return marked;
}
