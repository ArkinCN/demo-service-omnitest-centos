/**
 * 机翻兜底词典生成器 —— 扫描场景包里的中文数据文本，批量机翻，落盘成 autoCatalog.ts。
 *
 * 定位：`catalog.ts` 是**人工审核过的词典**（优先级最高，永不覆盖）；
 * 本脚本产出的 `autoCatalog.ts` 是**机翻兜底**，只在人工词典未命中时生效。
 * 不满意某条译文时，把它写进 `catalog.ts` 即可永久覆盖（重跑本脚本也不会动它）。
 *
 * 用法（在 `web/` 目录下执行）：
 *   node src/i18n/buildAutoCatalog.mjs            # 增量：只翻缺的，已有译文复用
 *   node src/i18n/buildAutoCatalog.mjs --force    # 全量重译
 *   node src/i18n/buildAutoCatalog.mjs --dry      # 只盘点不翻译（看规模与 token 估算）
 *
 * 设计要点：
 * 1. **只采集人类可读字段**（白名单），路径 / ID / 型号 / 标准号一律不译（沿用项目既有约定）。
 * 2. **已存在于人工词典的串直接跳过**（含 simp 繁简归一后比对），人工永不被机翻覆盖。
 * 3. **术语表按批次召回**：从人工词典 + 场景包已有 `*_en` 平行字段提取「中文→英文」对，
 *    只把与当前批次字符相关的 Top-K 注入 prompt，避免全量注入浪费 token 并稀释注意力。
 * 4. **严格校验**：返回必须是合法 JSON、key 集合与请求一致、值非空；
 *    含中文的值标记为可疑（记入对照表供人工优先复核），不静默丢弃。
 * 5. 零新增依赖：用 Node 内置 fetch 调 LLM，自行解析 backend/.env。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(here, '../..')
const scenesDir = path.join(webRoot, 'public/scenes')
const catalogPath = path.join(here, 'catalog.ts')
const outPath = path.join(here, 'autoCatalog.ts')
const reportDir = path.join(webRoot, '.codebuddy')
/** 中断续跑用的进度文件（逐批落盘，跑完删除） */
const PROGRESS_PATH = path.join(reportDir, 'auto-i18n.progress.json')
const envPath = path.resolve(webRoot, '../backend/.env')

const FORCE = process.argv.includes('--force')
const DRY = process.argv.includes('--dry')

/** 需要翻译的字段名白名单（人类可读文本） */
const TEXT_FIELDS = new Set([
  'title', 'name', 'label', 'note', 'description', 'summary', 'purpose', 'group',
  'criterion_text', 'criterion', 'symptom', 'cause', 'action', 'result', 'quote',
  'prompt', 'echo', 'success_feedback', 'hint', 'text', 'message', 'caption',
  'display_name', 'action_label', 'reason', 'risk', 'mitigation', 'scope', 'precondition',
  // 2026-10-15 补：知识库条目详情与分类字段（用户截图右栏那批中文值）
  'type', 'kind', 'status', 'usage_class', 'usageClass', 'doc_type', 'docType',
  'evidence_level', 'evidenceLevel', 'conversion', 'usage', 'origin',
  'verdict_text', 'verdictText', 'why', 'tag', 'meta',
  // 图例 / 状态说明这类「映射对象」（值是中文说明句，如
  // conversion_status_legend.not_converted = "尚未做文档→知识库的转化"）
  'conversion_status_legend', 'conversion_status_note', 'conversion_status_label',
])

/**
 * 字段名黑名单：即使命中白名单也跳过。
 *
 * ⚠️ 只保留「**即使含中文也不该译**」的键——路径、文件名、URL、标识符。
 * 早期版本把 `type`/`kind`/`unit` 也列在这里，导致 `type: "调试记录"` 这类
 * **中文枚举值**被误跳过（实测：知识库列表整列仍是中文）。
 * 现在这些键已移出黑名单：不含中文的值由上方 `!CJK.test(node)` 自动过滤，
 * 无需靠黑名单兜底。
 */
const SKIP_FIELDS = new Set([
  'id', 'key', 'code', 'path', 'url', 'href', 'file', 'filename', 'artifact',
  'checksum', 'hash', 'schema', 'scene_id',
])

const CJK = /[\u4e00-\u9fff]/
/** 不译内容形态：纯标识符 / 文件路径 / 标准号 / 单位 / 代码 */
function looksUntranslatable(s) {
  if (/^[\w.\-/\\:]+$/.test(s)) return true // 无空格无中文的标识符
  if (/\[(源|Source)\]/.test(s) && /\.\w{2,5}$/.test(s)) return true // `[源] xxx/yyy.pdf`
  if (/^[A-Z]{2,}(-[A-Z0-9]+)+$/.test(s)) return true // DOC-MAN-001
  if (/^(GB|IEC|ISO|EN|SAE|JIS|UL|TB|QC)[\s/-]*\d/.test(s)) return true // 标准号
  // 连字符写在字符类末尾，无需转义（写成 `\-` 会触发 no-useless-escape）
  if (/^[\d.\s±≤≥<>=~%°℃μΩa-zA-Z/().,-]*$/.test(s)) return true // 纯数值/单位表达式
  if (s.length > 300) return true // 超长段落（多为整段说明，机翻质量差且费 token）
  return false
}

/** 读取文本文件 */
const readText = (p) => fs.readFileSync(p, 'utf8')

/** 用 typescript 转译 TS 模块再动态 import（复用仓库既有取 simp 的做法） */
async function loadTsModule(file) {
  const out = ts.transpileModule(readText(file), {
    compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
  }).outputText
  return import('data:text/javascript;base64,' + Buffer.from(out).toString('base64'))
}

/** 解析 backend/.env（只取值，不引入 dotenv 依赖） */
function loadEnv(file) {
  const env = {}
  if (!fs.existsSync(file)) return env
  for (const line of readText(file).split(/\r?\n/)) {
    const m = /^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$/.exec(line.trim())
    if (!m) continue
    let v = m[2].trim()
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1)
    env[m[1]] = v
  }
  return env
}

/**
 * 组装 LLM 配置。
 *
 * ⚠️ 两个与后端 `config.py:188-199` 对齐的坑（那里有明确注释，2026-09-23 踩过）：
 * 1. **base_url 不要带 `/v1`** —— 上游路径是 `{base}/v1/chat/completions`，
 *    再带 /v1 会拼成 `/api/v1/v1/chat/completions` → OpenRouter 返回 404。
 * 2. **`MOTORDEBUG_LLM_FAST_MODEL` 常为空**（.env 里写成 `X=`），必须回落到
 *    `MOTORDEBUG_LLM_MODEL`；否则 model 传空串同样 404。
 */
function llmConfig(env) {
  const base = (env.MOTORDEBUG_LLM_BASE_URL ?? '').trim().replace(/\/+$/, '')
  // 容错：若有人误在 base 里写了 /v1，剥掉，保证只拼一次
  const normalizedBase = base.replace(/\/v1$/, '')
  return {
    baseUrl: normalizedBase,
    apiKey: (env.MOTORDEBUG_LLM_API_KEY ?? '').trim(),
    model: (env.MOTORDEBUG_LLM_FAST_MODEL ?? '').trim() || (env.MOTORDEBUG_LLM_MODEL ?? '').trim(),
    timeoutMs: 90_000,
  }
}

/** 递归收集所有 JSON 文件 */
function walkJson(dir) {
  const out = []
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) out.push(...walkJson(p))
    else if (e.name.endsWith('.json')) out.push(p)
  }
  return out
}

/** 递归遍历 JSON，按字段白名单收集中文串 */
function collect(node, field, sink) {
  if (typeof node === 'string') {
    if (!field || SKIP_FIELDS.has(field) || !TEXT_FIELDS.has(field)) return
    if (!CJK.test(node)) return
    if (looksUntranslatable(node)) return
    sink.add(node)
    return
  }
  if (Array.isArray(node)) { for (const x of node) collect(x, field, sink); return }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) collect(v, k, sink)
  }
}

/** 递归收集场景包里既有的 `*_en` 平行英文字段，作为术语参考 */
function collectParallelEn(node, sink) {
  if (node && typeof node === 'object' && !Array.isArray(node)) {
    const zh = node.name ?? node.title ?? node.label
    const en = node.name_en ?? node.title_en ?? node.label_en ?? node.section_en
    if (typeof zh === 'string' && typeof en === 'string' && CJK.test(zh) && !CJK.test(en)) {
      sink.set(zh, en)
    }
    // fields / fields_en 同序同长
    if (Array.isArray(node.fields) && Array.isArray(node.fields_en)) {
      node.fields.forEach((f, i) => {
        const e = node.fields_en[i]
        if (typeof f === 'string' && typeof e === 'string' && CJK.test(f) && !CJK.test(e)) sink.set(f, e)
        if (f && typeof f === 'object' && e && typeof e === 'object') {
          const fz = f.name, fe = e.name
          if (typeof fz === 'string' && typeof fe === 'string' && CJK.test(fz) && !CJK.test(fe)) sink.set(fz, fe)
        }
      })
    }
    for (const v of Object.values(node)) collectParallelEn(v, sink)
    return
  }
  if (Array.isArray(node)) { for (const x of node) collectParallelEn(x, sink) }
}

/** 从一批中文串里按字符交集召回相关术语（最多 limit 条） */
function recallGlossary(batch, glossary, limit = 60) {
  const chars = new Set()
  for (const s of batch) for (const c of s) if (CJK.test(c)) chars.add(c)
  const scored = []
  for (const [zh, en] of glossary) {
    let hit = 0
    for (const c of new Set(zh)) if (chars.has(c)) hit++
    if (hit > 0) scored.push({ zh, en, score: hit / Math.max(1, new Set(zh).size) })
  }
  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, limit)
}

/**
 * 带超时的 fetch。
 *
 * ⚠️ 必须显式加超时（2026-10-15 踩到）：裸 `fetch` 遇到网络挂起会**永久阻塞**，
 * 脚本卡在 350/1236 一动不动，日志 74 秒无输出。有了超时才能进重试分支。
 */
async function fetchWithTimeout(url, options, timeoutMs) {
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: ac.signal })
  } finally {
    clearTimeout(timer)
  }
}

/** 调 LLM 翻译一批（返回 { 中文: 英文 }） */
async function translateBatch(batch, glossary, cfg) {
  const glos = recallGlossary(batch, glossary)
  const glosText = glos.length
    ? '\n\n【术语表（必须优先采用这些译法）】\n' + glos.map((g) => `${g.zh} => ${g.en}`).join('\n')
    : ''
  const sys = '你是工业测试领域的专业中译英译者。把用户给出的 JSON 数组里的每个中文串翻成英文。' +
    '要求：1) 术语严格遵循下方术语表；2) 保留原文里的数字、单位、标准号、型号、代码标识符（如 DOC-MAN-001、GB 11555）不变；' +
    '3) 译文简洁专业，用于软件界面显示，不要添加解释；4) 只输出 JSON 对象，key 是中文原文，value 是英文译文，不要输出任何其他内容。' +
    glosText
  const body = {
    model: cfg.model,
    messages: [
      { role: 'system', content: sys },
      { role: 'user', content: JSON.stringify(batch) },
    ],
    temperature: 0,
    response_format: { type: 'json_object' },
  }
  const resp = await fetchWithTimeout(
    cfg.baseUrl.replace(/\/$/, '') + '/v1/chat/completions',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.apiKey}` },
      body: JSON.stringify(body),
    },
    cfg.timeoutMs,
  )
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 300)}`)
  const json = await resp.json()
  const content = json.choices?.[0]?.message?.content ?? ''
  const parsed = JSON.parse(content)
  const out = {}
  for (const zh of batch) {
    const en = parsed[zh]
    if (typeof en === 'string' && en.trim()) out[zh] = en.trim()
  }
  return out
}

async function main() {
  // ── 1. 载入人工词典与 simp ──
  const { ENGLISH } = await loadTsModule(catalogPath)
  const { simp } = await loadTsModule(path.join(webRoot, 'src/features/shared/zh.ts'))
  const catalogKeys = new Set(Object.keys(ENGLISH))
  const catalogSimp = new Set([...catalogKeys].map((k) => simp(k)))

  // ── 2. 采集场景包中文串 + 平行英文字段（术语参考）──
  const zhSet = new Set()
  const glossary = new Map()
  for (const f of walkJson(scenesDir)) {
    let json
    try { json = JSON.parse(readText(f)) } catch { continue }
    collect(json, null, zhSet)
    collectParallelEn(json, glossary)
  }
  // 人工词典本身也是最好的术语来源
  for (const [zh, en] of Object.entries(ENGLISH)) {
    if (CJK.test(zh) && !CJK.test(en) && !glossary.has(zh)) glossary.set(zh, en)
  }

  // ── 3. 过滤：人工词典已有的跳过 ──
  const missing = [...zhSet].filter((s) => !catalogKeys.has(s) && !catalogSimp.has(s))
  missing.sort()

  // ── 4. 载入已有译文（增量复用）──
  //
  // 两个来源：① 已落盘的 autoCatalog.ts（上一轮完整跑完的成果）
  //          ② 进度文件（上一轮**中途被中断**时逐批存下的成果）
  // 后者是必需的：早期版本只在全部翻完后才落盘，中断一次就白跑（实测踩到）。
  let existing = {}
  if (fs.existsSync(outPath) && !FORCE) {
    const mod = await loadTsModule(outPath)
    existing = { ...(mod.AUTO_ENGLISH ?? {}) }
  }
  if (fs.existsSync(PROGRESS_PATH) && !FORCE) {
    try {
      existing = { ...JSON.parse(readText(PROGRESS_PATH)), ...existing }
    } catch { /* 进度文件损坏则忽略 */ }
  }
  const todo = missing.filter((s) => !existing[s])

  process.stdout.write(
    `场景包中文串 ${zhSet.size} 条；人工词典已覆盖 ${zhSet.size - missing.length} 条；` +
    `待机翻 ${missing.length} 条；已有译文 ${Object.keys(existing).length} 条；` +
    `本轮需翻 ${todo.length} 条；术语表 ${glossary.size} 条\n`,
  )

  if (DRY) {
    const chars = todo.reduce((s, x) => s + x.length, 0)
    process.stdout.write(`--dry：预计输入约 ${chars} 字符（≈${Math.ceil(chars / 1.5)} tokens），跳过翻译与落盘\n`)
    return
  }
  if (!todo.length) {
    process.stdout.write('无需翻译，直接重写落盘文件\n')
  }

  // ── 5. 分批翻译 ──
  const env = loadEnv(envPath)
  const cfg = llmConfig(env)
  if (todo.length && (!cfg.baseUrl || !cfg.apiKey || !cfg.model)) {
    throw new Error(
      `缺少 LLM 配置（${envPath}）：need baseUrl/apiKey/model，实得 ` +
      `base=${cfg.baseUrl ? 'ok' : 'EMPTY'} key=${cfg.apiKey ? 'ok' : 'EMPTY'} model=${cfg.model || 'EMPTY'}`,
    )
  }

  // 批次大小与并发度（2026-10-15 调优）：
  // 原为 BATCH=25 串行，实测 17 分钟才跑 125 条（全量要 ~2.8 小时）——
  // 长中文句的**输出 token 多**，单批 25 条一次要吐几千 token，慢且易超时。
  // 改为小批次 + 并发，吞吐显著提升。
  const BATCH = 12
  const CONCURRENCY = 4
  const stamp = () => new Date().toTimeString().slice(0, 8)
  const translated = { ...existing }
  const suspicious = []
  const failed = []

  const batches = []
  for (let i = 0; i < todo.length; i += BATCH) batches.push(todo.slice(i, i + BATCH))

  let doneCount = 0
  const runBatch = async (batch) => {
    let got = null
    for (let attempt = 1; attempt <= 2 && !got; attempt++) {
      try {
        got = await translateBatch(batch, glossary, cfg)
      } catch (e) {
        process.stdout.write(`  [${stamp()}] 批次失败（第 ${attempt} 次）：${e.message}\n`)
        if (attempt === 2) failed.push(...batch)
      }
    }
    if (got) {
      for (const [zh, en] of Object.entries(got)) {
        if (CJK.test(en)) suspicious.push({ zh, en }) // 译文仍含中文：保留但标记
        translated[zh] = en
      }
      // 逐批落盘：中断后可续跑（早期版本只在全部翻完后才落盘，中断一次就白跑）
      fs.mkdirSync(reportDir, { recursive: true })
      fs.writeFileSync(PROGRESS_PATH, JSON.stringify(translated), 'utf8')
    }
    doneCount += batch.length
    process.stdout.write(`  [${stamp()}] 进度 ${doneCount}/${todo.length}\n`)
  }

  // 简单并发池：保持 CONCURRENCY 个批次同时在飞
  const queue = [...batches]
  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
      while (queue.length) {
        const b = queue.shift()
        if (!b) break
        await runBatch(b)
      }
    }),
  )

  // ── 6. 落盘（按 key 排序，便于 diff）──
  const sorted = Object.fromEntries(Object.entries(translated).sort((a, b) => a[0].localeCompare(b[0], 'zh')))
  const header =
    '/**\n' +
    ' * 机翻兜底词典 —— 自动生成，请勿手改。\n' +
    ' *\n' +
    ' * 用途：英文界面下，`catalog.ts`（人工审核词典）未命中时的兜底译文。\n' +
    ' * 手改译文请写到 `catalog.ts`（优先级更高，重跑本脚本也不会覆盖人工条目）。\n' +
    ' * 重跑：在 `web/` 目录执行 `node src/i18n/buildAutoCatalog.mjs`（加 --force 全量重译）。\n' +
    ' */\n'
  fs.writeFileSync(outPath, header + 'export const AUTO_ENGLISH: Readonly<Record<string, string>> = ' +
    JSON.stringify(sorted, null, 2) + '\n')

  // ── 7. 产出对照表供人工抽检 ──
  fs.mkdirSync(reportDir, { recursive: true })
  const csv = ['中文原文,英文译文,标记', ...[...Object.entries(sorted)]
    .map(([zh, en]) => `"${zh.replace(/"/g, '""')}","${String(en).replace(/"/g, '""')}","${CJK.test(en) ? '译文含中文' : ''}"`)]
    .join('\n')
  fs.writeFileSync(path.join(reportDir, 'auto-i18n.review.csv'), '\ufeff' + csv, 'utf8')

  // 全部成功落盘后清理进度文件（下次重跑从 autoCatalog.ts 复用即可）
  if (fs.existsSync(PROGRESS_PATH)) fs.unlinkSync(PROGRESS_PATH)

  process.stdout.write(
    `\n落盘 ${outPath}\n共 ${Object.keys(sorted).length} 条；译文仍含中文 ${suspicious.length} 条；` +
    `翻译失败 ${failed.length} 条\n对照表 ${path.join(reportDir, 'auto-i18n.review.csv')}\n`,
  )
}

await main()
