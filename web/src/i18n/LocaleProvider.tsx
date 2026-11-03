import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { LocaleContext, initialLocale, LOCALE_STORAGE_KEY } from './locale'
import type { Locale } from './runtime'
const originalDocumentTitle = document.title

/** This provider has no business state and never remounts its children on a language change. */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale)
  /**
   * 2026-10-15：**先同步写 localStorage、再 setState**。
   *
   * 纯函数模块（`scene/pack.ts` 的 `headerFieldName`/`sectionTitle`/`sectionFields`、
   * `shared/tiers.ts` 的 `readTiers`、`copilot/context.ts` 的 `ctxT`…）拿不到 React context，
   * 只能读 `initialLocale()`（即 localStorage）来判断语言。若等下面的 effect 再写，
   * **切换语言的那一轮渲染读到的还是旧语言**，表现为：切到英文后报告分节名先走中文清洗、
   * 或只显示旧语言词典译文（词典缺词条时甚至露出 `1.` / `FG / R…` 这类残名），
   * 直到下一次重渲才对。写在 setState 之前，整轮渲染都读新值，滞后从根上消失。
   * effect 里的 setItem 保留（幂等），兜「绕开本 setter 直接改 localStorage」的场景。
   */
  const setLocale = useCallback((next: Locale) => {
    try { localStorage.setItem(LOCALE_STORAGE_KEY, next) } catch { /* 写失败也切：内存态照常生效 */ }
    setLocaleState(next)
  }, [])
  useEffect(() => {
    document.documentElement.lang = locale
    document.title = locale === 'en' ? 'OmniTest · Industrial Automated Testing' : originalDocumentTitle
    try { localStorage.setItem(LOCALE_STORAGE_KEY, locale) } catch { /* Session preference still works. */ }
  }, [locale])
  const value = useMemo(() => ({ locale, setLocale }), [locale])
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

