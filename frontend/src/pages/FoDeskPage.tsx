import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Radio } from "lucide-react";
import { PageToolbar, PctCell, StatChip, ToolbarDivider } from "@/components/dense";
import {
  startLiveScan,
  stopLiveScan,
  type LiveCallRow,
  type LiveScanStatus,
} from "@/lib/api";

type StanceFilter = "action" | "buy" | "sell" | "wait" | "stand_aside" | "all";

const LIVE = new Set(["starting", "connecting", "connected", "reconnecting"]);

interface CallBoard {
  calls: LiveCallRow[];
  status: LiveScanStatus | null;
  stale: boolean;
  rankedAt: number | null;
  total: number;
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

function price(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function rvol(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}x`;
}

function futuresLabel(quadrant: string | null | undefined): string {
  if (quadrant === "long_buildup") return "Long build";
  if (quadrant === "short_buildup") return "Short build";
  if (quadrant === "short_covering") return "Short cover";
  if (quadrant === "long_unwinding") return "Long unwind";
  if (quadrant === "neutral") return "Neutral";
  return "—";
}

function quadrantClass(quadrant: string): string {
  if (quadrant === "long_buildup") return "text-gain";
  if (quadrant === "short_buildup" || quadrant === "long_unwinding") return "text-loss";
  if (quadrant === "short_covering") return "text-amber-300";
  return "text-slate-400";
}

function stanceClass(stance: string): string {
  if (stance === "buy") return "text-gain";
  if (stance === "sell") return "text-loss";
  if (stance === "wait") return "text-amber-300";
  return "text-slate-400";
}

async function fetchCalls(): Promise<CallBoard> {
  const res = await fetch("/api/live-scan/snapshot?board=calls&limit=500&segment=fno");
  if (!res.ok) throw new Error(await res.text());
  const body = (await res.json()) as {
    rows?: LiveCallRow[];
    status?: LiveScanStatus;
    stale?: boolean;
    ranked_at?: number | null;
    total?: number;
  };
  const calls = body.rows ?? [];
  return {
    calls,
    status: body.status ?? null,
    stale: Boolean(body.stale),
    rankedAt: body.ranked_at ?? null,
    total: body.total ?? calls.length,
  };
}

export function FoDeskPage() {
  const navigate = useNavigate();
  const [board, setBoard] = useState<CallBoard>({
    calls: [],
    status: null,
    stale: true,
    rankedAt: null,
    total: 0,
  });
  const [filter, setFilter] = useState<StanceFilter>("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        const next = await fetchCalls();
        if (cancelled) return;
        setBoard(next);
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
  }, []);

  const running = board.status ? LIVE.has(board.status.status) : false;
  const counts = useMemo(() => {
    const next = { buy: 0, sell: 0, wait: 0, stand_aside: 0 };
    for (const row of board.calls) {
      if (row.stance === "buy" || row.stance === "sell" || row.stance === "wait" || row.stance === "stand_aside") {
        next[row.stance] += 1;
      }
    }
    return next;
  }, [board.calls]);

  const rows = useMemo(() => {
    const q = query.trim().toUpperCase();
    return board.calls.filter((row) => {
      if (filter === "action" && row.stance !== "buy" && row.stance !== "sell") return false;
      if (filter !== "action" && filter !== "all" && row.stance !== filter) return false;
      if (q && !row.symbol.includes(q) && !(row.company_name ?? "").toUpperCase().includes(q)) return false;
      return true;
    });
  }, [board.calls, filter, query]);

  const onStart = async () => {
    setBusy(true);
    setError(null);
    try {
      const status = await startLiveScan();
      setBoard((current) => ({ ...current, status }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    setBusy(true);
    try {
      const status = await stopLiveScan();
      setBoard((current) => ({ ...current, status }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const open = (row: LiveCallRow) => {
    if (row.kind === "index") return;
    navigate(`/stock-research?ticker=${encodeURIComponent(row.symbol)}`);
  };

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
          <Radio className={`h-3.5 w-3.5 ${board.status?.status === "connected" ? "text-gain" : "text-slate-400"}`} />
          F&O calls
        </span>
        <ToolbarDivider />
        <StatChip label="Feed" value={board.status?.status ?? "stopped"} />
        <StatChip label="Names" value={board.total || "—"} />
        <StatChip label="Buy" value={counts.buy} />
        <StatChip label="Sell" value={counts.sell} />
        <StatChip
          label="Ranked"
          value={
            board.rankedAt
              ? new Date(board.rankedAt * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
              : "—"
          }
        />
      </PageToolbar>

      {error ? (
        <div className="rounded-md border border-loss/40 bg-loss/10 px-2 py-1 text-data-xs text-loss">{error}</div>
      ) : null}

      <div className="flex flex-wrap items-center gap-1">
        {(
          [
            ["action", "Buy & sell", counts.buy + counts.sell],
            ["buy", "Buy", counts.buy],
            ["sell", "Sell", counts.sell],
            ["wait", "Wait", counts.wait],
            ["stand_aside", "Stand aside", counts.stand_aside],
            ["all", "All", board.calls.length],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            onClick={() => setFilter(id)}
            className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${
              filter === id ? "border-accent/50 bg-accent/15 text-sky-200" : "border-surface-border text-slate-400"
            }`}
          >
            {label} {count}
          </button>
        ))}
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value.toUpperCase())}
          placeholder="Symbol"
          aria-label="Filter symbols"
          className="ml-1 w-28 rounded border border-surface-border bg-surface px-2 py-0.5 text-data-xs text-slate-100"
        />
        <span className="text-[10px] text-slate-500">
          Same session call as Live Scan, for every F&O stock and index. Exit is 2R. Swing is 2.5R.
        </span>
      </div>

      <div className="overflow-auto rounded-lg border border-surface-border bg-surface-raised">
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
              <th className="px-2 py-1.5 font-medium">Futures</th>
              <th className="px-2 py-1.5 font-medium">Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={13} className="px-2 py-6 text-center text-slate-500">
                  {board.calls.length === 0
                    ? "No calls yet. Start the scan. A name is a buy or a sell only when it clears the Live Scan gates."
                    : "Nothing in this filter."}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={row.symbol}
                  className={`border-t border-surface-border/70 hover:bg-white/5 ${row.kind === "index" ? "" : "cursor-pointer"}`}
                  onClick={() => open(row)}
                >
                  <td className={`px-2 py-1 font-semibold ${stanceClass(row.stance)}`}>{row.stance_label}</td>
                  <td className="px-2 py-1 font-semibold text-slate-100">
                    {row.symbol}
                    {row.kind === "index" ? <span className="ml-1 text-[10px] font-semibold text-slate-400">index</span> : null}
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
                  <td className={`px-2 py-1 ${quadrantClass(row.quadrant ?? "")}`}>
                    {futuresLabel(row.quadrant)}
                    {row.oi_change_pct == null ? "" : ` ${row.oi_change_pct > 0 ? "+" : ""}${row.oi_change_pct.toFixed(1)}%`}
                  </td>
                  <td className="max-w-[360px] px-2 py-1 text-slate-300">{row.reason}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
