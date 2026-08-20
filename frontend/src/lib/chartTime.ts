import { TickMarkType, type Time, type UTCTimestamp } from "lightweight-charts";

/** NSE / Upstox candles are IST session times — always label charts in Asia/Kolkata. */
export const CHART_TZ = "Asia/Kolkata";

function asUnixSeconds(time: Time): number | null {
  if (typeof time === "number" && Number.isFinite(time)) return time;
  if (typeof time === "string") {
    const ms = Date.parse(time.length === 10 ? `${time}T00:00:00+05:30` : time);
    return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
  }
  if (time && typeof time === "object" && "year" in time) {
    const ms = Date.UTC(time.year, time.month - 1, time.day);
    return Math.floor(ms / 1000);
  }
  return null;
}

function formatInIst(
  unixSec: number,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: CHART_TZ,
    ...options,
  }).format(new Date(unixSec * 1000));
}

/** Crosshair / tooltip clock — always IST wall time. */
export function istTimeFormatter(time: Time): string {
  try {
    const sec = asUnixSeconds(time);
    if (sec == null) return "";
    return formatInIst(sec, {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return "";
  }
}

/** Axis tick labels — always IST wall time. */
export function istTickMarkFormatter(
  time: Time,
  tickMarkType: TickMarkType,
): string | null {
  try {
    const sec = asUnixSeconds(time);
    if (sec == null) return null;

    switch (tickMarkType) {
      case TickMarkType.Year:
        return formatInIst(sec, { year: "numeric" });
      case TickMarkType.Month:
        return formatInIst(sec, { month: "short", year: "2-digit" });
      case TickMarkType.DayOfMonth:
        return formatInIst(sec, { day: "2-digit", month: "short" });
      case TickMarkType.Time:
        return formatInIst(sec, { hour: "2-digit", minute: "2-digit", hour12: false });
      case TickMarkType.TimeWithSeconds:
        return formatInIst(sec, {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
      default:
        return formatInIst(sec, { hour: "2-digit", minute: "2-digit", hour12: false });
    }
  } catch {
    return null;
  }
}

export function istChartLocalization() {
  return {
    locale: "en-IN",
    timeFormatter: istTimeFormatter,
  };
}

export function istTimeScaleOptions(timeVisible = true) {
  return {
    timeVisible,
    secondsVisible: false,
    tickMarkFormatter: istTickMarkFormatter,
  };
}

export function toUtcTimestamp(ts: string | number): UTCTimestamp {
  if (typeof ts === "number") {
    return (ts > 1e12 ? Math.floor(ts / 1000) : Math.floor(ts)) as UTCTimestamp;
  }
  const ms = Date.parse(ts);
  if (Number.isNaN(ms)) {
    return 0 as UTCTimestamp;
  }
  return Math.floor(ms / 1000) as UTCTimestamp;
}
