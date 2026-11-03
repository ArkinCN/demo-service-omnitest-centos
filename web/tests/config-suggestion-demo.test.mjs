import assert from 'node:assert/strict'
import test from 'node:test'
import { createDemoChanges } from '../src/features/config-suggestions/demo.ts'
import { validateProposal } from '../src/features/config-suggestions/protocol.ts'

function fixture(stage = 'init', patch = {}) {
  const id = stage === 'init' ? 'init.pa.motor.pole_pairs' : stage === 'run' ? 'run.cp.start.nonemode_speed' : 'req.TR-START-01'
  const field = { id, name: 'Demo fixture', kind: stage === 'req' ? 'selection' : 'number', current: stage === 'req' ? true : stage === 'run' ? 4000 : 2, minimum: 0, maximum: stage === 'run' ? 6000 : 10, step: 1, precision: 0, options: [], unit: '', ...patch }
  return { stage, scene_id: 'synthetic-test', fields: [field], evidence: [{ id: stage === 'req' ? 'criterion:TR-START-01' : 'field:' + id, title: 'Fixture', text: 'Synthetic metadata' }] }
}

test('init changes known numeric pole pairs with actual evidence and explicit synthetic reason', () => {
  const snapshot = fixture()
  const changes = createDemoChanges(snapshot)
  assert.equal(changes[0].before, 2)
  assert.equal(changes[0].after, 6)
  assert.deepEqual(changes[0].evidence_ids, ['field:init.pa.motor.pole_pairs'])
  assert.match(changes[0].reason, /人为注入/)
  assert.match(changes[0].reason, /不是模型建议/)
  validateProposal({ summary: 'Synthetic draft', changes, questions: [] }, snapshot)
})
test('already targeted values get a distinct legal alternative', () => {
  assert.equal(createDemoChanges(fixture('init', { current: 6 }))[0].after, 7)
  assert.equal(createDemoChanges(fixture('run', { current: 1000 }))[0].after, 1100)
})
test('run changes only speed and never substitutes a current field', () => {
  assert.equal(createDemoChanges(fixture('run'))[0].after, 1000)
  assert.deepEqual(createDemoChanges(fixture('run', { id: 'run.cp.start.motor_start_iq_current' })), [])
})
test('missing target or evidence produces no invented configuration', () => {
  assert.deepEqual(createDemoChanges({ ...fixture(), fields: [] }), [])
  assert.deepEqual(createDemoChanges({ ...fixture(), evidence: [] }), [])
  assert.deepEqual(createDemoChanges(fixture('init', { id: 'init.pa.other' })), [])
})
test('requirement can only deselect the known selected criterion', () => {
  const changes = createDemoChanges(fixture('req'))
  assert.equal(changes[0].after, false)
  assert.deepEqual(changes[0].evidence_ids, ['criterion:TR-START-01'])
  for (const current of [false, 'true', 1, null]) assert.deepEqual(createDemoChanges(fixture('req', { current })), [])
})
test('reject mismatched kinds and unsupported current numeric values', () => {
  for (const patch of [{ kind: 'enum' }, { current: '2' }, { current: NaN }, { current: -1 }]) assert.deepEqual(createDemoChanges(fixture('init', patch)), [])
  assert.deepEqual(createDemoChanges(fixture('req', { kind: 'number' })), [])
})
test('respect maximum, minimum and step including alternate target constraints', () => {
  for (const patch of [{ maximum: 2 }, { minimum: 7, current: 8 }, { step: 4, current: 4 }, { current: 6, maximum: 6 }]) assert.deepEqual(createDemoChanges(fixture('init', patch)), [])
  assert.deepEqual(createDemoChanges(fixture('run', { maximum: 500, current: 400 })), [])
  assert.deepEqual(createDemoChanges(fixture('run', { step: 300, current: 3900 })), [])
})
test('frozen input stays unchanged and output is a separate draft', () => {
  const snapshot = fixture()
  const original = JSON.stringify(snapshot)
  for (const field of snapshot.fields) { Object.freeze(field.options); Object.freeze(field) }
  for (const item of snapshot.evidence) Object.freeze(item)
  Object.freeze(snapshot.fields); Object.freeze(snapshot.evidence); Object.freeze(snapshot)
  const changes = createDemoChanges(snapshot)
  changes[0].after = 9
  assert.equal(JSON.stringify(snapshot), original)
})
// 2026-10-29：原「controlled model identifier is exact」断言已删除。
// 模型 id 不再在前端写死（由后端 .env 派生、经 /api/agent/models 下发），
// 因此前端没有可断言的常量；对应的行为约束改为：
// 「只用列表首项（平台主模型），不随机挑、失败时不静默换模型」。
