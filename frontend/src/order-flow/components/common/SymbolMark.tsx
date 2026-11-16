import { useEffect, useState } from 'react';
import { loadUnderlyingLogos, underlyingLogoUrl } from '@/order-flow/lib/underlyingLogos';
import './symbol-mark.css';

/*
 * The instrument's mark.
 *
 * Every insight card used to open with the same bar-chart glyph, which says
 * "a chart" on a screen that is already a chart and never says WHICH
 * instrument is being read. This draws the instrument instead: a monogram
 * built from the symbol, curated for the nine index series and derived for
 * the 208 stock underlyings.
 *
 * Real artwork comes from `public/brand/underlyings/` when we hold a mark for
 * the symbol (see `lib/underlyingLogos`), and the monogram stays behind it as
 * the fallback for a missing entry or a file that fails to load. `src`
 * overrides both.
 *
 * The marks are trademarks of their issuers, shown to identify the instrument
 * being quoted. They are never drawn as an endorsement.
 */

/** The index series, where initials alone would be ambiguous. */
const INDEX_MONOGRAM: Record<string, string> = {
  NIFTY: 'NF',
  BANKNIFTY: 'BN',
  FINNIFTY: 'FN',
  MIDCPNIFTY: 'MC',
  NIFTYNXT50: 'N5',
  SENSEX: 'SX',
  SENSEX50: 'S5',
  BANKEX: 'BX',
  FOCIT: 'IT',
};

/**
 * Two characters, upper case. Curated for an index, and the symbol's own
 * first two letters or digits for a stock — predictable, so the same symbol
 * always draws the same mark.
 */
export function symbolMonogram(symbol: string): string {
  const key = (symbol || '').trim().toUpperCase();
  if (INDEX_MONOGRAM[key]) return INDEX_MONOGRAM[key];
  const letters = key.replace(/[^A-Z0-9]/g, '');
  return letters.slice(0, 2) || '—';
}

interface SymbolMarkProps {
  symbol: string;
  kind?: 'index' | 'stock';
  /** Edge of the square, in pixels. */
  size?: number;
  /** Overrides the held artwork. The monogram stays as the fallback. */
  src?: string;
  /**
   * The native hover title naming the symbol. Off on a reading surface (an
   * insight box), where the name is already printed beside the mark and the
   * owner's rule forbids native tooltips.
   */
  showTitle?: boolean;
  className?: string;
}

export function SymbolMark({ symbol, kind = 'stock', size = 22, src, showTitle = true, className = '' }: SymbolMarkProps) {
  const monogram = symbolMonogram(symbol);
  // The monogram renders on the first paint; artwork replaces it once the
  // manifest has loaded, so a slow or missing manifest costs nothing.
  const [held, setHeld] = useState<string | null>(() => underlyingLogoUrl(symbol));
  const [failed, setFailed] = useState(false);
  // The monogram stays drawn until the artwork has actually painted, so a slow
  // or lazy image never leaves a blank white tile.
  const [loaded, setLoaded] = useState(false);
  // A wordmark is three times wider than it is tall. Contained in a square it
  // becomes an 8px sliver, so the tile widens to fit it instead.
  const [wide, setWide] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setLoaded(false);
    setWide(false);
    setHeld(underlyingLogoUrl(symbol));
    void loadUnderlyingLogos().then(() => { if (!cancelled) setHeld(underlyingLogoUrl(symbol)); });
    return () => { cancelled = true; };
  }, [symbol]);
  const art = failed ? null : src ?? held;
  useEffect(() => { setLoaded(false); }, [art]);
  return (
    <span
      className={`ui-symbol-mark is-${kind}${art && loaded ? ' has-art' : ''}${wide ? ' is-wide' : ''}${className ? ` ${className}` : ''}`}
      style={{ ['--mark-size' as string]: `${size}px` }}
      role="img"
      aria-label={symbol}
      title={showTitle ? symbol : undefined}
    >
      <span className="ui-symbol-mark__text" aria-hidden="true">{monogram}</span>
      {art && <img
        className="ui-symbol-mark__art"
        src={art}
        alt=""
        aria-hidden="true"
        loading="lazy"
        onError={() => setFailed(true)}
        onLoad={event => {
          const image = event.currentTarget;
          if (image.naturalWidth && image.naturalHeight) setWide(image.naturalWidth / image.naturalHeight > 1.6);
          setLoaded(true);
        }}
      />}
    </span>
  );
}
