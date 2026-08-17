import type { StockFundamentals } from "@/lib/api";

function unwrapSection(section: unknown): unknown {
  if (!section || typeof section !== "object") return section;
  const obj = section as Record<string, unknown>;
  if ("data" in obj) return obj.data;
  return section;
}

function formatCapValue(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "object" && value !== null) {
    const row = value as Record<string, unknown>;
    if (typeof row.formatted === "string" && row.formatted.trim()) {
      return row.formatted.trim();
    }
    if (row.value != null && row.unit != null) {
      return `${row.value} ${row.unit}`;
    }
  }
  return null;
}

export function extractProfileSector(profile: StockFundamentals["profile"]): string | null {
  const p = unwrapSection(profile);
  if (!p || typeof p !== "object") return null;
  const sector = (p as Record<string, unknown>).sector;
  return typeof sector === "string" && sector.trim() ? sector.trim() : null;
}

/** Upstox profile exposes sector aggregate mcap (sector_market_cap_inr). */
export function extractProfileMarketCap(profile: StockFundamentals["profile"]): string | null {
  const p = unwrapSection(profile);
  if (!p || typeof p !== "object") return null;
  const row = p as Record<string, unknown>;
  return formatCapValue(row.sector_market_cap_inr) ?? formatCapValue(row.sector_market_cap_usd);
}
