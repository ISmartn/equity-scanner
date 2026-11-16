const MARKET_TIME_ZONE = 'Asia/Kolkata';
export const MARKET_OPEN_MINUTE = 9 * 60 + 15;
/**
 * The exchanges' Closing Auction Session (CAS) took effect on 3 August 2026.
 * Cash price discovery runs from 15:15 to 15:35 and equity derivatives keep
 * trading until 15:40. `MARKET_CLOSE_MINUTE` therefore means the close of the
 * option-chain session, not the end of normal cash-market trading.
 */
export const CAS_EFFECTIVE_DATE = '2026-08-03';
export const CAS_START_MINUTE = 15 * 60 + 15;
export const CAS_END_MINUTE = 15 * 60 + 35;
const LEGACY_MARKET_CLOSE_MINUTE = 15 * 60 + 30;
export const DERIVATIVES_CLOSE_MINUTE = 15 * 60 + 40;
export const MARKET_CLOSE_MINUTE = DERIVATIVES_CLOSE_MINUTE;

export type MarketPhase =
  | 'closed'
  | 'pre-open'
  | 'continuous'
  | 'closing-auction'
  | 'derivatives-close';
/**
 * India Standard Time is UTC+05:30 all year: no daylight saving since 1945.
 * So a market date and clock are plain arithmetic on the epoch, exactly what
 * `Intl.DateTimeFormat(…, { timeZone: 'Asia/Kolkata' }).formatToParts`
 * returned, at a small fraction of its cost. That call was the hottest helper
 * on a heatmap first load (10 Oct 2026): every cached snapshot asks whether
 * it fell in a session, through two of these each.
 */
const IST_OFFSET_MS = 330 * 60_000;

export function marketParts(time: number | Date) {
  const ms = typeof time === 'number' ? time : time.getTime();
  // As formatToParts did, an invalid instant is an error, never NaN parts.
  if (!Number.isFinite(ms)) throw new RangeError('Invalid time value');
  const ist = new Date(ms + IST_OFFSET_MS);
  const year = ist.getUTCFullYear();
  const month = ist.getUTCMonth() + 1;
  const day = ist.getUTCDate();
  const hour = ist.getUTCHours();
  const minute = ist.getUTCMinutes();
  return {
    year,
    month,
    day,
    weekday: ist.getUTCDay(),
    hour,
    minute,
    dateKey: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
    minuteOfDay: hour * 60 + minute,
  };
}

/**
 * NSE trading holidays (source: NSE circular).
 * Update annually when NSE publishes the new holiday list.
 */
const NSE_HOLIDAYS = new Set([
  // 2025 NSE trading holidays — verify against official NSE circular
  '2025-02-26', // Mahashivratri
  '2025-03-14', // Holi
  '2025-03-31', // Id-Ul-Fitr
  '2025-04-10', // Mahavir Jayanti
  '2025-04-14', // Ambedkar Jayanti
  '2025-04-18', // Good Friday
  '2025-05-01', // Maharashtra Day
  '2025-08-15', // Independence Day
  '2025-08-27', // Ganesh Chaturthi
  '2025-10-02', // Gandhi Jayanti/Dussehra
  '2025-10-21', // Diwali Laxmi Pujan
  '2025-10-22', // Diwali Balipratipada
  '2025-11-05', // Guru Nanak Jayanti
  '2025-12-25', // Christmas

  // 2026 Holidays — cross-checked against the NSE holiday
  // calendars (Sept 2026); the previous entries here were largely wrong dates
  // (e.g. Holi, Good Friday, Bakri Id, Muharram, Guru Nanak Jayanti were all
  // off), see the 2026-08-26 note below for why that matters.
  '2026-01-15', // Municipal Corporation Election (Maharashtra)
  '2026-01-26', // Republic Day
  '2026-03-03', // Holi
  '2026-03-26', // Shri Ram Navami
  '2026-03-31', // Shri Mahavir Jayanti
  '2026-04-03', // Good Friday
  '2026-04-14', // Dr. Ambedkar Jayanti
  '2026-05-01', // Maharashtra Day
  '2026-05-28', // Bakri Id (Eid ul-Adha)
  '2026-06-26', // Muharram
  // 2026-08-26 was listed here as Janmashtami and is NOT a holiday: the
  // exchange traded it. The collector asks the live NSE trade calendar and
  // collected a full session — 312 snapshots, spot moving across 290 distinct
  // values, ATM call OI 24.4L → 87.8L, volume to 9.97Cr. A wrong entry here is
  // expensive out of all proportion to one line: getLatestTradingSessionDate
  // falls back a day, so the whole workspace replays the PREVIOUS session, and
  // every OI view is then handed history for an expiry that has since expired.
  // Verify against the exchange calendar before adding a projected date.
  '2026-09-14', // Ganesh Chaturthi
  '2026-10-02', // Mahatma Gandhi Jayanti
  '2026-10-20', // Dussehra
  '2026-11-10', // Diwali (Balipratipada)
  '2026-11-24', // Guru Nanak Jayanti
  '2026-12-25', // Christmas

  // 2027 Holidays (Provisional/Projected)
  '2027-01-26', // Republic Day
  '2027-03-08', // Maha Shivaratri
  '2027-03-22', // Holi
  '2027-04-14', // Dr. Ambedkar Jayanti
  '2027-04-16', // Ram Navami
  '2027-04-20', // Mahavir Jayanti
  '2027-08-15', // Independence Day
  '2027-09-05', // Ganesh Chaturthi
  '2027-10-02', // Mahatma Gandhi Jayanti
  '2027-10-18', // Dussehra
  '2027-10-29', // Diwali
  '2027-12-25', // Christmas
]);

/**
 * Check if a given dateKey (YYYY-MM-DD in IST) is an NSE holiday.
 */
function isMarketHoliday(dateKey: string): boolean {
  // After the mapped horizon (post-2027) we cannot positively identify exchange
  // holidays, so this returns false for unknown years. That is acceptable ONLY
  // because every caller (getPreviousTradingDay / isMarketSessionTime) still
  // performs its own weekend skip independently — so weekends are never treated
  // as trading days even past the horizon. The remaining gap is unmapped public
  // holidays after 2027; update NSE_HOLIDAYS annually to close it. (API-6)
  const year = Number(dateKey.slice(0, 4));
  if (Number.isFinite(year) && year > 2027) {
    console.warn(
      `marketSession.ts: NSE holidays are unmapped for ${year} (post-2027). ` +
      'Weekends are still skipped, but exchange holidays will be treated as trading days. Update NSE_HOLIDAYS.'
    );
  }
  return NSE_HOLIDAYS.has(dateKey);
}

/**
 * Returns the date `daysBack` trading days ago, skipping weekends and holidays.
 */
export function getPreviousTradingDay(daysBack: number, fromDate: Date = new Date()): Date {
  let currentMs = fromDate.getTime();
  let daysCounted = 0;
  // Limit to avoid infinite loop just in case
  let iterations = 0;
  while (daysCounted < daysBack && iterations < 100) {
    currentMs -= 86400_000;
    const parts = marketParts(currentMs);
    const isWeekend = parts.weekday === 0 || parts.weekday === 6;
    if (!isWeekend && !isMarketHoliday(parts.dateKey)) {
      daysCounted++;
    }
    iterations++;
  }
  return new Date(currentMs);
}

export function isMarketSessionTime(time: number | Date): boolean {
  const parts = marketParts(time);
  const isWeekend = parts.weekday === 0 || parts.weekday === 6;
  const isHoliday = NSE_HOLIDAYS.has(parts.dateKey);
  const closeMinute = marketCloseMinuteFor(time);
  return !isWeekend && !isHoliday && parts.minuteOfDay >= MARKET_OPEN_MINUTE && parts.minuteOfDay <= closeMinute;
}

/** The historically correct option-market close for the supplied IST date. */
export function marketCloseMinuteFor(time: number | Date): number {
  return marketParts(time).dateKey >= CAS_EFFECTIVE_DATE
    ? DERIVATIVES_CLOSE_MINUTE
    : LEGACY_MARKET_CLOSE_MINUTE;
}

/**
 * The option session's open and close, as epoch ms, on the IST date of `time`:
 * 09:15 to the derivatives close that applied that day (15:40 from 3 Aug 2026,
 * 15:30 before it). What an intraday chart's time axis spans, so a session in
 * progress keeps its unspent hours on the axis instead of being stretched
 * across it.
 */
export function marketSessionBounds(time: number | Date): { open: number; close: number } {
  const midnight = Date.parse(`${marketParts(time).dateKey}T00:00:00+05:30`);
  return {
    open: midnight + MARKET_OPEN_MINUTE * 60_000,
    close: midnight + marketCloseMinuteFor(time) * 60_000,
  };
}

/**
 * Has this expiry already settled?
 *
 * An expiry lives until the derivatives close ON its own date — 15:40 from
 * 3 Aug 2026, 15:30 before it. `expiry >= todayIST` is NOT that test: it keeps
 * the expiring series selected for the rest of the evening, and every figure
 * derived from it degenerates. Observed on Tue 25 Aug 2026 at 17:39 IST with
 * NIFTY still pinned to the 25 Aug series: T clamped to MIN_TIME_YEARS (one
 * minute), so Delta collapsed to a step function (1.00 / 0.39 / 0.00 / −1.00),
 * Theta printed −16815/day, and the IV solve pinned at its 200% cap. None of
 * that is a pricing bug — it is arithmetic on a contract that no longer exists.
 *
 * Date-only comparisons are correct for every OTHER expiry; only the one dated
 * today needs the clock. Callers filtering an expiry ladder should use
 * `filterLiveExpiries`.
 */
export function isExpirySettled(expiry: string, time: number | Date = Date.now()): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(expiry)) return false;
  const parts = marketParts(time);
  if (expiry < parts.dateKey) return true;
  if (expiry > parts.dateKey) return false;
  // Expiring today: settled once its own date's derivatives close has passed.
  return parts.minuteOfDay > marketCloseMinuteFor(time);
}

/**
 * The expiry ladder with settled series removed, de-duplicated and sorted
 * ascending — the order every caller assumes.
 */
export function filterLiveExpiries(expiries: string[], time: number | Date = Date.now()): string[] {
  return Array.from(new Set(expiries))
    .filter(expiry => /^\d{4}-\d{2}-\d{2}$/.test(expiry) && !isExpirySettled(expiry, time))
    .sort((a, b) => a.localeCompare(b));
}

/**
 * A trader-facing session phase for the option chain. CAS phases only exist
 * from their regulatory effective date; older sessions retain the 15:30 close.
 */
export function getMarketPhase(time: number | Date): MarketPhase {
  const parts = marketParts(time);
  if (!isTradingDay(time)) return 'closed';
  if (parts.minuteOfDay < MARKET_OPEN_MINUTE) return 'pre-open';

  const casApplies = parts.dateKey >= CAS_EFFECTIVE_DATE;
  if (!casApplies) {
    return parts.minuteOfDay <= LEGACY_MARKET_CLOSE_MINUTE ? 'continuous' : 'closed';
  }
  if (parts.minuteOfDay < CAS_START_MINUTE) return 'continuous';
  if (parts.minuteOfDay < CAS_END_MINUTE) return 'closing-auction';
  if (parts.minuteOfDay <= DERIVATIVES_CLOSE_MINUTE) return 'derivatives-close';
  return 'closed';
}

/**
 * Whether the given instant falls on an NSE trading day (weekday, non-holiday),
 * ignoring the time of day. Holiday-aware via NSE_HOLIDAYS (see caveat in
 * isMarketHoliday for post-2027 dates).
 */
export function isTradingDay(time: number | Date): boolean {
  const parts = marketParts(time);
  const isWeekend = parts.weekday === 0 || parts.weekday === 6;
  return !isWeekend && !NSE_HOLIDAYS.has(parts.dateKey);
}

const SESSION_DAY_FORMAT = new Intl.DateTimeFormat('en-CA', { timeZone: MARKET_TIME_ZONE });
let latestSessionMemo: { minute: number; date: string } | null = null;

/**
 * Returns the most recent trading day date string (YYYY-MM-DD in IST).
 * If today is a holiday, weekend, or before market open, it returns the previous trading day.
 */
export function getLatestTradingSessionDate(fromDate: Date = new Date()): string {
  // The answer changes only on a minute boundary (the open, or a new day), so
  // one reading per minute serves every caller in it: scanner redraws ask
  // hundreds of times a second (27 Sep: 0.9 s of one scan).
  const minute = Math.floor(fromDate.getTime() / 60_000);
  if (latestSessionMemo && latestSessionMemo.minute === minute) return latestSessionMemo.date;
  const parts = marketParts(fromDate);
  const date = !isTradingDay(fromDate) || parts.minuteOfDay < MARKET_OPEN_MINUTE
    ? SESSION_DAY_FORMAT.format(getPreviousTradingDay(1, fromDate))
    : parts.dateKey;
  if (Number.isFinite(minute)) latestSessionMemo = { minute, date };
  return date;
}

/**
 * Sessions remaining until an expiry, counted on the exchange calendar.
 *
 * ── Why this exists ────────────────────────────────────────────────────────
 *
 * Time to expiry is a CALENDAR quantity — an option decays over weekends — and
 * `fractionalYearsToExpiry` is rightly ACT/365. A realized-volatility window is
 * a TRADING quantity: the estimators slice daily bars, and a bar is a session.
 * The two are different clocks, and the volatility page was mixing them.
 *
 * It computed `dte = timeYears * 365`, a count of calendar days, and handed it
 * to `nearestHorizon`, whose horizons are trading-day windows. So a 7-day
 * option was matched against a 7-SESSION window spanning about 9.6 calendar
 * days — a 37% overshoot — and the card printed "against 7-day realized,
 * matched to 7 days to expiry", two different sevens in one sentence. The same
 * calendar figure positioned the implied mark on a trading-day axis, placing it
 * roughly 1.45x too far left, against a shorter and wider band than its own
 * tenor. That biases the reading toward "implied looks high", which is the very
 * conclusion the card exists to support, so the error is self-confirming.
 *
 * Counted, not approximated, because the approximation is what caused this:
 * the exchange calendar is the only thing that knows a Muhurat session trades
 * and a Thursday holiday does not.
 *
 * Returns a fractional count: the part of today still to come is worth the
 * fraction of the session that remains, so the figure moves continuously
 * through the day rather than stepping at midnight.
 */
export function tradingDaysUntil(expiry: string | number | Date, asOf: number | Date = Date.now()): number | null {
  const asOfMs = typeof asOf === 'number' ? asOf : asOf.getTime();
  const endMs = typeof expiry === 'string'
    ? new Date(`${expiry}T00:00:00+05:30`).getTime()
    : typeof expiry === 'number' ? expiry : expiry.getTime();
  if (!Number.isFinite(asOfMs) || !Number.isFinite(endMs)) return null;

  const expiryKey = marketParts(endMs).dateKey;
  const startParts = marketParts(asOfMs);
  if (startParts.dateKey > expiryKey) return 0;

  // Today contributes the unspent fraction of its own session.
  let sessions = 0;
  if (isTradingDay(asOfMs)) sessions += Math.max(0, 1 - marketSessionProgress(asOfMs));

  // Then every whole session strictly after today, up to and including expiry.
  // Bounded rather than open-ended: a malformed expiry must not spin.
  const DAY_MS = 86_400_000;
  const MAX_LOOKAHEAD_DAYS = 400;
  for (let i = 1; i <= MAX_LOOKAHEAD_DAYS; i += 1) {
    const cursor = asOfMs + i * DAY_MS;
    const parts = marketParts(cursor);
    if (parts.dateKey > expiryKey) break;
    if (isTradingDay(cursor)) sessions += 1;
  }
  return sessions;
}

export function marketSessionProgress(time: number | Date): number {
  const minute = marketParts(time).minuteOfDay;
  const closeMinute = marketCloseMinuteFor(time);
  const clamped = Math.min(closeMinute, Math.max(MARKET_OPEN_MINUTE, minute));
  return (clamped - MARKET_OPEN_MINUTE) / (closeMinute - MARKET_OPEN_MINUTE);
}

const MARKET_CLOCK_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: MARKET_TIME_ZONE,
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
});

export function formatMarketClockTime(time: number | Date): string {
  const formatted = MARKET_CLOCK_FORMAT.format(typeof time === 'number' ? new Date(time) : time);
  return formatted.replace(/\s?(am|pm)$/i, match => ` ${match.trim().toUpperCase()}`);
}
