// 2026-10-29：三处依赖显式带 `.ts` 扩展名。
// 原因：Node 24 直连 .ts 跑单测（web/tests/*.mjs 用 `node --test`）时不做扩展名补全，
// 无扩展名导入会抛 ERR_MODULE_NOT_FOUND；而本文件是纯函数模块复用的唯一入口
// （如 config-suggestions/presentation.ts 要调 translate()）。
// tsconfig 已开 allowImportingTsExtensions，`demo.ts` 也已有同样写法，Vite 侧无影响。
import { ENGLISH } from './catalog.ts'
import { AUTO_ENGLISH } from './autoCatalog.ts'
import { simp } from '../features/shared/zh.ts'

export type Locale = 'zh-CN' | 'en'
export type TranslationParams = Record<string, string | number>
const normalizeKey = (source: string) => simp(source).replace(/\s+/g, ' ').trim()
const normalizedCatalog = Object.fromEntries(Object.entries(ENGLISH).map(([source, english]) => [normalizeKey(source), english]))

/**
 * 两层词典查询：**人工词典（catalog.ts）优先，机翻词典（autoCatalog.ts）兜底**。
 *
 * 为什么拆两层：`catalog.ts` 是人工审核过的资产，`autoCatalog.ts` 是脚本生成物、
 * 可整体重写。拆开后「人工条目永不被机翻覆盖」是**结构性**保证，不依赖脚本自觉。
 * 手改译文只要写进 `catalog.ts` 即永久生效（重跑生成脚本也会跳过这些 key）。
 */
const normalizedAuto = Object.fromEntries(Object.entries(AUTO_ENGLISH).map(([source, english]) => [normalizeKey(source), english]))
const lookupExact = (source: string): string | undefined => ENGLISH[source] ?? AUTO_ENGLISH[source]
const lookupNormalized = (source: string): string | undefined =>
  normalizedCatalog[normalizeKey(source)] ?? normalizedAuto[normalizeKey(source)]

const templatePatterns = Object.entries(ENGLISH).filter(([source]) => /\{v\d+\}/.test(source)).map(([source, english]) => {
  const keys: string[] = []
  let pattern = '^'
  let position = 0
  for (const match of source.matchAll(/\{(v\d+)\}/g)) {
    pattern += source.slice(position, match.index).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '([\\s\\S]*?)'
    keys.push(match[1])
    position = match.index! + match[0].length
  }
  pattern += source.slice(position).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$'
  return { source, regex: new RegExp(pattern), keys, english }
}).sort((left, right) => right.source.replace(/\{v\d+\}/g, '').length - left.source.replace(/\{v\d+\}/g, '').length)

/** Translate only explicitly identified UI text. Parameters stay original data. */
export function translate(source: string, locale: Locale, params?: TranslationParams): string {
  if (!params && locale === 'en' && !/[\u3400-\u9fff]/.test(source)) return lookupExact(source) ?? source
  let template = locale === 'en' ? lookupExact(source) ?? source : source
  if (locale === 'en' && template === source) {
    const hit = lookupNormalized(source)
    if (hit) template = source.replace(source.trim(), hit)
  }
  // 模板层**只走人工词典**：机翻词典不含 `{v1}` 占位词条（生成脚本不产这类），
  // 故无需把 templatePatterns 扩到机翻层，也避免抢匹配、破坏既有递归翻译行为。
  if (locale === 'en' && !params && template === source && !ENGLISH[source]) {
    for (const entry of templatePatterns) {
      const match = entry.regex.exec(source)
      if (!match) continue
      // ⚠️ 捕获值必须再递归翻译一次（2026-10-14 修）：
      // 模板 `{v1} 失败：{v2}` 的 v1 常常**本身就是一条已收录的中文 UI 文案**
      // （如阶段名「启动测试及结果分析」）。不递归的话整句会变成
      // 「启动测试及结果分析 failed: ...」——半中半英，正是英文界面下日志漏中文的根因。
      // 兜底：值本身查不到译文时 translate 会原样返回，不会丢信息。
      const captured = Object.fromEntries(
        entry.keys.map((key, index) => [key, translate(match[index + 1], locale)]),
      )
      return entry.english.replace(/\{(v\d+)\}/g, (token, key: string) => captured[key] ?? token)
    }
  }
  return params ? template.replace(/\{([\w]+)\}/g, (token, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : token) : template
}

/** Convert newly authored UI text into a stable approved template and raw parameters. */
export function describeUiTranslation(source: string): { key: string; params?: TranslationParams } {
  if (Object.prototype.hasOwnProperty.call(ENGLISH, source)) return { key: source }
  for (const entry of templatePatterns) {
    const match = entry.regex.exec(source)
    if (!match) continue
    return { key: entry.source, params: Object.fromEntries(entry.keys.map((key, index) => [key, match[index + 1]])) }
  }
  return { key: source }
}
