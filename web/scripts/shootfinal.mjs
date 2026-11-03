/**
 * 收尾交付截图：五个流程页加知识库页各 1920×1080 + 1440×810，
 * 放大态三张，汽车包两张。
 *   npm run build && npm run preview   然后   node scripts/shootfinal.mjs
 * 环境变量：BASE（默认 http://localhost:4173）、ONLY（只出某一张）、PREFIX（默认 final）、OUTDIR（输出目录名，默认 shots2）
 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const OUT = new URL(`../${process.env.OUTDIR ?? 'shots2'}/`, import.meta.url).pathname
const P = process.env.PREFIX ?? 'final'
mkdirSync(OUT, { recursive: true })

const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)
if (!exe) throw new Error('本机未找到 Chrome')

const MOTOR = 'motor.cooling-fan.fortior-fu6832'
const AUTO = 'automotive.body-motor.window-regulator'
const PAGES = [
  ['init', '/init'],
  ['req', '/requirements'],
  ['run', '/run'],
  ['tune', '/tune'],
  ['report', '/report'],
  // 知识库是模块不是流程，排在五步之后单独出一张
  ['knowledge', '/knowledge'],
]

/** 放大态：点开某张卡的「放大」按钮再截。
    第三项可以是卡槽序号，也可以给一段文字——按文字挑画板上那个节点，
    免得默认挑到「被测对象」这种放大后只有一行字的事实型节点。 */
const ZOOM = [
  ['zoom-canvas', '/requirements', '工作流画布'],
  ['zoom-timeseries', '/run', 0],
  // 原先这一项写的是 ['zoom-evidence', '/knowledge', 1]：知识库模块页改成
  // 「左筛选 / 中列表 / 右详情」三栏之后已经没有任何放大按钮，点击必然失败，
  // 从前被 .catch(() => {}) 吞掉，照旧出一张与 final-knowledge 几乎一样的图。
  // 真正的「知识依据放大态」在流程 2 的画板上：双击「知识库依据」节点开浮层。
  ['zoom-evidence', '/requirements', '知识库依据'],
]

/** 静默失败是这套脚本此前最大的坑：点不到就吞掉、照旧出图，图名与图不符。
    现在一律记警告并在收尾时以非零码退出。 */
const WARNINGS = []
const warn = (name, msg) => {
  WARNINGS.push(`${name}: ${msg}`)
  console.log('  [warn]', name, '—', msg)
}

const SHOTS = []
for (const [n, path] of PAGES) {
  SHOTS.push({ name: `${P}-${n}`, path, scene: MOTOR, w: 1920, h: 1080 })
  SHOTS.push({ name: `${P}-${n}-1440`, path, scene: MOTOR, w: 1440, h: 810 })
}
for (const [n, path, slot] of ZOOM) {
  SHOTS.push({ name: `${P}-${n}`, path, scene: MOTOR, w: 1920, h: 1080, zoom: slot })
}
SHOTS.push({ name: `${P}-auto-run`, path: '/run', scene: AUTO, w: 1920, h: 1080 })
SHOTS.push({ name: `${P}-auto-init`, path: '/init', scene: AUTO, w: 1920, h: 1080 })

const ONLY = process.env.ONLY
const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })
for (const s of SHOTS) {
  if (ONLY && !s.name.includes(ONLY)) continue
  const page = await browser.newPage({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: 1 })
  page.on('console', (m) => m.type() === 'error' && console.log('  [console]', m.text().slice(0, 160)))
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))
  await page.goto(`${BASE}${s.path}?scene=${s.scene}`, { waitUntil: 'domcontentloaded' })
  await page
    .waitForLoadState('networkidle')
    .catch((e) => warn(s.name, `networkidle 未达成：${String(e).slice(0, 90)}`))
  await page.waitForTimeout(4200)
  if (s.zoom != null) {
    if (typeof s.zoom === 'string') {
      const node = page.locator('.react-flow__node').filter({ hasText: s.zoom }).first()
      try {
        await node.dblclick({ timeout: 4000 })
      } catch (e) {
        warn(s.name, `画板上找不到含「${s.zoom}」的节点：${String(e).slice(0, 90)}`)
      }
    } else {
      const btns = page.locator('[aria-label$="放大"]')
      try {
        await btns.nth(s.zoom).click({ timeout: 4000 })
      } catch (e) {
        warn(s.name, `第 ${s.zoom} 枚「放大」按钮点不到：${String(e).slice(0, 90)}`)
      }
    }
    await page.waitForTimeout(1600)
    // 点完必须真有浮层，否则这张图名不副实
    const modals = await page.locator('.tp-modal, [role="dialog"]').count()
    if (!modals) warn(s.name, '放大动作之后页面上没有任何浮层，这张图不是放大态')
  }
  await page.screenshot({ path: `${OUT}${s.name}.png` })
  console.log('✓', `${s.name}.png ${s.w}×${s.h}`)
  await page.close()
}
await browser.close()

if (WARNINGS.length) {
  console.log(`\n✗ ${WARNINGS.length} 处失败（图已落盘，但内容不可信）：`)
  for (const w of WARNINGS) console.log('  -', w)
  process.exit(1)
}
console.log('\n✓ 全部动作成功，无静默失败')
