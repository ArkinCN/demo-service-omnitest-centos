# 长期记忆（2026-09-29 重整压缩）

## 0. 仓库边界
- 我方交付物：`d:/Task4/平台代码-脱敏版/c/`（前端 `c/web` Vite8+React19，后端 `c/backend`）。
- 客户只读源：`api/`、`app/`=MotorDebug 桌面端、`debug-agent`=Rust 控制实现。Rust 子项目属 `app/` 线，与 `c/` 零调用。
- 设备能力在 `c/components/spike-device-mcp/`（设备桥）+ `c/components/dll-bridge/`（迁移过来的 32 位控制 exe）。

## 1. 运行环境（永久）
- **后端 ra 环境（必须纯净）**：`E:\Software_Installation\07_Programming_Languages\Miniconda3\envs\ra\python.exe`。
  锁定：fastapi 0.109 / starlette 0.35 / uvicorn 0.27 / pydantic 2.5.0 / httpx 0.26。
  起：`cd c/backend && <ra python> -m uvicorn app.main:app --host 127.0.0.1 --port 8011`。
- **设备桥 bridge 环境（独立 conda，与 ra 绝不共用）**：`E:\...\envs\bridge\python.exe`。
  py3.12.14 / mcp 2.2.0 / fastapi 0.141.1 / uvicorn 0.54 / pyvisa 1.16.2 / pyvisa-py / paramiko 5.0.0。
  ⚠️ **starlette 死结**：ra 要 starlette<0.36，bridge 的 mcp 要 starlette>=0.48，零交集 → 必须两个环境。
- **Rust/MSVC（编译 32 位 dll-bridge）**：`vcvarsall.bat x86 && cargo build --target i686-pc-windows-msvc --release`；
  MSVC 14.44 在 `E:\Software_Installation\CppTools`。mingw 处理不了中文路径（MSVC 没事）。
- **隔离 venv**：`c/kb-pipeline/.venv/Scripts/python.exe`（docling/torch/lancedb，重依赖走子进程调它）。
- 前端 `react-router` v7；`VITE_AGENT_BACKEND`（mock/dsh）改后**必须重启 vite**。`AUTH_DISABLED=true`。
- Playwright 在 `c/web/node_modules`；vite 只绑 IPv6 → 用 `http://[::1]:5173`。

## 2. 前后端契约
- 前端调无 `/v1` 的 `/api/agent/stream`、`/api/kb/*`、`/api/runs*`；后端兼容层挂 `/api`。`vite.config.ts` 代理 `/api`→8011。
- 助手：`VITE_AGENT_BACKEND=dsh` → dshAdapter → `/api/agent/stream` → DeepSeek。`copilot/backend.ts` 的 `USE_DSH` 流程页+知识库页共用。

## 3. 知识库
- 五阶段流水线 `services/kb_convert_service.py`（子进程调 docling）。条目复用 `kb_entries`，`entry_key` 带前缀（场景包 `<scene_id>:<id>` / 上传 `<doc_id>#<chunk_id>`）。
- 向量检索 LanceDB，`hashing` 默认档；换档必重建索引（`scripts/build_kb_vector_index.py`）。
- ⚠️ **客户原始 PDF 从未进本机**；真有抽取稿在 `c/data/kb/documents/<doc_id>/content.md`（13 份），前端未发布、只能后端读回。`MAX_FIGURES=20` 截断。
- 端点：`GET /api/kb/documents/{id}/run`(=POST run 推进/重跑)、`/download`、`/content-by-title`、`/export`（全量 zip）。
- 已完成：源文件查看/下载、合成图文稿弹窗、助手可拖高+四按钮接真 LLM、导出整包 zip、上传模板替换报告。
- **4-AF（2026-09-29）**：顶栏「重跑流水线」空壳 → 补 `onClick={()=>nav('/run')}` **跳转阶段3启动测试**（用户口径），非就地重跑。
- **4-AG（2026-09-29）**：知识库页三整改——①「点此取消」→ `markKbSeenBatch` 整批标记已看（顶部「N 条新增」随之消失+持久化）；② 状态全持久化（kbFilter/kbSelectedId/collapse/page/scopeNew）；③「N 条」旁加「返回」→ **回知识库首页**（重置三轴筛选+只看新增+页码，留在 /knowledge；**不是**跳 /init，初版理解错了已更正）。
  - **持久化键**：`omnitest.kbSeen.v1` / `kb.filter.v1` / `kb.selected.v1` / `kb.page.v1` / `kb.scopeNew.v1` / `collapse.v1`。
  - **左栏展开态复用 `storeKey`**（Collapsible 早有 `storeKey→s.collapse`），**未改组件**；`setCollapse` 本次才加持久化。
  - ⚠️ `selectProduct` 换产品清 kbSeen/kbFilter/kbSelectedId（**内存与 localStorage 必须成对**；kbSeen 曾漏写盘）；**不清 collapse**（视图偏好跨产品保留）。

## 4. 五条业务链路 + 判定（已全通且判定为真）
- 1→2 / 2→3 / 3→4 / 4→3 / 4→5 五条已修通（4-AB~4-AE + 壳层读回）。
- **判定已真修**：采纳值经 `control_overrides` 真流回 `evaluateAll`；`target_rpm` 特例（speed_mode=NONEMODE→回落 nonemode_speed）；流程3 真采转速（collectRunMeasures 调桥 read_fg）。旧「判定是假的」结论已过时。
- 通用规律：异步读回不覆盖同步写入；从产物反推状态须尊重本地否定；验收只查落库=假绿（须加消费端断言）。

## 5. 设备桥 / 真机现状（2026-09-29）
- **动作层 6 工具已真下发**（原全是占位）：start→free-run、stop/estop→break-run（真调 dll-bridge.exe，`executed:true`）；write_param 如实标现场层（FTGeneralUtils.dll 无写单参数函数，需烧录链）；export/archive 指向报告/知识库。
- **dll-bridge 已迁移+自编译**：`c/components/dll-bridge/target/i686-pc-windows-msvc/release/dll-bridge.exe`；DLL 在 `resources/`。
- **观测层本机直连已通**：`BENCH_BACKEND=local` → LocalVisaBackend(pyvisa-py `@py`)。
- **示波器已真连**：VISA_RESOURCE=`USB0::6833::1230::DS1ZC271600575::0::INSTR`（已填 `.env`）。
  ⚠️ pyusb 找不到 conda 的 libusb-1.0.dll → `config.py` 顶部把 `<sys.prefix>/Library/bin` 加进 PATH 修复（永久坑）。
- **前端 VITE_BRIDGE_TOKEN 必须填**（与桥 .env 同值），否则网页静默断连；红线条 PIN 禁止进 VITE_*。
- **E2E 10/10 全通**（网页→后端→桥→示波器）。电机未插时 read_fg 如实 `motor_spinning=false`。
- 启动：仓库根 `start-all.bat`（三进程各用各的解释器）。
- **现场层待做**：电机板插上+HID/SWD连本机→free-run 转起来才有真转速；客户报告模板 `.xlsm` 待甲方提供。

## 6. 前端 UI 约定与坑
- **助手上下文包 lastRun 已接真轮次（4-AI，2026-09-29）**：`flow-run/api.ts` 的 `loadLatestRun(sceneId, requiredMeasures)`
  读回真轮次（verdict-table/run-artifact/gap-list）；`context.ts` 的 `buildEnvelope` 用它填 lastRun（无则 null）；
  `ActionDock.tsx` 在 `useEffect([sceneId])` 读回并作**新入参**传入（保持 buildEnvelope 纯同步，运行时唯一调用点就是 ActionDock）。
  `missing_measures` = 声明所需 − 真采到；没跑过一轮 → null（依赖 `/lastRun/*` 的助手按钮据此如实置灰）。
  遗留：`history`（多轮对比）仍 null。⚠️ `heldEnv` 是模块级变量，脚本读它须走 `window.__heldEnv`（vite 双实例坑）。
- **确认/锁定类动作全站只留一个入口**：左栏页脚 `ConfirmFooter` → `confirmAndSnapshot`（唯一落库入口，存三类参数+锁定）。
  顶栏的「提交并锁定」（4-AH 移除，2026-09-29）、「确认需求基线」（2026-09-28 移除）都已删。
  ⚠️ 2026-10-09 又**隐藏**了流程 1 的三颗未实现动作（autofill/save-tpl/validate，均无 `flowActions` 绑定、属服务端能力）→ `data/flows.ts` 的 `init.actions` 现为 **空数组 `[]`**（流程 1 顶栏动作条不再有按钮）。改法=直接从数据源删（按钮不进 DOM，既不显示也不会被点），**不是**在 TopBar 里加过滤。
  同日同口径隐藏了流程 2 的三颗（`import-std`/`edit-wf`/`save-tpl`）→ `req.actions` 亦为 **空数组 `[]`**。至此 `save-tpl` 不再被任何流程使用。
  顶栏按钮改/删**优先动 `data/flows.ts` 的 actions 数组**（TopBar 按它渲染），别改 TopBar 共用逻辑。
  ⚠️ `ACTION_ICON` 里的 `save-tpl`/`autofill`/`validate` 已是孤儿键，保留无害（多余键不参与渲染）。
- **勾选/全选按钮的图标口径（2026-10-09 用户明确）**：图标反映**当前选择状态**（全选=打勾✓ `CheckSquare`、非全选/全不选=空格子☐ `Square`），**不是**「点下去会做什么」；动作语义交给 tooltip/aria-label。
  ⚠️ 流程 2 左栏「测试要求」头部那颗原本写反了（`all ? Square : CheckSquare`），已修为 `all ? CheckSquare : Square`（`features/flow-req/panel.tsx`）。
- **自动化运行台中栏可拖分隔条（2026-10-09）**：`features/automation/AutomationConsole.tsx` 中栏改「实时趋势 / 分隔条 / 执行日志」三行栅格
  （`minmax(220px,(1-r)fr) 20px minmax(140px,rfr)`，**`gap:0`**——行间距全由 20px 条承担，同时留 gap 会多出空档）。
  `r` = **日志区占比**，`DEFAULT_LOG_RATIO=0.45`（趋势 55% / 日志 45%），双击复位回 0.45；键 `automation-console-split-ratio`。
  `clampLogRatio(r, containerH)` 必须在**实测容器高**（`ResizeObserver` 维护 `splitH`）下夹取，只用静态兜底 `[0.18,0.82]` 会在 1280×720 溢出。
  `ArrowUp` = 日志变大（步进 0.02 / Shift 0.05）；拖动绑 **window** 的 pointermove/up；卸载 cleanup 要 `removeProperty('cursor'/'user-select')`。
  视觉/键位/aria 与 `FlowScreen.tsx` 分隔条**逐字同源**（常显 grip）。新增 `data-testid="auto-console-splitter"`；`auto-console-stop`、`data-phase` 契约保留。
- **运行台趋势卡 = /run 同一套（2026-10-09）**：抽 `features/fan-trend/FanTrendView.tsx` 为**受控展示卡**（工具行 + `trend-latest-readouts` 四通道读数行 + 趋势/波形切换 + 回到全程 + 波形通道开关 + 未采集清单），`FanTrendPanel` 瘦身为 `/run` 容器（只留 `useFanTrend` 与启停/`settleRun` 副作用），`AutomationConsole` 中栏用它替换裸 `FanTrendChart`。
  ⚠️ **View 必须零副作用**：绝不能把 `beginNow/stopNow/settleRun` 带进去——运行台由编排器驱动同一台设备，抢锁会 409（`runAndCollect` 里 `if (plan.simulation) throw` 直接拒绝 sim，故运行台只能在真机下跑完整轮）。View 唯一网络行为是 `useWaveforms` 的只读 GET。`chartMinH` prop：/run 默认 260，运行台传 140（趋势行下限只有 220px）。
- **样本归一唯一实现（2026-10-09）**：`features/fan-trend/samples.ts` 的 `mergeSamples(prev, incoming)` = 按 `sequence` 去重 + 按 `t_s` 排序（null 视作 0，不丢点）。三处共用：`useFanTrend.poll`、`useAppStore.runAndCollect` 采集循环（`samples` 须 `let`）、`AUTOMATION_LIVE` 写 store 前兜底。**禁止再写第二份合并逻辑**。
- **自动化「完成弹窗」（2026-10-09 定稿，核心约定）**：跑完的结果**不再是整屏结果页**，而是浮在运行台之上的**居中模态弹窗**（`AutomationResult`，`absolute inset-0 z-[60]` 遮罩 + `max-w-[760px]` 卡片，非 portal）。
  - `AutomationRunOverlay` 的 `phase` **只由 `runStatus`+`intent` 派生**：`isFinal ? 'result' : running ? 'running' : intent ? 'intro' : null`；`dismissed` **只控制弹窗显隐**，不再让整层卸载。
  - **running 与 result 是同一渲染分支**（HeaderBar + `AutomationConsole` 常驻），避免 running→result 重挂载丢图表/滚动/分隔条；仅当 `result && !dismissed` 时**叠加**弹窗。
  - ⚠️⚠️ **`dismissResult()` 里绝不能调 `clearAutomation()`**：它把 `automationRunStatus` 复位成 `idle` → `phase` 变 null → **整层 overlay 卸载**（症状＝点关闭直接退出全屏回归、数据全丢，正是要修的问题换个触发点复现）。**「收起弹窗」只 `setDismissed(true)`；「退出回归」才 `setAutomationIntent(false)+clearAutomation()`**。
  - 交互：弹窗「关闭」/Esc/点遮罩空白 = 收起（停留运行台，本轮数据保留）；`auto-console-show-result`（终态状态条内）= 重开弹窗（**只开弹窗不触发执行**）；`auto-result-retry` = 回引导屏；「查看报告」= 跳 `/report` 并退出；右上 ✕（aria/title=「退出自动化测试」，`automation-close`）= 退出全屏。
  - `AutomationConsole` 新增 `terminalStatus?`/`onShowResult?`：终态**隐藏「终止」**（对已终态 stop 是空操作，留着是假按钮）原位换「查看执行结果」；状态条改「本轮已结束（已完成/失败/已终止）· 末阶段：…」；终态不显示「本阶段已用时」；`TrendPill` 不再显示「待命」且点不呼吸。
  - testid：新增 `auto-result-dialog`/`auto-result-mask`/`auto-console-show-result`；`auto-result-close` 语义=收起弹窗；`auto-console-stop` **仅运行态存在**。
  - ⚠️ **弹窗内关闭入口只留底部那一个**（2026-10-09 用户要求「删除右上角的关闭，多余了」；原右上角 ✕ 与底部「关闭」同调 `onDismiss`，属重复入口）。
  - ⚠️⚠️ **弹窗统计必须优先取持久化切片 `summary.metrics`，实时判定表只作兜底**（2026-10-09 修）：`verdicts` 是 `AutomationLiveState` 的**实时**切片、**不持久化**，刷新恢复后为空 → `buildVerdictViews` 给 `total=null` → 徽章与「判定通过比」双双显示「—」（明明判了 20 条却像没测）。正确写法：`metrics.total > 0 ? metrics 五项 : liveVerdictStats`。**凡终态/刷新后要显示的统计一律以持久化切片为准**——与「dismissed 不能清运行态」同源：没分清「实时态」与「落库态」。
- **后端游标契约（2026-10-09 修）**：`samples()` 的 `next_after_sequence` **必须** = 「已交付样本的最大 `sequence`」，**不能**用 `st.next_sequence`。RealFanExecutor 的样本 `sequence` 取自 **events.jsonl 事件序号**（`_drain_events` 的 `"sequence": seq`，如 3/7/11…），而 `next_sequence` 是样本计数器 → 不同源时客户端拿计数器当游标会**重复回带**（趋势图重复画斜坡、「已采 N 条」虚高）。SimFanExecutor 两者同源（1,2,3…），故 **sim 永远复现不出此 bug**，只在真机暴露。
- `PanelHeader`(Card.tsx)、`Badge.tsx` 改=改全站。
- flex 行中文标题须 `shrink-0`+`whitespace-nowrap`；`truncate` 需 `min-w-0`；`cn()` 朴素拼接不消解冲突。
- 「同一语义全站同钥匙」：占位判据按 `paramKey('flow','pa'|'cp',group,key)`+touched。
- button 不能嵌套 button（安全闸门标题行已改 div）。

## 7. 关键教训（永久）
- 「界面正常」≠「功能正常」；禁止静默吞异常。
- `tsc --noEmit` 绿 ≠ 能构建（改完一律 `npm run build`）；单元测绿 ≠ 链路通。
- 验证脚本 `check()` 必须 `return cond`；`delete_file` 常假成功→删后 `del /f /q`+`if exist` 复核。
- React `useRef` 守卫遇 StrictMode 失效→只在成功后记账；`alive` 中断 StrictMode 丢结果→幂等回填不查 alive。
- zustand 相关字段可能只写一个（`applyAdopt` 曾漏 `adoptedKeys`）→改 action 前先查界面读哪个字段。
- Hooks 不能写在提前 `return` 之后（铁律）。
- vite HMR 卡死/不加载（已第 3 次）→**排查顺序先重启 vite 再怀疑代码**。改 `.env` 也必须重启 vite。
- 8011 有监听但 `/health` 超时 = 进程卡死。
- **验证「终态 UI」不要真跑一轮**（2026-10-09）：后端 sim 时 `useAppStore.runAndCollect` 对
  `plan.simulation` 直接 `throw` 拒绝 → run 阶段**永远轮询不落地终态**（实测等 180s 超时）。
  正确做法：用 store 真切片 `window.__useAppStore.getState()._syncAutomation(runStatus, stages, currentId, announcement, summary)`
  把状态推到终态，形状与真跑落地完全一致（`phase` 只看 `runStatus`）；比真台架快且不碰硬件。
  ⚠️ store 里**没有** `applyAutomationState`，只有 `_syncAutomation`（首版脚本用错方法名，白白多跑一轮）。
- UI 自动化断言：**读 DOM 或用 `window.__useAppStore`**，别动态 `import()` 读 store（`?t=` 会拿另一实例）。
- `execute_command` 偶发返回上一条输出；`timeout /t` 带重定向报错→用 `ping -n N 127.0.0.1 >nul`；cmd 单行上限 960 字节。
- conda 事务有破坏性（`conda install mcp` 曾删 pydantic 核心文件/破坏 uvicorn）→**装包先想好环境隔离**。

## 8. 确认态与「一轮多产物」契约
- 一轮带多份产物（config-snapshot/requirement-baseline/run-artifact/verdict-table/gap-list…）。
- 空轮次陷阱：新产物落库先挂 store 的 `runId`（`confirmAndSnapshot` 曾漏 `setRunId`）。
- 读产物不只看最新轮（`limit=10` 往前找并返回所在轮）；写入取最新轮——**方向相反是刻意的**。
- 确认态持久化在 `localStorage` 键 `omnitest.confirmed.v1`；读回只回填参数不动确认态。

## 9. 两条真实落库链路（以此为准）
- 流程2 确认基线：`ConfirmFooter`→`useConfirmBaseline`→`persistBaseline`→`PUT /api/runs/{id}/requirement-baseline`→`confirmFlow('req')`→`nav('/run')`。
- 流程5 采纳：`[role=checkbox][aria-label="采纳 <参数名>"]`→「确认采纳 ·N 项」→红线卡(`data-testid="redline-approve"`)→`persistAdoption`→`PUT /api/runs/{id}/param-change`（body 包 `{content:{...}}`）。**卡上再点一次才真落库**。

## 10. 数字口径与事实标记（用户定稿）
- 数字以左栏菜单为准；助手「出处」=左栏完整层级路径（`group_tiers` 段，复用 `buildTiers`）。
- 「待现场确认」计数按「人是否填过」算（订阅 `touched`，用 `obj[key]` 判存在）。
- 「事实标记」与「确认状态」分开：`_placeholder` 不因确认消失，只改措辞。
- 占位字段可编辑性**只看场景包 `editable`**；空值不落 0，`Stepper` value 为 `number|null`。

## 11. 全量审查工具集（`c/backend/scripts/`）
`audit_api_contract.py`/`audit_enum_contract.py`/`audit_code_quality.py`/`audit_auth_coverage.py`（`OWN_MODULES` 是硬编码白名单，新路由须加）/`verify_run_persist.py`/`e2e_verify.py`/`verify_stage2.py`/`verify_kb_*.py`/`verify_report_pipeline.py` 等。
- `--strict` 套路：脚本内 `settings.AUTH_DISABLED=False`（只改本进程）+`TestClient(app)`（不套 `with`）。
- 改协议/枚举/新增路由后，先跑对应脚本。

## 12. 七阶段与模型分工（用户指定）
1 三路准备(flash✅) / 2 接通保存(flash✅) / 3 接资料和助手(pro✅) / 4 模拟完整流程(flash✅) / 5 接真实设备(pro，**进行中，代码层已收口**) / 6 补齐验收(flash，待做：36任务/58按钮/106验收逐项回填) / 7 部署交接(flash，待做)。
- 每阶段按主文档第四章六项格式回信，末尾附「>>> 阶段 N 完成…请切换模型为 …」。一次只交一个阶段。

## 13. 设备/真机关键事实
- 控机地址写死两处：前端 `features/remote/device.ts`（`VITE_BENCH_HOST`，编译期）；桥 `config.py`（`BENCH_HOST`）。
- ⚠️ 旧 `_degrade()` 静默降级（连不上返回 mock）→**排查第一步永远先看 `mode`**；本机直连模式已改为如实报错不降级。
- `capture_scope` 从未真跑过（真抓 20-25 秒/~100MB/独占示波器）。
- SSH 在 Windows Session 0 点不了 Session 1 的 GUI → 电机未转时只有哨兵值 `9.9E37`。

## 14. 用户工作偏好（必须遵守）
- **书面版操作记录写在仓库根 `操作.md`**：什么问题→在哪干了什么→达成什么结果，可直接复制提交；每轮改完立即补。
- **周报/汇报**：领导喜欢**表格量化**，数字必须可复核不能编；**不学生气**（用阶段/交付/验收/风险/协调口径）；**不啰嗦**；明确区分「已完成」与「待启动」。
- **本会话 AI 有 execute_command**（可 taskkill 清端口、后台起服务、`npm run build`、跑验证脚本、浏览器验证）；能自己取证据不要再让用户跑。
- 结论先行，如实标注「未做/未验证」边界；回答给「原因→经过→结果」书面形式。

## 15. 环境坑（本机）
- 8011 常被多个旧 uvicorn 占用：`netstat -ano | findstr ":8011" | findstr LISTENING` + `taskkill /PID <pid> /F`。
- **Playwright 访问（2026-10-09 更正）**：vite 用 `http://127.0.0.1:5173`（HTTP 直连正常）；本机 chromium 在 `chromium-1247`（**1243 已不存在**）。
  `playwright-cli` 默认读 `./playwright-cli.json`（`--config` 只对 `open` 生效，`eval` 不认）；也可直接用仓库内 `web/node_modules/playwright`。
  ⚠️ **sim 一轮仅 3~5s**：`click` 与 `evaluate` 拆成两条命令必错过运行态 → 用单脚本串起 `click + waitForSelector + evaluate`；
  进运行台前先 `page.reload()`（store 的 `automationIntent/runStatus` 跨路由保留，不清会点到被结果浮层盖住的「自动化测试」按钮，报 pointer-events intercepted）。
- 客户 `api/` 红线：`credits_service.py` 的 `CREDIT_UNIT=1_000_000`、`TRIAL_DAILY_CREDITS=500` **保持原值**。
- 客户代码里 `EXP-001…018` 两包完全重号（条目 key 必须带前缀）。
