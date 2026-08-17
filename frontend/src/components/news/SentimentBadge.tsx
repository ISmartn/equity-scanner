import { SENTIMENT_BADGE_STYLES, type NewsSentiment } from "@/lib/newsSentiment";

interface SentimentBadgeProps {
  sentiment: NewsSentiment;
  size?: "sm" | "md";
  showTitle?: boolean;
}

export function SentimentBadge({ sentiment, size = "sm", showTitle = true }: SentimentBadgeProps) {
  const meta = SENTIMENT_BADGE_STYLES[sentiment] ?? SENTIMENT_BADGE_STYLES.Average;
  const sizeClass =
    size === "md"
      ? "px-2.5 py-1 text-xs font-semibold tracking-wide"
      : "px-2 py-0.5 text-[10px] font-semibold tracking-wide";

  return (
    <span
      title={showTitle ? meta.description : undefined}
      className={`inline-flex shrink-0 items-center rounded-md uppercase ${sizeClass} ${meta.className}`}
    >
      {meta.label}
    </span>
  );
}
