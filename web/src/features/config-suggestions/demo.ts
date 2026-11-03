import { requirementIdOf, validValue, type Change, type EditableField, type Snapshot } from './protocol.ts'
import { DEMO_FIELD_RULES, type DemoFieldRule } from './config.ts'

/**
 * 演示差异的理由文案：必须自证是合成数据，避免被误当成模型建议或设备推荐值。
 * 该字符串会随变更一起进入演示草稿，改动前先确认单测（demo.test）里的匹配断言。
 */
const DEMO_REASON = '合成演示：人为注入的草稿差异，用于观察真实模型是否提出更正；这不是模型建议，不代表设备推荐设置。'

const matches = (rule: DemoFieldRule, fieldId: string): boolean =>
  rule.match === 'exact' ? fieldId === rule.key : fieldId.endsWith(rule.key)

/** req 阶段唯一的演示动作：把「已选中」的判据取消勾选 */
function deselectTarget(field: EditableField): boolean | null {
  return field.kind === 'selection' && field.current === true ? false : null
}

/** 数值阶段：注入规则里的目标值；当前值已等于目标时按 bump 造一个合法差异 */
function numericTarget(field: EditableField, rule: DemoFieldRule): number | null {
  if (field.kind !== 'number' || typeof field.current !== 'number' || !validValue(field, field.current)) return null
  if (rule.target === undefined) return null
  const after = field.current === rule.target ? rule.target + (rule.bump ?? 0) : rule.target
  return validValue(field, after) ? after : null
}

/** Synthetic draft discrepancies for a live-model demo, never model advice. */
export function createDemoChanges(snapshot: Snapshot): Change[] {
  const rule = DEMO_FIELD_RULES[snapshot.stage]
  const field = snapshot.fields.find((candidate) => matches(rule, candidate.id))
  if (!field) return []
  const after = snapshot.stage === 'req' ? deselectTarget(field) : numericTarget(field, rule)
  if (after === null) return []
  const evidenceId = snapshot.stage === 'req' ? 'criterion:' + requirementIdOf(field.id) : 'field:' + field.id
  if (!snapshot.evidence.some((item) => item.id === evidenceId)) return []
  return [{ field_id: field.id, before: field.current, after, reason: DEMO_REASON, evidence_ids: [evidenceId] }]
}
