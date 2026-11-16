/**
 * Order Flow: the standalone board (github.com/MrChartist/order-flow), mounted
 * in the lab. Its data comes from the lab's own API (/api/order-flow/*).
 *
 * The board's stylesheets come from the standalone app's cascade, in the same
 * order its main.tsx loads them, and they are imported first so the cascade
 * matches. Under src/order-flow/styles they are scoped to `.ol-scope` by
 * postcss-order-flow-scope.mjs, so they reach this page and nothing else.
 * order-flow-lab.css is last: it drops the standalone site chrome and paints
 * the board with the lab's surfaces, type and up/down colours.
 */
import "@/order-flow/styles/oi-design-tokens.css";
import "@/order-flow/styles/ui-theme.css";
import "@/order-flow/styles/ui-prototype-system.css";
import "@/order-flow/styles/ui-colour-system.css";
import "@/order-flow/styles/ui-market-semantics.css";
import "@/order-flow/styles/ui-typography.css";
import "@/order-flow/styles/ui-light-surface-authority.css";
import "@/order-flow/styles/ui-chain-no-purple.css";
import "@/order-flow/styles/ui-motion.css";
import "@/order-flow/styles/ui-apple-finish.css";
import "@/order-flow/styles/ui-selection-pills.css";
import "@/order-flow/styles/ui-strike-studio-authority.css";
import "@/order-flow/styles/ui-chart-stage-authority.css";
import "@/order-flow/styles/ui-control-capsule-authority.css";
import "@/order-flow/styles/ui-wide-screen.css";
import "@/order-flow/styles/ui-borders.css";
import "@/order-flow/styles/ui-box-system.css";
import "./order-flow-lab.css";

import { useEffect, useLayoutEffect, useState } from "react";
import { UiIconProvider } from "@/order-flow/assets/svg";
import { MarketFlowPage } from "@/order-flow/features/market-flow/MarketFlowPage";
import { loadUnderlyings, type Underlying } from "@/order-flow/lib/underlyings";

export function OrderFlowPage() {
  const [universe, setUniverse] = useState<Underlying[]>([]);

  useLayoutEffect(() => {
    // The board used to write its own light theme onto the document. The lab is dark; clear that if a previous visit left it.
    const root = document.documentElement;
    delete root.dataset.theme;
    root.style.colorScheme = "dark";
  }, []);

  useEffect(() => {
    loadUnderlyings().then(setUniverse);
  }, []);

  return (
    <div className="page-shell flex min-h-0 flex-col overflow-hidden px-1.5 py-1 sm:px-2">
      <UiIconProvider>
        <div className="ol-scope flex min-h-0 flex-1 flex-col" data-theme="dark">
          <MarketFlowPage universe={universe} />
        </div>
      </UiIconProvider>
    </div>
  );
}
