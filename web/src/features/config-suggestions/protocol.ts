export type Stage = 'init' | 'req' | 'run'
export type Value = number | string | boolean | null
export interface EditableField {
  id: string; name: string; kind: 'number' | 'enum' | 'selection'; current: Value
  unit: string; minimum: number | null; maximum: number | null; step: number | null; precision: number; options: Value[]
}
export interface Evidence { id: string; title: string; text: string }
export interface Snapshot { stage: Stage; scene_id: string; fields: EditableField[]; evidence: Evidence[] }
export interface Change { field_id: string; before: Value; after: Value; reason: string; evidence_ids: string[] }
export interface Proposal { summary: string; changes: Change[]; questions: string[] }

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const keys = (value: Record<string, unknown>, names: string[]) => Object.keys(value).every(key => names.includes(key))
const scalar = (value: unknown): value is Value => value === null || typeof value === 'boolean' || typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))
export function validValue(field: EditableField, value: Value): boolean {
  if (field.kind === 'selection') return typeof value === 'boolean'
  if (field.kind === 'enum') return field.options.some(option => option === value)
  if (typeof value !== 'number' || !Number.isFinite(value)) return false
  if (Math.abs(value - Number(value.toFixed(field.precision))) > 1e-9) return false
  if (field.minimum !== null && value < field.minimum || field.maximum !== null && value > field.maximum) return false
  if (field.step !== null && field.step > 0) {
    const steps = (value - (field.minimum ?? 0)) / field.step
    if (Math.abs(steps - Math.round(steps)) >= 1e-6) return false
  }
  return true
}

export function validateProposal(value: unknown, snapshot: Snapshot): Proposal {
  if (!record(value) || !keys(value, ['summary', 'changes', 'questions']) || typeof value.summary !== 'string' || !value.summary.trim() || value.summary.length > 1500 || !Array.isArray(value.changes) || value.changes.length > 12 || !Array.isArray(value.questions) || value.questions.length > 12 || !value.questions.every(q => typeof q === 'string')) throw new Error('Invalid suggestion response')
  const fields = new Map(snapshot.fields.map(field => [field.id, field]))
  const evidence = new Set(snapshot.evidence.map(item => item.id))
  const seen = new Set<string>()
  for (const change of value.changes) {
    if (!record(change) || !keys(change, ['field_id', 'before', 'after', 'reason', 'evidence_ids']) || typeof change.field_id !== 'string' || !scalar(change.before) || !scalar(change.after) || typeof change.reason !== 'string' || !change.reason.trim() || change.reason.length > 1200 || !Array.isArray(change.evidence_ids) || !change.evidence_ids.length || !change.evidence_ids.every(id => typeof id === 'string' && evidence.has(id))) throw new Error('Invalid change or unsupported evidence')
    const field = fields.get(change.field_id)
    if (!field || seen.has(field.id) || change.before !== field.current || change.before === change.after || !validValue(field, change.after)) throw new Error('Suggestion does not match an editable field or its allowed values')
    seen.add(field.id)
  }
  return value as unknown as Proposal
}

export const fingerprint = (snapshot: Snapshot) => JSON.stringify([snapshot.scene_id, snapshot.stage, snapshot.fields])

/**
 * 判据字段 id 的唯一前缀约定：`req.<判据 id>`。
 *
 * 2026-10-29：此前三处各自推导这个映射——`context.ts` 硬拼 `'req.' + id`、
 * `flow-req/panel.tsx` 用 `field_id.slice(4)`（前缀长度写死）、`demo.ts` 又自己截一次。
 * 前缀一变就静默失效，且 `slice(4)` 看不出在剥什么。统一到这两个函数。
 */
export const REQ_FIELD_PREFIX = 'req.'
export const requirementFieldId = (requirementId: string): string => REQ_FIELD_PREFIX + requirementId
export const requirementIdOf = (fieldId: string): string =>
  fieldId.startsWith(REQ_FIELD_PREFIX) ? fieldId.slice(REQ_FIELD_PREFIX.length) : fieldId
