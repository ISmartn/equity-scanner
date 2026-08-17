import { ArrowDown, ArrowUp, Box, RefreshCw, TrendingUp, X } from "lucide-react";
import { useMemo } from "react";

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
      className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${toneClass}`}
    >
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onRemove}
        className="rounded-full p-0.5 opacity-70 transition hover:bg-black/20 hover:opacity-100"
        aria-label={`Remove ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

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

  const toggleBtn = (active: boolean) =>
    `inline-flex h-8 items-center gap-1 rounded-md border px-2 text-[11px] transition ${
      active
        ? "border-accent/40 bg-accent/15 font-medium text-accent"
        : "border-surface-border text-slate-400 hover:border-accent/30 hover:text-slate-200"
    }`;

  return (
    <div className="shrink-0 space-y-2 rounded-xl border border-surface-border bg-surface-raised px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
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
            className="ml-0.5 w-12 rounded border border-surface-border bg-surface px-1 py-0.5 text-[11px] text-slate-200 outline-none disabled:opacity-40"
            aria-label="Positive move threshold percent"
          />
          <span className="text-slate-500">%</span>
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
            className="ml-0.5 w-12 rounded border border-surface-border bg-surface px-1 py-0.5 text-[11px] text-slate-200 outline-none disabled:opacity-40"
            aria-label="Negative move threshold percent"
          />
          <span className="text-slate-500">%</span>
        </button>

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
            className="ml-0.5 w-12 rounded border border-surface-border bg-surface px-1 py-0.5 text-[11px] text-slate-200 outline-none disabled:opacity-40"
            aria-label="Darvas lookback days"
          />
          <span className="text-slate-500">d</span>
        </button>

        {darvasEnabled && (
          <div className="flex items-center gap-1">
            {[10, 20, 30, 60].map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => onDarvasLookbackInput(String(days))}
                className={`rounded border px-1.5 py-0.5 text-[10px] transition ${
                  darvasLookbackInput === String(days)
                    ? "border-sky-500/40 bg-sky-500/10 text-sky-200"
                    : "border-surface-border text-slate-500 hover:text-slate-300"
                }`}
              >
                {days}d
              </button>
            ))}
          </div>
        )}

        <button
          type="button"
          onClick={onRefresh}
          disabled={loadingCandles}
          className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[11px] font-semibold text-white transition hover:bg-accent-muted disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loadingCandles ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-t border-surface-border/80 pt-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Active</span>
        {chips.length === 0 ? (
          <span className="text-[11px] text-slate-500">
            No move filters on — chart shows raw price
          </span>
        ) : (
          chips.map((chip) => (
            <Chip key={chip.id} label={chip.label} tone={chip.tone} onRemove={chip.onRemove} />
          ))
        )}
        {chips.length > 0 && (
          <button
            type="button"
            onClick={onResetFilters}
            className="ml-1 rounded-md border border-surface-border px-2 py-0.5 text-[10px] text-slate-400 transition hover:border-red-500/40 hover:text-red-300"
          >
            Clear all
          </button>
        )}
        {(filterInvalid || darvasLookbackInvalid) && (
          <span className="text-[11px] text-amber-400">
            {filterInvalid ? "Enter valid % thresholds" : "Darvas lookback must be 5–252"}
          </span>
        )}
      </div>
    </div>
  );
}
