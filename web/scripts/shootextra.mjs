/**
 * 收尾轮（W6）补的五张状态截图，与 shootfinal.mjs 的整页图配套：
 *   画板缩放态 / 节点放大态 / 待确认态 / 知识库筛选态 / 折叠展开态
 *   node scripts/shootextra.mjs
 * 环境变量：BASE（默认 http://localhost:4173）、PREFIX（默认 final）、ONLY、OUTDIR（输出目录名，默认 shots2）
 * 每一张都打印它实际做到了哪一步，做不到就明说，不拿看起来像的图冒充。
 */
import { chromium } from 'playwright'
import { globSync, mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const OUT = new URL(`../${process.env.OUTDIR ?? 'shots2'}/`, import.meta.url).pathname
const P = process.env.PREFIX ?? 'final'
const ONLY = process.env.ONLY
mkdirSync(OUT, { recursive: true })

const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)
if (!exe) throw new Error('本机未找到 Chrome')

const MOTOR = 'motor.cooling-fan.fortior-fu6832'

/** 与 shootfinal.mjs 同口径：任何一步失败都记警告，收尾以非零码退出，不再静默出图。 */
const WARNINGS = []
const warn = (name, msg) => {
  WARNINGS.push(`${name}: ${msg}`)
  console.log('  [warn]', name, '—', msg)
}

const SHOTS = [
  {
    name: 'canvas-zoom',
    path: '/init',
    note: '画板缩放态：放大到内容超出视口，右下角缩放条与其上方的缩略导航图同屏',
    async act(page) {
      const plus = page.locator('button[aria-label="放大画布"]')
      await plus.waitFor({ timeout: 8000 })
      // 放大到内容超出视口，缩略导航图才按规格出现（不超出就不出，这是既定行为）
      for (let i = 0; i < 2; i += 1) {
        await plus.click()
        await page.waitForTimeout(260)
      }
      const pct = await page.locator('[data-testid="canvas-zoom"]').innerText()
      const zb = await page.locator('[data-testid="canvas-zoom"]').boundingBox()
      const mm = await page
        .locator('.react-flow__minimap')
        .boundingBox()
        .catch((e) => {
          warn('canvas-zoom', `缩略导航图取不到位置：${String(e).slice(0, 90)}`)
          return null
        })
      return `缩放读数 ${pct}；缩放条中心 x=${Math.round(zb.x + zb.width / 2)}；缩略导航图${
        mm ? `中心 x=${Math.round(mm.x + mm.width / 2)}` : '未出现'
      }（C 区左右边界约 436 与 1840，中线约 1138）`
    },
  },
  {
    name: 'node-zoom',
    path: '/init',
    note: '节点放大态：双击「设备节点」，开放大浮层（设备卡 + 四种接入形态 + 按需打开的终端）',
    async act(page) {
      // 挑内容最实的那个节点：程控电源之类的事实型节点放大后几乎是空的，不适合做交付图
      const node = page.locator('.react-flow__node').filter({ hasText: '设备节点' }).first()
      await node.waitFor({ timeout: 8000 })
      await node.dblclick()
      await page.waitForTimeout(1400)
      const n = await page.locator('.tp-modal, [role="dialog"]').count()
      if (!n) warn('node-zoom', '双击「设备节点」后没有浮层')
      const t = await page
        .locator('.tp-modal, [role="dialog"]')
        .first()
        .innerText()
        .catch((e) => {
          warn('node-zoom', `浮层文本读不到：${String(e).slice(0, 90)}`)
          return ''
        })
      return `浮层数 ${n}；浮层首行「${t.split('\n')[0] ?? ''}」`
    },
  },
  {
    name: 'confirm',
    path: '/requirements',
    note: '待确认态：点红线按钮「冻结待点」，停在「点亮人工按钮」这一步的确认闸门上',
    async act(page) {
      // 红线口径的证据：被确认的是「把 B 区那枚人工按钮由灰点亮」，不是归档动作本身
      const btn = page.getByRole('button', { name: '冻结待点' })
      await btn.waitFor({ timeout: 8000 })
      await btn.click()
      await page.waitForTimeout(11000)
      const box = page.locator('.ac-stream')
      await box.evaluate((el) => {
        el.scrollTop = el.scrollHeight
      })
      await page.waitForTimeout(500)
      const txt = await box.innerText()
      return `对话末段含「等待人工确认」= ${txt.includes('等待人工确认')}；含「不执行」= ${txt.includes('不执行')}`
    },
  },
  {
    name: 'kb-filter',
    path: '/knowledge',
    note: '知识库筛选态：展开「用途」轴并勾一类，列表与面包屑同步收窄',
    async act(page) {
      await page.getByRole('button', { name: /用途/ }).first().click()
      await page.waitForTimeout(500)
      await page.getByRole('button', { name: /测试需求/ }).first().click()
      await page.waitForTimeout(900)
      return '已展开用途轴并勾选一类'
    },
  },
  {
    name: 'collapse',
    path: '/init',
    note: '折叠展开态：把左栏一个折叠着的一级类点开，折叠与展开同屏',
    async act(page) {
      // 只认左栏里的折叠组头：页面上第一个 aria-expanded 其实是顶栏的产品级联，点它会开错东西
      const heads = page.locator('.fade-b button[aria-expanded="false"]')
      await heads.first().waitFor({ timeout: 8000 })
      const before = await heads.count()
      const target = page.locator('.fade-b button[aria-expanded="false"]').filter({ hasText: '驱动与控制' })
      await ((await target.count()) ? target.first() : heads.first()).click()
      await page.waitForTimeout(800)
      const after = await page.locator('.fade-b button[aria-expanded="false"]').count()
      return `左栏折叠组头 ${before} → ${after}（点开一个一级类，其内的二级组随之出现）`
    },
  },
]

const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })
for (const s of SHOTS) {
  if (ONLY && !s.name.includes(ONLY)) continue
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  page.on('console', (m) => m.type() === 'error' && console.log('  [console]', m.text().slice(0, 160)))
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))
  await page.goto(`${BASE}${s.path}?scene=${MOTOR}`, { waitUntil: 'domcontentloaded' })
  await page
    .waitForLoadState('networkidle')
    .catch((e) => warn(s.name, `networkidle 未达成：${String(e).slice(0, 90)}`))
  await page.waitForTimeout(4200)
  let detail = ''
  try {
    detail = await s.act(page)
  } catch (e) {
    detail = `动作失败：${String(e).slice(0, 120)}`
    warn(s.name, detail)
  }
  const file = `${P}-extra-${s.name}.png`
  await page.screenshot({ path: `${OUT}${file}` })
  console.log('✓', file, '—', s.note)
  console.log('   ', detail)
  await page.close()
}
await browser.close()

if (WARNINGS.length) {
  console.log(`\n✗ ${WARNINGS.length} 处失败（图已落盘，但内容不可信）：`)
  for (const w of WARNINGS) console.log('  -', w)
  process.exit(1)
}
console.log('\n✓ 全部动作成功，无静默失败')
