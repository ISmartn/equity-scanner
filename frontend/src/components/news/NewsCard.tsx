import { SentimentBadge } from "@/components/news/SentimentBadge";
import { formatRelativeTimestamp, type CompanyNewsItem } from "@/lib/newsSentiment";

interface NewsCardProps {
  item: CompanyNewsItem;
  active?: boolean;
  onClick?: () => void;
}

export function NewsCard({ item, active, onClick }: NewsCardProps) {
  return (
    <article
      className={`rounded-xl border px-3 py-2.5 transition ${
        active
          ? "border-sky-400/50 bg-sky-500/10"
          : "border-surface-border bg-surface/40 hover:border-slate-500/60 hover:bg-white/[0.03]"
      } ${onClick ? "cursor-pointer" : ""}`}
      onClick={onClick}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <SentimentBadge sentiment={item.sentiment} />
        <time
          dateTime={item.publishedAt}
          className="shrink-0 text-[10px] tabular-nums text-slate-500"
          title={new Date(item.publishedAt).toLocaleString()}
        >
          {formatRelativeTimestamp(item.publishedAt)}
        </time>
      </div>
      <h3 className="text-[13px] font-medium leading-snug text-slate-100">{item.headline}</h3>
      <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-slate-500">
        <span className="truncate">{item.source}</span>
        <span className="shrink-0 font-mono text-slate-600">
          {(item.confidence * 100).toFixed(0)}%
        </span>
      </div>
    </article>
  );
}
