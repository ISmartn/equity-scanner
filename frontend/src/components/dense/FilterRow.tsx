import ToggleButton from "@mui/material/ToggleButton";
import { RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Always-visible filter strip for a page toolbar's `below` slot, so users can
 * adjust several filters in a row while watching results update.
 */
export function FilterRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 py-0.5">{children}</div>;
}

export const filterToggleGroupSx = {
  flexShrink: 0,
  "& .MuiToggleButton-root": { textTransform: "none", px: 1 },
} as const;

interface FilterToggleProps {
  label: ReactNode;
  selected: boolean;
  onChange: (next: boolean) => void;
  title?: string;
  disabled?: boolean;
}

export function FilterToggle({ label, selected, onChange, title, disabled }: FilterToggleProps) {
  return (
    <ToggleButton
      value="on"
      selected={selected}
      disabled={disabled}
      onChange={() => onChange(!selected)}
      title={title}
      sx={{ flexShrink: 0, textTransform: "none", px: 1 }}
    >
      {label}
    </ToggleButton>
  );
}

export function FilterReset({ count, onReset }: { count: number; onReset: () => void }) {
  if (count <= 0) return null;
  return (
    <button
      type="button"
      onClick={onReset}
      className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-1.5 text-data-xs text-slate-300 hover:text-white"
      title="Reset all filters"
    >
      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
      Reset ({count})
    </button>
  );
}
