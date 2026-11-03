import type { Series } from './types';

export interface AlignedData {
  /** Shared x axis. */
  x: Float64Array | number[];
  /** One y array per input series, index-aligned to `x`. `null` marks a gap. */
  ys: Array<Float64Array | Array<number | null>>;
  /** True when every series already shared one x axis, so no gap filling happened. */
  uniform: boolean;
}

function sameAxis(a: Series['x'], b: Series['x']): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  const n = a.length;
  if (n === 0) return true;
  // Endpoints plus a few interior probes catch every realistic mismatch without
  // paying an O(n) comparison on million-point captures.
  const probes = [0, n - 1, n >> 1, n >> 2, (n * 3) >> 2];
  for (const i of probes) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * uPlot needs one x axis shared by all series. Channels captured in the same
 * sweep already share it, which is the fast path. When they do not, the union of
 * all timestamps is used and each series is padded with `null` at foreign
 * timestamps — no interpolation, so no fabricated sample ever reaches the plot.
 */
export function alignSeries(series: Series[]): AlignedData {
  if (series.length === 0) return { x: [], ys: [], uniform: true };

  const first = series[0].x;
  if (series.every((s) => sameAxis(s.x, first))) {
    return {
      x: first as Float64Array | number[],
      ys: series.map((s) => s.y as Float64Array),
      uniform: true,
    };
  }

  const union = new Set<number>();
  for (const s of series) for (let i = 0; i < s.x.length; i++) union.add(s.x[i]);
  const x = Float64Array.from(union).sort();

  const index = new Map<number, number>();
  for (let i = 0; i < x.length; i++) index.set(x[i], i);

  const ys = series.map((s) => {
    const col: Array<number | null> = new Array(x.length).fill(null);
    for (let i = 0; i < s.x.length; i++) {
      const at = index.get(s.x[i]);
      if (at !== undefined) col[at] = s.y[i];
    }
    return col;
  });

  return { x, ys, uniform: false };
}
