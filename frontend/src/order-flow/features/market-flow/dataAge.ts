import { getLatestTradingSessionDate, marketParts } from '@/order-flow/lib/marketSession';

/**
 * How old the board's market reading is, in words the page can print.
 *
 * `aged` is true when the reading is not from the latest trading session: the
 * page then says so beside the time, rather than letting an old board pass for
 * today's. A reading from the latest session is never aged, even after the
 * close: the board then describes that session's end.
 */
export interface FlowDataAge {
  aged: boolean;
  /** The session date of the reading, YYYY-MM-DD in IST. */
  date: string;
}

export function describeDataAge(readingAt: number, now: number = Date.now()): FlowDataAge {
  const date = marketParts(readingAt).dateKey;
  return { aged: date < getLatestTradingSessionDate(new Date(now)), date };
}
