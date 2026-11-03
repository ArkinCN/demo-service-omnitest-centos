# agent-chat —— 测试副驾对话组件

右下角「智能体对话」区（设计规格 D 区）的 React 组件与演示工程。独立可跑，也可整目录搬进宿主工程。

- 工程路径：`c/components/agent-chat`（本仓库根）
- 组件目录：`src/features/agent-chat/`
- 技术栈：Vite 8 + React 19 + TypeScript，无第三方 UI 库、无运行时依赖

## 一、助手名称

当前实现用 **副驾**（英文 Test Copilot），由 `AgentChat` 的 `assistantName` 属性控制，默认值就是「副驾」。

备选名三个，改 `assistantName` 即可切换：

| 备选名 | 英文 | 取向 |
| --- | --- | --- |
| 台架副驾 | Bench Copilot | 强调作业现场是台架，范围收在测试台 |
| 测试助理 | Test Assistant | 中性、无拟人色彩，适合对外演示 |
| 调试搭子 | Debug Buddy | 口语化，适合内部工具语境 |

## 二、执行边界

副驾可读、可算、可建议、可写草稿；**凡是改变被测对象状态或落盘生效的动作，必须人点按钮**。

组件层面的落地方式：

1. 事件 `tool_call` 带 `mutating: true` 的工具（`motor_start`、参数写回一类），卡片先进 **待确认** 态，卡片描边与徽标转暗红，正文明确写「等待人工确认，未执行」。
2. 卡片内给「确认执行 / 取消」两个按钮。确认后转 **已确认执行**，并回填确认人；取消则该次调用记为未执行，流程中止。
3. 适配器通过 `SendRequest.requestConfirm` 拿到这个闸门，未注入闸门时按「不放行」处理 —— 默认不执行，而不是默认执行。
4. 输入区的「开启自动执行」开关只覆盖只读类工具，不覆盖改动类动作，输入区下方常驻一行提示说明这一点。

权限档位三档，随请求下发给后端，前端不自行拦截：

| 值 | 显示 | 含义 |
| --- | --- | --- |
| `readonly` | 只读 | 仅读取工程文件与测量数据，不做任何写入 |
| `params` | 可改参数 | 允许修改标定参数与配置项，不驱动硬件 |
| `hardware` | 可控硬件 | 允许启停电机、切换负载、控制仪器 |

## 三、SSE 事件协议

后端以 `text/event-stream` 推送，一条消息一个事件，`event` 名与 `data.type` 保持一致，便于原生 `EventSource` 按名监听。协议定义在 `src/features/agent-chat/api.ts`。

| 事件 | 字段 | 前端行为 |
| --- | --- | --- |
| `message_delta` | `messageId`、`delta` | 把 `delta` 追加到 `messageId` 对应的助手气泡；该 id 首次出现时新建气泡。工具卡片之后继续说话应换新的 `messageId`，否则文字会追加回前一个气泡。 |
| `tool_call` | `callId`、`name`、`title?`、`args`、`argsSummary`、`mutating?` | 新建工具调用卡片。`mutating` 为真时置「待确认」并等人点按钮，否则直接置「执行中」。 |
| `tool_result` | `callId`、`status`(`ok`/`error`)、`durationMs`、`resultSummary`、`result` | 按 `callId` 回填同一张卡片：状态、耗时、结果摘要、可展开的原始 JSON。 |
| `verdict` | `verdict`（`id`/`title`/`pass`/`expression`/`measurements[]`/`conclusion`/`evidenceIds[]`） | 追加判定卡片。`pass` 为真用主色墨绿，为假用暗红。 |
| `evidence` | `items[]`（`id`/`kind`/`title`/`excerpt`/`source`/`locator`/`href?`） | 并入依据池，按 `id` 去重。`kind` 三值：`procedure` 规程条目、`case` 相似案例、`document` 资料段落。 |
| `done` | `reason`(`complete`/`aborted`/`error`)、`message?` | 本轮结束，停掉流式光标。 |

改动类动作的确认走的是带外通道，不占 SSE 事件位：前端点了确认后 `POST /api/agent/confirm {call_id, approved}`，后端再继续推该 `callId` 的 `tool_result`。

## 四、两种适配器

`AgentAdapter` 接口只有一个方法：`send(req: SendRequest): AsyncGenerator<AgentEvent>`。

### mockAdapter（已实现，用于截图与演示）

脚本化回放一段完整会话：读取 `MotorApp/Inc/Customer.h` → `motor_start`（走人工确认闸门）→ `rigol_measure` 深存储取数 → 判定「空载启动电流峰值」合格 → 推 4 条依据。另有 `mockAdapterInstant`，同一脚本不带延时，供截图使用；确认闸门在它上面照样生效。

### dshAdapter（预留，未联通）

对接 DeepSeek Harness（下称 DSH）Python SDK 的会话流。前端侧已写好 SSE 解析，后端按下表把 DSH 原生事件转成本协议：

| DSH 原生事件 | 本协议事件 | 后端要补的事 |
| --- | --- | --- |
| `assistant.text.delta{text}` | `message_delta` | 工具调用之后新起一段时换一个 `messageId` |
| `tool.invoke{call_id,name,arguments}` | `tool_call` | 生成 `argsSummary`；改动类工具置 `mutating: true` |
| `tool.output{call_id,ok,elapsed,data}` | `tool_result` | 生成 `resultSummary` |
| `judge.result{...}` | `verdict` | 补 `expression` 与 `measurements` 字段 |
| `retrieval.hits[{source,page,text}]` | `evidence` | 按检索库路由 `kind`：规程库→`procedure`，案例库→`case`，资料库→`document` |
| `run.finished{status}` | `done` | — |

改动类工具在 DSH 侧登记为 `requires_approval`：推完 `tool_call` 即挂起该次调用，收到 `/api/agent/confirm` 的放行才继续。`permission` 与 `auto_run` 直达 DSH 的 tool policy，前端只负责把用户选择带上。

## 五、组件接口

```tsx
import { AgentChat } from './features/agent-chat';

<AgentChat
  adapter={dshAdapter}          // 后端适配器，缺省 mockAdapter
  assistantName="副驾"           // 助手显示名
  operator="张工"                // 确认人署名，回填到已执行的改动类动作卡片
  defaultModel="deepseek-v4-pro"
  defaultPermission="params"    // readonly | params | hardware
  initialItems={[]}             // 预置消息流，用于会话恢复
  initialEvidence={[]}          // 预置依据池
  autoStartPrompt="…"           // 挂载后自动发起一轮，演示用
  evidenceOpenOnMount={false}   // 挂载即展开依据抽屉，截图用
  autoConfirm={false}           // 演示用：改动类动作自动放行。生产环境不要开
  onSaveExperience={(draft) => { /* 存经验库 */ }}
/>
```

`onSaveExperience` 收到的 `ExperienceDraft` 字段：`title`、`phenomenon`、`cause`、`action`、`result`、`tags[]`。表单预填规则：标题取判定项名与结论，现象取本轮首条用户消息，原因取判据与结论，动作取各次工具调用的参数摘要，结果取各次工具结果摘要。

组件占满父容器高度，自身不设高度，由外层给定尺寸（D 区面板给 420 高，全屏态给 1000 高）。

## 六、集成步骤

1. 把 `src/features/agent-chat/` 整个目录复制到 `[源] features/agent-chat`。目录自带 `agent-chat.css`，由 `AgentChat.tsx` 自行 import，不需要在宿主工程改样式入口。
2. 宿主工程需具备 React 18 以上与 TypeScript；组件无第三方运行时依赖。
3. 在 D 区容器里渲染 `<AgentChat adapter={dshAdapter} operator={当前登录人} />`，容器需有确定高度。
4. 色板通过 `.ac-root` 上的 CSS 变量暴露，宿主要统一主题就覆盖这些变量：`--ac-primary` `#2E5E45`、`--ac-secondary` `#A8C5B5`、`--ac-tint` `#EAF2EC`、`--ac-accent` `#A6353A`、`--ac-text` `#2C2C2C`、`--ac-text-weak` `#555555`、背景白。
5. 后端按第三节协议实现 `/api/agent/stream` 与 `/api/agent/confirm`，把 `adapter` 换成 `dshAdapter` 即可切走 mock。

## 七、本地运行与截图

```bash
npm install
npm run dev     # 开发
npm run build   # 产物在 dist/
```

演示页支持这些 URL 参数：`view=panel|full` 切面板高度，`instant=1` 用即时回放，`evidence=1` 挂载即展开依据抽屉，`hold=1` 停在待确认态，`bare=1` 只渲染面板本体（截图用）。

`shots/` 下五张截图：

| 文件 | 内容 |
| --- | --- |
| `panel-1600x420.png` | 右下角面板态，1600 × 420，回放到判定卡片 |
| `full-1600x1000-evidence.png` | 全屏态 1600 × 1000，依据抽屉展开，三段分组齐全 |
| `confirm-pending-1600x420.png` | `motor_start` 停在待确认态，确认条与两个按钮 |
| `experience-modal-1600x1000.png` | 沉淀为经验表单，五个字段加标签均已预填 |
| `tool-json-1600x1000.png` | 工具调用卡片展开原始 JSON |

## 八、语音输入

用 `webkitSpeechRecognition`（回退 `SpeechRecognition`），语言固定 `zh-CN`，边说边把结果追加进输入框。浏览器不提供该接口时麦克风按钮灰显并禁用，输入区下方给出提示。文字输入 Enter 发送、Shift+Enter 换行，中文输入法组字期间的 Enter 不触发发送。
