import type uPlot from 'uplot';
import type { Annotation, Threshold } from './types';

interface Palette {
  annotation: string;
  threshold: string;
  bg: string;
}

const LABEL_FAMILY = '"Segoe UI", system-ui, -apple-system, Arial, sans-serif';
const LABEL_PX = 11;
const LANE_H = 16;
const PAD = 4;
const MAX_LANES = 4;

/**
 * Assigns each vertical label to a horizontal lane so neighbouring markers never
 * overprint each other. Labels are walked left to right; a label drops to the
 * next lane whenever it would collide with the last one already placed there.
 */
function assignLanes(positions: number[], widths: number[], gap: number): number[] {
  const order = positions.map((_, i) => i).sort((a, b) => positions[a] - positions[b]);
  const laneEnd: number[] = [];
  const lane = new Array<number>(positions.length).fill(0);

  for (const i of order) {
    const start = positions[i];
    const end = start + widths[i] + gap;
    let placed = false;
    for (let l = 0; l < laneEnd.length; l++) {
      if (start >= laneEnd[l]) {
        lane[i] = l;
        laneEnd[l] = end;
        placed = true;
        break;
      }
    }
    if (!placed) {
      if (laneEnd.length < MAX_LANES) {
        lane[i] = laneEnd.length;
        laneEnd.push(end);
      } else {
        // Out of lanes: reuse the one that frees up soonest. The marker line
        // itself still shows the exact position unambiguously.
        let best = 0;
        for (let l = 1; l < laneEnd.length; l++) if (laneEnd[l] < laneEnd[best]) best = l;
        lane[i] = best;
        laneEnd[best] = end;
      }
    }
  }
  return lane;
}

export interface OverlayState {
  annotations: Annotation[];
  thresholds: Threshold[];
  palette: Palette;
  /** Draw the text labels, not just the marker lines. Off for mini plots. */
  showLabels: boolean;
}

/**
 * Draws threshold lines (horizontal, dashed) and event annotations (vertical,
 * dashed with a boxed label) over the plotted series.
 *
 * Everything here works in device pixels: uPlot does not scale its 2D context,
 * so `u.bbox` and `valToPos(..., true)` are already device-space and fonts have
 * to be multiplied by the pixel ratio by hand.
 */
export function overlayPlugin(get: () => OverlayState): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const { annotations, thresholds, palette, showLabels } = get();
        if (annotations.length === 0 && thresholds.length === 0) return;

        const ctx = u.ctx;
        const { left, top, width, height } = u.bbox;
        const r = (u as unknown as { pxRatio?: number }).pxRatio ?? window.devicePixelRatio ?? 1;

        const laneH = LANE_H * r;
        const pad = PAD * r;

        ctx.save();
        ctx.beginPath();
        ctx.rect(left, top, width, height);
        ctx.clip();

        // uPlot leaves textAlign/textBaseline set from its own axis rendering,
        // so both must be re-declared or labels land at the wrong anchor.
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.font = `${LABEL_PX * r}px ${LABEL_FAMILY}`;
        ctx.lineWidth = 1 * r;

        const box = (x: number, y: number, w: number, stroke: string | null) => {
          ctx.fillStyle = palette.bg;
          ctx.fillRect(x - pad, y, w + pad * 2, laneH);
          if (stroke) {
            ctx.strokeStyle = stroke;
            ctx.strokeRect(x - pad, y, w + pad * 2, laneH);
          }
        };

        // --- thresholds: dashed horizontal line, label pinned to the left edge
        for (const th of thresholds) {
          const py = u.valToPos(th.y, 'y', true);
          if (!Number.isFinite(py) || py < top || py > top + height) continue;
          const color = th.color ?? palette.threshold;

          ctx.setLineDash([6 * r, 4 * r]);
          ctx.strokeStyle = color;
          ctx.beginPath();
          ctx.moveTo(left, py);
          ctx.lineTo(left + width, py);
          ctx.stroke();
          ctx.setLineDash([]);

          if (!showLabels || !th.label) continue;
          const w = ctx.measureText(th.label).width;
          const bx = left + pad * 2;
          // Sit the label above its line, or below it when there is no room.
          const by = py - laneH - 2 * r >= top ? py - laneH - 2 * r : py + 2 * r;
          box(bx, by, w, null);
          ctx.fillStyle = color;
          ctx.fillText(th.label, bx, by + 3 * r);
        }

        // --- annotations: dashed vertical line, boxed label lane-packed at top
        const visible = annotations
          .map((a) => ({ a, px: u.valToPos(a.x, 'x', true) }))
          .filter((m) => Number.isFinite(m.px) && m.px >= left && m.px <= left + width);

        if (visible.length > 0) {
          for (const m of visible) {
            ctx.setLineDash([5 * r, 3 * r]);
            ctx.strokeStyle = m.a.color ?? palette.annotation;
            ctx.beginPath();
            ctx.moveTo(m.px, top);
            ctx.lineTo(m.px, top + height);
            ctx.stroke();
          }
          ctx.setLineDash([]);

          if (showLabels) {
            const widths = visible.map((m) => (m.a.label ? ctx.measureText(m.a.label).width : 0));
            const lanes = assignLanes(
              visible.map((m) => m.px),
              widths,
              pad * 4,
            );

            visible.forEach((m, i) => {
              if (!m.a.label) return;
              const color = m.a.color ?? palette.annotation;
              const w = widths[i];
              // Flip the label to the left of its line when it would overrun.
              const flip = m.px + w + pad * 3 > left + width;
              const bx = flip ? m.px - w - pad * 2 : m.px + pad * 2;
              const by = top + pad + lanes[i] * (laneH + 2 * r);
              box(bx, by, w, color);
              ctx.fillStyle = color;
              ctx.fillText(m.a.label, bx, by + 3 * r);
            });
          }
        }

        ctx.restore();
      },
    },
  };
}
