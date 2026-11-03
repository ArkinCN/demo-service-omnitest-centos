# OmniTest · 多场景 Agent 测试系统（前端壳与设计系统）

产品名 `OmniTest` 为占位，待拍板。智能体统一叫「测试助手」，界面短名「助手」，英文 `Assistant`，代码标识 `copilot`。

本仓只做**应用壳与设计系统**：A/B/C/D 四个大块的骨架、六条流程路由、UI 基础组件、场景包数据契约与扩展注册表。各流程内部的真实功能组件（时序图、工作流画布、知识库树等）由别的 agent 在 `src/features/<name>/` 下实现并注册进来，壳层不需要改动。

实现依据：`docs/20260919-通用Agent测试系统v2.0/01-设计规格-信息架构与页面.md`（下称《设计规格》）。业务逻辑见同目录 `02-业务逻辑说明-六个流程.md`，用户原始要求见 `00-用户需求原话-20260919.md`。

---

## 1. 跑起来

```bash
cd c/web
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build，必须零错误
npm run lint     # oxlint
```

技术栈：Vite 8 + React 19 + TypeScript 6 + Tailwind CSS 4（`@theme` 令牌）+ react-router 7 + zustand。

截图基准 1600×1000，采集脚本 `scripts/shoot.mjs`（playwright + 本机
`[源] chrome-linux64/chrome`，不额外下载浏览器），产物见 `shots/`：

```bash
npm run build && npm run preview -- --port 4173
node scripts/shoot.mjs                    # 默认打 http://localhost:4173
BASE=http://localhost:5173 node scripts/shoot.mjs
python3 scripts/compare.py run            # 两包并排对照图
```

v2 视觉层重做后的验收截图另有一套，基准 1920×1080，见本文第 6.2 节与 `shots2/`。

URL 上的 `?scene=<sceneId>` 直接指定开哪个场景包（截图脚本与分享链接都用它），
目录里没有这个 id 时忽略，走 `public/scenes/index.json` 的 `default`。

两个后端的起法与配置见本文第 10 节「交互与设备桥」。两个都不起也能跑，
画布设备节点显示「网关 未连通」并在 tooltip 里说明缺什么。

---

## 2. 目录结构

```
src/
├── app/                    四个大块的实现
│   ├── Shell.tsx           页面壳：A 区通栏 + 主体外边距（横 16 纵 12）
│   ├── TopBar.tsx          A 区 · 流程导航（行1 56 / 行2 44 / 行3 40）
│   ├── ProductCascader.tsx 三级级联产品选择器（场景 › 子类 › 产品类型）
│   ├── FlowScreen.tsx      B/C/D 三块的栅格（B 宽 384，右列 496 : 328）
│   ├── LeftPanel.tsx       B 区 · 输入清单 + 分组手风琴 + 确认条
│   ├── ResourcePanel.tsx   C 区 · 网格 2×2 与画布两种视图 + 放大态
│   ├── ToolRail.tsx        C 区右侧竖向工具条（四组，按钮带状态点）
│   ├── AssistantPanel.tsx  D 区 · 助手对话（四类消息 + 快捷指令 + 输入栏）
│   └── CardArt.tsx         卡片库占位图形（墨绿线条稿，被真实组件替换）
├── components/ui/          基础组件集，见第 4 节
├── data/
│   ├── types.ts            场景包数据契约（与《设计规格》同名同构）
│   ├── flows.ts            六条流程：路由、序号、动作按钮、前置条件
│   ├── cards.ts            卡片库 21 张卡的标识与卡名
│   ├── loadScene.ts        场景包加载适配层 + 产品三级目录
│   └── mock/               临时 mock 场景包（散热风扇）
├── features/               功能组件，见第 5 节与第 8 节
│   ├── index.tsx           装配点：卡片/左栏/助手的注册与按流程分派表
│   ├── scene/pack.ts       场景包原始 JSON 的类型、加载与两包差异归一化
│   ├── scene/workflows.ts  工作流统一取数口（.wfw 索引 / 包内 JSON 模型两条来源）
│   ├── scene/kb.ts         知识库流水线产物（public/kb/）的类型与取数
│   ├── waveforms/          场景包登记时序的加载与指标计算
│   ├── shared/bits.tsx     卡内复用的小件（分组条、行、标签、占比条）
│   ├── copilot/            助手：按流程回放的脚本化适配器 + 六段脚本
│   ├── flow-kb/ flow-init/ flow-req/ flow-run/ flow-tune/ flow-report/
│   │                       六条流程各自的左栏与卡片
│   ├── timeseries/ workflow/ agent-chat/ remote/
│   │                       从 c/components/ 整目录搬进来的四个组件（本体未改）
│   └── flow-run/evaluate.ts 判据求值：criterion + variables，缺实测量就标未采集
├── registry/index.tsx      扩展注册表：registerPanelCard / registerLeftPanel / registerAssistant
├── state/useAppStore.ts    zustand：当前产品、参数覆盖值、确认与锁定、全局状态
├── styles/
│   ├── tokens.css          设计令牌 + Tailwind @theme 映射
│   └── fonts.css           本地打包字体（离线可用，不依赖 CDN）
├── router.tsx              六条流程路由
└── index.css               基础层：重置、滚动条、.num / .tick / .paper-grid

public/
├── scenes/index.json                          产品三级级联目录，驱动选择器（第 7.1 节）
├── scenes/motor.cooling-fan.fortior-fu6832/   场景包一：10 份 JSON + assets
├── scenes/automotive.body-motor.window-regulator/  场景包二：同构，10 份 JSON + assets
├── kb/                                        知识库流水线产物（第 7.3 节）
└── data/                                      工作流索引 workflows.json 与 wfw/** 共 68 个 .wfw

scripts/
├── shoot.mjs               两个场景包 × 六路由 + 四张放大态的截图采集
├── compare.py              两个场景包同一流程并排拼图（PIL）
└── buildIndex.mjs          由 .wfw 目录重建 workflows.json（来自 c/components/workflow）
```

---

## 3. 设计 tokens

全部定义在 `src/styles/tokens.css`，同时以 Tailwind 4 `@theme` 暴露成工具类（`bg-ink`、`text-t2`、`border-line-soft`、`rounded-tp` 等）。

### 3.1 色板（双色相，不引入第三色相）

| 角色 | 令牌 | 色值 | 用法 |
| --- | --- | --- | --- |
| 页面底 | `--tp-bg` / `bg-page` | `#FAFAF8` | 全局背景 |
| 面板底 | `--tp-surface` / `bg-surface` | `#FFFFFF` | B/C/D 块与卡片 |
| 下沉区 | `--tp-surface-sunk` / `bg-sunk` | `#F4F3EF` | 输入框、子组标题条 |
| 主色 · 墨绿 | `--tp-ink` / `ink` | `#2E5E45` | 描边、主按钮、选中态、进行中 |
| 主色加深 | `--tp-ink-deep` | `#1F4232` | 实底按钮 hover |
| 主色弱描边 | `--tp-ink-soft` | `#A8C5B5` | 次级描边、连线 |
| 主色浅底 | `--tp-ink-wash` | `#EAF2EC` | 当前流程标签底、选中项底 |
| 强调 · 暗红 | `--tp-alert` / `alert` | `#A6353A` | 不通过、超限、联锁未满足 |
| 强调浅底 | `--tp-alert-wash` | `#F6ECEC` | 异常行底纹 |
| 正文 / 次要 / 弱 | `--tp-text` `-2` `-3` | `#2C2C2C` `#555555` `#9A9A9A` | `text-t1` `text-t2` `text-t3` |
| 分隔线 / 浅分隔线 | `--tp-line` `-soft` | `#C8C5BD` `#E6E3DC` | 块边界 / 卡内行分隔 |

面积约束按《设计规格》3.3：墨绿填充 ≤5%，浅底合计 ≤15%，暗红每屏 ≤3 处。状态语义只三档：未执行灰、进行中与通过墨绿、不通过与风险暗红；「待确认」用暗红描边加白底，不给新色相。

顶部流程标签的异常点只在**当前流程**上出现，其余流程显示「未开始」，就是为了守住暗红的处数上限。

### 3.2 字体

本地打包（`@fontsource`），离线与截图环境都不依赖网络。

| 用途 | 字体栈 | 令牌 |
| --- | --- | --- |
| 界面正文 | IBM Plex Sans + 思源黑体 Noto Sans SC | `--tp-font-sans` |
| 数值与标识符 | IBM Plex Mono（`.num` 类带 `tabular-nums`） | `--tp-font-mono` |
| 产品字标 | IBM Plex Serif | `--tp-font-display`，只用于 `OmniTest` 字样 |

等宽只给文件名、宏名、参数值、通道号、时间戳，避免整页「终端感」。

### 3.3 形状与节奏

卡片圆角 6（`rounded-tp`），按钮与输入框圆角 4（`rounded-tps`）；边框一律 1px；常态无阴影，只有弹层与放大态用 `0 8px 24px rgba(44,44,44,.12)`。按钮高 32 / 次按钮 28，输入框与步进器 32、加减号各 28 宽。

栅格：A 区通栏贴顶 140（56 + 44 + 40）；主体外边距横 16 纵 12，块间距同值；B 区固定 384 宽；右列 C : D = 496 : 328；C 区工具条 56 宽。

动效只留三处：块内容随流程切换的 `rise`（26ms 起、卡片按 30ms 递增错峰）、浮层 `pop`、状态点 `pulse-dot`。

---

## 4. 组件清单

`src/components/ui/`，全部手写，无第三方 UI 依赖。统一从 `src/components/ui` 导入。

| 组件 | 文件 | 说明 |
| --- | --- | --- |
| `Button` | `Button.tsx` | 五档：`primary` 墨绿描边（主动作）/ `default` 灰描边 / `danger` 暗红描边（急停、回滚）/ `ghost` / `solid` 实底（只给当前选中的单个元素） |
| `Panel` / `PanelHeader` | `Card.tsx` | B/C/D 大块容器与 32 高标题条 |
| `PanelCard` | `Card.tsx` | C 区卡片：卡头 32（卡名 + 换卡 / 刷新 / 放大三个图标按钮 + 当前使用竖条 + 时间戳），卡体定高不滚动，底部一行摘要 |
| `Tabs` | `Tabs.tsx` | 下划线式二级标签 |
| `Badge` / `SourceTag` / `StatusDot` | `Badge.tsx` | 徽标；来源标记三态（文档 / 人工 / 建议）；状态点四态（未填 / 已填 / 异常 / 不适用） |
| `Input` / `Textarea` | `Input.tsx` | 高 32 输入框 |
| `Stepper` | `Stepper.tsx` | 数值加减框：左右加减号各 28，中间可直接键入，带单位格与上下限 |
| `Select` | `Select.tsx` | 轻量下拉：点外部关闭、Esc 关闭、`listbox` 语义 |
| `Collapsible` | `Collapsible.tsx` | 手风琴分组，左栏参数分组与工具条分组共用 |
| `Modal` / `Drawer` | `Modal.tsx` | 居中放大态 / 右侧抽屉，均走 portal、Esc 关闭、`aria-modal` |
| `cn` | `cn.ts` | className 合并 |

**关于 Mantine。** 开源选型调研推荐 UI 用 Mantine 9.x，理由是知识库三级树 `Tree` 与步进器 `NumberInput` 是官方组件。当前壳层的 `Stepper` 已按《设计规格》6.2 的尺寸与交互手写完成（32 高、加减号 28、可键入、带上下限），且壳层本身不含树控件——三级分类树属于 C 区 `project-tree` 卡片的内容，由知识库那一路以 feature 形式注册进来。因此本仓不引入 Mantine，把选择权留给功能组件：

- 谁来做 `project-tree` 卡片，**建议直接用 Mantine `Tree`**，在自己的 feature 目录里 `npm i @mantine/core @mantine/hooks`，用 `MantineProvider` 包住自己的子树，主题按下表映射到本仓令牌，避免全局样式冲突：
  `primaryColor` → `#2E5E45`，`defaultRadius` → `6px`，`fontFamily` → `var(--tp-font-sans)`，`fontFamilyMonospace` → `var(--tp-font-mono)`，`white` → `#FFFFFF`，`black` → `#2C2C2C`。
- 若后续决定整仓切 Mantine，替换点只有 `components/ui/Stepper.tsx` 与 `Select.tsx` 两个文件，调用方签名保持不变即可。

图表建议 uPlot（`timeseries` 卡），画布建议 React Flow（`workflow` 卡与 C 区画布视图），均由对应 feature 自带依赖。

---

## 5. 接入约定（给其他 agent）

组件放在 `src/features/<name>/`，自带依赖与样式，通过注册表接入，**不要改 `src/app/` 下的文件**。

### 5.1 注册一张面板卡片

```tsx
// src/features/timeseries-chart/index.tsx
import { registerPanelCard } from '../../registry'
import { LiveChart } from './LiveChart'

registerPanelCard({
  id: 'timeseries',              // 必须是卡片库标识，见 src/data/cards.ts
  label: '时序曲线',
  caption: '两路转速反馈 + 母线电流',
  flows: ['run', 'tune'],        // 省略或 '*' 表示所有流程
  order: 10,                     // 越小越靠前，默认 100
  render: ({ flow, scene }) => <LiveChart mode="thumb" scene={scene} flow={flow} />,
  renderExpanded: ({ scene }) => <LiveChart mode="full" scene={scene} />,
})
```

规则：

- `id` 用卡片库里已有的标识时，**替换**该流程默认卡片的内容，卡头、摘要、状态由场景包给；用别的流程没有的卡时，追加到卡槽末尾。
- `render` 画缩略态（卡体定高不滚动，超出请自行截断），`renderExpanded` 画放大态（约 600×430），省略时复用 `render`。
- 卡片库 21 张卡的标识：`product-view` `schematic` `project-tree` `tools` `bench-live` `remote-device` `interlock` `workflow` `wf-lib` `timeseries` `progress` `pipeline` `candidates` `param-changes` `verdict` `evidence` `history` `experience` `artifacts` `report-preview` `template-fields`。卡名可在卡槽上用 `title` 覆写（同一张卡在不同场景包里指的东西不同时用，例如初始化 hero 图在散热风扇包里是原理图、在玻璃升降器包里是结构示意图）。

### 5.2 接管某条流程的左栏

```tsx
// src/features/kb-taxonomy/index.tsx
import { registerLeftPanel } from '../../registry'
import { TaxonomyPanel } from './TaxonomyPanel'

registerLeftPanel('kb', TaxonomyPanel)   // 组件收到 { flow, scene }
```

注册后该流程 B 区的输入清单与分组手风琴整块由你的组件负责，壳层仍提供标题条与底部确认条。流程标识六个：`kb` `init` `req` `run` `tune` `report`（路由分别是 `/kb` `/init` `/requirements` `/run` `/tune` `/report`）。

### 5.3 装配

在 `src/features/index.ts` 里加一行 import：

```ts
import './timeseries-chart'
import './kb-taxonomy'
```

注册表用 `useSyncExternalStore` 广播，运行期注册也会触发壳层重渲染。

### 5.4 读数据与写状态

- 场景包：`useAppStore(s => s.scene)`，结构见 `src/data/types.ts`。
- 参数值：`useAppStore(s => s.overrides[key])`，`key` 用 `paramKey(flow, groupId, subId, itemId)`；写用 `setParam`，写过之后来源标记自动转「人工」。
- 确认与锁定：`confirmed[flow]`、`confirmFlow`、`unconfirmFlow`。
- 助手的执行边界按《设计规格》8.3：可读、可算、可建议、可写草稿；凡是改变被测对象状态或落盘生效的动作必须人点按钮。注册的组件请遵守这条，不要提供「自动执行」入口。

### 5.5 场景包接入

场景包是一个目录下的 10 份 JSON（不是单文件），两个包都已就位，见第 7.1 节。

- `loadScene(sceneId)` → `loadPack()` 读 `public/scenes/<sceneId>/` 下的 10 份 JSON，
  经 `normalize()` 抹平两个包的字段差异，再由 `adaptScene()` 压成壳层的 `ScenePackage`。
  任何一份缺失就整体回落到内置 mock，保证任何时候都能渲染。
- 卡片要的明细不经壳层契约压扁，直接读 `src/features/scene/pack.ts` 的原始结构。
- **新增第三个场景包时要做的**：把包目录 rsync 进 `public/scenes/<sceneId>/`，
  在 `public/scenes/index.json` 的 `catalog` 里给对应的三级节点加一个 `sceneId`。
  如果它的字段与现有两个包又不同型，只改 `normalize()` 一个函数，UI 层不动。

---

## 6. 截图

截图分两套，各有各的脚本与目录，不要混：v1 的 `shots/`（1600×1000，功能验收），
v2 视觉层重做后的 `shots2/`（1920×1080 基准 + 1440×810 不破版对照，视觉验收）。

### 6.1 v1 · `shots/`

`shots/`，全部 1600×1000，由 `scripts/shoot.mjs` 采集。脚本对**两个场景包各跑一遍
六条路由**，场景由 URL 上的 `?scene=<sceneId>` 指定（`bootstrap()` 认这个参数）。

```bash
npm run build && npm run preview -- --port 4173
node scripts/shoot.mjs                    # 默认打 http://localhost:4173
BASE=http://localhost:5173 node scripts/shoot.mjs
python3 scripts/compare.py run            # 两个包同一流程并排拼一张对照图
```

| 文件 | 内容 |
| --- | --- |
| `flow-{kb,init,requirements,run,tune,report}.png` | 场景一 · 电机 › 散热风扇 › FU6832 驱动板，六条流程 |
| `auto-flow-{kb,init,requirements,run,tune,report}.png` | 场景二 · 汽车 › 车身电机 › 电动玻璃升降器，六条流程 |
| `zoom-workflow-canvas.png` | 放大态 · 工作流画布（场景一，真实 `.wfw`） |
| `zoom-timeseries.png` | 放大态 · 时序曲线（场景一，实测 CH1） |
| `zoom-evidence.png` | 放大态 · 助手依据抽屉 |
| `auto-zoom-workflow-canvas.png` | 放大态 · 工作流画布（场景二，包内 JSON 模型） |
| `compare-run.png` | 两个场景包并排对照：同一条流程（启动测试），左电机右汽车，各缩到 800 宽 |

`scripts/compare.py` 用 PIL 拼图，参数是流程路由名（默认 `run`），产物是
`shots/compare-<route>.png`。

### 6.2 v2 视觉层 · `shots2/`

视觉层按 `DESIGN.md` 重做后的交付截图。基准画布 1920×1080，另出 1440×810
一套核对不破版；放大态与两包对照各出几张。

```bash
npm run build
npx vite preview --port 4173
node scripts/shootfinal.mjs               # 六页 ×2 尺寸 + 放大态 3 张 + 汽车包 2 张
python3 scripts/compare2.py               # 电机／汽车并排对照图
ONLY=run node scripts/shootfinal.mjs      # 只重出名字里带 run 的那几张
PREFIX=wip node scripts/shootfinal.mjs    # 改到一半时出一套 wip-*.png 自查，不覆盖交付图
```

| 文件 | 内容 |
| --- | --- |
| `final-{kb,init,req,run,tune,report}.png` | 六条流程，1920×1080，场景一（电机 › 散热风扇 › FU6832 驱动板） |
| `final-{kb,init,req,run,tune,report}-1440.png` | 同上六页，1440×810，核对窄视口不破版 |
| `final-zoom-canvas.png` | 放大态 · 工作流画布（流程 3 首卡） |
| `final-zoom-timeseries.png` | 放大态 · 时序曲线（流程 4 首卡） |
| `final-zoom-evidence.png` | 放大态 · 知识库依据（流程 2 画板上双击「知识库依据」节点开浮层）。2026-09-20 改过一次取图口径：原先写的是「知识库模块页第 2 枚放大按钮」，而知识库模块页改成三栏版式后已无任何放大按钮，点击必然失败，旧图其实是一张没有浮层的知识库整页图 |
| `final-auto-run.png` / `final-auto-init.png` | 场景二（汽车 › 车身电机 › 电动玻璃升降器）的流程 4 与流程 2 |
| `final-compare-run.png` | 两包同一条流程并排，左电机右汽车，各缩到 960 宽，总宽 1920 |

`shots2/` 里另有几张 `run.png` / `kb.png` 一类无前缀的图，是视觉层铺页过程中
`scripts/shoot2.mjs` 出的中间稿，留着做前后对照，交付看 `final-*` 那一套。

`shootfinal.mjs` 与 `shootextra.mjs` 不再吞掉失败：任何一步点不到、或放大动作
之后页面上找不到浮层，都会打一条 `[warn]` 并在收尾时以退出码 1 结束，图虽然仍
落盘但脚本明说它不可信。另给一个 `OUTDIR` 环境变量换输出目录（默认 `shots2`），
自查时用它出一套到别处，不覆盖交付图。

## 7. 数据来源

### 7.1 场景包（六条流程的全部真实数据）

**两个场景包，同构不同型**。源目录
`c-data/scenes`，
各是一个目录下的 10 份 JSON 加 `assets/`，整目录复制进 `public/scenes/<sceneId>/`
（排除 `_build/`）。字段含义见各自目录自带的 `README.md`。

| sceneId | 三级分类 | 规模 | 数据性质 |
| --- | --- | --- | --- |
| `motor.cooling-fan.fortior-fu6832` | 电机 › 散热风扇 › FU6832 散热风扇驱动板 | 属性 29 / 控制参数 70 / 判据 26 / 工作流 67 / 文档 61 / 经验 24 | 客户私有材料 + 示波器实测时序 |
| `automotive.body-motor.window-regulator` | 汽车 › 车身电机 › 电动玻璃升降器（含防夹） | 属性 47 / 控制参数 59 / 判据 34 / 工作流 4 / 文档 83 / 经验 18 | 公开标准条款 + **合成时序**（已标注）+ 示例工作流 |

重新同步：

```bash
D=c-data/scenes
for s in motor.cooling-fan.fortior-fu6832 automotive.body-motor.window-regulator; do
  rsync -a --delete "$D/$s/" ./scenes/$s/ --exclude '_build/'
done
```

#### 两个包的字段差异与归一化

两个包按各自源材料建模，有几处字段名与建模方式不同。差异**一次性在加载时抹平**，
归一化函数是 `src/features/scene/pack.ts` 的 `normalize()`，UI 层只认一套字段：

| 差异 | 散热风扇包 | 玻璃升降器包 | 归一化后 |
| --- | --- | --- | --- |
| 报告模板 | Excel `.xlsm`，字段定位是单元格地址 `label_cell` / `value_cell` | PDF 报告样张，字段定位是「节 + 字段」`label_section` / `label_slot` / `value_slot` | 统一成「一个标题位 `label_slot` + 一个取值位 `value_slot`」，可选带 `label_section` |
| 转化状态 | 英文枚举 + `conversion_status_label` | 中文枚举，没有 label 字段 | 补齐 `conversion_status_label` 与布尔 `converted` |
| 经验标签 | 英文键 `scene/flow/parameters/topic` | 中文键 `场景/流程/参数/现象` | 统一成前者四个键 |
| 图纸变体 | `schematic_variants` 三套 PDF | 没有这个字段 | 由 `images` 派生，渲得出的挂 `rendered` |
| 批次统计 | `package_stats`（101 attempt / PASS 67 / FAIL 30） | 没有批次概念 | `package_stats` 可空，进度卡按登记时序条数算 |
| 性能表 / 波形图位 | Excel 模板独有 | 没有 | 两者改为可选，产物清单统一成 `artifact_groups` |
| 工作流 | 68 个真实 `.wfw`，要 `parseWfw` 解析 | `assets/workflows/*.json`，本身已是画布内部模型 | `caps.workflowSource` 两档，取数口统一在 `src/features/scene/workflows.ts` |
| 节点分组 | 峰岹客户端的 `NodeGroupId` 枚举 | 本包自定义的六类中文抽象分组 | 包声明的分组原样注册进画布分组表（`registerNodeGroups`），**分组名照包自己写的显示**，只借配色 |

#### 场景二带进来的五件前端能力

玻璃升降器包的 README 第 8.3 节列了五件事，本轮都已支持（也回头惠及场景一）：

1. `options` 非空 → 渲染下拉框而不是加减号（左栏 `kind: 'select'`，带 `optionLabels`）
2. `not_applicable: true` → 显示「不适用」，虚线描边灰字，不给控件，不显示单位
3. `evaluable: false` → 不渲染判定灯，只标「人工判」，并把 `not_evaluable_reason` 挂出来
4. `_status` 非空 → 数值旁挂「待核实」角标（弱描边中性标，**不占暗红名额**——
   「待核实」是来源没定版，不是数据异常，与 `_placeholder` 的「待确认」是两回事）
5. `synthetic: true` / `_placeholder: true` → 时序卡、判定卡、报告预览、产物清单
   都挂「合成数据，非实测」，文案取包自己的 `synthetic_banner`

#### 照数据自身口径办的事，不要「优化」掉

- 散热风扇包的波形列名 `voltage_v` 是示波器通道命名，物理量是相电流（安培）；
  `t < 0` 是人工 0 V 补线，不是实测，不得据此评噪声零漂。
- `probe_ratio_confirmed: false` → 电流绝对量级在客户给出 mV/A 系数前不对外引用。
- 玻璃升降器包的三条时序**全部是合成的**，按包自己的流程联锁 SI-PR-05，
  不得进入任何合规报告——界面上四处都标了。
- 判据要的量与手里的波形不是同一个量时（例如 `TR-CURR-01` 要母线电流、本轮
  回放的是相电流），一律判「未采集」，不拿相电流冒充母线电流。

### 7.2 工作流文件

`./data/` → `public/data/`：`workflows.json`（索引）与 `wfw/**` 共 68 个 `.wfw`
明文 UTF-8 JSON。场景包登记 67 条（58 主 + 9 子），本地多出的一个是 `SCOPETEST_时序采集_v1.wfw`，
界面上两个数都标了出处，没有对齐成同一个数。索引重建用 `node scripts/buildIndex.mjs`。

### 7.3 知识库流水线产物（`public/kb/`）

源目录 `c-data/kb`，
整目录复制进 `public/kb/`，**排除 `figures/` 大图、`content.md` 与 `source.json`**
（前端只要索引、切片与参数表，780 KB 对 20 MB）：

```bash
rsync -a --delete \
  "c-data/kb" ./kb/ \
  --exclude 'figures/' --exclude '*/figures/**' --exclude 'content.md' --exclude 'source.json'
```

| 文件 | 内容 | 用在哪 |
| --- | --- | --- |
| `documents/index.json` | 13 份文档：类型、用途流程标签、页数、表数、图数、切片数、抽取实体数、转化状态与转化器 | 流程 1 文档库卡、转化流水线卡、左栏摘要 |
| `documents/<doc-id>/chunks.jsonl` | 374 个切片，带 `heading_path` 与 `page` | 检索结果的章节路径与页码回溯 |
| `documents/customer-h-fu6832/params.json` | 203 条宏，含上下限、单位、分组 | 备用，当前由场景包的 `product-attributes.json` 顶着 |
| `search-samples.json` | 5 条查询的 Top 命中，带文档标题、章节路径、页码与片段 | 流程 1「检索样例」卡：点查询 → 出命中段落 → 标页码 |
| `experience/index.json` | 38 条经验（实验沉淀 30 + 规程沉淀 8）+ `caveats` | 流程 1 经验库卡 |
| `experience/taxonomy.json` | 三个正交维度：所属流程 / 问题类型 / 沉淀方式 | 经验库卡的筛选维度来[源] |

两条口径分开说，不并成一个数：

- **知识库流水线** 登记的是「哪些材料真的过了转化」，13 份、374 片，带页码可回溯；
- **场景包 `documents.json`** 登记的是「这个产品下有哪些材料」，61 条，含没转化的。

两边的条目标识不同源（`DOC-xxx` 对 `doc_id`），界面上分两段列，不硬并成一张表。

产物挂的三级节点写在 `index.json` 的 `taxonomy` 里，只对得上的场景包才用它
（`kbAppliesTo()`）。玻璃升降器包没有对应产物，四张卡一律回落到场景包自己的
`documents.json` / `experience.json`，并在卡面写明「流水线产物未就绪，没有页码」。

`experience/index.json` 的 `caveats` 是**必须显示**的：它说明这批经验成立到什么
程度（30 条实验沉淀全部来自同一个注入故障 align_weak、正常样本 0 条、
`result.status` 一律「未验证」）。经验库卡缩略态给第一条、放大态给全部。

代码：类型与取数在 `src/features/scene/kb.ts`，四张卡在 `src/features/flow-kb/panel.tsx`。

## 8. 集成进来的组件

四个组件整目录复制进 `src/features/<name>/`，**组件本体基本没改**；宿主侧的适配都放在
`src/features/flow-*/` 与 `src/features/scene/`、`src/features/waveforms/` 里。

| 组件 | 来[源] | 依赖 | 集成时改了什么 |
| --- | --- | --- | --- |
| 时序曲线 | `[源] features/timeseries` | `uplot` | 组件零改动。宿主给 `series.color` 显式取色——组件按 `status` 取色依赖首帧的 CSS 变量，首帧拿不到会退回中性调色板，合格/不合格就分不出来 |
| 工作流画布 | `[源] features/workflow` | `@xyflow/react`、`dagre` | 组件零改动。它的 `styles/workflow.css` 里 `.wf-root` 是整页演示壳（`100vh` 三栏网格），嵌进卡槽会撑破版面，因此在 `src/features/flow-req/wf-embed.css` 里加了 `.wf-embed` 覆盖，只留色板变量；缩略态另加 `.wf-thumb` 收起小地图与控制条 |
| 助手对话 | `[源] features/agent-chat` | 无 | 组件零改动。自带的 `mockAdapter` 只有一段固定脚本，不贴六条流程，因此新写了 `src/features/copilot/adapter.ts`（把脚本抽成数据，同一套 `AgentEvent` 协议）与 `scripts.ts`（六段脚本，数值路径全部取自当前场景包）。改动类动作照样走人工确认闸门 |
| 远程设备 | `[源] features/remote` | `@xterm/xterm`、`@xterm/addon-fit` | 组件零改动。网关未起时 `probeDevice` 失败即置离线态并给出起网关的命令 |

壳层侧改了三处，都是为了让真组件能用：

1. `src/components/ui/Card.tsx`：卡体原本是一个 `<button>`（整卡点击放大）。真组件要在卡内直接交互
   （画布拖拽、下拉、勾选、输入），按钮里套按钮既不合法也吃掉点击，所以卡体改成普通容器，放大改走
   卡头右上角那个「放大」图标。
2. `src/registry/index.tsx` + `src/app/AssistantPanel.tsx`：新增 `registerAssistant(flow, 组件)`，
   D 区可以整块交给真助手；没注册时仍走壳层的演示对话。
3. `src/data/loadScene.ts`：场景包从「单文件」改成「目录下 10 份 JSON」，并把它压成壳层的
   `ScenePackage`。卡片要的明细不经这层压扁，直接读 `src/features/scene/pack.ts` 的原始结构。

卡片注册表按卡片库标识唯一，所以同一张卡在多条流程里内容不同时只能注册一次、在 `render` 里按
`ctx.flow` 分派——分派表在 `src/features/index.tsx` 的 `CARD_IMPL`。

---

## 9. 待拍板与已知占位

壳层本身：

1. 产品名 `OmniTest` 是占位，未定。
2. C 区画布视图的连线与拖拽仍是壳层占位实现（网格视图才是真组件）。
3. 响应式只做到 1600 基准与向上放宽；1360 以下的抽屉降级（《设计规格》2.3）尚未实现。
4. 卡片「刷新」按钮只有按钮位，没有接重新取数。

本轮做掉的原占位（留档，便于对照）：

- **产品选择器由 `public/scenes/index.json` 驱动**，不再写死在代码里。新增场景包只在
  那份 JSON 里加一行，前端不改代码；取不到时回落到只含默认场景的最小目录。
- **切换产品弹「未保存内容将丢失」确认框**：有人工改过的参数或已锁定的流程时先问，
  确认后才换包并清掉覆盖值与锁定态（`hasUnsavedChanges()` + `ProductCascader` 的 Modal）。
- **流程 4 的第 5 张卡不再被裁**：网格固定两列两行 4 个卡槽，不长第三行；多出来的卡片
  进每张卡卡头的「换卡」下拉，选一张就换进那个卡槽。启动测试页把「单机设备会话」
  提到了第 2 槽。
- **工作流画布放大态不再被 `fitViewOptions.minZoom` 裁切**：`WorkflowCanvas` 新增
  `fitViewOptions` prop（默认仍是 `{padding:0.12, minZoom:0.6, maxZoom:1.1}`），
  宿主在放大态传 `{minZoom:0.2}`。`c/components/workflow` 的原件没动，改的是本仓的副本。
- **报告表头不再编造机型**：原先 `seed()` 硬写 `FU6832N-Diode-VSP-V1.0`，已删；
  该格显示「由上游流程带入」，左栏计数如实算 0/10。
- **未达标项不再写死**：流程 5 改为复用 `flow-run/evaluate.ts` 逐条求值，只有
  `criterion` 真判成 false 的才进未达标清单，求不出值的单列「本轮未采集，无法判定」。

数据与功能：

5. 两个场景包各自带占位：散热风扇包 13 处 `_placeholder`（风扇外形尺寸、额定母线
   12 V、额定转速 28000 RPM、`TR-CURR-01` 的峰值/稳态比上限 1.1 等），玻璃升降器包
   37 处。界面一律标「待确认」，不得当真值用。
6. 玻璃升降器包另有 188 个对象带 `_status`「待核实」——QC/T 626-2019 正式版全文未
   取得，用的是征求意见稿，数值相对正式版可能调整。界面上挂中性角标，数值照常可用，
   引用时要说明。这与「待确认」是两回事，不要混。
7. 散热风扇包的探头变比未确认（`datasets.probe_ratio_confirmed: false`），电流绝对
   量级在客户给出 mV/A 系数前不对外引用。
8. **两个包本轮都判不出结论**：判据要的现场实测量一个都没采到。散热风扇包只回放了
   CH1 相电流，而判据要的是母线电流、FG 转速一类；玻璃升降器包的时序是合成的，且
   判据要力、位移、声压级。判定卡整列「未采集」并逐条列出缺哪几个量——这是如实反映，
   不是功能没做。
9. 玻璃升降器包的 4 条工作流全部是本包自建的示例骨架（`all_placeholder: true`），
   没有客户真实文件；跑之前要按现场台架重做。
10. 历史成绩库尚未建立，`history` 卡只列场景包登记过的批次与数据集。
11. 远程设备卡在网关未起时显示离线态；台架机 SSH 在 Session 0，远程截图走
    `C:\fc_pull` 最新一张图的回退路径，不是实时截屏。
12. 三级分类树里除两个已接场景包之外的节点（吸尘器、吹风筒、水泵、通用规范）是占位，
    没有条目数。
13. 知识库流水线产物只覆盖散热风扇那一路；玻璃升降器包的文档与经验仍由场景包顶着，
    没有切片、没有页码回溯。

---

## 第三轮接口（W1 Phase A 落，并行期以此为准）

第三轮把六流程改成五流程、知识库降级为模块、C 区默认改画板、助手加预置动作。
以下接口由信息架构与壳这一包（W1）一次性落齐，其余四包直接按名取用，不要自行改这些文件。

### 1 · 流程与模块

| 导出 | 文件 | 说明 |
| --- | --- | --- |
| `FLOW_IDS` / `FlowId` | `src/data/types.ts` | 五条流程 `init` `req` `run` `tune` `report`，编号 1–5 |
| `MODULE_IDS` / `ModuleId` | `src/data/types.ts` | 模块只有 `knowledge`，不占流程序号 |
| `FLOWS` / `FLOW_BY_ID` / `FLOW_BY_PATH` | `src/data/flows.ts` | 路径不变，`index` 重排为 1–5 |
| `registerModulePage(id, component)` | `src/registry/index.tsx` | 把模块页整页内容挂到 `/knowledge` |

路由在 `src/router.tsx`：`/knowledge` 指向 `src/app/KnowledgePage.tsx`，旧路径 `/kb` 永久重定向到 `/knowledge`，
根路径与通配仍落 `/init`。顶栏右端一枚常驻知识库按钮，与五步 stepper 之间隔一条竖线。

### 2 · C 区画板

| 导出 | 文件 | 说明 |
| --- | --- | --- |
| `CANVAS_NODE_TYPES` / `CanvasNodeType` | `src/data/types.ts` | 十一类节点 |
| `CanvasEdgeKind` / `CanvasNode` / `CanvasEdge` / `CanvasLayout` | `src/data/types.ts` | 边两种语义：`physical` 物理连接、`data` 数据流 |
| `CARD_CANVAS_NODE` | `src/data/cards.ts` | 卡片库标识到节点类型的映射 |
| `registerCanvasNode(reg)` / `getCanvasNode(type)` | `src/features/canvas/index.ts` | 节点实现注册表 |
| `CanvasHost` | `src/features/canvas/CanvasHost.tsx` | 画板占位容器，一个节点都没注册时退回旧画布 |
| `BENCH_CHANNEL_MAP` / `channelLabel()` / `BENCH_CHANNEL_PENDING` | `src/data/bench.ts` | 通道映射：PWM1 接 CH4、FG1 接 CH2、FG2 接 CH3，台架实测，界面上一律标「待客户确认」 |

视图状态上提到 `useAppStore` 的 `canvasView`，默认值 `'canvas'`，网格降为备选。

### 3 · D 区助手预置动作

`CopilotAction`（`src/data/types.ts`）字段：`id`、`flow`、`label`、`icon`、`prompt`、`skill`、`requiresConfirm`。
`prompt` 与 `skill` 至少给一个。用 `registerCopilotActions(flow, actions)`（`src/registry/index.tsx`）登记，
`src/app/AssistantPanel.tsx` 的输入区上方已留好按钮槽，登记为空时整条不渲染。
图标名取值限定在 `src/app/icons.ts` 的 `COPILOT_ACTION_ICON_NAMES` 内，取不到时退回通用图标。

### 4 · 知识三轴

`KnowledgeUsage` 三类：`spec` 产品说明书、`requirement` 测试需求、`process` 工艺，固定三类不加第四类。
`KnowledgeOrigin` 两类：`doc` 文档、`experience` 经验。显示名走 `KNOWLEDGE_USAGE_LABEL` 与 `KNOWLEDGE_ORIGIN_LABEL`。
三轴筛选状态在 `useAppStore` 的 `kbFilter`，取数与筛选在 `src/features/knowledge/data.ts`。
每个流程页 B 区顶部的「本流程可用知识」窄条与抽屉是 `src/features/knowledge/KnowledgeDrawer.tsx`。

### 5 · 全局状态新增字段

`src/state/useAppStore.ts` 上提四组：`canvasView`、`canvasSelected`、`collapse`、`kbFilter`，
对应 setter 为 `setCanvasView`、`setCanvasSelected`、`setCollapse`、`setKbFilter`，
折叠记忆的键用 `collapseKey(flow, group)` 生成。

### 6 · 并行期不要碰的文件

`src/data/types.ts`、`src/data/flows.ts`、`src/data/cards.ts`、`src/data/bench.ts`、
`src/app/icons.ts`、`src/router.tsx`、`src/state/useAppStore.ts`、`src/registry/index.tsx`、
`src/features/index.tsx` 这九个文件在并行期冻结。要加东西写进跨包请求单，交收尾包统一改。

---

## 第三轮收尾（W6 落，并行期的冻结全部解除）

W1 至 W5 五包并行交付之后的一次统一收口：合并五份跨包请求单、执行编排者的七条裁决。
**上一节「第三轮接口」里凡与本节冲突的，以本节为准**——尤其是 `canvasView` 的形状与
「并行期不要碰的文件」那一条（冻结已解除）。

### 1 · 全局状态的两处形状变更

`src/state/useAppStore.ts`：

| 字段 | 旧 | 新 |
| --- | --- | --- |
| `canvasView` | `'canvas' \| 'grid'`，全局一份 | `Partial<Record<FlowId, 'canvas' \| 'grid'>>`，**按流程各存一份** |
| `setCanvasView` | `(v) => void` | `(flow, v) => void` |
| `demoMode` / `setDemoMode` | 无 | `boolean`，默认 `true`；顶栏「演示 / 全量」分段控件切它 |

两者的人工选择都持久到 localStorage（键 `omnitest.canvasView.v1`、`omnitest.demoMode.v1`），
读写包 `try/catch`：隐私窗口与禁用站点数据时 `localStorage` 会直接抛。
地址栏 `?mode=full` 仍然强制全量，供评审与截图对照。

**该显示哪个视图不要自己拼**，用 `useFlowView(flow, scene)`（`src/features/canvas`）：
人点过按人的 → 场景包的 `ui.defaultView` → 代码兜底 `FALLBACK_DEFAULT_VIEW`。
`src/features/shared/tiers.ts` 的 `demoOn()` 现在读 store，不再读地址栏，调用点一个没动。

### 2 · 场景包多一段界面配置

`ScenePackage` 新增 `ui?: { defaultView?: Partial<Record<FlowId, 'canvas' | 'grid'>> }`
（`src/data/types.ts`），由 `adaptScene()`（`src/data/loadScene.ts`）从 `scene.json` 的
`default_view` 段拼进来。`src/features/canvas/defaultView.ts` 因此不再自己 `fetch` 一次
`scene.json`——同一份 JSON 读两遍那笔账已经平掉，`resolveDefaultViews()` 与
`rememberFlowView()` 两个导出随之删除。

### 3 · AgentChat 的三个新口子

`src/features/agent-chat/AgentChat.tsx` 本轮之前对宿主是完全封闭的，宿主只能靠
「DOM 接管三件套」凑合。现在补了正经接口，那三件套整体下架：

| 新 prop / 类型 | 作用 | 取代了什么 |
| --- | --- | --- |
| `actionSlot?: ReactNode` | 渲染在 `.ac-stream` 与 `.ac-composer` 之间的 `.ac-slot` 里 | 往 `.ac-root` 里 portal 一个宿主节点 |
| `onReady?: (api: AgentChatApi) => void` | 交出命令式句柄，`api.send(text)` 代发一条消息 | 往 `.ac-textarea` 写值再点 `.ac-send` |
| `onBusyChange?: (busy: boolean) => void` | 忙态变化回调 | `MutationObserver` 盯 `.ac-header__state[data-busy]` |

`ActionDock` 的签名随之改成 `{ scope, send, busy }`，不再收容器 ref，也不再 portal。
任何一块对话都能挂：`/knowledge` 页就是这么接的（`scope="knowledge"`）。
`src/features/copilot/composer.ts` 已删除。

### 4 · 卡槽与注册表

- **网格不再回填。** `src/app/ResourcePanel.tsx` 以 `content.cards` 为准，有几张铺几张；
  没进卡槽的卡只留在卡头「换卡」下拉里。
- **`remote-device` 撤槽。** `loadScene.ts` 的 `runFlow().cards` 与 `src/features/index.tsx`
  的 `CARD_IMPL` 都不再出这张卡，`runCards['remote-device']` 与卡体 `BenchLive` 一并删除。
  设备只以画板上的 MCP 节点出现（`src/features/remote/DeviceMcpNode.tsx`）。
- **设备记录合并成一份。** `src/features/flow-run/panel.tsx` 里那份 `BENCH` 与
  `src/features/remote/device.ts` 的 `BENCH_DEVICE` 是同一台机器的逐字拷贝，留后者。
- **知识库注册归位。** `import './knowledge/register'` 统一收进 `src/features/index.tsx`，
  `src/app/KnowledgePage.tsx` 里那行临时 import 删掉。

### 5 · 图标表扩到 28 个

`src/app/icons.ts` 的 `COPILOT_ACTION_ICON` 补 11 个语义名：
`library` `folder-tree` `scale` `link` `workflow` `lock` `stethoscope` `network`
`file-diff` `note-pen` `package`。两个场景包的 `copilot-actions.json`（工程内 `public/`
与数据仓 `40_工程/agent-test-web-data/` 两处共四份）里对应的 11 枚按钮，`icon` 已按
`icon_draft` 记的原语义回填；`icon_draft` 字段保留作追溯。

### 6 · lint 与构建产物

`.oxlintrc.json` 加了 `ignorePatterns`：`dist` `dist-*` `dist-ssr` `shots` `shots2`
`node_modules`；`.gitignore` 同步加 `dist-*`。并行期 `dist-w5/` 那类产物目录曾把
lint 基线从 26 条冲到三千多条，忽略之后不会再发生。

### 7 · 截图

`node scripts/shootfinal.mjs` 出整页与放大态（`PREFIX` 默认 `final`，
`BASE` 默认 `http://localhost:4173`）；`node scripts/shootextra.mjs` 出五张状态图
`final-extra-{canvas-zoom,node-zoom,confirm,kb-filter,collapse}.png`，
每张都会打印它实际做到了哪一步。旧的 `final-kb*.png` 已由 `final-knowledge*.png` 取代。

---

## 10. 交互与设备桥

第四轮（2026-09-20）把原型上「看得见点不动」的四处接上了：顶栏动作条、左栏底部
确认按钮、判定卡未达标行、画布设备节点。本节讲配置与红线流程，改动清单见
`CHANGELOG-wire-20260920.md`。

### 10.1 两个后端，各配各的

页面这一侧接两个独立后端，地址与 token 全部经 `.env` 配置。复制模板再改：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 谁在用 | 不配会怎样 |
| --- | --- | --- | --- |
| `VITE_DEVICE_BRIDGE_URL` | `http://127.0.0.1:8031` | 设备桥。画布设备节点的状态、工具条下半截的分层工具菜单、红线动作的凭据 | 节点显示「网关 未连通」，tooltip 写明桥不可达与该起哪个脚本 |
| `VITE_BRIDGE_TOKEN` | 空 | 同上，桥的 `x-bridge-token` 头。**只是调用票，不是批准权**，见 10.5 | 所有请求被 401，节点 tooltip 指名缺这一项 |
| `VITE_GATEWAY_URL` | `http://localhost:8022` | SSH 网关。只剩设备节点放大态里那个 xterm 终端一个用途 | 终端连不上，其余一切照常 |
| `VITE_GATEWAY_TOKEN` | 空 | 同上 | 同上 |

改完 `.env` 必须重启 `npm run dev`，Vite 不热加载环境变量。

起设备桥：

```bash
cd c/components/spike-device-mcp
cp .env.example .env      # 填 FORTIOR_WIN_KEY、BRIDGE_TOKEN、BRIDGE_APPROVER_PIN
./run-bridge.sh           # 监听 127.0.0.1:8031；探一次 /health，再自动 connect 一次台架
```

桥的 `BRIDGE_TOKEN` 与前端的 `VITE_BRIDGE_TOKEN` 必须同值。桥的
`BRIDGE_APPROVER_PIN` 与它们都不同值，且**前端不配这一项**——它由人在确认卡上现场输入。
桥在 `BRIDGE_APPROVER_PIN` 未设置、或与 `BRIDGE_TOKEN` 同值时拒绝启动。

`run-bridge.sh` 起桥后会自动调一次 `connect`，并打印本次拿到的 `mode`：`live` 真连上
台架、`mock` 连不上返回合成数据、`unknown` 连接没建立。桥重启会清空 SSH 会话，
不补这一步的话 `status` 会一直停在 `unknown`，演示当场才发现没连台架。要跳过自动
连接用 `./run-bridge.sh --no-connect`，脚本会打出手动 connect 的命令行。桥默认只放行
`http://localhost:5173` 与 `http://localhost:3080` 两个来源（它的 `BRIDGE_CORS_ORIGIN`）。
前端跑在别的端口——例如 `npm run preview` 的 4173/4199——浏览器会直接拦掉请求，
页面上看不到任何错误，只会显示「未连通」。所以要联设备桥就用 `npm run dev` 的 5173，
或者去桥那侧把端口加进 `BRIDGE_CORS_ORIGIN`。

设备桥的接口清单与红线机制见 `[源] spike-device-mcp/README.md` 第 3 节与第 6 节；
前端调用点全部收在 `src/features/remote/bridge.ts` 一个文件里。

### 10.2 设备节点读什么

画布上的「设备节点」由 `src/features/remote/DeviceMcpNode.tsx` 渲染，数据源是桥的
`GET /devices`（一次取全：设备元信息、live/mock 模式、按层分组的工具清单）与
`GET /devices/{id}/status`（每 5 秒轮一次，只刷徽章）。节点上三行事实：

- **工具**：桥现在真挂着几个工具，分几层。桥不通时退回场景包工具条的登记数。
- **模式**：`live` 真连台架 / `mock` 连不上台架返回合成数据 / `未连过`。mock 一律
  显式标「合成」，不让合成数据冒充实测。
- **网关**：已连通 / 未连通。未连通时 tooltip 写明是缺 `VITE_BRIDGE_TOKEN`、
  桥地址不可达，还是鉴权不匹配，并指出该起哪个脚本。

C 区右侧工具条下半截按桥返回的三层分组渲染工具：连接层、观测层、动作层。观测层与
连接层点了直接调；动作层六个工具描边走暗红，点下去只拿凭据，不执行。

### 10.3 红线动作怎么走

红线的原话：**启动、停止、急停、写回参数、导出、归档六个动作只能人点，且必须经确认。
副驾不得自动执行。** 前端这一侧落成两条纪律：

1. 这六个动作一律经 `useAppStore` 的 `requestRedline()` 排队，弹出确认卡
   （`src/features/redline/RedlineConfirm.tsx`），人点「确认执行」才执行；
2. 批准接口 `approveConfirmation()` 只有一个合法调用点——store 的 `approveRedline()`，
   而它只由确认卡上那颗按钮触发。副驾（`features/copilot`、`features/agent-chat`）
   只能排队，不能批准：`features/agent-chat/api.ts` 拿到桥的凭据后走
   `requestRedlineAsync()` 把它排进同一张确认卡，不自己调批准接口。

接了设备桥时是三段式，**闸口在桥里，前端骗不过去**：

1. 前端不带 `confirm_token` 调一次桥的工具 → 桥拒绝执行（`executed: false`），
   回一张 `pending` 凭据，带 `prompt` 与 `args_preview`；
2. 人在确认卡上**输入批准 PIN**再点确认 → 前端调 `POST /confirmations/{token}/approve`，
   带确认人署名与 `x-approver-pin` 头（见 10.5）；
3. 前端带同一张票、**同一组参数**重调工具 → 才真执行。

凭据的四道约束（单次使用、180 秒过期、绑工具名、绑参数指纹）只在桥里实现一次，
前端不另起一套。副驾侧的 `POST /api/agent/confirm` 同样是转发这条批准接口，不另起凭据
（依据：`08a-开发接口契约-v1.0.md` 第 3.4 节「两套确认机制，收口方案」）。

桥不可达时第 1、3 步跳过，只驱动页面回放，**确认卡照弹**，并在卡上写明「设备桥未接入，
本次只驱动页面回放，不向台架下发任何控制命令」。红线口径不因为桥没起就松掉。

### 10.4 走一遍

```bash
cd c/components/spike-device-mcp && ./run-bridge.sh     # 桥已在 8031 监听则跳过
cd c/ && npm run dev               # 必须是 5173，见 10.1 的 CORS 说明
BASE=http://localhost:5173 node scripts/walk-wire.mjs
```

走查脚本要批准 PIN，从环境变量 `WALK_PIN` 读（脚本不接受写死的默认值）：

```bash
WALK_PIN=$(grep '^BRIDGE_APPROVER_PIN=' [源] spike-device-mcp/.env | cut -d= -f2-) \
  BASE=http://localhost:5173 node scripts/walk-wire.mjs
```

脚本走完整条主线：勾满九条安全闸门 → 启动按钮由灰转亮 → 点 → 确认卡 → 敲批准 PIN →
运行中 → 出判定 → 未达标行点进流程 4 → 勾选候选 → 采纳（写回参数，走红线）→
回流程 3 → 生成报告 → 导出（走红线）。截图落 `shots5/`。

### 10.5 两级鉴权：调用票与批准权

2026-09-20 修的一条严重问题（`07i-交互打通独立核验.md` 的 P1）：此前桥的全部鉴权
就是一个 `x-bridge-token`，而它随 `VITE_BRIDGE_TOKEN` 被打进 `dist` 的 JS。任何拿到
构建产物的人都能自己调工具签一张凭据、自己调 approve 批准、再带票执行，全程不需要
任何人点任何按钮——整条红线形同虚设。

现在桥把权限拆成两级：

| 秘密 | 存在哪 | 能做什么 | 不能做什么 |
| --- | --- | --- | --- |
| `BRIDGE_TOKEN`（前端的 `VITE_BRIDGE_TOKEN`，请求头 `x-bridge-token`） | 桥的 `.env` 与**浏览器包里**，按公开处理 | 列设备、查状态、调工具、驳回凭据。调红线工具只会拿到一张 `pending` 凭据 | 把凭据推到 `approved` |
| `BRIDGE_APPROVER_PIN`（请求头 `x-approver-pin`） | **只在桥的 `.env` 与桥进程内存**，不进任何 `VITE_` 变量、不进构建产物 | 批准一张 `pending` 凭据 | —— |

桥用 `hmac.compare_digest` 做常量时间比较；没带 PIN 或 PIN 不对一律 **403**，凭据
**保持 pending**（不消耗、不降级）；连续错 5 次锁 60 秒（`BRIDGE_APPROVER_PIN_MAX_FAILS`
与 `BRIDGE_APPROVER_PIN_LOCK_SECONDS` 可调），锁定期间 PIN 正确也拒。批准成功后台账
的 `approved_by` 记前端传来的操作者名，`approve_channel` 记 `human_pin`。

**PIN 在前端的边界，说清楚。** PIN 由人在确认卡上敲进一个 `type="password"` 的输入框，
只存在于该组件的 `useState` 里：换一张凭据即清空，卡关掉即随组件卸载消失。它不写
`localStorage`、不写 `sessionStorage`、不进 store、不进任何模块级变量，因此**不会出现在
构建产物里**。它确实会在敲入到请求发出的这段时间里存在于浏览器内存，也会以明文出现在
那一次 HTTPS/HTTP 请求头里——能读到这台机器浏览器内存或能嗅到这条回环流量的人仍然能拿到
它。这条边界改不掉，它换来的是：**光有构建产物批不动任何红线动作**，批准必须有人在这台
机器前面现场敲一次。要再收紧一档，下一步是把批准挪到桥所在主机上的本地确认（页面只展示
待批清单），页面这一侧连 PIN 都不经手。

自查一条，交付任何构建产物前跑：

```bash
npm run build
grep -c "$(grep '^BRIDGE_TOKEN=' [源] spike-device-mcp/.env | cut -d= -f2-)" dist/assets/*.js   # 调用票仍会命中，属预期
grep -c "$(grep '^BRIDGE_APPROVER_PIN=' [源] spike-device-mcp/.env | cut -d= -f2-)" dist/assets/*.js   # 必须为 0
```
