/**
 * Underlying universe — loader + search for all F&O underlyings.
 *
 * `public/underlyings.json` lists every F&O underlying: symbol, name, exchange
 * key, lot size, kind and sector. Data providers map these symbols to their own
 * instrument ids (server/providers).
 *
 * The app keeps working with the embedded indices even if the JSON
 * fails to load — loading only EXTENDS the universe, never replaces it.
 */



export interface Underlying {
  symbol: string;         // app-facing symbol, e.g. 'NIFTY'
  name: string;
  apiKey: string;         // exchange key, e.g. 'NSE:NIFTY50'
  lot: number;
  /** Upcoming expiries captured with the catalogue, used as an offline fallback. */
  expiries?: string[];
  kind: 'index' | 'stock';
  exch: string;           // 'NSE' | 'BSE'
  /**
   * Theme tags stamped in by scripts/build-underlyings.mjs from the taxonomy in
   * scripts/themes.mjs. Stocks only — indices are pinned in the picker already.
   * Optional so an older universe file still validates and loads; the themes UI
   * simply finds nothing rather than the whole picker breaking.
   */
  sector?: string;        // exactly one, exhaustive across stocks
  baskets?: string[];     // overlapping themes: psu, defence, tata-group, …
}

/** Label + size for every theme, published alongside the rows. */
export interface ThemeDirectory {
  sectors: Record<string, { label: string; count: number }>;
  baskets: Record<string, { label: string; count: number }>;
}

let universe: Underlying[] | null = null;
let themeDirectory: ThemeDirectory | null = null;
let loadPromise: Promise<Underlying[]> | null = null;

/** Underlyings the header always pins on top */
export const PINNED_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'];

/** Compact market cards shown in the global header. */
export const HEADER_MARKET_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

const UNDERLYING_SEARCH_ALIASES: Record<string, string[]> = {
  INDHOTEL: ['INDIAN HOTELS CO', 'INDIAN HOTELS COMPANY'],
  POLYCAB: ['POLYCAB INDIA'],
};

const UNIVERSE_FETCH_ATTEMPTS = 3;
const UNIVERSE_RETRY_BASE_MS = 300;

/** A response worth asking for again: the server is up but not answering yet. */
function isRetryableStatus(status: number): boolean {
  return status === 429 || status >= 500;
}

/**
 * GET a same-origin file, retrying a dropped connection or a transient server
 * status with a short backoff. `fetch` rejects with a TypeError for transport
 * failures — DNS, TLS, connection reset — which is the case that matters here.
 */
async function fetchWithRetry(url: string): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt < UNIVERSE_FETCH_ATTEMPTS; attempt += 1) {
    if (attempt > 0) {
      await new Promise((resolve) => setTimeout(resolve, UNIVERSE_RETRY_BASE_MS * 3 ** (attempt - 1)));
    }
    try {
      const res = await fetch(url, { cache: 'no-cache' });
      if (!isRetryableStatus(res.status)) return res;
      lastError = new Error(`${url}: HTTP ${res.status}`);
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError instanceof Error ? lastError : new Error(`${url}: unreachable`);
}

/**
 * Load the underlying universe once per session (memoised promise) and
 * register every entry in the analytics resolver so fetchers/WS/ATM
 * rounding work for any symbol. Safe to call repeatedly.
 */
export function loadUnderlyings(): Promise<Underlying[]> {
  if (loadPromise) return loadPromise;
  loadPromise = (async () => {
    try {
      const payload = await (async () => {
        // Bypass any cached copy. This file's SHAPE changes between releases —
        // entries used to be keyed by broker scrip/segment and are now keyed by
        // `apiKey` — so a stale cached copy does not merely go out of date, it
        // fails validation wholesale and empties the universe. The symptom is a
        // picker that finds no stock at all while the six embedded indices still
        // work, which reads as "search is broken" rather than "the file is old".
        //
        // Retried, because this promise is memoised for the whole session: one
        // dropped connection and every stock stays missing until the visitor
        // reloads. Only transport failures and
        // 5xx/429 are retried; a 404 is a deploy problem and repeating it just
        // delays the error.
        const res = await fetchWithRetry('/underlyings.json');
        if (!res.ok) throw new Error(`underlyings.json: HTTP ${res.status}`);
        return res.json() as Promise<{ underlyings?: Underlying[]; themes?: ThemeDirectory }>;
      })();
      const list = Array.isArray(payload.underlyings) ? payload.underlyings : [];
      const valid = list.filter(u =>
        u && typeof u.symbol === 'string' && typeof u.apiKey === 'string' && u.apiKey.includes(':') && u.lot > 0
      );

      if (valid.length === 0) {
        // Name the actual cause instead of a bare "empty". A file full of rows
        // that every one failed validation is a format mismatch, not an empty
        // file, and the two need completely different fixes.
        const legacy = list.some((u: any) => u && u.scrip !== undefined && u.apiKey === undefined);
        throw new Error(
          list.length === 0
            ? 'underlyings.json: no entries'
            : `underlyings.json: all ${list.length} entries rejected${
                legacy ? ' — each entry needs symbol, apiKey (EXCHANGE:SYMBOL), lot and kind' : ''
              }`,
        );
      }

      themeDirectory = payload.themes && typeof payload.themes === 'object' ? payload.themes : null;
      universe = valid;
      if (valid.length < list.length) {
        console.warn(`[Underlyings] ${list.length - valid.length} of ${list.length} entries were rejected and are unreachable in search.`);
      }
      return valid;
    } catch (err) {
      // Loud, not a warning: with an empty universe every stock silently
      // disappears from search while indices keep working.
      console.error('[Underlyings] Failed to load universe — only the embedded indices are searchable.', err);
      universe = [];
      return [];
    }
  })();
  return loadPromise;
}

/** Synchronous access after load (empty until loadUnderlyings resolves) */
/** Sector and basket labels from the same catalogue file; null until it has loaded. */
export function getThemeDirectory(): ThemeDirectory | null {
  return themeDirectory;
}

export function getUniverse(): Underlying[] {
  return universe ?? [];
}

/**
 * Rank-based search: prefix matches first, then substring on symbol,
 * then substring on name. Case-insensitive. Indices float to the top.
 */
export function searchUnderlyings(query: string, list: Underlying[], limit = 30): Underlying[] {
  const q = query.trim().toUpperCase();
  if (!q) return list.slice(0, limit);
  const compactQuery = q.replace(/[^A-Z0-9]/g, '');
  const tokens = q.split(/[^A-Z0-9]+/).filter(Boolean);
  const scored: { u: Underlying; score: number }[] = [];
  for (const u of list) {
    const sym = u.symbol.toUpperCase();
    const name = (u.name || '').toUpperCase();
    const aliases = (UNDERLYING_SEARCH_ALIASES[u.symbol] || []).join(' ').toUpperCase();
    const haystack = `${sym} ${name} ${aliases}`;
    const compactHaystack = haystack.replace(/[^A-Z0-9]/g, '');
    let score = -1;
    if (sym === q) score = 0;
    else if (sym.startsWith(q)) score = 1;
    else if (name.startsWith(q)) score = 1.5;
    else if (sym.includes(q)) score = 2;
    else if (name.includes(q)) score = 3;
    else if (aliases.includes(q)) score = 3.25;
    else if (compactQuery && compactHaystack.includes(compactQuery)) score = 3.5;
    else if (tokens.length > 1 && tokens.every(token => haystack.includes(token))) score = 4;
    if (score >= 0) scored.push({ u, score: score + (u.kind === 'index' ? 0 : 0.5) });
  }
  return scored.sort((a, b) => a.score - b.score || a.u.symbol.localeCompare(b.u.symbol)).slice(0, limit).map(s => s.u);
}

// ── Favourites & Recent (localStorage) ──

const RECENT_KEY = 'ui:underlying:recent';
const RECENT_LIMIT = 8;

export function getRecent(): string[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch { return []; }
}

export function pushRecent(symbol: string): void {
  if (PINNED_SYMBOLS.includes(symbol)) return; // pinned ones don't need recency
  const next = [symbol, ...getRecent().filter(s => s !== symbol)].slice(0, RECENT_LIMIT);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* quota */ }
}
