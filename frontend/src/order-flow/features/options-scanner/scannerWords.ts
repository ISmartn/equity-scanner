import type { BuildUp } from '@/order-flow/lib/buildUp';

/**
 * The scanner's words for a build-up, in sentence case like every other label
 * on the page ("Long build-up", "Short covering"). The four patterns and their
 * meanings are the app's own (BUILDUP_TERMS in utils/marketVocabulary); only
 * the casing is the scanner's.
 */
const BUILD_UP_WORDS: Record<BuildUp, string> = {
  LONG_BUILD: 'Long build-up',
  SHORT_BUILD: 'Short build-up',
  SHORT_COVER: 'Short covering',
  LONG_UNWIND: 'Long unwinding',
  NEUTRAL: 'No clear pattern',
};

export function buildUpWord(code: BuildUp | null | undefined): string {
  return BUILD_UP_WORDS[code ?? 'NEUTRAL'];
}

