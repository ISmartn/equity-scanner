import { ClipboardCopy, Layers, Newspaper, PanelRightClose, PanelRightOpen, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { AppButton } from "@/components/mui";
import { AdvancedDrawer, AdvancedSection } from "@/components/dense";
import { TimelineDataCoverage } from "@/components/TimelineDataCoverage";
import type { TimelineStats } from "@/lib/api";

export type FnoGroupFilter = "all" | "fno" | "non_fno";

export const SCANNER_ALL_FILTER = "all";

function PanelToggle({
  active,
  disabled,
  onClick,
  title,
  icon,
  label,
  tone,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  title: string;
  icon: ReactNode;
  label: string;
  tone: "amber" | "accent" | "sky";
}) {
  const activeTone =
    tone === "amber"
      ? "border-amber-500/50 bg-amber-500/15 text-amber-100"
      : tone === "sky"
        ? "border-sky-500/50 bg-sky-500/15 text-sky-100"
        : "border-accent/50 bg-accent/15 text-sky-100";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-pressed={active}
      className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-data-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
        active ? activeTone : "border-surface-border text-slate-300 hover:text-white"
      }`}
    >
      {icon}
      <span className="flex-1">{label}</span>
      <span className="text-data-xs font-semibold">{active ? "On" : "Off"}</span>
    </button>
  );
}

export interface MomentumScannerAdvancedProps {
  open: boolean;
  onClose: () => void;

  stats: TimelineStats | null;
  tradeDate: string;
  scanDatesCount: number;
  refinedScanDatesCount: number;

  scanRunning: boolean;
  bootLoading: boolean;
  onRunScanMonth: () => void;
  onRunScanLast7: () => void;

  vcpAvailable: boolean;
  showVcpOverlay: boolean;
  onToggleVcpOverlay: () => void;
  showFundamentals: boolean;
  onToggleFundamentals: () => void;
  showCompanyNews: boolean;
  onToggleCompanyNews: () => void;

  hasLoaded: boolean;
  exportRowsCount: number;
  exportJson: string;
  copyingJson: boolean;
  copyMessage: string | null;
  onCopyJson: () => void;
  exportJsonOpen: boolean;
  setExportJsonOpen: (updater: (open: boolean) => boolean) => void;

  foSyncing: boolean;
  foSyncNote: string | null;
}

export function MomentumScannerAdvanced(props: MomentumScannerAdvancedProps) {
  const {
    open,
    onClose,
    stats,
    tradeDate,
    scanDatesCount,
    refinedScanDatesCount,
    scanRunning,
    bootLoading,
    onRunScanMonth,
    onRunScanLast7,
    vcpAvailable,
    showVcpOverlay,
    onToggleVcpOverlay,
    showFundamentals,
    onToggleFundamentals,
    showCompanyNews,
    onToggleCompanyNews,
    hasLoaded,
    exportRowsCount,
    exportJson,
    copyingJson,
    copyMessage,
    onCopyJson,
    exportJsonOpen,
    setExportJsonOpen,
    foSyncing,
    foSyncNote,
  } = props;

  const batchDisabled = scanRunning || bootLoading || !tradeDate;

  return (
    <AdvancedDrawer open={open} onClose={onClose} title="Scanner options" subtitle={tradeDate || undefined}>
      <AdvancedSection title="Batch scans">
        <div className="flex gap-2">
          <AppButton
            size="small"
            onClick={onRunScanMonth}
            disabled={batchDisabled}
            title={`Scan every weekday in ${tradeDate.slice(0, 7)} through ${tradeDate}`}
          >
            Scan month
          </AppButton>
          <AppButton
            size="small"
            onClick={onRunScanLast7}
            disabled={batchDisabled}
            title={`Scan the 7 weekdays before ${tradeDate}`}
          >
            Scan −7 days
          </AppButton>
        </div>
        <p className="text-data-xs text-slate-400">
          Batch runs execute in the background; progress shows under the toolbar.
        </p>
      </AdvancedSection>

      <AdvancedSection title="Data coverage">
        <TimelineDataCoverage stats={stats} />
        <div className="flex flex-wrap items-center gap-3 text-data-xs text-slate-300">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm bg-emerald-400" />
            Scan done ({scanDatesCount})
          </span>
          {refinedScanDatesCount > 0 ? (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-sm bg-sky-400" />
              Rescanned · Darvas ({refinedScanDatesCount})
            </span>
          ) : null}
        </div>
      </AdvancedSection>

      <AdvancedSection title="Chart overlays & panels">
        <PanelToggle
          active={showVcpOverlay && vcpAvailable}
          disabled={!vcpAvailable}
          onClick={onToggleVcpOverlay}
          title={
            !vcpAvailable
              ? "Select a VCP signal to show contraction bands"
              : "VCP overlay (20d / 10d / 5d ranges + pivot)"
          }
          icon={<Layers className="h-3.5 w-3.5" />}
          label="VCP overlay"
          tone="amber"
        />
        <PanelToggle
          active={showFundamentals}
          onClick={onToggleFundamentals}
          title={showFundamentals ? "Hide fundamentals panel" : "Show fundamentals panel"}
          icon={
            showFundamentals ? <PanelRightClose className="h-3.5 w-3.5" /> : <PanelRightOpen className="h-3.5 w-3.5" />
          }
          label="Fundamentals panel"
          tone="accent"
        />
        <PanelToggle
          active={showCompanyNews}
          onClick={onToggleCompanyNews}
          title={showCompanyNews ? "Hide company news" : "Show company news"}
          icon={<Newspaper className="h-3.5 w-3.5" />}
          label="Company news sidebar"
          tone="sky"
        />
      </AdvancedSection>

      <AdvancedSection title="Export" hint={hasLoaded ? `${exportRowsCount} rows` : undefined}>
        <AppButton
          size="small"
          startIcon={<ClipboardCopy className={`h-3.5 w-3.5 ${copyingJson ? "animate-pulse" : ""}`} />}
          disabled={!exportRowsCount || copyingJson}
          onClick={onCopyJson}
          title="Copy all matching results as JSON"
        >
          Copy JSON
        </AppButton>
        {copyMessage ? <p className="text-data-xs text-gain">{copyMessage}</p> : null}
        {hasLoaded && exportRowsCount > 0 ? (
          <div className="rounded-md border border-surface-border">
            <button
              type="button"
              onClick={() => setExportJsonOpen((v) => !v)}
              className="flex w-full items-center justify-between px-2 py-1 text-data-xs text-slate-300 hover:text-white"
            >
              <span>Export JSON ({exportRowsCount} rows)</span>
              <span>{exportJsonOpen ? "Hide" : "Show"}</span>
            </button>
            {exportJsonOpen ? (
              <textarea
                readOnly
                value={exportJson}
                onFocus={(e) => e.target.select()}
                className="h-48 w-full resize-y border-t border-surface-border bg-surface px-2 py-1.5 font-mono text-data-xs text-slate-300 outline-none"
              />
            ) : null}
          </div>
        ) : null}
      </AdvancedSection>

      <AdvancedSection title="Logs" defaultOpen={Boolean(foSyncing || foSyncNote)}>
        {foSyncing || foSyncNote ? (
          <div
            className={`flex items-start gap-2 rounded-md border px-2 py-1 text-data-xs ${
              foSyncing
                ? "border-sky-500/30 bg-sky-500/10 text-sky-100"
                : "border-surface-border bg-surface/40 text-slate-300"
            }`}
          >
            {foSyncing ? <RefreshCw className="mt-0.5 h-3 w-3 shrink-0 animate-spin" /> : null}
            <span>{foSyncing ? "Fetching F&O derivative data from Upstox…" : foSyncNote}</span>
          </div>
        ) : (
          <p className="text-data-xs text-slate-400">No F&O sync activity yet.</p>
        )}
      </AdvancedSection>
    </AdvancedDrawer>
  );
}
