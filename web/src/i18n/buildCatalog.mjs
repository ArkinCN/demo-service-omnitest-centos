/** Rebuild approved display translations from local transcriptions. No network or model calls. */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const directory = path.dirname(fileURLToPath(import.meta.url))
const sourceRoot = path.resolve(directory, '..')
const documents = path.resolve(directory, '../../../docs/i18n')
const read = (name) => JSON.parse(fs.readFileSync(path.join(documents, name), 'utf8'))
const catalog = read('pro-first-en.json')
for (const entry of Object.values(read('pro-first-messages.json'))) {
  if (entry.en) catalog[entry.zh] = entry.en
}

const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
function restoreAnonymousSlots(entry, english) {
  if (entry.source === entry.text) return english
  // C009's reviewed upload removed one formatting space after a comma.
  // Restore its sole local filename explicitly, without broad fuzzy matching.
  if (entry.id === 'C009') {
    if (entry.source.replace('Customer.h', '{file}').replace('， 原理图', '，原理图') !== entry.text) {
      throw new Error('Unexpected reviewed local filename source in C009')
    }
    return english.replace('{file}', 'Customer.h')
  }
  const names = []
  let pattern = '^'
  let last = 0
  for (const match of entry.text.matchAll(/\{(?!v\d+\})([A-Za-z][A-Za-z0-9_]*)\}/g)) {
    pattern += escape(entry.text.slice(last, match.index)).replace(/\s+/g, '\\s+') + '([\\s\\S]*?)'
    names.push(match[1])
    last = match.index + match[0].length
  }
  pattern += escape(entry.text.slice(last)).replace(/\s+/g, '\\s+') + '$'
  const matched = new RegExp(pattern).exec(entry.source)
  if (!matched) throw new Error(`Cannot restore local source values for ${entry.id}`)
  const values = new Map()
  names.forEach((name, index) => {
    const list = values.get(name) ?? []
    list.push(matched[index + 1])
    values.set(name, list)
  })
  // These two reviewed bridge configuration messages use two distinct identifiers in order.
  if (entry.id === 'U1227' || entry.id === 'U1229') {
    const list = values.get('identifier')
    if (list?.join('|') !== 'VITE_BRIDGE_TOKEN|BRIDGE_TOKEN') throw new Error(`Unexpected reviewed identifiers in ${entry.id}`)
  }
  const offsets = new Map()
  return english.replace(/\{(?!v\d+\})([A-Za-z][A-Za-z0-9_]*)\}/g, (token, name) => {
    const list = values.get(name)
    if (!list) throw new Error(`Unknown anonymous slot ${token} in ${entry.id}`)
    const index = offsets.get(name) ?? 0
    offsets.set(name, index + 1)
    if (list.length > 1 && index >= list.length) throw new Error(`Repeated anonymous slot changed in ${entry.id}`)
    return list.length === 1 ? list[0] : list[index]
  })
}

if (fs.existsSync(path.join(documents, 'pro-additional-en.json'))) {
  const translated = read('pro-additional-en.json')
  for (const entry of read('additional-local-map.json').results) {
    if (typeof translated[entry.id] !== 'string') throw new Error(`Missing approved translation ${entry.id}`)
    catalog[entry.source] = restoreAnonymousSlots(entry, translated[entry.id])
  }
}
if (fs.existsSync(path.join(documents, 'pro-omission-en.json'))) {
  const translated = read('pro-omission-en.json')
  for (const entry of read('omission-local-map.json')) {
    if (typeof translated[entry.id] !== 'string') throw new Error(`Missing approved display alias ${entry.id}`)
    const source = entry.source ?? entry.text
    catalog[source] = restoreAnonymousSlots({ ...entry, source }, translated[entry.id])
  }
}
if (fs.existsSync(path.join(documents, 'pro-last-en.json'))) {
  const translated = read('pro-last-en.json')
  const safeText = Object.fromEntries(fs.readFileSync(path.join(documents, 'last-generic-ui.md'), 'utf8')
    .split(/\r?\n/).flatMap((line) => {
      const match = /^(C\d{3}):\s*(".*")$/.exec(line)
      return match ? [[match[1], JSON.parse(match[2])]] : []
    }))
  const sourceText = read('last-generic-local-map.json')
  const finalEntries = [...Array.from({ length: 10 }, (_, index) => {
    const id = `C${String(index + 1).padStart(3, '0')}`
    return { id, text: safeText[id], source: sourceText.find((entry) => entry.id === id)?.text ?? safeText[id] }
  }), ...read('last-display-alias-map.json')]
  for (const entry of finalEntries) {
    if (typeof translated[entry.id] !== 'string') throw new Error(`Missing approved display text ${entry.id}`)
    const source = entry.source ?? entry.text
    catalog[source] = restoreAnonymousSlots({ ...entry, source }, translated[entry.id])
  }
}
if (fs.existsSync(path.join(documents, 'pro-semantic-en.json'))) {
  Object.assign(catalog, read('pro-semantic-en.json'))
  const resistorKey = '母线分压电阻 {component1}/{component2}'
  const resistorLabel = catalog[resistorKey].replace('{component1}', 'RV1').replace('{component2}', 'RV2')
  catalog['母线分压电阻 RV1/RV2'] = resistorLabel
  // Source exposes separate values for the two physical components.
  // Root reviewed the grammatical singular of Pro's approved plural phrase.
  // The raw reference designator identifies the individual component.
  for (const component of ['RV1', 'RV2']) {
    const individualLabel = catalog[resistorKey].replace('resistors', 'resistor')
      .replace('{component1}/{component2}', component)
    catalog[`母线分压电阻 ${component}`] = individualLabel
    catalog[`母线分压电阻${component}`] = individualLabel
  }
  // Exact final QA labels: root reviewed these display-only semantic/grammar aliases.
  catalog['Omega 强拖启动'] = catalog['Omega强拖']
  catalog['Omega强拖启动'] = catalog['Omega强拖']
  catalog['不启用功率限制器'] = catalog['不启用电流限制器'].replace(/^Current /, 'Power ')
}
if (fs.existsSync(path.join(documents, 'pro-gate-en.json'))) {
  const translated = read('pro-gate-en.json')
  for (const [index, entry] of read('gate-local-map.json').entries()) {
    if (typeof translated[entry.text] !== 'string') throw new Error(`Missing approved final gate text ${index + 1}`)
    catalog[entry.source] = restoreAnonymousSlots({ ...entry, id: `gate-${index + 1}` }, translated[entry.text])
  }
}

// Existing source display normalization must reach the same approved alias.
const normalization = ts.transpileModule(fs.readFileSync(path.join(sourceRoot, 'features/shared/zh.ts'), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
}).outputText
const { simp } = await import('data:text/javascript;base64,' + Buffer.from(normalization).toString('base64'))
for (const [source, english] of Object.entries(catalog)) {
  const normalized = simp(source)
  if (!(normalized in catalog)) catalog[normalized] = english
}

// Recombine only static application source concatenations whose parts all have approved translations.
function translatedStatic(node) {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    return catalog[node.text] ? { source: node.text, english: catalog[node.text] } : undefined
  }
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const left = translatedStatic(node.left)
    const right = translatedStatic(node.right)
    if (left && right) {
      const separator = /[.!?]$/.test(left.english) && /^\w/.test(right.english) ? ' ' : ''
      return { source: left.source + right.source, english: left.english + separator + right.english }
    }
  }
}
function visitFiles(folder) {
  for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const filename = path.join(folder, entry.name)
    if (entry.isDirectory()) { if (entry.name !== 'i18n') visitFiles(filename); continue }
    if (!/\.tsx?$/.test(filename)) continue
    const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true)
    const visit = (node) => {
      if (ts.isBinaryExpression(node)) {
        const result = translatedStatic(node)
        if (result) catalog[result.source] = result.english
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
}
visitFiles(sourceRoot)
fs.writeFileSync(path.join(directory, 'catalog.ts'),
  '/** Approved official GPT-6 Pro translations; source values and display aliases stay separate. */\n' +
  'export const ENGLISH: Readonly<Record<string, string>> = ' + JSON.stringify(catalog, null, 2) + '\n')
process.stdout.write(`Approved catalog entries: ${Object.keys(catalog).length}\n`)
