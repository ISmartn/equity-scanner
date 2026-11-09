import { TimelineStockChart } from "@/components/TimelineStockChart";
import { RecentNewsFeed } from "@/components/news/RecentNewsFeed";
import { AppButton } from "@/components/mui";
import {
  ActiveFilterChips,
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  Clip,
  PageToolbar,
  PctCell,
  StatChip,
  ToolbarDivider,
} from "@/components/dense";
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
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { Newspaper, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";

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

const NEWS_PREFS_KEY = "trading.newsImpact.prefs";
type NewsUiPrefs = {
  feedMode: FeedMode;
  ticker: string;
  sentiment: string;
  monitorTopic: string;
};
const DEFAULT_NEWS_PREFS: NewsUiPrefs = {
  feedMode: "all",
  ticker: "",
  sentiment: "",
  monitorTopic: "",
};

export function NewsImpactPage() {
  const initialPrefs = loadUiPrefs(NEWS_PREFS_KEY, DEFAULT_NEWS_PREFS);
  const [feedMode, setFeedMode] = useState<FeedMode>(initialPrefs.feedMode === "linked" ? "linked" : "all");
  const [stats, setStats] = useState<NewsStats | null>(null);
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [messages, setMessages] = useState<TelegramNewsMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [ticker, setTicker] = useState(initialPrefs.ticker);
  const [sentiment, setSentiment] = useState(initialPrefs.sentiment);
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
  const [monitorTopic, setMonitorTopic] = useState<string>(initialPrefs.monitorTopic);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    saveUiPrefs(NEWS_PREFS_KEY, {
      feedMode,
      ticker,
      sentiment,
      monitorTopic,
    } satisfies NewsUiPrefs);
  }, [feedMode, ticker, sentiment, monitorTopic]);

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

  const statusTone = liveRunning ? "text-emerald-400" : "text-slate-400";

  return (
    <div className="page-shell flex flex-col gap-1 overflow-y-auto px-1.5 py-1 sm:px-2 lg:overflow-hidden">
      <PageToolbar
        right={
          <AdvancedButton
            onClick={() => setAdvancedOpen(true)}
            label="Sync & live"
            activeCount={monitorTopic ? 1 : 0}
          />
        }
        below={
          monitorTopic ? (
            <ActiveFilterChips
              chips={[
                {
                  key: "monitor",
                  label: `Monitor: ${monitors.find((m) => m.key === monitorTopic)?.label ?? monitorTopic}`,
                  onRemove: () => setMonitorTopic(""),
                },
              ]}
            />
          ) : undefined
        }
      >
        <h1 className="flex shrink-0 items-center gap-1.5 text-data-md font-semibold text-slate-100">
          <Newspaper className="h-4 w-4 text-sky-400" />
          News Impact
        </h1>
        <ToolbarDivider />
        <ToggleButtonGroup
          exclusive
          value={feedMode}
          onChange={(_, v: FeedMode | null) => {
            if (v) setFeedMode(v);
          }}
        >
          <ToggleButton value="all" sx={{ textTransform: "none" }}>
            All recent posts
          </ToggleButton>
          <ToggleButton value="linked" sx={{ textTransform: "none" }}>
            Linked (company)
          </ToggleButton>
        </ToggleButtonGroup>

        {feedMode === "linked" && (
          <>
            <TextField
              placeholder="Ticker e.g. RELIANCE"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              sx={{ width: 160 }}
              slotProps={{ htmlInput: { "aria-label": "Ticker filter" } }}
            />
            <FormControl sx={{ minWidth: 120 }}>
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
            <AppButton size="small" variant="contained" onClick={() => void loadEvents()} disabled={loading}>
              Apply
            </AppButton>
          </>
        )}
        <ToolbarDivider />
        <StatChip label={feedMode === "all" ? "Posts" : "Events"} value={total} />
        <StatChip label="In DB" value={stats?.message_count ?? "—"} hint="Messages in DB" />
        <StatChip label="Linked" value={stats?.linked_events ?? "—"} hint="Linked events" />
        <StatChip label="Queue" value={stats?.unprocessed_messages ?? "—"} hint="Unprocessed messages" />
        <StatChip
          label="Live"
          value={stats?.live?.status || "stopped"}
          valueClassName={`text-data-sm ${statusTone}`}
          hint={stats?.live?.error || undefined}
        />
      </PageToolbar>

      {error && (
        <div className="shrink-0 rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1 text-data-sm text-red-200">
          {error}
        </div>
      )}

      {feedMode === "all" ? (
        <div className="grid min-h-0 flex-1 gap-1.5 lg:grid-cols-[minmax(0,1fr)_360px] lg:grid-rows-[minmax(0,1fr)]">
          <div className="panel max-h-[70vh] min-h-0 overflow-auto lg:max-h-none">
            <RecentNewsFeed
              messages={messages}
              loading={loading}
              selectedId={selectedMessage?.id}
              onSelect={setSelectedMessage}
            />
          </div>
          <div className="panel max-h-[70vh] min-h-0 overflow-auto p-2 lg:max-h-none">
            {!selectedMessage && <p className="text-data-sm text-slate-400">Select a post.</p>}
            {selectedMessage && (
              <div className="space-y-2 text-data-md">
                <div className="text-[10px] uppercase tracking-wide text-slate-400">Full post</div>
                <p className="whitespace-pre-wrap text-slate-200">{selectedMessage.text || "—"}</p>
                <div className="grid grid-cols-2 gap-1.5 text-data-sm">
                  <div>
                    <div className="text-slate-400">Posted</div>
                    <div className="num text-slate-200">{selectedMessage.posted_at}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">Telegram ID</div>
                    <div className="num text-slate-200">{selectedMessage.message_id}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">Ticker link</div>
                    <div className="ticker text-sky-300">{selectedMessage.primary_ticker || "—"}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">Status</div>
                    <div className="text-slate-200">
                      {selectedMessage.event_status ||
                        (selectedMessage.processed ? "processed" : "queued")}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-1.5 lg:grid-cols-[300px_minmax(0,1fr)_320px] lg:grid-rows-[minmax(0,1fr)]">
          <div className="panel max-h-[70vh] min-h-0 overflow-auto lg:max-h-none">
            {loading && <p className="p-2 text-data-sm text-slate-400">Loading events…</p>}
            {!loading && !events.length && (
              <p className="p-2 text-data-sm text-slate-400">
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
                      className={`w-full px-2 py-1.5 text-left transition ${
                        active ? "bg-sky-500/15" : "hover:bg-white/5"
                      }`}
                      onClick={() => setSelected(ev)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="ticker">{ev.ticker}</span>
                        <span className={`text-data-xs ${sentimentClass(ev.sentiment)}`}>{ev.sentiment}</span>
                      </div>
                      <Clip
                        className="text-data-xs text-slate-400"
                        title={`${ev.company_name_matched || "—"} · ${ev.event_date ?? ""}`}
                      >
                        {ev.company_name_matched || "—"} · {ev.event_date}
                      </Clip>
                      <div className="mt-0.5 flex gap-2 text-data-xs text-slate-300">
                        <span>
                          T+1 <PctCell value={reactionFor(ev, "t1")} />
                        </span>
                        <span>
                          T+3 <PctCell value={reactionFor(ev, "t3")} />
                        </span>
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-data-xs text-slate-400">
                        {ev.summary || ev.message_text}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="h-[28rem] min-h-0 lg:h-auto">
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
              <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-surface-border text-data-md text-slate-400">
                Select a linked news event
              </div>
            )}
          </div>

          <div className="panel max-h-[70vh] min-h-0 overflow-auto p-2 lg:max-h-none">
            {!detail && <p className="text-data-sm text-slate-400">Event detail appears here.</p>}
            {detail && (
              <div className="space-y-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-slate-400">Headline</div>
                  <p className="mt-0.5 whitespace-pre-wrap text-data-md text-slate-200">
                    {detail.message_text || detail.summary || "—"}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-1.5 text-data-sm">
                  <div>
                    <div className="text-slate-400">Posted</div>
                    <div className="num text-slate-200">{detail.posted_at?.slice(0, 19) || "—"}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">Event session</div>
                    <div className="num text-slate-200">{detail.event_date || "—"}</div>
                  </div>
                </div>

                <div>
                  <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-400">Reaction path</div>
                  <div className="overflow-hidden rounded-md border border-surface-border">
                    <table className="dt w-full text-left">
                      <thead>
                        <tr>
                          <th>H</th>
                          <th className="text-right">Return</th>
                          <th className="text-right">vs Nifty</th>
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
                            <tr key={r.horizon}>
                              <td className="num text-slate-200">{HORIZON_LABELS[r.horizon] || r.horizon}</td>
                              <td className="text-right">
                                <PctCell value={r.return_pct} />
                              </td>
                              <td className="text-right">
                                <PctCell value={r.rel_return_pct} />
                              </td>
                            </tr>
                          ))}
                        {!detail.reactions?.length && (
                          <tr>
                            <td colSpan={3} className="text-slate-400">
                              No candle reaction yet
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div>
                  <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-400">Gemini outlook</div>
                  {detail.outlook ? (
                    <div className="space-y-1 rounded-md border border-surface-border bg-black/20 p-2 text-data-sm text-slate-200">
                      <div>
                        <span className={sentimentClass(detail.outlook.bias)}>{detail.outlook.bias}</span>
                        {detail.outlook.typical_move_pct != null && (
                          <span className="num ml-2">{formatPct(detail.outlook.typical_move_pct)}</span>
                        )}
                      </div>
                      <p>{detail.outlook.rationale}</p>
                    </div>
                  ) : (
                    <p className="text-data-xs text-slate-400">
                      {stats?.gemini_enabled
                        ? "No outlook yet — generate one from Sync & live."
                        : "Set GEMINI_API_KEY for outlook."}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="News sync & live"
        subtitle={channelHint}
      >
        <AdvancedSection title="Jobs">
          <div className="flex flex-wrap gap-1.5">
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
          </div>
          <p className="text-data-xs text-slate-300">
            Live:{" "}
            <span className={statusTone}>{stats?.live?.status || "stopped"}</span>
            {stats?.live?.last_event_at
              ? ` · last event ${new Date(stats.live.last_event_at).toLocaleTimeString()}`
              : ""}
            {stats?.live?.error ? ` · ${stats.live.error}` : ""}
          </p>
          <p className="text-data-xs text-slate-400">
            {channelHint} · DB-backed posts · monitors: Gold / Silver / Crude Oil
            {stats?.gemini_enabled ? " · Gemini on" : " · Gemini off"}
          </p>
        </AdvancedSection>

        <AdvancedSection title="Filters" hint="Monitor topic">
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => {
                setFeedMode("all");
                setMonitorTopic("");
              }}
              className={`rounded-md px-2 py-0.5 text-data-xs font-medium ring-1 transition ${
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
                className={`rounded-md px-2 py-0.5 text-data-xs font-medium ring-1 transition ${
                  monitorTopic === m.key
                    ? "bg-amber-300 text-amber-950 ring-amber-500/50"
                    : "bg-slate-800 text-slate-300 ring-slate-600/50 hover:bg-slate-700"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </AdvancedSection>

        <AdvancedSection title="Gemini outlook" hint={selected?.ticker ?? undefined}>
          <AppButton
            size="small"
            variant="outlined"
            startIcon={<Sparkles className="h-3.5 w-3.5" />}
            disabled={outlookLoading || !stats?.gemini_enabled}
            onClick={() => void onOutlook()}
          >
            {outlookLoading ? "…" : "Generate"}
          </AppButton>
          <p className="text-data-xs text-slate-400">
            {stats?.gemini_enabled
              ? "Generates an outlook for the selected linked event."
              : "Set GEMINI_API_KEY for outlook."}
          </p>
        </AdvancedSection>

        <AdvancedSection title="Data">
          <div className="grid grid-cols-2 gap-1.5">
            <StatChip label="Messages in DB" value={stats?.message_count ?? "—"} />
            <StatChip label="Linked events" value={stats?.linked_events ?? "—"} />
            <StatChip label="With reactions" value={stats?.events_with_reactions ?? "—"} />
            <StatChip label="Queue" value={stats?.unprocessed_messages ?? "—"} />
          </div>
        </AdvancedSection>

        <AdvancedSection title="Help" defaultOpen={false}>
          <p className="text-data-xs text-slate-300">
            Raw rows live in <code>telegram_messages</code>. Company links create{" "}
            <code>news_events</code> (+ reactions when candles exist).
          </p>
        </AdvancedSection>
      </AdvancedDrawer>
    </div>
  );
}
