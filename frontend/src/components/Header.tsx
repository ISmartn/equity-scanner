import type { ReactNode } from "react";
import { Database, KeyRound, TrendingUp } from "lucide-react";

interface HeaderProps {
  onOpenSettings: () => void;
  backendOnline: boolean;
  stocksWithData?: number | null;
  totalProfiles?: number | null;
  /** Primary navigation rendered inline in the bar. */
  nav?: ReactNode;
}

export function Header({
  onOpenSettings,
  backendOnline,
  stocksWithData,
  totalProfiles,
  nav,
}: HeaderProps) {
  const dbLabel =
    stocksWithData != null && totalProfiles != null
      ? `${stocksWithData.toLocaleString()} / ${totalProfiles.toLocaleString()} stocks`
      : "Timeline DB";

  return (
    <header className="sticky top-0 z-40 flex h-[var(--app-chrome-h)] items-stretch gap-2 border-b border-surface-border bg-surface-raised/90 px-2 backdrop-blur sm:px-3">
      <div
        className="flex shrink-0 items-center gap-1.5"
        title="Equity Scan Lab — NSE scanners · forecast · sector rotation · TimesFM 2.5 on demand"
      >
        <span className="rounded-md bg-accent/15 p-1 text-accent">
          <TrendingUp className="h-4 w-4" aria-hidden />
        </span>
        <span className="hidden whitespace-nowrap text-data-md font-semibold tracking-tight text-slate-100 md:inline">
          Equity Scan Lab
        </span>
      </div>

      <div className="min-w-0 flex-1">{nav}</div>

      <div className="flex shrink-0 items-center gap-2">
        <span
          className="inline-flex items-center gap-1 text-data-xs text-slate-300"
          title={backendOnline ? "Backend online" : "Backend offline"}
        >
          <span
            className={`h-2 w-2 rounded-full ${backendOnline ? "bg-gain" : "bg-amber-400 animate-pulse"}`}
            aria-hidden
          />
          <span className="hidden xl:inline">{backendOnline ? "Online" : "Offline"}</span>
        </span>
        <span
          className="hidden items-center gap-1 whitespace-nowrap text-data-xs tabular-nums text-slate-300 lg:inline-flex"
          title="Stocks with timeline candles / total profiles"
        >
          <Database className="h-3 w-3 text-slate-400" aria-hidden />
          {dbLabel}
        </span>
        <button
          type="button"
          onClick={onOpenSettings}
          className="inline-flex h-7 items-center gap-1 rounded-md border border-surface-border bg-surface px-2 text-data-xs font-semibold text-slate-200 transition hover:border-accent/40 hover:text-white"
        >
          <KeyRound className="h-3.5 w-3.5" aria-hidden />
          <span className="hidden sm:inline">Upstox Token</span>
          <span className="sm:hidden">Token</span>
        </button>
      </div>
    </header>
  );
}
