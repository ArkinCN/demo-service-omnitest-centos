import { createElement } from 'react'
import { KIND, RAIL, type RailItem } from './model'

/** 右侧竖向工具条：按住图标拖到画布中间即落节点（HTML5 DnD，React Flow / SVG 两版共用） */
export function ToolRail() {
  return (
    <aside className="rail" data-testid="rail">
      {RAIL.map((g) => (
        <div className="rail-group" key={g.id}>
          <span className="rail-label">{g.title}</span>
          {g.items.map((it) => (
            <button
              key={g.id + it.kind + it.name}
              type="button"
              className="rail-btn"
              title={`${it.name} · 拖入画布`}
              data-kind={it.kind}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/x-canvas-node', JSON.stringify(it satisfies RailItem))
                e.dataTransfer.effectAllowed = 'move'
              }}
            >
              {createElement(KIND[it.kind].icon, { size: 16, strokeWidth: 1.75 })}
              <span className={`dot ${it.state}`} />
            </button>
          ))}
        </div>
      ))}
    </aside>
  )
}
