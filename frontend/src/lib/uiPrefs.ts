/** Persist UI filter/toggle prefs across page navigations. */

export function loadUiPrefs<T extends Record<string, unknown>>(key: string, defaults: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { ...defaults };
    const parsed = JSON.parse(raw) as Partial<T>;
    if (!parsed || typeof parsed !== "object") return { ...defaults };
    return { ...defaults, ...parsed };
  } catch {
    return { ...defaults };
  }
}

export function saveUiPrefs(key: string, prefs: Record<string, unknown>): void {
  try {
    localStorage.setItem(key, JSON.stringify(prefs));
  } catch {
    /* quota / private mode */
  }
}

export function readStringPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeStringPref(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}
