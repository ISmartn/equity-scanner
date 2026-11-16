/**
 * Where an underlying's logo lives, if we hold one.
 *
 * The files and `manifest.json` under `public/brand/underlyings/` are produced
 * by `scripts/fetch-underlying-logos.mjs` from Wikidata → Wikimedia Commons,
 * with the issuer's own site icon as the fallback. Coverage is partial by
 * design: a symbol with no freely-licensed mark keeps its monogram rather
 * than borrowing someone else's artwork.
 *
 * The manifest is fetched once, lazily, and never blocks a render: the card
 * draws its monogram immediately and the logo replaces it when (or if) the
 * manifest arrives.
 */

export interface UnderlyingLogo {
  file: string;
  name: string;
  kind?: 'index' | 'stock';
  /** Wikidata item the mark was resolved through. */
  wikidata?: string;
  /** Commons file name, when the mark came from Commons. */
  commons?: string;
  /** Page the file came from — the licence lives there. */
  source?: string;
  via?: 'commons' | 'site-icon';
}

const BASE = '/brand/underlyings';

let manifest: Record<string, UnderlyingLogo> | null = null;
let inflight: Promise<Record<string, UnderlyingLogo>> | null = null;

/** The manifest, loaded once. An absent or broken file resolves to {}. */
export function loadUnderlyingLogos(): Promise<Record<string, UnderlyingLogo>> {
  if (manifest) return Promise.resolve(manifest);
  if (inflight) return inflight;
  if (typeof fetch !== 'function') return Promise.resolve({});
  inflight = fetch(`${BASE}/manifest.json`)
    .then(response => (response.ok ? response.json() : {}))
    .then((data: Record<string, UnderlyingLogo>) => {
      manifest = data && typeof data === 'object' ? data : {};
      return manifest;
    })
    .catch(() => {
      manifest = {};
      return manifest;
    });
  return inflight;
}

/** The logo URL for a symbol, or null when we hold none. Synchronous. */
export function underlyingLogoUrl(symbol: string): string | null {
  const entry = manifest?.[(symbol || '').trim().toUpperCase()];
  return entry ? `${BASE}/${entry.file}` : null;
}
