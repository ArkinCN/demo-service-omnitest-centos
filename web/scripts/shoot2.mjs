/**
 * v2 视觉验收截图：1920×1080 基准 + 1440×810 不破版对照。
 *   npm run preview  然后  node scripts/shoot2.mjs
 *   BASE=http://localhost:5173 node scripts/shoot2.mjs
 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const OUT = new URL('../shots2/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)
if (!exe) throw new Error('本机未找到 Chrome')

const SCENE = 'motor.cooling-fan.fortior-fu6832'
const ONLY = process.env.ONLY
const SHOTS = [
  { name: 'run', path: '/run', w: 1920, h: 1080 },
  { name: 'run-1440', path: '/run', w: 1440, h: 810 },
  { name: 'run-1600', path: '/run', w: 1600, h: 900 },
]

const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })
for (const s of SHOTS) {
  if (ONLY && s.name !== ONLY) continue
  const page = await browser.newPage({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: 1 })
  page.on('console', (m) => m.type() === 'error' && console.log('  [console]', m.text().slice(0, 160)))
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))
  await page.goto(`${BASE}${s.path}?scene=${SCENE}`, { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(4200)
  await page.screenshot({ path: `${OUT}${s.name}.png` })
  console.log('✓', `${s.name}.png ${s.w}×${s.h}`)
  await page.close()
}
await browser.close()
