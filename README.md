# 多场景 Agent 测试系统（agent-test-system）

## 所有人先看：项目总开工顺序 v4.3

[总顺序与分工](docs/开发交接/v4.3-20260921/README.md) · [飞书总入口](https://hcnd3xtushu0.feishu.cn/wiki/WKchwMsK0i2QIHkFzY8c5FmNnDf)。前端、后端与现场准备同时开始，再依次完成真实保存、资料和助手、模拟全流程、实机联调、完整验收与部署。每阶段明确负责人、交付结果和下一步条件；下面的后端指南作为详细参考。

## 后端同事先看这里 · v4.2

[后端开工顺序](docs/开发交接/v4.2-20260921/README.md) · [飞书开工指南](https://hcnd3xtushu0.feishu.cn/wiki/OC2lwiqxGiblAJk3GVDchG1WnMg) · [客户代码复用清单](https://hcnd3xtushu0.feishu.cn/wiki/Jz2AwRoPSi83TDklAeccezYdnbh)。以客户已有 API、数据库、助手与报告库为起点，逐步新增测试业务并接新页面。新仓尚未迁入客户后端；不要从零重写已有能力。后端复用与数据库取舍以 v4.2 更正为准，v4.0 的完整功能与验收要求继续保留。

## 先看页面图解 v4.1

[图文入口](docs/开发交接/v4.1-20260921/README.md) · [飞书图文版](https://hcnd3xtushu0.feishu.cn/wiki/PgtDwsWGMiD61KkgS43cIHwVn0w)。按实际页面讲解知识库、五个流程和助手，含 9 张界面截图及 2 张说明图。看懂页面后再查 v4.0 的接口、任务与部署明细。

## 2026-09-21 开发接手入口

[开发交接 v4.0](docs/开发交接/v4.0-20260921/README.md) · [飞书入口](https://hcnd3xtushu0.feishu.cn/wiki/GFHPwZNQYibCrrki2JmcDwlBnzT)。包括功能、助手后端与客户代码、接口数据、36 项任务、调试部署、106 条验收及外部依赖。代码基线已同步 Gitee；新材料不表示真实后端已经完成。原 03 保留图示，旧 04 v3.2 简版改用此入口，历史版本保留。

面向电机/整车电子测试场景的 Agent 测试系统原型仓库。一套壳层承载多个可插拔场景包，
当前落地两个场景：峰岹散热风扇（电机控制芯片启动与调速测试）与汽车玻璃升降器（车身电子件耐久与防夹测试）。
仓库同时收录支撑这套原型的四个前端组件、DeepSeek Harness（DSH）插件骨架、知识库构建流水线，
以及两个场景包的完整数据与设计文档。

本仓库是**原型与骨架**，不是可交付生产系统：页面数据来自预置场景包与离线知识库快照，
设备链路（SSH 网关、示波器 VISA）有真实实现但默认指向实验台架。

## 目录

| 目录 | 内容 |
|------|------|
| `web/` | 网页原型主工程（Vite + React + TypeScript），v2 视觉版。含 `public/` 场景与知识库静态数据、`shots/` 第一版截图、`shots2/` v2 视觉版截图 |
| `components/timeseries/` | 时序波形组件，基于 uPlot 1.6.32，承载启动电流/转速曲线 |
| `components/workflow/` | 工作流画布组件，基于 @xyflow/react 12，解析客户 `.wfw` 工作流文件 |
| `components/agent-chat/` | Agent 对话组件，零运行时依赖，含人工确认闸门与依据引用 |
| `components/webssh/` | 网页 SSH 组件与 Node 网关（ssh2 + ws），连台架工控机与仪器 |
| `dsh-plugins/` | DeepSeek Harness 插件骨架：三个 MCP stub（motor / scope / report）、skill、hooks 双桥、端到端实跑记录 |
| `kb-pipeline/` | 知识库构建流水线：Docling 文档转换、BM25 索引、经验条目提炼脚本与配置 |
| `data/scenes/` | 两个场景包数据（含 assets）：峰岹散热风扇、汽车玻璃升降器 |
| `data/kb/` | 知识库产物快照：文档索引 `documents/index.json`、每篇文档的正文 `content.md`／切片 `chunks.jsonl`／实体 `entities.json`／配图 `figures/`，以及经验条目 `experience/` 与检索样例 `search-samples.json` |
| `docs/` | 需求原话、设计规格、业务逻辑、实施任务详单、交接文档，配图与调研材料 |

## 各子项目启动命令

### web —— 网页原型主工程

```bash
cd web
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build，必须零错误
npm run lint     # oxlint
```

出截图与对照图：

```bash
npm run build && npm run preview -- --port 4173
node scripts/shootfinal.mjs     # 六页 × 两尺寸 + 放大态 3 张 + 汽车包 2 张
python3 scripts/compare2.py     # 电机／汽车并排对照图
```

### components/timeseries —— 时序波形

```bash
cd components/timeseries
npm install
npm run dev
npm run build          # 产物到 dist/
python3 scripts/shoot.py   # 截图到 shots/
```

### components/workflow —— 工作流画布

```bash
cd components/workflow
npm install
npm run data       # 抽取工作流 → public/data/{workflows.json, wfw/}
npm run coverage   # 全量解析覆盖报告
npm run build
npm run shots      # 截图到 shots/
```

### components/agent-chat —— Agent 对话

```bash
cd components/agent-chat
npm install
npm run dev
npm run build      # 产物在 dist/
```

### components/webssh —— 网页 SSH 与网关

先按 `.env.example` 生成 `.env`（`GATEWAY_TOKEN` 必填，未设置时网关直接退出；
`FORTIOR_WIN_KEY` 指向私钥**文件路径**，私钥本体不入库）。

```bash
cd components/webssh
cp .env.example .env    # 填 GATEWAY_TOKEN 与私钥路径
npm install
npm run dev:all         # 同时起网关 :8022 与前端 :5173
npm run gateway         # 仅起网关（生产下需常驻）
```

### dsh-plugins —— DSH 插件骨架

```bash
cd dsh-plugins
npm install --save-exact @deepseek-ai/dsh@0.1.5-rc.2
export DEEPSEEK_API_KEY=<你的 key>   # 不写进仓库任何配置文件
```

版本必须精确锁定，不能用 caret/tilde——细节与排查方法见 `dsh-plugins/README.md` 第 2 节。
三个 MCP stub 的契约见第 5 节，端到端实跑记录见 `dsh-plugins/logs/e2e.md`。

### kb-pipeline —— 知识库流水线

```bash
cd kb-pipeline
uv venv --python 3.10 .venv
uv pip install docling==2.129.0 rank_bm25 pymupdf4llm --torch-backend=cpu
bash scripts/run_all.sh                    # 全量
bash scripts/run_all.sh foc-debug-manual   # 只重转指定文档
```

首次运行 Docling 会下载一次版面与表格模型到本地缓存，之后完全离线。

## 从哪开始读

新接手请从 `docs/05-交接文档-给接手模型-v1.0.md` 开始，它交代了系统边界、已完成范围与未尽事项。
其次是 `docs/03-主文档-多场景Agent测试系统页面原型与业务逻辑-v2.1.md`（页面与业务逻辑全貌）
与 `docs/04-同事实施任务详单-v2.0.md`（分工与任务拆解）。

## 数据来源说明

- **客户原始资料不入库**。`kb-pipeline/input/`（芯片数据手册、调试规程、客户代码）与
  `kb-pipeline/work/` 中间产物均已排除，仓库只保留转换脚本、配置与说明。
- `data/kb/` 收录的是知识库**构建产物快照**（文档索引、正文、切片、实体、配图、经验条目、检索样例），
  可直接驱动原型页面的检索演示，不含客户原始文档全文之外的私密信息。
- `data/scenes/` 两个场景包中的波形与截图素材来源已在各自场景包与组件 README 中注明出处。
- `components/webssh/gateway/devices.json` 记录的是实验台架设备地址与用户名，
  私钥按 `keyRef` 指向的环境变量间接引用，密钥本体不在仓库内。

---