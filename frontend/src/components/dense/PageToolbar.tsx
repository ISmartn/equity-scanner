import { SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PageToolbarProps {
  children: ReactNode;
  right?: ReactNode;
  /** Rendered full-width below the control row (progress bars, active filter chips). */
  below?: ReactNode;
  className?: string;
}

export function PageToolbar({ children, right, below, className }: PageToolbarProps) {
  return (
    <div className={cn("shrink-0 rounded-lg border border-surface-border bg-surface-raised", className)}>
      <div className="flex items-center gap-2 px-2 py-1">
        <div className="min-w-0 flex-1 overflow-x-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5">
          <div className="flex w-max flex-nowrap items-center gap-2 py-0.5">{children}</div>
        </div>
        {right ? <div className="flex shrink-0 items-center gap-1.5">{right}</div> : null}
      </div>
      {below ? <div className="border-t border-surface-border px-2 py-1">{below}</div> : null}
    </div>
  );
}

export function ToolbarDivider() {
  return <div className="h-5 w-px shrink-0 bg-surface-border" aria-hidden />;
}

interface AdvancedButtonProps {
  onClick: () => void;
  activeCount?: number;
  label?: string;
}

export function AdvancedButton({ onClick, activeCount = 0, label = "Advanced" }: AdvancedButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Filters, batch jobs, overlays, export and logs"
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-data-xs font-semibold transition",
        activeCount > 0
          ? "border-accent/50 bg-accent/15 text-sky-200 hover:bg-accent/25"
          : "border-surface-border text-slate-200 hover:border-accent/40 hover:text-white",
      )}
    >
      <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
      {label}
      {activeCount > 0 ? (
        <span className="min-w-[1.1rem] rounded-full bg-accent px-1 text-center text-[10px] leading-4 text-white">
          {activeCount}
        </span>
      ) : null}
    </button>
  );
}
