# A｜开源工具与 DSH 插件生态调研

**调研日期**：2026-09-19
**面向项目**：通用 Agent 测试系统 v2.0（浏览器端、多场景：电机 / 汽车 / 芯片 / 其他可运动产品）
**需求来源**：`docs/20260919-通用Agent测试系统v2.0/00-用户需求原话-20260919.md`

**取证口径**：全部 star 数、版本号、最近更新时间、许可证均于 2026-09-19 当日通过 `gh api repos/OWNER/REPO`、`npm view`、PyPI JSON API、bundlephobia API 实测读取，或直接下载包体本地 gzip 实测。**不使用模型记忆估算**。查不到的字段一律标注"待核实"，不填近似值。星标数在调研窗口内存在分钟级微增，属正常波动。

---

## 零、先读：三条影响架构选型的前置结论

在进入六类选型之前，有三条实测结论会直接改变开发方案，先行列出。

### 0.1 DSH 本体确实存在且在高速迭代

| 项 | 实测值 |
|---|---|
| 仓库全名 | deepseek-ai/deepseek-harness |
| 仓库 URL | https://github.com/deepseek-ai/deepseek-harness |
| Star | 229,258 |
| 最近 push | 2026-09-17 |
| License | MIT |
| npm 主包 | `@deepseek-ai/dsh` v0.1.5-rc.2（2026-09-17 发布） |
| 底层框架 | Cordis，论文 *A Programming Paradigm for Spatiotemporal Composability*，https://arxiv.org/abs/2608.25512 |
| 成熟度 | 官方自述 developer preview，明确预告会有破坏性变更 |

### 0.2 自定义 UI 卡片不在 presentCall / presentResult 这条路上

这是本次调研中最容易踩坑的一点。DSH 官方文档 `docs/cookbook/adding-a-tool.md` 原文写明：**内置 Web Client 并不消费 `presentCall` 与 `presentResult`**。

因此"右上面板放时序曲线卡片"的正确实现路径是：

1. 写一个 Client 插件，把自己的组件注册进 `tool.call.toolview` 这个 keyed slot。该 slot 在 `docs/subsystems/slots.md` 的 shipped hierarchy 中确实存在。
2. 注册通过 `ctx.slots.register()` 或 `ctx.slots.inject()` 完成，类型系统由 `@deepseek-ai/dsh-client-ui-slots` 提供。
3. 组件从 `ToolCallBlock` 的 arguments、content、error、metadata 自行派生 props，并在本地做校验，遇到畸形输入回退到通用行。

另有一条硬约束：`presentCall` 与 `presentResult` 必须是 args 的纯函数。官方文档要求它们不做 I/O、不读 session 状态、不取时钟与随机数，原因是这两个方法在实时流式与**会话日志回放**两种场景下都会执行。需要结果期事实的，走 `output.presentationMeta(args, value)` 投影成可回放 JSON。

### 0.3 硬件 I/O 层无现成插件，必须自建

穷举搜索 DSH 插件生态中的硬件接口能力，结果如下。

| 搜索词 | DSH 相关命中 |
|---|---|
| serial port | 0 |
| modbus | 0（仅误命中一个代码审查插件） |
| oscilloscope | 0 |
| instrument / VISA | 0 |
| hardware test | 0 |
| PLC | 0 |
| CAN bus | 0 |

结论：示波器、采集卡、串口、Modbus 这一层没有任何现成 DSH 插件可用。该层需要我们自建，推荐形态是写成标准 MCP Server，再通过官方 `@deepseek-ai/dsh-mcp-client` 桥接进 DSH。这样做的好处是该 MCP Server 同时可被其他 Agent 框架复用，不与 DSH 绑死。

---

## 一、DSH 插件生态

### 1.1 三个插件索引站（均实测可访问）

| 站点 | URL | 性质 | 规模 | 特点 |
|---|---|---|---|---|
| DSH Plugin Hub | https://dsh-plugin.org/ | 社区维护的非官方插件注册站 | 自称收录约 9,650 个开源插件，分 11 类 | 每日更新 + 人工审核 |
| dsh.pub | https://dsh.pub/ | source-backed 目录 | 分 13 类 | 同时收录内置模块与社区 bundle，安装命令 pin 到具体 commit |
| dshfind | https://dshfind.com/ | 中文学习与分享社区 | 待核实 | 编辑精选 + 每日同步 GitHub，含论文解读栏目 |

GitHub topic `dsh-plugin` 搜索返回 15,381 个仓库。需注意该 topic 已出现明显的蹭热度现象，返回结果中混入 PicGo、Reactive Resume 等与 DSH 无关的项目，不能直接按 star 排序取用。

### 1.2 插件安装机制（对需求文档中"cordis.yml 片段"的更正）

实测 `docs/user/develop/basic/publish.md` 与 `config.md` 后，需要更正一处提法：分发插件用的文件是 **`cordis.patch.yml`**，不是 `cordis.yml`。两者是不同层级的概念。

| 概念 | 文件 | 作用 |
|---|---|---|
| bundle（作者侧） | `package.json` 中声明 `dsh.bundle`，指向 `cordis.patch.yml` | 一个 npm 包贡献的配置层，回答"这个包贡献了什么" |
| profile（用户侧） | `$DSH_HOME/profiles/<name>/package.json` 中声明 `dsh.profile` | 一份可启动的组合，回答"由哪些 bundle 按什么顺序组成" |
| 本地开发 overlay | `cordis.yml` + `--patch` 参数 | 开发期临时挂载本地插件，不走安装流程 |

bundle 包的 `package.json` 最小形态：

```json
{
  "name": "dsh-fortior-scope",
  "version": "0.1.0",
  "type": "module",
  "main": "index.js",
  "files": ["index.js", "cordis.patch.yml"],
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
}
```

配套的 `cordis.patch.yml`：

```yaml
- insert:
    - id: scope
      name: dsh-fortior-scope
      config:
        host: 172.25.5.166
        sampleDepth: 1200000
```

安装与启动命令：

```bash
npx @deepseek-ai/dsh web                          # 拉起 Web UI
dsh plugin --profile <名称> add <包名或本地路径>    # 装插件，实际转发给 pnpm
dsh --profile <名称>                               # 用该 profile 启动
```

配置层的叠加顺序是：`@deepseek-ai/dsh-base` 最先，然后按 `dsh.profile.bundles` 列表顺序逐个叠加，最后叠加用户自己的 `cordis.patch.yml`。插件配置用 Schemastery 声明 schema，加载时校验并填默认值，校验失败会直接中断加载并给出可操作的报错。

### 1.3 与本项目相关的插件清单

全部经 `npm view` 实测存在。**星标数在此生态中是弱信号**：DSH 社区插件普遍为 0.x 版本、个位数 star，判断活跃度应以 npm 最近发布时间为准。

#### 知识库 / RAG / 记忆

| 包名 | 仓库 URL | 版本 | 最近更新 | Star | License | 功能 |
|---|---|---|---|---|---|---|
| `dsh-kb-rag` | https://github.com/Breeze136/dsh-kb-rag | 1.6.7 | 2026-09-14 | 11 | MIT | BM25 + 向量混合检索，cross-encoder 重排，答案带章节级与页级出处，SQLite 底座，后台增量入库带进度轮询 |
| `dsh-mnemon` | https://github.com/omdsh-dev/dsh-mnemon | 0.5.11 | 2026-09-18 | 385 | MIT | 三层记忆控制平面：持久运行时上下文、可检索项目文档、可插拔长期记忆 |
| `dsh-tiddlywiki` | https://github.com/bbqisbbq/dsh-tiddlywiki | 0.23.5 | 2026-09-18 | 2 | MIT | TiddlyWiki 5 作持久知识库，15 个 `tiddlywiki_*` 工具，含过滤检索、批量改写、git 同步与冲突解决 |
| `dsh-knowledge-base` | https://github.com/htcqp802/dsh-knowledge-base | 0.1.5 | 2026-08-16 | 5 | MIT | 通用知识库：md/txt/json/yml/docx/pdf 导入，目录化管理，FTS5 全文检索 |
| `dsh-knowledge` | 待核实 | 0.4.0 | 2026-09-16 | 待核实 | **AGPL-3.0** | Cherry Studio 风格知识库，含分块、嵌入、检索与浏览器管理面板 |
| `dsh-project-memory` | 待核实 | 0.1.0 | 2026-08-16 | 待核实 | MIT | 证据支撑、人工审批的项目记忆 |

**许可提示**：`dsh-knowledge` 是 AGPL-3.0，功能虽最贴合"带管理面板的知识库"需求，但交付给客户的商业系统引入 AGPL 组件会触发传染条款，不建议采用。

**推荐**：`dsh-kb-rag`。理由是它是唯一原生提供**页级出处溯源**的方案，而测试报告场景下"这条判据出自哪份文档哪一页"是刚需，不可省略。

#### 图表卡片渲染

| 包名 | 仓库 URL | 版本 | 最近更新 | Star | License | 功能 |
|---|---|---|---|---|---|---|
| `dsh-genui` | https://github.com/lhuans/dsh-genui | 0.2.1 | 2026-09-10 | 4 | MIT | 在回复内嵌入交互式图表、表单、计算器、仪表盘，且交互结果可回流给模型 |
| `dsh-visualize` | https://github.com/brzvsk/dsh-plugins | 0.2.1 | 2026-08-17 | 1 | MIT | `visualize_html` 工具 + 沙箱 HTML 预览卡片 |
| `dsh-chart` | 待核实（npm 无 repository 字段） | 0.5.0 | 2026-09-06 | 待核实 | MIT | 结构化数据转对话内联图表，零依赖 SVG |
| `dsh-report-html` | 待核实 | 1.8.1 | 2026-08-15 | 待核实 | MIT | 从 Markdown、表格、图表数据生成自包含交互式 HTML 报告 |

**推荐**：`dsh-genui` 作参考实现而非直接依赖。它是唯一打通"图表交互回流给模型"的插件，这正是"点击曲线异常段让模型解释"所需的机制，值得读其源码学习 slot 注册写法。但百万点级测试波形不能靠通用 GenUI 渲染，最终仍应自建基于 uPlot 的专用卡片（见第三节）。

#### SSH / 远程执行

| 方案 | 仓库 URL | 版本 | 最近更新 | Star | License | 功能 |
|---|---|---|---|---|---|---|
| DSH 官方 SSH 族 `dsh-ssh` | https://github.com/deepseek-ai/deepseek-harness（packages/ssh） | 随主包 | 2026-09-17 | 随主包 | MIT | 把 filesystem、subprocess、sandbox 三套 API 整体重定向到远程机，不引入任何 SSH 专用模型工具 |
| `dsh-ssh-ops` | https://github.com/caoyiwei850/dsh-ssh-ops | 0.3.11 | 2026-09-18 | 20 | MIT | Web UI 内的 SSH 终端、SFTP、隧道，外加数据库连接；host 侧用 ssh2 管会话，client 侧渲染终端 |
| `dsh-remote` | 待核实 | 0.8.21 | 2026-09-18 | 待核实 | MIT | 20 个 `rw_*` 远程工具，支持密码 / 密钥 / agent / 键盘交互 / 跳板机 |

官方 `dsh-ssh` 的设计要点：Harness 本体、模型传输与会话存储都留在本机，只有文件系统与进程世界搬到远端。管理类 RPC 走 SSH exec 流，标准输入输出与终端输出走各自独立鉴权的转发 Unix socket，各有独立的 SSH channel window，因此远端程序刷屏不会阻塞控制通道。

**推荐**：**官方 `dsh-ssh` 负责 Agent 侧远程执行，`dsh-ssh-ops` 负责人看的终端界面**，两者分工不冲突。这正好对应需求中"示波器这类必须单机的，SSH 过去"：Agent 自动取数走官方族，工程师手工排查走 `dsh-ssh-ops` 的终端卡片。

#### MCP 桥接

| 包名 | 版本 | 最近更新 | License | 功能 |
|---|---|---|---|---|
| `@deepseek-ai/dsh-mcp-client` | 0.0.1-rc.1 | 2026-09-17 | BSD-3-Clause | 连接 MCP server，把其工具注册到 `ctx.tools` |
| `dsh-tui-mcp-manager` | 0.1.3 | 2026-09-13 | MIT | TUI 下的全屏 MCP 管理器 |

官方 MCP 客户端的机制要点：每个 server 配一个 `@deepseek-ai/dsh-mcp-client` 条目，放在目标 Cordis scope 内；它不发布共享的 `ctx.mcp` 服务，而是作为工具注册表的消费者存在；`serverName` 在其注册 scope 内唯一，公开工具名会带上 server 名前缀，因此不同 server 的同名工具不会撞车。

**推荐**：`@deepseek-ai/dsh-mcp-client`，官方出品无替代。这是我们自建示波器 / 台架 MCP Server 的接入点。

#### 工作流编排

| 方案 | 仓库 URL | 版本 | 最近更新 | License | 功能 |
|---|---|---|---|---|---|
| DSH 官方 workflow 族 | https://github.com/deepseek-ai/deepseek-harness（packages/workflow） | 随主包 | 2026-09-17 | MIT | `ctx.workflowEngine`，跑模型编写的编排脚本并启动子 agent |
| `@gm-hz/dsh-dag-workflow-canvas` | https://github.com/GM-HZ/dsh-dag-workflow | 0.2.0 | 2026-08-27 | MIT | 基于 XYFlow 的 DAG 工作流可视化编辑器 |
| `dsh-automation` | https://github.com/cofy-x/dsh-automation | 0.2.0-alpha.0 | 2026-09-11 | MIT | 持久化的 Run 与 Worker 执行 |
| `dsh-tongflow` | 待核实 | 0.8.2 | 2026-09-12 | **AGPL-3.0-only** | TongFlow studio，内嵌画布 |

官方 workflow 引擎有一条重要约束：一个 context 只允许一个引擎实现，没有具名 provider 注册表，第二个引擎是替换而非并存。`meta` 与 `args` 是纯 JSON 数据，引擎在任何脚本文本求值之前先按 schema 校验并大声失败。

**推荐**：官方 workflow 族做执行引擎，`@gm-hz/dsh-dag-workflow-canvas` 作前端画布的参考实现。后者用 XYFlow 实现，与第四节独立得出的 React Flow 推荐相互印证。`dsh-tongflow` 因 AGPL-3.0 排除。

#### 语音输入

| 包名 | 仓库 URL | 版本 | 最近更新 | License | 功能 |
|---|---|---|---|---|---|
| `dsh-voice-scribe` | 待核实 | 0.4.9 | 2026-09-09 | MIT | 点按或长按 Alt 说话，支持热词替换表与自定义润色提示词；默认本地离线识别（SenseVoice），零配置零 key |
| `dsh-voice-input-web` | https://github.com/CrazyGummies/dsh-voice-input | 0.1.2 | 2026-08-15 | MIT | 输入框工具行的麦克风按钮，走浏览器 Web Speech API（Chrome / Edge），零依赖 |
| `dsh-ears` | https://github.com/WizisCool/dsh-ears | 0.3.2 | 2026-09-18 | MIT | 语音输入插件 |

**推荐**：`dsh-voice-scribe`。理由是它默认走 SenseVoice 本地离线识别且带热词表，而测试场景充斥"母线电压""相电流""换向""占空比"这类术语，热词表是中文识别可用性的决定因素。`dsh-voice-input-web` 可作一周内跑通的兜底。

#### 文档解析

| 包名 | 版本 | 最近更新 | License | 功能 |
|---|---|---|---|---|
| `mineru-parse-dsh-tool` | 0.2.0 | 2026-08-14 | MIT | 注册 `parse_docs` 工具，经本地 MinerU 把 PDF/DOCX/PPTX/XLSX/TIFF/批量图片读成 Markdown |

**注意**：该插件自带 `parse.ps1`，是 PowerShell 脚本，偏 Windows 环境。我们的后端若在 Linux/WSL 上跑，建议不直接用此插件，而是按第六节的结论自建 Docling 服务。

#### Skill 市场与管理

| 包名 | 仓库 URL | 版本 | 最近更新 | Star | License | 功能 |
|---|---|---|---|---|---|---|
| `@michengai/dsh-skills-manager` | https://github.com/MichengAI/dsh-skills-manager | 0.1.53 | 2026-09-18 | 56 | Apache-2.0 | 在 DSH 中统一加载并安全管理本机 Agent Skills |
| `dsh-skill-hub` | https://github.com/cheshireez/dsh-skill-hub | 0.3.13 | 2026-09-15 | 待核实 | MIT | GUI 内浏览完整本地 skill 目录，开关 skill，查看正文，显示 frontmatter 诊断信息 |
| `dsh-skill-picker` | 待核实 | 0.5.10 | 2026-09-13 | 待核实 | MIT | 输入框旁的按钮打开可搜索 skill 列表，选中后插入 `/skill-name` 手势 |
| `@deepseek-ai/dsh-client-ui-skill` | 官方仓库 | 0.0.1-rc.1 | 2026-09-17 | 随主包 | BSD-3-Clause | Web 端 skill 引用与专用 skill 工具行 |

**推荐**：`dsh-skill-hub`。它带 frontmatter 诊断能力，而第二节将说明批量导入 Claude Code skill 时最常见的失败原因正是 frontmatter 缺 `name`，有诊断界面能省大量排查时间。

### 1.4 本节推荐一句话

DSH 插件生态在知识库、SSH、语音、Skill 管理四处已有可直接用的成熟件，但**图表渲染需自建专用卡片、硬件 I/O 完全空白**，这两处是我们必须写代码的地方。

---

## 二、Skill 积累包

### 2.1 候选全清单

按"这个仓库提供什么"分三类。

#### A 类：方法论型 Skill 积累包

| 仓库全名 | URL | Star | 最近 push | License | 功能 |
|---|---|---|---|---|---|
| obra/superpowers | https://github.com/obra/superpowers | 288,569 | 2026-09-19 | MIT | Agentic skills 框架 + 软件开发方法论，15 个流程型 skill，同时分发到 9 套 harness 插件目录 |
| mattpocock/skills | https://github.com/mattpocock/skills | 265,326 | 2026-09-18 | MIT | Matt Pocock 个人 `.agents` 目录开源版，38 个工程与生产力 skill |
| affaan-m/ECC | https://github.com/affaan-m/ECC | 262,154 | 2026-09-19 | MIT | Agent harness 性能优化系统，主目录 39 个 skill，含多语言镜像共 903 个 SKILL.md |
| anthropics/skills | https://github.com/anthropics/skills | 177,055 | 2026-09-10 | 无 LICENSE 文件 | Anthropic 官方 Agent Skills 仓库，19 个官方 skill + `spec/` + `template/` |
| DietrichGebert/ponytail | https://github.com/DietrichGebert/ponytail | 142,086 | 2026-09-14 | MIT | 让 agent 像最懒的资深工程师那样思考，主打少写代码 |
| addyosmani/agent-skills | https://github.com/addyosmani/agent-skills | 96,467 | 2026-09-18 | MIT | 25 个生产级工程 skill |
| microsoft/skills | https://github.com/microsoft/skills | 3,033 | 2026-09-18 | MIT | 微软官方，给 coding agent 用的 Skills / MCP / Custom Agents |
| jnMetaCode/superpowers-zh | https://github.com/jnMetaCode/superpowers-zh | 8,150 | 2026-09-17 | MIT | superpowers 完整汉化 + 4 个中国原创 skill |

#### B 类：聚合目录与标准

| 仓库全名 | URL | Star | 最近 push | License | 功能 |
|---|---|---|---|---|---|
| ComposioHQ/awesome-claude-skills | https://github.com/ComposioHQ/awesome-claude-skills | 75,301 | 2026-09-18 | 无 | Claude Skills 精选目录，按 10 个分类索引 |
| hesreallyhim/awesome-claude-code | https://github.com/hesreallyhim/awesome-claude-code | 54,285 | 2026-09-19 | NOASSERTION | Claude Code 全生态精选 |
| VoltAgent/awesome-openclaw-skills | https://github.com/VoltAgent/awesome-openclaw-skills | 52,656 | 2026-09-14 | MIT | 从 OpenClaw Skills Registry 筛出 5,400+ skill 并分类 |
| VoltAgent/awesome-agent-skills | https://github.com/VoltAgent/awesome-agent-skills | 34,581 | 2026-09-15 | MIT | 1000+ skill 精选，兼容多 harness |
| agentskills/agentskills | https://github.com/agentskills/agentskills | 25,506 | 2026-08-09 | Apache-2.0 | **Agent Skills 开放标准**规范仓库，规范正文在 https://agentskills.io/specification |

#### C 类：领域型 Skill 库（与测试、硬件、数据、报告直接相关）

| 仓库全名 | URL | Star | 最近 push | License | 功能 |
|---|---|---|---|---|---|
| K-Dense-AI/scientific-agent-skills | https://github.com/K-Dense-AI/scientific-agent-skills | 45,529 | 2026-09-14 | MIT | 科研 Agent Skill 库，166 个 SKILL.md，覆盖数据分析、统计、可视化、报告、实验设计 |
| earthtojake/text-to-cad | https://github.com/earthtojake/text-to-cad | 16,098 | 2026-09-19 | MIT | CAD / CAE / CAM skill 库，12 个 skill |
| google-labs-code/stitch-skills | https://github.com/google-labs-code/stitch-skills | 8,340 | 2026-08-17 | Apache-2.0 | Google Labs Agent Skills，显式遵循 Agent Skills 开放标准 |
| Arcadia-1/analog-agents | https://github.com/Arcadia-1/analog-agents | 69 | 2026-07-02 | 无 | 模拟 IC 设计 15 个 skill |
| alexex1993/mcu-skills | https://github.com/alexex1993/mcu-skills | 17 | 2026-09-16 | MIT | 19 块具体 MCU 开发板的 board-aware skill |
| luckiday/vibe-hardware | https://github.com/luckiday/vibe-hardware | 5 | 2026-09-17 | MIT | 7 个硬件全链路 skill |
| **TaewoooPark/instrument-control-skills** | https://github.com/TaewoooPark/instrument-control-skills | **0** | 2026-08-28 | MIT | **9 个实验室仪器控制 skill，VISA / SCPI / 扫描引擎 / 测量完整性** |

### 2.2 判定：用户所说的"非常火的项目"

**最可能是 obra/superpowers**（https://github.com/obra/superpowers ，288,569 star，MIT，2026-09-19 仍在 push）。

四条理由按证据强度排列。

第一，star 量级居首。在 `skills`、`agent skills`、`superpowers` 三组关键词的 star 排序中均为榜首。

第二，语义最贴合"积累包"。它不是单点 skill，而是一整套把工作方法沉淀成 skill 再复用的框架，15 个 skill 全是流程性资产，并自带 `writing-skills` 与 `using-superpowers` 这类教人继续积累的元 skill。

第三，跨 harness 分发。仓库根目录同时维护 `.claude-plugin`、`.codex-plugin`、`.cursor-plugin`、`.hermes-plugin`、`.agents` 等九套目录，说明它被当作通用资产包发行，往 DSH 搬最容易落地。

第四，有独立汉化分身。jnMetaCode/superpowers-zh 拥有 8,150 star，是中文圈热度的硬指标。

不能排除的次高可能：anthropics/skills（177,055 star，若用户指"官方那个"）、mattpocock/skills（265,326）、affaan-m/ECC（262,154）。

### 2.3 与本项目直接相关的具体 skill

#### 仪器控制（与电机 / 芯片台架重合度最高）

来自 TaewoooPark/instrument-control-skills，路径均为 `skills/<名>/SKILL.md`。

| skill 目录名 | 用途 |
|---|---|
| `visa-instrument-driver` | VISA 仪器驱动编写 |
| `scpi-precision-io` | SCPI 命令精确读写 |
| `sweep-engine-design` | 扫描引擎设计，对应变速与扫频测试 |
| `multi-instrument-lifecycle` | 多仪器会话生命周期管理 |
| `one-shot-instrument-control` | 单次触发式仪器控制 |
| `instrument-mock-testing` | 仪器 mock，无硬件时跑测试 |
| `measurement-integrity` | 测量完整性校验 |
| `fail-closed-safety` | 失效即停安全策略 |
| `atomic-data-export` | 原子化数据导出 |

这个仓库 0 star，按任何热度排序都会被淹没，但它是本次穷举中**唯一**成体系覆盖 VISA / SCPI / 扫描 / 测量完整性的 skill 包，正对"绕过软件 1200 点限制直连示波器取深存储时序"的需求。其中 `fail-closed-safety` 与需求文档第 2 条"测试保护 / 不能违背的原则"直接对应。价值在内容而非 star。

#### 测试与 QA

| 来源仓库 | skill 目录名 | 用途 |
|---|---|---|
| anthropics/skills | `webapp-testing` | 用 Playwright 测本地 Web 应用，截图、看浏览器日志，自带多服务生命周期管理脚本 |
| obra/superpowers | `test-driven-development` | TDD 流程 |
| obra/superpowers | `systematic-debugging` | 系统化调试 |
| obra/superpowers | `verification-before-completion` | 宣称完成前的强制验证 |
| addyosmani/agent-skills | `browser-testing-with-devtools` | DevTools 浏览器测试 |
| addyosmani/agent-skills | `observability-and-instrumentation` | 可观测性与埋点 |
| affaan-m/ECC | `eval-harness` / `benchmark-methodology` | 评测 harness 与基准方法论 |

#### 数据分析与时序

来自 K-Dense-AI/scientific-agent-skills。

| skill 目录名 | 用途 |
|---|---|
| `aeon` | 时序机器学习，含分类、回归、聚类、预测、异常检测、分割；对电机时序异常判别最对口 |
| `timesfm-forecasting` | TimesFM 时序预测 |
| `exploratory-data-analysis` | 探索性数据分析 |
| `statistical-analysis` / `statistical-power` | 统计分析与功效 |
| `analytical-method-validation` | 分析方法学验证，对应"判据是否可信"这类问题 |
| `uncertainty-and-units` | 不确定度与量纲 |
| `experimental-design` | 实验设计 |
| `polars` / `vaex` / `dask` | 大表与并行数据处理 |

#### 报告产出

| 来源仓库 | skill 目录名 | 用途 |
|---|---|---|
| anthropics/skills | `xlsx` | 电子表格读写、公式、图表、脏数据清洗 |
| anthropics/skills | `docx` | Word 创建编辑，含目录、页码、修订、批注 |
| anthropics/skills | `pdf` | PDF 抽取、合并拆分、表单填写、OCR |
| anthropics/skills | `skill-creator` | 造新 skill、跑 eval 测 skill 触发准确率 |
| K-Dense-AI/scientific-agent-skills | `scientific-visualization` / `matplotlib` / `plotly` | 科研级绘图 |
| 第三方（ComposioHQ 目录索引） | `pypict-claude-skill`，https://github.com/omkamal/pypict-claude-skill | 用 PICT 做成对组合测试用例设计，对应"测哪些工况组合" |

### 2.4 关键技术问题：DSH skill 格式与 Claude Code SKILL.md 的兼容性

**结论：高度兼容，但有三处必须处理的差异。**

证据来源为实测：`npm pack @deepseek-ai/dsh-skill@next` 解包读 `README.md` 与 `lib/types/index.d.ts`；GitHub 读 `packages/skill/skill-filesystem/src/index.ts` 与 `docs/subsystems/skills.md`；对照 Claude Code 官方文档 https://code.claude.com/docs/en/skills 与开放标准 https://agentskills.io/specification 。

#### frontmatter 字段对照

| 字段 | 开放标准 | Claude Code | DSH | 结论 |
|---|---|---|---|---|
| `name` | 必填，kebab-case | **可选**，缺省取目录名 | **必填**，缺失则整条跳过并告警 | 差异点一 |
| `description` | 必填 | 推荐 | 必填 | 一致 |
| `disable-model-invocation` | 无 | 可选 bool | 同名同语义 | 完全一致 |
| `user-invocable` | 无 | 可选 bool，默认 true | 同名同语义，默认 true | 完全一致 |
| bool 取值语法 | 无 | `true/false/yes/no/on/off/1/0`，大小写不敏感 | 一字不差相同 | 完全一致 |
| 何时使用提示 | 无 | `when_to_use`（下划线） | `whenToUse`（驼峰） | 差异点二 |
| `allowed-tools` / `model` / `context` / `hooks` | 无 | 支持 | 不解析，静默忽略 | 差异点三 |

DSH 对未知键静默忽略，不会因为多了 `allowed-tools` 就拒绝整个 skill。源码中只对三个旧拼写硬报错，要求改用 kebab-case 官方拼写。

#### 目录约定对照

| 项 | Claude Code | DSH |
|---|---|---|
| 单 skill 形态 | `<name>/SKILL.md`，必须是目录 | `<name>/SKILL.md` 或扁平 `<name>.md` |
| 项目级根目录 | `.claude/skills/` | `.dsh/skills/`（rank 100）、`.agents/skills/`（rank 200） |
| 用户级根目录 | `[源] .claude/skills` | `[源] .dsh/skills`（rank 400）、`[源] .agents/skills`（rank 500） |
| 自定义根目录 | `--add-dir` | `Config.customSkillDirs`（rank 300）、`bundledSkillDir`（rank 600） |
| 递归发现 | 支持嵌套 | **不支持** `**/SKILL.md` 递归，只扫根目录直接子项 |
| 热更新 | 无 | Chokidar watch，增删改名与改 frontmatter 免重启生效 |

DSH 默认**不扫** `.claude/skills/`。

#### 三条落地结论

第一，绝大多数能直接用。两边都实现了开放标准核心，`disable-model-invocation` 与 `user-invocable` 连布尔取值语法都相同。DSH 原生扫 `.agents/skills`，而 obra/superpowers、affaan-m/ECC、mattpocock/skills 恰好把资产放在 `.agents/` 下，这几家可零改动挂载。

第二，必改点 A：frontmatter 缺 `name` 的会被丢弃。批量导入前须扫一遍，给缺 `name` 的补上，值取目录名即可。

第三，必改点 B：按分类嵌套的仓库要逐个挂载。DSH 不做递归发现，`skills/engineering/tdd/SKILL.md` 这种两级结构，把 `skills/` 设成 `customSkillDirs` 是扫不到的，需把每个分类目录单独列入或先扁平化。anthropics/skills、obra/superpowers、addyosmani/agent-skills、K-Dense-AI/scientific-agent-skills 都是单层结构，不受影响。

### 2.5 本节推荐一句话

以 **obra/superpowers** 打底做流程方法论，**TaewoooPark/instrument-control-skills** 补仪器控制，**K-Dense-AI/scientific-agent-skills** 补时序分析与报告，全部放进项目的 `.agents/skills/`，composition 挂 `@deepseek-ai/dsh-skill` 与 `@deepseek-ai/dsh-skill-filesystem` 两行即可。

---

## 三、时序折线图小工具

### 3.1 对比表

| 项目全名 | 仓库 URL | Star | 最近 push | npm 版本 | License | gzip 体积 | 百万点级性能证据 | 游标 | 缩放/平移 | React 集成 |
|---|---|---|---|---|---|---|---|---|---|---|
| uPlot | https://github.com/leeoniya/uPlot | 10,499 | 2026-09-18 | `uplot` 1.6.32 / 2025-03-14 | MIT | **21.3 KB** | 官方 bench 166,650 点冷启动 34ms；第三方 ApexCharts 2026-07-20 横评中 100k 点折线 9ms、更新 2,560 次/秒，均列第一 | 原生 | zoom 原生，**pan 官方明确不内置** | 社区 `uplot-react` 1.2.4 |
| Apache ECharts | https://github.com/apache/echarts | 67,350 | 2026-09-16 | `echarts` 6.1.0 | Apache-2.0 | 359.3 KB | 冷启动 55ms；百万点数字未找到 | 原生 | 原生 dataZoom | 官方 `echarts-for-react` 3.0.6 |
| Plotly.js | https://github.com/plotly/plotly.js | 18,338 | 2026-09-17 | `plotly.js` 4.1.1 | MIT | 1,410.9 KB | 负面：冷启动 310ms，内存 104MB | 原生 | 原生 | 官方 `react-plotly.js` 4.1.0 |
| Observable Plot | https://github.com/observablehq/plot | 5,384 | 2026-09-01 | `@observablehq/plot` 0.6.17 | ISC | 125.0 KB | 未找到 | 无内置 | 无内置 | 无官方 wrapper |
| Chart.js | https://github.com/chartjs/Chart.js | 67,704 | 2026-09-14 | `chart.js` 4.5.1 | MIT | 66.8 KB | 100k 折线 33ms | crosshair 需插件 | 需 `chartjs-plugin-zoom` | 官方 `react-chartjs-2` 5.3.1 |
| TimeChart | https://github.com/huww98/TimeChart | 404 | **2024-06-10 已停更** | `timechart` 0.5.2 / **2023-08-04** | MIT | 8.1 KB | 自称交互 FPS 下点数为 uPlot 的 20 倍，但原始数字仅存于图片 | 插件 | 原生 | 无 wrapper |
| TradingView lightweight-charts | https://github.com/tradingview/lightweight-charts | 17,308 | 2026-09-18 | `lightweight-charts` 5.2.1 | Apache-2.0 | 60.1 KB | 未找到 | 原生 | 原生 | 社区 `lightweight-charts-react-components` 2.6.0 |
| ChartGPU | https://github.com/ChartGPU/ChartGPU | 3,230 | 2026-08-24 | `chartgpu` 0.3.8 | MIT | 约 200.5 KB | 仅定性描述 | 原生 | 原生 | 官方 wrapper；**纯 WebGPU 无回退** |
| dygraphs | https://github.com/danvk/dygraphs | 3,242 | 2026-07-29 | `dygraphs` 2.2.2 | 仓库 NOASSERTION / npm MIT | 36.5 KB | 负面：冷启动 90ms，内存 88MB | 需插件 | 原生 | 社区包已于 2022 停更 |
| ApexCharts | https://github.com/apexcharts/apexcharts.js | 15,158 | 2026-09-16 | `apexcharts` 7.4.0 | 仓库 NOASSERTION | 258.2 KB | 负面：冷启动 685ms，内存 175MB | 原生 | 原生 | 官方 `react-apexcharts` 2.1.1 |

### 3.2 推荐：uPlot

理由分三层。

**性能证据是全表唯一被独立第三方复核的。** uPlot 官方 benchmark 给出 166,650 点冷启动 34 毫秒；与 uPlot 无利益关系的 ApexCharts 在自家 2026-07-20 横评中，仍把 uPlot 排在 100k 点折线渲染第一（9 毫秒）与更新吞吐第一（2,560 次/秒）。竞品的评测把对手排第一，这类证据的可信度高于自证。

**体积最贴合"小工具"约束。** 21.3 KB gzip，比 Chart.js 小约 3 倍，比 Apache ECharts 小约 17 倍，比 Plotly.js 小约 66 倍。

**多通道能力原生具备。** 多 series、多 Y 轴、跨图表游标同步都是核心能力，FG1 / FG2 / PWM / 电流四通道同屏不需额外造轮子。

两个必须预先知道的缺口：uPlot 不内置拖拽平移，官方把它列为非目标，需自己接约三十行插件代码；npm 发布停在 2025-03-14，但仓库本身 2026-09-18 仍在提交，日常开发无影响，追新特性需从 GitHub 直装。

### 3.3 React 最小接入

```bash
npm install uplot uplot-react
```

```jsx
import { useMemo } from 'react';
import UplotReact from 'uplot-react';
import 'uplot/dist/uPlot.min.css';

export default function WaveformChart({ t, ch1, ch2, width = 900, height = 360 }) {
  const data = useMemo(() => [t, ch1, ch2], [t, ch1, ch2]);
  const options = useMemo(() => ({
    width, height,
    scales: { x: { time: true } },
    cursor: { drag: { x: true, y: false }, sync: { key: 'bench' } },
    series: [
      {},
      { label: 'FG1', stroke: '#2E5E45', width: 1, points: { show: false } },
      { label: 'FG2', stroke: '#A6353A', width: 1, points: { show: false } },
    ],
    plugins: [wheelZoomPlugin()],
  }), [width, height]);
  return <UplotReact options={options} data={data} />;
}

function wheelZoomPlugin({ factor = 0.75 } = {}) {
  return { hooks: { ready(u) {
    const over = u.over;
    over.addEventListener('wheel', (e) => {
      e.preventDefault();
      const { left } = over.getBoundingClientRect();
      const xVal = u.posToVal(e.clientX - left, 'x');
      const range = u.scales.x.max - u.scales.x.min;
      const nRange = e.deltaY < 0 ? range * factor : range / factor;
      const nMin = xVal - ((e.clientX - left) / over.clientWidth) * nRange;
      u.setScale('x', { min: nMin, max: nMin + nRange });
    }, { passive: false });
  }}};
}
```

---

## 四、工作流画布

### 4.1 对比表

按"React 原生 / vanilla JS / 领域专用"分三组。

**组一：React 原生**

| 项目全名 | 仓库 URL | Star | 最近 push | npm 版本 | License 结论 | gzip | 节点自定义 | 嵌套 | JSON 导出 |
|---|---|---|---|---|---|---|---|---|---|
| React Flow（xyflow） | https://github.com/xyflow/xyflow | 38,422 | 2026-09-17 | `@xyflow/react` 12.11.6 | 核心 MIT，无功能闸门 | 59.9 KB | 原生 React 组件 | 原生 `parentId` + group 节点 | 原生 `toObject()` |
| Reaflow | https://github.com/reaviz/reaflow | 2,491 | **2025-06-04** | `reaflow` 5.4.1 | Apache-2.0 | 818 KB | 原生 | 有 | 受控数组 |
| React Diagrams | https://github.com/projectstorm/react-diagrams | 9,426 | **2025-04-03** | 7.0.4 | MIT | 49.9 KB | 原生 | 无原生 subflow | `model.serialize()` |
| Flume | https://github.com/chrisjpatty/flume | 1,629 | 2026-04-12 | `flume` 1.2.0 | MIT | 约 61.8 KB | 受端口模型约束 | 无 | 原生 JSON |

**组二：Vanilla JS**

| 项目全名 | 仓库 URL | Star | 最近 push | npm 版本 | License 结论 | gzip | 嵌套 | JSON 导出 |
|---|---|---|---|---|---|---|---|---|
| Rete.js | https://github.com/retejs/rete | 12,263 | 2026-09-13 | `rete` 2.0.6 | 核心 MIT，**但分组插件 `rete-scopes-plugin` 与 `rete-structures` 是 CC-BY-NC-SA-4.0 禁商用** | 核心 3.1 KB，实际待核实 | 有，即禁商用插件 | 需自写 |
| LiteGraph.js | https://github.com/jagenjo/litegraph.js | 8,144 | **2024-08-01 已停更** | 0.7.18 | MIT | 123.3 KB | 有 Subgraph | 原生 `serialize()` |
| Drawflow | https://github.com/jerosoler/Drawflow | 6,120 | **2024-10-19 已停更** | 0.0.60 | MIT | 8.7 KB | 无嵌套 | 原生 |
| LogicFlow（滴滴） | https://github.com/didi/LogicFlow | 11,706 | 2026-07-30 | `@logicflow/core` 2.2.5 | Apache-2.0 | 99.5 KB（含 preact + mobx） | 有分组插件 | 原生 |
| AntV X6 | https://github.com/antvis/X6 | 6,707 | 2026-08-11 | `@antv/x6` 3.1.8 | MIT | 待核实 | 原生 parent/child | 原生 `toJSON()` |

**组三：领域专用**

| 项目全名 | 仓库 URL | Star | 最近 push | npm 版本 | License 结论 | 嵌套 | 导出格式 |
|---|---|---|---|---|---|---|---|
| bpmn-js | https://github.com/bpmn-io/bpmn-js | 9,660 | 2026-09-15 | 18.28.0 | MIT + **强制条件：画布上 bpmn.io 水印不得移除或遮挡** | 原生 SubProcess / Lane | BPMN 2.0 XML，非 JSON |
| Sequential Workflow Designer | https://github.com/nocode-js/sequential-workflow-designer | 1,472 | 2026-09-04 | 0.40.2 | MIT | 原生容器步骤嵌套 | 原生 JSON |

### 4.2 React Flow 许可专项核实

第一，代码协议是标准 MIT，版权方 webkid GmbH，无附加条款，`@xyflow/react` 的 npm license 字段同为 MIT。

第二，功能不分层收费。官网 Pro 页面明确写 React Flow 是开[源] MIT 软件并将永远如此，付费档卖的是示例工程、模板、issue 优先级与技术支持。子流程、自定义节点、序列化全部在开源核心内。

第三，唯一实际约束是画布默认渲染一枚指向 reactflow.dev 的角标，官方 remove-attribution 文档写明订阅 Pro 才能去除。这是协议文本之外的商业约定，不是 MIT 许可条件。

对照之下，真正的许可雷区不在 React Flow：**Rete.js 的分组嵌套能力挂在禁商用的 CC-BY-NC-SA-4.0 插件上**，而**bpmn-js 的水印移除限制写在 LICENSE 文本里是硬性条件**。两者对交付给芯片客户的商用系统都是硬伤。

### 4.3 推荐：React Flow

四点理由。许可最干净，核心 MIT 零功能闸门。维护度断层领先，38,422 star 且 2026-09-17 仍在提交，而 LiteGraph.js、Drawflow、React Diagrams、Reaflow 分别停更于 2024-08、2024-10、2025-04、2025-06。体积命中约束，59.9 KB gzip 且仅三个直接依赖。子流程与序列化原生具备，`parentId` + `extent: 'parent'` 直接支持工位展开成子步骤，`toObject()` 直接产出可存库 JSON。

另一条独立证据：DSH 生态中的 `@gm-hz/dsh-dag-workflow-canvas` 正是用 XYFlow 实现的，两条互不相干的调研路径指向同一结论。

### 4.4 React 最小接入

```bash
npm install @xyflow/react
```

```tsx
import { useCallback } from 'react';
import {
  ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Panel,
  useNodesState, useEdgesState, addEdge, useReactFlow,
  Handle, Position, type Node, type Edge, type Connection, type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

type StepData = { label: string; limit: string; status: 'pass' | 'fail' | 'idle' };

function TestStepNode({ data }: NodeProps<Node<StepData>>) {
  const color = { pass: '#2E5E45', fail: '#A6353A', idle: '#9A9A9A' }[data.status];
  return (
    <div style={{ border: `1.5px solid ${color}`, borderRadius: 6, padding: '8px 12px', background: '#fff' }}>
      <Handle type="target" position={Position.Left} />
      <div>{data.label}</div>
      <div style={{ fontSize: 12 }}>{data.limit}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { testStep: TestStepNode };
const initialNodes: Node[] = [
  { id: 'grp-1', type: 'group', position: { x: 0, y: 0 }, data: {}, style: { width: 420, height: 200 } },
  { id: 'n1', type: 'testStep', parentId: 'grp-1', extent: 'parent', position: { x: 20, y: 60 },
    data: { label: '上电自检', limit: 'Vdd 4.5~5.5V', status: 'pass' } },
];

function Canvas() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge[]>([]);
  const { toObject } = useReactFlow();
  const onConnect = useCallback((c: Connection) => setEdges((eds) => addEdge(c, eds)), [setEdges]);
  return (
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes}
      onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} fitView>
      <Background /><Controls /><MiniMap />
      <Panel position="top-right">
        <button onClick={() => console.log(JSON.stringify(toObject()))}>导出流程 JSON</button>
      </Panel>
    </ReactFlow>
  );
}

export default function TestFlowEditor() {
  return <ReactFlowProvider><Canvas /></ReactFlowProvider>;
}
```

---

## 五、前端快速出页面的设计辅助

### 5.1 UI 组件体系

按"控件从哪来"分三类。

**类 A：成套企业级组件库**

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License |
|---|---|---|---|---|---|
| Ant Design | https://github.com/ant-design/ant-design | 99,542 | 2026-09-18 | `antd` 6.6.4 | MIT |
| Mantine | https://github.com/mantinedev/mantine | 31,734 | 2026-09-18 | `@mantine/core` 9.6.1 | MIT |
| Chakra UI v3 | https://github.com/chakra-ui/chakra-ui | 40,651 | 2026-09-15 | `@chakra-ui/react` 3.37.0 | MIT |
| Arco Design（字节跳动） | https://github.com/arco-design/arco-design | 5,704 | 2026-08-24 | `@arco-design/web-react` 2.66.16 | MIT |
| TDesign React（腾讯） | https://github.com/Tencent/tdesign-react | 965 | 2026-09-17 | `tdesign-react` 1.18.3 | MIT |
| MUI Material UI | https://github.com/mui/material-ui | 99,061 | 2026-09-18 | `@mui/material` 9.4.0 | MIT |
| COSS UI（原 Origin UI） | https://github.com/cosscom/coss | 10,606 | 2026-09-16 | 待核实 | **AGPL-3.0** |

**类 B：无样式基元层**

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License |
|---|---|---|---|---|---|
| Radix UI Primitives | https://github.com/radix-ui/primitives | 19,291 | 2026-08-08 | `radix-ui` 1.6.7 | MIT |
| Ark UI | https://github.com/chakra-ui/ark | 5,395 | 2026-09-18 | `@ark-ui/react` 5.39.2 | MIT |
| Base UI | https://github.com/mui/base-ui | 10,943 | 2026-09-18 | 1.0.0-rc.0 | MIT |
| React Aria Components | https://github.com/adobe/react-spectrum | 15,878 | 2026-09-19 | `react-aria-components` 1.21.1 | Apache-2.0 |

**类 C：复制粘贴式代码分发**

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License |
|---|---|---|---|---|---|
| shadcn/ui | https://github.com/shadcn-ui/ui | 124,155 | 2026-09-17 | CLI `shadcn` 4.21.0 | MIT |
| Tailwind CSS | https://github.com/tailwindlabs/tailwindcss | 97,608 | 2026-09-08 | `tailwindcss` 4.3.3 | MIT |
| daisyUI | https://github.com/saadeghi/daisyui | 42,420 | 2026-09-18 | `daisyui` 5.7.42 | MIT |

### 5.2 硬需求控件核对

需求文档第 15 条要求知识库体系三级树，第 16 条要求"调整框，左右加减号调数值"。这两个控件是一票否决项，逐库实测官方组件清单结果如下。

| 库 | 三级树形 | 数字步进器 | 表格 | 暗色主题 |
|---|---|---|---|---|
| Ant Design | `Tree` + `TreeSelect`，递归无深度限制 | `InputNumber`，`controls` 属性可自定义加减图标 | `Table` / `ProTable` | `theme.darkAlgorithm` 内置 |
| Mantine | `Tree` + `TreeSelect`，官方明确无限嵌套 | `NumberInput`，默认自带增减按钮，`handlersRef` 可自绘 | `Table` | `MantineProvider` 内置 |
| Chakra UI v3 | 有 tree-view | 有 number-input | 有 | 基于 next-themes |
| Arco Design | 有 | 有 | 有 | `arco-theme='dark'` |
| TDesign React | 有 | 有 | 有 | 全局 theme-mode |
| HeroUI | **无**（80 余组件实测不含 tree） | 有 number-field | 有 | Tailwind 插件 |
| Radix UI Primitives | **无** | **无** | 无 | 需自建 |
| shadcn/ui | **无**（官方 73 个组件不含 Tree） | **无**（官方仅 Slider） | 有 | 需自建 ThemeProvider |

shadcn/ui 的社区补位方案实测：MrLightful/shadcn-tree-view（395 star，2025-11-20 最后更新）、BelkacemYerfa/shadcn-extension（1,330 star，2025-08-04 最后更新）、ggoggam/shadcn-treeview（23 star）。均为三位数 star 级、半年以上未更新的第三方仓库。

### 5.3 设计转代码工具

| 项目全名 | 仓库或官网 | Star | 最近 push | 版本 | License | 定位 |
|---|---|---|---|---|---|---|
| Penpot | https://github.com/penpot/penpot | 60,143 | 2026-09-18 | 2.17.2 | MPL-2.0 | 开[源] Figma 替代，出矢量设计稿，不直接出代码 |
| Excalidraw | https://github.com/excalidraw/excalidraw | 132,366 | 2026-09-18 | 0.18.1 | MIT | 手绘风白板，画流程与信息架构 |
| tldraw | https://github.com/tldraw/tldraw | 50,452 | 2026-09-18 | 5.4.2 | **自有商业许可，非 OSI 开源** | 无限画布 SDK |
| v0 by Vercel | https://v0.dev | 闭[源] | — | SDK `v0-sdk` 0.16.7 | SDK 为 Apache-2.0，服务闭源商用 | 提示词直出 React + Tailwind 代码 |

**许可提示**：tldraw 5.4.2 的 `LICENSE.md` 原文明确禁止在生产环境使用（Not to use the Software in Production Environments），商用需另购。把 tldraw SDK 打进交付给客户的系统属违规，只能当草图网站用。

### 5.4 开[源] AI 生成前端页面工具

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License | 产物 |
|---|---|---|---|---|---|---|
| screenshot-to-code | https://github.com/abi/screenshot-to-code | 79,256 | 2026-09-09 | 无 release | MIT | 截图或设计稿转 HTML/Tailwind/React/Vue |
| OpenDesign | https://github.com/nexu-io/open-design | 96,968 | 2026-09-19 | 待核实 | Apache-2.0 | 本地优先桌面端，出 HTML/PPTX/MP4 |
| Onlook | https://github.com/onlook-dev/onlook | 26,761 | 2026-08-25 | v0.2.32（2025-07-17） | Apache-2.0 | 在既有代码库上可视化编辑 |
| OpenUI | https://github.com/wandb/openui | 22,562 | 2026-09-10 | 无 release | Apache-2.0 | 描述生成 HTML，可转 React/Svelte |
| Dyad | https://github.com/dyad-sh/dyad | 21,578 | 2026-09-18 | v1.15.0 | Apache-2.0（`src/pro/` 另行授权） | 本地桌面应用生成器 |
| bolt.diy | https://github.com/stackblitz-labs/bolt.diy | 19,890 | **2026-02-07 已停滞** | v1.0.0 | MIT | 浏览器内整工程生成 |
| E2B Fragments | https://github.com/e2b-dev/fragments | 6,377 | 2026-09-19 | 待核实 | Apache-2.0 | 带沙箱执行的全栈生成 |
| open-lovable | https://github.com/firecrawl/open-lovable | 28,496 | **2025-11-19 已停滞** | 待核实 | MIT | Lovable 开源替代 |

GitHub topic `ai-ui-generator` 下仅 4 个仓库，已穷举，star 均为个位数至两位数，不具生产采用价值。

按"近一月仍 push + 有正式版本号 + 许可清晰"三条筛选，仅 Dyad、screenshot-to-code、E2B Fragments、OpenDesign 通过。

### 5.5 推荐组合：一周出 6 个页面

**Vite + React + Mantine 9.6.1 + Penpot 2.17.2 + screenshot-to-code + v0 by Vercel 救急**

选 Mantine 而非 shadcn/ui，理由是硬需求匹配而非偏好。知识库三级树用 `Tree`，参数配置加减号步进器用 `NumberInput`，两者都是官方组件、当天仍在 push、MIT 许可，不需引入 star 三位数以下的第三方仓库。shadcn/ui 官方 73 个组件里这两个恰好都缺，补位方案维护风险不适合一周工期。Mantine 暗色主题由 `MantineProvider` 内置，比 shadcn/ui 自建 ThemeProvider 省事。

工期分配：

| 天 | 任务 |
|---|---|
| 第 1 天 | 用 Penpot 排完 6 个页面的信息架构并导出截图 |
| 第 2 天 | 用 screenshot-to-code 批量转 JSX 骨架，统一换成 Mantine 组件 |
| 第 3 天 | 知识库管理页（三级树交互是真写代码处） |
| 第 4 天 | 初始化配置页（表单校验与步进器） |
| 第 5 天 | 测试需求确认 + 调优确认（结构接近，合并）；启动测试与结果分析 + 测试报告（以 Table 加图表为主，合并） |
| 第 6–7 天 | 暗色主题统一、联调、留白 |

---

## 六、其它流程配套

### 6.1 Web 端 SSH 与终端

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License |
|---|---|---|---|---|---|
| WebSSH2 | https://github.com/billchurch/webssh2 | 2,772 | 2026-08-18 | v5.2.1 | MIT |
| xterm.js | https://github.com/xtermjs/xterm.js | 21,197 | 2026-09-13 | `@xterm/xterm` 6.0.0 | MIT |
| ssh2 | https://github.com/mscdex/ssh2 | 5,821 | 2026-08-20 | `ssh2` 1.17.0 | MIT |
| Termix | https://github.com/Termix-SSH/Termix | 15,167 | 2026-09-19 | release-2.7.1 | Apache-2.0 |
| ttyd | https://github.com/tsl0922/ttyd | 12,387 | 2026-08-12 | 1.7.7（2024-03-30，两年半未发版） | MIT |
| Apache Guacamole | https://github.com/apache/guacamole-server | 3,987 | 2026-09-14 | 1.6.0 | Apache-2.0 |
| guacamole-lite | https://github.com/vadimpronin/guacamole-lite | 333 | 2026-01-11 | 1.2.0 | Apache-2.0 |

ttyd 与 GoTTY 部署最轻但二进制必须跑在示波器单机上；WebSSH2 与自建方案不要求改动目标机；Apache Guacamole 需 guacd 加 Java Servlet 加数据库多组件，对本任务超配。

**推荐**：**WebSSH2** v5.2.1。它已把 xterm.js 与 ssh2 组装成可直接跑的 Node 服务，MIT 无商用顾虑，网关模式不需要在示波器单机上装任何东西。若后续需要终端深度融进 React 布局，回退到 xterm.js + ssh2 + WebSocket 自建，两者底层依赖一致，迁移成本低。

### 6.2 文档解析转知识库

**开源自部署**

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License |
|---|---|---|---|---|---|
| Docling（IBM / LF AI & Data） | https://github.com/docling-project/docling | 66,691 | 2026-09-18 | v2.129.0 | MIT |
| MinerU（上海 AI Lab OpenDataLab） | https://github.com/opendatalab/MinerU | 80,221 | 2026-09-18 | 4.0.3 | 附加条款：月活超 1 亿或月收入超 2000 万美元需商业授权 |
| Marker（Datalab） | https://github.com/datalab-to/marker | 39,832 | 2026-09-13 | v2.0.0 | Apache-2.0（模型权重另有条款待核实） |
| Unstructured | https://github.com/Unstructured-IO/unstructured | 15,451 | 2026-09-15 | 0.27.6 | Apache-2.0 |

**商用 API**

| 产品全名 | 定价页 | 模式 |
|---|---|---|
| LlamaParse（LlamaIndex LlamaCloud） | https://www.llamaindex.ai/pricing | 积分制，1000 积分 = 1.25 美元，Free 档每月 1 万积分 |
| Reducto | https://reducto.ai/pricing | Standard 档每千页 Parse 10 美元、Extract 20 美元 |
| Unstructured Platform | https://unstructured.io/pricing | 赠 1 万页，超出 0.015 美元每页 |

**推荐**：**Docling** v2.129.0。许可最干净、发版最密、原生覆盖 PDF 与 DOCX、纯 CPU 可跑。中文扫描件与复杂表格占比高时用 MinerU 补充，其附加许可阈值对本项目不构成约束。

### 6.3 轻量向量库

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License | 部署形态 |
|---|---|---|---|---|---|---|
| LanceDB | https://github.com/lancedb/lancedb | 11,462 | 2026-09-19 | v0.39.0 | Apache-2.0 | 进程内嵌入，Node 与 Python 均无需起服务 |
| sqlite-vec | https://github.com/asg017/sqlite-vec | 8,116 | 2026-05-18 | v0.1.9 | MIT / Apache-2.0 双许可 | 进程内嵌入，README 明确支持浏览器 WASM |
| Chroma | https://github.com/chroma-core/chroma | 29,327 | 2026-09-18 | `chromadb` 1.5.9 | Apache-2.0 | Python 可嵌入，JS 侧需另起服务 |
| pgvector | https://github.com/pgvector/pgvector | 23,070 | 2026-09-10 | v0.8.6 | PostgreSQL License | 需已有 PostgreSQL |
| Qdrant | https://github.com/qdrant/qdrant | 34,667 | 2026-09-18 | v1.19.1 | Apache-2.0 | 独立服务，对本任务超配 |
| DuckDB VSS | https://github.com/duckdb/duckdb-vss | 265 | 2026-09-14 | 待核实 | MIT | README 自称 experimental |

**推荐**：**LanceDB** v0.39.0。它是唯一同时满足"Node 与 Python 双侧进程内嵌入、无独立服务、当日仍有提交、Apache-2.0"的候选。若后端只用 Python 且希望索引与数据同在一个 SQLite 文件，换 sqlite-vec，它也是唯一能把同一份扩展搬进浏览器 WASM 的方案。

### 6.4 语音输入

| 项目全名 | 仓库或文档 URL | Star | 最近 push | 版本 | License | 浏览器可行性 |
|---|---|---|---|---|---|---|
| Web Speech API | https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition | 不适用 | 不适用 | 不适用 | 不适用 | Chrome 实现走云端，离线不可用；caniuse 实测全球支持率 87.89%，**无浏览器标为完全支持**，Firefox 默认关闭 |
| sherpa-onnx（k2-fsa） | https://github.com/k2-fsa/sherpa-onnx | 14,847 | 2026-09-17 | v1.13.8 | Apache-2.0 | 官方 WASM 构建含 asr/vad/kws/tts 等 8 个目标；在线演示含中英双语流式 Zipformer/Paraformer、中英日韩粤 SenseVoice、中文多方言 TeleSpeech-ASR |
| whisper.cpp | https://github.com/ggml-org/whisper.cpp | 53,769 | 2026-09-18 | v1.9.4 | MIT | 有 whisper.wasm 示例；中文需至少 small 档 466 MiB，浏览器首载不现实 |
| Transformers.js | https://github.com/huggingface/transformers.js | 16,302 | 2026-09-18 | `@huggingface/transformers` 4.3.0 | Apache-2.0 | 支持 WebGPU（实验特性）；whisper-base int8 约 77 MB |
| Vosk-browser | https://github.com/ccoreilly/vosk-browser | 528 | **2025-12-07 近停更** | 0.0.8 | Apache-2.0 | 纯 WASM 全离线；中文小模型 42 MB，但官方标注为轻量档，词错率 17–38 |

**推荐**：**sherpa-onnx** v1.13.8。它是唯一把中文优先声学模型、浏览器 WASM 构建、可查证在线演示三件事做全的方案。可先用 Web Speech API 兜底一周内跑通，把 sherpa-onnx 作为第二阶段离线替换。在 DSH 侧则直接用 `dsh-voice-scribe`，其 SenseVoice 后端与 sherpa-onnx 同源。

### 6.5 报告生成

| 项目全名 | 仓库 URL | Star | 最近 push | 版本 | License | 适用场景 |
|---|---|---|---|---|---|---|
| docx（dolanmiu） | https://github.com/dolanmiu/docx | 5,909 | 2026-08-07 | 9.7.1 | MIT | 明确支持 Node 与浏览器，前端直出 .docx 无需后端 |
| ExcelJS | https://github.com/exceljs/exceljs | 15,480 | **2025-01-21，近 20 个月未动** | 4.4.0 | MIT | 数据表导出主力，**维护风险明确** |
| python-docx | https://github.com/python-openxml/python-docx | 5,724 | 2026-08-01 | 1.2.0 | MIT | 后端批量出报告，1.2.0 起支持 `add_comment` 写 Word 批注 |
| Quarto | https://github.com/quarto-dev/quarto-cli | 6,006 | 2026-09-18 | v1.10.18 | MIT | 基于 Pandoc，图文公式交叉引用最强，需装 CLI 加 TeX 工具链 |

**推荐**：**docx（dolanmiu/docx）9.7.1**。MIT，2026-08-07 仍有提交，唯一官方声明浏览器内可直接生成 Word 的库，与"浏览器端系统、要轻"的约束完全对齐。ExcelJS 用于原始数据附表导出，但因停更风险需薄封装隔离。Quarto 排版最强但独立工具链与一周工期冲突，留到后续正式交付排版再引入。

---

## 七、推荐技术栈一览

| 层 | 选型 | 版本 | 理由 |
|---|---|---|---|
| Agent 运行时 | DeepSeek Harness（deepseek-ai/deepseek-harness） | `@deepseek-ai/dsh` 0.1.5-rc.2 | 项目既定；MIT；一切皆插件的架构与多场景扩展诉求同构 |
| 插件配置 | bundle + profile，`cordis.patch.yml` | 随主包 | 官方唯一分发机制；Schemastery 校验保证配置错误在加载期大声失败 |
| 前端框架 | Vite + React | React 19 系 | 项目既定 |
| UI 组件库 | Mantine | `@mantine/core` 9.6.1 | 唯一官方同时提供无限嵌套 `Tree` 与带加减号 `NumberInput` 且当天仍在 push 的 MIT 库；暗色主题内置 |
| 时序图表 | uPlot | `uplot` 1.6.32 + `uplot-react` 1.2.4 | 竞品横评中 100k 点渲染与更新吞吐双第一；21.3 KB gzip 最轻；多通道与游标同步原生 |
| 工作流画布 | React Flow | `@xyflow/react` 12.11.6 | 核心 MIT 无功能闸门；子流程与 `toObject()` 原生；DSH 生态同类插件亦用 XYFlow |
| Web SSH | WebSSH2 | v5.2.1 | 已组装好的 Node 服务，MIT，网关模式不需改动示波器单机 |
| Agent 远程执行 | DSH 官方 `dsh-ssh` | 随主包 | 把 filesystem / subprocess / sandbox 整体重定向到远端，无需 SSH 专用工具 |
| 硬件 I/O | **自建 MCP Server** + `@deepseek-ai/dsh-mcp-client` 0.0.1-rc.1 | 自建 | 生态零命中，必须自写；做成 MCP 可跨框架复用 |
| 知识库 RAG | `dsh-kb-rag` | 1.6.7 | 唯一原生提供页级出处溯源，测试报告溯源刚需 |
| 文档解析 | Docling | v2.129.0 | MIT 最干净、发版最密、纯 CPU 可跑；中文扫描件补 MinerU |
| 向量库 | LanceDB | v0.39.0 | 唯一 Node 与 Python 双侧进程内嵌入且无需起服务 |
| 语音输入 | `dsh-voice-scribe` / sherpa-onnx | 0.4.9 / v1.13.8 | 本地离线 SenseVoice 加热词表，中文术语识别可用性的决定因素 |
| Skill 底座 | obra/superpowers + TaewoooPark/instrument-control-skills + K-Dense-AI/scientific-agent-skills | 见第二节 | 方法论、仪器控制、时序分析三块拼齐；放 `.agents/skills/` 零改动挂载 |
| Skill 管理 | `dsh-skill-hub` | 0.3.13 | 带 frontmatter 诊断，批量导入排错省时 |
| 报告生成 | docx（dolanmiu） | 9.7.1 | 唯一官方支持浏览器内直出 Word |
| 设计辅助 | Penpot + screenshot-to-code | 2.17.2 / 无 release | 排稿与转骨架两端；均许可清晰 |

### 明确排除项与理由

| 被排除 | 理由 |
|---|---|
| tldraw | LICENSE 原文禁止生产环境使用，商用需另购 |
| Rete.js | 分组嵌套能力挂在 CC-BY-NC-SA-4.0 禁商用插件上 |
| bpmn-js | MIT 附强制条件，bpmn.io 水印不得移除或遮挡 |
| COSS UI（原 Origin UI） | AGPL-3.0 传染条款 |
| `dsh-knowledge` / `dsh-tongflow` | AGPL-3.0 |
| shadcn/ui 作唯一组件库 | 官方 73 个组件缺 Tree 与 NumberInput，补位方案均为三位数 star 且半年以上未更新 |
| TimeChart / LiteGraph.js / Drawflow | 分别停更于 2024-06、2024-08、2024-10，与"工具要新"要求冲突 |
| bolt.diy / open-lovable / gpt-engineer / openv0 | 长期停更 |
| `mineru-parse-dsh-tool` | 自带 PowerShell 脚本，偏 Windows，与 Linux 后端不合 |

---

## 八、搜索范围与零命中

### 8.1 已覆盖的搜索范围

**DSH 生态**：WebFetch 三个索引站 dsh-plugin.org、dsh.pub、dshfind.com；`gh api` 取 deepseek-ai 组织全部 39 个仓库；`gh api` 拉取 deepseek-harness 完整仓库树共 13,854 条路径；下载并精读 8 份官方文档（`docs/user/develop/basic/config.md`、`publish.md`、`tool.md`、`docs/subsystems/skills.md`、`mcp.md`、`ssh.md`、`workflow.md`、`slots.md`、`docs/cookbook/adding-a-tool.md`）；GitHub topic `dsh-plugin` 按 11 个类别关键词分组搜索；`npm search` 按 17 个类别关键词搜索；`npm view` 逐个实测 40 余个插件包。

**Skill 生态**：`gh api search/repositories` 关键词 10 组（claude skills、agent skills、skill library agent、SKILL.md、superpowers、agent skill hardware test、claude skill oscilloscope、agent skills embedded firmware、skill SCPI instrument agent、agent skills data analysis report）；GitHub topic 6 组；`gh api search/code` 在 deepseek-harness 内查 SKILL.md（158 命中）、`.claude/skills`（2 命中）、agentsHome（18 命中）；逐仓实测 25 个候选；对 11 个仓跑 `git/trees?recursive=1` 全量枚举 SKILL.md 路径；`npm pack @deepseek-ai/dsh-skill@next` 解包读源码类型定义。

**前端库**：`gh api` 查询约 155 个仓库；`npm view` 查询约 110 个包；bundlephobia API 查询 25 个包；对 7 个包下载包体本地 gzip 实测；PyPI JSON API 查询约 20 个包；Hugging Face API 查询 4 个模型仓库的逐文件字节数；WebFetch 核实官方文档与定价页约 20 个 URL。

### 8.2 零命中项

**DSH 硬件接口**：serial port、modbus、oscilloscope、instrument/VISA、hardware test、PLC、CAN bus 七组关键词在 npm 的 DSH 插件中全部零命中。这是本次调研最重要的零命中结论，已在第 0.3 节与技术栈表中体现为"必须自建"。

**GitHub topic**：`webgl-chart` 与 `timeseries-chart` 两个 topic 下无任何仓库使用，改用 `topic:timeseries`、`topic:charting-library` 补齐。`ai-ui-generator` topic 下仅 4 个仓库，已穷举。关键词 `agent+skill+hardware+test` 在 GitHub 搜索零结果。

**不存在的仓库**：`skills-sh/skills`、`anthropic-experimental/skills`、`arco-design/arco-design-react`、`OpenSWE/open-lovable`、`Kilo-Org/kilocode`、`sshpiper/sshpiperd`、`stuartleeks/webterm` 均返回 404。

**未能证实的资源**：任务中提到的 **skills.sh 未能证实存在**。GitHub 侧无对应组织，且 WebSearch 配额耗尽无法做站点检索确认或否认。可确证的标准站是 agentskills.io，对应仓库 agentskills/agentskills（25,506 star，Apache-2.0）。此项待用户确认或补充链接。

**npm 上不存在的插件名**（出自索引站描述但 `npm view` 返回 404，可能为 GitHub 直装或已更名）：`dsh-auto-memory`、`dsh-shoucang-memory`、`dsh-timer-task`、`dsh-agent-loop-guard`、`goodandready-dsh-vision-bridge`、`dsh-openpencil`、`dsh-agent-teams`、`dsh-worktable`、`dsh-vision-toolkit`、`deepseek-design`。本报告未采信这些条目。

**性能数据缺口**：Apache ECharts、TradingView lightweight-charts、Observable Plot、FINOS Perspective、VisActor VChart 的百万点级实测数字均未找到，对比表该列为空而非填估算值。

**体积数据缺口**：`@visactor/vchart`、`@finos/perspective`、`@workflowbuilder/sdk`、`@antv/x6`（bundlephobia 因纯 ESM re-export 返回 0.4 KB 失真）、rete 生态插件叠加后的实际体积均标待核实。

**其它待核实**：`dsh-chart`、`dsh-report-html`、`dsh-knowledge`、`dsh-project-memory`、`dsh-voice-scribe`、`dsh-remote`、`dsh-skill-picker` 的 npm repository 字段缺失或仓库未定位，star 数标待核实；DuckDB VSS 无 release/tag，版本号查不到；Chunkr Cloud API 定价三次 WebFetch 均未取到数字；Mistral OCR 每千页单价未取到；dshfind.com 收录规模未给出数字。

### 8.3 方法论层面的覆盖缺口

三路子调研均报告 **WebSearch 配额在会话中途耗尽**（200 次上限），后续扩搜改用 `gh api search/repositories` 与 topic 检索替代。由此产生两处影响：其一，"2025–2026 年新出现的、无 GitHub 仓库的纯闭源产品"未能独立核实，仅能从间接引用得知存在；其二，React Flow Pro 的定价与去角标政策为官网单源，未做第三方交叉核对；其三，热度判定完全基于 GitHub star 实测值，未用网页搜索交叉验证。

另需说明：**DSH 社区插件生态整体处于早期**。绝大多数插件为 0.x 版本、个位数 star、创建于 2026 年 8 月之后。本报告在该生态内的活跃度判断以 npm 最近发布时间为主、star 为辅，与前端成熟库采用的判断标准不同，两类表格的 star 列不可横向比较。
