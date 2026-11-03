/**
 * 按 06d 第 1.1 节口径数首屏元素：
 * 「观众在 1920×1080 首屏上能直接看见的可辨识信息单元」。
 * 实现：取可见文本节点，按「最近的行容器」合并（同一行里的 标签+数值+单位 记 1），
 * 不计入：纯装饰图标（无文本的 svg）、图表坐标轴刻度（recharts / svg 内文本）、
 * 折叠后不可见的内容（getBoundingClientRect 为 0 或 offsetParent 为 null）、
 * 视口之外的内容。
 */
import { chromium } from 'playwright'
import { globSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://localhost:4199'
const SCENE = 'motor.cooling-fan.fortior-fu6832'
const exe = globSync(`${process.env.HOME}/.cache/puppeteer/chrome/*/chrome-linux64/chrome`).sort().at(-1)

const COUNT = () => {
  const root = document.querySelector('main')
  const grid = root.firstElementChild
  const left = grid.children[0]
  const right = grid.children[1]
  const panel = right.children[0]
  const assist = right.children[1]
  const top = document.querySelector('main').previousElementSibling

  const inView = (el) => {
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1) return false
    if (r.bottom <= 0 || r.top >= window.innerHeight) return false
    if (r.right <= 0 || r.left >= window.innerWidth) return false
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) < 0.05) return false
    return true
  }

  // 一个「行」= 最近的块级祖先（display 非 inline），用它做合并键
  const rowOf = (node, scope) => {
    const sv = node.parentElement && node.parentElement.closest('svg')
    if (sv) return sv
    // 一个可点控件（按钮/链接/列表项/表单标签）整体算一个信息单元
    const ctl = node.parentElement && node.parentElement.closest('button, a, li, label, [role="button"], [role="tab"], [role="option"]')
    if (ctl && scope.contains(ctl)) return ctl
    let el = node.parentElement
    while (el) {
      const st = getComputedStyle(el)
      if (st.display !== 'inline' && st.display !== 'contents') return el
      el = el.parentElement
    }
    return null
  }

  const collect = (scope) => {
    if (!scope) return []
    const rows = new Map()
    const w = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT)
    let n
    while ((n = w.nextNode())) {
      const t = n.textContent.replace(/\s+/g, ' ').trim()
      if (!t) continue
      const p = n.parentElement
      if (!p || !inView(p)) continue
      // 图表内部（坐标轴刻度、图内标注）不计
      if (p.closest('svg')) continue
      const r = rowOf(n, scope)
      if (!r) continue
      if (!rows.has(r)) rows.set(r, [])
      rows.get(r).push(t)
    }
    return [...rows.values()].map((a) => a.join(' | '))
  }

  const out = {}
  for (const [k, el] of [['top', top], ['left', left], ['panel', panel], ['assist', assist]]) {
    const items = collect(el)
    out[k] = { n: items.length, items }
  }
  out.total = out.top.n + out.left.n + out.panel.n + out.assist.n
  return out
}

const browser = await chromium.launch({ executablePath: exe, args: ['--force-device-scale-factor=1'] })
const res = {}
for (const [name, path] of [['run', '/run'], ['tune', '/tune']]) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  await page.goto(`${BASE}${path}?scene=${SCENE}`, { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(14000)
  res[name] = await page.evaluate(COUNT)
  await page.close()
}
await browser.close()
for (const [k, v] of Object.entries(res)) {
  console.log(`\n===== ${k} : 顶栏 ${v.top.n} + 左栏 ${v.left.n} + 面板 ${v.panel.n} + 助手 ${v.assist.n} = ${v.total}`)
  if (process.env.DETAIL) {
    for (const zone of ['top', 'left', 'panel', 'assist']) {
      console.log(`--- ${zone}`)
      v[zone].items.forEach((s, i) => console.log(`  ${i + 1}. ${s.slice(0, 90)}`))
    }
  }
}
