import { TimelineStockChart } from "@/components/TimelineStockChart";
import { RecentNewsFeed } from "@/components/news/RecentNewsFeed";
import { AppButton, FieldLabel } from "@/components/mui";
import {
  fetchNewsEvent,
  fetchNewsEvents,
  fetchNewsMessages,
  fetchNewsOutlook,
  fetchNewsStats,
  fetchTimelineCandles,
  startNewsLive,
  stopNewsLive,
  syncNews,
  type NewsEvent,
  type NewsStats,
  type TelegramNewsMessage,
  type TimelineCandlePoint,
} from "@/lib/api";
import RefreshIcon from "@mui/icons-material/Refresh";
import RadioButtonCheckedIcon from "@mui/icons-material/RadioButtonChecked";
import StopCircleIcon from "@mui/icons-material/StopCircle";
import SyncIcon from "@mui/icons-material/Sync";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { Newspaper, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

const HORIZON_LABELS: Record<string, string> = {
  t_m2: "T-2",
  t_m1: "T-1",
  t0: "T+0",
  t1: "T+1",
  t2: "T+2",
  t3: "T+3",
  t4: "T+4",
  t5: "T+5",
};

function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function sentimentClass(sentiment: string | null | undefined): string {
  if (sentiment === "bullish") return "text-emerald-400";
  if (sentiment === "bearish") return "text-red-400";
  return "text-slate-300";
}

function reactionFor(event: NewsEvent, horizon: string): number | null {
  const hit = event.reactions?.find((r) => r.horizon === horizon);
  return hit?.return_pct ?? null;
}

type FeedMode = "all" | "linked";

export function NewsImpactPage() {
  const [feedMode, setFeedMode] = useState<FeedMode>("all");
  const [stats, setStats] = useState<NewsStats | null>(null);
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [messages, setMessages] = useState<TelegramNewsMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [ticker, setTicker] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<NewsEvent | null>(null);
  const [selectedMessage, setSelectedMessage] = useState<TelegramNewsMessage | null>(null);
  const [detail, setDetail] = useState<NewsEvent | null>(null);
  const [chartHistory, setChartHistory] = useState<TimelineCandlePoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [outlookLoading, setOutlookLoading] = useState(false);
  const [liveBusy, setLiveBusy] = useState(false);
  const [monitorTopic, setMonitorTopic] = useState<string>("");

  const loadStats = useCallback(async () => {
    try {
      setStats(await fetchNewsStats());
    } catch {
      /* ignore */
    }
  }, []);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchNewsEvents({
        ticker: ticker.trim() || undefined,
        sentiment: sentiment || undefined,
        status: "linked",
        limit: 80,
      });
      setEvents(res.results);
      setTotal(res.total);
      setSelected((prev) => {
        if (prev && res.results.some((e) => e.id === prev.id)) return prev;
        return res.results[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [ticker, sentiment]);

  const loadMessages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchNewsMessages({
        limit: 100,
        topic: monitorTopic || undefined,
      });
      setMessages(res.results);
      setTotal(res.total);
      setSelectedMessage((prev) => {
        if (prev && res.results.some((m) => m.id === prev.id)) return prev;
        return res.results[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [monitorTopic]);

  const refreshFeed = useCallback(async () => {
    await loadStats();
    if (feedMode === "all") await loadMessages();
    else await loadEvents();
  }, [feedMode, loadStats, loadMessages, loadEvents]);

  useEffect(() => {
    void refreshFeed();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on mode/topic change
  }, [feedMode, monitorTopic]);

  useEffect(() => {
    if (!stats?.live?.running) return;
    const id = window.setInterval(() => {
      void loadStats();
      if (feedMode === "all") void loadMessages();
    }, 15000);
    return () => window.clearInterval(id);
  }, [stats?.live?.running, feedMode, loadStats, loadMessages]);

  const onToggleLive = async () => {
    setLiveBusy(true);
    setError(null);
    try {
      if (stats?.live?.running) {
        await stopNewsLive();
      } else {
        await startNewsLive({ catch_up: true, process: true });
      }
      await refreshFeed();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await loadStats();
    } finally {
      setLiveBusy(false);
    }
  };
  useEffect(() => {
    if (feedMode !== "linked" || !selected?.id) {
      if (feedMode !== "linked") setDetail(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const ev = await fetchNewsEvent(selected.id);
        if (!cancelled) setDetail(ev);
      } catch {
        if (!cancelled) setDetail(selected);
      }
      if (!selected.ticker) {
        setChartHistory([]);
        return;
      }
      setChartLoading(true);
      try {
        const candles = await fetchTimelineCandles(selected.ticker);
        if (!cancelled) setChartHistory(candles.history);
      } catch {
        if (!cancelled) setChartHistory([]);
      } finally {
        if (!cancelled) setChartLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, feedMode]);

  const extraMarkers = useMemo(() => {
    if (!selected?.ticker) return [];
    return events
      .filter((e) => e.ticker === selected.ticker && e.event_date)
      .map((e) => ({
        date: e.event_date as string,
        sentiment: e.sentiment,
        label: e.sentiment?.slice(0, 1).toUpperCase() || "N",
      }));
  }, [events, selected]);

  const onSync = async (backfill: boolean) => {
    setSyncing(true);
    setError(null);
    try {
      await syncNews({ backfill, limit: 500, process: true });
      await refreshFeed();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  const onOutlook = async () => {
    if (!selected) return;
    setOutlookLoading(true);
    setError(null);
    try {
      const updated = await fetchNewsOutlook(selected.id);
      setDetail(updated);
      setSelected(updated);
      setEvents((prev) => prev.map((e) => (e.id === updated.id ? { ...e, outlook: updated.outlook } : e)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOutlookLoading(false);
    }
  };

  const highlightMove = selected ? reactionFor(selected, "t0") : null;
  const channelHint = stats?.channels?.join(", ") || "@indiaredboxglobal";
  const liveRunning = Boolean(stats?.live?.running);
  const monitors = stats?.monitors?.length
    ? stats.monitors
    : [
        { key: "GOLD", label: "Gold", keywords: [] as string[] },
        { key: "SILVER", label: "Silver", keywords: [] as string[] },
        { key: "CRUDEOIL", label: "Crude Oil", keywords: [] as string[] },
      ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 px-3 py-4 sm:px-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Typography variant="h5" className="flex items-center gap-2 font-semibold text-white">
            <Newspaper className="h-5 w-5 text-sky-400" />
            News Impact
          </Typography>
          <p className="mt-1 text-sm text-slate-400">
            {channelHint} · DB-backed posts · monitors: Gold / Silver / Crude Oil
            {stats?.gemini_enabled ? " · Gemini on" : " · Gemini off"}
          </p>
          <p className="mt-1 text-[11px] text-slate-500">
            Live:{" "}
            <span className={liveRunning ? "text-emerald-400" : "text-slate-400"}>
              {stats?.live?.status || "stopped"}
            </span>
            {stats?.live?.last_event_at
              ? ` · last event ${new Date(stats.live.last_event_at).toLocaleTimeString()}`
              : ""}
            {stats?.live?.error ? ` · ${stats.live.error}` : ""}
          </p>
        </div>
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
          <AppButton
            size="small"
            variant="contained"
            startIcon={<SyncIcon fontSize="small" className={syncing ? "animate-spin" : undefined} />}
            disabled={syncing || liveBusy}
            onClick={() => void onSync(false)}
          >
            {syncing ? "Syncing…" : "Sync news"}
          </AppButton>
          <AppButton
            size="small"
            variant={liveRunning ? "outlined" : "contained"}
            color={liveRunning ? "error" : "primary"}
            startIcon={
              liveRunning ? (
                <StopCircleIcon fontSize="small" />
              ) : (
                <RadioButtonCheckedIcon fontSize="small" />
              )
            }
            disabled={liveBusy || syncing}
            onClick={() => void onToggleLive()}
          >
            {liveBusy ? "…" : liveRunning ? "Live off" : "Live on"}
          </AppButton>
          <AppButton size="small" variant="outlined" disabled={syncing} onClick={() => void onSync(true)}>
            Backfill 500
          </AppButton>
          <AppButton
            size="small"
            variant="outlined"
            startIcon={<RefreshIcon />}
            disabled={loading}
            onClick={() => void refreshFeed()}
          >
            Refresh
          </AppButton>
        </Stack>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-surface-border bg-surface-raised/50 px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Monitor</span>
        <button
          type="button"
          onClick={() => {
            setFeedMode("all");
            setMonitorTopic("");
          }}
          className={`rounded-md px-2.5 py-1 text-[11px] font-medium ring-1 transition ${
            feedMode === "all" && !monitorTopic
              ? "bg-sky-300 text-sky-950 ring-sky-500/50"
              : "bg-slate-800 text-slate-300 ring-slate-600/50 hover:bg-slate-700"
          }`}
        >
          All posts
        </button>
        {monitors.map((m) => (
          <button
            key={m.key}
            type="button"
            title={(m.keywords || []).join(", ")}
            onClick={() => {
              setFeedMode("all");
              setMonitorTopic(m.key);
            }}
            className={`rounded-md px-2.5 py-1 text-[11px] font-medium ring-1 transition ${
              monitorTopic === m.key
                ? "bg-amber-300 text-amber-950 ring-amber-500/50"
                : "bg-slate-800 text-slate-300 ring-slate-600/50 hover:bg-slate-700"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="grid gap-3 rounded-2xl border border-surface-border bg-surface-raised/60 p-3 sm:grid-cols-4">
        <div>
          <div className="text-[10px] uppercase text-slate-500">Messages in DB</div>
          <div className="font-mono text-lg text-white">{stats?.message_count ?? "—"}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">Linked events</div>
          <div className="font-mono text-lg text-white">{stats?.linked_events ?? "—"}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">With reactions</div>
          <div className="font-mono text-lg text-white">{stats?.events_with_reactions ?? "—"}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">Queue</div>
          <div className="font-mono text-lg text-white">{stats?.unprocessed_messages ?? "—"}</div>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-surface-border bg-surface p-3">
        <ToggleButtonGroup
          size="small"
          exclusive
          value={feedMode}
          onChange={(_, v: FeedMode | null) => {
            if (v) setFeedMode(v);
          }}
        >
          <ToggleButton value="all" sx={{ textTransform: "none", px: 1.5 }}>
            All recent posts
          </ToggleButton>
          <ToggleButton value="linked" sx={{ textTransform: "none", px: 1.5 }}>
            Linked (company)
          </ToggleButton>
        </ToggleButtonGroup>

        {feedMode === "linked" && (
          <>
            <div className="min-w-[160px] flex-1">
              <FieldLabel>Ticker filter</FieldLabel>
              <TextField
                size="small"
                fullWidth
                placeholder="e.g. RELIANCE"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
              />
            </div>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Sentiment</InputLabel>
              <Select
                label="Sentiment"
                value={sentiment}
                onChange={(e: SelectChangeEvent) => setSentiment(e.target.value)}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="bullish">Bullish</MenuItem>
                <MenuItem value="bearish">Bearish</MenuItem>
                <MenuItem value="neutral">Neutral</MenuItem>
                <MenuItem value="unknown">Unknown</MenuItem>
              </Select>
            </FormControl>
            <AppButton variant="contained" onClick={() => void loadEvents()} disabled={loading}>
              Apply
            </AppButton>
          </>
        )}
        <Typography variant="caption" className="text-slate-500">
          {total} {feedMode === "all" ? "posts" : "events"}
        </Typography>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {error}
        </div>
      )}

      {feedMode === "all" ? (
        <div className="grid min-h-[560px] gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="max-h-[70vh] overflow-auto rounded-2xl border border-surface-border bg-surface-raised">
            <RecentNewsFeed
              messages={messages}
              loading={loading}
              selectedId={selectedMessage?.id}
              onSelect={setSelectedMessage}
            />
          </div>
          <div className="max-h-[70vh] overflow-auto rounded-2xl border border-surface-border bg-surface-raised p-3">
            {!selectedMessage && <p className="text-sm text-slate-500">Select a post.</p>}
            {selectedMessage && (
              <div className="space-y-3 text-sm">
                <div className="text-[10px] uppercase text-slate-500">Full post</div>
                <p className="whitespace-pre-wrap text-slate-200">{selectedMessage.text || "—"}</p>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-slate-500">Posted</div>
                    <div className="font-mono text-slate-300">{selectedMessage.posted_at}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Telegram ID</div>
                    <div className="font-mono text-slate-300">{selectedMessage.message_id}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Ticker link</div>
                    <div className="font-mono text-sky-300">{selectedMessage.primary_ticker || "—"}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Status</div>
                    <div className="text-slate-300">
                      {selectedMessage.event_status ||
                        (selectedMessage.processed ? "processed" : "queued")}
                    </div>
                  </div>
                </div>
                <p className="text-[11px] text-slate-600">
                  Raw rows live in <code>telegram_messages</code>. Company links create{" "}
                  <code>news_events</code> (+ reactions when candles exist).
                </p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="grid min-h-[560px] gap-3 lg:grid-cols-[320px_minmax(0,1fr)_320px]">
          <div className="max-h-[70vh] overflow-auto rounded-2xl border border-surface-border bg-surface-raised">
            {loading && <p className="p-3 text-sm text-slate-400">Loading events…</p>}
            {!loading && !events.length && (
              <p className="p-3 text-sm text-slate-500">
                No linked events yet. Sync/backfill/listen, then open Linked view.
              </p>
            )}
            <ul className="divide-y divide-surface-border">
              {events.map((ev) => {
                const active = selected?.id === ev.id;
                return (
                  <li key={ev.id}>
                    <button
                      type="button"
                      className={`w-full px-3 py-2.5 text-left transition ${
                        active ? "bg-sky-500/15" : "hover:bg-white/5"
                      }`}
                      onClick={() => setSelected(ev)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-sm font-semibold text-white">{ev.ticker}</span>
                        <span className={`text-xs ${sentimentClass(ev.sentiment)}`}>{ev.sentiment}</span>
                      </div>
                      <div className="mt-0.5 truncate text-xs text-slate-400">
                        {ev.company_name_matched || "—"} · {ev.event_date}
                      </div>
                      <div className="mt-1 flex gap-2 font-mono text-[11px] text-slate-300">
                        <span>T+1 {formatPct(reactionFor(ev, "t1"))}</span>
                        <span>T+3 {formatPct(reactionFor(ev, "t3"))}</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                        {ev.summary || ev.message_text}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="min-h-[420px]">
            {selected?.ticker ? (
              <TimelineStockChart
                symbol={selected.ticker}
                companyName={selected.company_name_matched}
                source="local"
                history={chartHistory}
                highlightDate={selected.event_date || ""}
                highlightMovePct={highlightMove}
                loading={chartLoading}
                fillHeight
                extraMarkers={extraMarkers}
              />
            ) : (
              <div className="flex h-full min-h-[420px] items-center justify-center rounded-2xl border border-dashed border-surface-border text-sm text-slate-500">
                Select a linked news event
              </div>
            )}
          </div>

          <div className="max-h-[70vh] overflow-auto rounded-2xl border border-surface-border bg-surface-raised p-3">
            {!detail && <p className="text-sm text-slate-500">Event detail appears here.</p>}
            {detail && (
              <div className="space-y-3">
                <div>
                  <div className="text-[10px] uppercase text-slate-500">Headline</div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-slate-200">
                    {detail.message_text || detail.summary || "—"}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-slate-500">Posted</div>
                    <div className="font-mono text-slate-200">{detail.posted_at?.slice(0, 19) || "—"}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Event session</div>
                    <div className="font-mono text-slate-200">{detail.event_date || "—"}</div>
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-[10px] uppercase text-slate-500">Reaction path</div>
                  <div className="overflow-hidden rounded-lg border border-surface-border">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-black/20 text-slate-500">
                        <tr>
                          <th className="px-2 py-1">H</th>
                          <th className="px-2 py-1">Return</th>
                          <th className="px-2 py-1">vs Nifty</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(detail.reactions || [])
                          .slice()
                          .sort((a, b) => {
                            const order = ["t_m2", "t_m1", "t0", "t1", "t2", "t3", "t4", "t5"];
                            return order.indexOf(a.horizon) - order.indexOf(b.horizon);
                          })
                          .map((r) => (
                            <tr key={r.horizon} className="border-t border-surface-border/70">
                              <td className="px-2 py-1 font-mono text-slate-300">
                                {HORIZON_LABELS[r.horizon] || r.horizon}
                              </td>
                              <td
                                className={`px-2 py-1 font-mono ${sentimentClass(
                                  r.return_pct != null && r.return_pct >= 0 ? "bullish" : "bearish",
                                )}`}
                              >
                                {formatPct(r.return_pct)}
                              </td>
                              <td className="px-2 py-1 font-mono text-slate-400">
                                {formatPct(r.rel_return_pct)}
                              </td>
                            </tr>
                          ))}
                        {!detail.reactions?.length && (
                          <tr>
                            <td colSpan={3} className="px-2 py-2 text-slate-500">
                              No candle reaction yet
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <div className="text-[10px] uppercase text-slate-500">Gemini outlook</div>
                    <AppButton
                      size="small"
                      variant="outlined"
                      startIcon={<Sparkles className="h-3.5 w-3.5" />}
                      disabled={outlookLoading || !stats?.gemini_enabled}
                      onClick={() => void onOutlook()}
                    >
                      {outlookLoading ? "…" : "Generate"}
                    </AppButton>
                  </div>
                  {detail.outlook ? (
                    <div className="space-y-1 rounded-lg border border-surface-border bg-black/20 p-2 text-xs text-slate-300">
                      <div>
                        <span className={sentimentClass(detail.outlook.bias)}>{detail.outlook.bias}</span>
                        {detail.outlook.typical_move_pct != null && (
                          <span className="ml-2 font-mono">{formatPct(detail.outlook.typical_move_pct)}</span>
                        )}
                      </div>
                      <p>{detail.outlook.rationale}</p>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">
                      {stats?.gemini_enabled ? "No outlook yet." : "Set GEMINI_API_KEY for outlook."}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
