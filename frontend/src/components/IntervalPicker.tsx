import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import type { Interval } from "@/lib/api";

const INTERVALS: { id: Interval; label: string; hint: string }[] = [
  { id: "daily", label: "Daily", hint: "5 years · 20-day forecast" },
  { id: "weekly", label: "Weekly", hint: "5 years · 12-week forecast" },
  { id: "monthly", label: "Monthly", hint: "5 years · 6-month forecast" },
];

interface IntervalPickerProps {
  value: Interval;
  onChange: (interval: Interval) => void;
  /** Segmented control for toolbars; hints become tooltips. */
  compact?: boolean;
}

export function IntervalPicker({ value, onChange, compact = false }: IntervalPickerProps) {
  if (compact) {
    return (
      <ToggleButtonGroup
        exclusive
        value={value}
        onChange={(_e, next: Interval | null) => {
          if (next) onChange(next);
        }}
        sx={{ flexShrink: 0 }}
      >
        {INTERVALS.map((item) => (
          <ToggleButton key={item.id} value={item.id} title={item.hint}>
            {item.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {INTERVALS.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onChange(item.id)}
          className={`rounded-xl border px-4 py-3 text-left transition ${
            value === item.id
              ? "border-accent/50 bg-accent/15 text-white"
              : "border-surface-border bg-surface-raised text-slate-300 hover:border-slate-600"
          }`}
        >
          <div className="text-sm font-semibold">{item.label}</div>
          <div className="text-xs text-slate-500">{item.hint}</div>
        </button>
      ))}
    </div>
  );
}
