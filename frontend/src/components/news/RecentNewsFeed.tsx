import { formatRelativeTimestamp } from "@/lib/newsSentiment";
import type { TelegramNewsMessage } from "@/lib/api";

interface RecentNewsFeedProps {
  messages: TelegramNewsMessage[];
  loading?: boolean;
  emptyHint?: string;
  selectedId?: number | null;
  onSelect?: (msg: TelegramNewsMessage) => void;
}

export function RecentNewsFeed({
  messages,
  loading,
  emptyHint,
  selectedId,
  onSelect,
}: RecentNewsFeedProps) {
  if (loading) {
    return <p className="p-3 text-sm text-slate-400">Loading posts…</p>;
  }
  if (!messages.length) {
    return (
      <p className="p-3 text-sm text-slate-500">
        {emptyHint ||
          "No Telegram posts in DB yet. Run npm run news:login, then news:backfill or news:listen."}
      </p>
    );
  }

  return (
    <ul className="divide-y divide-surface-border">
      {messages.map((msg) => {
        const active = selectedId === msg.id;
        return (
          <li key={msg.id}>
            <button
              type="button"
              className={`w-full px-3 py-2.5 text-left transition ${
                active ? "bg-sky-500/15" : "hover:bg-white/5"
              }`}
              onClick={() => onSelect?.(msg)}
            >
              <div className="flex items-center justify-between gap-2 text-[10px] text-slate-500">
                <span className="truncate">{msg.channel_key}</span>
                <time dateTime={msg.posted_at}>{formatRelativeTimestamp(msg.posted_at)}</time>
              </div>
              <p className="mt-1 line-clamp-3 text-[13px] leading-snug text-slate-100">
                {msg.text}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
                {msg.primary_ticker ? (
                  <span className="font-mono text-sky-300">{msg.primary_ticker}</span>
                ) : (
                  <span className="text-slate-600">unlinked</span>
                )}
                {msg.sentiment && <span className="capitalize">{msg.sentiment}</span>}
                {(msg.monitor_topics || []).map((t) => (
                  <span
                    key={t}
                    className="rounded bg-amber-300/90 px-1.5 py-0.5 font-semibold uppercase tracking-wide text-amber-950"
                  >
                    {t}
                  </span>
                ))}
                <span>{msg.event_status || (msg.processed ? "processed" : "queued")}</span>
                <span className="font-mono text-slate-600">#{msg.message_id}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
