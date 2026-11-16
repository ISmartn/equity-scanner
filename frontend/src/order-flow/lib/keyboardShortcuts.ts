/** Shared boundaries for app shortcuts. Local controls keep their own keys. */
const EDITABLE = 'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]';
const LOCAL = '[role="dialog"], [aria-modal="true"], [role="menu"], [role="listbox"], [role="combobox"], [role="slider"], [role="spinbutton"], [aria-haspopup][aria-expanded="true"]';

function closest(target: EventTarget | null, selector: string): boolean {
  return target instanceof Element && Boolean(target.closest(selector));
}

export function isEditableTarget(target: EventTarget | null): boolean {
  return closest(target, EDITABLE);
}

export function isShortcutTarget(target: EventTarget | null): boolean {
  return isEditableTarget(target) || closest(target, LOCAL);
}

export function isComposingKey(event: { isComposing?: boolean; keyCode?: number }): boolean {
  return Boolean(event.isComposing || event.keyCode === 229);
}

export const WORKSPACE_SHORTCUTS = [
  ['1', 'chain', 'Option Chain'],
  ['2', 'options-scanner', 'Options Scanner'],
  ['3', 'strategy-builder', 'Strategy Builder'],
  ['4', 'open-interest', 'Open Interest'],
  ['5', 'oi-spurts', 'Open Interest Spurts'],
  ['6', 'oi-heatmap', 'Open Interest Heatmap'],
  ['7', 'pcr', 'PCR'],
  ['8', 'straddle', 'Straddle'],
  ['9', 'gex', 'GEX Levels'],
  ['0', 'implied-volatility', 'Implied Volatility'],
  ['-', 'terminal', 'Trader Cockpit'],
  ['=', 'market-flow', 'Order Flow'],
] as const;

export function workspaceShortcut(routeId: string): string | undefined {
  return WORKSPACE_SHORTCUTS.find(([, route]) => route === routeId)?.[0];
}
