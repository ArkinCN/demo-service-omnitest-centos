/**
 * Min/max decimation worker.
 *
 * Plain stride sampling drops the very features an oscilloscope capture exists
 * to show — commutation spikes on the FG feedback lines, PWM edges. Min/max
 * decimation instead splits the record into buckets and keeps both extremes of
 * every bucket, so the drawn envelope still touches every peak in the raw data.
 *
 * All channels share one bucket grid, which keeps a single x axis for the whole
 * frame: two output samples per bucket, anchored on the first and last real
 * timestamp inside it.
 */

export interface DecimateRequest {
  id: number;
  x: Float64Array;
  ys: Float64Array[];
  /** Desired output length in points. Rounded down to an even number. */
  target: number;
}

export interface DecimateResponse {
  id: number;
  x: Float64Array;
  ys: Float64Array[];
  inputPoints: number;
  outputPoints: number;
  elapsedMs: number;
}

export function decimateMinMax(
  x: Float64Array,
  ys: Float64Array[],
  target: number,
): { x: Float64Array; ys: Float64Array[] } {
  const n = x.length;
  const buckets = Math.max(1, Math.floor(target / 2));
  if (n <= buckets * 2) return { x, ys };

  const size = Math.floor(n / buckets);
  const outLen = buckets * 2;
  const ox = new Float64Array(outLen);
  const oys = ys.map(() => new Float64Array(outLen));

  for (let b = 0; b < buckets; b++) {
    const start = b * size;
    // The final bucket absorbs the remainder so no tail sample is discarded.
    const end = b === buckets - 1 ? n : start + size;
    ox[b * 2] = x[start];
    ox[b * 2 + 1] = x[end - 1];

    for (let c = 0; c < ys.length; c++) {
      const src = ys[c];
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = start; i < end; i++) {
        const v = src[i];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (lo === Infinity) {
        lo = NaN;
        hi = NaN;
      }
      oys[c][b * 2] = lo;
      oys[c][b * 2 + 1] = hi;
    }
  }
  return { x: ox, ys: oys };
}

self.onmessage = (e: MessageEvent<DecimateRequest>) => {
  const { id, x, ys, target } = e.data;
  const t0 = performance.now();
  const out = decimateMinMax(x, ys, target);
  const res: DecimateResponse = {
    id,
    x: out.x,
    ys: out.ys,
    inputPoints: x.length,
    outputPoints: out.x.length,
    elapsedMs: performance.now() - t0,
  };
  (self as unknown as Worker).postMessage(res, [
    out.x.buffer,
    ...out.ys.map((a) => a.buffer),
  ] as unknown as Transferable[]);
};
