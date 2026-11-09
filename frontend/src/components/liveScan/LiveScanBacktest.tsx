import { useEffect, useRef, useState, type ReactNode } from "react";
import { ColorType, createChart, type IChartApi } from "lightweight-charts";
import {
  fetchLiveBacktest,
  fetchLiveJournalStats,
  type LiveBacktestGroup,
  type LiveBacktestLeg,
  type LiveBacktestParams,
  type LiveBacktestResult,
  type LiveBacktestTrade,
  type LiveJournalScorecard,
} from "@/lib/api";
import { PctCell, StatChip } from "@/components/dense";

type Segment = "fno" | "cash" | "all";

const DEFAULTS = {
  side: "both",
  reward_r: 2,
  swing_r: 4,
  entry_window_r: 0.35,
  min_efficiency: 0.2,
  risk_min_atr: 0.5,
  risk_max_atr: 1.5,
  max_swing_days: 20,
  cost_pct: 0.05,
} as const;

type Knobs = Omit<LiveBacktestParams, "start" | "end" | "segment">;

const KNOBS: { key: keyof Omit<Knobs, "side">; label: string; step: number; hint: string }[] = [
  { key: "reward_r", label: "Target R", step: 0.25, hint: "Day exit, multiple of the stop distance" },
  { key: "swing_r", label: "Swing R", step: 0.5, hint: "Multi-session target, multiple of the stop distance" },
  { key: "entry_window_r", label: "Entry window R", step: 0.05, hint: "How far a gap may open past the entry and still fill" },
  { key: "min_efficiency", label: "Min efficiency", step: 0.05, hint: "20-day path efficiency below this is a range: no call" },
  { key: "risk_min_atr", label: "Stop min ATR", step: 0.1, hint: "Stop distance floor, in ATR" },
  { key: "risk_max_atr", label: "Stop max ATR", step: 0.1, hint: "Stop distance cap, in ATR" },
  { key: "max_swing_days", label: "Swing days", step: 1, hint: "Sessions a swing may carry before it is closed" },
  { key: "cost_pct", label: "Cost %", step: 0.01, hint: "Round-trip cost and slippage, percent of the fill" },
];

const FUNNEL_LABELS: [string, string][] = [
  ["sessions", "Symbol-days"],
  ["no_trend", "No trend"],
  ["choppy", "Range"],
  ["wrong_side", "Other side"],
  ["no_plan", "No candle"],
  ["through_stop", "Through stop"],
  ["chased_gap", "Chased gap"],
  ["not_triggered", "Not reached"],
  ["cancelled_intraday", "Stopped before entry"],
  ["filled", "Filled"],
];

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function errorText(err: unknown): string {
  if (!(err instanceof Error)) return "Request failed";
  try {
    const parsed = JSON.parse(err.message) as { detail?: string };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* body was plain text */
  }
  return err.message;
}

function rTone(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "text-slate-500";
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-slate-300";
}

function R({ value, digits = 2 }: { value: number | null | undefined; digits?: number }) {
  if (value == null || Number.isNaN(value)) return <span className="text-slate-500">—</span>;
  return (
    <span className={`num ${rTone(value)}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(digits)}R
    </span>
  );
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function LiveScanBacktest({ segment: pageSegment }: { segment: "fno" | "cash" }) {
  const [segment, setSegment] = useState<Segment>(pageSegment);
  const [start, setStart] = useState(isoDaysAgo(365));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const [knobs, setKnobs] = useState<Knobs>({ ...DEFAULTS });
  const [result, setResult] = useState<LiveBacktestResult | null>(null);
  const [record, setRecord] = useState<LiveJournalScorecard | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dimension, setDimension] = useState("side");

  useEffect(() => setSegment(pageSegment), [pageSegment]);

  useEffect(() => {
    let cancelled = false;
    fetchLiveJournalStats(segment, knobs.cost_pct)
      .then((next) => {
        if (!cancelled) setRecord(next);
      })
      .catch((err) => {
        if (!cancelled) setError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [segment, knobs.cost_pct]);

  const run = async (override?: { start: string; end: string }) => {
    setRunning(true);
    setError(null);
    try {
      const next = await fetchLiveBacktest({ start: override?.start ?? start, end: override?.end ?? end, segment, ...knobs });
      setResult(next);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setRunning(false);
    }
  };

  const replayRecord = () => {
    if (!record?.first_session || !record.last_session) return;
    setStart(record.first_session);
    setEnd(record.last_session);
    void run({ start: record.first_session, end: record.last_session });
  };

  const changed = (Object.keys(DEFAULTS) as (keyof Knobs)[]).filter((key) => knobs[key] !== DEFAULTS[key]).length;
  const breakdown = result?.breakdowns.find((item) => item.key === dimension) ?? result?.breakdowns[0];

  return (
    <div className="flex flex-col gap-2 p-2 text-data-xs">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="From">
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={inputClass} />
        </Field>
        <Field label="To">
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Universe">
          <select value={segment} onChange={(e) => setSegment(e.target.value as Segment)} className={inputClass}>
            <option value="fno">F&O + index</option>
            <option value="cash">Non-F&O</option>
            <option value="all">All</option>
          </select>
        </Field>
        <Field label="Side">
          <select
            value={knobs.side}
            onChange={(e) => setKnobs({ ...knobs, side: e.target.value as Knobs["side"] })}
            className={inputClass}
          >
            <option value="both">Both</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </Field>
        {KNOBS.map((knob) => (
          <Field key={knob.key} label={knob.label} hint={knob.hint}>
            <input
              type="number"
              step={knob.step}
              value={knobs[knob.key]}
              onChange={(e) => setKnobs({ ...knobs, [knob.key]: Number(e.target.value) })}
              className={`${inputClass} w-20 ${knobs[knob.key] !== DEFAULTS[knob.key] ? "border-amber-500/60" : ""}`}
            />
          </Field>
        ))}
        <button
          type="button"
          onClick={() => void run()}
          disabled={running}
          className="h-7 rounded-md bg-accent px-3 font-semibold text-white disabled:opacity-40"
        >
          {running ? "Replaying…" : "Run backtest"}
        </button>
        <button
          type="button"
          onClick={() => setKnobs({ ...DEFAULTS })}
          disabled={changed === 0}
          className="h-7 rounded-md border border-surface-border px-2 font-semibold text-slate-300 disabled:opacity-40"
        >
          Live rules{changed ? ` (${changed} changed)` : ""}
        </button>
      </div>
      <p className="text-[11px] text-slate-500">
        Replays the Session Call rules on daily candles: the 20-day trend picks the side, entry on a break of
        yesterday&rsquo;s high or low, stop from the same candle bounded by ATR. Amber fields differ from the live
        board. A year of the full universe takes about 20 seconds; a repeat is served from memory.
      </p>

      {error ? (
        <div className="rounded-md border border-loss/40 bg-loss/10 px-2 py-1 text-loss">{error}</div>
      ) : null}

      <LiveRecord record={record} onReplay={replayRecord} running={running} />

      {result ? <Results result={result} breakdown={breakdown} onDimension={setDimension} /> : null}
    </div>
  );
}

const inputClass =
  "h-7 rounded-md border border-surface-border bg-surface px-1.5 text-data-xs text-slate-100 tabular-nums";

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5" title={hint}>
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function Card({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-surface-border bg-surface">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-2 py-1.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-300">{title}</h3>
        {right}
      </header>
      <div className="p-2">{children}</div>
    </section>
  );
}

function LegChips({ leg, label }: { leg: LiveBacktestLeg; label: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <span className="text-[11px] font-semibold text-slate-200">{label}</span>
      <StatChip label="Trades" value={leg.trades.toLocaleString("en-IN")} />
      <StatChip label="Win" value={pct(leg.win_rate_pct)} />
      <StatChip label="Avg" value={<R value={leg.avg_r} digits={3} />} hint="Average result per trade, in R after costs" />
      <StatChip label="Total" value={<R value={leg.total_r} digits={1} />} />
      <StatChip label="PF" value={num(leg.profit_factor)} hint="Gross wins over gross losses" />
      <StatChip label="Avg win" value={<R value={leg.avg_win_r} />} />
      <StatChip label="Avg loss" value={<R value={leg.avg_loss_r} />} />
      {leg.avg_pct != null ? <StatChip label="Avg %" value={<PctCell value={leg.avg_pct} digits={3} />} /> : null}
      {leg.avg_days != null ? <StatChip label="Days held" value={num(leg.avg_days, 1)} /> : null}
      <span className="text-[10px] text-slate-500">
        {Object.entries(leg.statuses)
          .map(([status, count]) => `${count.toLocaleString("en-IN")} ${status}`)
          .join(" · ")}
      </span>
    </div>
  );
}

function LiveRecord({
  record,
  onReplay,
  running,
}: {
  record: LiveJournalScorecard | null;
  onReplay: () => void;
  running: boolean;
}) {
  const sessions = record?.breakdowns.find((item) => item.key === "session")?.rows ?? [];
  return (
    <Card
      title="Live record — what the board actually did"
      right={
        record?.first_session ? (
          <button
            type="button"
            onClick={onReplay}
            disabled={running}
            className="rounded-md border border-surface-border px-2 py-0.5 text-[10px] font-semibold text-sky-200 disabled:opacity-40"
            title="Run the replay over the same sessions to see how close the daily-candle model is"
          >
            Replay these {record.sessions} sessions
          </button>
        ) : null
      }
    >
      {!record || record.funnel.plans === 0 ? (
        <p className="text-slate-500">No saved plans yet. The record fills as the live scan runs.</p>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="text-[11px] text-slate-400">
            {record.sessions} sessions ({record.first_session} → {record.last_session}) · {record.funnel.plans} plans ·{" "}
            {record.funnel.resolved} resolved · {record.funnel.cancelled} never reached the entry ·{" "}
            {record.funnel.open + record.funnel.pending} still working
          </div>
          <LegChips leg={record.day} label="Day" />
          {record.swing.trades ? <LegChips leg={record.swing} label="Swing" /> : null}
          {sessions.length ? <GroupTable rows={sessions} groupLabel="Session" compact /> : null}
        </div>
      )}
    </Card>
  );
}

function Results({
  result,
  breakdown,
  onDimension,
}: {
  result: LiveBacktestResult;
  breakdown: LiveBacktestResult["breakdowns"][number] | undefined;
  onDimension: (key: string) => void;
}) {
  const bounds = result.day.bounds;
  return (
    <>
      <Card
        title={`Replay ${result.params.start} → ${result.params.end}`}
        right={
          <span className="text-[10px] text-slate-500">
            {result.universe.symbols.toLocaleString("en-IN")} symbols ({result.universe.fno} F&O, {result.universe.cash}{" "}
            non-F&O, {result.universe.index} index) · {(result.elapsed_ms / 1000).toFixed(1)}s
            {result.cached ? " · cached" : ""}
          </span>
        }
      >
        <div className="flex flex-col gap-2">
          {result.warnings.map((warning) => (
            <div key={warning} className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-amber-300">
              {warning}
            </div>
          ))}
          <LegChips leg={result.day} label="Day" />
          {bounds ? (
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded border border-surface-border/70 px-2 py-1">
              <span className="text-[11px] font-semibold text-slate-200">Bar-order range</span>
              <StatChip
                label="Ambiguous"
                value={`${bounds.ambiguous.toLocaleString("en-IN")} (${pct(bounds.ambiguous_pct)})`}
                hint="Trades where one daily bar touched two levels and the order is unknown"
              />
              <StatChip
                label="Minute replay"
                value={(bounds.minute_resolved ?? 0).toLocaleString("en-IN")}
                hint="Ambiguous days settled exactly from stored live minute bars (full sessions only)"
              />
              <StatChip label="Booked avg" value={<R value={result.day.avg_r} digits={3} />} hint="Worse order assumed" />
              <StatChip
                label="Optimistic avg"
                value={<R value={bounds.optimistic_avg_r} digits={3} />}
                hint="Better order assumed; a plan stopped before its entry is dropped as cancelled"
              />
              <StatChip label="Optimistic win" value={pct(bounds.optimistic_win_rate_pct)} />
              <span className="text-[10px] text-slate-500">The true result sits between the two averages.</span>
            </div>
          ) : null}
          <LegChips leg={result.swing} label="Swing" />
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-[11px] font-semibold text-slate-200">Book</span>
            <StatChip label="Sessions" value={result.curve.sessions} />
            <StatChip label="Green sessions" value={pct(result.curve.green_sessions_pct)} />
            <StatChip label="Cum mean R" value={<R value={result.curve.final_r} />} hint="Sum of each session's mean day R" />
            <StatChip label="Max DD" value={<R value={result.curve.max_drawdown_r} />} />
            <StatChip label="Avg MFE" value={<R value={result.day.avg_mfe_r} />} hint="Best price of the day after the fill" />
            <StatChip label="Avg MAE" value={<R value={result.day.avg_mae_r} />} hint="Worst price of the day" />
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400">
            {FUNNEL_LABELS.map(([key, label]) =>
              result.funnel[key] ? (
                <span key={key}>
                  {label} <span className="num text-slate-200">{result.funnel[key].toLocaleString("en-IN")}</span>
                </span>
              ) : null,
            )}
          </div>
        </div>
      </Card>

      <div className="grid gap-2 xl:grid-cols-[2fr_1fr]">
        <Card title="Equal-weight book — cumulative mean day R per session">
          <EquityCurve points={result.curve.points} />
        </Card>
        <Card title="Target sweep — same entries and stops">
          <table className="w-full border-collapse text-left">
            <thead className="text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-1.5 py-1 font-medium">Target</th>
                <th className="px-1.5 py-1 text-right font-medium">Hit</th>
                <th className="px-1.5 py-1 text-right font-medium">Win</th>
                <th className="px-1.5 py-1 text-right font-medium">Avg</th>
                <th className="px-1.5 py-1 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {result.target_sweep.map((row) => (
                <tr
                  key={row.reward_r}
                  className={`border-t border-surface-border/70 ${row.reward_r === result.params.reward_r ? "bg-accent/10" : ""}`}
                >
                  <td className="px-1.5 py-1 tabular-nums text-slate-200">{row.reward_r}R</td>
                  <td className="px-1.5 py-1 text-right tabular-nums">{pct(row.target_pct)}</td>
                  <td className="px-1.5 py-1 text-right tabular-nums">{pct(row.win_rate_pct)}</td>
                  <td className="px-1.5 py-1 text-right"><R value={row.avg_r} digits={3} /></td>
                  <td className="px-1.5 py-1 text-right"><R value={row.total_r} digits={0} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-[10px] text-slate-500">Unhit targets book the close. Stops are unchanged.</p>
        </Card>
      </div>

      <Card title="What separates better and worse trades">
        {result.insights.length === 0 ? (
          <p className="text-slate-500">No group differs from the whole book by more than two standard errors.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {result.insights.map((item) => (
              <li key={`${item.dimension}-${item.group}`} className="flex flex-wrap items-baseline gap-x-2">
                <span className={`w-12 text-[10px] font-semibold uppercase ${item.direction === "better" ? "text-gain" : "text-loss"}`}>
                  {item.direction}
                </span>
                <span className="text-slate-400">{item.dimension}</span>
                <span className="font-semibold text-slate-100">{item.group}</span>
                <span className="text-slate-500">{item.trades.toLocaleString("en-IN")} trades</span>
                <R value={item.avg_r} digits={3} />
                <span className="text-slate-500">
                  ({item.delta_r > 0 ? "+" : ""}
                  {item.delta_r.toFixed(3)}R vs book, t = {item.t_stat})
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-[10px] text-slate-500">
          A filter that keeps only the better groups is a hypothesis. Check it on a different date range before trusting it.
        </p>
      </Card>

      <Card
        title="Breakdown"
        right={
          <div className="flex flex-wrap gap-1">
            {result.breakdowns.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => onDimension(item.key)}
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  (breakdown?.key ?? "") === item.key ? "bg-accent/20 text-sky-200" : "text-slate-400 hover:text-slate-100"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
      >
        {breakdown ? <GroupTable rows={breakdown.rows} groupLabel={breakdown.label} /> : null}
      </Card>

      <div className="grid gap-2 xl:grid-cols-2">
        <Card title="Best symbols (5+ trades)">
          <GroupTable rows={result.symbols.best} groupLabel="Symbol" compact />
        </Card>
        <Card title="Worst symbols (5+ trades)">
          <GroupTable rows={result.symbols.worst} groupLabel="Symbol" compact />
        </Card>
      </div>

      <Card title={`Most recent ${result.trades.length} trades`}>
        <TradeTable rows={result.trades} />
      </Card>

      <ul className="list-disc pl-5 text-[10px] text-slate-500">
        {result.assumptions.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </>
  );
}

function GroupTable({ rows, groupLabel, compact = false }: { rows: LiveBacktestGroup[]; groupLabel: string; compact?: boolean }) {
  if (rows.length === 0) return <p className="text-slate-500">Not enough trades.</p>;
  const showSwing = rows.some((row) => row.swing_trades);
  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-left">
        <thead className="text-[10px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-1.5 py-1 font-medium">{groupLabel}</th>
            <th className="px-1.5 py-1 text-right font-medium">Trades</th>
            <th className="px-1.5 py-1 text-right font-medium">Win</th>
            <th className="px-1.5 py-1 text-right font-medium">Avg</th>
            <th className="px-1.5 py-1 text-right font-medium">Total</th>
            {!compact ? <th className="px-1.5 py-1 text-right font-medium">PF</th> : null}
            {!compact && rows.some((row) => row.target_pct != null) ? (
              <>
                <th className="px-1.5 py-1 text-right font-medium">Target</th>
                <th className="px-1.5 py-1 text-right font-medium">Stopped</th>
              </>
            ) : null}
            {showSwing ? (
              <>
                <th className="px-1.5 py-1 text-right font-medium">Swing avg</th>
                <th className="px-1.5 py-1 text-right font-medium">Swing win</th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.group} className="border-t border-surface-border/70">
              <td className="px-1.5 py-1 font-semibold text-slate-100">{row.group}</td>
              <td className="px-1.5 py-1 text-right tabular-nums">{row.trades.toLocaleString("en-IN")}</td>
              <td className="px-1.5 py-1 text-right tabular-nums">{pct(row.win_rate_pct)}</td>
              <td className="px-1.5 py-1 text-right"><R value={row.avg_r} digits={3} /></td>
              <td className="px-1.5 py-1 text-right"><R value={row.total_r} digits={1} /></td>
              {!compact ? <td className="px-1.5 py-1 text-right tabular-nums">{num(row.profit_factor)}</td> : null}
              {!compact && row.target_pct != null ? (
                <>
                  <td className="px-1.5 py-1 text-right tabular-nums text-gain">{pct(row.target_pct)}</td>
                  <td className="px-1.5 py-1 text-right tabular-nums text-loss">{pct(row.stopped_pct)}</td>
                </>
              ) : null}
              {showSwing ? (
                <>
                  <td className="px-1.5 py-1 text-right"><R value={row.swing_avg_r} digits={3} /></td>
                  <td className="px-1.5 py-1 text-right tabular-nums">{pct(row.swing_win_rate_pct)}</td>
                </>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const FILL_LABELS: Record<string, string> = {
  level: "Crossed",
  open: "Gap",
  pullback: "Pullback",
  recovery: "Recovery",
};

function statusClass(status: string): string {
  if (status === "target") return "text-gain";
  if (status === "stopped") return "text-loss";
  if (status === "open") return "text-sky-200";
  return "text-slate-400";
}

function TradeTable({ rows }: { rows: LiveBacktestTrade[] }) {
  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full min-w-[1100px] border-collapse text-left">
        <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-1.5 py-1 font-medium">Date</th>
            <th className="px-1.5 py-1 font-medium">Symbol</th>
            <th className="px-1.5 py-1 font-medium">Side</th>
            <th className="px-1.5 py-1 font-medium">Fill</th>
            <th className="px-1.5 py-1 text-right font-medium">Entry</th>
            <th className="px-1.5 py-1 text-right font-medium">Filled</th>
            <th className="px-1.5 py-1 text-right font-medium">Stop</th>
            <th className="px-1.5 py-1 text-right font-medium">Target</th>
            <th className="px-1.5 py-1 font-medium">Day</th>
            <th className="px-1.5 py-1 text-right font-medium">Day R</th>
            <th className="px-1.5 py-1 text-right font-medium">MFE</th>
            <th className="px-1.5 py-1 font-medium">Swing</th>
            <th className="px-1.5 py-1 text-right font-medium">Swing R</th>
            <th className="px-1.5 py-1 text-right font-medium">Days</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.trade_date}-${row.symbol}-${row.side}`} className="border-t border-surface-border/70">
              <td className="px-1.5 py-1 tabular-nums text-slate-400">{row.trade_date}</td>
              <td className="px-1.5 py-1 font-semibold text-slate-100">
                {row.symbol}
                {row.segment === "cash" ? <span className="ml-1 text-[10px] text-slate-500">cash</span> : null}
              </td>
              <td className={`px-1.5 py-1 font-semibold ${row.side === "buy" ? "text-gain" : "text-loss"}`}>
                {row.side === "buy" ? "Buy" : "Sell"}
              </td>
              <td className="px-1.5 py-1 text-slate-300">
                {FILL_LABELS[row.fill_type] ?? row.fill_type}
                {row.ambiguous ? (
                  <span className="ml-1 text-[10px] text-amber-300" title="The daily bar cannot say which level came first">
                    ?
                  </span>
                ) : null}
              </td>
              <td className="px-1.5 py-1 text-right tabular-nums text-sky-200">{num(row.entry)}</td>
              <td className="px-1.5 py-1 text-right tabular-nums">{num(row.fill)}</td>
              <td className="px-1.5 py-1 text-right tabular-nums text-loss">{num(row.stop)}</td>
              <td className="px-1.5 py-1 text-right tabular-nums text-gain">{num(row.target)}</td>
              <td className={`px-1.5 py-1 capitalize ${statusClass(row.day_status)}`}>{row.day_status}</td>
              <td className="px-1.5 py-1 text-right"><R value={row.day_r} /></td>
              <td className="px-1.5 py-1 text-right"><R value={row.mfe_r} /></td>
              <td className={`px-1.5 py-1 capitalize ${statusClass(row.swing_status)}`}>{row.swing_status}</td>
              <td className="px-1.5 py-1 text-right"><R value={row.swing_r} /></td>
              <td className="px-1.5 py-1 text-right tabular-nums text-slate-400">{row.swing_days}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EquityCurve({ points }: { points: LiveBacktestResult["curve"]["points"] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      layout: { background: { type: ColorType.Solid, color: "#1a2332" }, textColor: "#94a3b8" },
      grid: { vertLines: { color: "#2a3544" }, horzLines: { color: "#2a3544" } },
      rightPriceScale: { borderColor: "#2a3544" },
      timeScale: { borderColor: "#2a3544" },
      width: el.clientWidth || 640,
      height: 260,
    });
    chartRef.current = chart;
    const cumulative = chart.addLineSeries({ color: "#38bdf8", lineWidth: 2, title: "cum R" });
    cumulative.setData(points.map((point) => ({ time: point.date, value: point.cum_r })));
    const daily = chart.addHistogramSeries({ priceScaleId: "daily", title: "session R" });
    chart.priceScale("daily").applyOptions({ scaleMargins: { top: 0.75, bottom: 0 } });
    daily.setData(
      points.map((point) => ({
        time: point.date,
        value: point.mean_r,
        color: point.mean_r >= 0 ? "rgba(34,197,94,0.5)" : "rgba(239,68,68,0.5)",
      })),
    );
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    observer.observe(el);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [points]);

  if (points.length === 0) return <p className="text-slate-500">No trades in this range.</p>;
  return <div ref={containerRef} className="w-full" />;
}
