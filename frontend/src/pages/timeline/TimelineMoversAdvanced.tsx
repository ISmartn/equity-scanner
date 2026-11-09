import {
  CalendarClock,
  ClipboardCopy,
  Database,
  PanelRightClose,
  PanelRightOpen,
  Square,
} from "lucide-react";
import { AppButton } from "@/components/mui";
import { AdvancedDrawer, AdvancedSection } from "@/components/dense";
import { TimelineDataCoverage } from "@/components/TimelineDataCoverage";
import type { TimelineIngestStatus, TimelineStats } from "@/lib/api";

export interface TimelineMoversAdvancedProps {
  open: boolean;
  onClose: () => void;

  stats: TimelineStats | null;
  tradeDate: string;
  dataIsStale: boolean;
  candleSyncNeeded: boolean;

  syncing: boolean;
  reprofiling: boolean;
  uptoDateRunning: boolean;
  ingestStopping: boolean;
  ingestStatus: TimelineIngestStatus | null;
  ingestProgressPct: number;
  onSyncProfiles: () => void;
  onReprofileStale: () => void;
  onUptoDate: () => void;
  onStopIngest: () => void;
  syncInfo: string | null;

  showFundamentals: boolean;
  onToggleFundamentals: () => void;

  hasSearched: boolean;
  exportRowsCount: number;
  exportJson: string;
  copyingJson: boolean;
  copyMessage: string | null;
  onCopyJson: () => void;
  exportJsonOpen: boolean;
  setExportJsonOpen: (updater: (open: boolean) => boolean) => void;
}

export function TimelineMoversAdvanced(props: TimelineMoversAdvancedProps) {
  const {
    open,
    onClose,
    stats,
    tradeDate,
    dataIsStale,
    candleSyncNeeded,
    syncing,
    reprofiling,
    uptoDateRunning,
    ingestStopping,
    ingestStatus,
    ingestProgressPct,
    onSyncProfiles,
    onReprofileStale,
    onUptoDate,
    onStopIngest,
    syncInfo,
    showFundamentals,
    onToggleFundamentals,
    hasSearched,
    exportRowsCount,
    exportJson,
    copyingJson,
    copyMessage,
    onCopyJson,
    exportJsonOpen,
    setExportJsonOpen,
  } = props;

  return (
    <AdvancedDrawer open={open} onClose={onClose} title="Timeline options" subtitle={tradeDate || undefined}>
      <AdvancedSection title="Jobs">
        <div className="flex flex-wrap items-center gap-1.5">
          <AppButton
            size="small"
            onClick={onSyncProfiles}
            disabled={syncing || reprofiling || uptoDateRunning}
            title="Sync NSE profiles"
          >
            {syncing ? "Syncing…" : "Sync"}
          </AppButton>
          <AppButton
            size="small"
            onClick={onReprofileStale}
            disabled={syncing || reprofiling || uptoDateRunning}
            title="Refresh profiles, migrate ISINs, skip delisted symbols in ingest"
            className="hover:border-amber-500/40 hover:text-amber-200"
          >
            {reprofiling ? "Reprofiling…" : "Reprofile"}
          </AppButton>
          <AppButton
            size="small"
            variant={uptoDateRunning ? "outlined" : "contained"}
            color={uptoDateRunning ? "error" : "primary"}
            onClick={uptoDateRunning ? onStopIngest : onUptoDate}
            disabled={
              syncing ||
              reprofiling ||
              ingestStopping ||
              (!uptoDateRunning && (stats?.profile_count ?? 0) === 0)
            }
            title={
              uptoDateRunning
                ? "Stop candle sync after the current symbol"
                : candleSyncNeeded
                  ? `Fetch missing candles through ${stats?.target_trade_date ?? "today"}`
                  : `Data current through ${stats?.max_trade_date ?? "—"}`
            }
            startIcon={
              uptoDateRunning ? (
                <Square className={`h-3 w-3 ${ingestStopping ? "animate-pulse" : ""}`} />
              ) : (
                <CalendarClock className="h-3.5 w-3.5" />
              )
            }
          >
            {uptoDateRunning
              ? ingestStopping || ingestStatus?.cancel_requested
                ? "Stopping…"
                : "Stop"
              : candleSyncNeeded
                ? "Up-to-date"
                : "Current"}
          </AppButton>
        </div>

        {uptoDateRunning && ingestStatus && (
          <div className="space-y-1.5 rounded-md border border-surface-border p-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-data-xs text-slate-300">
              <span>
                Updating stocks
                {ingestStatus.current_ticker ? (
                  <>
                    {" · "}
                    <span className="font-semibold text-slate-100">{ingestStatus.current_ticker}</span>
                  </>
                ) : null}
              </span>
              <span className="tabular-nums">
                {ingestStatus.processed.toLocaleString()} / {ingestStatus.total.toLocaleString()}
                {ingestStatus.total > 0 ? ` (${ingestProgressPct}%)` : ""}
              </span>
              {(ingestStopping || ingestStatus.cancel_requested) && (
                <span className="text-amber-400">Stopping after current symbol…</span>
              )}
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${ingestProgressPct}%` }}
              />
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-data-xs tabular-nums text-slate-300">
              {ingestStatus.success > 0 && (
                <span className="text-gain">{ingestStatus.success.toLocaleString()} new bars</span>
              )}
              {(ingestStatus.empty ?? 0) > 0 && (
                <span className="text-amber-400/90">
                  {(ingestStatus.empty ?? 0).toLocaleString()} no new data
                </span>
              )}
              <span>{ingestStatus.skipped.toLocaleString()} skipped</span>
              {ingestStatus.failed > 0 && (
                <span className="text-loss">{ingestStatus.failed.toLocaleString()} failed</span>
              )}
              <span>{ingestStatus.total_bars.toLocaleString()} bars written</span>
              <span className="text-slate-400">3 parallel connections</span>
            </div>
            {ingestStatus.recent_errors && ingestStatus.recent_errors.length > 0 && (
              <div className="max-h-32 overflow-y-auto rounded border border-red-500/20 bg-red-500/5 px-2 py-1 text-data-xs text-red-200/90">
                {ingestStatus.recent_errors.slice(0, 8).map((row) => (
                  <div key={row.ticker} className="truncate" title={`${row.ticker}: ${row.error}`}>
                    <span className="font-semibold text-red-100">{row.ticker}</span>: {row.error}
                  </div>
                ))}
                {ingestStatus.failed > ingestStatus.recent_errors.length && (
                  <div className="text-red-300/80">
                    +{(ingestStatus.failed - ingestStatus.recent_errors.length).toLocaleString()} more in{" "}
                    {ingestStatus.error_log ?? "candle_ingest_errors.log"}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {syncInfo && (
          <div className="flex items-start gap-2 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-data-xs text-sky-100">
            <Database className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{syncInfo}</span>
          </div>
        )}
      </AdvancedSection>

      <AdvancedSection title="Data">
        <TimelineDataCoverage stats={stats} />
        {stats && (
          <p className="flex items-center gap-1 text-data-xs text-slate-300">
            <Database className="h-3.5 w-3.5 text-slate-400" />
            <span className="num text-slate-100">
              {stats.symbols_at_max_date.toLocaleString()}/{stats.profile_count.toLocaleString()}
            </span>
            symbols at latest date
          </p>
        )}
        {dataIsStale && (
          <p className="text-data-xs text-amber-400/90">Behind target {stats?.target_trade_date}</p>
        )}
      </AdvancedSection>

      <AdvancedSection title="Panels">
        <button
          type="button"
          onClick={onToggleFundamentals}
          title={showFundamentals ? "Hide fundamentals panel" : "Show fundamentals panel"}
          aria-pressed={showFundamentals}
          className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-data-sm transition ${
            showFundamentals
              ? "border-accent/50 bg-accent/15 text-sky-100"
              : "border-surface-border text-slate-300 hover:text-white"
          }`}
        >
          {showFundamentals ? (
            <PanelRightClose className="h-3.5 w-3.5" />
          ) : (
            <PanelRightOpen className="h-3.5 w-3.5" />
          )}
          <span className="flex-1">Fundamentals panel</span>
          <span className="text-data-xs font-semibold">{showFundamentals ? "On" : "Off"}</span>
        </button>
      </AdvancedSection>

      <AdvancedSection title="Export" hint={hasSearched ? `${exportRowsCount} rows` : undefined}>
        <AppButton
          size="small"
          startIcon={<ClipboardCopy className={`h-3.5 w-3.5 ${copyingJson ? "animate-pulse" : ""}`} />}
          disabled={!exportRowsCount || copyingJson}
          onClick={onCopyJson}
          title="Copy all search results as JSON"
        >
          Copy JSON
        </AppButton>
        {copyMessage ? <p className="text-data-xs text-gain">{copyMessage}</p> : null}
        {hasSearched && exportRowsCount > 0 ? (
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
    </AdvancedDrawer>
  );
}
