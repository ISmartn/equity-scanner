import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { RefreshCw } from "lucide-react";
import { Clip, PageToolbar, StatChip, ToolbarDivider } from "@/components/dense";
import {
  fetchNewsdesk,
  fetchNewsdeskSummary,
  type NewsdeskBoard,
  type NewsdeskStory,
  type NewsdeskSummary,
} from "@/lib/api";

const DAY_OPTIONS = [1, 3, 7] as const;

function formatWhen(ms: number): string {
  return new Date(ms).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function NewsdeskPage() {
  const [days, setDays] = useState<(typeof DAY_OPTIONS)[number]>(3);
  const [board, setBoard] = useState<NewsdeskBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [summary, setSummary] = useState<NewsdeskSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        let payload = await fetchNewsdesk(days, false);
        if (!cancelled && payload.article_count === 0) {
          payload = await fetchNewsdesk(days, true);
        }
        if (cancelled) return;
        setBoard(payload);
        setSelectedId((current) =>
          current && payload.stories.some((story) => story.id === current)
            ? current
            : payload.stories[0]?.id ?? null,
        );
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Newsdesk failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [days]);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchNewsdesk(days, true);
      setBoard(payload);
      setSelectedId((current) =>
        current && payload.stories.some((story) => story.id === current) ? current : payload.stories[0]?.id ?? null,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setLoading(false);
    }
  };

  const query = symbol.trim().toUpperCase();
  const visible = useMemo(() => {
    return (board?.stories ?? []).filter((story) => {
      if (category && story.category !== category) return false;
      if (!query) return true;
      return (
        story.companies.some((ticker) => ticker.includes(query)) ||
        story.lead.title.toUpperCase().includes(query) ||
        Object.values(story.company_names).some((name) => name.toUpperCase().includes(query))
      );
    });
  }, [board, category, query]);

  const selected = visible.find((story) => story.id === selectedId) ?? visible[0] ?? null;

  useEffect(() => {
    if (!selected) {
      setSummary(null);
      return;
    }
    let cancelled = false;
    setSummary(null);
    setSummaryError(null);
    fetchNewsdeskSummary(selected.lead.link)
      .then((payload) => {
        if (!cancelled) setSummary(payload);
      })
      .catch((err) => {
        if (!cancelled) setSummaryError(err instanceof Error ? err.message : "Summary failed");
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  return (
    <div className="page-shell flex flex-col gap-1 overflow-hidden px-1.5 py-1 sm:px-2">
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} className="shrink-0 py-0 text-data-sm">
          {error}
        </Alert>
      ) : null}
      <PageToolbar
        right={
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-surface-border px-2 text-data-xs font-semibold text-slate-200 hover:border-accent/40 hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh feeds
          </button>
        }
      >
        <ToggleButtonGroup
          exclusive
          size="small"
          value={days}
          onChange={(_event, value: (typeof DAY_OPTIONS)[number] | null) => {
            if (value) {
              setCategory(null);
              setDays(value);
            }
          }}
          sx={{ flexShrink: 0, "& .MuiToggleButton-root": { textTransform: "none", px: 1.25 } }}
        >
          {DAY_OPTIONS.map((option) => (
            <ToggleButton key={option} value={option}>
              {option}d
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        <ToolbarDivider />
        <input
          value={symbol}
          onChange={(event) => setSymbol(event.target.value)}
          placeholder="Ticker or headline"
          className="h-7 w-40 rounded-md border border-surface-border bg-surface px-2 text-data-xs text-slate-100 outline-none placeholder:text-slate-500 focus:border-accent/50"
        />
        {board ? (
          <>
            <ToolbarDivider />
            <StatChip label="Stories" value={board.story_count} />
            <StatChip label="Articles" value={board.article_count} />
            <StatChip label="Sources" value={board.sources.length} />
          </>
        ) : null}
        {loading ? <span className="shrink-0 text-data-xs text-slate-400">Updating…</span> : null}
      </PageToolbar>

      {board?.notes?.length ? (
        <p className="shrink-0 px-1 text-data-xs text-slate-400">{board.notes.join(" ")}</p>
      ) : null}

      {board && board.categories.length > 0 ? (
        <div className="flex shrink-0 gap-1 overflow-x-auto px-0.5 [scrollbar-width:thin]">
          <FilterChip label="All" active={category == null} onClick={() => setCategory(null)} />
          {board.categories.map((item) => (
            <FilterChip
              key={item.id}
              label={`${item.id} ${item.count}`}
              active={category === item.id}
              onClick={() => setCategory((current) => (current === item.id ? null : item.id))}
            />
          ))}
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-1 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="panel mobile-pane min-h-0 overflow-auto">
          {visible.length === 0 ? (
            <p className="p-4 text-data-sm text-slate-400">
              {loading ? "Loading the desk…" : "No stories in this window. Refresh feeds to pull the latest headlines."}
            </p>
          ) : (
            <ul>
              {visible.map((story) => (
                <li key={story.id}>
                  <StoryRow story={story} active={selected?.id === story.id} onSelect={() => setSelectedId(story.id)} />
                </li>
              ))}
            </ul>
          )}
        </div>
        <aside className="panel min-h-0 overflow-auto p-3">
          {selected ? (
            <StoryDetail story={selected} summary={summary} summaryError={summaryError} />
          ) : (
            <p className="text-data-sm text-slate-400">Select a story.</p>
          )}
        </aside>
      </div>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`shrink-0 rounded-full border px-2 py-0.5 text-data-xs ${
        active ? "border-accent/60 bg-accent/15 text-slate-100" : "border-surface-border bg-surface text-slate-300"
      }`}
    >
      {label}
    </button>
  );
}

function StoryRow({
  story,
  active,
  onSelect,
}: {
  story: NewsdeskStory;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full flex-col gap-0.5 border-b border-surface-border px-2 py-1.5 text-left ${
        active ? "bg-accent/10" : "hover:bg-surface-raised"
      }`}
    >
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-slate-500">
        <span style={{ color: story.lead.source.color }}>{story.lead.source.name}</span>
        <span>{story.category}</span>
        <span className="num">{formatWhen(story.time)}</span>
        {story.coverage > 1 ? <span className="text-sky-300">+{story.coverage - 1} sources</span> : null}
      </div>
      <Clip className="text-data-sm font-medium text-slate-100">{story.lead.title}</Clip>
    </button>
  );
}

function StoryDetail({
  story,
  summary,
  summaryError,
}: {
  story: NewsdeskStory;
  summary: NewsdeskSummary | null;
  summaryError: string | null;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div>
        <p className="text-[10px] uppercase tracking-wide" style={{ color: story.lead.source.color }}>
          {story.lead.source.name} · {formatWhen(story.lead.published_at)}
        </p>
        <h2 className="text-data-md font-semibold text-slate-100">{story.lead.title}</h2>
      </div>
      {story.companies.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {story.companies.map((ticker) => (
            <span key={ticker} className="rounded border border-surface-border px-1.5 py-0.5 text-[10px] text-slate-200">
              {ticker}
              <span className="text-slate-500"> {story.company_names[ticker]}</span>
            </span>
          ))}
        </div>
      ) : null}
      {summary?.figures?.length ? (
        <div className="flex flex-wrap gap-1">
          {summary.figures.map((figure) => (
            <span key={figure} className="num rounded bg-surface-raised px-1.5 py-0.5 text-[11px] text-amber-200">
              {figure}
            </span>
          ))}
        </div>
      ) : null}
      {summary?.summary?.length ? (
        <ul className="list-disc space-y-1 pl-4 text-data-xs leading-snug text-slate-300">
          {summary.summary.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="text-data-xs leading-snug text-slate-300">{story.lead.description || "No blurb on this item."}</p>
      )}
      {summaryError ? <p className="text-data-xs text-rose-300">{summaryError}</p> : null}
      <a href={story.lead.link} target="_blank" rel="noreferrer" className="text-data-xs text-sky-300 hover:text-sky-200">
        Open original
      </a>
      {story.others.length > 0 ? (
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Also reported</p>
          <ul className="space-y-1">
            {story.others.map((other) => (
              <li key={other.link}>
                <a href={other.link} target="_blank" rel="noreferrer" className="text-data-xs text-slate-300 hover:text-white">
                  <span style={{ color: other.color }}>{other.name}</span> — {other.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
