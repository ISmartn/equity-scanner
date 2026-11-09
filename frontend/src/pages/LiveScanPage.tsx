import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Radio } from "lucide-react";
import {
  fetchLiveScanSnapshot,
  startLiveScan,
  stopLiveScan,
  type LiveBreakoutRow,
  type LiveCallRow,
  type LiveIndexDriver,
  type LiveJournalRow,
  type LiveMomentumRow,
  type LiveOiRow,
  type LiveScanLevel,
  type LiveScanSnapshot,
  type LiveScanStatus,
} from "@/lib/api";
import { PageToolbar, PctCell, StatChip, ToolbarDivider } from "@/components/dense";
import { LiveScanBacktest } from "@/components/liveScan/LiveScanBacktest";

type Board = "calls" | "momentum" | "breakout" | "oi" | "record" | "backtest";
type Segment = "fno" | "cash";
type StanceFilter = "all" | "buy" | "sell" | "wait" | "stand_aside";

const LIVE = new Set(["starting", "connecting", "connected", "reconnecting"]);

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

function price(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function compact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function rvol(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}x`;
}

function levelLabel(level: LiveScanLevel): string {
  if (level.state === "pending") return "ORB";
  if (level.state === "unavailable" || level.level == null) return "—";
  return price(level.level);
}

function levelClass(state: string): string {
  if (state === "triggered") return "text-gain";
  if (state === "testing") return "text-amber-300";
  if (state === "pending") return "text-sky-300";
  return "text-slate-400";
}

function quadrantClass(quadrant: string): string {
  if (quadrant === "long_buildup") return "text-gain";
  if (quadrant === "short_buildup" || quadrant === "long_unwinding") return "text-loss";
  if (quadrant === "short_covering") return "text-amber-300";
  return "text-slate-400";
}

function ScanBadge({ on }: { on: boolean }) {
  if (!on) return <span className="text-slate-600">—</span>;
  return <span className="rounded bg-sky-500/15 px-1 py-0.5 text-[10px] font-semibold text-sky-300">scan</span>;
}

export function LiveScanPage() {
  const navigate = useNavigate();
  const [board, setBoard] = useState<Board>("calls");
  const [segment, setSegment] = useState<Segment>("fno");
  const [stanceFilter, setStanceFilter] = useState<StanceFilter>("all");
  const [snapshot, setSnapshot] = useState<LiveScanSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        const next = await fetchLiveScanSnapshot(250, segment);
        if (cancelled) return;
        setSnapshot(next);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorText(err));
      }
    };
    void pull();
    const timer = window.setInterval(() => void pull(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [segment]);

  const status: LiveScanStatus | null = snapshot?.status ?? null;
  const running = status ? LIVE.has(status.status) : false;

  const onStart = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await startLiveScan();
      setSnapshot((current) =>
        current
          ? { ...current, status: next, stale: true }
          : {
              board: "all",
              ranked_at: null,
              stale: true,
              totals: { momentum: 0, breakout: 0, oi: 0, calls: 0 },
              status: next,
              momentum: [],
              breakout: [],
              oi: [],
              calls: [],
            },
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    setBusy(true);
    try {
      const next = await stopLiveScan();
      setSnapshot((current) => (current ? { ...current, status: next, stale: true } : current));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const open = (symbol: string) => navigate(`/stock-research?ticker=${encodeURIComponent(symbol)}`);

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-2 p-2">
      <PageToolbar
        right={
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => void onStart()}
              disabled={busy || running}
              className="h-7 rounded-md bg-accent px-2.5 text-data-xs font-semibold text-white disabled:opacity-40"
            >
              Start
            </button>
            <button
              type="button"
              onClick={() => void onStop()}
              disabled={busy || !running}
              className="h-7 rounded-md border border-surface-border bg-surface px-2.5 text-data-xs font-semibold text-slate-200 disabled:opacity-40"
            >
              Stop
            </button>
          </div>
        }
      >
        <span className="inline-flex items-center gap-1 text-data-xs font-semibold text-slate-100">
          <Radio className={`h-3.5 w-3.5 ${status?.status === "connected" ? "text-gain" : "text-slate-400"}`} />
          Live Scan
        </span>
        <ToolbarDivider />
        <StatChip label="Feed" value={status?.status ?? "stopped"} />
        <StatChip label="Symbols" value={status ? `${status.symbols_live}/${status.universe}` : "—"} />
        <StatChip label="F&O" value={status?.fno_symbols ?? "—"} />
        <StatChip label="Cash" value={status?.cash_symbols ?? "—"} />
        <StatChip
          label="Keys"
          value={status ? `${status.subscribed}/${status.full_key_limit ?? 1900}` : "—"}
        />
        <StatChip label="Futures" value={status?.futures_matched ?? "—"} />
        <StatChip
          label="Tick age"
          value={status?.last_tick_age_sec != null ? `${status.last_tick_age_sec.toFixed(1)}s` : "—"}
        />
        {snapshot?.stale ? (
          <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-300">
            Stale
          </span>
        ) : null}
        {status?.session_name === "muhurat" ? (
          <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-300">
            Muhurat 2:20–3:30 pm
          </span>
        ) : null}
        {status?.offhours ? (
          <span className="text-[10px] text-slate-400">After hours — stream stays up until Stop</span>
        ) : null}
        {status?.candle_sync && status.candle_sync.requested > 0 ? (
          <span className="text-[10px] text-slate-400">
            {status.candle_sync.phase === "updating"
              ? `Updating ${status.candle_sync.requested} stocks missing ${status.candle_sync.session}`
              : `Updated ${status.candle_sync.success} of ${status.candle_sync.requested} stocks missing ${status.candle_sync.session}`}
            {status.candle_sync.deferred ? ` · ${status.candle_sync.deferred} deferred` : ""}
          </span>
        ) : null}
      </PageToolbar>

      {error ? (
        <div className="rounded-md border border-loss/40 bg-loss/10 px-2 py-1 text-data-xs text-loss">{error}</div>
      ) : null}

      {segment === "fno" ? (
        <IndexStrip
          rows={(snapshot?.calls ?? []).filter((row) => row.kind === "index")}
          onOpen={open}
        />
      ) : (
        <p className="px-1 text-[11px] text-slate-400">
          Non-F&O cash names on the same full-mode feed. No futures, so there is no open-interest board.
        </p>
      )}

      <div className="flex items-center gap-1">
        {(
          [
            ["fno", "F&O"],
            ["cash", "Non-F&O"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              setSegment(id);
              if (id === "cash" && board === "oi") setBoard("calls");
            }}
            className={`rounded-md border px-2 py-1 text-data-xs font-semibold ${
              segment === id
                ? "border-accent/50 bg-accent/15 text-sky-200"
                : "border-surface-border text-slate-400"
            }`}
          >
            {label}
            <span className="ml-1 tabular-nums text-slate-500">
              {id === "fno" ? (status?.fno_symbols ?? 0) : (status?.cash_symbols ?? 0)}
            </span>
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1">
        {(
          [
            ["calls", "Session Call"],
            ["record", "Record"],
            ["backtest", "Backtest"],
            ["momentum", "Momentum"],
            ["breakout", "Breakout"],
            ["oi", "OI buildup"],
          ] as const
        )
          .filter(([id]) => segment === "fno" || id !== "oi")
          .map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setBoard(id)}
            className={`rounded-md px-2 py-1 text-data-xs font-semibold ${
              board === id ? "bg-accent/20 text-sky-200" : "text-slate-400 hover:text-slate-100"
            }`}
          >
            {label}
            {id === "backtest" ? null : (
              <span className="ml-1 tabular-nums text-slate-500">
                {(id === "record" ? snapshot?.totals?.journal : snapshot?.totals?.[id]) ?? 0}
              </span>
            )}
          </button>
        ))}
      </div>

      {board === "calls" ? (
        <div className="flex items-center gap-1">
          {(
            [
              ["all", "All"],
              ["buy", "Buy"],
              ["sell", "Sell"],
              ["wait", "Wait"],
              ["stand_aside", "Stand aside"],
            ] as const
          ).map(([id, label]) => {
            const count =
              id === "all"
                ? (snapshot?.calls.length ?? 0)
                : (snapshot?.calls.filter((row) => row.stance === id).length ?? 0);
            return (
              <button
                key={id}
                type="button"
                onClick={() => setStanceFilter(id)}
                className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${
                  stanceFilter === id
                    ? "border-accent/50 bg-accent/15 text-sky-200"
                    : "border-surface-border text-slate-400"
                }`}
              >
                {label} {count}
              </button>
            );
          })}
          <span className="text-[10px] text-slate-500">
            Exit is today’s target. Swing can stay open past the close.
          </span>
        </div>
      ) : null}

      <div className="overflow-auto rounded-lg border border-surface-border bg-surface-raised">
        {board === "calls" ? (
          <CallTable
            rows={(snapshot?.calls ?? []).filter((row) => stanceFilter === "all" || row.stance === stanceFilter)}
            onOpen={open}
          />
        ) : null}
        {board === "momentum" ? (
          <MomentumTable rows={snapshot?.momentum ?? []} onOpen={open} />
        ) : null}
        {board === "breakout" ? (
          <BreakoutTable rows={snapshot?.breakout ?? []} onOpen={open} />
        ) : null}
        {board === "oi" ? <OiTable rows={snapshot?.oi ?? []} onOpen={open} /> : null}
        {board === "record" ? (
          <RecordTable rows={snapshot?.journal ?? []} summary={snapshot?.journal_summary} onOpen={open} />
        ) : null}
        {board === "backtest" ? <LiveScanBacktest segment={segment} /> : null}
      </div>
    </div>
  );
}

function recordStatusClass(status: string): string {
  if (status === "target") return "text-gain";
  if (status === "stopped") return "text-loss";
  if (status === "open") return "text-sky-200";
  if (status === "pending") return "text-amber-300";
  return "text-slate-500";
}

function RecordTable({
  rows,
  summary,
  onOpen,
}: {
  rows: LiveJournalRow[];
  summary: LiveScanSnapshot["journal_summary"];
  onOpen: (symbol: string) => void;
}) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-surface-border px-2 py-1.5 text-[10px] text-slate-400">
        <span>{summary?.plans ?? 0} plans</span>
        <span className="text-sky-200">{summary?.open ?? 0} open</span>
        <span className="text-gain">{summary?.target ?? 0} target</span>
        <span className="text-loss">{summary?.stopped ?? 0} stopped</span>
        <span className="text-amber-300">{summary?.pending ?? 0} waiting</span>
        <span>{summary?.cancelled ?? 0} cancelled</span>
        <span>
          Day win {summary?.win_rate_pct == null ? "—" : `${summary.win_rate_pct.toFixed(0)}%`} · avg{" "}
          <PctCell value={summary?.avg_result_pct} />
        </span>
        <span className="text-sky-200">{summary?.swing_open ?? 0} swing carried</span>
        <span className="text-gain">{summary?.swing_target ?? 0} swing target</span>
        <span className="text-loss">{summary?.swing_stopped ?? 0} swing stopped</span>
      </div>
      <table className="w-full min-w-[1280px] border-collapse text-left text-data-xs">
        <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-2 py-1.5 font-medium">Day</th>
            <th className="px-2 py-1.5 font-medium">Swing</th>
            <th className="px-2 py-1.5 font-medium">Side</th>
            <th className="px-2 py-1.5 font-medium">Symbol</th>
            <th className="px-2 py-1.5 text-right font-medium">Last</th>
            <th className="px-2 py-1.5 text-right font-medium">Day %</th>
            <th className="px-2 py-1.5 text-right font-medium">Swing %</th>
            <th className="px-2 py-1.5 text-right font-medium">Entry</th>
            <th className="px-2 py-1.5 text-right font-medium">Stop</th>
            <th className="px-2 py-1.5 text-right font-medium">Exit</th>
            <th className="px-2 py-1.5 text-right font-medium">Swing exit</th>
            <th className="px-2 py-1.5 text-right font-medium">Best</th>
            <th className="px-2 py-1.5 text-right font-medium">Worst</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={13} className="px-2 py-6 text-center text-slate-500">
                No plans yet. A row is saved when a stock or index is given an entry, stop, and exit.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={`${row.symbol}-${row.side}`}
                className={`border-t border-surface-border/70 hover:bg-white/5 ${row.kind === "index" ? "" : "cursor-pointer"}`}
                onClick={() => {
                  if (row.kind !== "index") onOpen(row.symbol);
                }}
              >
                <td className={`px-2 py-1 font-semibold ${recordStatusClass(row.status)}`}>{row.status_label}</td>
                <td className={`px-2 py-1 font-semibold ${recordStatusClass(row.swing_status ?? "")}`}>
                  {row.swing_status_label ?? "—"}
                </td>
                <td className={`px-2 py-1 font-semibold ${row.side === "buy" ? "text-gain" : "text-loss"}`}>
                  {row.side_label}
                </td>
                <td className="px-2 py-1 font-semibold text-slate-100">
                  {row.symbol}
                  {row.kind === "index" ? <span className="ml-1 text-[10px] text-slate-500">index</span> : null}
                </td>
                <td className="px-2 py-1 text-right tabular-nums">{price(row.last_price)}</td>
                <td className="px-2 py-1 text-right"><PctCell value={row.result_pct} /></td>
                <td className="px-2 py-1 text-right"><PctCell value={row.swing_result_pct} /></td>
                <td className="px-2 py-1 text-right tabular-nums text-sky-200">{price(row.entry)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-loss">{price(row.stop)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-gain">{price(row.exit)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-gain">{price(row.swing_exit)}</td>
                <td className="px-2 py-1 text-right"><PctCell value={row.mfe_pct} /></td>
                <td className="px-2 py-1 text-right"><PctCell value={row.mae_pct} /></td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function stanceClass(stance: string): string {
  if (stance === "buy") return "text-gain";
  if (stance === "sell") return "text-loss";
  if (stance === "wait") return "text-amber-300";
  return "text-slate-400";
}

function toneClass(tone: string | undefined): string {
  if (tone === "broad_rise" || tone === "rise") return "font-semibold text-gain";
  if (tone === "broad_drop" || tone === "drop") return "font-semibold text-loss";
  if (tone === "narrow_rise" || tone === "narrow_drop") return "font-semibold text-amber-300";
  return "font-semibold text-slate-400";
}

function DriverLine({
  label,
  drivers,
  onOpen,
}: {
  label: string;
  drivers: LiveIndexDriver[] | undefined;
  onOpen: (symbol: string) => void;
}) {
  if (!drivers || drivers.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[11px] text-slate-500">
      <span>{label}</span>
      {drivers.map((driver) => (
        <button
          key={driver.symbol}
          type="button"
          className="text-slate-200 hover:text-sky-200"
          onClick={() => onOpen(driver.symbol)}
        >
          {driver.symbol} <PctCell value={driver.change_pct} />
        </button>
      ))}
    </div>
  );
}

function IndexStrip({ rows, onOpen }: { rows: LiveCallRow[]; onOpen: (symbol: string) => void }) {
  const bySymbol = new Map(rows.map((row) => [row.symbol, row]));
  const cards = INDEX_PLACEHOLDERS.map((placeholder) => bySymbol.get(placeholder.symbol) ?? placeholder);
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {cards.map((row) => (
        <div key={row.symbol} className="rounded-lg border border-surface-border bg-surface-raised px-2 py-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-data-xs font-semibold text-slate-100">
              {row.company_name || row.symbol}
              <span className="ml-1 text-[10px] font-medium text-slate-500">{row.symbol}</span>
            </span>
            <span className={`text-data-xs font-semibold ${stanceClass(row.stance)}`}>{row.stance_label}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px] tabular-nums">
            <span className="text-slate-200">{price(row.ltp)}</span>
            <PctCell value={row.change_pct} />
            {row.tone_label ? (
              <span className={toneClass(row.tone)}>{row.tone_label}</span>
            ) : null}
            {row.weighted_change_pct != null ? (
              <span className="text-slate-500">
                From stocks <PctCell value={row.weighted_change_pct} />
              </span>
            ) : null}
            <span className="text-slate-500">
              Entry <span className="text-sky-200">{price(row.entry)}</span>
            </span>
            <span className="text-slate-500">
              Stop <span className="text-loss">{price(row.stop)}</span>
            </span>
            <span className="text-slate-500">
              Exit <span className="text-gain">{price(row.exit)}</span>
            </span>
            <span className="text-slate-500">
              Swing <span className="text-gain">{price(row.swing_exit)}</span>
            </span>
          </div>
          {row.breadth_seen != null ? (
            <div className="mt-1 text-[11px] text-slate-400">
              <span className="text-gain">{row.breadth_up ?? 0} up</span>
              <span className="mx-1 text-slate-600">·</span>
              <span className="text-loss">{row.breadth_down ?? 0} down</span>
              <span className="mx-1 text-slate-600">·</span>
              <span>{row.breadth_flat ?? 0} flat</span>
              <span className="mx-1 text-slate-600">·</span>
              <span>
                {row.breadth_seen}/{row.breadth_total ?? row.breadth_seen} stocks
              </span>
            </div>
          ) : null}
          <DriverLine label="Lifting" drivers={row.leaders} onOpen={onOpen} />
          <DriverLine label="Dragging" drivers={row.drags} onOpen={onOpen} />
          {row.read ? <p className="mt-1 text-[11px] text-slate-300">{row.read}</p> : null}
        </div>
      ))}
    </div>
  );
}

const INDEX_PLACEHOLDERS: LiveCallRow[] = [
  {
    symbol: "NIFTY",
    company_name: "Nifty 50",
    sector: "Index",
    kind: "index",
    ltp: null,
    change_pct: null,
    vs_sma_pct: null,
    trend_20_pct: null,
    return_5d_pct: null,
    session_rvol: null,
    stance: "stand_aside",
    stance_label: "Start scan",
    reason: "",
    entry: null,
    stop: null,
    exit: null,
    swing_exit: null,
    quadrant: null,
    on_last_scan: false,
    score: null,
  },
  {
    symbol: "SENSEX",
    company_name: "Sensex",
    sector: "Index",
    kind: "index",
    ltp: null,
    change_pct: null,
    vs_sma_pct: null,
    trend_20_pct: null,
    return_5d_pct: null,
    session_rvol: null,
    stance: "stand_aside",
    stance_label: "Start scan",
    reason: "",
    entry: null,
    stop: null,
    exit: null,
    swing_exit: null,
    quadrant: null,
    on_last_scan: false,
    score: null,
  },
];

function CallTable({ rows, onOpen }: { rows: LiveCallRow[]; onOpen: (symbol: string) => void }) {
  return (
    <table className="w-full min-w-[1280px] border-collapse text-left text-data-xs">
      <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400">
        <tr>
          <th className="px-2 py-1.5 font-medium">Call</th>
          <th className="px-2 py-1.5 font-medium">Symbol</th>
          <th className="px-2 py-1.5 text-right font-medium">LTP</th>
          <th className="px-2 py-1.5 text-right font-medium">Entry</th>
          <th className="px-2 py-1.5 text-right font-medium">Stop</th>
          <th className="px-2 py-1.5 text-right font-medium">Exit</th>
          <th className="px-2 py-1.5 text-right font-medium">Swing</th>
          <th className="px-2 py-1.5 text-right font-medium">Today</th>
          <th className="px-2 py-1.5 text-right font-medium">20d trend</th>
          <th className="px-2 py-1.5 text-right font-medium">vs 20d avg</th>
          <th className="px-2 py-1.5 text-right font-medium">RVOL</th>
          <th className="px-2 py-1.5 font-medium">Why</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={12} className="px-2 py-6 text-center text-slate-500">
              No session calls yet. A buy or sell needs the 20-day trend and a break of yesterday’s candle.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr
              key={row.symbol}
              className={`border-t border-surface-border/70 hover:bg-white/5 ${row.kind === "index" ? "" : "cursor-pointer"}`}
              onClick={() => {
                if (row.kind !== "index") onOpen(row.symbol);
              }}
            >
              <td className={`px-2 py-1 font-semibold ${stanceClass(row.stance)}`}>{row.stance_label}</td>
              <td className="px-2 py-1 font-semibold text-slate-100">
                {row.symbol}
                {row.kind === "index" ? (
                  <span className="ml-1 text-[10px] font-semibold text-slate-400">index</span>
                ) : null}
                {row.on_last_scan ? <span className="ml-1 text-[10px] font-semibold text-sky-300">scan</span> : null}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{price(row.ltp)}</td>
              <td className="px-2 py-1 text-right tabular-nums text-sky-200">{price(row.entry)}</td>
              <td className="px-2 py-1 text-right tabular-nums text-loss">{price(row.stop)}</td>
              <td className="px-2 py-1 text-right tabular-nums text-gain">{price(row.exit)}</td>
              <td className="px-2 py-1 text-right tabular-nums text-gain">{price(row.swing_exit)}</td>
              <td className="px-2 py-1 text-right"><PctCell value={row.change_pct} /></td>
              <td className="px-2 py-1 text-right"><PctCell value={row.trend_20_pct} /></td>
              <td className="px-2 py-1 text-right"><PctCell value={row.vs_sma_pct} /></td>
              <td className="px-2 py-1 text-right tabular-nums">{rvol(row.session_rvol)}</td>
              <td className="max-w-[360px] px-2 py-1 text-slate-300">{row.reason}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function MomentumTable({ rows, onOpen }: { rows: LiveMomentumRow[]; onOpen: (symbol: string) => void }) {
  return (
    <table className="w-full min-w-[860px] border-collapse text-left text-data-xs">
      <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400">
        <tr>
          <th className="px-2 py-1.5 font-medium">Symbol</th>
          <th className="px-2 py-1.5 text-right font-medium">LTP</th>
          <th className="px-2 py-1.5 text-right font-medium">Chg</th>
          <th className="px-2 py-1.5 text-right font-medium">vs VWAP</th>
          <th className="px-2 py-1.5 text-right font-medium">Day range</th>
          <th className="px-2 py-1.5 text-right font-medium">Sess RVOL</th>
          <th className="px-2 py-1.5 text-right font-medium">Burst</th>
          <th className="px-2 py-1.5 font-medium">Scan</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={8} className="px-2 py-6 text-center text-slate-500">
              No live quotes yet. Start the feed to subscribe the F&O universe.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr
              key={row.symbol}
              className="cursor-pointer border-t border-surface-border/70 hover:bg-white/5"
              onClick={() => onOpen(row.symbol)}
            >
              <td className="px-2 py-1 font-semibold text-slate-100">
                {row.symbol}
                <span className="ml-1 font-normal text-slate-500">{row.sector}</span>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{price(row.ltp)}</td>
              <td className="px-2 py-1 text-right"><PctCell value={row.change_pct} /></td>
              <td className="px-2 py-1 text-right"><PctCell value={row.vwap_dist_pct} /></td>
              <td className="px-2 py-1 text-right tabular-nums text-slate-300">
                {row.day_range_pos == null ? "—" : `${Math.round(row.day_range_pos * 100)}%`}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{rvol(row.session_rvol)}</td>
              <td className="px-2 py-1 text-right tabular-nums">{rvol(row.burst_rvol)}</td>
              <td className="px-2 py-1"><ScanBadge on={row.on_last_scan} /></td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function BreakoutTable({ rows, onOpen }: { rows: LiveBreakoutRow[]; onOpen: (symbol: string) => void }) {
  return (
    <table className="w-full min-w-[980px] border-collapse text-left text-data-xs">
      <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400">
        <tr>
          <th className="px-2 py-1.5 font-medium">Symbol</th>
          <th className="px-2 py-1.5 text-right font-medium">LTP</th>
          <th className="px-2 py-1.5 font-medium">State</th>
          <th className="px-2 py-1.5 text-right font-medium">Prev high</th>
          <th className="px-2 py-1.5 text-right font-medium">ORB</th>
          <th className="px-2 py-1.5 text-right font-medium">Pivot</th>
          <th className="px-2 py-1.5 text-right font-medium">Multi-year</th>
          <th className="px-2 py-1.5 font-medium">Scan</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={8} className="px-2 py-6 text-center text-slate-500">
              No live quotes yet.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr
              key={row.symbol}
              className="cursor-pointer border-t border-surface-border/70 hover:bg-white/5"
              onClick={() => onOpen(row.symbol)}
            >
              <td className="px-2 py-1 font-semibold text-slate-100">{row.symbol}</td>
              <td className="px-2 py-1 text-right tabular-nums">{price(row.ltp)}</td>
              <td className={`px-2 py-1 capitalize ${levelClass(row.state)}`}>{row.state}</td>
              <LevelCell level={row.prior_high} />
              <LevelCell level={row.opening_range} />
              <LevelCell level={row.pivot} />
              <LevelCell level={row.multi_year} />
              <td className="px-2 py-1"><ScanBadge on={row.on_last_scan} /></td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function LevelCell({ level }: { level: LiveScanLevel }) {
  return (
    <td className={`px-2 py-1 text-right tabular-nums ${levelClass(level.state)}`}>
      {levelLabel(level)}
      <span className="ml-1 text-[10px] uppercase">{level.state === "unavailable" ? "" : level.state}</span>
    </td>
  );
}

function OiTable({ rows, onOpen }: { rows: LiveOiRow[]; onOpen: (symbol: string) => void }) {
  return (
    <table className="w-full min-w-[980px] border-collapse text-left text-data-xs">
      <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-slate-400">
        <tr>
          <th className="px-2 py-1.5 font-medium">Symbol</th>
          <th className="px-2 py-1.5 text-right font-medium">Cash</th>
          <th className="px-2 py-1.5 text-right font-medium">Future</th>
          <th className="px-2 py-1.5 text-right font-medium">Price</th>
          <th className="px-2 py-1.5 text-right font-medium">OI chg</th>
          <th className="px-2 py-1.5 font-medium">Quadrant</th>
          <th className="px-2 py-1.5 text-right font-medium">Basis</th>
          <th className="px-2 py-1.5 font-medium">Scan</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={8} className="px-2 py-6 text-center text-slate-500">
              No futures quotes yet.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr
              key={row.symbol}
              className="cursor-pointer border-t border-surface-border/70 hover:bg-white/5"
              onClick={() => onOpen(row.symbol)}
            >
              <td className="px-2 py-1 font-semibold text-slate-100">
                {row.symbol}
                <span className="ml-1 font-normal text-slate-500">{row.future_expiry}</span>
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{price(row.cash_ltp)}</td>
              <td className="px-2 py-1 text-right tabular-nums">{price(row.fut_ltp)}</td>
              <td className="px-2 py-1 text-right"><PctCell value={row.price_change_pct} /></td>
              <td className="px-2 py-1 text-right">
                <PctCell value={row.oi_change_pct} />
                <div className="text-[10px] text-slate-500">{compact(row.oi)}</div>
              </td>
              <td className={`px-2 py-1 ${quadrantClass(row.quadrant)}`}>{row.quadrant_label}</td>
              <td className="px-2 py-1 text-right tabular-nums">{price(row.basis)}</td>
              <td className="px-2 py-1"><ScanBadge on={row.on_last_scan} /></td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
