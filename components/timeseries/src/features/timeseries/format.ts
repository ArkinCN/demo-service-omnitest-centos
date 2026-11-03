/** Formats a measurement with an adaptive number of significant decimals. */
export function formatValue(v: number | null | undefined, unit = ''): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  let s: string;
  if (a === 0) s = '0';
  else if (a >= 1000) s = v.toFixed(0);
  else if (a >= 100) s = v.toFixed(1);
  else if (a >= 1) s = v.toFixed(3);
  else if (a >= 0.001) s = v.toFixed(4);
  else s = v.toExponential(2);
  return unit ? `${s} ${unit}` : s;
}

/** Formats a time in seconds, switching to milliseconds below one second. */
export function formatTime(t: number | null | undefined): string {
  if (t == null || !Number.isFinite(t)) return '—';
  if (Math.abs(t) < 1) return `${(t * 1000).toFixed(1)} ms`;
  return `${t.toFixed(4)} s`;
}

/** Compact point count, e.g. 3000000 -> "3.0 M". */
export function formatCount(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} k`;
  return String(n);
}
