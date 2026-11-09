import { ArrowDown, ArrowUp, Box, RefreshCw, TrendingUp, X } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { PageToolbar, ToolbarDivider } from "@/components/dense";

export interface MoveFilterToolbarProps {
  positiveEnabled: boolean;
  negativeEnabled: boolean;
  threeGreenEnabled: boolean;
  darvasEnabled: boolean;
  positiveInput: string;
  negativeInput: string;
  darvasLookbackInput: string;

  onPositiveEnabled: (v: boolean) => void;
  onNegativeEnabled: (v: boolean) => void;
  onThreeGreenEnabled: (v: boolean) => void;
  onDarvasEnabled: (v: boolean) => void;
  onPositiveInput: (v: string) => void;
  onNegativeInput: (v: string) => void;
  onDarvasLookbackInput: (v: string) => void;
  onResetFilters: () => void;

  filterInvalid: boolean;
  darvasLookbackInvalid: boolean;
  loadingCandles: boolean;
  onRefresh: () => void;

  /** Rendered at the right edge of the toolbar (typically the Advanced button). */
  right?: ReactNode;
}

type ActiveChip = {
  id: string;
  label: string;
  tone: "emerald" | "red" | "lime" | "sky";
  onRemove: () => void;
};

function Chip({
  label,
  tone,
  onRemove,
}: {
  label: string;
  tone: ActiveChip["tone"];
  onRemove: () => void;
}) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
      : tone === "red"
        ? "border-red-500/30 bg-red-500/10 text-red-200"
        : tone === "lime"
          ? "border-lime-500/30 bg-lime-500/10 text-lime-200"
          : "border-sky-500/30 bg-sky-500/10 text-sky-200";

  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-px text-data-xs ${toneClass}`}
    >
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onRemove}
        className="rounded-full opacity-70 transition hover:bg-black/20 hover:opacity-100"
        aria-label={`Remove ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

const toggleBtn = (active: boolean) =>
  `inline-flex h-7 shrink-0 items-center gap-1 rounded-md border px-2 text-data-xs transition ${
    active
      ? "border-accent/40 bg-accent/15 font-medium text-accent"
      : "border-surface-border text-slate-300 hover:border-accent/30 hover:text-slate-100"
  }`;

const numInputClass =
  "ml-0.5 w-12 rounded border border-surface-border bg-surface px-1 py-0.5 text-data-xs tabular-nums text-slate-200 outline-none disabled:opacity-40";

export function MoveFilterToolbar(props: MoveFilterToolbarProps) {
  const {
    positiveEnabled,
    negativeEnabled,
    threeGreenEnabled,
    darvasEnabled,
    positiveInput,
    negativeInput,
    darvasLookbackInput,
    onPositiveEnabled,
    onNegativeEnabled,
    onThreeGreenEnabled,
    onDarvasEnabled,
    onPositiveInput,
    onNegativeInput,
    onDarvasLookbackInput,
    onResetFilters,
    filterInvalid,
    darvasLookbackInvalid,
    loadingCandles,
    onRefresh,
    right,
  } = props;

  const chips = useMemo<ActiveChip[]>(() => {
    const out: ActiveChip[] = [];
    if (positiveEnabled) {
      out.push({
        id: "pos",
        label: `Up ≥ ${positiveInput || "?"}%`,
        tone: "emerald",
        onRemove: () => onPositiveEnabled(false),
      });
    }
    if (negativeEnabled) {
      out.push({
        id: "neg",
        label: `Down ≤ −${negativeInput || "?"}%`,
        tone: "red",
        onRemove: () => onNegativeEnabled(false),
      });
    }
    if (threeGreenEnabled) {
      out.push({
        id: "3g",
        label: "3 green candles",
        tone: "lime",
        onRemove: () => onThreeGreenEnabled(false),
      });
    }
    if (darvasEnabled) {
      out.push({
        id: "darvas",
        label: `Darvas ${darvasLookbackInput || "?"}d`,
        tone: "sky",
        onRemove: () => onDarvasEnabled(false),
      });
    }
    return out;
  }, [
    positiveEnabled,
    negativeEnabled,
    threeGreenEnabled,
    darvasEnabled,
    positiveInput,
    negativeInput,
    darvasLookbackInput,
    onPositiveEnabled,
    onNegativeEnabled,
    onThreeGreenEnabled,
    onDarvasEnabled,
  ]);

  return (
    <PageToolbar
      right={right}
      below={
        chips.length > 0 || filterInvalid || darvasLookbackInvalid ? (
          <div className="flex flex-wrap items-center gap-1">
            {chips.map((chip) => (
              <Chip key={chip.id} label={chip.label} tone={chip.tone} onRemove={chip.onRemove} />
            ))}
            {chips.length > 0 && (
              <button
                type="button"
                onClick={onResetFilters}
                className="ml-1 rounded border border-surface-border px-1.5 py-px text-data-xs text-slate-300 transition hover:border-red-500/40 hover:text-red-300"
              >
                Clear all
              </button>
            )}
            {filterInvalid && (
              <span className="text-data-xs text-amber-400">Enter valid % thresholds</span>
            )}
            {darvasLookbackInvalid && (
              <span className="text-data-xs text-amber-400">Darvas lookback must be 5–252</span>
            )}
          </div>
        ) : undefined
      }
    >
      <button
        type="button"
        className={toggleBtn(positiveEnabled)}
        onClick={() => onPositiveEnabled(!positiveEnabled)}
      >
        <ArrowUp className="h-3.5 w-3.5 text-emerald-400" />
        Up
        <input
          type="number"
          min="0"
          step="0.1"
          value={positiveInput}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            onPositiveEnabled(true);
            onPositiveInput(e.target.value);
          }}
          disabled={!positiveEnabled}
          className={numInputClass}
          aria-label="Positive move threshold percent"
        />
        <span className="text-slate-400">%</span>
      </button>

      <button
        type="button"
        className={toggleBtn(negativeEnabled)}
        onClick={() => onNegativeEnabled(!negativeEnabled)}
      >
        <ArrowDown className="h-3.5 w-3.5 text-red-400" />
        Down
        <input
          type="number"
          min="0"
          step="0.1"
          value={negativeInput}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            onNegativeEnabled(true);
            onNegativeInput(e.target.value);
          }}
          disabled={!negativeEnabled}
          className={numInputClass}
          aria-label="Negative move threshold percent"
        />
        <span className="text-slate-400">%</span>
      </button>

      <ToolbarDivider />

      <button
        type="button"
        className={toggleBtn(threeGreenEnabled)}
        onClick={() => onThreeGreenEnabled(!threeGreenEnabled)}
        title="Highlight 3+ consecutive green candles"
      >
        <TrendingUp className="h-3.5 w-3.5 text-lime-400" />
        3 green
      </button>

      <button
        type="button"
        className={toggleBtn(darvasEnabled)}
        onClick={() => onDarvasEnabled(!darvasEnabled)}
        title="Show Darvas boxes on filtered days"
      >
        <Box className="h-3.5 w-3.5 text-sky-400" />
        Darvas
        <input
          type="number"
          min="5"
          max="252"
          step="1"
          value={darvasLookbackInput}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            onDarvasEnabled(true);
            onDarvasLookbackInput(e.target.value);
          }}
          disabled={!darvasEnabled}
          className={numInputClass}
          aria-label="Darvas lookback days"
        />
        <span className="text-slate-400">d</span>
      </button>

      {darvasEnabled && (
        <div className="flex shrink-0 items-center gap-1">
          {[10, 20, 30, 60].map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => onDarvasLookbackInput(String(days))}
              className={`rounded border px-1.5 py-0.5 text-data-xs transition ${
                darvasLookbackInput === String(days)
                  ? "border-sky-500/40 bg-sky-500/10 text-sky-200"
                  : "border-surface-border text-slate-300 hover:text-slate-100"
              }`}
            >
              {days}d
            </button>
          ))}
        </div>
      )}

      <ToolbarDivider />

      <button
        type="button"
        onClick={onRefresh}
        disabled={loadingCandles}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md bg-accent px-2.5 text-data-xs font-semibold text-white transition hover:bg-accent-muted disabled:opacity-60"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loadingCandles ? "animate-spin" : ""}`} />
        Refresh
      </button>

      {chips.length === 0 && (
        <span className="shrink-0 whitespace-nowrap text-data-xs text-slate-400">
          No move filters on — chart shows raw price
        </span>
      )}
    </PageToolbar>
  );
}
