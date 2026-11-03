/** 用发布用的解析逻辑跑一遍全部 .wfw，报告解析成功率与节点类型覆盖。 */
import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DATA = path.join(HERE, '..', 'public', 'data')
const index = JSON.parse(readFileSync(path.join(DATA, 'workflows.json'), 'utf8'))

const { NODE_TYPE_GROUP, LEGACY_NODE_TYPE_GROUP } = await import(
  '../src/features/workflow/lib/nodeCatalog.ts'
).catch(() => ({ NODE_TYPE_GROUP: null, LEGACY_NODE_TYPE_GROUP: null }))

const typeTally = new Map()
const rows = []
let ok = 0
let failed = 0

for (const entry of index.workflows) {
  const file = path.join(DATA, 'wfw', entry.file)
  try {
    let buf = readFileSync(file)
    if (buf[0] === 0x1f && buf[1] === 0x8b) buf = gunzipSync(buf)
    let text = buf.toString('utf8')
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
    const json = JSON.parse(text)
    const def = json.definition ?? {}
    const nodes = def.nodes ?? []
    const ids = new Set(nodes.map((n) => n.id))
    const edges = (def.edges ?? []).filter((e) => ids.has(e.source) && ids.has(e.target))
    const dangling = (def.edges ?? []).length - edges.length
    const embedded = nodes.filter((n) => n?.data?.embeddedWorkflow).length
    for (const n of nodes) typeTally.set(n.type, (typeTally.get(n.type) ?? 0) + 1)
    rows.push({ ...entry, parsedNodes: nodes.length, parsedEdges: edges.length, dangling, embedded })
    ok++
  } catch (err) {
    rows.push({ ...entry, error: String(err.message ?? err) })
    failed++
  }
}

const main = rows.filter((r) => !r.isSubflow)
const sub = rows.filter((r) => r.isSubflow)
const sum = (a, k) => a.reduce((s, r) => s + (r[k] ?? 0), 0)

console.log('=== 解析成功率 ===')
console.log(`总计 ${rows.length} 个文件，成功 ${ok}，失败 ${failed}（${((ok / rows.length) * 100).toFixed(1)}%）`)
console.log(`主流程 ${main.length} 个：${sum(main, 'parsedNodes')} 节点 / ${sum(main, 'parsedEdges')} 连线`)
console.log(`子流程 ${sub.length} 个：${sum(sub, 'parsedNodes')} 节点 / ${sum(sub, 'parsedEdges')} 连线`)
console.log(`内嵌子流程节点 ${sum(rows, 'embedded')} 个，悬空连线 ${sum(rows, 'dangling')} 条`)

console.log('\n=== 节点类型覆盖 ===')
const known = new Set(Object.keys(NODE_TYPE_GROUP ?? {}))
const legacy = new Set(Object.keys(LEGACY_NODE_TYPE_GROUP ?? {}))
for (const [t, c] of [...typeTally].sort((a, b) => b[1] - a[1])) {
  const flag = known.has(t) ? '' : legacy.has(t) ? '  [枚举外·已兜底]' : '  [未识别]'
  console.log(`  ${String(c).padStart(4)}  ${t}${flag}`)
}
console.log(`出现 ${typeTally.size} 种类型；类型目录收录 ${known.size} 种 + ${legacy.size} 种历史遗留`)

console.log('\n=== 逐文件 ===')
for (const r of rows) {
  if (r.error) console.log(`  ✗ ${r.file}  ${r.error}`)
  else console.log(`  ✓ ${String(r.parsedNodes).padStart(3)}n ${String(r.parsedEdges).padStart(3)}e  ${r.voltage.padEnd(5)} ${r.file}`)
}
