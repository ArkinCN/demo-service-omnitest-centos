# 第四轮接线：把「看得见点不动」的四处接上，并把设备桥接进页面

日期 2026-09-20。工程 `[源] zzz/agent-test-web`。改动前的 `src/` 快照留在
`（见交付包内备份）`。

起因是《部署、联调与演示标准作业程序 v1.0》
（`docs/20260919-通用Agent测试系统v2.0/08c-部署联调与演示SOP-v1.0.md`）
第零节列的「点不动的三处」，加上该文第 1.2 节那句「这个设备桥没有接进页面」。
四处一并接上，红线口径不动。

---

## 一、红线口径先写在前面

红线的原话：**启动、停止、急停、写回参数、导出、归档六个动作只能人点，且必须经确认；
副驾不得自动执行。** 本轮把它落成两条可核查的纪律：

1. 六个动作一律经 `useAppStore` 的 `requestRedline()` 排队，弹确认卡
   （`src/features/redline/RedlineConfirm.tsx`），人点「确认执行」才执行。没有第二条执行路径。
2. 批准函数 `approveConfirmation()`（`src/features/remote/bridge.ts`）**只有一个合法调用点**：
   store 的 `approveRedline()`，而它只由确认卡上那颗按钮触发。副驾的两个包
   （`src/features/copilot`、`src/features/agent-chat`）只能排队，调不到批准。

   > **2026-09-20 更正。** 本条在写下时与事实不符：`src/features/agent-chat/api.ts:427`
   > 的 `confirmAt()` 当时是第二个调用点，本文第 2.2 节自己也描述了它，前后自相矛盾。
   > 独立核验把它记为 P2（`07i-交互打通独立核验.md`）。修复见
   > `CHANGELOG-fix-redline-pin-20260920.md`：该调用点已改走 store 的
   > `requestRedlineAsync()`，把票排进同一张确认卡；改完之后本条才成立。

接了设备桥时走三段式，闸口在桥里不在前端：不带 `confirm_token` 调一次 → 桥拒绝执行并
签发 `pending` 凭据 → 人点确认后调 `POST /confirmations/{token}/approve` → 带同一张票、
同一组参数重调才执行。凭据的四道约束（单次使用、180 秒过期、绑工具名、绑参数指纹）
只在桥里实现一次。依据：`[源] spike-device-mcp/README.md` 第 3 节，以及
`08a-开发接口契约-v1.0.md` 第 3.4 节「当前的两套确认机制，收口方案」。

桥不可达时第 1、3 段跳过，只驱动页面回放，**确认卡照弹**，并在卡上写明本次不向台架
下发任何控制命令。红线不因为桥没起就松掉。

---

## 二、改动文件

新建 6 个文件，改动 12 个（与下面两张表、与 `diff -rq` 实测一致；此处原写「新建 5 个、
改动 11 个」，与自身表格矛盾，2026-09-20 改正）。行数一列是改后文件总行数，改动量一列是与改动前快照的
diff 行数（增删合计）。

### 2.1 新建

| 文件 | 行数 | 做什么 |
| --- | --- | --- |
| `src/features/remote/bridge.ts` | 250 | 设备桥 HTTP 客户端：`GET /devices`、`GET /devices/{id}/status`、`POST /devices/{id}/tools/{name}`、凭据的批准与驳回，外加订阅钩子 `useBridgeDevice()`（首拉全量、之后 5 秒轮状态） |
| `src/features/redline/flowActions.ts` | 295 | 动作行为表。`useRedlineGate()` 负责三段式取票，`useFlowActions()` 按动作 id 给出 `{onClick, disabled, reason}` |
| `src/features/redline/RedlineConfirm.tsx` | 102 | 红线确认卡。摆动作全名、物理后果、参数指纹、凭据串与四道约束的说明 |
| `src/features/redline/index.ts` | 3 | 出口 |
| `scripts/walk-wire.mjs` | 207 | Playwright 主线走查脚本，12 步，截图落 `shots5/` |
| `.env.example` | 23 | 全部 `VITE_` 变量清单，含设备桥 CORS 那个坑的说明 |

### 2.2 改动

| 文件 | 行数 | 改动量 | 改了什么 |
| --- | --- | --- | --- |
| `src/state/useAppStore.ts` | 454 | 221 | 新增闸门勾选、本轮运行状态机、红线排队与批准、采纳候选、判据跳转焦点、一句话提示六组状态；`selectProduct()` 换包时一并清空 |
| `src/app/ToolRail.tsx` | 394 | 168 | 工具条下半截新增 `BridgeRail`：按桥返回的三层分组渲染工具，动作层描边走暗红且点下去只取凭据；桥不通时显示一枚离线占位 |
| `src/features/flow-run/panel.tsx` | 966 | 145 | 闸门状态从模块级私有变量搬进 store；`ConfirmFooter` 接「启动测试」同一条动作；判定卡加运行中态，未达标行做成可点按钮跳流程 4；执行进度卡加本轮运行态 |
| `src/features/remote/DeviceMcpNode.tsx` | 154 | 102 | 节点体与放大态改读设备桥。节点三行事实改成工具 / 模式 / 网关；地址退进 tooltip（节点高 168 只放得下三行，第四行会被裁掉半截） |
| `src/features/agent-chat/api.ts` | 472 | 64 | 修 `api.ts:382` 确认弹窗丢 `name` / `argsSummary`：改成从已收到的那条 `tool_call` 事件里取；放行回执补 `actor` 与 `confirm_token`；人点确认后先批准桥的凭据再发回执，批不动就按取消处理，不谎报放行 |
| `src/app/TopBar.tsx` | 260 | 38 | 动作条按钮挂 `onClick`，置灰与理由现算；动作条右端那行字改报本轮运行态，且只在流程 3 报 |
| `src/features/flow-tune/panel.tsx` | 1128 | 58 | 采纳勾选从模块级变量搬进 store；`ConfirmFooter` 接「采纳并回到启动测试」同一条动作；加一条「来自流程 3 判定卡的未达标项」横幅 |
| `src/features/flow-report/panel.tsx` | 1233 | 32 | 第 403 行 `runtimeMeasures(waves)` 改 `runtimeMeasures(waves, pack)`；「生成报告」「导出」「归档到知识库」三颗按钮接上，后两颗走红线 |
| `src/app/Shell.tsx` | 45 | 27 | 全局挂确认卡与一句话提示条 |
| `src/features/canvas/nodeKinds.tsx` | 62 | 15 | 设备节点的三色状态改按桥的 `mode` 取：live 绿、mock 中性、不可达暗红 |
| `src/features/remote/api.ts` | 34 | 11 | 补文件头：说清它现在只管 SSH 网关那条，设备桥在 `bridge.ts` |
| `src/data/flows.ts` | 106 | 10 | 「启动测试」的 `disabled: true` 硬编码删掉，改由闸门勾选数现算 |

---

## 三、四处「点不动」各自怎么接的

### 3.1 顶栏动作条

按钮的 `onClick`、置灰与置灰理由全部由 `useFlowActions()` 给。置灰不再写死在
`src/data/flows.ts` 里，而是现算：

- **启动测试**：安全闸门九条（本场景包里人员类 2 条 + 流程类 7 条）全勾才亮，
  差几条 tooltip 就写差几条；本轮正在运行时也置灰，理由是「先停止再启动」。
- **停止**：只有本轮在运行时才可点。
- **急停**：始终可点，走暗红确认卡，卡上写明软件急停只是补充手段，现场仍须有一条
  物理急停回路。
- **采纳并回到启动测试**：勾了候选才可点；确认后写回参数、标记流程 4 已确认、跳回 `/run`。
- **全部忽略 / 回滚基线 / 查看依据 / 预检自检 / 生成报告 / 预览 / 导出**：逐个接上，
  其中回滚基线与导出走红线确认卡，查看依据跳知识库，预检自检去桥上读一次真实状态。

流程 1 与流程 2 里那五颗（读取文档自动填充、另存为参数模板、校验配置、导入标准、
编辑工作流）本轮**没有接后端**，落到统一的置灰兜底，tooltip 写「该动作在当前原型里
未接后端」。这是有意为之：让它们看着可点而点了没反应，比明摆着置灰更糟。
同组里「提交并锁定」与「确认需求基线」是纯前端的确认动作，已接上。

### 3.2 左栏底部的悬浮确认按钮

流程 3 的「确认参数 · N 项」接「启动测试」同一条动作，流程 4 的「确认采纳 · N 项」接
「采纳并回到启动测试」同一条动作，流程 5 的「确认表头 · N 项」接「生成报告」。
同一条动作只有一份行为表，不会出现顶栏与左栏两种行为。

### 3.3 判定卡上的未达标行

`state === 'fail'` 的行做成按钮，行尾加一枚右向箭头，点下去把判据 id 记进
`store.focusReq` 再跳 `/tune`；流程 4 左栏顶部据此摆一条「来自流程 3 判定卡的未达标项
TR-START-01」。其余状态的行不可点——没有可跟进的结论却给点击反馈是假的。

### 3.4 流程 3 的「运行中 → 出判定」

`store.beginRun()` 把 `runPhase` 推到 `running` 并每 120 毫秒走一格，20 格走满转 `done`，
中途被停止或急停就停在那一态、不出判定。判定卡在 `running` 期间摆进度而不是摆上一轮的
结论；执行进度卡摆本轮运行态与第几轮。回放用的是场景包里已登记的那几条时序，不生成
任何新数据。

---

## 四、设备桥接进页面

### 4.1 双后端配置

原来只有一个 `VITE_GATEWAY_URL`（默认 8022，即上一轮的 webssh 网关），设备节点靠
`GET /probe/bench` 拿一个布尔量。本轮新增：

| 变量 | 默认值 | 谁在用 |
| --- | --- | --- |
| `VITE_DEVICE_BRIDGE_URL` | `http://127.0.0.1:8031` | 设备桥 |
| `VITE_BRIDGE_TOKEN` | 空 | 设备桥的 `x-bridge-token` 头 |
| `VITE_GATEWAY_URL` | `http://localhost:8022` | SSH 网关，只剩节点放大态里那个终端一个用途 |
| `VITE_GATEWAY_TOKEN` | 空 | 同上 |

清单落在 `c/.env.example`，`.env` 已加进 `.gitignore`。

### 4.2 节点与工具菜单

设备节点状态改读桥的 `GET /devices`（一次取全元信息、`live`/`mock` 模式、分层工具清单）
与 `GET /devices/{id}/status`（5 秒轮一次）。工具条下半截按桥返回的三层分组渲染，
动作层六个工具描边走暗红。

桥不可达时节点显示「网关 未连通」，tooltip 按成因分三句话：缺 `VITE_BRIDGE_TOKEN`、
桥地址不可达（附该起哪个脚本、该改哪个变量）、token 与桥的 `BRIDGE_TOKEN` 不一致。

### 4.3 踩到的两个坑

**凭据字段是平铺的，不在 `confirmation` 里。** 桥调红线工具且不带票时，返回体是
`{status, executed, reason, how_to_proceed, confirm_token, tool, state, prompt, args_preview,
created_at, expires_at, seconds_left, ...}`，凭据各字段与 `status` 同层。第一版按
`r.confirmation.token` 取，取到 `undefined`，表现是确认卡照弹但凭据栏写「本轮无设备凭据」，
不报错——差点当成桥没起。`args_preview` 也是对象不是字符串。

**桥的 CORS 默认只放行 5173 与 3080。** `bridge.py` 的 `BRIDGE_CORS_ORIGIN` 默认值是
`http://localhost:5173,http://localhost:3080`。用 `npm run preview`（4173/4199）或者用
`127.0.0.1:5173` 而不是 `localhost:5173` 打开页面，浏览器直接拦掉请求，页面上没有任何
错误提示，只会显示「未连通」。走查因此固定用 `npm run dev` 的 `http://localhost:5173`。

---

## 五、走查结果

环境：设备桥在 8031 监听且已 SSH 上台架（`mode: live`，`hostname: SK-20251218QPBB`）；
前端 `npm run dev` 于 `http://localhost:5173`；场景包 `motor.cooling-fan.fortior-fu6832`。

```bash
BASE=http://localhost:5173 node scripts/walk-wire.mjs
```

| 步 | 结果 | 实测 |
| --- | --- | --- |
| 0 设备桥节点 | PASS | 节点「网关 已连通」，工具条桥工具 13 个，离线占位 0 个 |
| 1 闸门未满 → 启动置灰 | PASS | `button[data-action="start"]` 为 disabled |
| 2 逐条勾满闸门 | PASS | 点到 9 条：SI-PROC-01～07、SI-PERSON-01、SI-PERSON-02 |
| 3 闸门全绿 → 启动变亮 | PASS | 按钮转可点，顶栏盾形徽章由「9」转「就绪」 |
| 4 弹红线确认卡 | PASS | 卡上凭据 `ct_…`，标「设备桥已签发」；提示语取自桥的 `prompt`：「启动被测电机：台架会真的转起来。红线动作，未带 confirm_token，已拒绝执行」；参数 `duty_percent=60 · duration_s=10` |
| 5 运行中 → 出判定 | PASS | 运行中读数 20%，结束后「本会话第 1 轮」，判定卡未达标 1 条 |
| 6 未达标行跳流程 4 | PASS | URL 转 `/tune`，左栏出现「来自流程 3 判定卡的未达标项 TR-START-01」 |
| 7 勾选候选 → 采纳可点 | PASS | 页面上可勾候选 6 条，勾一条后采纳按钮转可点 |
| 8 采纳走红线确认卡 | PASS | 动作 `write_param`，参数 `key=ALIGN_CURRENT · value=0.6` |
| 9 采纳后回到流程 3 | PASS | URL 转 `/run` |
| 10 生成报告 | PASS | URL 转 `/report` |
| 11 导出走红线确认卡 | PASS | 动作 `export`，参数 `run_id=demo-run · fmt=xlsm` |

**闸口确实在桥里，不是前端装样子。** 走完之后查桥的凭据台账：

```bash
curl -s -H "x-bridge-token: $BRIDGE_TOKEN" "localhost:8031/confirmations?include_done=true"
```

回的是：`start` 与 `write_param` 两张 `consumed`、`approved_by` 记着确认人；走查里点了
「取消」的那张 `export` 是 `rejected`；另有几张没人管的停在 `pending`，其中一张已 `expired`。
也就是说三段式每一段都真发生了：签发、人工批准、带票重调。

---

## 六、截图

产出目录 `c/shots5`，1920×1080。

| 文件 | 内容 |
| --- | --- |
| `online-0-device-node.png` | 桥在线：流程 1 画板，设备节点显示「工具 13 个 · 三层 / 模式 live 真连台架 / 网关 已连通」，底栏「设备桥 · 13 个工具」 |
| `online-0-device-node-tip.png` | 同上，悬出节点 tooltip |
| `online-1-gate-empty.png` | 闸门 0/9，顶栏「启动测试」置灰 |
| `online-2-gate-green.png` | 闸门 9/9 全绿 |
| `online-4-redline-confirm.png` | 红线确认卡，凭据栏是桥签发的真 token |
| `online-5-running.png` | 运行中 |
| `online-5-verdict.png` | 已出判定，判定卡未达标行带右向箭头 |
| `online-6-tune-focus.png` | 流程 4，左栏带来源横幅 |
| `online-7-adopt-picked.png` / `online-8-adopt-confirm.png` | 勾选候选与写回参数的确认卡 |
| `online-9-back-to-run.png` | 采纳后回到流程 3 |
| `online-10-report.png` | 流程 5 |
| `online-11-export-confirm.png` | 导出的确认卡 |
| `offline-0-device-node.png` | 桥离线（`VITE_DEVICE_BRIDGE_URL` 指向空端口 8039）：节点「网关 未连通」，工具条桥工具 0 个、离线占位 1 枚 |
| `offline-0-device-node-tip.png` | 同上，tooltip 写「设备桥 http://127.0.0.1:8039 不可达：先起 [源] spike-device-mcp/run-bridge.sh，或改配 VITE_DEVICE_BRIDGE_URL」 |

---

## 七、门禁

| 命令 | 结果 |
| --- | --- |
| `npx tsc -b` | 零错误 |
| `npm run build` | 零错误，`tsc -b && vite build` 均通过 |
| `npm run lint` | 退出码 0。`src/` 下 21 条 warning（**计数口径**：逐字跑 `npm run lint` 当时得到的是 43 条，另 22 条来自本轮留的改动前快照目录 `.bak-src-wire-0906/`，oxlint 没排除它。该目录已于 2026-09-20 删除、`.oxlintrc.json` 也加了 `.bak-*` 忽略项，现在命令输出就是 21 条），逐条与改动前的快照比对过（把快照路径前缀换成 `src/` 再按「文件 + 规则」聚合）：本轮**一条都没新增，还少了一条**——`flow-run/panel.tsx` 原先那条 `react(immutability)`，起因正是闸门状态挂在模块级可变变量上，搬进 store 之后自然消掉。其余全是既有的 `react(only-export-components)` 与 `react(static-components)` |

lint 直接跑会数到 44 条，多出来的 22 条来自本轮的回滚快照 `.bak-src-wire-0906/`，
oxlint 把它也扫了。上表的 21 条是 `src/` 下的真实数。

---

## 八、收尾

- 删掉 `.bak-src-0849/` 与 `.bak-src-r14-0849/`。删前逐文件比对过：两份内容字节相同，
  且其中每一个文件在现 `src/` 里都有对应（`diff -rq` 没有「只在备份里存在」的条目），
  差异全部是 r14 那一轮的修复，已经在现 `src/` 里。本轮的回滚点是 `.bak-src-wire-0906/`。
- `count-r14.mjs` 与 `shot-r14.mjs` 移到 `scripts/`。两个脚本内部用的都是
  `$HOME` 开头的绝对路径，移动后不用改。`CHANGELOG-fix-r14-20260920.md` 里写的旧路径
  没有回改——那份是当时的记录，路径以本文为准。
- `README.md` 新增第 10 节「交互与设备桥」，讲配置、设备节点读什么、红线三段式、
  以及走查的跑法。

---

## 九、没做完的与原因

1. **流程 1、流程 2 的五颗动作按钮仍未接后端**（读取文档自动填充、另存为参数模板、
   校验配置、导入标准、编辑工作流）。它们要的是文档解析与模板落盘，属于服务端能力，
   本轮范围是把已有能力接上，没有去补后端。现在它们统一置灰并给出理由，不再是
   「看着能点、点了没反应」。
2. **动作层工具拿到批准后桥不真下发控制命令。** 这是设备桥 spike 阶段自身的限制
   （`[源] spike-device-mcp/README.md` 第 8 节写明 `dispatch` 是占位），不是前端的缺口。
   页面这一侧的回放与真下发之间的切换点已经留好：`flowActions.ts` 的 `BRIDGE_CALL` 表。
3. **凭据存在桥的进程内存里，桥一重启就没了。** 同样是桥侧的已知限制，落地要换成带
   持久化的存储，否则「人批了、服务重启、带票来执行」会失败。
4. **副驾侧 `/api/agent/confirm` 的服务端未实现。** 前端这一侧已按契约第 3.4 节改成
   转发桥的批准接口并补齐 `actor` 与 `confirm_token`，但没有服务端可以对接，
   这条路径**没有端到端实测过**，只有类型与调用顺序是对的。
5. **`npm run preview` 下设备桥连不上。** 成因是桥的 CORS 白名单不含 preview 端口，
   在前端这一侧改不了。要在 preview 下联桥，得去桥那侧把端口加进 `BRIDGE_CORS_ORIGIN`。
