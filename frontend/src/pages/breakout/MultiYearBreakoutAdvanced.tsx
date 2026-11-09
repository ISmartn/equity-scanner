import Checkbox from "@mui/material/Checkbox";
import Collapse from "@mui/material/Collapse";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import TextField from "@mui/material/TextField";
import type { Dispatch, SetStateAction } from "react";
import { AdvancedDrawer, AdvancedSection } from "@/components/dense";
import { AppButton } from "@/components/mui/AppButton";
import { TimelineDataCoverage } from "@/components/TimelineDataCoverage";
import type {
  MybMaType,
  MybMatchMode,
  MybScanStatus,
  MybStrategy,
  TimelineStats,
} from "@/lib/api";
import { FUNDAMENTALLY_STRONG_TOOLTIP } from "@/lib/fundamentalsMeta";

export type FnoGroupFilter = "all" | "fno" | "non_fno";

export interface MultiYearBreakoutAdvancedProps {
  open: boolean;
  onClose: () => void;
  tradeDate: string;
  stats: TimelineStats | null;

  strategy: MybStrategy;
  strategyBlurb?: string;
  showBreakoutControls: boolean;
  showPullbackControls: boolean;
  lookbackYears: number;

  scanRunning: boolean;
  bootLoading: boolean;
  onRunScanMonth: () => void;
  onRunScanLast7: () => void;
  scanStatus: MybScanStatus | null;
  activeProgressPct: number;

  pullbackPct: number;
  setPullbackPct: (value: number) => void;
  matchMode: MybMatchMode;
  setMatchMode: (value: MybMatchMode) => void;
  bandWidthPct: number;
  setBandWidthPct: (value: number) => void;
  showAdvancedTrend: boolean;
  setShowAdvancedTrend: Dispatch<SetStateAction<boolean>>;
  maType: MybMaType;
  setMaType: (value: MybMaType) => void;
  shortMaPeriod: number;
  setShortMaPeriod: (value: number) => void;
  longMaPeriod: number;
  setLongMaPeriod: (value: number) => void;
  includeMultiYear: boolean;
  setIncludeMultiYear: (value: boolean) => void;
  includeAthPullback: boolean;
  setIncludeAthPullback: (value: boolean) => void;
}

export function MultiYearBreakoutAdvanced(props: MultiYearBreakoutAdvancedProps) {
  const {
    open,
    onClose,
    tradeDate,
    stats,
    strategy,
    strategyBlurb,
    showBreakoutControls,
    showPullbackControls,
    lookbackYears,
    scanRunning,
    bootLoading,
    onRunScanMonth,
    onRunScanLast7,
    scanStatus,
    activeProgressPct,
    pullbackPct,
    setPullbackPct,
    matchMode,
    setMatchMode,
    bandWidthPct,
    setBandWidthPct,
    showAdvancedTrend,
    setShowAdvancedTrend,
    maType,
    setMaType,
    shortMaPeriod,
    setShortMaPeriod,
    longMaPeriod,
    setLongMaPeriod,
    includeMultiYear,
    setIncludeMultiYear,
    includeAthPullback,
    setIncludeAthPullback,
  } = props;

  const batchDisabled = scanRunning || bootLoading || !tradeDate;

  return (
    <AdvancedDrawer open={open} onClose={onClose} title="Breakout scan options" subtitle={tradeDate || undefined}>
      {showPullbackControls || strategy === "custom" ? (
        <AdvancedSection title="Strategy parameters" hint="Re-run scan after changing">
          {showPullbackControls ? (
            <>
              <div>
                <div className="text-data-xs text-slate-400">Min pullback ≥ {pullbackPct}% from ATH</div>
                <Slider
                  size="small"
                  value={pullbackPct}
                  min={5}
                  max={90}
                  step={1}
                  valueLabelDisplay="auto"
                  onChange={(_e, v) => setPullbackPct(v as number)}
                  sx={{ py: 0.5 }}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <TextField
                  select
                  label="Match"
                  value={matchMode}
                  onChange={(e) => setMatchMode(e.target.value as MybMatchMode)}
                >
                  <MenuItem value="at_least">At least X%</MenuItem>
                  <MenuItem value="at_most">At most X%</MenuItem>
                  <MenuItem value="band">X% ± band</MenuItem>
                </TextField>
                {matchMode === "band" ? (
                  <TextField
                    label="Band ±%"
                    type="number"
                    value={bandWidthPct}
                    onChange={(e) => setBandWidthPct(Number(e.target.value) || 0)}
                    slotProps={{ htmlInput: { min: 0, max: 40, step: 1 } }}
                  />
                ) : null}
              </div>
              <AppButton size="small" variant="text" onClick={() => setShowAdvancedTrend((v) => !v)}>
                {showAdvancedTrend ? "Hide MA" : "MA settings"}
              </AppButton>
              <Collapse in={showPullbackControls && showAdvancedTrend}>
                <div className="space-y-2 rounded-md border border-surface-border p-2">
                  <div className="text-[10px] uppercase tracking-wide text-slate-400">Trend MAs</div>
                  <div className="grid grid-cols-3 gap-2">
                    <TextField
                      select
                      label="Type"
                      value={maType}
                      onChange={(e) => setMaType(e.target.value as MybMaType)}
                    >
                      <MenuItem value="sma">SMA</MenuItem>
                      <MenuItem value="ema">EMA</MenuItem>
                    </TextField>
                    <TextField
                      label="Short"
                      type="number"
                      value={shortMaPeriod}
                      onChange={(e) => setShortMaPeriod(Number(e.target.value) || 50)}
                      slotProps={{ htmlInput: { min: 5, max: 100 } }}
                    />
                    <TextField
                      label="Long"
                      type="number"
                      value={longMaPeriod}
                      onChange={(e) => setLongMaPeriod(Number(e.target.value) || 200)}
                      slotProps={{ htmlInput: { min: 20, max: 300 } }}
                    />
                  </div>
                  <p className="text-data-xs text-slate-300">
                    Uptrend = price &gt; {longMaPeriod} {maType.toUpperCase()}, short &gt; long, RSI ≥ 45.
                    Downtrend = opposite stack, RSI ≤ 50. Re-run scan after changing MAs.
                  </p>
                </div>
              </Collapse>
            </>
          ) : null}

          {strategy === "custom" ? (
            <div className="flex flex-wrap items-center gap-2">
              <FormControlLabel
                control={
                  <Checkbox checked={includeMultiYear} onChange={(e) => setIncludeMultiYear(e.target.checked)} />
                }
                label={<span className="text-data-sm text-slate-200">Multi-year</span>}
              />
              <FormControlLabel
                control={
                  <Checkbox checked={includeAthPullback} onChange={(e) => setIncludeAthPullback(e.target.checked)} />
                }
                label={<span className="text-data-sm text-slate-200">ATH pullback</span>}
              />
            </div>
          ) : null}
        </AdvancedSection>
      ) : null}

      <AdvancedSection title="Jobs" defaultOpen={scanRunning}>
        <div className="flex gap-2">
          <AppButton
            size="small"
            onClick={onRunScanMonth}
            disabled={batchDisabled}
            title={
              tradeDate
                ? `Scan every weekday in ${tradeDate.slice(0, 7)} through ${tradeDate}`
                : "Scan whole month"
            }
          >
            Scan month
          </AppButton>
          <AppButton
            size="small"
            onClick={onRunScanLast7}
            disabled={batchDisabled}
            title={tradeDate ? `Scan the 7 weekdays before ${tradeDate}` : "Scan last 7 days"}
          >
            Scan −7 days
          </AppButton>
        </div>
        {scanRunning && scanStatus ? (
          <div className="space-y-1">
            <div className="flex flex-wrap items-center justify-between gap-2 text-data-xs text-slate-300">
              <span>
                {scanStatus.batch_mode === "month"
                  ? "Batch · month"
                  : scanStatus.batch_mode === "last_7"
                    ? "Batch · −7d"
                    : "Scanning"}
                {scanStatus.batch_day_total ? (
                  <>
                    {" · "}
                    <span className="font-semibold text-slate-100">
                      {scanStatus.batch_day_index}/{scanStatus.batch_day_total}
                    </span>
                  </>
                ) : null}
                {scanStatus.strategy ? (
                  <>
                    {" · "}
                    <span className="font-semibold text-slate-100">{scanStatus.strategy}</span>
                  </>
                ) : null}
                {scanStatus.trade_date ? (
                  <>
                    {" · "}
                    <span className="font-semibold text-slate-100">{scanStatus.trade_date}</span>
                  </>
                ) : null}
                {scanStatus.current_ticker ? (
                  <>
                    {" · "}
                    <span className="font-semibold text-slate-100">{scanStatus.current_ticker}</span>
                  </>
                ) : null}
              </span>
              <span className="tabular-nums">
                {scanStatus.processed.toLocaleString()}/{scanStatus.total.toLocaleString()}
                {scanStatus.total > 0 ? ` (${activeProgressPct}%)` : ""}
                {" · "}
                {scanStatus.alerts_count.toLocaleString()} alerts
              </span>
            </div>
            <LinearProgress
              variant="determinate"
              value={activeProgressPct}
              className="h-1 rounded-full"
              sx={{ bgcolor: "background.default", borderRadius: 999 }}
            />
          </div>
        ) : (
          <p className="text-data-xs text-slate-400">
            Batch runs execute in the background; progress shows under the toolbar.
          </p>
        )}
      </AdvancedSection>

      <AdvancedSection title="Data coverage">
        <TimelineDataCoverage stats={stats} compact />
      </AdvancedSection>

      <AdvancedSection title="Help" defaultOpen={false}>
        <p className="text-data-xs leading-relaxed text-slate-300">
          {strategyBlurb}{" "}
          {showPullbackControls
            ? `Condition: % pullback = (ATH − LTP) / ATH × 100 ${
                matchMode === "band"
                  ? `∈ ${pullbackPct}% ± ${bandWidthPct}%`
                  : matchMode === "at_most"
                    ? `≤ ${pullbackPct}%`
                    : `≥ ${pullbackPct}%`
              }. Trend filter updates the table without re-scan; change min pullback / MAs then Run scan.`
            : showBreakoutControls
              ? `Close vs prior ${lookbackYears}Y high (fresh = Breakout; within 3% below = Near).`
              : null}{" "}
          Size tiers use 20d avg turnover. Listing filter uses the NSE F&O universe (★ = F&O).
          Strong Fund: {FUNDAMENTALLY_STRONG_TOOLTIP}.
        </p>
      </AdvancedSection>
    </AdvancedDrawer>
  );
}
