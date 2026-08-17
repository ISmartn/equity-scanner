import type { TimelineMoverRow } from "@/lib/api";

export interface TimelineMoverExportRow {
  date: string;
  ticker: string;
  open: number;
  close: number;
  percentage: number;
  volume: number;
}

export function moversToExportRows(rows: TimelineMoverRow[]): TimelineMoverExportRow[] {
  return rows.map((row) => ({
    date: row.trade_date,
    ticker: row.ticker,
    open: row.open_price ?? 0,
    close: row.close_price ?? 0,
    percentage: row.daily_return_pct ?? 0,
    volume: row.volume ?? 0,
  }));
}

export function moversToExportJson(rows: TimelineMoverRow[], pretty = true): string {
  const payload = moversToExportRows(rows);
  return pretty ? JSON.stringify(payload, null, 2) : JSON.stringify(payload);
}

export async function copyTextToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}
