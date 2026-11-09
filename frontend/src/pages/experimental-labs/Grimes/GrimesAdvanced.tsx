import type { Dispatch, SetStateAction } from "react";
import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import { AdvancedDrawer, AdvancedSection } from "@/components/dense";
import { AppButton } from "@/components/mui/AppButton";
import type { GrimesChartPayload, GrimesKnowledgeResponse, GrimesSummaryResponse } from "@/lib/api";
import { GrimesChartGuide } from "./GrimesChartGuide";
import { GrimesDiagnostics } from "./GrimesDiagnostics";
import { GrimesKnowledgeHub } from "./GrimesKnowledgeHub";

export type GrimesOverlays = {
  pivots: boolean;
  mas: boolean;
  setups: boolean;
  riskBox: boolean;
  keltner: boolean;
};

type Props = {
  open: boolean;
  onClose: () => void;
  rightTab: string;
  data: GrimesSummaryResponse | null;
  tradeDate: string;
  loading: boolean;
  hasScanDates: boolean;
  onRescan: () => void;
  overlays: GrimesOverlays;
  setOverlays: Dispatch<SetStateAction<GrimesOverlays>>;
  capitalInr: number;
  setCapitalInr: Dispatch<SetStateAction<number>>;
  riskPctPerTrade: number;
  setRiskPctPerTrade: Dispatch<SetStateAction<number>>;
  showFundamentals: boolean;
  setShowFundamentals: Dispatch<SetStateAction<boolean>>;
  knowledge: GrimesKnowledgeResponse | null;
  chart: GrimesChartPayload | null;
  checklistOpen: boolean;
  setChecklistOpen: Dispatch<SetStateAction<boolean>>;
};

export function GrimesAdvanced({
  open,
  onClose,
  rightTab,
  data,
  tradeDate,
  loading,
  hasScanDates,
  onRescan,
  overlays,
  setOverlays,
  capitalInr,
  setCapitalInr,
  riskPctPerTrade,
  setRiskPctPerTrade,
  showFundamentals,
  setShowFundamentals,
  knowledge,
  chart,
  checklistOpen,
  setChecklistOpen,
}: Props) {
  return (
    <AdvancedDrawer
      open={open}
      onClose={onClose}
      title="Grimes lab"
      subtitle="Overlays, sizing, guide & diagnostics"
      width={420}
    >
      <AdvancedSection title="Scan">
        <Alert severity="info" className="py-0 text-data-xs">
          Grimes TA lab — market structure, pullbacks, squeezes, failure tests, and R-based
          diagnostics on local daily bars. Select a stock for chart + cached balance sheet / quarterly
          results (Fundamentals panel). Heuristic, not advice. Spec in{" "}
          <code>docs/adam_grimes_complete_framework.md</code>.
        </Alert>
        <p className="text-data-xs text-slate-400">
          All NSE equities with local daily data + Nifty IDX · ★ = F&amp;O
          {data?.trade_date ? ` · as of ${data.trade_date}` : tradeDate ? ` · ${tradeDate}` : ""}
          {data?.has_run === false ? " · no stored scan" : ""}
          {data?.source === "db" && data.has_run !== false ? " · stored run" : data?.source === "scan" ? " · fresh scan" : ""}
          {data ? ` · ${data.analyzed.toLocaleString("en-IN")}/${data.universe_size.toLocaleString("en-IN")} analyzed` : ""}
          {loading ? " · Scanning full universe (may take 1–2 min)…" : ""}
        </p>
        {hasScanDates ? (
          <span className="inline-flex items-center gap-1 text-data-xs text-slate-400">
            <span className="inline-block h-2 w-2 rounded-sm bg-emerald-400" />
            Scan done (calendar marker)
          </span>
        ) : null}
        <Tooltip title="Recompute and overwrite the stored scan for the selected date. Uses local candles through that session. Does not fetch new prices.">
          <span className="block">
            <AppButton
              size="small"
              variant="outlined"
              startIcon={
                <RefreshIcon fontSize="small" className={loading ? "animate-spin" : undefined} />
              }
              onClick={onRescan}
              disabled={loading || !tradeDate}
            >
              Rescan
            </AppButton>
          </span>
        </Tooltip>
      </AdvancedSection>

      <AdvancedSection title="Chart overlays & panels">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-data-sm text-slate-300">
          {(
            [
              ["pivots", "Swings"],
              ["mas", "20/50 MA"],
              ["keltner", "Keltner"],
              ["setups", "Setups"],
              ["riskBox", "R box"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={overlays[key]}
                onChange={(e) => setOverlays((o) => ({ ...o, [key]: e.target.checked }))}
              />
              {label}
            </label>
          ))}
        </div>
        <FormControlLabel
          className="mr-0"
          control={
            <Switch
              size="small"
              checked={showFundamentals}
              onChange={() => setShowFundamentals((v) => !v)}
            />
          }
          label={<span className="text-data-xs text-slate-300">Fundamentals panel</span>}
        />
      </AdvancedSection>

      <AdvancedSection title="Capital & risk">
        <div className="flex flex-wrap gap-2">
          <Tooltip title="Hypothetical trading capital for position-size math only (Grimes fixed-fraction rule). Not linked to your broker.">
            <TextField
              label="Capital (₹)"
              type="number"
              value={capitalInr}
              onChange={(e) => setCapitalInr(Math.max(1_000, Number(e.target.value) || 0))}
              slotProps={{ htmlInput: { min: 1000, step: 50_000 } }}
              className="w-[9.5rem]"
            />
          </Tooltip>
          <Tooltip title="Max loss per idea as % of capital (Grimes: 1% conservative, ~2% aggressive). Shares = (capital × risk%) ÷ |entry − stop|.">
            <TextField
              label="Risk / trade (%)"
              type="number"
              value={riskPctPerTrade}
              onChange={(e) =>
                setRiskPctPerTrade(Math.min(5, Math.max(0.25, Number(e.target.value) || 1)))
              }
              slotProps={{ htmlInput: { min: 0.25, max: 5, step: 0.25 } }}
              className="w-[7.5rem]"
            />
          </Tooltip>
        </div>
      </AdvancedSection>

      <AdvancedSection title="Chart guide" defaultOpen={rightTab === "guide"}>
        <GrimesChartGuide
          compact
          intro={
            knowledge?.chart_guide?.intro ??
            "Plain-language explanations for every marker on the Grimes chart."
          }
          sections={knowledge?.chart_guide?.sections ?? []}
        />
      </AdvancedSection>

      <AdvancedSection title="Diagnostics · MAE / MFE" defaultOpen={rightTab === "diagnostics"}>
        <GrimesDiagnostics data={chart} />
      </AdvancedSection>

      <AdvancedSection title="Knowledge hub" defaultOpen={rightTab === "knowledge"}>
        <AppButton size="small" variant="outlined" onClick={() => setChecklistOpen(true)}>
          Checklist
        </AppButton>
        <GrimesKnowledgeHub
          knowledge={knowledge}
          checklist={chart?.checklist ?? null}
          checklistOpen={checklistOpen}
          onCloseChecklist={() => setChecklistOpen(false)}
        />
      </AdvancedSection>
    </AdvancedDrawer>
  );
}
