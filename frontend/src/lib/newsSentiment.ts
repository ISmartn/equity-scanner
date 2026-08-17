import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";

dayjs.extend(relativeTime);

/** Seven-label LLM taxonomy (UI shows all seven; middle three refine “average”). */
export const NEWS_SENTIMENTS = [
  "Good",
  "Decent",
  "Fair",
  "Passable",
  "Average",
  "Mediocre",
  "Bad",
] as const;

export type NewsSentiment = (typeof NEWS_SENTIMENTS)[number];

export interface CompanyNewsItem {
  id: string;
  ticker: string;
  companyName: string;
  headline: string;
  source: string;
  publishedAt: string; // ISO
  sentiment: NewsSentiment;
  confidence: number;
}

export interface SentimentClassification {
  sentiment: NewsSentiment;
  confidence: number;
}

/** High-contrast badge surfaces + dark text (accessible). */
export const SENTIMENT_BADGE_STYLES: Record<
  NewsSentiment,
  { label: string; className: string; description: string }
> = {
  Good: {
    label: "Good",
    className: "bg-emerald-300 text-emerald-950 ring-1 ring-emerald-500/40",
    description: "Strong earnings, positive growth",
  },
  Decent: {
    label: "Decent",
    className: "bg-teal-200 text-teal-950 ring-1 ring-teal-500/40",
    description: "Minor positive updates, steady progress",
  },
  Fair: {
    label: "Fair",
    className: "bg-cyan-200 text-cyan-950 ring-1 ring-cyan-500/40",
    description: "Mildly constructive, limited upside signal",
  },
  Passable: {
    label: "Passable",
    className: "bg-sky-200 text-sky-950 ring-1 ring-sky-500/40",
    description: "Acceptable but uninspiring",
  },
  Average: {
    label: "Average",
    className: "bg-slate-300 text-slate-900 ring-1 ring-slate-500/40",
    description: "Routine corporate update, no major impact",
  },
  Mediocre: {
    label: "Mediocre",
    className: "bg-amber-200 text-amber-950 ring-1 ring-amber-500/40",
    description: "Underperforming targets, slight negative outlook",
  },
  Bad: {
    label: "Bad",
    className: "bg-red-300 text-red-950 ring-1 ring-red-500/40",
    description: "Regulatory issues, major losses",
  },
};

export function isNewsSentiment(value: string): value is NewsSentiment {
  return (NEWS_SENTIMENTS as readonly string[]).includes(value);
}

export function normalizeSentiment(value: string | null | undefined): NewsSentiment {
  if (!value) return "Average";
  const trimmed = value.trim();
  const exact = NEWS_SENTIMENTS.find((s) => s.toLowerCase() === trimmed.toLowerCase());
  if (exact) return exact;
  // Map legacy bullish/bearish extracts into the 7-tier scale
  const legacy: Record<string, NewsSentiment> = {
    bullish: "Good",
    bearish: "Bad",
    neutral: "Average",
    unknown: "Average",
  };
  return legacy[trimmed.toLowerCase()] ?? "Average";
}

export function formatRelativeTimestamp(iso: string): string {
  const d = dayjs(iso);
  if (!d.isValid()) return "—";
  return d.fromNow();
}

export async function classifyNewsSentiment(text: string): Promise<SentimentClassification> {
  const res = await fetch("/api/news/classify-sentiment", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Sentiment classify failed (${res.status})`);
  }
  const data = (await res.json()) as { sentiment: string; confidence: number };
  return {
    sentiment: normalizeSentiment(data.sentiment),
    confidence: Number(data.confidence) || 0,
  };
}
