import { NewsCard } from "@/components/news/NewsCard";
import { SentimentBadge } from "@/components/news/SentimentBadge";
import { fetchNewsEvents } from "@/lib/api";
import {
  NEWS_SENTIMENTS,
  normalizeSentiment,
  type CompanyNewsItem,
  type NewsSentiment,
} from "@/lib/newsSentiment";
import { Newspaper } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

interface CompanyNewsSidebarProps {
  ticker?: string | null;
  companyName?: string | null;
  /** Optional override feed; otherwise loads linked Telegram events from DB. */
  items?: CompanyNewsItem[] | null;
  className?: string;
  widthClassName?: string;
}

export function CompanyNewsSidebar({
  ticker,
  companyName,
  items,
  className = "",
  widthClassName = "w-full max-w-full lg:w-[22rem] lg:max-w-[22rem] xl:w-[24rem] xl:max-w-[24rem]",
}: CompanyNewsSidebarProps) {
  const [filter, setFilter] = useState<NewsSentiment | "All">("All");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dbItems, setDbItems] = useState<CompanyNewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const symbol = (ticker || "").trim().toUpperCase();
  const useProps = Boolean(items && items.length);

  useEffect(() => {
    if (useProps) {
      setDbItems([]);
      setError(null);
      setLoading(false);
      return;
    }
    if (!symbol) {
      setDbItems([]);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchNewsEvents({ ticker: symbol, status: "linked", limit: 30 })
      .then((res) => {
        if (cancelled) return;
        setDbItems(
          res.results.map((ev) => ({
            id: `ev-${ev.id}`,
            ticker: ev.ticker || symbol,
            companyName: ev.company_name_matched || companyName || symbol,
            headline: ev.summary || ev.message_text || "(no text)",
            source: ev.channel_key || "Telegram",
            publishedAt: ev.posted_at || new Date().toISOString(),
            sentiment: normalizeSentiment(ev.sentiment),
            confidence:
              typeof ev.match_confidence === "number"
                ? Math.min(1, ev.match_confidence / 100)
                : 0.7,
          })),
        );
      })
      .catch((err) => {
        if (!cancelled) {
          setDbItems([]);
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, companyName, useProps]);

  const news = useMemo(() => {
    if (useProps && items) return items;
    return dbItems;
  }, [useProps, items, dbItems]);

  useEffect(() => {
    setFilter("All");
    setSelectedId(news[0]?.id ?? null);
  }, [ticker, news]);

  const filtered = useMemo(() => {
    if (filter === "All") return news;
    return news.filter((n) => n.sentiment === filter);
  }, [news, filter]);

  return (
    <aside
      className={`flex min-h-0 flex-col border-surface-border bg-surface-raised/80 ${widthClassName} ${className} lg:border-l`}
      aria-label="Company news sidebar"
    >
      <header className="shrink-0 border-b border-surface-border px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Newspaper className="h-4 w-4 text-sky-400" aria-hidden />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-100">Company news</h2>
            <p className="truncate text-[11px] text-slate-500">
              {symbol
                ? `${symbol}${companyName ? ` · ${companyName}` : ""}`
                : "Select a company to load news"}
              {loading ? " · loading…" : ""}
            </p>
          </div>
        </div>

        {symbol && news.length > 0 && (
          <div className="mt-2 flex gap-1 overflow-x-auto pb-0.5">
            <FilterChip active={filter === "All"} onClick={() => setFilter("All")} label="All" />
            {NEWS_SENTIMENTS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setFilter(s)}
                className={`rounded-md transition ${
                  filter === s
                    ? "ring-2 ring-sky-400/70 ring-offset-1 ring-offset-surface-raised"
                    : "opacity-80 hover:opacity-100"
                }`}
              >
                <SentimentBadge sentiment={s} showTitle={false} />
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2.5 py-2">
        {!symbol && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">
            Pick a stock in the main view to see linked Telegram headlines.
          </p>
        )}
        {symbol && loading && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">Loading news…</p>
        )}
        {symbol && !loading && error && (
          <p className="px-1 py-6 text-center text-xs text-red-300">{error}</p>
        )}
        {symbol && !loading && !error && news.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">
            No linked news for {symbol} yet. Sync or turn on Live feed on News Impact.
          </p>
        )}
        {symbol && !loading && filtered.length === 0 && news.length > 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">No headlines for this filter.</p>
        )}
        <ul className="space-y-2">
          {filtered.map((item) => (
            <li key={item.id}>
              <NewsCard
                item={item}
                active={selectedId === item.id}
                onClick={() => setSelectedId(item.id)}
              />
            </li>
          ))}
        </ul>
      </div>

      {symbol && (
        <footer className="shrink-0 border-t border-surface-border px-3 py-2 text-[10px] text-slate-600">
          {loading
            ? "Loading…"
            : news.length
              ? `Showing ${filtered.length} of ${news.length} · Telegram DB`
              : "No stored news for this ticker"}
        </footer>
      )}
    </aside>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 transition ${
        active
          ? "bg-sky-300 text-sky-950 ring-sky-500/50"
          : "bg-slate-700/60 text-slate-200 ring-slate-500/40 hover:bg-slate-600/70"
      }`}
    >
      {label}
    </button>
  );
}
