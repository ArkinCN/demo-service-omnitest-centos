import { translate } from '../../i18n/runtime.ts'
import { initialLocale } from '../../i18n/locale.ts'
import { getPack, sourceLine, type RawAttribute } from '../scene/pack'
import { paramKey, resolveParamKey, useAppStore } from '../../state/useAppStore'
import { fingerprint, requirementFieldId, validValue, type Stage, type Snapshot, type Change, type EditableField, type Value } from './protocol'
import { decimalsOf } from '../../data/loadScene'

export function assertEditable(stage: Stage) {
  const state = useAppStore.getState()
  if (state.confirmed[stage] || state.runPhase === 'running' || state.automationRunStatus === 'running') throw new Error('Unlock this stage and stop any running test before requesting or applying suggestions.')
}

export function snapshotFor(stage: Stage, selection?: ReadonlySet<string>): Snapshot {
  assertEditable(stage)
  const pack = getPack()
  const state = useAppStore.getState()
  if (!pack || pack.scene.id !== state.sceneId) throw new Error('Scene is still loading')
  const fields: EditableField[] = []
  const evidence: Snapshot['evidence'] = []
  const add = (attribute: RawAttribute, key: string, current: unknown) => {
    if (attribute.editable === false || attribute.not_applicable) return
    const options = attribute.options?.map(option => option.value) ?? []
    // Match the actual editors: number controls plus existing enumerated selects.
    if (!options.length && typeof current !== 'number') return
    if (options.length && !['number', 'string', 'boolean'].includes(typeof current)) return
    const field: EditableField = { id: key, name: attribute.name, kind: options.length ? 'enum' : 'number', current: current as Value, unit: attribute.unit ?? '', minimum: attribute.min, maximum: attribute.max, step: attribute.step, precision: decimalsOf(attribute.step) || Math.min(4, decimalsOf(typeof attribute.value === 'number' ? attribute.value : 0)), options }
    fields.push(field)
    // Keep the source configuration distinct from today's editable draft.
    // Only expose a directly usable reference when it satisfies the same editor.
    // 单位来自场景包原文（如「对」），随界面语言翻译；纯函数模块拿不到 hook，按项目既有约定
    // 用 initialLocale()。这段 evidence 文本同时会送给模型，英文界面下保持全英文。
    const unit = field.unit ? translate(field.unit, initialLocale()) : ''
    const reference = validValue(field, attribute.value)
      ? `Scenario package reference (not a live measurement): ${JSON.stringify(attribute.value)} ${unit}.`
      : ''
    evidence.push({ id: 'field:' + key, title: attribute.name, text: [reference, sourceLine(attribute._source), attribute.note, attribute._status].filter(Boolean).join(' · ').slice(0, 1200) || 'Current scenario field metadata; not an independent measurement.' })
  }
  if (stage === 'req') {
    if (!selection) throw new Error('Test selection is not ready')
    for (const requirement of pack.requirements.requirements) {
      const key = requirementFieldId(requirement.id)
      fields.push({ id: key, name: requirement.name, kind: 'selection', current: selection.has(requirement.id), unit: '', minimum: null, maximum: null, step: null, precision: 0, options: [true, false] })
      evidence.push({ id: 'criterion:' + requirement.id, title: requirement.name, text: requirement.criterion_text.slice(0, 1200) })
    }
  } else {
    if (stage === 'init') for (const attribute of pack.attributes.attributes) {
      const key = paramKey('init', 'pa', attribute.group, attribute.key)
      // The property editor only supports numeric values, not arbitrary strings.
      if (!attribute.options?.length) add(attribute, key, state.overrides[key] ?? attribute.value)
    }
    for (const parameter of pack.controls.parameters) {
      if (stage === 'run' && !parameter.editable) continue
      if (!parameter.adjustable_in_flows?.some(flow => flow.startsWith(stage === 'init' ? 'F2' : 'F4'))) continue
      const key = paramKey(stage, 'cp', parameter.group, parameter.key)
      const value = stage === 'run' ? resolveParamKey('run', 'cp', parameter.group, parameter.key, state.overrides, state.snapshotValues).value ?? parameter.value : state.overrides[key] ?? parameter.value
      // Run ParamRow permits numeric editing only when source value is numeric.
      if (stage === 'run' && !parameter.options?.length && typeof parameter.value !== 'number') continue
      add(parameter, key, value)
    }
  }
  for (const item of pack.experience.experiences.slice(0, 35)) evidence.push({ id: 'experience:' + item.id, title: item.symptom.slice(0, 200), text: [item.cause, item.action].filter(Boolean).join(' · ').slice(0, 1200) })
  if (!fields.length) throw new Error('No editable settings in this stage')
  return { stage, scene_id: state.sceneId, fields, evidence }
}

export function applyChanges(original: Snapshot, changes: Change[], current: Snapshot, updateSelection?: (changes: Change[]) => void) {
  assertEditable(original.stage)
  if (fingerprint(original) !== fingerprint(current)) throw new Error('Configuration changed. Generate a fresh proposal before applying it.')
  const fields = new Map(current.fields.map(field => [field.id, field]))
  if (!changes.length || new Set(changes.map(change => change.field_id)).size !== changes.length) throw new Error('Select at least one valid change')
  for (const change of changes) {
    const field = fields.get(change.field_id)
    if (!field || field.current !== change.before || change.after === null || !validValue(field, change.after)) throw new Error('A proposed value is no longer valid')
  }
  if (original.stage === 'req') {
    if (!updateSelection) throw new Error('Test selection editor unavailable')
    updateSelection(changes)
  } else {
    // One store update after validating the whole batch; no partial application.
    const updates = Object.fromEntries(changes.map(change => [change.field_id, fields.get(change.field_id)!.kind === 'enum' ? String(change.after) : Number(change.after)]))
    useAppStore.setState(state => ({ overrides: { ...state.overrides, ...updates }, touched: { ...state.touched, ...Object.fromEntries(changes.map(change => [change.field_id, true])) } }))
  }
}
