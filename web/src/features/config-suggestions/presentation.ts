// 2026-10-29：本模块是纯函数模块（无 hook 作用域），文案走 runtime.translate + 显式传入的
// locale，与组件内的 uiT() 共用同一本词典，避免「同一句中文两套英文」。
import { translate, type Locale } from '../../i18n/runtime.ts'
import type { EditableField, Value } from './protocol'

/** Display the original value without rounding or changing its meaning. */
export function formatSuggestionValue(field: EditableField, value: Value, locale: Locale): string {
  const label = value === null ? '—' : field.kind === 'selection' && typeof value === 'boolean'
    ? translate(value ? '纳入本轮' : '不纳入本轮', locale)
    : String(value)
  // 单位来自场景包原文（如「对」），英文界面下同样要过词典，否则弹窗里会留中文。
  return field.unit && value !== null ? `${label} ${translate(field.unit, locale)}` : label
}

export const visibleQuestions = (questions: readonly string[]): string[] => questions.filter(question => question.trim())
export const uniqueEvidenceIds = (ids: readonly string[]): string[] => [...new Set(ids)]
