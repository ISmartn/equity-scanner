import { X } from "lucide-react";

export interface ActiveFilterChip {
  key: string;
  label: string;
  onRemove?: () => void;
}

export function ActiveFilterChips({ chips }: { chips: ActiveFilterChip[] }) {
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex items-center gap-1 rounded border border-accent/30 bg-accent/10 px-1.5 py-px text-data-xs text-sky-100"
        >
          {chip.label}
          {chip.onRemove ? (
            <button
              type="button"
              onClick={chip.onRemove}
              aria-label={`Remove ${chip.label} filter`}
              className="text-sky-300 hover:text-white"
            >
              <X className="h-3 w-3" />
            </button>
          ) : null}
        </span>
      ))}
    </div>
  );
}
