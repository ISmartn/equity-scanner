import type { Interval } from "@/lib/api";

const INTERVALS: { id: Interval; label: string; hint: string }[] = [
  { id: "daily", label: "Daily", hint: "5 years · 20-day forecast" },
  { id: "weekly", label: "Weekly", hint: "5 years · 12-week forecast" },
  { id: "monthly", label: "Monthly", hint: "5 years · 6-month forecast" },
];

interface IntervalPickerProps {
  value: Interval;
  onChange: (interval: Interval) => void;
}

export function IntervalPicker({ value, onChange }: IntervalPickerProps) {
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
