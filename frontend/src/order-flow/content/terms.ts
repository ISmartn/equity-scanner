/**
 * The one source of every term the tools print (`terms.json`). The page ⓘ
 * sheets, the in-tool tips and the /glossary/ page all read their words from
 * here, so a term cannot say two different things in two places.
 * `terms.test.ts` holds the rules: every reference resolves, no surface keeps
 * its own copy of a definition, and no definition advises.
 */

import data from './terms.json';
import type { PageTerm, PageTone } from '@/order-flow/components/chrome/pageInfoContent';

export interface Term {
  id: string;
  /** The term as the glossary heads it. */
  term: string;
  /** How a tool names it, where that differs from the glossary heading ("Breakevens"). */
  label?: string;
  group: string;
  /** What it is and how it is read, in one or two plain sentences. */
  short: string;
  /** What it does not say. Printed after `short` wherever the term is explained. */
  not?: string;
  guide?: string;
  tool?: string;
  also?: string[];
  /** Route ids of the tools that print it. */
  tools: string[];
}

export const TERM_GROUPS: ReadonlyArray<{ id: string; label: string }> = data.groups;
export const TERMS: readonly Term[] = data.terms as Term[];

const BY_ID = new Map(TERMS.map(entry => [entry.id, entry]));

export function termById(id: string): Term {
  const entry = BY_ID.get(id);
  if (!entry) throw new Error(`Unknown term "${id}": add it to src/content/terms.json`);
  return entry;
}

/** The explanation as every surface prints it: what it is, then what it does not say. */
export function termText(entry: Term): string {
  return entry.not ? `${entry.short} ${entry.not}` : entry.short;
}

/** The words of an in-tool tip (TermTip): the shared explanation, plus one sentence on how this place applies it. */
export function termTip(id: string, context?: string): string {
  const text = termText(termById(id));
  return context ? `${text} ${context}` : text;
}

/** The glossary address of a term, for "more" links from a tool. */
export function termHref(id: string): string {
  return `/glossary/#term-${termById(id).id}`;
}

/**
 * A row of a page's Key terms, read from the source. `context` adds one
 * sentence about how this page applies the term (a threshold, a scope); it
 * never restates the definition.
 */
export function pageTerm(id: string, options: { tone?: PageTone; context?: string } = {}): PageTerm {
  const entry = termById(id);
  const meaning = options.context ? `${termText(entry)} ${options.context}` : termText(entry);
  return { id, term: entry.label ?? entry.term, meaning, ...(options.tone ? { tone: options.tone } : {}) };
}
