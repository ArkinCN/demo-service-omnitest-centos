/** One plotted channel. `x` and `y` must be the same length. */
export interface Series {
  /** Channel label shown in the legend and cursor readout. */
  name: string;
  /** Physical unit, e.g. "V" or "A". Shown after every readout value. */
  unit: string;
  x: number[] | Float64Array;
  y: number[] | Float64Array;
  /**
   * Verdict colouring. `pass` paints the channel in the primary colour,
   * `fail` in the accent colour. Omit to use the neutral channel palette.
   */
  status?: 'pass' | 'fail';
  /** Explicit CSS colour. Overrides both `status` and the palette. */
  color?: string;
}

/** A vertical event marker, e.g. "412 ms 起动完成". */
export interface Annotation {
  x: number;
  label: string;
  color?: string;
}

/** A horizontal limit line, e.g. an over-current trip level. */
export interface Threshold {
  y: number;
  label: string;
  color?: string;
}

export interface TimeSeriesChartProps {
  series: Series[];
  /** Show the synchronised cursor and per-channel readout. Default true. */
  cursor?: boolean;
  /** Enable drag-to-zoom on the time axis; double-click resets. Default true. */
  zoom?: boolean;
  /** Show the channel legend. Default true. */
  legend?: boolean;
  annotations?: Annotation[];
  thresholds?: Threshold[];
  /**
   * Draw the text labels for annotations and thresholds. Turn off for mini
   * plots, where only the marker lines fit. Default true.
   */
  showOverlayLabels?: boolean;
  /** Total component height in px, plot area included. Default 320. */
  height?: number;
  /** Axis label for the x scale. Default "时间 (s)". */
  xLabel?: string;
  className?: string;
}
