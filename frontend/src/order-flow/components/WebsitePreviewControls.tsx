import { createContext, useContext, type ReactNode } from 'react';
import { SearchIcon } from '@/order-flow/assets/svg';
import { applyTheme } from '@/order-flow/lib/applyTheme';
import { ThemeToggle } from './chrome/ThemeToggle';

interface PreviewControls {
  symbol: string;
  searchOpen: boolean;
  onSearch: () => void;
  /** The index ticker capsule each page bar carries between its title and its actions (desktop). */
  ticker?: ReactNode;
}
const Controls = createContext<PreviewControls | null>(null);
export const WebsitePreviewControlsProvider = Controls.Provider;
export const useWebsitePreviewControls = () => useContext(Controls);

/** Reuses the App's instrument picker; never adds a second search system. */
export function WebsitePreviewSearch() {
  const controls = useWebsitePreviewControls();
  if (!controls) return null;
  return <button
    type="button"
    className={`ui-pagebar__secondary ui-preview-search${controls.searchOpen ? ' is-active' : ''}`}
    data-underlying-search-layer
    aria-label={`Search instruments. Current symbol ${controls.symbol}.`}
    aria-haspopup="dialog"
    aria-expanded={controls.searchOpen}
    aria-keyshortcuts="Control+K Meta+K"
    onClick={controls.onSearch}
  ><SearchIcon size={15} aria-hidden="true" /><span>Search</span></button>;
}

/**
 * The theme switch, kept in the tool's own bar: the website header carries no
 * toggle. It is the app's one ThemeToggle on the shared theme store, so the
 * bridge reports the change to the header like any other. Bars that sit inside
 * a null context (the cockpit's) pass `enabled` themselves.
 */
export function WebsitePreviewTheme({ enabled }: { enabled?: boolean } = {}) {
  const controls = useWebsitePreviewControls();
  if (!(enabled ?? controls)) return null;
  return <ThemeToggle className="ui-preview-theme" size="md" onChange={theme => applyTheme(theme)} />;
}
