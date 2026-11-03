/** R-14 收口截图：流程 3 启动测试与流程 4 调优运行，演示模式与全量模式各一张。 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'
const BASE = process.env.BASE ?? 'http://localhost:4199'
const OUT = `${process.env.HOME}/agent-test-web/shots4-r14/`
mkdirSync(OUT, { recursive: true })
const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)
const SCENE = 'motor.cooling-fan.fortior-fu6832'
const SHOTS = [
  ['r14-run', '/run', ''],
  ['r14-tune', '/tune', ''],
  ['r14-run-full', '/run', '&mode=full'],
  ['r14-tune-full', '/tune', '&mode=full'],
  ['r14-run-1440', '/run', '', 1440, 810],
  ['r14-tune-1440', '/tune', '', 1440, 810],
]
const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })
for (const [name, path, q, w = 1920, h = 1080] of SHOTS) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 })
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))
  await page.goto(`${BASE}${path}?scene=${SCENE}${q}`, { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(9000)
  await page.screenshot({ path: `${OUT}${name}.png` })
  console.log('saved', name)
  await page.close()
}
await browser.close()
