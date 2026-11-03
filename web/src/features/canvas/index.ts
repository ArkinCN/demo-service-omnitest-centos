/* C 区统一画板的对外出口。节点注册表与画板本体都从这里取。
   import './nodes' 是副作用注册：十一类节点在这一行落进 registry，
   因此不需要改已冻结的 src/features/index.tsx。 */
import './nodes'

export { CanvasHost } from './CanvasHost'
export { CANVAS_DND_MIME, type CanvasDragPayload } from './dnd'
export { registerCanvasNode, getCanvasNode, getCanvasNodes } from '../../registry'
export type { CanvasNodeRegistration } from '../../registry'
export {
  CANVAS_NODE_META,
  CANVAS_GROUP_ORDER,
  CANVAS_NODE_SIZE,
  defaultLayout,
  layoutKey,
  loadLayout,
  saveLayout,
  clearLayout,
  type CanvasNodeGroup,
  type CanvasLinkState,
} from './model'
export { defaultViewOf, useFlowView, FALLBACK_DEFAULT_VIEW, type PanelView } from './defaultView'
