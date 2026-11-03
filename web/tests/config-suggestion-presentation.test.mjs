import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatSuggestionValue, visibleQuestions, uniqueEvidenceIds } from '../src/features/config-suggestions/presentation.ts'

const field = { kind: 'number', unit: 'mA' }
test('both comparison values retain units and original precision', () => {
  assert.equal(formatSuggestionValue(field, 0.123456789, 'en'), '0.123456789 mA')
  assert.equal(formatSuggestionValue(field, 0, 'zh-CN'), '0 mA')
  assert.equal(formatSuggestionValue(field, null, 'en'), '—')
})
test('test inclusion is different from a boolean enum', () => {
  assert.equal(formatSuggestionValue({kind:'selection',unit:''}, false, 'en'), 'Excluded')
  assert.equal(formatSuggestionValue({kind:'enum',unit:''}, false, 'en'), 'false')
})
test('display filtering leaves original evidence and questions untouched', () => {
  const ids = Object.freeze(['field:x','field:x','experience:y'])
  const questions = Object.freeze([' ', 'A question\nwith detail'])
  assert.deepEqual(uniqueEvidenceIds(ids), ['field:x','experience:y'])
  assert.deepEqual(visibleQuestions(questions), ['A question\nwith detail'])
  assert.equal(ids.length, 3)
  assert.equal(questions.length, 2)
})
