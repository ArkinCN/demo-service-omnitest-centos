import assert from 'node:assert/strict'
import test from 'node:test'
import { fingerprint, validateProposal } from '../src/features/config-suggestions/protocol.ts'

const snapshot = { stage: 'init', scene_id: 'fixture', fields: [{ id: 'init.cp.current', name: 'Current', kind: 'number', current: 1, minimum: 0, maximum: 2, step: 0.1, precision: 1, options: [], unit: 'A' }], evidence: [{ id: 'source', title: 'Source', text: 'Fixture only' }] }
const proposal = () => ({ summary: 'Review', changes: [{ field_id: 'init.cp.current', before: 1, after: 1.2, reason: 'Evidence', evidence_ids: ['source'] }], questions: [] })
test('valid typed proposal and legitimate no-change result', () => {
  assert.equal(validateProposal(proposal(), snapshot).changes.length, 1)
  assert.equal(validateProposal({ summary: 'No evidence', changes: [], questions: [] }, snapshot).changes.length, 0)
})
for (const after of [true, '1.2', null, NaN, Infinity, -1, 3, 1.25, 1]) test(`reject invalid value ${String(after)}`, () => {
  const value = proposal(); value.changes[0].after = after
  assert.throws(() => validateProposal(value, snapshot))
})
test('reject unknown fields, duplicate changes and unsupported evidence', () => {
  for (const patch of [{ field_id: 'run.cp.other' }, { before: 0 }, { evidence_ids: ['invented'] }, { execute: true }]) {
    const value = proposal(); Object.assign(value.changes[0], patch)
    assert.throws(() => validateProposal(value, snapshot))
  }
  const value = proposal(); value.changes.push({ ...value.changes[0] })
  assert.throws(() => validateProposal(value, snapshot))
})
test('whole snapshot identity detects changes outside selected field and scene', () => {
  assert.notEqual(fingerprint(snapshot), fingerprint({ ...snapshot, scene_id: 'other' }))
  assert.notEqual(fingerprint(snapshot), fingerprint({ ...snapshot, fields: [...snapshot.fields, { ...snapshot.fields[0], id: 'init.cp.other', current: 4 }] }))
})
test('reject a fraction that would be rounded by the original integer editor', () => {
  const integer = { ...snapshot, fields: [{ ...snapshot.fields[0], step: null, precision: 0 }] }
  const value = proposal(); value.changes[0].after = 1.5
  assert.throws(() => validateProposal(value, integer))
})
