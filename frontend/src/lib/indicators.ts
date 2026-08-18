/** Chart indicators — Wilder RSI + Bollinger Bands */

export function wildersRsiSeries(closes: number[], period: number): number[] {
  if (period < 1) throw new Error("RSI period must be >= 1");
  const n = closes.length;
  if (n < period + 1) return [];

  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i += 1) {
    const change = closes[i] - closes[i - 1];
    if (change >= 0) gains += change;
    else losses -= change;
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;
  const out: number[] = [];

  const value = (ag: number, al: number) => {
    if (al === 0) return ag > 0 ? 100 : 50;
    const rs = ag / al;
    return 100 - 100 / (1 + rs);
  };

  out.push(value(avgGain, avgLoss));

  for (let i = period + 1; i < n; i += 1) {
    const change = closes[i] - closes[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out.push(value(avgGain, avgLoss));
  }

  return out;
}

export function rsiStatus(
  value: number | null | undefined,
  overbought = 70,
  oversold = 30,
): "Overbought" | "Oversold" | "Neutral" | "Warming" {
  if (value == null || Number.isNaN(value)) return "Warming";
  if (value >= overbought) return "Overbought";
  if (value <= oversold) return "Oversold";
  return "Neutral";
}

export interface BollingerPoint {
  middle: number;
  upper: number;
  lower: number;
}

export function bollingerBandsSeries(
  closes: number[],
  period = 20,
  stdDevMult = 2,
): (BollingerPoint | null)[] {
  if (period < 2) throw new Error("Bollinger period must be >= 2");
  const out: (BollingerPoint | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period) return out;

  for (let i = period - 1; i < closes.length; i += 1) {
    const window = closes.slice(i - period + 1, i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const variance = window.reduce((acc, v) => acc + (v - mean) ** 2, 0) / period;
    const std = Math.sqrt(variance);
    out[i] = {
      middle: mean,
      upper: mean + stdDevMult * std,
      lower: mean - stdDevMult * std,
    };
  }
  return out;
}
