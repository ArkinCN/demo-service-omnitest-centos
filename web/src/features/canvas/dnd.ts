/** 工具条 → 画板的拖拽载荷。单独成文件，避免与组件混在一个模块里。 */
import type { CanvasNodeType } from '../../data/types'

export const CANVAS_DND_MIME = 'application/x-canvas-node'

export interface CanvasDragPayload {
  type: CanvasNodeType
  label: string
}
