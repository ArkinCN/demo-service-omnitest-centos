/**
 * Demo-side signal analysis. Kept out of `src/features/timeseries/` on purpose:
 * the component library stays generic, these helpers encode Fortior bench
 * semantics (power-on at t = 0, post-power response window).
 */

export interface StartupMetrics {
  /** First instant after power-on where the rolling RMS clears `rmsGate`. */
  firstResponseS: number | null;
  /** RMS over the first second after power-on. */
  firstSecondRms: number;
  /** Peak-to-peak over the whole post-power window. */
  peakToPeak: number;
  /** RMS over the last two seconds, i.e. how quiet the run settles. */
  settledRms: number;
  /** Largest absolute excursion after power-on. */
  peakAbs: number;
}

function rms(v: Float64Array | number[], from: number, to: number): number {
  let acc = 0;
  let n = 0;
  for (let i = from; i < to; i++) {
    const x = v[i];
    if (Number.isFinite(x)) {
      acc += x * x;
      n++;
    }
  }
  return n > 0 ? Math.sqrt(acc / n) : 0;
}

/** Index of the first sample at or after time `t`. */
function indexAt(time: Float64Array | number[], t: number): number {
  let lo = 0;
  let hi = time.length - 1;
  if (time[0] >= t) return 0;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (time[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function analyseStartup(
  time: Float64Array | number[],
  v: Float64Array | number[],
  opts: { rmsGate?: number; window?: number } = {},
): StartupMetrics {
  const { rmsGate = 0.12, window = 200 } = opts;
  const p0 = indexAt(time, 0);
  const n = time.length;

  let peakAbs = 0;
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = p0; i < n; i++) {
    const x = v[i];
    if (!Number.isFinite(x)) continue;
    if (x < lo) lo = x;
    if (x > hi) hi = x;
    const a = Math.abs(x);
    if (a > peakAbs) peakAbs = a;
  }

  let firstResponseS: number | null = null;
  for (let i = p0; i + window < n; i += 5) {
    if (rms(v, i, i + window) > rmsGate) {
      firstResponseS = time[i];
      break;
    }
  }

  const oneSec = indexAt(time, 1);
  const lastTwo = indexAt(time, time[n - 1] - 2);

  return {
    firstResponseS,
    firstSecondRms: rms(v, p0, oneSec),
    peakToPeak: hi > lo ? hi - lo : 0,
    settledRms: rms(v, lastTwo, n),
    peakAbs,
  };
}
