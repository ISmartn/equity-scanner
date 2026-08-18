import type { ScannerPatternId, ScannerPatternSignal } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/timelineExport";

export const SCANNER_PATTERN_LABELS: Record<ScannerPatternId, string> = {
  vcp: "VCP",
  high_tight_flag: "High Tight Flag",
  pocket_pivot: "Pocket Pivot",
  pocket_pivot_setup: "Pocket Pivot Setup",
  inside_bar_cluster: "Inside Bar Cluster",
  power_gap: "Power Gap",
  tight_range_near_pivot: "Tight Range Near Pivot",
  darvas_pre_setup: "Darvas Pre-Setup",
};

export type ScannerSignalStatus = "trigger" | "setup" | "structure";
export type TimingClass = "early" | "confirmation" | "extended";

export const EARLY_SETUP_PATTERNS: ScannerPatternId[] = [
  "vcp",
  "inside_bar_cluster",
  "high_tight_flag",
  "pocket_pivot_setup",
  "tight_range_near_pivot",
  "darvas_pre_setup",
];

export function signalStatus(row: ScannerPatternSignal): ScannerSignalStatus {
  if (row.triggered_today) return "trigger";
  if (row.setup_ready) return "setup";
  return "structure";
}

export function timingClassFromRow(row: ScannerPatternSignal): TimingClass | null {
  const value = row.details?.timing_class;
  return value === "early" || value === "confirmation" || value === "extended" ? value : null;
}

export function pre20dReturnFromRow(row: ScannerPatternSignal): number | null {
  const value = row.details?.pre_20d_return_pct;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function timingClassLabel(timing: TimingClass): string {
  switch (timing) {
    case "early":
      return "Setup";
    case "extended":
      return "Extended";
    case "confirmation":
      return "Triggered";
  }
}

export function fundamentalPassFromRow(row: ScannerPatternSignal): boolean | null {
  return readFundamentalPass(row.details ?? {});
}

export type FoOverlayTone = "confirm" | "caution" | "neutral" | "na";

export function foOverlayTone(row: ScannerPatternSignal): FoOverlayTone {
  const fo = row.details?.fo_overlay as Record<string, unknown> | undefined;
  if (!fo || fo.available !== true) return "na";
  const quadrant = fo.quadrant as string | undefined;
  if (quadrant === "long_buildup") return "confirm";
  if (quadrant === "short_covering") return "caution";
  if (quadrant === "short_buildup") return "caution";
  return "neutral";
}

export function foOverlayLabel(row: ScannerPatternSignal): string | null {
  const fo = row.details?.fo_overlay as Record<string, unknown> | undefined;
  if (!fo || fo.available !== true) return null;
  const label = fo.quadrant_label;
  return typeof label === "string" ? label : null;
}

export function compositeScoreFromRow(row: ScannerPatternSignal): number | null {
  const composite = row.details?.composite_score;
  return typeof composite === "number" ? composite : null;
}

/** Day move on the signal bar: prev-close return if available, else open→close. */
export function signalDayMovePct(row: ScannerPatternSignal): number | null {
  if (row.daily_return_pct != null && Number.isFinite(row.daily_return_pct)) {
    return row.daily_return_pct;
  }
  if (row.open != null && row.close != null && row.open !== 0) {
    return ((row.close - row.open) / row.open) * 100;
  }
  return null;
}

export function formatSignalMovePct(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

const STATUS_LABELS: Record<ScannerSignalStatus, string> = {
  trigger: "Trigger",
  setup: "Setup",
  structure: "Structure",
};

export function statusLabel(status: ScannerSignalStatus): string {
  return STATUS_LABELS[status];
}

export interface ScannerExportRow {
  date: string;
  ticker: string;
  pattern: string;
  score: number;
  pattern_score: number | null;
  macro_pass: boolean;
  fundamental_pass: boolean | null;
  status: "trigger" | "setup" | "structure";
  why: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  details: Record<string, unknown>;
}

function readFundamentalPass(details: Record<string, unknown>): boolean | null {
  const fund = details.fundamental;
  if (!fund || typeof fund !== "object") return null;
  const pass = (fund as Record<string, unknown>).pass;
  return typeof pass === "boolean" ? pass : null;
}

export function describeScannerWhy(row: ScannerPatternSignal): string {
  const d = row.details ?? {};
  const parts: string[] = [];

  if (row.macro_pass && d.trend) {
    parts.push("Passes Minervini trend template (price > SMA50 > SMA150 > SMA200)");
  } else if (!row.macro_pass) {
    parts.push("Macro trend template not met");
  }

  if (row.triggered_today) {
    parts.push(`Trigger fired on ${row.trade_date}`);
  } else if (row.setup_ready) {
    parts.push("Setup forming — breakout not confirmed yet");
  }

  const fund = d.fundamental as Record<string, unknown> | undefined;
  if (fund?.available === true) {
    if (fund.pass === true) {
      const roe = fund.roe != null ? `ROE ${fund.roe}%` : null;
      const roce = fund.roce != null ? `ROCE ${fund.roce}%` : null;
      parts.push(`Fundamentals pass (${[roe, roce].filter(Boolean).join(", ") || "quality gate"})`);
    } else if (fund.pass === false) {
      parts.push("Fundamentals below ROE/ROCE thresholds");
    }
  }

  const market = d.market as Record<string, unknown> | undefined;
  const contextAdj = d.context_adjustment;
  if (typeof contextAdj === "number" && contextAdj !== 0) {
    parts.push(`Context overlay ${contextAdj > 0 ? "+" : ""}${contextAdj} pts (fundamentals/market)`);
  } else if (market?.available === true && market.score_delta != null && market.score_delta !== 0) {
    parts.push(`Market context ${Number(market.score_delta) > 0 ? "+" : ""}${market.score_delta} pts`);
  }
  if (market?.nifty_pcr != null) {
    parts.push(`NIFTY PCR ${market.nifty_pcr}`);
  }

  const fo = d.fo_overlay as Record<string, unknown> | undefined;
  if (fo?.available === true) {
    if (fo.quadrant_label) parts.push(`F&O: ${fo.quadrant_label}`);
    if (fo.oi_change_pct != null) parts.push(`Option OI Δ ${fo.oi_change_pct}%`);
    if (fo.pcr_change_pct != null) parts.push(`PCR Δ ${fo.pcr_change_pct}%`);
    const mult = d.fo_multiplier;
    if (typeof mult === "number" && mult !== 1) {
      parts.push(`F&O multiplier ×${mult.toFixed(2)}`);
    }
    const composite = d.composite_score;
    if (typeof mult === "number" && mult !== 1 && typeof composite === "number") {
      parts.push(`Composite score ${composite}`);
    }
  } else if (fo?.reason === "no_derivative_snapshot") {
    parts.push("F&O overlay pending — fetching derivative data when available");
  }
  if (fo?.would_reject === true) {
    parts.push("F&O structure would reject this signal (short build-up)");
  }

  switch (row.pattern_type) {
    case "vcp":
      if (d.stage) parts.push(`VCP stage: ${d.stage}`);
      if (d.breakout === true) parts.push("Breakout above 10-day pivot");
      if (d.volume_dry != null) parts.push(d.volume_dry ? "Volume drying up" : "Volume not yet dry");
      if (d.range_5d_pct != null) parts.push(`5d range ${d.range_5d_pct}%`);
      break;
    case "high_tight_flag":
      if (d.flagpole_pct != null) parts.push(`Flagpole +${d.flagpole_pct}%`);
      if (d.flag_depth_pct != null) parts.push(`Flag depth ${d.flag_depth_pct}%`);
      break;
    case "pocket_pivot":
      if (d.in_base != null) parts.push(d.in_base ? "In base near 52w high" : "Outside base context");
      if (d.volume_ratio != null) parts.push(`Volume ${d.volume_ratio}× max down-day vol`);
      if (d.volume_zscore != null) parts.push(`Volume z-score ${d.volume_zscore}`);
      break;
    case "inside_bar_cluster":
      if (d.inside_bars != null) parts.push(`${d.inside_bars} inside bars after mother bar`);
      if (d.mother_date) parts.push(`Mother bar: ${d.mother_date}`);
      break;
    case "power_gap":
      parts.push("Power Gap (not earnings-confirmed)");
      if (d.gap_pct != null) parts.push(`Gap +${d.gap_pct}%`);
      if (d.volume_ratio != null) parts.push(`Volume ${d.volume_ratio}× 20d avg`);
      break;
  }

  return parts.join(". ") || SCANNER_PATTERN_LABELS[row.pattern_type];
}

export function scannerToExportRows(rows: ScannerPatternSignal[]): ScannerExportRow[] {
  return rows.map((row) => ({
    date: row.trade_date,
    ticker: row.ticker,
    pattern: SCANNER_PATTERN_LABELS[row.pattern_type],
    score: row.score,
    pattern_score:
      typeof row.details?.pattern_score === "number" ? row.details.pattern_score : null,
    macro_pass: row.macro_pass,
    fundamental_pass: readFundamentalPass(row.details ?? {}),
    status: signalStatus(row),
    why: describeScannerWhy(row),
    open: row.open ?? null,
    high: row.high ?? null,
    low: row.low ?? null,
    close: row.close ?? null,
    volume: row.volume ?? null,
    details: row.details,
  }));
}

export function scannerToExportJson(rows: ScannerPatternSignal[], pretty = true): string {
  const payload = scannerToExportRows(rows);
  return pretty ? JSON.stringify(payload, null, 2) : JSON.stringify(payload);
}

export { copyTextToClipboard };
