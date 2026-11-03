/**
 * 从峰岹现场工作流目录生成 public/data/wfw/ 与 public/data/workflows.json。
 *
 * 源目录（只读，不修改客户原文件）：
 *   主流程  .../ClientSoftware/WORKINGflow/WORKINGflow          58 个 .wfw
 *   子流程  .../ClientSoftware/子流程/子流程                     9 个 .wfw
 *   附加    .../测试数据_20260622/SCOPETEST_时序采集_v1.wfw      1 个 .wfw
 *
 * 用法：node scripts/buildIndex.mjs [源根目录]
 */
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, readdirSync, statSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.join(HERE, '..', 'public', 'data')
const WFW_DIR = path.join(OUT_DIR, 'wfw')

const SRC_ROOT = process.argv[2] ?? '[源] archive-POC/40_工程'
const SOURCES = [
  { label: 'main', dir: path.join(SRC_ROOT, 'ClientSoftware/WORKINGflow/WORKINGflow'), sub: false },
  { label: 'subflow', dir: path.join(SRC_ROOT, 'ClientSoftware/子流程/子流程'), sub: true },
  { label: 'extra', dir: path.join(SRC_ROOT, '测试数据_20260622'), sub: false, only: /^SCOPETEST_时序采集/ },
]

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (name.toLowerCase().endsWith('.wfw')) out.push(p)
  }
  return out
}

function readWfw(file) {
  let buf = readFileSync(file)
  const compressed = buf[0] === 0x1f && buf[1] === 0x8b
  if (compressed) buf = gunzipSync(buf)
  let text = buf.toString('utf8')
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1)
  return { json: JSON.parse(text), compressed }
}

/** 从文件名与目录推断电压档。HSLV 必须先于 LV 匹配，否则会被误判。 */
function voltageOf(relPath) {
  const s = relPath.toUpperCase()
  const hits = []
  if (/HSLV/.test(s)) hits.push('HSLV')
  if (/(^|[^S])HV/.test(s.replace(/HSLV/g, ''))) hits.push('HV')
  if (/SV/.test(s.replace(/HSLV/g, ''))) hits.push('SV')
  if (/LV/.test(s.replace(/HSLV/g, ''))) hits.push('LV')
  const uniq = [...new Set(hits)]
  if (uniq.length === 0) return 'N/A'
  if (uniq.length === 1) return uniq[0]
  // HV_SV_LV_* 这类三档合一的调度流程。
  return 'MIXED'
}

/** 业务分组：主流程取一级目录名，子流程统一归「子流程」。 */
function groupOf(relPath, isSub) {
  if (isSub) return '子流程'
  const first = relPath.split(path.sep)[0]
  return first.toLowerCase().endsWith('.wfw') ? '根目录' : first
}

/** 文件名去扩展名作为展示名——样例 metadata.name 几乎全是占位值「新工作流」。 */
function displayName(file, meta) {
  const stem = path.basename(file, path.extname(file)).trim()
  const metaName = typeof meta?.name === 'string' ? meta.name.trim() : ''
  return metaName && metaName !== '新工作流' ? metaName : stem
}

mkdirSync(WFW_DIR, { recursive: true })

const entries = []
const failures = []
let totalBytes = 0

for (const src of SOURCES) {
  let files
  try {
    files = walk(src.dir)
  } catch (err) {
    failures.push({ dir: src.dir, error: String(err.message ?? err) })
    continue
  }
  if (src.only) files = files.filter((f) => src.only.test(path.basename(f)))

  for (const file of files.sort()) {
    const rel = path.relative(src.dir, file)
    try {
      const { json, compressed } = readWfw(file)
      const def = json.definition ?? {}
      const nodes = Array.isArray(def.nodes) ? def.nodes : []
      const edges = Array.isArray(def.edges) ? def.edges : []

      // 展平到 <label>/<原相对路径>，避免子流程与主流程重名互相覆盖。
      const outRel = path.posix.join(src.label, rel.split(path.sep).join('/'))
      const outAbs = path.join(WFW_DIR, outRel)
      mkdirSync(path.dirname(outAbs), { recursive: true })
      copyFileSync(file, outAbs)
      totalBytes += statSync(outAbs).size

      entries.push({
        id: outRel.replace(/[^\w一-龥]+/g, '_').replace(/_+/g, '_'),
        name: displayName(file, json.metadata),
        group: groupOf(rel, src.sub),
        voltage: voltageOf(rel),
        file: outRel,
        nodeCount: nodes.length,
        edgeCount: edges.length,
        isSubflow: src.sub,
        compressed,
      })
    } catch (err) {
      failures.push({ file, error: String(err.message ?? err) })
    }
  }
}

writeFileSync(
  path.join(OUT_DIR, 'workflows.json'),
  JSON.stringify({ generatedAt: new Date().toISOString(), count: entries.length, workflows: entries }, null, 2),
)

const mb = (totalBytes / 1048576).toFixed(2)
console.log(`索引条目 ${entries.length} 个，主流程 ${entries.filter((e) => !e.isSubflow).length}，子流程 ${entries.filter((e) => e.isSubflow).length}`)
console.log(`拷贝 .wfw 总大小 ${mb} MB`)
console.log(`节点总数 ${entries.reduce((s, e) => s + e.nodeCount, 0)}，连线总数 ${entries.reduce((s, e) => s + e.edgeCount, 0)}`)
if (failures.length) {
  console.error(`解析失败 ${failures.length} 个：`)
  for (const f of failures) console.error('  ', f.file ?? f.dir, f.error)
  process.exitCode = 1
}
