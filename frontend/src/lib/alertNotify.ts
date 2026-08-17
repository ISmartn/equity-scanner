/**
 * Cross-tab alert delivery: sound, browser notifications, title flash, floating toast.
 */

export type AlertTone = "bullish" | "bearish" | "warning" | "info";

const PREFS_KEY = "trading-alert-notify-prefs";
const TITLE_FLASH_MS = 12_000;
const TITLE_FLASH_INTERVAL_MS = 900;

export interface AlertNotifyPrefs {
  sound: boolean;
  browser: boolean;
}

const DEFAULT_PREFS: AlertNotifyPrefs = { sound: true, browser: true };

export function loadAlertNotifyPrefs(): AlertNotifyPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const parsed = JSON.parse(raw) as Partial<AlertNotifyPrefs>;
    return {
      sound: parsed.sound !== false,
      browser: parsed.browser !== false,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function saveAlertNotifyPrefs(partial: Partial<AlertNotifyPrefs>): AlertNotifyPrefs {
  const next = { ...loadAlertNotifyPrefs(), ...partial };
  localStorage.setItem(PREFS_KEY, JSON.stringify(next));
  return next;
}

let audioContext: AudioContext | null = null;
let audioUnlocked = false;

function getAudioContext(): AudioContext {
  if (!audioContext) audioContext = new AudioContext();
  return audioContext;
}

/** Call after a user gesture so sounds work when the tab is in the background. */
export function unlockAlertAudio(): void {
  try {
    const ctx = getAudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    audioUnlocked = true;
  } catch {
    /* ignore */
  }
}

const toneFrequencies: Record<AlertTone, number[]> = {
  bullish: [523.25, 659.25, 783.99],
  bearish: [783.99, 659.25, 523.25],
  warning: [880, 880, 880],
  info: [659.25, 783.99],
};

export function playAlertSound(tone: AlertTone = "warning", volume = 0.45) {
  try {
    const ctx = getAudioContext();
    if (ctx.state === "suspended") void ctx.resume();

    const freqs = toneFrequencies[tone];
    const noteLength = 0.14;

    freqs.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = tone === "warning" ? "square" : "sine";
      osc.frequency.value = freq;
      gain.gain.value = volume;
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + (i + 1) * noteLength + 0.08);
      osc.start(ctx.currentTime + i * noteLength);
      osc.stop(ctx.currentTime + (i + 1) * noteLength + 0.08);
    });
  } catch (e) {
    console.warn("Alert sound failed:", e);
  }
}

let titleFlashTimer: ReturnType<typeof setInterval> | null = null;
let titleFlashStopTimer: ReturnType<typeof setTimeout> | null = null;

export function flashDocumentTitle(alertTitle: string, durationMs = TITLE_FLASH_MS) {
  if (typeof document === "undefined") return;
  const base = document.title;
  let on = false;

  if (titleFlashTimer) clearInterval(titleFlashTimer);
  if (titleFlashStopTimer) clearTimeout(titleFlashStopTimer);

  titleFlashTimer = setInterval(() => {
    on = !on;
    document.title = on ? `🔔 ${alertTitle}` : base;
  }, TITLE_FLASH_INTERVAL_MS);

  titleFlashStopTimer = setTimeout(() => {
    if (titleFlashTimer) clearInterval(titleFlashTimer);
    titleFlashTimer = null;
    document.title = base;
  }, durationMs);
}

export async function requestBrowserNotifyPermission(): Promise<
  NotificationPermission | "unsupported"
> {
  if (typeof Notification === "undefined") return "unsupported";
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  return Notification.requestPermission();
}

export function showBrowserNotification(
  title: string,
  body: string,
  tag?: string,
): boolean {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return false;
  }
  try {
    new Notification(title, {
      body,
      tag: tag ?? title,
      requireInteraction: false,
      silent: false,
    });
    return true;
  } catch {
    return false;
  }
}

function showFloatingToast(title: string, body: string) {
  if (typeof document === "undefined") return;

  const wrap = document.createElement("div");
  wrap.className =
    "fixed bottom-4 right-4 z-[100] max-w-sm rounded-lg border border-amber-500/40 bg-surface-raised px-4 py-3 shadow-xl";
  wrap.setAttribute("role", "alert");

  const heading = document.createElement("p");
  heading.className = "text-sm font-semibold text-amber-200";
  heading.textContent = title;
  wrap.appendChild(heading);

  if (body) {
    const desc = document.createElement("p");
    desc.className = "mt-1 text-xs leading-relaxed text-slate-400";
    desc.textContent = body;
    wrap.appendChild(desc);
  }

  document.body.appendChild(wrap);
  window.setTimeout(() => wrap.remove(), 12_000);
}

export interface NotifyUserAlertOptions {
  title: string;
  body?: string;
  tone?: AlertTone;
  tag?: string;
  toast?: boolean;
  sound?: boolean;
  browser?: boolean;
  flashTitle?: boolean;
}

export function notifyUserAlert(options: NotifyUserAlertOptions) {
  const prefs = loadAlertNotifyPrefs();
  const hidden = typeof document !== "undefined" && document.hidden;
  const sound = options.sound ?? prefs.sound;
  const browser = options.browser ?? prefs.browser;
  const tone = options.tone ?? "warning";
  const body = options.body ?? "";
  const showToast = options.toast ?? !hidden;

  if (showToast) {
    showFloatingToast(options.title, body);
  }

  if (sound) {
    playAlertSound(tone);
  }

  if (browser) {
    showBrowserNotification(options.title, body, options.tag);
  }

  if (hidden && options.flashTitle !== false) {
    flashDocumentTitle(options.title);
  }
}

export function isAlertAudioUnlocked(): boolean {
  return audioUnlocked;
}
