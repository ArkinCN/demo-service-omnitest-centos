/** 用本地 Chrome 对 dist 产物截图到 shots/。用法：node scripts/shoot.mjs */
import { chromium } from 'playwright'
import { createServer } from 'node:http'
import { readFileSync, existsSync, statSync, globSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DIST = path.join(HERE, '..', 'dist')
const SHOTS = path.join(HERE, '..', 'shots')

const chromes = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort()
const executablePath = chromes[chromes.length - 1]
if (!executablePath) throw new Error('未找到 chrome 可执行文件')

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.wfw': 'application/json; charset=utf-8',
}

const server = createServer((req, res) => {
  const url = decodeURIComponent((req.url ?? '/').split('?')[0])
  let file = path.join(DIST, url)
  if (!existsSync(file) || statSync(file).isDirectory()) file = path.join(DIST, 'index.html')
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] ?? 'application/octet-stream' })
  res.end(readFileSync(file))
})
await new Promise((r) => server.listen(4173, r))

const browser = await chromium.launch({ executablePath, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2 })
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
page.on('pageerror', (e) => errors.push(String(e)))

async function settle() {
  await page.waitForSelector('.react-flow__node', { timeout: 15000 })
  await page.waitForTimeout(900)
}

// 1. 默认视图：StaticStart / HV 档
await page.goto('http://localhost:4173/', { waitUntil: 'networkidle' })
await settle()
await page.screenshot({ path: path.join(SHOTS, '01-default-hv-staticstart.png') })

// 2. 选中 RIGOL 示波器节点——参数最复杂，最能体现属性抽屉
// 长链流程有节点落在视口外，dispatchEvent 可以在不移动视口的前提下触发选中
const rigol = page.locator('.react-flow__node', { hasText: 'RIGOL' }).first()
const target = (await rigol.count()) > 0 ? rigol : page.locator('.react-flow__node').nth(3)
await target.dispatchEvent('click')
await page.waitForTimeout(500)
await page.screenshot({ path: path.join(SHOTS, '02-node-selected-params.png') })

// 3. 展开一个嵌套对象参数
const expand = page.locator('.wf-expand').first()
if ((await expand.count()) > 0) {
  await expand.click()
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(SHOTS, '03-nested-param-expanded.png') })
} else {
  console.warn('未找到可展开的复杂参数，跳过 03')
}

// 4. 换到一张更大的图：节点最多的主流程
await page.locator('.wf-group-head', { hasText: 'OTHERTEST' }).click()
await page.waitForTimeout(300)
await page.locator('.wf-card', { hasText: 'WholeTest' }).first().click()
await settle()
await page.screenshot({ path: path.join(SHOTS, '04-wholetest-large-graph.png') })

// 5. 子流程分组
await page.locator('.wf-group-head', { hasText: '子流程' }).click()
await page.waitForTimeout(300)
await page.locator('.wf-card', { hasText: 'PWM_VSP插入' }).first().click()
await settle()
await page.screenshot({ path: path.join(SHOTS, '05-subflow-pwm-vsp.png') })

await browser.close()
server.close()
console.log(errors.length ? `页面报错 ${errors.length} 条：\n${errors.join('\n')}` : '页面无控制台报错')
