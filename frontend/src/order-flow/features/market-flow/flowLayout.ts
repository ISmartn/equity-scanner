/**
 * Pure layout helpers for the Order Flow plane. No React, no DOM: the plane
 * hands in numbers and draws what comes back, which is what lets the label
 * stacking be unit-tested.
 */

export interface LabelAnchor {
  id: string;
  /** Where the label wants to sit: the vertical centre of the line's end, px. */
  y: number;
}

export interface LabelBounds {
  /** One label's height, px: the least distance between two label centres. */
  height: number;
  /** The highest and lowest centre a label may take, px. */
  top: number;
  bottom: number;
}

/** How many labels fit in the bounds when each takes `height`. */
export function labelCapacity({ height, top, bottom }: LabelBounds): number {
  return Math.max(0, Math.floor((bottom - top) / height) + 1);
}

/**
 * Lays labels out so no two overprint: each sits as near its own line's end as
 * the others allow, and a crowd is laid down one label height apart, centred
 * on where its members wanted to be (the approach the the app chart plane takes
 * for its level tags). The result is clamped inside the bounds. More labels
 * than the bounds hold cannot all be kept apart: callers cut the list to
 * `labelCapacity` first.
 */
export function stackLabels(anchors: readonly LabelAnchor[], bounds: LabelBounds): Map<string, number> {
  const { height, top, bottom } = bounds;
  const sorted = [...anchors].sort((a, b) => a.y - b.y || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  interface Cluster { ids: string[]; wanted: number[]; start: number }
  const clusters: Cluster[] = [];
  const startOf = (cluster: Cluster) => {
    // Centre the stack on the mean of where its members wanted to be, then keep it inside the bounds.
    const mean = cluster.wanted.reduce((sum, y, i) => sum + (y - i * height), 0) / cluster.wanted.length;
    const lo = top;
    const hi = bottom - (cluster.ids.length - 1) * height;
    return Math.max(lo, Math.min(hi, mean));
  };
  for (const anchor of sorted) {
    let current: Cluster = { ids: [anchor.id], wanted: [anchor.y], start: 0 };
    current.start = startOf(current);
    let previous = clusters[clusters.length - 1];
    while (previous && previous.start + previous.ids.length * height > current.start + 1e-9) {
      current = { ids: [...previous.ids, ...current.ids], wanted: [...previous.wanted, ...current.wanted], start: 0 };
      current.start = startOf(current);
      clusters.pop();
      previous = clusters[clusters.length - 1];
    }
    clusters.push(current);
  }
  const out = new Map<string, number>();
  for (const cluster of clusters) cluster.ids.forEach((id, i) => out.set(id, cluster.start + i * height));
  return out;
}

/** A tick step from `candidates` that leaves at least `minGap` px between ticks over `span`, the first that does. */
export function niceStep(range: number, plotPx: number, minGap: number, candidates: readonly number[]): number {
  for (const step of candidates) if ((range / step) * minGap <= plotPx) return step;
  return candidates[candidates.length - 1];
}

/** Candidate steps for the change axis, in %. */
export const CHANGE_STEPS = [0.1, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 50] as const;
/** Candidate steps for the time axis, in minutes. */
export const TIME_STEPS_MIN = [5, 10, 15, 30, 60, 120] as const;

/** The value at quantile `q` (0 to 1) of an ascending list; 0 for an empty one. */
export function quantile(sorted: readonly number[], q: number): number {
  if (!sorted.length) return 0;
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)))];
}

/**
 * How far the change axis reaches, % either side of nought: the 99th percentile
 * move (a wild print or two is clamped to the edge rather than squashing the
 * rest onto the zero rule), never less than twice the floor, and never short of
 * `include` (the picks, which are drawn bold and must not be clamped).
 */
export function axisReach(changes: readonly number[], floorPct: number, include = 0): number {
  const sorted = changes.map(Math.abs).sort((a, b) => a - b);
  return Math.max(floorPct * 2, quantile(sorted, 0.99) * 1.06, include * 1.05, 0.2);
}
