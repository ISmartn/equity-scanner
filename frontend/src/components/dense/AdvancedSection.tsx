import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

interface AdvancedSectionProps {
  title: string;
  hint?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function AdvancedSection({ title, hint, defaultOpen = true, children }: AdvancedSectionProps) {
  return (
    <details open={defaultOpen} className="group border-b border-surface-border">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-slate-300 hover:text-slate-100 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
        <span className="flex-1">{title}</span>
        {hint ? <span className="font-normal normal-case tracking-normal text-slate-400">{hint}</span> : null}
      </summary>
      <div className="space-y-2 px-3 pb-3 text-data-sm text-slate-300">{children}</div>
    </details>
  );
}
