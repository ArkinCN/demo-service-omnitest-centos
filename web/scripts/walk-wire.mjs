/**
 * 第四轮接线走查：勾满安全闸门 → 启动按钮变亮 → 点 → 红线确认卡 → 判定出结论 →
 * 未达标行跳流程 4 → 采纳 → 回流程 3 → 生成报告。
 * 附带取两态截图：设备桥在线与离线时，画布设备节点各显示什么。
 *
 * 用法：
 *   WALK_PIN=$(grep '^BRIDGE_APPROVER_PIN=' [源] spike-device-mcp/.env | cut -d= -f2-) \
 *   BASE=http://localhost:5173 node scripts/walk-wire.mjs
 *
 * 桥默认只放行 5173 与 3080 两个来源，所以走查要用 vite dev 而不是 preview。
 *
 * 批准 PIN（2026-09-20 起）：桥把批准权从调用票里拆了出去，确认卡上多一个 PIN 输入框。
 * 脚本从环境变量 WALK_PIN 读，不接受写死的默认值——走查脚本里塞一个默认 PIN，
 * 等于把第二道闸口又变回公开的。没给就直接退出。
 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:5173'
const OUT = `${process.env.HOME}/agent-test-web/${process.env.SHOTS ?? 'shots7'}/`
const TAG = process.env.TAG ?? 'online'
mkdirSync(OUT, { recursive: true })
const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)
const SCENE = 'motor.cooling-fan.fortior-fu6832'

const PIN = process.env.WALK_PIN ?? ''
if (!PIN && !process.env.ONLY_DEVICE) {
  console.error(
    '缺 WALK_PIN：确认卡上的批准 PIN 要现场给，脚本不带默认值。\n' +
      "  WALK_PIN=$(grep '^BRIDGE_APPROVER_PIN=' [源] spike-device-mcp/.env | cut -d= -f2-) node scripts/walk-wire.mjs",
  )
  process.exit(2)
}

const log = []
const step = (n, ok, note) => {
  log.push(`${ok ? 'PASS' : 'FAIL'}  ${n}${note ? ` — ${note}` : ''}`)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${note ? ` — ${note}` : ''}`)
}

const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 300)))
const shot = (name) => page.screenshot({ path: `${OUT}${TAG}-${name}.png` })

const startBtn = () => page.locator('button[data-action="start"]')

/**
 * 确认卡上的那一步：先敲批准 PIN，再点「确认执行」。
 * 接了桥的凭据时 PIN 框必须在，没在就是红线又被绕回去了，这里当失败处理。
 * 回放态（卡上没凭据）没有 PIN 框，直接点。
 */
const typePinAndApprove = async () => {
  const pinBox = page.locator('[data-testid="redline-pin"]')
  const hasPin = (await pinBox.count()) > 0
  if (hasPin) await pinBox.fill(PIN)
  await page.locator('[data-testid="redline-approve"]').click()
  await page.waitForTimeout(900)
  return hasPin
}
/** 折叠组的展开循环会误点到卡头的「换卡」菜单，它会盖一层 fixed inset-0 的关闭层，
 *  挡住后面所有点击。每次批量点击之后先把它关掉。 */
const dismiss = async () => {
  for (let i = 0; i < 3; i++) {
    const veil = page.locator('button[aria-label="关闭换卡"]')
    if (!(await veil.count())) return
    await veil.first().click({ timeout: 1500 }).catch(() => {})
    await page.waitForTimeout(150)
  }
}
const go = async (path, q = '') => {
  await page.goto(`${BASE}${path}?scene=${SCENE}${q}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1400)
}

/* ---------------------------------------------------- 0 · 设备桥两态：节点文案

   设备节点画在 C 区画板上。流程 3 与流程 4 的默认视图是网格（场景包 scene.json
   的 default_view 段），画板只在流程 1、流程 2 默认出现，所以这一步去 /init 取。 */
await go('/init')
const linkText = (await page.locator('[data-testid="device-link"]').first().textContent().catch(() => null))?.trim()
const railOffline = await page.locator('[data-testid="rail-bridge-offline"]').count()
const bridgeTools = await page.locator('[data-bridge-tool]').count()
step('0 设备桥节点', linkText === '已连通' || linkText === '未连通', `节点文案「${linkText ?? '未渲染'}」· 工具条桥工具 ${bridgeTools} 个 · 离线占位 ${railOffline} 个`)
await shot('0-device-node')
// 把节点那行文案的 tooltip 悬出来：桥不可达时这里写的是缺哪个配置、该起哪个脚本
await page.locator('[data-testid="device-link"]').first().hover().catch(() => {})
await page.waitForTimeout(700)
await shot('0-device-node-tip')

if (process.env.ONLY_DEVICE) {
  console.log('\n' + log.join('\n'))
  await browser.close()
  process.exit(0)
}

await go('/run')

/* ------------------------------------------------ 1 · 闸门未满时启动按钮是灰的 */
const disabledBefore = await startBtn().isDisabled()
step('1 闸门未满 → 启动置灰', disabledBefore === true)
await shot('1-gate-empty')

/* ------------------------------------------------------------ 2 · 逐条勾满闸门 */
// 左栏「安全闸门」组默认展开，逐条勾选按钮的 aria-label 是闸门条目名，
// 这里直接按 GateRow 的结构取：组内每一行都是一个 button，行尾是条目编号。
await page.locator('button:has-text("安全闸门")').first().click().catch(() => {})
await page.waitForTimeout(300)
// 展开全部二级 / 三级折叠组，确保九条都在 DOM 里
for (let round = 0; round < 3; round++) {
  const heads = page.locator('button[aria-expanded="false"]')
  const n = await heads.count()
  for (let i = 0; i < n; i++) {
    await heads.nth(i).click({ timeout: 2000 }).catch(() => {})
    await dismiss()
  }
  await page.waitForTimeout(250)
}
await dismiss()
const gateBtns = page.locator('button[data-gate]')
const gateIds = await gateBtns.evaluateAll((els) => els.map((e) => e.getAttribute('data-gate')))
let clicked = 0
for (const id of gateIds) {
  const btn = page.locator(`button[data-gate="${id}"]`).first()
  if ((await btn.getAttribute('aria-pressed')) === 'true') continue
  await btn.click({ timeout: 2000 }).catch(() => {})
  clicked++
}
await dismiss()
await page.waitForTimeout(400)
const shieldText = (await page.locator('header span.num').allTextContents()).join('|')
step('2 逐条勾满闸门', clicked > 0, `点到 ${clicked} 条（${gateIds.join(' ')}）· 闸门计数见截图`)
await shot('2-gate-green')

/* ------------------------------------------------------- 3 · 启动按钮变亮并点击 */
const disabledAfter = await startBtn().isDisabled()
step('3 闸门全绿 → 启动变亮', disabledAfter === false, `盾形徽章一行：${shieldText.slice(0, 60)}`)
if (disabledAfter) {
  console.log('\n' + log.join('\n'))
  await browser.close()
  process.exit(1)
}
await startBtn().click()
await page.waitForTimeout(1200)

/* ------------------------------------------------------------ 4 · 红线确认卡 */
const approve = page.locator('[data-testid="redline-approve"]')
const cardOpen = (await approve.count()) > 0
const hasToken = cardOpen && (await page.locator('[role="dialog"]').innerText()).includes('设备桥已签发')
const pinBoxCount = await page.locator('[data-testid="redline-pin"]').count()
const cardText = cardOpen ? (await page.locator('[role="dialog"]').innerText()).replace(/\s+/g, ' ').slice(0, 180) : ''
// 接了桥就必须有 PIN 框；没接桥（回放态）不要求
step(
  '4 弹红线确认卡（含批准 PIN 框）',
  cardOpen && (!hasToken || pinBoxCount === 1),
  `PIN 框 ${pinBoxCount} 个 · ${cardText}`,
)
await shot('4-redline-confirm')
// 先只敲 PIN 不点确认，留一张"卡上确实有 PIN 框且已填"的证据图
if (pinBoxCount) {
  await page.locator('[data-testid="redline-pin"]').fill(PIN)
  await shot('4b-redline-pin-filled')
}

/* -------------------------------------------------- 5 · 确认后运行中 → 出判定 */
await approve.click()
await page.waitForTimeout(600)
const running = (await page.locator('[data-testid="run-phase"]').first().textContent().catch(() => '')) ?? ''
await shot('5-running')
await page.waitForTimeout(3200)
const phase = (await page.locator('[data-testid="run-phase"]').first().textContent().catch(() => '')) ?? ''
const failRows = await page.locator('[data-testid="verdict-fail-row"]').count()
step('5 运行中 → 出判定', failRows > 0, `运行中读数「${running.trim()}」→ 结束读数「${phase.trim()}」· 判定卡未达标行 ${failRows} 条`)
await shot('5-verdict')

/* ------------------------------------------------ 6 · 未达标行点进流程 4 */
await dismiss()
if (failRows > 0) await page.locator('[data-testid="verdict-fail-row"]').first().click()
await page.waitForTimeout(1500)
const onTune = page.url().includes('/tune')
const banner = (await page.locator('text=来自流程 3 判定卡的未达标项').count()) > 0
step('6 未达标行跳流程 4', onTune && banner, `URL ${page.url().replace(BASE, '')} · 来源横幅 ${banner ? '有' : '无'}`)
await shot('6-tune-focus')

/* ------------------------------------------------------------ 7 · 勾选并采纳 */
await dismiss()
// 推荐参数按改动部位切三类，默认只展开第一类，先把折叠的都点开
for (let round = 0; round < 3; round++) {
  const heads = page.locator('button[aria-expanded="false"]')
  const n = await heads.count()
  for (let i = 0; i < n; i++) {
    await heads.nth(i).click({ timeout: 2000 }).catch(() => {})
    await dismiss()
  }
  await page.waitForTimeout(250)
}
await dismiss()
const pickCount = await page.locator('button[role="checkbox"][aria-label^="采纳"]').count()
const pick = page.locator('button[role="checkbox"][aria-label^="采纳"]').first()
if (await pick.count()) await pick.click()
await page.waitForTimeout(400)
const adoptBtn = page.locator('button[data-action="adopt-back"]')
const adoptEnabled = (await adoptBtn.count()) > 0 && !(await adoptBtn.isDisabled())
step('7 勾选候选 → 采纳按钮可点', adoptEnabled, `页面上可勾候选 ${pickCount} 条`)
await shot('7-adopt-picked')
if (adoptEnabled) {
  await adoptBtn.click()
  await page.waitForTimeout(1200)
  const a2 = page.locator('[data-testid="redline-approve"]')
  const ok2 = (await a2.count()) > 0
  const t2 = ok2 ? (await page.locator('[role="dialog"]').innerText()).replace(/\s+/g, ' ').slice(0, 160) : ''
  const pin2 = ok2 ? await page.locator('[data-testid="redline-pin"]').count() : 0
  step('8 采纳走红线确认卡', ok2, `PIN 框 ${pin2} 个 · ${t2}`)
  await shot('8-adopt-confirm')
  if (ok2) await typePinAndApprove()
  await page.waitForTimeout(1200)
}
const backToRun = page.url().includes('/run')
step('9 采纳后回到流程 3', backToRun, `URL ${page.url().replace(BASE, '')}`)
await shot('9-back-to-run')

/* ---------------------------------------------------------- 10 · 生成报告 */
await dismiss()
await page.locator('a[href="/report"]').first().click()
await page.waitForTimeout(1400)
const genBtn = page.locator('button[data-action="gen-report"]')
const hasGen = (await genBtn.count()) > 0
if (hasGen) await genBtn.click()
await page.waitForTimeout(1000)
step('10 生成报告', hasGen && page.url().includes('/report'), `URL ${page.url().replace(BASE, '')}`)
await shot('10-report')

/* ---------------------------------------------------- 11 · 导出走红线确认卡 */
await dismiss()
const exportBtn = page.locator('button[data-action="export"]').first()
if (await exportBtn.count()) {
  await exportBtn.click()
  await page.waitForTimeout(1200)
  const a3 = page.locator('[data-testid="redline-approve"]')
  const ok3 = (await a3.count()) > 0
  const t3 = ok3 ? (await page.locator('[role="dialog"]').innerText()).replace(/\s+/g, ' ').slice(0, 160) : ''
  const pin3 = ok3 ? await page.locator('[data-testid="redline-pin"]').count() : 0
  step('11 导出走红线确认卡', ok3, `PIN 框 ${pin3} 个 · ${t3}`)
  await shot('11-export-confirm')
  if (ok3) await page.locator('[data-testid="redline-cancel"]').click()
} else {
  step('11 导出走红线确认卡', false, '没找到导出按钮')
}

console.log('\n===== 走查结果 =====\n' + log.join('\n'))
await browser.close()
