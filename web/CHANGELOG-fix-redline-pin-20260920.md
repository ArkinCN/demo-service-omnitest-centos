# 红线绕过修复：把「调用票」和「批准权」拆开

日期：2026-09-20。触发来源：`07i-交互打通独立核验.md`（第四轮接线的独立核验报告，
位于 `[源] 09-实验室demo线/20260919-通用Agent测试系统v2.0`）。
本轮修的是它第十节记下的 P1（严重）、P2 与 P3（中）、P5 与 P4 的一部分（低）。

改动横跨两套工程，**两边都改了**：

| 工程 | 绝对路径 | 角色 |
| --- | --- | --- |
| 前端原型 OmniTest | `[源] zzz/agent-test-web` | 确认卡、store、副驾、走查脚本 |
| 设备桥 device-bench bridge | `c/components/spike-device-mcp` | 鉴权分级、台账字段、启动脚本 |

---

## 一、被修的是什么

独立核验的原话：构建产物 `dist/assets/index-*.js` 里躺着设备桥的鉴权 token 明文，
而桥的人工批准接口 `POST /confirmations/{token}/approve` 的**全部**鉴权就是这一个
token。于是任何拿到那份构建产物的人都能自己调工具签一张凭据、自己调 approve 批准、
再带票执行，全程不需要任何人点任何按钮。红线的三段式在桥里实现得没错，但整道闸口
可以被绕过去。

核验人另记了两条中级问题：副驾的 `autoConfirm` 分支能在无人点击时 `resolve(true)`，
而批准人署名与操作者名都是写死的「张工」，自动放行与真人批准在台账里分不开；
助手侧三枚红线按钮恒为置灰，那条红线在该路径上拿不到任何运行时证据。

---

## 二、修法

### 2.1 桥：鉴权拆成两级

| 秘密 | 请求头 | 存在哪 | 能做什么 |
| --- | --- | --- | --- |
| `BRIDGE_TOKEN` | `x-bridge-token` | 桥的 `.env`；本地开发时随 `VITE_BRIDGE_TOKEN` 进浏览器——按**公开**处理 | 列设备、查状态、调工具、驳回凭据。调红线工具只拿得到一张 `pending` 凭据 |
| `BRIDGE_APPROVER_PIN` | `x-approver-pin` | **只在桥的 `.env` 与桥进程内存**，不进任何 `VITE_` 变量、不进任何构建产物 | 把一张 `pending` 凭据批成 `approved` |

落地细节：

- 比较用 `hmac.compare_digest`，常量时间，不用 `==`。两处都改了（调用票那一处顺手一并改）。
- 没带 PIN 或 PIN 不对一律 **403**，凭据**保持 pending**：不消耗、不作废、不降级。
- 连续错 5 次锁 60 秒（`BRIDGE_APPROVER_PIN_MAX_FAILS`、`BRIDGE_APPROVER_PIN_LOCK_SECONDS` 可调）。
  锁定期间 PIN 正确也拒。**没带 PIN 也计一次失败**。计数全进程一份，不按来[源] IP 分桶。
- 桥在 `BRIDGE_APPROVER_PIN` 未设置、或与 `BRIDGE_TOKEN` 同值时**拒绝启动**——同值等于没有第二道闸口。
- 台账多两个字段：`approved_by` 记前端传来的操作者名，`approve_channel` 记 `human_pin`。
- `GET /health` 与 `GET /devices/{id}/status` 回 `approve_requires_pin` 与 `approver_pin_gate`
  （是否锁定、还剩几秒），前端据此把 403 解释清楚。

### 2.2 前端：PIN 现场输入，批准只剩一条路径

- `src/features/redline/RedlineConfirm.tsx` 加批准 PIN 输入框（`type="password"`，
  `autoComplete="new-password"`，`data-testid="redline-pin"`）。没填 PIN 时「确认执行」按钮置灰
  并挂 tooltip 说明原因。PIN 只活在该组件的 `useState` 里，换一张凭据即清空，卡关掉随组件卸载消失。
- `src/state/useAppStore.ts` 的 `approveRedline` 签名改为 `(pin: string) => Promise<void>`，
  把 PIN 作为实参逐次传进 `approveConfirmation`，不缓存、不落 `localStorage`、不进模块级变量。
- **删除** `src/features/agent-chat/AgentChat.tsx` 的 `autoConfirm` 分支与 `autoConfirm` prop
  （核验 P2 给了「删除」与「限制为 dev」两个选项，按任务书的优先级取删除）。
  `requestConfirm` 现在只有一条出路：把 `resolve` 挂进 `confirmWaiters`，等人点。
- `src/features/agent-chat/api.ts` 原第 427 行那个第二批准调用点改走
  `requestRedlineAsync()`：把桥的凭据排进同一张确认卡，人敲 PIN 点确认才 `resolve(true)`，
  点取消或桥 403 就按取消送回执。全工程批准桥凭据的路径因此只剩一条：
  **确认卡 → `approveRedline` → `approveConfirmation`**。
- 操作者名改为从 store 读（`operator` 字段，默认仍「张工」，`setOperator` 可改），
  写死的 `CONFIRM_ACTOR` 与导出常量 `OPERATOR` 一并删除。
- `src/features/remote/bridge.ts`：构建产物不再内嵌调用票。
  `import.meta.env.DEV` 在 build 时被替换成 `false`，整条分支连同那个字符串一起被消掉；
  交付出去的页面由操作员现场给票（`omnitestSetBridgeToken('<token>')`，存本机 `localStorage`）。
  本地开发照旧读 `.env`，起了 vite 就能用。

### 2.3 助手三枚红线按钮：查清恒灰的原因并接上

三枚按钮读的是上下文包（`src/features/copilot/context.ts`）里的 JSON 指针，缺任一项即置灰。
逐枚查下来的原因与修法：

| 按钮 | 读的指针 | 恒灰的原因 | 修法 |
| --- | --- | --- | --- |
| 写回草稿（流程 4） | `/zoneB/selected_candidate` | 该字段在 `buildEnvelope()` 里写死 `null`，与界面上的勾选不是同一处 | 接到 store 的 `adoptedKeys` / `adoptMeta`：勾选候选即非 null |
| 经验草稿（流程 4） | `/session/transcript_summary` | `ActionDock` 传的是写死的 `null` | `FlowCopilot` 在对话忙态的下降沿记一笔 `chatRounds`，摘要按已跑轮数如实给；零轮仍为 `null` |
| 导出待点（流程 5） | `/lastRun/artifacts` | 轮次产物存储未实现，如实写 `null` | 跑完一轮后给回放态产物索引，字段里写明 `replay: true`，不冒充台架落盘文件；没跑过仍为 `null` |

三枚按钮的类型仍是 `prepare`，`degraded_to` 仍是 `prepare_and_wait`——它们做到「备好等人点」为止，
点亮的是 B 区的人工按钮，真正的红线动作仍只在 B 区点，且仍走 `RedlineConfirm` 那张卡。
置灰时的 tooltip 也重写过，写明前置条件在哪一步补。

### 2.4 顺手清掉的低级问题

- 删除工程根的 `.bak-src-wire-0906/`（先 `diff -rq` 确认它里面没有 `src/` 没有的文件，
  确认后移走，不是直接 `rm`）。`.oxlintrc.json` 的 `ignorePatterns` 补 `.bak-*`、`shots*`、`tmp`，
  以后备份目录不会再被算进 lint 计数。
- `CHANGELOG-wire-20260920.md` 两处更正：第二节引导句「新建 5 个、改动 11 个」改为
  「新建 6 个、改动 12 个」（与它自己的两张表和 `diff -rq` 一致）；第一节「批准函数只有一个
  合法调用点」那条加了一段更正说明，写明它在当时与事实不符、第二个调用点在哪、何时改掉。
  第五节的 lint 计数补了口径说明。
- `run-bridge.sh` 起桥后自动调一次 `connect` 并打印 `mode`。桥重启会清空 SSH 会话，
  不补这一步的话 `status` 一直停在 `unknown`，演示当场才发现没连台架（核验第五节的附带观察）。
  `--no-connect` 跳过，并打出手动 connect 的命令行。

---

## 三、验证

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 类型 | `npx tsc -b` | 退出码 0，无输出 |
| 构建 | `npm run build` | 退出码 0，452 ms；唯一告警是既有的 chunk 体积提示 |
| lint | `npx oxlint` | **0 error、21 warning**（删掉备份目录前是 43 条，其中 22 条来自那个目录） |
| 产物不含桥 token | `grep -c "$(grep '^BRIDGE_TOKEN=' [源] spike-device-mcp/.env \| cut -d= -f2-)" dist/assets/*.js` | **0**（递归搜整个 `dist/` 也是 0 个文件命中） |
| 产物不含批准 PIN | 同上换 `BRIDGE_APPROVER_PIN` | **0**（递归搜整个 `dist/` 也是 0） |
| 主线走查 | `WALK_PIN=… BASE=http://localhost:5173 node scripts/walk-wire.mjs` | **12 步全 PASS**，三张确认卡各检出 1 个 PIN 框 |

反向测试（直接打桥的 HTTP 面，不经页面）：

| 编号 | 做法 | 结果 |
| --- | --- | --- |
| R-A | 拿浏览器那份 token 调 approve，不带 PIN | **403**，回「缺 x-approver-pin 头…凭据保持 pending」；票查回来仍是 `pending`、`approved_by` 为空 |
| R-B | 连打 5 次错 PIN | 第 4 次错 PIN 触发锁定（R-A 那次空手也计了一次失败），回「已锁定 60 秒」；此后**即使 PIN 正确**也回 403「批准已被锁定：…60.0 秒后才能再试」；票始终 `pending` |
| R-C | 等锁定解除，带正确 PIN 批准 | **HTTP 200**，`state=approved`、`approved_by=李工`、`approve_channel=human_pin`；带同票同参数重调 `start` → `executed=true`、`mode=live`；票终态 `consumed` |

桥 `status` 两态：

```
./run-bridge.sh --no-connect  → mode=unknown connected=False hostname=None
./run-bridge.sh               → connect 返回 mode=live
                                mode=live connected=True hostname=SK-20251218QPBB
```

台账抽查（`GET /confirmations?include_done=true`）：

```
export       rejected   by=None  channel=None        reason=操作员在页面上驳回
write_param  consumed   by=张工  channel=human_pin
start        consumed   by=张工  channel=human_pin
start        consumed   by=李工  channel=human_pin
start        pending    by=None  channel=None
```

助手三枚红线按钮的可用态（`tmp/probe-buttons.mjs`、`tmp/probe-export.mjs`，截图落 `shots7/`）：

| 按钮 | 前置条件未满足 | 前置条件满足后 |
| --- | --- | --- |
| 写回草稿 | `disabled`，tooltip「先在流程 4 的推荐参数里勾选至少一条候选改动」 | 勾一条候选后 `disabled=false` |
| 经验草稿 | `disabled`（零对话轮时） | 助手跑完一轮后 `disabled=false` |
| 导出待点 | `disabled`，tooltip「先在流程 3 跑完一轮…」 | 跑完一轮后 `disabled=false` |

截图落 `shots7/`：`online-4-redline-confirm.png`（确认卡含 PIN 框，PIN 未填时确认按钮置灰）、
`online-4b-redline-pin-filled.png`（PIN 已填）、`online-8-adopt-confirm.png`、
`online-11-export-confirm.png`、`probe-tune-writeback.png`、`probe-report-export.png`。

---

## 四、剩余边界

一、**PIN 会在浏览器内存里短暂存在。** 它从输入框敲进来，到请求发出为止存在于那个组件的
`useState` 里，并以明文出现在那一次请求头里。能读这台机器浏览器内存、或能嗅这条回环流量
的人仍然拿得到它。这一版改不掉。它换来的是要堵的那个口子：**光有构建产物批不动任何红线
动作**，批准必须有人在这台机器前面现场敲一次。要再收一档，下一步是把批准挪到桥所在主机上
做本地确认，页面只展示待批清单，PIN 连浏览器都不经过。

二、**调用票在本地开发时仍进浏览器。** `import.meta.env.DEV` 为真时读 `.env`，方便起了
vite 就能用。它现在只是调用票，泄漏的后果限于「能让桥签发 pending 凭据」，但仍应按公开处理。

三、**凭据与 PIN 失败计数都是纯内存。** 桥一重启全部归零，包括锁定状态。这与凭据的设计一致，
但意味着能重启桥的人可以清掉锁定。桥跑在本机回环上，能重启它的人本来就已经能读 `.env`。

四、**探桥请求重复放大这条没修**（核验 P4）：`useBridgeDevice()` 按组件实例各自建连，
`/run` 页静置 20 秒实测在线 24 次请求、离线 48 次并伴随 48 条 `net::ERR_CONNECTION_REFUSED`。
它不影响功能与红线，属观感与控制台噪音问题，留到下一轮收敛成模块级单例订阅。

五、**`.gitignore` 仍不产生保护作用**（核验 P6）：`[源] zzz/agent-test-web` 不是 git 仓库，
那一行目前是一句无效声明。纳入版本管理时要一并确认 `.env` 与 `dist/` 都被忽略。

六、**真后端那条路径只做了代码核验。** DSH 会话服务本次未起，`api.ts` 改走
`requestRedlineAsync()` 之后的那条路径没有经真 SSE 事件流跑过。桥侧的两级鉴权是跑过的，
但「助手拿到票 → 弹确认卡 → 人敲 PIN」这一段在真后端下的表现待补。
