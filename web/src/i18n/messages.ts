import { describeUiTranslation } from './runtime'
/** Provenance is assigned where local UI messages are produced, never inferred from role. */
export interface UiMessageText { key: string; params?: Record<string, string | number>; uiParams?: string[] }
const knownScripts = new Set<string>()
export function rememberScriptMessages(messages: readonly string[]) {
  for (const message of messages) knownScripts.add(message)
}
export function knownScriptMessage(text: string): boolean { return knownScripts.has(text) }
export function uiMessage(key: string, params?: Record<string, string | number>, uiParams?: string[]): UiMessageText {
  return params ? { key, params, ...(uiParams ? { uiParams } : {}) } : describeUiTranslation(key)
}
