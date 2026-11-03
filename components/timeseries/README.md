# timeseries — 可复用 React 时序曲线组件

用峰岹（Fortior）电机测试台架的实测示波器记录驱动的一组时序曲线组件。组件本体位于
`src/features/timeseries/`，只依赖 `react` 与图表库 `uplot`，不引入 UI 框架、不引入状态管理库，
可以整目录复制进宿主工程。

---

## 一、图表库选型：uPlot

选定 **uPlot 1.6.32**（作者 Leon Sorokin，仓库 <https://github.com/leeoniya/uPlot>，npm 包名 `uplot`）。

| 维度 | uPlot 1.6.32 | ECharts 6.1.0（备选） |
| --- | --- | --- |
| 打包体积 | 约 47 KB 未压缩、约 17 KB gzip | 完整包约 1 MB 级，按需裁剪后仍数百 KB |
| 百万点折线 | 官方基准以此为设计目标，Canvas 直绘、无虚拟 DOM 中间层 | 需开启 `large`/`sampling` 才能接近，默认路径明显更慢 |
| API 形态 | 极薄，直接暴露 2D 上下文与 `hooks`，自定义标注与阈值线容易 | 声明式配置完备，自定义绘制需走 `graphic`/自定义系列 |
| 维护活跃度 | 最近一次发版 2025-03-14（`npm view uplot time.modified` 实测） | 最近一次发版 2026-05-19（`npm view echarts time.modified` 实测） |

**选它的理由**：本组件的核心诉求是"百万点级示波器波形流畅缩放 + 自定义标注"，uPlot 在体积和大数据
渲染上优势明显，`hooks.draw` 直接给出 Canvas 上下文，阈值横线与事件竖线用几十行就能画完，不必和
声明式配置系统搏斗。

**须如实说明的代价**：uPlot 距上一次发版已约一年半，活跃度明显低于 ECharts。这对本项目可接受——
它是一个 API 稳定、功能收敛的成熟库，不是停更的废弃库；但如果后续需要饼图、地图、复杂交互图元，
或者要求依赖持续跟进的安全审计，应改选 ECharts。图表库在本工程中被隔离在
`src/features/timeseries/TimeSeriesChart.tsx` 一个文件内，替换成本可控。

---

## 二、接口

### `<TimeSeriesChart>`

```tsx
import { TimeSeriesChart } from './features/timeseries';

<TimeSeriesChart
  series={[{ name: 'CH1', unit: 'V', x: timeArray, y: valueArray, status: 'pass' }]}
  annotations={[{ x: 0.412, label: '412 ms 起动完成' }]}
  thresholds={[{ y: 0.3, label: '合格包络 +0.30 V' }]}
  height={360}
/>
```

| 属性 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `series` | `Series[]` | 必填 | 多通道数据。`x`/`y` 接受 `number[]` 或 `Float64Array` |
| `cursor` | `boolean` | `true` | 游标与逐通道同步读数 |
| `zoom` | `boolean` | `true` | 横向框选缩放，双击复位 |
| `legend` | `boolean` | `true` | 图例，点击条目可显隐单通道 |
| `annotations` | `Annotation[]` | `[]` | 事件竖线，`{ x, label, color? }` |
| `thresholds` | `Threshold[]` | `[]` | 阈值横线，`{ y, label, color? }` |
| `showOverlayLabels` | `boolean` | `true` | 是否绘制标注与阈值的文字标签（迷你图应关掉） |
| `height` | `number` | `320` | 组件总高度（px），含图例与读数行 |
| `xLabel` | `string` | `'时间 (s)'` | x 轴标题 |

`Series` 的 `status` 取 `'pass'` 用主色、`'fail'` 用强调色；显式给 `color` 则覆盖两者。

### `<WaveformCard>`

面板用紧凑卡片：标题 + 合格/不合格徽标 + 迷你图 + 三个关键指标，整卡可点。

```tsx
<WaveformCard
  title="TRY-0010 起动记录"
  subtitle="故障用例 CF-L-0003"
  series={series}
  verdict="fail"
  thresholds={thresholds}
  metrics={[{ label: '首次响应时刻', value: 2835, unit: 'ms', alert: true }]}
  onExpand={() => openFullView()}
/>
```

迷你图内部固定关闭图例、游标、缩放与标注文字，只保留标注和阈值的线，避免小尺寸下文字互相压盖。
`metrics` 超过三项只取前三项。

### `loadCsv(url, options)`

```ts
const r = await loadCsv('data/fullrun_v2b_decimated.csv');
// r.series / r.time / r.sampleRate / r.rawPoints / r.plottedPoints / r.decimated / r.timings
```

行为：

1. 剥离 UTF-8 BOM（示波器导出工具会写 BOM）。
2. 抽样探测各列，丢弃无法解析为数字的列（如 `sample_source` 文本列、全空的 `raw_byte` 列），
   丢弃结果放在返回值的 `droppedColumns` 里，不静默吞掉。
3. 由时间列一阶差分的中位数推算采样率。
4. 单通道样本数达到 `decimateThreshold`（默认 500,000）时，把数据转移进 Web Worker 做 min/max
   抽稀到 `decimateTarget`（默认 4000）点；Worker 不可用时回退为全量渲染而不是直接报错。
5. 列名尾缀自动推断单位，`ch2_fg1_V` → 名称 `ch2 fg1`、单位 `V`。

用 min/max 抽稀而不是等距抽样，是因为等距抽样会丢掉换相尖峰与 PWM 边沿——而这些正是判异常要看的东西。
min/max 在每个桶内同时保留极小值与极大值，绘出的包络仍然触到原始数据的每一个极值。

### 样式

全部颜色走 CSS 变量，宿主工程在任意祖先元素上覆盖即可换肤：

```css
--color-primary: #2E5E45;   /* 主色，合格 */
--color-accent:  #A6353A;   /* 强调，不合格 */
--color-text:    #2C2C2C;
--color-tint:    #EAF2EC;   /* 浅底 */
--color-bg:      #ffffff;
```

多通道配色只用两个色相（墨绿系 + 强调暗红）加一个中性色，顺序为
`--ts-ch-1` 至 `--ts-ch-5`，依次是主色墨绿、中绿 `#6B9E82`、近黑 `#2C2C2C`、强调暗红、浅沙绿
`#A8C5B5`。浅沙绿排最后，因为它在 1.4 px 线宽下最弱。

---

## 三、演示数据来源

三份数据全部取自峰岹电机测试台架实测记录。台架信号定义：FG1 为电机换相反馈（电气转速）、
FG2 为红外传感器照反光纸得到的机械真实转速、PWM1 为驱动板输出至被测电机的驱动信号。

| 页面文件 | 原始路径 | 处理方式 |
| --- | --- | --- |
| `public/data/faithful_norm1200.csv` | `测试数据_20260701/faithful_norm1200.csv` | 原样复制，1200 点 |
| `public/data/attempt_TRY-0009_PASS.csv` | `[源] capture/CH1_上电时刻归一化.csv` | 原样复制；标签取自同目录 `operator_label.json`，`operator_result` 为 `PASS` |
| `public/data/attempt_TRY-0010_FAIL.csv` | 同上，`attempts/TRY-0010/capture/CH1_上电时刻归一化.csv` | 原样复制；`operator_result` 为 `FAIL`，`case_id` 为 `CF-L-0003` |
| `public/data/fullrun_v2b_decimated.csv` | `测试数据_20260627/fullrun_v2b_20260627.csv`（101 MB，**未复制入库**） | 由 `scripts/decimate_fullrun.py` 离线 min/max 抽稀，3,000,000 → 4,000 点，152 KB |

两份 attempt 记录各 24,000 点 @ 2000 Sa/s，t = 0 为操作员点击"即将上电"按钮的时刻，上电前 6 秒为
采集工具合成的零值填充（CSV 中 `sample_source` 列标为 `SYNTHETIC_PRE_POWER`），该列因非数值已被
`loadCsv` 丢弃。

重跑离线抽稀：

```bash
python3 scripts/decimate_fullrun.py
```

### 关于 `faithful_norm1200.csv` 的一点如实说明

这份文件几乎是一条直流线：四个通道各自只有 3 个不同取值，1200 行里只有开头两行偏离常数，
t = −11.96 s 之后全部恒定。页面照实呈现，并用它验证组件不会凭空造出并不存在的波动。

---

## 四、性能

| 环节 | 输入点数 | 输出点数 | 压缩比 | 耗时 |
| --- | --- | --- | --- | --- |
| 离线 Python min/max 抽稀 | 3,000,000 | 4,000 | 750× | 9 ms（另读盘 0.93 s，pandas 读 101 MB） |
| 浏览器解析 CSV（抽稀后全程记录） | 4,000 | 4,000 | 1× | 约 5 ms |
| Web Worker min/max 抽稀 | 4,000 | 800 | 5× | 0.40 ms |

Worker 一行的数据来自演示页把触发门限临时下调到 1000 点后的实测，目的是在浏览器里真实跑通该代码
路径。随库交付的默认门限仍为 500,000 点、抽稀目标 4000 点；由于随页面交付的全程记录已在离线环节
压到 4000 点，正常加载不会触发默认门限。

**没有实测的一项**：浏览器端对 300 万点原始 CSV 的解析与 Worker 抽稀耗时未测——101 MB 文件按要求
未复制进 `public/`，页面拿不到它。如需该数字，把原始文件放进 `public/data/` 后以默认门限加载即可。

---

## 五、集成到 `c/`

1. 整目录复制：
   ```bash
   cp -r [源] features/timeseries [源] src/features
   ```
2. 装依赖（宿主工程已有 react）：
   ```bash
   cd c/ && npm i uplot
   ```
3. 引入：
   ```tsx
   import { TimeSeriesChart, WaveformCard, loadCsv } from '@/features/timeseries';
   ```
   组件自带 `timeseries.css`，由 `TimeSeriesChart.tsx` 自行 `import`，无需在宿主入口额外引样式。
   uPlot 官方样式 `uplot/dist/uPlot.min.css` 同样已在组件内引入。
4. 覆盖 CSS 变量对齐宿主主题（见上文"样式"一节）；不覆盖则使用内置的峰岹配色。
5. Worker 走 `new Worker(new URL('./decimate.worker.ts', import.meta.url), { type: 'module' })`，
   Vite 与 Webpack 5 均可直接识别并单独产出 chunk；若宿主用其他打包器，需确认其支持该写法。

演示页 `src/App.tsx`、`src/demo/` 与 `public/data/` 仅供本工程演示，集成时不必带走。
其中 `src/demo/analysis.ts` 里的起动指标计算绑定了"t = 0 即上电时刻"这一台架语义，
因此刻意放在组件库之外。

---

## 六、本地运行

```bash
cd c/components/timeseries
npm install
npm run dev     # 开发服务器
npm run build   # 生产构建，输出到 dist/
```

截图（Playwright + 本地 Chrome，1600×900）：

```bash
python3 scripts/shoot.py   # 输出到 shots/
```
