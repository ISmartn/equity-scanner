import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import MenuBookOutlinedIcon from "@mui/icons-material/MenuBookOutlined";
import Dialog from "@mui/material/Dialog";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import { useState } from "react";
import type { GrimesChartGuideSection } from "@/lib/api";
import { GrimesChartGuide } from "./GrimesChartGuide";

type LegendRow = {
  label: string;
  shape: string;
  color: string;
  description: string;
};

const SWING_ROWS: LegendRow[] = [
  {
    label: "HH",
    shape: "●",
    color: "#94a3b8",
    description: "Higher High — peak above the prior peak (bullish structure).",
  },
  {
    label: "HL",
    shape: "●",
    color: "#64748b",
    description: "Higher Low — pullback low holds above the prior low.",
  },
  {
    label: "LH",
    shape: "●",
    color: "#94a3b8",
    description: "Lower High — rally peak below the prior peak (bearish structure).",
  },
  {
    label: "LL",
    shape: "●",
    color: "#64748b",
    description: "Lower Low — new low below the prior low.",
  },
];

const SETUP_ROWS: LegendRow[] = [
  {
    label: "PB",
    shape: "▲ / ▼",
    color: "#34d399",
    description: "Trend pullback — retrace to 20 EMA / 50 SMA.",
  },
  {
    label: "ABC",
    shape: "◆",
    color: "#38bdf8",
    description: "Complex pullback — two-legged A–B–C correction.",
  },
  {
    label: "NR7",
    shape: "◆",
    color: "#fbbf24",
    description: "Volatility squeeze — smallest range in 7 sessions.",
  },
  {
    label: "FT",
    shape: "▼ / ▲",
    color: "#fb7185",
    description: "Failure test — spring or upthrust that rejects.",
  },
  {
    label: "CLX",
    shape: "▼ / ▲",
    color: "#fb923c",
    description: "Climactic bar — outlier range with volume spike.",
  },
  {
    label: "ABS",
    shape: "◆",
    color: "#c084fc",
    description: "Absorption — heavy volume, narrow spread at S/R.",
  },
];

const LINE_ROWS = [
  { label: "20 EMA", color: "#38bdf8", note: "Short-term value / pullback magnet." },
  { label: "50 SMA", color: "#fbbf24", note: "Deeper trend value." },
  { label: "Keltner ±", color: "#94a3b8", note: "EMA ± 1.5× ATR envelope." },
  { label: "Entry", color: "#38bdf8", note: "Trigger level for the active setup." },
  { label: "Stop", color: "#fb7185", note: "Where the idea is wrong (dashed)." },
  { label: "1R / 2R / 3R", color: "#34d399", note: "Targets at 1×, 2×, 3× risk." },
];

type Props = {
  chartGuideIntro?: string;
  chartGuideSections?: GrimesChartGuideSection[];
};

export function GrimesChartLegend({ chartGuideIntro, chartGuideSections = [] }: Props) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState(0);
  const hasGuide = chartGuideSections.length > 0 && Boolean(chartGuideIntro);

  return (
    <>
      <div className="absolute right-2 top-2 z-20 flex gap-0.5">
        {hasGuide ? (
          <IconButton
            size="small"
            aria-label="Chart guide — what to expect"
            onClick={() => {
              setTab(1);
              setOpen(true);
            }}
            className="!bg-[#121820]/90 !text-slate-300 hover:!text-slate-100"
            title="Chart guide"
          >
            <MenuBookOutlinedIcon fontSize="small" />
          </IconButton>
        ) : null}
        <IconButton
          size="small"
          aria-label="Chart legend"
          onClick={() => {
            setTab(0);
            setOpen(true);
          }}
          className="!bg-[#121820]/90 !text-slate-300 hover:!text-slate-100"
          title="Quick legend"
        >
          <InfoOutlinedIcon fontSize="small" />
        </IconButton>
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle className="text-slate-100">
          {hasGuide && tab === 1 ? "Chart guide" : "Chart legend"}
        </DialogTitle>
        {hasGuide ? (
          <div className="flex gap-1 border-b border-surface-border px-3 py-2">
            {(["Quick legend", "What to expect"] as const).map((label, idx) => (
              <button
                key={label}
                type="button"
                onClick={() => setTab(idx)}
                className={`rounded-md px-2.5 py-1 text-[11px] ${
                  tab === idx
                    ? "bg-accent/20 text-accent"
                    : "bg-white/5 text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
        <DialogContent dividers className="max-h-[min(70vh,640px)] overflow-auto">
          {tab === 0 || !hasGuide ? (
            <div className="space-y-4 text-[13px] text-slate-300">
              <section>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Swing pivots (● circle)
                </h3>
                <ul className="space-y-2">
                  {SWING_ROWS.map((r) => (
                    <li key={r.label} className="flex gap-2">
                      <span className="w-10 shrink-0 font-mono text-[12px]" style={{ color: r.color }}>
                        {r.shape} {r.label}
                      </span>
                      <span className="text-slate-400">{r.description}</span>
                    </li>
                  ))}
                </ul>
              </section>
              <section>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Setup badges (◆ circle · ▲▼ arrows)
                </h3>
                <p className="mb-2 text-[11px] text-slate-400">
                  ▲ = long bias · ▼ = short bias · ◆ = context (direction from regime).
                </p>
                <ul className="space-y-2">
                  {SETUP_ROWS.map((r) => (
                    <li key={r.label} className="flex gap-2">
                      <span className="w-14 shrink-0 font-mono text-[12px]" style={{ color: r.color }}>
                        {r.shape} {r.label}
                      </span>
                      <span className="text-slate-400">{r.description}</span>
                    </li>
                  ))}
                </ul>
              </section>
              <section>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Lines &amp; R-box
                </h3>
                <ul className="space-y-1.5">
                  {LINE_ROWS.map((r) => (
                    <li key={r.label} className="flex gap-2">
                      <span className="w-20 shrink-0 font-medium" style={{ color: r.color }}>
                        {r.label}
                      </span>
                      <span className="text-slate-400">{r.note}</span>
                    </li>
                  ))}
                </ul>
              </section>
              <section className="rounded-lg bg-white/5 px-2 py-1.5 text-[11px] text-slate-400">
                ★ = NSE F&amp;O stock · IDX = Nifty 50 · Q = setup quality · Vol% = ATR percentile.
                {hasGuide ? (
                  <>
                    {" "}
                    Open the <strong className="text-slate-400">What to expect</strong> tab for plain-language
                    “what happens next” for each marker.
                  </>
                ) : null}
              </section>
            </div>
          ) : (
            <GrimesChartGuide intro={chartGuideIntro!} sections={chartGuideSections} compact />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
