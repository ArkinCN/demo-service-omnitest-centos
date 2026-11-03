import type { CopilotAction, FlowId, ModuleId } from '../../data/types'
import { fetchJson } from '../shared/fetchJson'

/* ===========================================================================
   助手预置动作的数据层。

   数据源是场景包里的 copilot-actions.json（与 control-parameters.json 等并列），
   结构沿用 06c-copilot-actions.draft.json：结构层与编排层跨场景不变，
   换场景只换 source / skill_ref / prompt / operation 四个内容层字段。

   前端按 sceneId 读，读不到退回本文件末尾的默认骨架。
   =========================================================================== */

export type ActionType = 'explain' | 'prepare' | 'execute'

/** 六个只能人点的红线动作。助手一律不做成自动执行。 */
export type RedlineAction = 'start' | 'stop' | 'estop' | 'write_back' | 'export' | 'archive'

/** JSON 里一枚按钮的全量字段，字段释义见场景包文件的 _field_docs 段。 */
export interface ActionDef {
  id: string
  label: string
  /** 已映射到 src/app/icons.ts 的 COPILOT_ACTION_ICON_NAMES */
  icon: string
  /** 草案里写的 lucide 组件名，仅作追溯 */
  icon_draft?: string
  type: ActionType
  source: 'customer' | 'ours'
  skill_ref: string
  skill_verify: 'verified' | 'unverified'
  prompt: string
  operation: string[]
  touches_redline: boolean
  redline_action: RedlineAction | null
  degraded_to: 'prepare_and_wait' | null
  confirm_required: boolean
  echo: string
  success_feedback: string
  /** 缺任一字段即置灰，值是上下文包的 JSON 指针 */
  context_requires: string[]
  /** 本场景是否开放，缺省视为开放 */
  available?: boolean
  unavailable_reason?: string
}

export interface ActionsFile {
  schema: string
  version: string
  flows: Record<string, { label: string; buttons: ActionDef[] }>
}

/** 五条流程加知识库模块，键与 FLOW_IDS / MODULE_IDS 对齐 */
export type ActionScope = FlowId | ModuleId

const SCOPES: ActionScope[] = ['init', 'req', 'run', 'tune', 'report', 'knowledge']

/**
 * 登记进注册表时只带 registry 契约要的五个字段。
 * requiresConfirm 的口径：执行类一律为 true（走 agent-chat 的 requestConfirm 闸门）；
 * 触碰六个红线动作的按钮也为 true——它们已降级成「备好等人点」，
 * 助手做的是点亮 B 区的人工按钮这一步，那一步同样要人放行，真正的红线动作仍只在 B 区点。
 */
export function toCopilotActions(scope: ActionScope, defs: ActionDef[]): CopilotAction[] {
  return defs.map((d) => ({
    id: d.id,
    flow: scope,
    label: d.label,
    icon: d.icon,
    prompt: d.prompt,
    skill: d.skill_ref,
    requiresConfirm: d.type === 'execute' || d.touches_redline,
  }))
}

const cache = new Map<string, Promise<ActionsFile>>()

/** 读一个场景包的预置动作定义；文件缺失或解析失败时退回默认骨架。 */
export function loadActions(sceneId: string): Promise<ActionsFile> {
  const hit = cache.get(sceneId)
  if (hit) return hit
  const task = (async () => {
    // 2026-10-08：改用统一 fetchJson（原 force-cache 会读旧副本，见 fetchJson 模块头）
    const f = await fetchJson<ActionsFile>(`/scenes/${sceneId}/copilot-actions.json`)
    if (!f || typeof f !== 'object' || !f.flows) return FALLBACK
    return f
  })()
  cache.set(sceneId, task)
  return task
}

export function buttonsOf(file: ActionsFile, scope: ActionScope): ActionDef[] {
  return file.flows[scope]?.buttons ?? []
}

export function scopesOf(file: ActionsFile): ActionScope[] {
  return SCOPES.filter((s) => Array.isArray(file.flows[s]?.buttons))
}

/* --------------------------------------------------------------- 默认骨架 */

/**
 * 场景包没带 copilot-actions.json 时用的兜底。
 * 只给每条流程三枚与场景无关的按钮，不写任何产品名词——
 * 宁可少给几枚，也不拿上一个场景的业务话术套到未知场景上。
 */
function generic(
  scope: ActionScope,
  id: string,
  label: string,
  icon: string,
  type: ActionType,
  prompt: string,
  echo: string,
  operation: string[],
): ActionDef {
  return {
    id: `${scope}.${id}`,
    label,
    icon,
    type,
    source: 'ours',
    skill_ref: `generic-${id}`,
    skill_verify: 'verified',
    prompt,
    operation,
    touches_redline: false,
    redline_action: null,
    degraded_to: null,
    confirm_required: type === 'execute',
    echo,
    success_feedback: '结论写在气泡里，不改动任何数据。',
    context_requires: ['/flow/id'],
  }
}

const GENERIC_LABEL: Record<ActionScope, string> = {
  init: '初始化配置',
  req: '测试需求确认',
  run: '启动测试及结果分析',
  tune: '调优确认及运行',
  report: '测试报告及产出',
  knowledge: '知识库',
}

export const FALLBACK: ActionsFile = {
  schema: 'copilot-actions/v1',
  version: 'fallback',
  flows: Object.fromEntries(
    SCOPES.map((s) => [
      s,
      {
        label: GENERIC_LABEL[s],
        buttons: [
          generic(
            s,
            'explain',
            '本页讲解',
            'explain',
            'explain',
            '讲清楚这一页在做什么、为什么要做、做完之后会发生什么。只讲页面上真实存在的内容，场景包里没有的一律不提。',
            '把这一页在做什么、为什么做、做完会怎样讲一遍。',
            ['读取当前流程的页面结构', '按三段生成讲解'],
          ),
          generic(
            s,
            'gaps',
            '缺项体检',
            'check',
            'prepare',
            '过一遍当前页面：哪些必填项还空着、哪些值还是占位、哪些标了待核实。按是否挡住本流程确认分两组给，每条指出字段名与所在分组。',
            '过一遍空项、占位项和待核实项，只列清单不改数据。',
            ['读取当前页面的值与占位标记', '按阻塞性分两组', '生成体检清单'],
          ),
          generic(
            s,
            'evidence',
            '依据溯源',
            'search',
            'prepare',
            '把本页引用到的数值与结论逐条回链到来源：哪份文件的第几节、哪条经验、还是人工填的。来源不明的单独列一组标「待核实」。',
            '给本页的数值找出处，找不到的会标待核实。',
            ['按字段名检索知识库', '逐条回链并复核单位', '生成溯源表'],
          ),
        ],
      },
    ]),
  ) as ActionsFile['flows'],
}
