import { uiMessage } from '../../i18n/messages'
import type { RawPack } from '../scene/pack'
import type { Step } from './adapter'
import type { ActionDef } from './actions'
import type { Envelope } from './context'

/* ===========================================================================
   点一枚预置按钮之后放什么。

   按 06c 第 5.3 节，一次点击固定走三段，一段都不许省：
     回显  先把 echo 那句话显示出来，讲清将要做什么、会不会改东西
     确认  执行类弹确认卡片，走 agent-chat 现成的 requestConfirm 闸门
     执行  按 operation 逐条发 tool_call，结果按既有协议回填

   本轮没有后端，执行段是按场景包数据的脚本化回放，所以每一次执行的收尾都要
   明说这是演示态——助手嘴里的每一个数都得能指回场景包，指不回的宁可不说。
   =========================================================================== */

const REDLINE_LABEL: Record<string, string> = {
  start: '启动',
  stop: '停止',
  estop: '急停',
  write_back: '写回参数',
  export: '导出',
  archive: '归档',
}

const SOURCE_LABEL = { customer: '客户 dc-skills 规程', ours: '我方规程' } as const

/** operation 的一条写法是「tool_name 中文说明」或纯中文说明，拆成工具名与标题 */
function splitOp(op: string, fallbackName: string): { name: string; title: string } {
  const m = /^([a-z][a-z0-9_]*)\s+(.+)$/.exec(op)
  if (m) return { name: m[1], title: m[2] }
  return { name: fallbackName, title: op }
}

/** 场景包里拿得到的几个计数，用来把工具卡的入参与结果写实，不编数 */
function facts(p: RawPack | null) {
  return {
    attrs: p?.attributes.attributes.length ?? 0,
    placeholders: p?.attributes.attributes.filter((a) => a._placeholder).length ?? 0,
    params: p?.controls.parameters.length ?? 0,
    reqs: p?.requirements.requirements.length ?? 0,
    evaluable: p?.requirements.evaluable_count ?? 0,
    interlocks: p?.interlocks.interlocks.length ?? 0,
    workflows: p?.workflows.total ?? 0,
    docs: p?.documents.total ?? 0,
    exps: p?.experience.count ?? 0,
    reportFields: p?.report.header_fields.length ?? 0,
    synthetic: p?.caps.syntheticData ?? false,
  }
}

/** 一句能指回场景包的结果摘要。凡是本轮拿不到的，直接说拿不到。 */
function resultLine(def: ActionDef, i: number, f: ReturnType<typeof facts>): string {
  const scope = def.id.split('.')[0]
  if (i > 0) return '已按上一步的结果继续，产出写进气泡与 B 区暂存区，未落盘'
  switch (scope) {
    case 'init':
      return `本体属性 ${f.attrs} 项、占位 ${f.placeholders} 处、安全联锁 ${f.interlocks} 条，已读入`
    case 'req':
      return `判据 ${f.reqs} 条（可自动求值 ${f.evaluable} 条）、工作流 ${f.workflows} 条，已读入`
    case 'run':
      return `控制参数 ${f.params} 项、安全联锁 ${f.interlocks} 条已读入；现场实测量本轮未采到`
    case 'tune':
      return `经验库 ${f.exps} 条、控制参数 ${f.params} 项已读入`
    case 'report':
      return `报告模板表头 ${f.reportFields} 字段、分节结构已读入`
    default:
      return `文档 ${f.docs} 份、经验 ${f.exps} 条已读入`
  }
}

/**
 * 把一枚按钮展开成一段回放脚本。
 *
 * 红线按钮（touches_redline）的收尾固定是「点亮 B 区的人工按钮」这一步，
 * 而且这一步本身带 mutating 走人工放行；真正的启动 / 停止 / 急停 / 写回参数 /
 * 导出 / 归档六个动作，助手一次都不发。
 */
export function stepsForAction(def: ActionDef, pack: RawPack | null, env: Envelope): Step[] {
  const f = facts(pack)
  const steps: Step[] = []

  // ── 第一段 · 回显 ───────────────────────────────────────────────
  const verify =
    def.skill_verify === 'unverified'
      ? `规程 ${def.skill_ref}（${SOURCE_LABEL[def.source]}，名称待核实，入参与步骤未逐条打开原文确认）`
      : `规程 ${def.skill_ref}（${SOURCE_LABEL[def.source]}）`
  steps.push({
    kind: 'say',
    text: `${def.echo}\n依据：${verify}。预置内容共 ${def.operation.length} 步，先摊开给你看再动手。`,
          uiText: uiMessage("{v1}\n依据：{v2}。预置内容共 {v3} 步，先摊开给你看再动手。", { v1: def.echo, v2: verify, v3: def.operation.length }, ["v1","v2"]),
  })
  if (def.touches_redline && def.redline_action) {
    steps.push({
      kind: 'say',
      text: `这枚按钮碰到的是「${REDLINE_LABEL[def.redline_action]}」，属六个只能人点的动作之一。我做到「备好等人点」为止：检查跑完、草稿生成好、B 区的人工按钮由灰点亮，真正那一下由你在 B 区点。`,
          uiText: uiMessage("这枚按钮碰到的是「{v1}」，属六个只能人点的动作之一。我做到「备好等人点」为止：检查跑完、草稿生成好、B 区的人工按钮由灰点亮，真正那一下由你在 B 区点。", { v1: REDLINE_LABEL[def.redline_action] }, ["v1"]),
    })
  }

  // ── 第二、三段 · 确认与执行 ────────────────────────────────────
  def.operation.forEach((op, i) => {
    const { name, title } = splitOp(op, `${def.id.replace('.', '_')}_s${i + 1}`)
    steps.push({
      kind: 'tool',
      callId: `${def.id}-${i + 1}`,
      name,
      title,
      args: {
        button_id: def.id,
        skill_ref: def.skill_ref,
        scene_id: env.product.scene_id,
        flow: env.flow.id,
        step: i + 1,
      },
      argsSummary: `${title}（场景包 ${env.product.scene_id}）`,
      // 执行类的第一步走人工确认闸门：确认卡片出现在气泡里，人点了才往下走
      mutating: def.type === 'execute' && i === 0,
      durationMs: 520 + i * 260,
      resultSummary: resultLine(def, i, f),
      result: {
        button_id: def.id,
        step: op,
        scene_id: env.product.scene_id,
        replay: true,
        note: '演示态脚本化回放，数值来自场景包登记值，不是设备实时返回',
      },
    })
  })

  if (def.touches_redline && def.redline_action) {
    steps.push({
      kind: 'tool',
      callId: `${def.id}-arm`,
      name: 'arm_manual_button',
      title: `点亮 B 区的「${REDLINE_LABEL[def.redline_action]}」按钮`,
      args: { redline_action: def.redline_action, degraded_to: def.degraded_to },
      argsSummary: `只把人工按钮由灰转可点，不执行「${REDLINE_LABEL[def.redline_action]}」本身`,
      mutating: true,
      durationMs: 180,
      resultSummary: `已点亮；「${REDLINE_LABEL[def.redline_action]}」仍只能由你在 B 区点`,
      result: { armed: true, executed: false, redline_action: def.redline_action },
    })
  }

  // ── 收尾 ────────────────────────────────────────────────────────
  const tail = f.synthetic
    ? ' 本场景的时序数据全部是合成的，不是实测，任何结论都不得进合规报告。'
    : ''
  steps.push({
    kind: 'say',
    text: `${def.success_feedback}${tail}\n本轮是演示态：没有接后端，上面的工具调用是按场景包数据的脚本化回放，不是真设备返回。接上 DeepSeek Harness 之后，同一枚按钮会把这段预置 prompt 与上下文包一起发给后端，回放通路整条换成真事件流。`,
          uiText: uiMessage("{v1}{v2}\n本轮是演示态：没有接后端，上面的工具调用是按场景包数据的脚本化回放，不是真设备返回。接上 DeepSeek Harness 之后，同一枚按钮会把这段预置 prompt 与上下文包一起发给后端，回放通路整条换成真事件流。", { v1: def.success_feedback, v2: tail }, ["v1","v2"]),
  })
  return steps
}
