/**
 * The ONE place days-to-expiry is counted for every expiry control in the app.
 * Calendar days from the tape's own IST date (`asOf`) to the expiry. Never the
 * device clock: a replayed historical tape must read the same on any machine.
 * No `asOf` gives null (shown as an em dash).
 */
import { marketCloseMinuteFor } from '../../lib/marketSession';

// One formatter each, made once: toLocaleDateString builds a new one per call,
// and a scanner redraw calls this for every row (27 Sep: 3.7 s of one scan).
const LABEL = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' });
const DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' });
const labels = new Map<string, string>();

export function expiryDisplay(expiry: string, asOf?: number | null) {
  // Expiry close from the shared session helper (15:40 since 2026-08-03), never a literal.
  const noon = new Date(expiry + 'T12:00:00+05:30');
  const closeMin = Number.isFinite(noon.getTime()) ? marketCloseMinuteFor(noon) : 0;
  const date = Number.isFinite(noon.getTime()) ? new Date(noon.getTime() + (closeMin - 720) * 60000) : noon;
  if (!expiry || !Number.isFinite(date.getTime())) return { label: expiry || '—', days: null };
  let label = labels.get(expiry);
  if (label === undefined) { label = LABEL.format(date); if (labels.size < 500) labels.set(expiry, label); }
  const tape = asOf && Number.isFinite(asOf) ? (asOf < 1e12 ? asOf * 1000 : asOf) : null;
  const stamp = tape == null ? null : new Date(tape);
  const parts = stamp ? DAY.format(stamp) : undefined;
  const days = parts ? Math.max(0, Math.round((Date.parse(expiry) - Date.parse(parts)) / 86400000)) : null;
  return { label, days };
}
