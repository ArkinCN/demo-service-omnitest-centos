import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = resolve(ROOT, 'shots')
const BASE = process.env.BASE ?? 'http://localhost:5300'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chromium' })
const page = await browser.newPage({ viewport: { width: 1280, height: 700 }, deviceScaleFactor: 2 })

async function shoot(name) {
  await page.waitForTimeout(450)
  await page.locator('[data-testid="panel"]').screenshot({ path: `${OUT}/${name}.png` })
  const pct = await page.locator('[data-testid="zoom-pct"]').innerText()
  const n = await page.locator('[data-testid="canvas"] [data-testid="panel"], [data-testid="canvas"]').count()
  console.log(`  ${name}.png  zoom=${pct}  (canvas nodes present: ${n > 0})`)
}

for (const [tag, hash] of [['flow', '#flow'], ['svg', '#svg']]) {
  await page.goto(`${BASE}/${hash}`)
  await page.waitForTimeout(900)
  console.log(`[${tag}]`)
  await shoot(`${tag}-1-default`)

  // 放大态：指针停在画布中心连滚 5 下
  const box = await page.locator('[data-testid="canvas"]').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 5; i++) { await page.mouse.wheel(0, -120); await page.waitForTimeout(90) }
  await shoot(`${tag}-2-zoomed`)

  // 复位后从右侧工具条拖入一个节点
  await page.locator('[data-testid="zoombar"] button:last-child').click()
  await page.waitForTimeout(400)
  const src = page.locator('[data-testid="rail"] .rail-btn').first()  // 设备组 · 示波器
  await src.dragTo(page.locator('[data-testid="canvas"]'), {
    targetPosition: { x: box.width * 0.42, y: box.height * 0.78 },
  })
  await shoot(`${tag}-3-dropped`)
}

await browser.close()
console.log(`\nshots -> ${OUT}`)
