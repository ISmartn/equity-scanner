/* One writer for the document theme. Called straight from the click handler so
 * the repaint does not wait for React to re-render the whole App, and it
 * freezes CSS transitions for two frames — otherwise every cell with a
 * colour/background transition animates the swap on its own timeline, which
 * is the "everything feels delayed" lag. */

export type ThemeMode = 'light' | 'dark';

let releaseFrame = 0;
const listeners = new Set<() => void>();

/** The document's current theme: the attribute is the one source of truth. */
export function getTheme(): ThemeMode {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

/** The theme as the user last chose it (boot default: light). */
export function readStoredTheme(): ThemeMode {
  try { return localStorage.getItem('preferredTheme') === 'dark' ? 'dark' : 'light'; } catch { return 'light'; }
}

/** useSyncExternalStore subscribe: only the few components that draw the theme re-render. */
export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function applyTheme(theme: ThemeMode, persist = true): void {
  const root = document.documentElement;
  if (root.dataset.theme === theme && root.style.colorScheme === theme) return;
  root.dataset.themeSwitching = '';
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => {
    m.setAttribute('content', theme === 'light' ? '#FFFFFF' : '#0F0F0F');
  });
  if (persist) {
    try { localStorage.setItem('preferredTheme', theme); } catch { /* storage blocked */ }
  }
  listeners.forEach((l) => l());
  cancelAnimationFrame(releaseFrame);
  releaseFrame = requestAnimationFrame(() => {
    releaseFrame = requestAnimationFrame(() => {
      /* Two animation frames do not guarantee a rendering update between them
         (a throttled or hidden page runs both back to back). Flush the swapped
         styles while the freeze still holds, so lifting it can never be the
         first time the new theme is computed: that is what let every cell
         start its own colour transition (seconds of main-thread work). */
      void getComputedStyle(root).color;
      delete root.dataset.themeSwitching;
    });
  });
}
