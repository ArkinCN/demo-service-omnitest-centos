import type { DecimateRequest, DecimateResponse } from './decimate.worker';
import type { Series } from './types';

export interface LoadCsvOptions {
  /**
   * Decimate once the record reaches this many samples per channel.
   * Default 500_000.
   */
  decimateThreshold?: number;
  /** Point count to decimate down to. Default 4000. */
  decimateTarget?: number;
  /** Name of the time column. Defaults to the first numeric column. */
  timeColumn?: string;
  signal?: AbortSignal;
}

export interface LoadCsvResult {
  /** One entry per numeric non-time column, ready to hand to `TimeSeriesChart`. */
  series: Series[];
  /** Shared time axis in seconds. */
  time: Float64Array;
  /** Header names kept after dropping empty and non-numeric columns. */
  columns: string[];
  /** Header names dropped because they held no parsable numbers. */
  droppedColumns: string[];
  /** Median sampling rate in samples per second, or null if undeterminable. */
  sampleRate: number | null;
  /** Samples per channel present in the file. */
  rawPoints: number;
  /** Samples per channel actually handed to the chart. */
  plottedPoints: number;
  decimated: boolean;
  timings: {
    fetchMs: number;
    parseMs: number;
    decimateMs: number;
    totalMs: number;
  };
}

/** Infers a unit from a column name suffix, e.g. `ch2_fg1_V` -> "V". */
export function inferUnit(column: string): string {
  const m = /_([A-Za-z]+)$/.exec(column);
  if (!m) return '';
  const tail = m[1];
  const map: Record<string, string> = { v: 'V', a: 'A', ma: 'mA', s: 's', ms: 'ms', hz: 'Hz', rpm: 'rpm' };
  return map[tail.toLowerCase()] ?? '';
}

/** Strips the unit suffix so the legend reads `ch2 fg1` rather than `ch2_fg1_V`. */
export function prettyName(column: string): string {
  return column.replace(/_([A-Za-z]+)$/, '').replace(/_/g, ' ');
}

let workerSeq = 0;
let workerInstance: Worker | null = null;

function getWorker(): Worker | null {
  if (typeof Worker === 'undefined') return null;
  if (!workerInstance) {
    workerInstance = new Worker(new URL('./decimate.worker.ts', import.meta.url), { type: 'module' });
  }
  return workerInstance;
}

function decimateInWorker(
  x: Float64Array,
  ys: Float64Array[],
  target: number,
): Promise<DecimateResponse> {
  const worker = getWorker();
  if (!worker) return Promise.reject(new Error('Web Worker unavailable'));

  const id = ++workerSeq;
  return new Promise((resolve, reject) => {
    const onMessage = (e: MessageEvent<DecimateResponse>) => {
      if (e.data.id !== id) return;
      worker.removeEventListener('message', onMessage);
      worker.removeEventListener('error', onError);
      resolve(e.data);
    };
    const onError = (e: ErrorEvent) => {
      worker.removeEventListener('message', onMessage);
      worker.removeEventListener('error', onError);
      reject(e.error ?? new Error(e.message));
    };
    worker.addEventListener('message', onMessage);
    worker.addEventListener('error', onError);
    const req: DecimateRequest = { id, x, ys, target };
    // Buffers are transferred, so the caller must not touch them afterwards.
    worker.postMessage(req, [x.buffer, ...ys.map((a) => a.buffer)]);
  });
}

/** Median of the first-differences of the time column, used for the sample rate. */
function medianSampleRate(t: Float64Array): number | null {
  const n = Math.min(t.length - 1, 2000);
  if (n < 2) return null;
  const d: number[] = [];
  for (let i = 0; i < n; i++) {
    const dt = t[i + 1] - t[i];
    if (Number.isFinite(dt) && dt > 0) d.push(dt);
  }
  if (d.length === 0) return null;
  d.sort((a, b) => a - b);
  const mid = d[d.length >> 1];
  return mid > 0 ? 1 / mid : null;
}

/**
 * Fetches and parses a CSV capture into chart-ready channels.
 *
 * Columns that hold no parsable numbers (text tags, empty placeholder columns
 * such as `raw_byte`) are dropped and reported in `droppedColumns`. Records at
 * or above `decimateThreshold` samples are min/max decimated in a Web Worker so
 * the main thread never blocks on a multi-million-point file.
 */
export async function loadCsv(url: string, options: LoadCsvOptions = {}): Promise<LoadCsvResult> {
  const {
    decimateThreshold = 500_000,
    decimateTarget = 4000,
    timeColumn,
    signal,
  } = options;

  const tStart = performance.now();
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`加载 ${url} 失败：HTTP ${res.status}`);
  const text = await res.text();
  const fetchMs = performance.now() - tStart;

  const tParse = performance.now();
  // Strip a UTF-8 BOM; the scope export tool writes one.
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const lines = body.split(/\r?\n/);
  let headerIdx = 0;
  while (headerIdx < lines.length && lines[headerIdx].trim() === '') headerIdx++;
  if (headerIdx >= lines.length) throw new Error(`${url} 为空文件`);

  const header = lines[headerIdx].split(',').map((h) => h.trim());
  const rows = lines.slice(headerIdx + 1).filter((l) => l.length > 0);
  const nRows = rows.length;
  if (nRows === 0) throw new Error(`${url} 没有数据行`);

  // Probe up to 200 rows to decide which columns carry numbers.
  const probeCount = Math.min(nRows, 200);
  const probeStep = Math.max(1, Math.floor(nRows / probeCount));
  const numericHits = new Array(header.length).fill(0);
  let probed = 0;
  for (let r = 0; r < nRows; r += probeStep) {
    const cells = rows[r].split(',');
    for (let c = 0; c < header.length; c++) {
      const cell = cells[c];
      if (cell !== undefined && cell.trim() !== '' && Number.isFinite(Number(cell))) numericHits[c]++;
    }
    probed++;
  }
  const keep: number[] = [];
  const droppedColumns: string[] = [];
  for (let c = 0; c < header.length; c++) {
    if (numericHits[c] / probed > 0.5) keep.push(c);
    else droppedColumns.push(header[c]);
  }
  if (keep.length < 2) throw new Error(`${url} 中可用的数值列不足两列`);

  const timeIdx = timeColumn ? header.indexOf(timeColumn) : keep[0];
  if (timeIdx < 0 || !keep.includes(timeIdx)) throw new Error(`${url} 中找不到数值型时间列`);
  const valueIdx = keep.filter((c) => c !== timeIdx);

  const time = new Float64Array(nRows);
  const ys = valueIdx.map(() => new Float64Array(nRows));
  for (let r = 0; r < nRows; r++) {
    const cells = rows[r].split(',');
    time[r] = Number(cells[timeIdx]);
    for (let k = 0; k < valueIdx.length; k++) ys[k][r] = Number(cells[valueIdx[k]]);
  }
  const parseMs = performance.now() - tParse;
  const sampleRate = medianSampleRate(time);

  // Widened element type: buffers coming back from the worker are typed
  // `ArrayBufferLike`, which does not narrow to the `ArrayBuffer` inferred here.
  let outX: Float64Array<ArrayBufferLike> = time;
  let outYs: Float64Array<ArrayBufferLike>[] = ys;
  let decimated = false;
  let decimateMs = 0;

  if (nRows >= decimateThreshold) {
    try {
      const r = await decimateInWorker(time, ys, decimateTarget);
      outX = r.x;
      outYs = r.ys;
      decimated = true;
      decimateMs = r.elapsedMs;
    } catch {
      // Worker unavailable (older runtime, blocked by CSP): fall back to the
      // full record rather than failing the load outright.
      decimated = false;
    }
  }

  const series: Series[] = valueIdx.map((c, k) => ({
    name: prettyName(header[c]),
    unit: inferUnit(header[c]),
    x: outX,
    y: outYs[k],
  }));

  return {
    series,
    time: outX,
    columns: keep.map((c) => header[c]),
    droppedColumns,
    sampleRate,
    rawPoints: nRows,
    plottedPoints: outX.length,
    decimated,
    timings: {
      fetchMs,
      parseMs,
      decimateMs,
      totalMs: performance.now() - tStart,
    },
  };
}
