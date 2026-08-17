import type { CandlePoint } from "@/lib/api";

export interface MoveFilterOptions {
  positiveThreshold: number | null;
  negativeThreshold: number | null;
  positiveEnabled: boolean;
  negativeEnabled: boolean;
}

export function pctFromPrevClose(
  candle: CandlePoint,
  index: number,
  history: CandlePoint[],
): number | null {
  if (index === 0) return null;
  const prevClose = history[index - 1].close;
  if (!prevClose) return null;
  return ((candle.close - prevClose) / prevClose) * 100;
}

export function isPositiveMove(
  pct: number,
  options: MoveFilterOptions,
): boolean {
  return (
    options.positiveEnabled &&
    options.positiveThreshold !== null &&
    pct >= options.positiveThreshold
  );
}

export function isNegativeMove(
  pct: number,
  options: MoveFilterOptions,
): boolean {
  return (
    options.negativeEnabled &&
    options.negativeThreshold !== null &&
    pct <= -options.negativeThreshold
  );
}

export function isHighlighted(
  candle: CandlePoint,
  index: number,
  history: CandlePoint[],
  options: MoveFilterOptions,
): boolean {
  const pct = pctFromPrevClose(candle, index, history);
  if (pct === null) return false;
  return isPositiveMove(pct, options) || isNegativeMove(pct, options);
}

export function moveDirection(
  pct: number,
  options: MoveFilterOptions,
): "up" | "down" | null {
  if (isPositiveMove(pct, options)) return "up";
  if (isNegativeMove(pct, options)) return "down";
  return null;
}
