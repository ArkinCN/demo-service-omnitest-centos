/**
 * W3 · C 区统一画板的三张补充验收截图。
 *   npm run build && npx vite preview --port 4185   然后   BASE=http://localhost:4185 node scripts/shootw3.mjs
 * 产出（shots2/ 下）：
 *   w3-board-zoom.png  同一页把画布缩到约 60%，外框不动、只有内容缩放
 *   w3-board-drag.png  右侧工具条一枚工具被拖到画板中央、落点上生成了节点
 *   w3-node-zoom.png   节点放大态（设备 MCP 节点，终端按钮在放大态里）
 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const OUT = new URL('../shots2/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)
if (!exe) throw new Error('本机未找到 Chrome')

const SCENE = 'motor.cooling-fan.fortior-fu6832'
const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })

async function open(path = '/init') {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))
  await page.goto(`${BASE}${path}?scene=${SCENE}`, { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(4200)
  return page
}

/* ---- 1. 缩放态：点两下缩放条的「−」，90% → 约 62%，外框尺寸位置不变 ---- */
{
  const page = await open('/init')
  const box = await page.locator('.cv-wrap').boundingBox()
  await page.locator('.cv-zoom button[aria-label="缩小"]').click()
  await page.waitForTimeout(300)
  await page.locator('.cv-zoom button[aria-label="缩小"]').click()
  await page.waitForTimeout(600)
  const after = await page.locator('.cv-wrap').boundingBox()
  const pct = await page.locator('[data-testid="canvas-zoom"]').textContent()
  console.log('  画板外框', JSON.stringify(box), '→', JSON.stringify(after), '缩放', pct)
  await page.screenshot({ path: `${OUT}w3-board-zoom.png` })
  console.log('✓ w3-board-zoom.png')
  await page.close()
}

/* ---- 2. 拖入态：把工具条的一枚工具拖到画板中央，落点上生成节点 ---- */
{
  const page = await open('/init')
  const before = await page.locator('.react-flow__node').count()
  await page.evaluate(() => {
    const el = document.querySelector('.cv-wrap')
    const r = el.getBoundingClientRect()
    const dt = new DataTransfer()
    dt.setData('application/x-canvas-node', JSON.stringify({ type: 'scope', label: '波形采集' }))
    const at = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }
    const opt = { bubbles: true, cancelable: true, dataTransfer: dt, ...at }
    el.dispatchEvent(new DragEvent('dragover', opt))
    el.dispatchEvent(new DragEvent('drop', opt))
  })
  await page.waitForTimeout(900)
  const after = await page.locator('.react-flow__node').count()
  console.log(`  画板节点数 ${before} → ${after}`)
  await page.screenshot({ path: `${OUT}w3-board-drag.png` })
  console.log('✓ w3-board-drag.png')
  await page.close()
}

/* ---- 3. 节点放大态：设备 MCP 节点，终端只在这里出现 ---- */
{
  const page = await open('/init')
  await page.locator('[aria-label="设备节点 放大"]').click({ timeout: 4000 })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}w3-node-zoom.png` })
  console.log('✓ w3-node-zoom.png')
  await page.close()
}

await browser.close()
