# 视觉缺陷修复记录 · 2026-09-20

修的是 `03-截图/CHANGES-v2.1-to-v3.0.md` 第 13 节「本次人眼复检发现的问题（不阻断交付，记录待修）」
列出的 5 条，外加第 1 条连带的截图脚本静默失败。工程根目录 `c/`（非 git 仓库），
动手前把 `src/` 整份备份到 `（见交付包内备份）`，下面的「原行号」即相对该备份。

本轮只动了以下 6 个文件，`src/features/flow-run/**`、`src/features/flow-tune/**`、
`src/data/**` 一行未碰（另一会话在改）。

---

## 1. 截图脚本静默失败：`final-zoom-evidence.png` 名不副实

**病因**：`scripts/shootfinal.mjs` 的 `ZOOM` 表里写的是 `['zoom-evidence', '/knowledge', 1]`，
它在知识库模块页上点 `[aria-label$="放大"]` 的第 2 枚按钮。知识库模块页（`src/features/knowledge/KnowledgeModule.tsx`）
改成「左筛选 / 中列表 / 右详情」三栏之后**整页没有任何放大按钮**（全文件只有 `aria-label="上一页"`
与 `"下一页"` 两处），点击必然超时，而超时被 `.catch(() => {})` 吞掉，脚本照旧出图，
出来的是一张没有浮层的知识库整页图。

**改法**：
- 知识库模块页确无放大态，该条从「知识库模块页」改挂到流程 2（测试需求）画板上的
  「知识库依据」节点——那才是真正的知识依据放大态。新口径为
  `['zoom-evidence', '/requirements', '知识库依据']`（节点标题实测为「知识库依据」，
  取自 `src/data/cards.ts` 第 23 行 `evidence: { title: '知识库依据' }`）。
- 两份脚本里所有 `.catch(() => {})` 全部去掉，换成 `warn(name, msg)` 记录并打印 `[warn]`；
  收尾若 `WARNINGS` 非空，打印清单并 `process.exit(1)`。
- 放大类截图另加一道断言：动作之后页面上若 `.tp-modal, [role="dialog"]` 计数为 0，
  记一条「这张图不是放大态」的警告。
- 新增 `OUTDIR` 环境变量换输出目录（默认 `shots2`），自查时不覆盖交付图。

**改动文件与行号**（当前行号）：

| 文件 | 行 | 内容 |
| --- | --- | --- |
| `scripts/shootfinal.mjs` | 5 | 文件头环境变量说明补 `OUTDIR` |
| `scripts/shootfinal.mjs` | 11 | `OUT` 改读 `process.env.OUTDIR` |
| `scripts/shootfinal.mjs` | 34–51 | `ZOOM` 表第三项换成 `/requirements` 的「知识库依据」节点，附成因注释；新增 `WARNINGS` 与 `warn()` |
| `scripts/shootfinal.mjs` | 78–97 | `waitForLoadState` / `dblclick` / `click` 三处 catch 改成记警告；补浮层断言 |
| `scripts/shootfinal.mjs` | 101–106 | 收尾打印失败清单并 `process.exit(1)` |
| `scripts/shootextra.mjs` | 5、12 | 同上，`OUTDIR` |
| `scripts/shootextra.mjs` | 22–27 | `WARNINGS` 与 `warn()` |
| `scripts/shootextra.mjs` | 33 | `canvas-zoom` 的 note 由「左下角缩略导航图」改为「其上方的缩略导航图」（配合第 4 条） |
| `scripts/shootextra.mjs` | 41–48、64–76、140–150 | 三处 catch 改成记警告；`act()` 抛错也记警告 |
| `scripts/shootextra.mjs` | 154–159 | 收尾非零退出 |
| `README.md` | 299 | 第 6.2 节 `final-zoom-evidence.png` 那一行改口径并写明旧口径为什么是错的 |
| `README.md` | 306–310 | 第 6.2 节补一段：脚本不再吞失败、`OUTDIR` 用法 |

**非零退出实测**：把节点名临时改成不存在的「不存在的节点XYZ」跑一次，脚本打印两条
`[warn]` 并以退出码 1 结束（`EXIT_CODE=1`），改回后全量重跑两份脚本均打印
「✓ 全部动作成功，无静默失败」、退出码 0。

---

## 2. 画板节点底部内容被裁切、无滚动提示

**病因**：`src/components/ui/Card.tsx` 的 `PanelCard` 卡体是 `overflow-hidden`，
而 `CanvasNodeShell` 的内容区只有 `min-h-0 flex-1`，没有 overflow 也没有渐隐，
内容超出节点固定高度时直接硬切在半行上。

**改法**（不写死任何绝对高度，遵守 `DESIGN.md` 第 3 节第 3 条「卡内长列表用底部渐隐 + 无滚动条」）：
- `src/features/canvas/CanvasNodeShell.tsx` 原第 68 行 → 现 68–72 行：内容区加 `cv-node-scroll` 类。
- `src/features/canvas/canvas.css` 末尾新增 `.cv-node-scroll`（现 125–149 行）：
  `overflow-y: auto` + 隐藏滚动条 + `::after` 用 `position: sticky; bottom: 0` 加 `margin-top: -16px`
  做一层不占高度、不跟着内容滚的底部渐隐。
  没有复用 `src/index.css` 的 `.fade-b`：那一条带 `scrollbar-gutter: stable`，
  在 240px 宽的节点里会吃掉一截正文宽度。

**验证**：`shots4/final-init.png` 的「台架实况」节点末行「红外转速计」、「设备节点」末行
「网关未连通」，由 v3.0 的全不透明硬切变为渐隐收尾；`shots4/final-req.png` 的「判定卡」
与「知识库依据」两个节点同样。

**未修的部分（超出文件所有权）**：`final-report.png` 上的「判定卡」「模板字段」不是画板节点——
测试报告页默认走网格视图（`src/features/canvas/defaultView.ts` 的 `FALLBACK_DEFAULT_VIEW.report = 'grid'`），
这两张是 `src/features/flow-report/panel.tsx` 渲染的网格卡片，不在本轮可改文件范围内。
实测它们本来就各自挂了 `style={mask}` 的遮罩渐隐（见该文件第 602、626 行附近），
本轮前后截图逐像素一致，不是硬切。

---

## 3. 知识库右栏「备注」末行与卡片下边界叠压

**病因**：`DetailColumn` 的滚动容器写的是 `fade-b … px-4 pb-4`。
`.fade-b::after` 是 `position: sticky; bottom: 0`，它的定位基准是滚动容器的**内边距盒**——
容器只要有 `padding-bottom`，渐隐带就被顶到离底 16px 处，最后那 16px 正文既不渐隐、
又被面板的 `overflow-hidden` 硬切，于是「备注」这种多行长文的末行与卡片下边界叠成一团。

**改法**：`src/features/knowledge/KnowledgeModule.tsx`
- 原第 262 行 → 现 262–263 行：`Field` 的正文行高由 `leading-5`（20px）抬到 `leading-[1.65]`，
  长路径这类连续字符不再挤成一团。
- 原第 266 行后 → 现 268–277 行：给 `DetailColumn` 补一段说明上述成因的文档注释。
- 原第 285 行 → 现第 296 行：底部留白由容器的 `pb-4` 改挂到末个字段上
  （`[&>div:last-child]:pb-7`），并去掉末个字段的下框线（`[&>div:last-child]:border-b-0`），
  免得与卡底连成双线。

**验证**：`shots4/final-knowledge.png` 右栏「备注」末行「发资料/调试经验文档/FU-AM-FOC方案调试手册-.md」
完整成行、与卡片下边界之间留白充足，无叠压。与 03-截图 下 v3.0 同位置裁剪对比确认。

---

## 4. 画板缩放态下缩略导航图压住「文档读取」节点

**改法**：
- `src/features/canvas/CanvasHost.tsx` 原第 192 行 → 现 192–194 行：`MiniMap` 的
  `position` 由 `bottom-left` 改为 `bottom-right`；原第 170 行注释同步改。
- `src/features/canvas/canvas.css` 现第 118–119 行：给 `.react-flow__minimap` 补
  `margin-bottom: 54px`，让出右下角缩放条（30 高 + 12 间距）的位置，两个控件叠成一摞控制区。

**验证**：`shots4/final-extra-canvas-zoom.png`，脚本实测输出「缩放读数 130%；缩放条中心 x=1731；
缩略导航图中心 x=1754」（v3.0 时为 x=514）。左下角的「文档读取」节点恢复完整可见
（「40 KB」「24/29」两行不再被盖）。

---

## 5. 设备节点放大浮层右半区大面积留白

**病因**：所有节点放大态共用 `width={1220}` 与 `h-[min(64vh,470px)]`，
而设备节点的浮层内容（`src/features/remote/DeviceMcpNode.tsx` 的 `DeviceMcpExpanded`）
只有「设备卡 + 接入形态 + 工具统计 + 终端占位」四块，左栏固定 320px，右栏按 1220 宽铺开后基本是空的。

**改法**（`src/features/remote/**` 不在本轮可改范围，故在调用侧收口）：
`src/features/canvas/CanvasHost.tsx`
- 原第 404 行 → 现 407–409 行：`width={expanded?.type === 'device-mcp' ? 860 : 1220}`。
- 原第 418 行 → 现 423–428 行：容器高度按类型分档，设备节点走 `h-[min(42vh,300px)]`，
  其余仍是 `h-[min(64vh,470px)]`；为此第 35 行的 import 补了 `cn`。

**验证**：`shots4/final-extra-node-zoom.png`。浮层由 1220×470 收到 860×300，
右栏「已挂工具」说明文字由一行半铺满改为两行自然换行，终端占位块的空白面积
由约 900×300 收到约 480×220。留白未归零——「终端只在放大态出现」那块占位区
是终端真正打开后要占的位置，按设计保留。

---

## 门禁与截图

| 项 | 结果 |
| --- | --- |
| `npx tsc -b` | 通过，无输出 |
| `npm run lint` | 退出码 0，只有既有的 `react(only-export-components)` / `react(static-components)` 警告，无 error |
| `npm run build` | 通过，`✓ built in 497ms`；只有既有的 chunk 体积警告 |
| `node scripts/shootfinal.mjs` | 17 张（六页 ×2 尺寸 + 放大态 3 张 + 汽车包 2 张），退出码 0，「✓ 全部动作成功，无静默失败」 |
| `node scripts/shootextra.mjs` | 5 张，退出码 0，同上 |

截图落在 `c/shots4`（共 22 张），复现命令：

```bash
cd c/
npm run build && npx vite preview --port 4173
OUTDIR=shots4 node scripts/shootfinal.mjs
OUTDIR=shots4 node scripts/shootextra.mjs
```

## 本轮未处理

- 测试报告页网格卡片的底部渐隐（见第 2 条末），文件归属 `src/features/flow-report/panel.tsx`，
  不在本轮可改文件清单内；实测该处已有 mask 渐隐，不是硬切。
- `.bak-src-0849/` 是本轮的源码备份，留在工程根下会被 ESLint 一并扫到（只出既有警告，
  不影响退出码）。确认无需回滚后可直接删除。

## 一条给复核者的提示：截图差分里混着另一会话的改动

`shots4/` 与 `03-截图/` 下 v3.0 交付批逐像素比对的结果如下，其中流程 3（启动测试）与
流程 4（调优运行）的差异**不是本轮造成的**——本轮一行未碰 `src/features/flow-run/**`
与 `src/features/flow-tune/**`，那两页的变化来自同期另一会话正在改的那批文件，
本轮构建时一并被打进产物。

| 截图 | 与 v3.0 的画面差异 | 归因 |
| --- | --- | --- |
| `final-report.png` | 0.0000%（完全零差异） | 报告页走网格视图，本轮未触及 |
| `final-req.png` | 0.1528% | 本轮：判定卡与知识库依据两个节点的底部渐隐 |
| `final-init.png` | 0.4906% | 本轮：台架实况与设备节点的底部渐隐 |
| `final-knowledge.png` | 1.1311% | 本轮：右栏详情的行高与底部留白 |
| `final-run.png` | 0.8327% | 另一会话改 `src/features/flow-run/**` |
| `final-tune.png` | 4.6726% | 另一会话改 `src/features/flow-tune/**` |
