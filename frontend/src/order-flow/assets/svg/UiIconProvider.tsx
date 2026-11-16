import type { ReactNode } from 'react';
import { IconContext, type IconProps } from '@phosphor-icons/react';

/*
 * App-wide Phosphor defaults, applied once at the root instead of on each of
 * the ~50 files that draw a glyph:
 *
 *   - `aria-hidden`: a bare Phosphor <svg> is otherwise announced by some
 *     screen readers as an unlabelled graphic. Every icon beside text or inside
 *     a named button is decoration. An icon that IS the content must opt out
 *     with `aria-hidden={false}` plus `role="img"` and a label (the named
 *     exports in UiIcons do this for you through `title`).
 *   - `focusable="false"`: old Edge/IE tab-stopped inline SVGs.
 *   - `color`/`weight`: one regular cut in the text colour, never a literal.
 */
const UI_ICON_DEFAULTS: IconProps = {
  color: 'currentColor',
  weight: 'regular',
  'aria-hidden': true,
  focusable: 'false',
};

export function UiIconProvider({ children }: { children: ReactNode }) {
  return <IconContext.Provider value={UI_ICON_DEFAULTS}>{children}</IconContext.Provider>;
}
