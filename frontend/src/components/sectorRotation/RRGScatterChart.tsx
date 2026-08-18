import type { SectorQuadrant, SectorRotationRow } from "@/lib/api";

type Props = {
  sectors: SectorRotationRow[];
  selectedName: string | null;
  onSelect: (name: string) => void;
};

const PAD = { top: 32, right: 20, bottom: 44, left: 52 };

const QUAD_COLOR: Record<SectorQuadrant, string> = {
  Leading: "rgb(52 211 153)",
  Weakening: "rgb(251 191 36)",
  Lagging: "rgb(251 113 133)",
  Improving: "rgb(56 189 248)",
};

function clampDomain(values: number[], padRatio = 0.12): [number, number] {
  if (!values.length) return [92, 108];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(6, max - min);
  const pad = span * padRatio;
  return [Math.min(min - pad, 100 - 3), Math.max(max + pad, 100 + 3)];
}

function shortLabel(name: string): string {
  return name
    .replace(/^Nifty\s+/i, "")
    .replace(/\s+&\s+/g, "/")
    .replace(/\s+/g, " ")
    .trim();
}

/** Official index = diamond; synthetic theme = circle. */
function SectorMarker({
  cx,
  cy,
  r,
  official,
  fill,
  fillOpacity = 1,
  stroke,
  strokeWidth = 1,
}: {
  cx: number;
  cy: number;
  r: number;
  official: boolean;
  fill: string;
  fillOpacity?: number;
  stroke: string;
  strokeWidth?: number;
}) {
  if (official) {
    const d = `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`;
    return (
      <path
        d={d}
        fill={fill}
        fillOpacity={fillOpacity}
        stroke={stroke}
        strokeWidth={strokeWidth}
      />
    );
  }
  return (
    <circle
      cx={cx}
      cy={cy}
      r={r}
      fill={fill}
      fillOpacity={fillOpacity}
      stroke={stroke}
      strokeWidth={strokeWidth}
    />
  );
}

export function RRGScatterChart({ sectors, selectedName, onSelect }: Props) {
  const width = 640;
  const height = 420;
  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;

  const xs = sectors.map((s) => s.rs_ratio);
  const ys = sectors.map((s) => s.rs_momentum);
  const [xMin, xMax] = clampDomain(xs);
  const [yMin, yMax] = clampDomain(ys);

  const sx = (v: number) => PAD.left + ((v - xMin) / (xMax - xMin || 1)) * innerW;
  const sy = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * innerH;
  const x100 = sx(100);
  const y100 = sy(100);

  const selected = sectors.find((s) => s.name === selectedName) ?? null;

  const labelNames = new Set<string>();
  if (selected) labelNames.add(selected.name);
  if (sectors.length) {
    const byRatio = [...sectors].sort((a, b) => b.rs_ratio - a.rs_ratio);
    const byMom = [...sectors].sort((a, b) => b.rs_momentum - a.rs_momentum);
    [byRatio[0], byRatio[byRatio.length - 1], byMom[0], byMom[byMom.length - 1]].forEach((s) => {
      if (s) labelNames.add(s.name);
    });
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-surface-border bg-surface-raised p-2">
      <div className="mb-1 flex items-center justify-between gap-2 px-1">
        <div>
          <h3 className="text-[11px] font-medium text-slate-200">Relative Rotation Graph</h3>
          <p className="text-[9px] text-slate-500">
            ◆ Official index · ● Theme · click to load stocks · trail = selection only
          </p>
        </div>
        <div className="hidden flex-wrap gap-x-2 gap-y-0.5 text-[8px] text-slate-500 sm:flex">
          <span className="text-emerald-400">● Leading</span>
          <span className="text-amber-300">● Weakening</span>
          <span className="text-rose-300">● Lagging</span>
          <span className="text-sky-300">● Improving</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="min-h-0 w-full flex-1" role="img">
        <rect
          x={x100}
          y={PAD.top}
          width={Math.max(0, PAD.left + innerW - x100)}
          height={Math.max(0, y100 - PAD.top)}
          fill="rgb(16 185 129 / 0.07)"
        />
        <rect
          x={x100}
          y={y100}
          width={Math.max(0, PAD.left + innerW - x100)}
          height={Math.max(0, PAD.top + innerH - y100)}
          fill="rgb(234 179 8 / 0.07)"
        />
        <rect
          x={PAD.left}
          y={y100}
          width={Math.max(0, x100 - PAD.left)}
          height={Math.max(0, PAD.top + innerH - y100)}
          fill="rgb(244 63 94 / 0.07)"
        />
        <rect
          x={PAD.left}
          y={PAD.top}
          width={Math.max(0, x100 - PAD.left)}
          height={Math.max(0, y100 - PAD.top)}
          fill="rgb(56 189 248 / 0.07)"
        />

        <line
          x1={x100}
          y1={PAD.top}
          x2={x100}
          y2={PAD.top + innerH}
          stroke="rgb(148 163 184 / 0.4)"
          strokeDasharray="4 4"
        />
        <line
          x1={PAD.left}
          y1={y100}
          x2={PAD.left + innerW}
          y2={y100}
          stroke="rgb(148 163 184 / 0.4)"
          strokeDasharray="4 4"
        />
        <rect
          x={PAD.left}
          y={PAD.top}
          width={innerW}
          height={innerH}
          fill="none"
          stroke="rgb(51 65 85)"
        />

        <text
          x={PAD.left + innerW - 4}
          y={PAD.top + 12}
          textAnchor="end"
          className="fill-emerald-400/70"
          style={{ fontSize: 9 }}
        >
          Leading
        </text>
        <text
          x={PAD.left + innerW - 4}
          y={PAD.top + innerH - 6}
          textAnchor="end"
          className="fill-amber-300/70"
          style={{ fontSize: 9 }}
        >
          Weakening
        </text>
        <text x={PAD.left + 4} y={PAD.top + innerH - 6} className="fill-rose-300/70" style={{ fontSize: 9 }}>
          Lagging
        </text>
        <text x={PAD.left + 4} y={PAD.top + 12} className="fill-sky-300/70" style={{ fontSize: 9 }}>
          Improving
        </text>

        <text
          x={PAD.left + innerW / 2}
          y={height - 12}
          textAnchor="middle"
          className="fill-slate-400"
          style={{ fontSize: 10 }}
        >
          RS-Ratio (relative strength)
        </text>
        <text
          x={14}
          y={PAD.top + innerH / 2}
          textAnchor="middle"
          transform={`rotate(-90 14 ${PAD.top + innerH / 2})`}
          className="fill-slate-400"
          style={{ fontSize: 10 }}
        >
          RS-Momentum
        </text>
        <text x={x100 + 4} y={PAD.top + innerH + 14} className="fill-slate-500" style={{ fontSize: 8 }}>
          100
        </text>
        <text x={PAD.left - 6} y={y100 + 3} textAnchor="end" className="fill-slate-500" style={{ fontSize: 8 }}>
          100
        </text>

        {sectors.map((s) => {
          if (selectedName === s.name) return null;
          const color = QUAD_COLOR[s.quadrant];
          const official = s.category === "Official";
          return (
            <g
              key={s.name}
              className="cursor-pointer"
              onClick={() => onSelect(s.name)}
              opacity={0.9}
            >
              <title>
                {s.name} ({official ? "Official index" : "Theme"}): RS {s.rs_ratio.toFixed(1)} · Mom{" "}
                {s.rs_momentum.toFixed(1)} · {s.quadrant}
                {s.rotation_path ? ` · ${s.rotation_path}` : ""}
                {s.rotation_note ? `\n${s.rotation_note}` : ""}
              </title>
              <SectorMarker
                cx={sx(s.rs_ratio)}
                cy={sy(s.rs_momentum)}
                r={official ? 5.5 : 4.5}
                official={official}
                fill={color}
                fillOpacity={0.9}
                stroke={official ? "rgb(253 224 71)" : "rgb(15 23 42)"}
                strokeWidth={official ? 1.4 : 1}
              />
              {labelNames.has(s.name) ? (
                <text
                  x={sx(s.rs_ratio) + 7}
                  y={sy(s.rs_momentum) - 6}
                  className="fill-slate-400"
                  style={{ fontSize: 8 }}
                >
                  {shortLabel(s.name).length > 16
                    ? `${shortLabel(s.name).slice(0, 14)}…`
                    : shortLabel(s.name)}
                </text>
              ) : null}
            </g>
          );
        })}

        {selected ? (
          <g className="cursor-pointer" onClick={() => onSelect(selected.name)}>
            {(() => {
              const trail = selected.trail_5d.length
                ? selected.trail_5d
                : [{ rs_ratio: selected.rs_ratio, rs_momentum: selected.rs_momentum }];
              const path = trail
                .map(
                  (p, i) =>
                    `${i === 0 ? "M" : "L"}${sx(p.rs_ratio)},${sy(p.rs_momentum)}`,
                )
                .join(" ");
              const color = QUAD_COLOR[selected.quadrant];
              const official = selected.category === "Official";
              return (
                <>
                  <path
                    d={path}
                    fill="none"
                    stroke={color}
                    strokeWidth={2}
                    strokeOpacity={0.7}
                  />
                  {trail.slice(0, -1).map((p, i) => (
                    <circle
                      key={`t-${i}`}
                      cx={sx(p.rs_ratio)}
                      cy={sy(p.rs_momentum)}
                      r={2}
                      fill={color}
                      fillOpacity={0.45}
                    />
                  ))}
                  <SectorMarker
                    cx={sx(selected.rs_ratio)}
                    cy={sy(selected.rs_momentum)}
                    r={official ? 9 : 7}
                    official={official}
                    fill={color}
                    stroke="rgb(248 250 252)"
                    strokeWidth={2}
                  />
                  <text
                    x={sx(selected.rs_ratio) + 12}
                    y={sy(selected.rs_momentum) - 8}
                    className="fill-slate-100"
                    style={{ fontSize: 10, fontWeight: 600 }}
                  >
                    {shortLabel(selected.name)}
                    {official ? " ◆" : ""}
                  </text>
                  <title>
                    {selected.name}: RS {selected.rs_ratio.toFixed(1)} · Mom{" "}
                    {selected.rs_momentum.toFixed(1)} · {selected.quadrant}
                    {selected.rotation_path ? ` · ${selected.rotation_path}` : ""}
                    {selected.rotation_note ? `\n${selected.rotation_note}` : ""}
                  </title>
                </>
              );
            })()}
          </g>
        ) : null}
      </svg>
    </div>
  );
}
