# 峰岹工作流画布组件

用 React Flow 渲染峰岹（Fortior）集成测试系统的 `.wfw` 工作流文件：加载、看图、点选节点查配置、改参数、增删连线、导出 JSON。独立工程，`src/features/workflow/` 下的代码可整目录搬进 `c/`。

## 一、选型

| 项 | 取值 | 依据 |
| --- | --- | --- |
| 图渲染 | `@xyflow/react` 12.11.6 | `npm view @xyflow/react version time.modified` → `time.modified = 2026-09-01T12:08:12.184Z`，2026 年 9 月仍在更新，活跃 |
| 自动布局 | `dagre` 0.8.5 | 分层有向图布局，体积小、无 WebWorker 依赖；elkjs 能力更强但打包体积与异步 API 在本场景无收益 |
| 截图 | `playwright` + 本机 Chrome | 复用 `[源] chrome-linux64/chrome`，不额外下载浏览器 |

## 二、`.wfw` 格式发现

数据来源：客户端引擎类型定义 `app/src/features/integrated-test-system/workflow/models/types.ts`、节点面板 `models/nodeTypes.ts`、读写实现 `app/src-tauri/src/integrated_test_system/workflow_commands.rs`；样例为 `archive-POC/40_工程` 下的 68 个 `.wfw`。

### 2.1 容器层

1. **可选 gzip**。Rust 侧按魔数 `0x1f 0x8b` 自动判别（`is_gzip_compressed()`），压缩与否都用 `.wfw` 扩展名。**实测 68 个样例全部未压缩**，魔数均为 `0x7b 0x0a`（即 `{\n`）。解析器两条路径都实现了。
2. **UTF-8 JSON，可能带 BOM**。解析前必须剥掉 `U+FEFF`，否则 `JSON.parse` 直接抛错。
3. 相关常量：`.wf.json.gz`（V1 压缩后缀）、`.wflz`（V2 压缩后缀）在引擎里有定义，但现场文件一律是 `.wfw`。

### 2.2 结构层

```
{
  formatVersion: "1.0.0",
  metadata:   { id?, name, description?, author?, createdAt, updatedAt,
                version: {major,minor,patch}, tags[], category?,
                isTemplate, isSubsystem },
  definition: { nodes[], edges[], variables[], ports?, curveGroups?, curveBindings? }
}
```

`definition.nodes` **已经是 React Flow 的节点形状**：`{ id, type, position: {x,y}, data }`，参数全部平铺在 `data` 里（除 `label` 外的字段即业务参数）。这是本次最省事的一点——不需要做坐标或字段的形状转换。

`definition.edges`：`{ id, source, target, sourceHandle, targetHandle }`。

### 2.3 四个会踩的坑

1. **`metadata.name` 基本是废字段**。68 个文件里 67 个是占位值「新工作流」，只有 `SCOPETEST_时序采集_v1.wfw` 填了真名。**展示名必须从文件名派生**，本工程的 `displayName()` 就是这么做的。
2. **`sourceHandle` 承载分支语义**，取值 `output`（主干）、`error`（异常出口）、`true`/`false`（条件分支）。这解释了为什么连线数常常多于节点数——`14 节点 / 20 连线` 的图里，多出来的正是每个节点指向公共异常节点的 `error` 边。本工程把 `error` / `false` 画成暗红虚线，主干画墨绿实线。
3. **`subworkflow` 节点内嵌整个子工作流**。`data.embeddedWorkflow` 是一份完整的工作流结构（自带 `definition`），单个这样的节点能到 50 KB。样例里共 56 个内嵌节点。解析器对它递归调用自身，结果挂在 `node.embedded` 上。
4. **存在枚举外的节点类型**。`WorkflowNodeType` 枚举有 58 个成员，但子流程文件里出现了 `hid_preset_pwm_speed_set`——不在枚举内。解析器不能假设类型封闭，未知类型归入 `unknown` 分组照常渲染，另设 `LEGACY_NODE_TYPE_GROUP` 给已知的历史遗留类型兜底。

### 2.4 节点分组

分组取自 `nodeTypes.ts` 的 `NODE_CATEGORIES`，**实际是 11 个而非 8 个**：基础、HID 通信、功能设置、代码调试、参数查询、逻辑控制、数据处理、验证、子系统、仪器设备、报告输出。58 个枚举成员中 57 个在节点面板有归属，`_deprecated` 是加载老文件时的兜底类型、不进面板，本工程归入「基础」。

每组配一个墨绿明度档，从 `#1F4232`（基础，执行主干）递浅到 `#BCD2C6`（报告输出），同色相、不引入第三色相。

## 三、接口

```ts
import {
  WorkflowCanvas, WorkflowCard, PropertyDrawer,
  parseWfw, parseWfwAsync, exportJson,
  listWorkflows, loadWorkflow, groupEntries,
  layoutModel, NODE_GROUPS, groupOf,
} from './features/workflow'
```

### 3.1 解析

```ts
parseWfw(buffer: ArrayBuffer): WorkflowModel        // 同步，仅未压缩
parseWfwAsync(buffer: ArrayBuffer): Promise<WorkflowModel>  // 自动解 gzip
exportJson(model: WorkflowModel): string
```

统一内部模型：

```ts
interface WorkflowModel {
  nodes: { id, type, label, group, params, position, embedded? }[]
  edges: { id, source, target, sourceHandle?, targetHandle? }[]
  meta:  { id?, name, formatVersion, compressed, tags, isSubsystem, ... }
  variables: unknown[]
}
```

### 3.2 组件

```tsx
<WorkflowCanvas
  model={model}                      // 必填
  selectedId={selected?.id ?? null}   // 选中态由宿主受控
  onSelect={(node) => ...}            // 点空白处传 null
  onChange={(model) => ...}           // 增删连线后的完整模型
  readonly={false}                    // 只读时禁止拖拽/连线/删边
/>

<WorkflowCard entry={indexEntry} model={model} active onOpen={(e) => ...} />

<PropertyDrawer node={node} readonly onParamChange={(id, key, v) => ...}
                onLabelChange={(id, label) => ...} />
```

`WorkflowCanvas` 只负责渲染与交互，不持有业务状态；参数编辑走 `PropertyDrawer` 直接改模型，连线增删走 `onChange`。画布内部用「节点 id + 连线 id 的签名」判断是否需要重排，因此改参数或改名不会打乱已有布局。

### 3.3 数据

```ts
listWorkflows(opts?): Promise<WorkflowIndexEntry[]>   // 读 <base>/workflows.json
loadWorkflow(entry, opts?): Promise<WorkflowModel>    // 读 <base>/wfw/<file>，带内存缓存
groupEntries(entries)                                 // 按业务分组折叠用
```

`opts.baseUrl` 默认 `'data'`，集成到宿主时改成宿主的静态资源前缀即可。注意文件路径含中文与空格，`loadWorkflow` 内部逐段 `encodeURIComponent`。

### 3.4 布局

```ts
layoutModel(model, { nodeSep, rankSep, direction, wrap, aspect }): Positions
```

原文件自带 `position`，但那是人工拖拽的结果，跨文件疏密不一、常有重叠，所以一律重排。峰岹的工作流绝大多数是「一条长链 + 一个公共异常出口」，纯 dagre 左→右会摊成几千像素宽、几十像素高的细带，在 16:9 视口里读不了。因此对链式图（层数 ≥ 9 且每层 ≤ 2 个节点）额外做一次**蛇形折行**，按目标宽高比折成矩形；不满足条件的图保持 dagre 原结果。`wrap: false` 可关掉。

## 四、生成数据

```bash
npm run data       # 从峰岹目录抽取 → public/data/{workflows.json, wfw/}
npm run coverage   # 全量解析覆盖报告
npm run build
npm run shots      # 截图到 shots/
```

`scripts/buildIndex.mjs` 只读客户原文件，不做修改。源路径可传参覆盖，默认 `[源] archive-POC/40_工程`。三个来源：

| 来[源] | 目录 | 数量 |
| --- | --- | --- |
| 主流程 | `ClientSoftware/WORKINGflow/WORKINGflow` | 58 |
| 子流程 | `ClientSoftware/子流程/子流程` | 9 |
| 附加 | `测试数据_20260622/SCOPETEST_时序采集_v1.wfw` | 1 |

索引条目字段：`id / name / group / voltage / file / nodeCount / edgeCount / isSubflow / compressed`。电压档由文件名与目录推断，`HSLV` 必须先于 `LV` 匹配否则误判；`HV_SV_LV_*` 这类三档合一的调度流程标为 `MIXED`。

拷贝后的 `public/data/wfw/` 共 **3.72 MB**，在 10 MB 预算内。

## 五、集成进 `c/`

1. 整目录复制 `src/features/workflow/` 到宿主的 `src/features/` 下。
2. 宿主安装 `@xyflow/react`、`dagre`、`@types/dagre`。
3. 复制 `scripts/buildIndex.mjs`，把输出目录改成宿主的静态资源目录，加一条 `npm run data`。
4. 调用处传 `baseUrl`：`listWorkflows({ baseUrl: '/static/workflow' })`、`loadWorkflow(entry, { baseUrl: '/static/workflow' })`。
5. 引一次 `styles/workflow.css`。样式全部挂在 `.wf-*` 类名下、CSS 变量定义在 `.wf-root` 作用域内，不污染宿主全局。
6. 若宿主已有自己的色板，只需覆盖 `.wf-root` 上的 `--wf-*` 变量。

若宿主直接对接 Tauri 后端而不是静态文件，把 `workflowStore.ts` 里的 `fetch` 换成 `invoke('load_workflow_from_file', ...)`，再把返回的 JSON 字符串编码成 `ArrayBuffer` 喂给 `parseWfwAsync` 即可，其余不变。

## 六、色板

| 角色 | 色值 |
| --- | --- |
| 主色 | `#2E5E45` |
| 主色深 / 浅 | `#1F4232` / `#A8C5B5` |
| 强调（异常分支、选中态、MIXED 标记） | `#A6353A` |
| 浅底 | `#EAF2EC` |
| 文字 / 次级 / 弱化 | `#2C2C2C` / `#555555` / `#9A9A9A` |
| 分隔线 | `#C8C5BD` |
| 背景 | `#FFFFFF` |

节点一律描边成形、不做实色填充，仅选中时用浅底。层次靠线宽（1.5 / 1）、虚实（实线 / `6 4` 虚线）、色深三者区分。
