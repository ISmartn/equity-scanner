/** Local calendar date as YYYY-MM-DD (avoids UTC shift from toISOString). */
export function localTodayIso(): string {
  return new Date().toLocaleDateString("en-CA");
}

export function isWeekend(isoDate: string): boolean {
  const day = new Date(`${isoDate}T12:00:00`).getDay();
  return day === 0 || day === 6;
}

/** Snap Saturday/Sunday to the nearest weekday (default: previous Friday). */
export function nearestWeekday(
  isoDate: string,
  prefer: "backward" | "forward" = "backward",
): string {
  if (!isWeekend(isoDate)) return isoDate;
  const d = new Date(`${isoDate}T12:00:00`);
  const day = d.getDay();
  if (day === 6) {
    d.setDate(d.getDate() - 1);
  } else if (prefer === "forward") {
    d.setDate(d.getDate() + 1);
  } else {
    d.setDate(d.getDate() - 2);
  }
  return d.toLocaleDateString("en-CA");
}

/** Move by N weekdays (skips Saturday and Sunday). */
export function stepWeekday(isoDate: string, delta: number): string {
  if (!delta) return isoDate;
  const d = new Date(`${isoDate}T12:00:00`);
  const step = delta > 0 ? 1 : -1;
  let remaining = Math.abs(delta);
  while (remaining > 0) {
    d.setDate(d.getDate() + step);
    const iso = d.toLocaleDateString("en-CA");
    if (!isWeekend(iso)) {
      remaining -= 1;
    }
  }
  return d.toLocaleDateString("en-CA");
}

export function clampWeekday(
  isoDate: string,
  minDate?: string | null,
  maxDate?: string | null,
): string {
  let next = nearestWeekday(isoDate);
  if (minDate && next < minDate) next = nearestWeekday(minDate, "forward");
  if (maxDate && next > maxDate) next = nearestWeekday(maxDate, "backward");
  return next;
}

export function isoMonthFromDate(isoDate: string): string {
  return isoDate.slice(0, 7);
}

export function addCalendarMonths(isoMonth: string, delta: number): string {
  const [year, month] = isoMonth.split("-").map(Number);
  const next = new Date(year, month - 1 + delta, 1, 12);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
}

export function formatMonthLabel(isoMonth: string): string {
  const [year, month] = isoMonth.split("-").map(Number);
  return new Date(year, month - 1, 1, 12).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

export interface CalendarMonthCell {
  iso: string;
  inMonth: boolean;
}

/** Monday-first month grid (42 cells). */
export function calendarMonthCells(isoMonth: string): CalendarMonthCell[] {
  const [year, month] = isoMonth.split("-").map(Number);
  const first = new Date(year, month - 1, 1, 12);
  const daysInMonth = new Date(year, month, 0, 12).getDate();
  const leading = (first.getDay() + 6) % 7;
  const cells: CalendarMonthCell[] = [];

  for (let i = leading - 1; i >= 0; i -= 1) {
    const d = new Date(year, month - 1, 1 - (i + 1), 12);
    cells.push({ iso: d.toLocaleDateString("en-CA"), inMonth: false });
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const d = new Date(year, month - 1, day, 12);
    cells.push({ iso: d.toLocaleDateString("en-CA"), inMonth: true });
  }
  while (cells.length < 42) {
    const d = new Date(year, month - 1, daysInMonth + (cells.length - leading - daysInMonth + 1), 12);
    cells.push({ iso: d.toLocaleDateString("en-CA"), inMonth: false });
  }
  return cells;
}

export function isDateSelectable(
  isoDate: string,
  minDate?: string | null,
  maxDate?: string | null,
): boolean {
  if (isWeekend(isoDate)) return false;
  if (minDate && isoDate < minDate) return false;
  if (maxDate && isoDate > maxDate) return false;
  return true;
}
