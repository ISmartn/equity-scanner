import { BarChart3, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { StockFundamentals } from "@/lib/api";

interface StockFundamentalsPanelProps {
  data: StockFundamentals | null;
  loading?: boolean;
  error?: string | null;
  syncing?: boolean;
  onSync?: () => void;
  compact?: boolean;
  /** Fill parent column height (timeline / scanner right rail). */
  sidebar?: boolean;
}

type TabId = "overview" | "financials" | "actions" | "peers";

type KeyRatioRow = { name: string; company: string; sector: string };
type HoldingRow = { category: string; pct: string };
type ActionRow = { name: string; date: string; detail: string };
type PeerRow = { name: string; sector: string; instrumentKey: string };
type HistoryRow = { period: string; values: Record<string, string> };

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "financials", label: "Financials" },
  { id: "actions", label: "Actions" },
  { id: "peers", label: "Peers" },
];

function parseNumeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const n = Number.parseFloat(value.replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return parseNumeric(obj.value ?? obj.amount);
  }
  return null;
}

function formatValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (Math.abs(value) >= 1e7) return `${(value / 1e7).toFixed(2)} Cr`;
    if (Math.abs(value) >= 1e5) return `${(value / 1e5).toFixed(2)} L`;
    return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    if (typeof obj.formatted === "string" && obj.formatted.trim()) {
      return obj.formatted;
    }
    const num = obj.amount ?? obj.value;
    if (num != null) {
      const unit = obj.unit ?? "";
      return `${formatValue(num)}${unit ? ` ${String(unit)}` : ""}`;
    }
  }
  return String(value);
}

function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") return [value];
  return [];
}

function unwrapSection(section: unknown): unknown {
  if (!section || typeof section !== "object") return section;
  const obj = section as Record<string, unknown>;
  if ("data" in obj) return obj.data;
  return section;
}

function extractProfileText(profile: StockFundamentals["profile"]): string | null {
  const p = unwrapSection(profile);
  if (!p || typeof p !== "object") return null;
  const row = p as Record<string, unknown>;
  const desc = row.company_profile ?? row.description;
  return typeof desc === "string" && desc.trim() ? desc.trim() : null;
}

function extractSector(profile: StockFundamentals["profile"]): string | null {
  const p = unwrapSection(profile);
  if (!p || typeof p !== "object") return null;
  const sector = (p as Record<string, unknown>).sector;
  return typeof sector === "string" && sector.trim() ? sector.trim() : null;
}

function extractMarketCap(profile: StockFundamentals["profile"]): string | null {
  const p = unwrapSection(profile);
  if (!p || typeof p !== "object") return null;
  const row = p as Record<string, unknown>;
  const inr = row.sector_market_cap_inr;
  if (inr) return formatValue(inr);
  return null;
}

function extractKeyRatios(keyRatios: StockFundamentals["key_ratios"]): KeyRatioRow[] {
  const raw = unwrapSection(keyRatios);
  const items = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && "ratios" in (raw as object)
      ? (raw as { ratios: unknown }).ratios
      : null;
  if (!Array.isArray(items)) return [];

  return items
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const name = row.name ?? row.ratio_name;
      if (typeof name !== "string") return null;
      return {
        name,
        company: formatValue(row.company_value ?? row.value),
        sector: formatValue(row.sector_value ?? row.sector_avg),
      };
    })
    .filter((row): row is KeyRatioRow => row !== null);
}

function extractHoldings(shareHoldings: StockFundamentals["share_holdings"]): HoldingRow[] {
  const raw = unwrapSection(shareHoldings);
  const items = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && "holdings" in (raw as object)
      ? (raw as { holdings: unknown }).holdings
      : null;
  if (!Array.isArray(items)) return [];

  return items
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const category = row.category ?? row.name;
      if (typeof category !== "string") return null;
      const history = row.history;
      let pct: unknown = row.percentage ?? row.pct;
      if (Array.isArray(history) && history.length > 0) {
        const latest = history[history.length - 1] as Record<string, unknown>;
        pct = latest.percentage ?? latest.pct ?? latest.value ?? pct;
      }
      return { category, pct: formatValue(pct) };
    })
    .filter((row): row is HoldingRow => row !== null);
}

function extractCorporateActions(actions: StockFundamentals["corporate_actions"]): ActionRow[] {
  const raw = unwrapSection(actions);
  const items = Array.isArray(raw) ? raw : asArray(raw);
  return items
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const name = row.name ?? row.type;
      if (typeof name !== "string") return null;
      const parts = [
        row.amount != null ? formatValue(row.amount) : null,
        row.ratio != null ? `ratio ${formatValue(row.ratio)}` : null,
      ].filter(Boolean);
      return {
        name,
        date: formatValue(row.expiry_date ?? row.ex_date ?? row.date),
        detail: parts.join(" · ") || "—",
      };
    })
    .filter((row): row is ActionRow => row !== null);
}

function extractCompetitors(competitors: StockFundamentals["competitors"]): PeerRow[] {
  const raw = unwrapSection(competitors);
  const items = Array.isArray(raw) ? raw : asArray(raw);
  return items
    .map((item, idx) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const profile = row.company_profile;
      const name =
        typeof profile === "string"
          ? profile.split(".")[0]?.slice(0, 40) ?? profile
          : typeof row.name === "string"
            ? row.name
            : `Peer ${idx + 1}`;
      const sector = typeof row.sector === "string" ? row.sector : "—";
      const instrumentKey =
        typeof row.instrument_key === "string" ? row.instrument_key.split("|").pop() ?? row.instrument_key : "—";
      return { name, sector, instrumentKey };
    })
    .filter((row): row is PeerRow => row !== null);
}

function extractSimpleHistory(section: unknown, valueKeys: string[]): HistoryRow[] {
  const raw = unwrapSection(section);
  if (!raw || typeof raw !== "object") return [];
  const obj = raw as Record<string, unknown>;
  const history = obj.history;
  if (!Array.isArray(history)) return [];

  return history
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const period = formatValue(row.period ?? row.date ?? row.year);
      const values: Record<string, string> = {};
      for (const key of valueKeys) {
        if (row[key] != null) values[key] = formatValue(row[key]);
      }
      if (Object.keys(values).length === 0) {
        for (const [k, v] of Object.entries(row)) {
          if (k !== "period" && k !== "date" && k !== "year" && v != null) {
            values[k] = formatValue(v);
          }
        }
      }
      return { period, values };
    })
    .filter((row): row is HistoryRow => row !== null);
}

function unwrapFinancialCategories(section: unknown, nestedKey: string): unknown[] {
  const raw = unwrapSection(section);
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const nested = obj[nestedKey];
    if (Array.isArray(nested)) return nested;
  }
  return asArray(raw);
}

function extractCategoryHistory(
  section: unknown,
  nestedKey?: string,
): { category: string; rows: HistoryRow[] }[] {
  const raw = unwrapSection(section);
  const items = nestedKey
    ? unwrapFinancialCategories(section, nestedKey)
    : Array.isArray(raw)
      ? raw
      : asArray(raw);
  return items
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const category = row.category ?? row.name;
      if (typeof category !== "string") return null;
      const history = row.history;
      if (!Array.isArray(history)) return null;
      const rows = history
        .map((h) => {
          if (!h || typeof h !== "object") return null;
          const entry = h as Record<string, unknown>;
          const period = formatValue(entry.period ?? entry.date ?? entry.year);
          const values: Record<string, string> = {};
          if (entry.value != null) values.value = formatValue(entry.value);
          if (entry.amount != null) values.amount = formatValue(entry.amount);
          return { period, values };
        })
        .filter((r): r is HistoryRow => r !== null);
      return rows.length ? { category, rows } : null;
    })
    .filter((g): g is { category: string; rows: HistoryRow[] } => g !== null);
}

function formatUpdatedAt(iso: string | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

type ChartPoint = { label: string; value: number };

type ChartSeries = { key: string; label: string; color: string; points: ChartPoint[] };

function historyRowsToSeries(
  rows: HistoryRow[],
  keys: { key: string; label: string; color: string }[],
): ChartSeries[] {
  return keys
    .map(({ key, label, color }) => {
      const points = rows
        .map((row) => {
          const value = parseNumeric(row.values[key]);
          if (value == null) return null;
          return { label: row.period, value };
        })
        .filter((p): p is ChartPoint => p !== null);
      return points.length ? { key, label, color, points } : null;
    })
    .filter((s): s is ChartSeries => s !== null);
}

function categoryRowsToSeries(rows: HistoryRow[]): ChartPoint[] {
  return rows
    .map((row) => {
      const raw = row.values.value ?? row.values.amount ?? Object.values(row.values)[0];
      const value = parseNumeric(raw);
      if (value == null) return null;
      return { label: row.period, value };
    })
    .filter((p): p is ChartPoint => p !== null);
}

type ChartLayout = "vertical-bars" | "horizontal-bars";

function pickChartLayout(labelCount: number, seriesCount: number): ChartLayout {
  if (labelCount > 4 || (labelCount > 3 && seriesCount > 1)) {
    return "horizontal-bars";
  }
  return "vertical-bars";
}

function shortPeriodLabel(label: string): string {
  return label.replace(/^Mar /, "'").replace(/^Q/, "Q").slice(0, 8);
}

/** Compact label for values already in crores (Upstox fundamentals). */
function formatChartValue(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 100000) return `${sign}${(abs / 100000).toFixed(1)}L`;
  if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(1)}K`;
  if (abs >= 100) return `${sign}${abs.toFixed(0)}`;
  if (abs >= 10) return `${sign}${abs.toFixed(1)}`;
  return `${sign}${abs.toFixed(2)}`;
}

function extractUnits(section: unknown): string {
  const raw = unwrapSection(section);
  if (raw && typeof raw === "object") {
    const u = (raw as Record<string, unknown>).units_in;
    if (typeof u === "string") {
      if (u.toLowerCase() === "crore") return "₹ Cr";
      return u;
    }
  }
  return "₹ Cr";
}

function ChartHeader({
  title,
  unitLabel,
  series,
}: {
  title: string;
  unitLabel?: string;
  series: ChartSeries[];
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1.5">
      <p className="text-xs font-semibold text-slate-300">
        {title}
        {unitLabel && <span className="ml-1 font-normal text-slate-500">({unitLabel})</span>}
      </p>
      {series.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5 text-[11px] text-slate-400">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function VerticalBarChartBody({
  series,
  labels,
  maxAbs,
  tall,
}: {
  series: ChartSeries[];
  labels: string[];
  maxAbs: number;
  tall?: boolean;
}) {
  const barAreaClass = tall ? "h-32" : "h-28";

  return (
    <div
      className="grid border-b border-slate-700/50 pb-2"
      style={{ gridTemplateColumns: `repeat(${labels.length}, minmax(0, 1fr))` }}
    >
      {labels.map((period) => (
        <div key={period} className="flex min-w-0 flex-col items-center px-0.5">
          <div className={`flex w-full items-end justify-center gap-1.5 ${barAreaClass}`}>
            {series.map((s) => {
              const point = s.points.find((p) => p.label === period);
              if (!point) {
                return <div key={s.key} className="flex-1" aria-hidden />;
              }
              const pct = Math.max((Math.abs(point.value) / maxAbs) * 100, 8);
              const color = point.value < 0 ? "#f87171" : s.color;
              return (
                <div
                  key={s.key}
                  className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5"
                  style={{ maxWidth: series.length > 1 ? "2.75rem" : "3.25rem" }}
                  title={`${s.label} · ${period}: ${formatValue(point.value)} Cr`}
                >
                  <span className="whitespace-nowrap text-[11px] font-semibold leading-none tabular-nums text-slate-200">
                    {formatChartValue(point.value)}
                  </span>
                  <div
                    className="w-full rounded-t-md"
                    style={{
                      height: `${pct}%`,
                      backgroundColor: color,
                      minHeight: 8,
                    }}
                  />
                </div>
              );
            })}
          </div>
          <span className="mt-2 whitespace-nowrap text-[11px] text-slate-500">
            {shortPeriodLabel(period)}
          </span>
        </div>
      ))}
    </div>
  );
}

function HorizontalBarChartBody({
  series,
  labels,
  maxAbs,
}: {
  series: ChartSeries[];
  labels: string[];
  maxAbs: number;
}) {
  return (
    <div className="space-y-2.5">
      {labels.map((period) => (
        <div key={period} className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-start gap-2">
          <span className="pt-0.5 text-right text-[11px] leading-tight text-slate-500">
            {shortPeriodLabel(period)}
          </span>
          <div className="space-y-1.5">
            {series.map((s) => {
              const point = s.points.find((p) => p.label === period);
              if (!point) return null;
              const pct = Math.max((Math.abs(point.value) / maxAbs) * 100, 2);
              const color = point.value < 0 ? "#f87171" : s.color;
              return (
                <div key={s.key} className="flex items-center gap-2">
                  {series.length > 1 && (
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: color }}
                      aria-hidden
                    />
                  )}
                  <div className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-800/80">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${pct}%`, backgroundColor: color, minWidth: 3 }}
                    />
                  </div>
                  <span className="w-14 shrink-0 text-right text-[11px] font-semibold tabular-nums text-slate-200">
                    {formatChartValue(point.value)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function FinancialBarChart({
  title,
  series,
  unitLabel,
  forceVertical = false,
  tall = false,
}: {
  title: string;
  series: ChartSeries[];
  unitLabel?: string;
  forceVertical?: boolean;
  tall?: boolean;
}) {
  if (!series.length) return null;

  const allPoints = series.flatMap((s) => s.points);
  const maxAbs = Math.max(...allPoints.map((p) => Math.abs(p.value)), 1);
  const labels = [...new Set(allPoints.map((p) => p.label))];
  const layout = forceVertical ? "vertical-bars" : pickChartLayout(labels.length, series.length);

  return (
    <div className="min-w-0">
      <ChartHeader title={title} unitLabel={unitLabel} series={series} />
      {layout === "horizontal-bars" ? (
        <HorizontalBarChartBody series={series} labels={labels} maxAbs={maxAbs} />
      ) : (
        <VerticalBarChartBody series={series} labels={labels} maxAbs={maxAbs} tall={tall} />
      )}
    </div>
  );
}

function FinancialChartCard({
  title,
  series,
  className = "",
  unitLabel,
  forceVertical,
  tall,
}: {
  title: string;
  series: ChartSeries[];
  className?: string;
  unitLabel?: string;
  forceVertical?: boolean;
  tall?: boolean;
}) {
  if (!series.length) return null;
  return (
    <div
      className={`min-w-0 rounded-lg border border-surface-border/50 bg-slate-900/40 p-3 ${className}`}
    >
      <FinancialBarChart
        title={title}
        series={series}
        unitLabel={unitLabel}
        forceVertical={forceVertical}
        tall={tall}
      />
    </div>
  );
}

function HistoryTable({
  title,
  rows,
  valueLabels,
}: {
  title: string;
  rows: HistoryRow[];
  valueLabels?: Record<string, string>;
}) {
  if (!rows.length) return null;
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r.values)))].slice(0, 4);
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">{title}</p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pr-2 pb-0.5">Period</th>
              {keys.map((k) => (
                <th key={k} className="pr-2 pb-0.5 tabular-nums">
                  {valueLabels?.[k] ?? k.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(-5).map((row) => (
              <tr key={row.period} className="text-slate-300">
                <td className="pr-2 py-0.5 text-slate-400">{row.period}</td>
                {keys.map((k) => (
                  <td key={k} className="pr-2 py-0.5 tabular-nums">
                    {row.values[k] ?? "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OverviewTab({ data }: { data: StockFundamentals }) {
  const profileText = extractProfileText(data.profile);
  const sector = extractSector(data.profile);
  const marketCap = extractMarketCap(data.profile);
  const ratios = extractKeyRatios(data.key_ratios);
  const holdings = extractHoldings(data.share_holdings);

  return (
    <div className="space-y-2">
      {(sector || marketCap) && (
        <div className="flex flex-wrap gap-x-3 text-xs text-slate-400">
          {sector && (
            <span>
              Sector: <span className="text-slate-300">{sector}</span>
            </span>
          )}
          {marketCap && (
            <span>
              Sector mcap: <span className="text-slate-300">{marketCap}</span>
            </span>
          )}
        </div>
      )}
      {profileText && (
        <p className="line-clamp-3 text-xs leading-relaxed text-slate-500">{profileText}</p>
      )}
      {ratios.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Key ratios
          </p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
            {ratios.map((row) => (
              <div key={row.name} className="text-xs">
                <span className="text-slate-500">{row.name}</span>
                <span className="ml-1 tabular-nums text-slate-200">{row.company}</span>
                {row.sector !== "—" && (
                  <span className="ml-0.5 text-slate-600">/ {row.sector}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {holdings.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Shareholding
          </p>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {holdings.map((row) => (
              <span key={row.category} className="text-xs text-slate-400">
                {row.category}:{" "}
                <span className="tabular-nums text-slate-300">{row.pct}%</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FinancialsTab({ data }: { data: StockFundamentals }) {
  const balanceHistory = extractSimpleHistory(data.balance_sheet, [
    "total_asset",
    "total_liability",
  ]);
  const incomeCategories = extractCategoryHistory(data.income_statement, "income_statement");
  const cashFlowCategories = extractCategoryHistory(data.cash_flow, "cash_flow");

  const balanceSeries = historyRowsToSeries(balanceHistory, [
    { key: "total_asset", label: "Assets", color: "#38bdf8" },
    { key: "total_liability", label: "Liabilities", color: "#f97316" },
  ]);

  const hasContent =
    balanceHistory.length > 0 || incomeCategories.length > 0 || cashFlowCategories.length > 0;

  if (!hasContent) {
    return <p className="text-xs text-slate-500">No financial statement data.</p>;
  }

  const incomeColors = ["#34d399", "#a78bfa", "#f472b6"];
  const cashFlowColors = ["#22d3ee", "#fb923c", "#94a3b8"];
  const unitLabel =
    extractUnits(data.balance_sheet) ||
    extractUnits(data.income_statement) ||
    extractUnits(data.cash_flow);

  const chartItems: {
    key: string;
    title: string;
    series: ChartSeries[];
    className?: string;
    forceVertical?: boolean;
    tall?: boolean;
  }[] = [];
  if (balanceSeries.length > 0) {
    chartItems.push({
      key: "balance",
      title: "Balance sheet trend",
      series: balanceSeries,
      forceVertical: true,
      tall: true,
      className: "col-span-full",
    });
  }
  for (const [idx, group] of incomeCategories.entries()) {
    const points = categoryRowsToSeries(group.rows);
    if (!points.length) continue;
    chartItems.push({
      key: `income-${group.category}`,
      title: `Income · ${group.category.replace(/_/g, " ")}`,
      series: [
        {
          key: group.category,
          label: group.category.replace(/_/g, " "),
          color: incomeColors[idx % incomeColors.length],
          points,
        },
      ],
    });
  }
  for (const [idx, group] of cashFlowCategories.entries()) {
    const points = categoryRowsToSeries(group.rows);
    if (!points.length) continue;
    chartItems.push({
      key: `cf-${group.category}`,
      title: `Cash flow · ${group.category.replace(/_/g, " ")}`,
      series: [
        {
          key: group.category,
          label: group.category.replace(/_/g, " "),
          color: cashFlowColors[idx % cashFlowColors.length],
          points,
        },
      ],
    });
  }

  return (
    <div className="space-y-3">
      {chartItems.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {chartItems.map((item) => (
            <FinancialChartCard
              key={item.key}
              title={item.title}
              series={item.series}
              unitLabel={unitLabel}
              forceVertical={item.forceVertical}
              tall={item.tall}
              className={item.className}
            />
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <HistoryTable
          title="Balance sheet (consolidated)"
          rows={balanceHistory}
          valueLabels={{
            total_asset: "Assets",
            total_liability: "Liabilities",
          }}
        />
        {incomeCategories.map((group) => (
          <HistoryTable
            key={group.category}
            title={`Income · ${group.category.replace(/_/g, " ")}`}
            rows={group.rows}
          />
        ))}
        {cashFlowCategories.map((group) => (
          <HistoryTable
            key={group.category}
            title={`Cash flow · ${group.category.replace(/_/g, " ")}`}
            rows={group.rows}
          />
        ))}
      </div>
    </div>
  );
}

function ActionsTab({ data }: { data: StockFundamentals }) {
  const actions = extractCorporateActions(data.corporate_actions);
  if (!actions.length) {
    return <p className="text-xs text-slate-500">No corporate actions on record.</p>;
  }
  return (
    <div className="space-y-1.5">
      {actions.slice(0, 12).map((row, idx) => (
        <div key={`${row.name}-${row.date}-${idx}`} className="flex gap-2 text-xs">
          <span className="shrink-0 text-slate-500">{row.date}</span>
          <span className="font-medium text-slate-300">{row.name}</span>
          <span className="truncate text-slate-500">{row.detail}</span>
        </div>
      ))}
    </div>
  );
}

function PeersTab({ data }: { data: StockFundamentals }) {
  const peers = extractCompetitors(data.competitors);
  if (!peers.length) {
    return <p className="text-xs text-slate-500">No competitor data.</p>;
  }
  return (
    <div className="space-y-1.5">
      {peers.map((peer) => (
        <div key={peer.instrumentKey} className="text-xs">
          <span className="font-medium text-slate-300">{peer.instrumentKey}</span>
          <span className="text-slate-500"> · {peer.sector}</span>
          {peer.name !== peer.instrumentKey && (
            <p className="line-clamp-1 text-slate-600">{peer.name}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export function StockFundamentalsPanel({
  data,
  loading,
  error,
  syncing,
  onSync,
  compact,
  sidebar,
}: StockFundamentalsPanelProps) {
  const [tab, setTab] = useState<TabId>("overview");

  if (!loading && !data && !error) return null;

  const heightClass = sidebar
    ? "min-h-0 flex-1"
    : tab === "financials"
      ? "max-h-96"
      : "max-h-72";

  return (
    <div
      className={`flex flex-col rounded-lg border border-surface-border bg-surface-raised/60 ${heightClass} ${
        sidebar ? "h-full shrink" : "shrink-0"
      } ${compact ? "px-2.5 py-2" : "px-3 py-2.5"}`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[13px] font-medium text-slate-200">
          <BarChart3 className="h-4 w-4 text-accent" />
          Fundamentals
          {data?.updated_at && (
            <span className="font-normal text-slate-500">· {formatUpdatedAt(data.updated_at)}</span>
          )}
        </div>
        {onSync && (
          <button
            type="button"
            onClick={onSync}
            disabled={syncing || loading}
            title="Refresh all fundamentals from Upstox"
            className="inline-flex items-center gap-1 rounded border border-surface-border px-2 py-0.5 text-xs text-slate-400 transition hover:border-accent/40 hover:text-slate-200 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync"}
          </button>
        )}
      </div>

      {data && !loading && (
        <div className="mb-2 flex gap-1 overflow-x-auto">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`shrink-0 rounded px-2.5 py-1 text-xs transition ${
                tab === id
                  ? "bg-accent/15 text-accent"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="text-xs text-slate-500">Loading fundamentals…</p>}

        {error && !loading && <p className="text-xs text-amber-400/90">{error}</p>}

        {data && !loading && tab === "overview" && <OverviewTab data={data} />}
        {data && !loading && tab === "financials" && <FinancialsTab data={data} />}
        {data && !loading && tab === "actions" && <ActionsTab data={data} />}
        {data && !loading && tab === "peers" && <PeersTab data={data} />}

        {data?.partial_errors && data.partial_errors.length > 0 && (
          <p className="mt-1 text-[11px] text-amber-500/80">
            Partial fetch: {data.partial_errors.join("; ")}
          </p>
        )}
      </div>
    </div>
  );
}
