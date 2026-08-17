import type { TimelineCandlePoint } from "@/lib/api";

type VcpWindowDays = 20 | 10 | 5;

export interface VcpBand {
  rangeDays: VcpWindowDays;
  startDate: string;
  endDate: string;
  top: number;
  bottom: number;
  rangePct: number;
}

export interface VcpOverlayData {
  asOfDate: string;
  pivotHigh: number;
  pivotStartDate: string;
  bands: VcpBand[];
  baseStartDate: string;
  baseEndDate: string;
  baseTop: number;
  baseBottom: number;
  baseDepthPct: number;
  volumeDry: boolean;
  breakout: boolean;
  stage?: string;
}

function buildRangeBand(bars: TimelineCandlePoint[], endIndex: number, rangeDays: VcpWindowDays): VcpBand | null {
  const startIndex = endIndex - rangeDays + 1;
  if (startIndex < 0) return null;
  const slice = bars.slice(startIndex, endIndex + 1);
  const top = Math.max(...slice.map((b) => b.high));
  const bottom = Math.min(...slice.map((b) => b.low));
  const close = bars[endIndex].close;
  const rangePct = close > 0 ? ((top - bottom) / close) * 100 : 0;
  return {
    rangeDays: rangeDays,
    startDate: bars[startIndex].date,
    endDate: bars[endIndex].date,
    top,
    bottom,
    rangePct: Math.round(rangePct * 100) / 100,
  };
}

/** Match scanner VCP geometry for chart overlay at the signal bar. */
export function computeVcpOverlay(
  history: TimelineCandlePoint[],
  asOfDate: string,
  signalDetails?: Record<string, unknown>,
): VcpOverlayData | null {
  const endIndex = history.findIndex((b) => b.date === asOfDate);
  if (endIndex < 0 || endIndex < 59) return null;

  const bars = history.slice(0, endIndex + 1);
  const band20 = buildRangeBand(bars, endIndex, 20);
  const band10 = buildRangeBand(bars, endIndex, 10);
  const band5 = buildRangeBand(bars, endIndex, 5);
  if (!band20 || !band10 || !band5) return null;

  const contracting = band20.rangePct > band10.rangePct && band10.rangePct > band5.rangePct;
  if (!contracting && signalDetails?.breakout !== true) return null;

  const pivotSlice = bars.slice(Math.max(0, endIndex - 10), endIndex);
  const computedPivot =
    pivotSlice.length > 0 ? Math.max(...pivotSlice.map((b) => b.high)) : band10.top;
  const pivotHigh =
    typeof signalDetails?.pivot_high === "number" ? signalDetails.pivot_high : computedPivot;

  const baseStartIndex = Math.max(0, endIndex - 39);
  const baseSlice = bars.slice(baseStartIndex, endIndex + 1);
  const baseTop = Math.max(...baseSlice.map((b) => b.high));
  const baseBottom = Math.min(...baseSlice.map((b) => b.low));
  const baseDepthPct =
    typeof signalDetails?.base_depth_pct === "number"
      ? signalDetails.base_depth_pct
      : baseTop > 0
        ? Math.round(((baseTop - baseBottom) / baseTop) * 10000) / 100
        : 0;

  const close = bars[endIndex].close;
  const vol20 =
    bars.slice(Math.max(0, endIndex - 19), endIndex + 1).reduce((s, b) => s + b.volume, 0) / 20;
  const vol5 =
    bars.slice(Math.max(0, endIndex - 4), endIndex + 1).reduce((s, b) => s + b.volume, 0) / 5;
  const volumeDry =
    typeof signalDetails?.volume_dry === "boolean"
      ? signalDetails.volume_dry
      : vol20 > 0
        ? vol5 < vol20 * 0.85
        : false;

  return {
    asOfDate,
    pivotHigh,
    pivotStartDate: bars[Math.max(0, endIndex - 10)].date,
    bands: [band20, band10, band5],
    baseStartDate: bars[baseStartIndex].date,
    baseEndDate: bars[endIndex].date,
    baseTop,
    baseBottom,
    baseDepthPct,
    volumeDry,
    breakout: close > pivotHigh,
    stage: typeof signalDetails?.stage === "string" ? signalDetails.stage : undefined,
  };
}
