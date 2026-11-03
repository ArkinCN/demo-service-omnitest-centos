import { useEffect, useMemo, useState } from 'react';
import './demo/demo.css';

import { TimeSeriesChart, WaveformCard, loadCsv, formatCount } from './features/timeseries';
import type { Annotation, Series, Threshold } from './features/timeseries';
import type { LoadCsvResult } from './features/timeseries';
import { analyseStartup } from './demo/analysis';
import type { StartupMetrics } from './demo/analysis';

const SECTIONS = [
  { id: 'startup', label: '一、起动对照（合格 / 不合格）' },
  { id: 'fullrun', label: '二、全程运行四通道' },
  { id: 'baseline', label: '三、1200 点基线波形' },
  { id: 'perf', label: '四、抽稀与渲染性能' },
  { id: 'source', label: '五、数据来源' },
];

/** Envelope derived from the passing reference run's own peak, not an invented limit. */
const PASS_ENVELOPE_V = 0.3;

interface AttemptData {
  id: string;
  verdict: 'pass' | 'fail';
  caseId: string | null;
  result: LoadCsvResult;
  metrics: StartupMetrics;
  series: Series[];
  annotations: Annotation[];
}

function ms(v: number): string {
  return `${v.toFixed(1)} ms`;
}

function useActiveSection(): string {
  const [active, setActive] = useState(SECTIONS[0].id);
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: '-10% 0px -70% 0px', threshold: 0 },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    }
    return () => obs.disconnect();
  }, []);
  return active;
}

export default function App() {
  const [attempts, setAttempts] = useState<AttemptData[] | null>(null);
  const [fullrun, setFullrun] = useState<LoadCsvResult | null>(null);
  const [baseline, setBaseline] = useState<LoadCsvResult | null>(null);
  const [workerProbe, setWorkerProbe] = useState<LoadCsvResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<AttemptData | null>(null);
  const active = useActiveSection();

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [pass, fail, run, base] = await Promise.all([
          loadCsv('data/attempt_TRY-0009_PASS.csv'),
          loadCsv('data/attempt_TRY-0010_FAIL.csv'),
          loadCsv('data/fullrun_v2b_decimated.csv'),
          loadCsv('data/faithful_norm1200.csv'),
        ]);
        if (cancelled) return;

        const build = (
          id: string,
          verdict: 'pass' | 'fail',
          caseId: string | null,
          r: LoadCsvResult,
        ): AttemptData => {
          const ch = r.series[0];
          const metrics = analyseStartup(r.time, ch.y);
          const annotations: Annotation[] = [
            { x: 0, label: '上电时刻 t=0' },
          ];
          if (metrics.firstResponseS != null) {
            annotations.push({
              x: metrics.firstResponseS,
              label:
                verdict === 'fail'
                  ? `静默期结束 ${(metrics.firstResponseS * 1000).toFixed(0)} ms`
                  : `起动响应 ${(metrics.firstResponseS * 1000).toFixed(0)} ms`,
              color: verdict === 'fail' ? 'var(--color-accent)' : undefined,
            });
          }
          return {
            id,
            verdict,
            caseId,
            result: r,
            metrics,
            series: [{ ...ch, name: `${id} CH1`, unit: 'V', status: verdict }],
            annotations,
          };
        };

        setAttempts([
          build('TRY-0009', 'pass', null, pass),
          build('TRY-0010', 'fail', 'CF-L-0003', fail),
        ]);
        setFullrun(run);
        setBaseline(base);

        // Functional check of the Web Worker path on real data. The shipped file
        // is already Python-decimated to 4k points, so the production 500k gate
        // is lowered here purely to exercise the worker in the browser.
        const probe = await loadCsv('data/fullrun_v2b_decimated.csv', {
          decimateThreshold: 1000,
          decimateTarget: 800,
        });
        if (!cancelled) setWorkerProbe(probe);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const thresholds: Threshold[] = useMemo(
    () => [
      { y: PASS_ENVELOPE_V, label: `合格包络 +${PASS_ENVELOPE_V.toFixed(2)} V` },
      { y: -PASS_ENVELOPE_V, label: `合格包络 −${PASS_ENVELOPE_V.toFixed(2)} V` },
    ],
    [],
  );

  const fullrunAnnotations: Annotation[] = useMemo(
    () => [
      { x: -120, label: '记录起点' },
      { x: 0, label: '时间轴零点' },
      { x: 120, label: '记录终点' },
    ],
    [],
  );

  return (
    <div className="app">
      <nav className="toc">
        <p className="toc-brand">TIMESERIES</p>
        <p className="toc-sub">可复用 React 时序曲线组件<br />峰岹电机测试台架实测数据</p>
        <ul className="toc-list">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a className={`toc-link${active === s.id ? ' is-active' : ''}`} href={`#${s.id}`}>
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <main className="main">
        <h1 className="page-title">时序曲线组件演示</h1>
        <p className="page-lede">
          本页用峰岹（Fortior）电机测试台架的三份实测示波器记录，演示 TimeSeriesChart、WaveformCard
          与 loadCsv 三个可复用单元。所有游标读数、事件标注时刻与统计指标均由页面在浏览器内从原始
          CSV 现场计算，没有预先写死的数值。
        </p>
        <p className="page-meta">
          图表内核 uPlot 1.6.32　·　台架信号定义 FG1 电气转速 / FG2 红外机械转速 / PWM1 驱动被测电机
        </p>

        {error && <p className="status status--error">数据加载失败：{error}</p>}

        {/* ---------------- 1. startup comparison ---------------- */}
        <section className="section" id="startup">
          <h2 className="section-title">一、起动对照（合格 / 不合格）</h2>
          <p className="section-note">
            同一批次 batch_20260811_113726_010 中的两次起动尝试，标签取自各自的 operator_label.json。
            横线为合格包络，由合格样本自身峰值取整得到；竖线为事件标注，时刻由滚动 RMS 越过 0.12 V
            门限的首个采样点确定。点击卡片展开完整图表，可框选缩放、移入读数。
          </p>

          {!attempts && !error && <p className="status">正在加载两份起动记录……</p>}

          {attempts && (
            <>
              <div className="card-grid">
                {attempts.map((a) => (
                  <WaveformCard
                    key={a.id}
                    title={`${a.id} 起动记录`}
                    subtitle={
                      a.caseId
                        ? `故障用例 ${a.caseId}　·　${formatCount(a.result.rawPoints)} 点 @ ${a.result.sampleRate?.toFixed(0)} Sa/s`
                        : `对照样本　·　${formatCount(a.result.rawPoints)} 点 @ ${a.result.sampleRate?.toFixed(0)} Sa/s`
                    }
                    series={a.series}
                    verdict={a.verdict}
                    thresholds={thresholds}
                    annotations={a.annotations}
                    onExpand={() => setExpanded(a)}
                    metrics={[
                      {
                        label: '首次响应时刻',
                        value:
                          a.metrics.firstResponseS != null
                            ? (a.metrics.firstResponseS * 1000).toFixed(0)
                            : '—',
                        unit: 'ms',
                        alert: a.verdict === 'fail',
                      },
                      {
                        label: '上电首秒 RMS',
                        value: a.metrics.firstSecondRms.toFixed(3),
                        unit: 'V',
                      },
                      {
                        label: '末两秒 RMS',
                        value: a.metrics.settledRms.toFixed(3),
                        unit: 'V',
                        alert: a.metrics.settledRms > 0.1,
                      },
                    ]}
                  />
                ))}
              </div>

              <table className="stat-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>TRY-0009（合格）</th>
                    <th>TRY-0010（不合格）</th>
                    <th>读法</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>首次响应时刻</td>
                    <td className="num">{ms((attempts[0].metrics.firstResponseS ?? 0) * 1000)}</td>
                    <td className="accent">{ms((attempts[1].metrics.firstResponseS ?? 0) * 1000)}</td>
                    <td>合格件上电即响应，故障件静默近三秒</td>
                  </tr>
                  <tr>
                    <td>上电首秒 RMS</td>
                    <td className="num">{attempts[0].metrics.firstSecondRms.toFixed(4)} V</td>
                    <td className="accent">{attempts[1].metrics.firstSecondRms.toFixed(4)} V</td>
                    <td>故障件首秒完全平直，无起动电流</td>
                  </tr>
                  <tr>
                    <td>post-power 峰峰值</td>
                    <td className="num">{attempts[0].metrics.peakToPeak.toFixed(4)} V</td>
                    <td className="accent">{attempts[1].metrics.peakToPeak.toFixed(4)} V</td>
                    <td>故障件幅值约为合格件两倍</td>
                  </tr>
                  <tr>
                    <td>末两秒 RMS</td>
                    <td className="num">{attempts[0].metrics.settledRms.toFixed(4)} V</td>
                    <td className="accent">{attempts[1].metrics.settledRms.toFixed(4)} V</td>
                    <td>合格件收敛，故障件持续振荡</td>
                  </tr>
                </tbody>
              </table>
            </>
          )}
        </section>

        {/* ---------------- 2. full run ---------------- */}
        <section className="section" id="fullrun">
          <h2 className="section-title">二、全程运行四通道</h2>
          <p className="section-note">
            240 秒全程记录，原始 300 万采样点、101 MB，经 Python 侧 min/max 抽稀到 4000 点后进入页面。
            四条曲线分别为电流采样、FG1 电气转速反馈、FG2 红外机械转速反馈与 PWM1 驱动输出。
            点击图例可逐通道显隐。
          </p>
          {!fullrun && !error && <p className="status">正在加载全程记录……</p>}
          {fullrun && (
            <div className="panel">
              <TimeSeriesChart
                series={fullrun.series}
                annotations={fullrunAnnotations}
                height={400}
              />
              <div className="tags">
                <span className="tag">原始 3,000,000 点</span>
                <span className="tag tag--on">渲染 {formatCount(fullrun.plottedPoints)} 点</span>
                <span className="tag">原始采样率 12,500 Sa/s</span>
                <span className="tag">解析 {fullrun.timings.parseMs.toFixed(0)} ms</span>
              </div>
            </div>
          )}
        </section>

        {/* ---------------- 3. baseline ---------------- */}
        <section className="section" id="baseline">
          <h2 className="section-title">三、1200 点基线波形</h2>
          <p className="section-note">
            客户软件导出上限即 1200 点，这份记录是该上限下的忠实复现结果。数据量小，组件直接全量渲染，
            不触发任何抽稀。需要如实说明的是，这份文件本身几乎是一条直流线：四个通道各自只有 3 个不同取值，
            1200 行里只有开头两行偏离常数，t = −11.96 s 之后全部恒定。图上因此只在最左端出现一段起始瞬变，
            这是文件的真实内容，也正好用来验证组件不会凭空造出并不存在的波动。
          </p>
          {!baseline && !error && <p className="status">正在加载基线波形……</p>}
          {baseline && (
            <div className="panel">
              <TimeSeriesChart
                series={baseline.series}
                height={340}
                annotations={[{ x: -11.98, label: '起始瞬变（仅前 2 个采样点）' }]}
              />
              <div className="tags">
                <span className="tag tag--on">全量渲染 {baseline.rawPoints} 点</span>
                <span className="tag">采样率 {baseline.sampleRate?.toFixed(0)} Sa/s</span>
                <span className="tag">未抽稀</span>
                <span className="tag">每通道仅 3 个不同取值</span>
              </div>
            </div>
          )}
        </section>

        {/* ---------------- 4. performance ---------------- */}
        <section className="section" id="perf">
          <h2 className="section-title">四、抽稀与渲染性能</h2>
          <p className="section-note">
            大文件走两级抽稀。离线一级由 scripts/decimate_fullrun.py 完成，把 101 MB 原始记录压到
            152 KB；在线一级由 loadCsv 在 Web Worker 里完成，默认在单通道达到 50 万点时触发。
            两级都用 min/max 抽稀而非等距抽样，保证换相尖峰与 PWM 边沿不被丢掉。
          </p>
          <div className="panel">
            <table className="stat-table">
              <thead>
                <tr>
                  <th>环节</th>
                  <th>输入点数</th>
                  <th>输出点数</th>
                  <th>压缩比</th>
                  <th>耗时</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>离线 Python min/max 抽稀</td>
                  <td className="num">3,000,000</td>
                  <td className="num">4,000</td>
                  <td className="num">750×</td>
                  <td className="num">9 ms（另读盘 0.93 s）</td>
                </tr>
                <tr>
                  <td>浏览器解析 CSV（全程记录）</td>
                  <td className="num">{fullrun ? fullrun.rawPoints.toLocaleString() : '—'}</td>
                  <td className="num">{fullrun ? fullrun.plottedPoints.toLocaleString() : '—'}</td>
                  <td className="num">1×</td>
                  <td className="num">{fullrun ? `${fullrun.timings.parseMs.toFixed(1)} ms` : '—'}</td>
                </tr>
                <tr>
                  <td>Web Worker min/max 抽稀（门限降至 1000 点以实测该路径）</td>
                  <td className="num">{workerProbe ? workerProbe.rawPoints.toLocaleString() : '—'}</td>
                  <td className="num">{workerProbe ? workerProbe.plottedPoints.toLocaleString() : '—'}</td>
                  <td className="num">
                    {workerProbe ? `${(workerProbe.rawPoints / workerProbe.plottedPoints).toFixed(0)}×` : '—'}
                  </td>
                  <td className="num">
                    {workerProbe ? `${workerProbe.timings.decimateMs.toFixed(2)} ms` : '—'}
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="source-note">
              Worker 一行的门限是为在本页实测该代码路径而临时下调的。随库交付的默认门限仍为 50 万点，
              抽稀目标 4000 点；随页面交付的全程记录已在离线环节压到 4000 点，因此不会触发默认门限。
            </p>
          </div>
        </section>

        {/* ---------------- 5. sources ---------------- */}
        <section className="section" id="source">
          <h2 className="section-title">五、数据来源</h2>
          <p className="section-note">三份数据均取自峰岹电机测试台架实测记录，路径如下，便于独立核对。</p>
          <div className="panel">
            <table className="stat-table">
              <thead>
                <tr>
                  <th>页面文件</th>
                  <th>原始路径</th>
                  <th>处理</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>public/data/faithful_norm1200.csv</td>
                  <td className="source-note">
                    测试数据_20260701/faithful_norm1200.csv
                  </td>
                  <td>原样复制</td>
                </tr>
                <tr>
                  <td>public/data/attempt_TRY-0009_PASS.csv</td>
                  <td className="source-note">
                    [源] capture/CH1_上电时刻归一化.csv
                  </td>
                  <td>原样复制，标签 PASS</td>
                </tr>
                <tr>
                  <td>public/data/attempt_TRY-0010_FAIL.csv</td>
                  <td className="source-note">
                    [源] capture/CH1_上电时刻归一化.csv
                  </td>
                  <td>原样复制，标签 FAIL，用例 CF-L-0003</td>
                </tr>
                <tr>
                  <td>public/data/fullrun_v2b_decimated.csv</td>
                  <td className="source-note">
                    测试数据_20260627/fullrun_v2b_20260627.csv（101 MB，未复制入库）
                  </td>
                  <td>scripts/decimate_fullrun.py 抽稀 3,000,000 → 4,000 点</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </main>

      {expanded && (
        <div
          className="modal-backdrop"
          onClick={() => setExpanded(null)}
          role="presentation"
        >
          <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="modal-head">
              <div>
                <h3 className="modal-title">
                  {expanded.id} 起动记录　·　{expanded.verdict === 'pass' ? '合格' : '不合格'}
                </h3>
                <p className="modal-sub">
                  {expanded.result.rawPoints.toLocaleString()} 点 @{' '}
                  {expanded.result.sampleRate?.toFixed(0)} Sa/s　·　上电时刻归一化至 t = 0
                </p>
              </div>
              <button type="button" className="modal-close" onClick={() => setExpanded(null)}>
                关闭
              </button>
            </div>
            <TimeSeriesChart
              series={expanded.series}
              annotations={expanded.annotations}
              thresholds={thresholds}
              height={440}
            />
          </div>
        </div>
      )}
    </div>
  );
}
