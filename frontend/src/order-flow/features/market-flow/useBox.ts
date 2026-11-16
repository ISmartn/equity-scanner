import { useEffect, useState } from 'react';

/** An element's laid-out width and height, kept current; zeros until it has a width (a height of nought is taken: a box sized by its content). */
export function useBox<T extends HTMLElement>(): [(node: T | null) => void, { width: number; height: number }] {
  const [node, setNode] = useState<T | null>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!node) return undefined;
    const take = (width: number, height: number) => {
      const w = Math.round(width);
      const h = Math.round(height);
      if (w > 0) setBox(current => (current.width === w && current.height === h ? current : { width: w, height: h }));
    };
    const rect = node.getBoundingClientRect();
    take(rect.width, rect.height);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(entries => {
      const r = entries[0]?.contentRect;
      if (r) take(r.width, r.height);
    });
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);
  return [setNode, box];
}
