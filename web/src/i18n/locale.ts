import { createContext, useCallback, useContext } from 'react'
import { translate, type Locale, type TranslationParams } from './runtime'

export const LOCALE_STORAGE_KEY = 'omnitest.locale'

export function initialLocale(): Locale {
  try { return localStorage.getItem(LOCALE_STORAGE_KEY) === 'en' ? 'en' : 'zh-CN' }
  catch { return 'zh-CN' }
}

export const LocaleContext = createContext<{ locale: Locale; setLocale: (locale: Locale) => void }>({
  locale: 'zh-CN', setLocale: () => {},
})

export function useLocale() { return useContext(LocaleContext) }

export function useT() {
  const { locale } = useLocale()
  return useCallback(<T extends string | null | undefined>(source: T, params?: TranslationParams): T =>
    (typeof source === 'string' ? translate(source, locale, params) : source) as T, [locale])
}

