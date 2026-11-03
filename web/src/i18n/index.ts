export { LocaleProvider } from './LocaleProvider'
// initialLocale 也一并导出：**纯函数模块**（无 hook 作用域，如 canvas 的模块级工具函数）
// 需要按语言翻译时用它，口径与 context.ts 的 ctxT() 一致。
export { useLocale, useT, LOCALE_STORAGE_KEY, initialLocale } from './locale'
export { translate } from './runtime'
export type { Locale, TranslationParams } from './runtime'
