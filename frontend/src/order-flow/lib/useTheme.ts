import { useSyncExternalStore } from 'react';
import { getTheme, subscribeTheme, type ThemeMode } from './applyTheme';

/** Live theme without making any ancestor own it as state. */
export function useTheme(): ThemeMode {
  return useSyncExternalStore(subscribeTheme, getTheme, () => 'dark');
}
