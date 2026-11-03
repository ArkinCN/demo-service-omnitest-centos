/* ===========================================================================
   扩展装配点。

   第三轮：知识库从流程降级为模块，flow-kb 的注册全部下架，
   /knowledge 页的内容由知识库模块用 registerModulePage('knowledge', …) 挂进来；
   收尾轮把那一行注册 import 统一收到这里（并行期它临时挂在 KnowledgePage.tsx 上）。

   卡片注册表按卡片库标识（CardId）唯一，因此同一张卡在多条流程里要显示不同
   内容时，只能注册一次、在 render 里按 ctx.flow 分派——这里的 CARD_IMPL 就是
   那张分派表。左栏与助手按流程各注册一次。
   =========================================================================== */
import { FLOW_IDS, type CardId, type FlowId } from '../data/types'
import { registerAssistant, registerLeftPanel, registerPanelCard } from '../registry'
import { useAppStore } from '../state/useAppStore'
import { FlowCopilot } from './copilot'
import { initCards } from './flow-init/panel'
import { reqCards, ReqLeftPanel } from './flow-req/panel'
import { runCards, RunLeftPanel } from './flow-run/panel'
import { tuneCards, TuneLeftPanel } from './flow-tune/panel'
import { reportCards, ReportLeftPanel } from './flow-report/panel'
// 副作用注册：registerModulePage('knowledge', KnowledgeModule)
import './knowledge/register'
// 副作用注册：把写类工具的前端执行器（WriteReportHeader 等）挂进 agent-chat 注册表，
// 供人工确认放行后真正执行。与上面 knowledge/register 同一手法。
import './copilot/toolExecutors'

type CardImpl = (p: { full?: boolean }) => React.ReactNode

/** 卡片库标识 → 各流程的实现。key 是流程，缺省表示该流程不出这张卡。 */
const CARD_IMPL: Partial<Record<CardId, Partial<Record<FlowId, CardImpl>>>> = {
  'project-tree': { init: initCards['project-tree'] },
  'wf-lib': { req: reqCards['wf-lib'] },
  evidence: { req: reqCards.evidence, tune: tuneCards.evidence },
  history: {
    req: reqCards.history,
    tune: tuneCards.history,
    report: reportCards.history,
  },
  progress: { run: runCards.progress },
  candidates: { tune: tuneCards.candidates },
  'param-changes': { tune: tuneCards['param-changes'] },
  'product-view': { init: initCards['product-view'] },
  schematic: { init: initCards.schematic, run: runCards.schematic },
  'bench-live': { init: initCards['bench-live'] },
  interlock: { init: initCards.interlock, run: runCards.interlock },
  workflow: { req: reqCards.workflow },
  verdict: {
    req: reqCards.verdict,
    run: runCards.verdict,
    tune: tuneCards.verdict,
    report: reportCards.verdict,
  },
  timeseries: { run: runCards.timeseries, tune: tuneCards.timeseries },
  // 'remote-device'（单机设备会话）第三轮撤掉独立卡槽：设备只以画板上的 MCP 节点
  // 出现（src/features/remote/DeviceMcpNode.tsx），卡库里也不再留实现。
  // 依据：《第三轮需求变更方案 v0.1》第 2.3 节第 4 条。
  'report-preview': { report: reportCards['report-preview'] },
  artifacts: { report: reportCards.artifacts },
  'template-fields': { report: reportCards['template-fields'] },
}

const LABEL: Partial<Record<CardId, string>> = {
  'project-tree': '文档库 / 工程树',
  'wf-lib': '工作流库',
  evidence: '知识库依据',
  history: '历史对比',
  experience: '经验库',
  pipeline: '转化流水线',
  progress: '执行进度与日志',
  candidates: '候选队列',
  'param-changes': '参数变更',
  verdict: '判定卡',
}

for (const [id, impls] of Object.entries(CARD_IMPL) as [CardId, Record<FlowId, CardImpl>][]) {
  const flows = Object.keys(impls) as FlowId[]
  registerPanelCard({
    id,
    label: LABEL[id] ?? id,
    flows,
    render: ({ flow }) => {
      const C = impls[flow]
      return C ? <C /> : null
    },
    renderExpanded: ({ flow }) => {
      const C = impls[flow]
      return C ? (
        <div className="h-[min(60vh,430px)] w-[1180px] max-w-full bg-surface p-2">
          <C full />
        </div>
      ) : null
    },
  })
}

registerLeftPanel('req', ReqLeftPanel)
registerLeftPanel('run', RunLeftPanel)
registerLeftPanel('tune', TuneLeftPanel)
registerLeftPanel('report', ReportLeftPanel)
// 流程 2 初始化配置的左栏就是 product-attributes.json 的 29 项参数，
// 壳层默认参数栏（Stepper + 来源标签）已经正好，不另外接管。

for (const f of FLOW_IDS) {
  // 透传注册表给的 props：onCollapse 由壳层（FlowScreen）经 AssistantPanel →
  // registry 一路带到这，只把 flow 往下传会把「收起」回调丢掉，
  // 表现为助手头部少一枚收起键（编译不报错，只在界面上看不见）。
  registerAssistant(f, (props) => <FlowCopilot flow={f} onCollapse={props.onCollapse} />)
}

/** 启动即把真实场景包读进来（public/scenes/motor.cooling-fan.fortior-fu6832/）。 */
useAppStore.getState().bootstrap()

