/** 画板给节点实现用的回调通道：节点里点「放大」由画板统一开浮层，节点自己不开。 */
import { createContext, useContext } from 'react'
import type { CanvasNode } from '../../data/types'

export interface CanvasCtxValue {
  expand: (node: CanvasNode) => void
  selectedId: string | null
}

export const CanvasCtx = createContext<CanvasCtxValue>({ expand: () => {}, selectedId: null })

export const useCanvasCtx = () => useContext(CanvasCtx)
