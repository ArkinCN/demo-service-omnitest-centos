import {
  createElement,
  useSyncExternalStore,
  type ComponentType,
  type ReactNode,
} from 'react'
import type {
  CanvasNode,
  CanvasNodeType,
  CardId,
  CopilotAction,
  FlowId,
  ModuleId,
  ScenePackage,
} from '../data/types'

/* ===========================================================================
   扩展注册表：别的 agent 把组件放在 src/features/<name>/ 下，
   在该目录的 index.ts 里调用 registerPanelCard / registerLeftPanel，
   再由 src/features/index.ts 统一 import 一次即可接入，Shell 不需要改。
   =========================================================================== */

export interface PanelCardContext {
  flow: FlowId
  scene: ScenePackage
}

export interface PanelCardRegistration {
  /** 卡片库标识（src/data/cards.ts）。用库内标识即可替换默认占位卡片。 */
  id: CardId
  label: string
  caption?: string
  /** 限定出现在哪些流程，'*' 表示全部 */
  flows?: FlowId[] | '*'
  /** 卡片缩略内容 */
  render: (ctx: PanelCardContext) => ReactNode
  /** 放大后的内容，缺省时复用 render */
  renderExpanded?: (ctx: PanelCardContext) => ReactNode
  /** 数字越小越靠前，默认 100 */
  order?: number
}

export interface LeftPanelRegistration {
  flow: FlowId
  component: ComponentType<{ flow: FlowId; scene: ScenePackage }>
}

/* ------------------------------------------------------------- 第三轮新增契约 */

/** 模块页（不占流程序号，路由从 src/router.tsx 挂）。知识库是第一个模块。 */
export interface ModulePageRegistration {
  id: ModuleId
  component: ComponentType
}

/** 画板节点实现。W3 在 src/features/canvas/ 下按节点类型逐个注册。 */
export interface CanvasNodeRegistration {
  type: CanvasNodeType
  label: string
  render: (ctx: { node: CanvasNode; flow: FlowId; scene: ScenePackage }) => ReactNode
  /** 默认尺寸，画板落点建节点时用 */
  size?: { w: number; h: number }
}

const cards = new Map<string, PanelCardRegistration>()
const modulePages = new Map<ModuleId, ComponentType>()
const canvasNodes = new Map<CanvasNodeType, CanvasNodeRegistration>()
const copilotActions = new Map<FlowId | ModuleId, CopilotAction[]>()
const leftPanels = new Map<FlowId, LeftPanelRegistration>()
const assistants = new Map<FlowId, AssistantComponent>()

let version = 0
const listeners = new Set<() => void>()
const bump = () => {
  version += 1
  listeners.forEach((l) => l())
}

/** 注册一张右上资源面板卡片 */
export function registerPanelCard(reg: PanelCardRegistration) {
  cards.set(reg.id, reg)
  bump()
}

/** 注册某条流程路由的左栏内容（整块替换默认参数栏） */
export function registerLeftPanel(
  flow: FlowId,
  component: LeftPanelRegistration['component'],
) {
  leftPanels.set(flow, { flow, component })
  bump()
}

/**
 * 注册某条流程的 D 区助手对话（整块替换默认演示对话）。
 *
 * 组件除了 flow / scene，还会收到壳层带的 onCollapse（可选）。类型在这里一并
 * 声明出来，注册方才能把它透传给自己的实现——否则类型上收窄，实际拿到了也传不下去。
 */
export type AssistantComponent = ComponentType<{
  flow: FlowId
  scene: ScenePackage
  onCollapse?: () => void
}>

export function registerAssistant(flow: FlowId, component: AssistantComponent) {
  assistants.set(flow, component)
  bump()
}

/** 注册一个模块页的整页内容。W2 用它把 /knowledge 的版式挂进来。 */
export function registerModulePage(id: ModuleId, component: ComponentType) {
  modulePages.set(id, component)
  bump()
}

export function hasModulePage(id: ModuleId) {
  return modulePages.has(id)
}

/** 渲染模块页；未注册时返回 null，由 src/app/KnowledgePage.tsx 画空壳 */
export function renderModulePage(id: ModuleId): ReactNode {
  const c = modulePages.get(id)
  return c ? createElement(c) : null
}

/** 注册一类画板节点的渲染。W3 用。 */
export function registerCanvasNode(reg: CanvasNodeRegistration) {
  canvasNodes.set(reg.type, reg)
  bump()
}

export function getCanvasNode(type: CanvasNodeType): CanvasNodeRegistration | undefined {
  return canvasNodes.get(type)
}

export function getCanvasNodes(): CanvasNodeRegistration[] {
  return [...canvasNodes.values()]
}

/**
 * 登记某条流程或模块的助手预置动作。W5 用。
 * 同一 key 重复调用整条替换，不做合并——切场景包时按新包整条换掉。
 */
export function registerCopilotActions(flow: FlowId | ModuleId, actions: CopilotAction[]) {
  copilotActions.set(flow, actions)
  bump()
}

export function getCopilotActions(flow: FlowId | ModuleId): CopilotAction[] {
  return copilotActions.get(flow) ?? []
}

export function hasAssistant(flow: FlowId) {
  return assistants.has(flow)
}

/**
 * 渲染注册进来的助手。
 *
 * onCollapse 要原样透传给组件：它由壳层（FlowScreen）提供，用来在助手头部
 * 挂一枚「收起」。此前这里的 props 类型只声明了 flow / scene，虽然运行时
 * 传进来的对象带着 onCollapse，但类型上被裁掉，组件里读不到 → 收起键不渲染。
 * 契约里补上这个可选字段，注册方与壳层就对得上了。
 */
export function renderAssistant(
  flow: FlowId,
  props: { flow: FlowId; scene: ScenePackage; onCollapse?: () => void },
): ReactNode {
  const c = assistants.get(flow)
  return c ? createElement(c, props) : null
}

export function getPanelCards(flow: FlowId): PanelCardRegistration[] {
  return [...cards.values()]
    .filter((c) => !c.flows || c.flows === '*' || c.flows.includes(flow))
    .sort((a, b) => (a.order ?? 100) - (b.order ?? 100))
}

export function hasLeftPanel(flow: FlowId) {
  return leftPanels.has(flow)
}

/** 渲染注册进来的左栏；未注册时返回 null，由壳层画默认参数栏 */
export function renderLeftPanel(
  flow: FlowId,
  props: { flow: FlowId; scene: ScenePackage },
): ReactNode {
  const reg = leftPanels.get(flow)
  return reg ? createElement(reg.component, props) : null
}

/** 让 Shell 在有新注册时重渲染 */
export function useRegistryVersion() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => version,
    () => version,
  )
}

