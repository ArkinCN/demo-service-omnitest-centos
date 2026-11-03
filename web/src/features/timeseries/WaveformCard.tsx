import { useT } from '../../i18n'
import { TimeSeriesChart } from './TimeSeriesChart';
import './timeseries.css';
import type { Annotation, Series, Threshold } from './types';

export interface WaveformMetric {
  label: string;
  value: string | number;
  unit?: string;
  /** Paints the value in the accent colour, for an out-of-limit reading. */
  alert?: boolean;
}

export interface WaveformCardProps {
  title: string;
  subtitle?: string;
  series: Series[];
  /** Up to three headline numbers shown beneath the mini plot. */
  metrics?: WaveformMetric[];
  verdict?: 'pass' | 'fail';
  verdictLabel?: string;
  annotations?: Annotation[];
  thresholds?: Threshold[];
  /** Mini plot height in px. Default 120. */
  height?: number;
  /** Called when the card is clicked; wire it to open the full-size view. */
  onExpand?: () => void;
}

/**
 * Compact dashboard tile: title, a stripped-down mini plot, and three headline
 * metrics. The mini plot drops the legend, cursor and zoom affordances so the
 * card stays readable at panel size; click the card to open the full chart.
 */
export function WaveformCard({
  title,
  subtitle,
  series,
  metrics = [],
  verdict,
  verdictLabel,
  annotations,
  thresholds,
  height = 120,
  onExpand,
}: WaveformCardProps) {
  const uiT = useT()

  const clickable = typeof onExpand === 'function';
  const shown = metrics.slice(0, 3);

  return (
    <div
      className={['ts-root', 'ts-card', clickable ? 'ts-card--clickable' : ''].filter(Boolean).join(' ')}
      onClick={onExpand}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onExpand?.();
              }
            }
          : undefined
      }
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <div className="ts-card-head">
        <div>
          <h3 className="ts-card-title">{title}</h3>
          {subtitle && <p className="ts-card-sub">{subtitle}</p>}
        </div>
        {verdict && (
          <span className={`ts-card-verdict ts-card-verdict--${verdict}`}>
            {verdictLabel ?? (verdict === 'pass' ? uiT('合格') : uiT('不合格'))}
          </span>
        )}
      </div>

      <TimeSeriesChart
        series={series}
        height={height}
        cursor={false}
        zoom={false}
        legend={false}
        annotations={annotations}
        thresholds={thresholds}
        showOverlayLabels={false}
        xLabel=""
      />

      {shown.length > 0 && (
        <div className="ts-card-metrics">
          {shown.map((m) => (
            <div className="ts-card-metric" key={m.label}>
              <div className="ts-card-metric-label" title={uiT(m.label)}>
                {uiT(m.label)}
              </div>
              <div
                className="ts-card-metric-value"
                style={m.alert ? { color: 'var(--color-accent)' } : undefined}
              >
                {m.value}
                {m.unit && <span className="ts-card-metric-unit">{m.unit}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default WaveformCard;
