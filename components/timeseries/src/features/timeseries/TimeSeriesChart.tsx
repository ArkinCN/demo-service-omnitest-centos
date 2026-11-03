import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import './timeseries.css';

import { alignSeries } from './align';
import { overlayPlugin } from './overlay';
import { formatTime, formatValue } from './format';
import type { TimeSeriesChartProps } from './types';

const PALETTE_VARS = ['--ts-ch-1', '--ts-ch-2', '--ts-ch-3', '--ts-ch-4', '--ts-ch-5'];

function readVar(el: Element, name: string, fallback: string): string {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || fallback;
}

/**
 * Canvas silently ignores a `var(--x)` colour, leaving the previous fill in
 * place — which is how white-on-white labels happen. Resolve any custom
 * property against the live element before it reaches the 2D context.
 */
function resolveColor(el: Element | null, color: string | undefined, fallback: string): string {
  if (!color) return fallback;
  const m = /^var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)$/.exec(color.trim());
  if (!m) return color;
  if (!el) return m[2]?.trim() || fallback;
  return readVar(el, m[1], m[2]?.trim() || fallback);
}

/**
 * Multi-channel oscilloscope-style time series plot.
 *
 * Rendering is delegated to uPlot; this component owns the React lifecycle, the
 * cursor readout, the legend, and the annotation/threshold overlay. The cursor
 * readout is written straight into the DOM rather than through React state so a
 * mouse sweep over a million-point capture does not trigger a render per frame.
 */
export function TimeSeriesChart({
  series,
  cursor = true,
  zoom = true,
  legend = true,
  annotations = [],
  thresholds = [],
  showOverlayLabels = true,
  height = 320,
  xLabel = '时间 (s)',
  className,
}: TimeSeriesChartProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const uRef = useRef<uPlot | null>(null);
  const readoutRef = useRef<HTMLDivElement>(null);

  const [hidden, setHidden] = useState<Set<number>>(() => new Set());

  // Overlay data is read at draw time, so a change to annotations or thresholds
  // only needs a redraw — not a full chart rebuild.
  const overlayRef = useRef({ annotations, thresholds, showOverlayLabels });
  overlayRef.current = { annotations, thresholds, showOverlayLabels };

  const aligned = useMemo(() => alignSeries(series), [series]);

  const colors = useMemo(() => {
    const root = rootRef.current;
    const fallback = ['#2E5E45', '#6B9E82', '#2C2C2C', '#A6353A', '#A8C5B5'];
    return series.map((s, i) => {
      if (s.color) return s.color;
      if (!root) return fallback[i % fallback.length];
      if (s.status === 'pass') return readVar(root, '--color-primary', '#2E5E45');
      if (s.status === 'fail') return readVar(root, '--color-accent', '#A6353A');
      return readVar(root, PALETTE_VARS[i % PALETTE_VARS.length], fallback[i % fallback.length]);
    });
    // `mounted` forces one recompute after the first paint, when CSS vars resolve.
  }, [series, rootRef.current]);

  // --- build / rebuild the plot ----------------------------------------
  useLayoutEffect(() => {
    const host = plotRef.current;
    const root = rootRef.current;
    if (!host || !root || series.length === 0) return;

    const axisColor = readVar(root, '--color-text-muted', '#555555');
    const gridColor = readVar(root, '--color-grid', '#ECEAE5');
    const bgColor = readVar(root, '--color-bg', '#ffffff');

    const opts: uPlot.Options = {
      width: host.clientWidth || 800,
      height: Math.max(120, height - (legend ? 26 : 0) - (cursor ? 22 : 0)),
      padding: [12, 12, 0, 0],
      legend: { show: false },
      cursor: {
        show: cursor,
        x: cursor,
        y: cursor,
        drag: { x: zoom, y: false, setScale: zoom },
        points: { size: 6 },
      },
      scales: { x: { time: false } },
      axes: [
        {
          label: xLabel,
          labelSize: 26,
          labelFont: '12px system-ui, -apple-system, sans-serif',
          font: '11px system-ui, -apple-system, sans-serif',
          stroke: axisColor,
          grid: { stroke: gridColor, width: 1 },
          ticks: { stroke: gridColor, width: 1 },
        },
        {
          label: series.length === 1 ? `${series[0].name} (${series[0].unit})` : '幅值',
          labelSize: 26,
          labelFont: '12px system-ui, -apple-system, sans-serif',
          font: '11px system-ui, -apple-system, sans-serif',
          stroke: axisColor,
          grid: { stroke: gridColor, width: 1 },
          ticks: { stroke: gridColor, width: 1 },
          size: 56,
        },
      ],
      series: [
        { label: xLabel },
        ...series.map((s, i) => ({
          label: s.name,
          stroke: colors[i],
          width: 1.4,
          spanGaps: !aligned.uniform,
          points: { show: false },
        })),
      ],
      plugins: [
        overlayPlugin(() => ({
          annotations: overlayRef.current.annotations.map((a) => ({
            ...a,
            color: resolveColor(root, a.color, readVar(root, '--color-primary', '#2E5E45')),
          })),
          thresholds: overlayRef.current.thresholds.map((t) => ({
            ...t,
            color: resolveColor(root, t.color, readVar(root, '--color-accent', '#A6353A')),
          })),
          showLabels: overlayRef.current.showOverlayLabels,
          palette: {
            annotation: readVar(root, '--color-primary', '#2E5E45'),
            threshold: readVar(root, '--color-accent', '#A6353A'),
            bg: bgColor,
          },
        })),
      ],
      hooks: {
        setCursor: [
          (u) => {
            const out = readoutRef.current;
            if (!out) return;
            const idx = u.cursor.idx;
            const parts: string[] = [];
            if (idx == null) {
              parts.push('<span class="ts-readout-t">游标：移入图区读数</span>');
            } else {
              const t = (u.data[0] as ArrayLike<number>)[idx];
              parts.push(`<span class="ts-readout-t">t = ${formatTime(t)}</span>`);
              series.forEach((s, i) => {
                if (u.series[i + 1].show === false) return;
                const v = (u.data[i + 1] as ArrayLike<number | null>)[idx];
                parts.push(
                  `<span><span style="color:${colors[i]}">${s.name}</span> ` +
                    `<span class="ts-readout-v">${formatValue(v as number, s.unit)}</span></span>`,
                );
              });
            }
            out.innerHTML = parts.join('');
          },
        ],
      },
    };

    // uPlot mutates nothing in these arrays; the cast covers its union data type.
    const data = [aligned.x, ...aligned.ys] as unknown as uPlot.AlignedData;
    const u = new uPlot(opts, data, host);
    uRef.current = u;

    // Double-click resets both scales to auto-range.
    const onDblClick = () => {
      u.setScale('x', { min: null as unknown as number, max: null as unknown as number });
    };
    u.over.addEventListener('dblclick', onDblClick);

    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry.contentRect.width);
      if (w > 0 && w !== u.width) u.setSize({ width: w, height: u.height });
    });
    ro.observe(host);

    return () => {
      ro.disconnect();
      u.over.removeEventListener('dblclick', onDblClick);
      u.destroy();
      uRef.current = null;
    };
  }, [aligned, series, colors, cursor, zoom, legend, height, xLabel]);

  // --- redraw when only the overlay changed -----------------------------
  useEffect(() => {
    uRef.current?.redraw(false, false);
  }, [annotations, thresholds, showOverlayLabels]);

  // --- legend visibility toggles ---------------------------------------
  useEffect(() => {
    const u = uRef.current;
    if (!u) return;
    series.forEach((_, i) => u.setSeries(i + 1, { show: !hidden.has(i) }));
  }, [hidden, series]);

  const toggle = (i: number) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  return (
    <div ref={rootRef} className={['ts-root', className].filter(Boolean).join(' ')}>
      {legend && (
        <div className="ts-head">
          <div className="ts-legend">
            {series.map((s, i) => (
              <button
                key={`${s.name}-${i}`}
                type="button"
                className="ts-legend-item"
                aria-pressed={!hidden.has(i)}
                onClick={() => toggle(i)}
                title="点击显示或隐藏该通道"
              >
                <span className="ts-legend-swatch" style={{ borderTopColor: colors[i] }} />
                {s.name}
                {s.unit ? ` (${s.unit})` : ''}
              </button>
            ))}
          </div>
        </div>
      )}
      <div ref={plotRef} className="ts-plot" />
      {cursor && <div ref={readoutRef} className="ts-readout" />}
      {zoom && <div className="ts-hint">横向拖拽框选放大，双击复位</div>}
    </div>
  );
}

export default TimeSeriesChart;
