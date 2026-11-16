/**
 * Scopes the Order Flow board's global token sheets under `.ol-scope`.
 *
 * The board's design tokens (`--up`, `--font-sans`, …) and its theme rules
 * are written for the standalone app's document: `:root` and `html, body`
 * carry them. Copied into this app unchanged, they would restyle every page.
 * This plugin rewrites the selectors of the sheets under `src/order-flow/styles/`
 * so they apply only inside the wrapper the Order Flow page renders:
 *
 *   :root                  →  .ol-scope
 *   :root[data-theme=x]    →  .ol-scope[data-theme=x]
 *   html, body, #root      →  .ol-scope
 *   anything else          →  .ol-scope <selector>
 *
 * `@font-face` and `@keyframes` are global by nature and are left alone.
 */
const SCOPE = '.ol-scope';
const SHEETS = '/src/order-flow/styles/';

function scopeSelector(selector) {
  const sel = selector.trim();
  const root = /^(:root|html|body|#root)/.exec(sel);
  if (root) return SCOPE + sel.slice(root[1].length);
  return `${SCOPE} ${sel}`;
}

function orderFlowScope() {
  return {
    postcssPlugin: 'order-flow-scope',
    Once(root) {
      const file = (root.source?.input?.file ?? '').replace(/\\/g, '/');
      if (!file.includes(SHEETS)) return;
      root.walkRules(rule => {
        if (rule.parent?.type === 'atrule' && /keyframes$/i.test(rule.parent.name)) return;
        rule.selectors = rule.selectors.map(scopeSelector);
      });
    },
  };
}
orderFlowScope.postcss = true;

export default orderFlowScope;
