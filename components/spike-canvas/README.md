# C 区统一画布技术 spike

针对「多场景 Agent 测试系统」C 区面板的独立验证工程。只验证三件事：**滚轮整体缩放**、
**统一画板仿物理连接**、**右侧工具条拖入节点**，外加设备以 MCP 节点形态出现在画板上。
对应 2026-09-19 录音意见 R-03 / R-04 / R-07 / R-17（原话见
`docs/20260919-通用Agent测试系统v2.0/00b-用户录音意见原话-20260919-2121.md`）。

本工程**不修改**现有前端原型 `c/` 下的任何文件。

---

## 一、选型结论

**用 React Flow（npm 包 `@xyflow/react`，版本 12.11.6，MIT 许可，官网 https://reactflow.dev）做 C 区统一画板；
自研 SVG 路线放弃。**

理由按重要性排三条：

### 1. 它在本项目里已经是既有技术栈，边际成本为零

`c/package.json` 已经依赖 `@xyflow/react` 12.11.6，
`[源] components/WorkflowCanvas.tsx` 用它渲染了 68 个客户 `.wfw` 工作流。
C 区现在既不能缩放也不能拖入，原因不是"没有能力"，而是
`[源] app/ResourcePanel.tsx` 里的 `CanvasView` 走的是另一套实现——
绝对定位的 `<div>` 加一层手画 `<svg>` 连线，压根没接 React Flow。
所以这不是引入新依赖，是把已经付过的账用起来。

包体积实测（本 spike 工程 `npm run build`，含 React 18 与 lucide-react）：

| 构建 | JS (gzip) | CSS (gzip) |
| --- | --- | --- |
| 含 React Flow（方案 A + B 两页） | 111.5 KB | 4.2 KB |
| 不含 React Flow（只留方案 B） | 50.8 KB | 1.8 KB |
| **React Flow 增量** | **约 61 KB** | **约 2.4 KB** |

这 63 KB 在 `c/` 里已经被工作流画布付掉了，C 区复用它不再增加一个字节。

### 2. 用户要的三种交互全部开箱，不需要自己实现

| 录音要求 | React Flow 的实现方式 | 自研需要自己写 |
| --- | --- | --- |
| R-03 滚轮整体缩放、外框尺寸不变 | `zoomOnScroll`（默认开），`minZoom` / `maxZoom` 限幅 | 指针锚点缩放公式、限幅、与页面滚动的 `preventDefault` 竞争 |
| R-03 拖拽平移 | `panOnDrag`（默认开） | pointer capture、平移与节点拖动的事件分流 |
| R-04 统一画板、节点可自由摆放 | `nodesDraggable`，节点坐标即模型 | 拖动命中测试、坐标系换算 |
| R-04 右侧拖入功能模块 | `screenToFlowPosition()` 一行把落点换成画布坐标 | 自己维护 transform 逆矩阵 |
| 仿物理连接的连线 | 内置 `smoothstep`（正交带圆角）/ `default`（贝塞尔），带 `label` 自动加白底 | 自己写路径生成器 |
| 双击复位 | `fitView()` | 自己算包围盒 |

方案 B 那一页是真的写出来跑通了的（见 `src/SvgSpike.tsx`，约 180 行），五件事都能动。
但它暴露了自研路线的真实代价：**连线路由没法靠一个公式糊过去**。
截图 `shots/svg-1-default.png` 里，「FU6832N 驱动板 → 涵道风机电机」这条"三相输出"边被画成一条竖直线，
直接穿过了驱动板卡片本身；同一张图里 React Flow 版（`shots/flow-1-default.png`）把它绕成了 L 形折线。
要把自研版做到同等水准，得补节点避让、边标签防重叠、多边并行分离——这几项本身就是 React Flow 的核心代码量。

### 3. 自定义节点外观不受限，设计令牌能 100% 贴合

React Flow 的自定义节点就是一个普通 React 组件，外框、描边、卡头图标、状态圆点全部由业务代码控制，
库只注入定位和 `<Handle>` 连接点。本 spike 的 `src/NodeCard.tsx` 在方案 A 与方案 B 之间**逐字复用**，
两版截图的卡片外观完全一致——这直接证明"换成 React Flow 不会被库的样式绑架"。

兼容性实测：本 spike 跑在 **Vite 5.4.21 + React 18.3.1 + TypeScript 5.6**，`tsc -b` 零报错，构建通过。
`@xyflow/react` 的 peerDependencies 写的是 `react: ">=17"`，宿主工程的 React 19.2 同样在范围内
（`c/` 的工作流画布已经在 React 19 下跑了 68 个工作流，是活的证据）。

---

## 二、怎么跑

```bash
cd [源] lab/spike-canvas
npm install
npm run dev            # http://localhost:5300
```

- `http://localhost:5300/#flow` —— 方案 A，React Flow（默认页）
- `http://localhost:5300/#svg` —— 方案 B，自研 transform 视口 + SVG 连线（对比用）

画布操作：滚轮缩放 / 在空白处按住拖拽平移 / 双击复位 / 拖动节点改位置 /
从右侧竖向工具条把图标拖到画布中间放置新节点。

重新出截图（需要 dev server 已在跑）：

```bash
npm run shots          # 产物落到 shots/
```

截图脚本 `scripts/shots.mjs` 用 playwright 1.63 驱动本机已缓存的 chromium
（`chromium.launch({ channel: 'chromium' })`，避开缺失的 headless shell 构建），
视口 1280×700、`deviceScaleFactor: 2`，只截 `[data-testid="panel"]` 这个固定外框。

---

## 三、截图

目录 `[源] spike-canvas/shots`：

| 文件 | 内容 |
| --- | --- |
| `flow-1-default.png` | 方案 A 默认态，缩放 96%，六类节点全在框内 |
| `flow-2-zoomed.png` | 方案 A 放大态，缩放 145%，外框尺寸不变、内容整体放大并被框裁切 |
| `flow-3-dropped.png` | 方案 A 从工具条「设备」组拖入一个"示波器"节点后，新节点带选中描边、状态为"未连接 · SSH 待连接" |
| `svg-1-default.png` | 方案 B 默认态，同样的节点组件，但连线穿卡 |
| `svg-2-zoomed.png` | 方案 B 放大态 139% |
| `svg-3-dropped.png` | 方案 B 拖入节点后 |

---

## 四、画面构成（对照客户 Copilot 页）

参照图：`.../20260919-通用Agent测试系统v2.0/_调研/ref-客户Copilot页面-用户提供-20260919.png`。
从那张图上抄过来的四件事：

1. **一块统一画板**，不再切成功能块网格；元素自由摆放，靠连线表达关系。
2. **右下角缩放条**：`−` / 百分比 / `+` / `复位`，与客户页面同位置同顺序。
3. **右侧竖向工具条**分组，每个图标右上角带连接状态小圆点。
4. **左下角图例**，说明实线/虚线各代表什么，以及三种鼠标操作。

节点分六类，类型决定外观，实例只带业务字段：

| 类型 key | 中文 | 卡头副标题 | MCP 标签 | 示例实例 |
| --- | --- | --- | --- | --- |
| `dut` | 被测对象 | 直流无刷电机 | — | 涵道风机电机 |
| `board` | 驱动板 | 电机驱动芯片 | — | FU6832N 驱动板 |
| `bench` | 测试台架 | 台架控制 | MCP | 风机测试台架（SSH · 172.25.5.166:8963） |
| `scope` | 示波器 | 波形采集 | MCP | Rigol DS1104Z（SSH · VISA 直连） |
| `workflow` | 工作流 | 测试编排 | — | 变速稳态工作流 |
| `datasource` | 数据[源] | 知识库 / 数据集 | — | 芯片知识库 |

R-17 的落法：设备就是画板上一个普通节点，右上角一枚 `MCP` 标签说明它是 MCP 节点；
后台链路是 SSH 这件事只以一行灰字写在卡底（"SSH · 172.25.5.166:8963"），
**不做任何 SSH 专属页面**。连接状态是卡底的一枚圆点，四态：已连接（墨绿）/ 有告警（琥珀）/
连接中断（暗红）/ 未连接（灰）。截图里 Rigol 示波器故意设成"连接中断"，
它是全图唯一的暗红卡框——符合"暗红每屏 ≤ 2 处"的配色约束。

连线两类，样式与工作流画布同口径（抄自 `WorkflowCanvas.tsx` 的 `edgeStyle`）：

- **物理接线**：`#2e5e45` 实线，线宽 1.5，`smoothstep` 正交折线。台架→驱动板→电机→示波器这条链路。
- **数据链路**：`#a8c5b5` 虚线 `6 4`，线宽 1，贝塞尔，带流动动画。工作流/知识库下发到台架的那两条。

层次只靠线宽、虚实、色深区分，不靠填充明度；节点一律描边成形，
唯一的浅色填充是卡头的 `--p-50`，非白填充占画面远低于 15%。

---

## 五、怎么嵌回 `c/`

### 5.1 替换哪个组件

替换目标是 **`[源] app/ResourcePanel.tsx` 里的 `CanvasView` 函数**（该文件第 19–91 行那一段），
它现在的实现是绝对定位 `<div>` 加手画 `<svg>` 直线，既不能缩放也不能拖入。
`ResourcePanel` 外层的「网格 / 画布」分段控件、`ToolRail` 挂载位置、`Modal` 放大浮层都不动。

落地建议拆成三个文件，放在新目录 `src/features/canvas/`：

| 新文件 | 内容 | 从本 spike 搬 |
| --- | --- | --- |
| `src/features/canvas/UnifiedCanvas.tsx` | 画布本体，含 `ReactFlowProvider`、拖放、缩放条 | `src/FlowSpike.tsx` 的 `Canvas` 与 `ZoomBar` |
| `src/features/canvas/DeviceNodeCard.tsx` | 六类节点的外观 | `src/NodeCard.tsx` |
| `src/features/canvas/model.ts` | 类型与 `KIND` 元数据表 | `src/model.ts` |

`ResourcePanel.tsx` 里把 `<CanvasView flow={flow} scene={scene} onExpand={setOpen} />`
换成 `<UnifiedCanvas flow={flow} scene={scene} onExpand={setOpen} />` 即可；
节点双击仍旧调 `onExpand` 打开原有的放大浮层，卡片内容复用 `registry` 里已注册的 `render()`。

### 5.2 怎么与现有 `WorkflowCanvas` 共用，避免两套画布

**两套画布的边界要划清楚：`WorkflowCanvas` 画的是"一个工作流内部的步骤图"，
统一画板画的是"整个测试系统里各实体之间的物理与数据连接"。语义不同，不能合并成一个组件。**
但底下三样东西必须共用，否则就会出现两套长相不一样的画布：

1. **共用 React Flow 实例配置口径**。抽一个 `src/features/canvas/flowDefaults.ts`，
   导出 `proOptions={{ hideAttribution: true }}`、`minZoom` / `maxZoom`、`fitViewOptions` 这些
   两边一模一样的参数，两个画布都从这里取，不各写一份。

2. **共用连线样式函数**。`WorkflowCanvas.tsx` 里那个 `edgeStyle(sourceHandle)` 函数
   （主干 `#2e5e45` 实线 1.5 / 弱化 `#a8c5b5` 虚线 `6 4` 线宽 1）直接提到
   `src/features/canvas/edgeStyle.ts`，两个画布都 import。
   本 spike 已经按这个口径对齐，截图里两种画布的连线视觉是同一套。

3. **共用节点卡的底层样式类**。`WorkflowNodeCard.tsx`（工作流节点）与 `DeviceNodeCard.tsx`（设备节点）
   字段不同，不能合并成一个组件，但它们的外框、描边、选中态、`<Handle>` 尺寸应当来自同一份 CSS。
   建议把 `[源] styles/workflow.css` 里 `.wf-node`、`.wf-handle`
   这两条规则提成 `.flow-node` / `.flow-handle` 放进共享样式文件，两边各自只加自己的内容层类名。

反过来，统一画板里的「工作流」节点被双击展开时，应当直接复用 `WorkflowCanvas` 渲染该工作流的内部步骤图。
这样两套画布是嵌套关系而不是并列关系：统一画板是外层系统视图，工作流画布是某个节点的内部视图。

### 5.3 数据结构：nodes / edges JSON 放场景包哪里

场景包真实源目录（不是 `40_工程/agent-test-web-data/scenes/`，实测该路径不存在）：

```
c-data/scenes<sceneId>/
```

现有两个场景：`motor.cooling-fan.fortior-fu6832` 与 `automotive.body-motor.window-regulator`。
每个场景是一个目录下的 11 份 JSON（`scene.json`、`workflows.json`、`documents.json`、
`control-parameters.json`、`test-requirements.json` 等），整目录被复制到
`./scenes/<sceneId>/` 供前端 `loadScene()` 读取。

**建议新增第 12 份文件 `canvas.json`**，与其他 JSON 平级，而不是塞进 `scene.json` 的 `flows` 里。
理由：画布拓扑是跨流程复用的（同一套台架接线在流程 2 到流程 6 都一样），
塞进 `flows[flowId].canvas` 会导致六份重复。

结构照抄本 spike 的 `src/model.ts`：

```jsonc
{
  "schema": "canvas/v1",
  // 默认拓扑：所有流程共用
  "nodes": [
    {
      "id": "bench-1",
      "kind": "bench",                       // dut | board | bench | scope | workflow | datasource
      "name": "风机测试台架",
      "state": "online",                     // online | warn | fault | offline
      "channel": "SSH · 172.25.5.166:8963",  // 卡底灰字，MCP 节点在这写后台链路
      "facts": [["通道", "PWM1/2 · FG1/2"], ["台架", "bench-a"]],  // 最多 3 行，超出折叠
      "x": 330, "y": 170
    }
  ],
  "edges": [
    { "id": "e3", "from": "bench-1", "to": "board-1", "kind": "physical", "label": "PWM 驱动" }
    // kind: physical（实线正交，物理接线）| data（虚线贝塞尔，数据链路）
  ],
  // 每个流程只声明"高亮哪几个节点"，不重复整张拓扑
  "flowFocus": {
    "flow-3": { "highlight": ["bench-1", "scope-1"], "dim": ["ds-1"] }
  }
}
```

对应要改的宿主类型：`[源] data/types.ts` 第 139–142 行那个
`canvas?: { nodes: {id: CardId, x, y, w, h}[], links: {...}[] }` 应当废弃——
它把节点 id 绑成了 `CardId`（卡片库的 id），而画板上的设备节点根本不是卡片。
新结构里 `id` 是自由字符串，`kind` 决定外观，节点与卡片的关联另用可选字段 `cardId` 表达。

右侧工具条的可拖入条目，建议挂在 `scene.json` 已有的 `toolGroups` 下面，
给每个 tool 加一个可选的 `spawn` 字段，值就是一个不带 `id` / `x` / `y` 的节点模板；
有 `spawn` 的工具才能拖入画布，没有的保持现在点开抽屉的行为。

---

## 六、已知限制

本 spike 刻意没做、真正落地时要补的东西：

### A. 画布能力

1. **没有持久化**。拖动节点、拖入新节点的结果只在内存里，刷新即回到种子数据。
   落地要决定：节点位置是写回场景包（所有人共享），还是存 localStorage（每人自己的摆法）。
2. **没有手工连线**。`onConnect` 没接，用户不能自己拖一条边出来。
   考虑到"仿物理连接"的语义是反映真实接线而不是让用户随便连，这条可能本来就不该开，但需要确认。
3. **没有删除节点 / 撤销**。拖错了只能刷新。
4. **没有小地图**。`WorkflowCanvas` 用了 `<MiniMap>`；节点上到十几个以后统一画板大概也需要，但会占掉右下角。
5. **节点位置是手写死的坐标**，没有自动布局。`[源] lib/layout.ts`
   里已有基于 dagre 的 `layoutModel()`，但物理接线图用分层自动布局反而会破坏"台架在中间、设备在两侧"的空间直觉，
   建议坐标就由场景包给定。

### B. 与真实后端的落差

6. **状态圆点是静态数据**。真实的 MCP 节点连接状态要从后端轮询或推送，
   本 spike 的 `state` 字段是写死的。
7. **`facts` 只显示前 3 行，多出来的直接丢弃**，没有做 R-16 要求的折叠交互。
8. **节点双击没有接放大浮层**，spike 里双击是画布复位。嵌回宿主时这两个手势会冲突，
   需要改成"双击画布空白处复位、双击节点展开"。

### C. 工程

9. **方案 B 那一页不该合并进宿主**，它只是对比证据。嵌入时只搬 `FlowSpike.tsx` 与 `NodeCard.tsx`。
10. **spike 用的是 React 18 + Vite 5**，宿主是 React 19 + Vite 8 + Tailwind 4。
    搬过去时 `tokens.css` 那份要删掉（宿主已有 `src/styles/tokens.css`），
    类名建议改写成宿主的 Tailwind 原子类或按宿主约定进 `src/features/canvas/canvas.css`。
11. **截图脚本依赖本机已缓存的 chromium**。换机器要先 `npx playwright install chromium`。
