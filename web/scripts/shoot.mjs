/**
 * 两个场景包各截六条流程 1600×1000，另截三张放大态与一张两包并排对照。
 * 用本机已有的 Chrome，不额外下载浏览器。
 *   node scripts/shoot.mjs            # 对 http://localhost:4173（npm run preview）
 *   BASE=http://localhost:5173 node scripts/shoot.mjs
 *
 * 产物见 shots/：
 *   flow-<route>.png        场景一 散热风扇
 *   auto-flow-<route>.png   场景二 玻璃升降器
 *   zoom-*.png              三张放大态（场景一）
 *   compare-run.png         同一流程（启动测试）两包并排，由 scripts/compare.py 拼
 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const OUT = new URL('../shots/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`)
  .sort()
  .at(-1)
if (!exe) throw new Error('本机未找到 Chrome：[源] chrome-linux64/chrome')

const ROUTES = [
  ['kb', '/kb'],
  ['init', '/init'],
  ['requirements', '/requirements'],
  ['run', '/run'],
  ['tune', '/tune'],
  ['report', '/report'],
]

/** 两个场景包：sceneId 决定开哪个包（走 ?scene=），prefix 决定文件名前缀 */
const SCENES = [
  { id: 'motor.cooling-fan.fortior-fu6832', prefix: 'flow' },
  { id: 'automotive.body-motor.window-regulator', prefix: 'auto-flow' },
]

const browser = await chromium.launch({
  executablePath: exe,
  args: ['--force-device-scale-factor=1'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 })
page.on('console', (m) => m.type() === 'error' && console.log('  [console]', m.text().slice(0, 160)))
page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))

const settle = async (ms = 2600) => {
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(ms)
}

for (const scene of SCENES) {
  for (const [name, path] of ROUTES) {
    await page.goto(`${BASE}${path}?scene=${scene.id}`, { waitUntil: 'domcontentloaded' })
    await settle(name === 'run' || name === 'tune' ? 3800 : 3000)
    await page.screenshot({ path: `${OUT}${scene.prefix}-${name}.png` })
    console.log('✓', `${scene.prefix}-${name}.png`)
  }
}

const one = SCENES[0].id

/* 放大态 1 · 工作流画布 */
await page.goto(`${BASE}/requirements?scene=${one}`, { waitUntil: 'domcontentloaded' })
await settle(3200)
await page.getByRole('button', { name: /放大$/ }).first().click()
await settle(2400)
await page.screenshot({ path: `${OUT}zoom-workflow-canvas.png` })
console.log('✓ zoom-workflow-canvas.png')

/* 放大态 2 · 时序曲线 */
await page.goto(`${BASE}/run?scene=${one}`, { waitUntil: 'domcontentloaded' })
await settle(3600)
await page.getByRole('button', { name: /放大$/ }).first().click()
await settle(2600)
await page.screenshot({ path: `${OUT}zoom-timeseries.png` })
console.log('✓ zoom-timeseries.png')

/* 放大态 3 · 依据面板（助手右侧的依据抽屉） */
await page.goto(`${BASE}/tune?scene=${one}`, { waitUntil: 'domcontentloaded' })
await settle(4200)
await page
  .locator('.ac-iconbtn', { hasText: '依据' })
  .first()
  .click()
  .catch(() => {})
await settle(1800)
await page.screenshot({ path: `${OUT}zoom-evidence.png` })
console.log('✓ zoom-evidence.png')

/* 放大态 4 · 汽车包的工作流画布（验证 minZoom 覆盖后不再裁切） */
await page.goto(`${BASE}/requirements?scene=${SCENES[1].id}`, { waitUntil: 'domcontentloaded' })
await settle(3400)
await page.getByRole('button', { name: /放大$/ }).first().click()
await settle(2400)
await page.screenshot({ path: `${OUT}auto-zoom-workflow-canvas.png` })
console.log('✓ auto-zoom-workflow-canvas.png')

await browser.close()
