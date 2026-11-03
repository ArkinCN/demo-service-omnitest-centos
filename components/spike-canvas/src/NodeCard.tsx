import { createElement } from 'react'
import { KIND, type CanvasNodeData } from './model'

/** 节点外观：描边成形、无实色填充；卡头浅绿底 + lucide 图标；卡底状态圆点 */
export function NodeCard({
  data, selected, alert,
}: { data: CanvasNodeData; selected?: boolean; alert?: boolean }) {
  const meta = KIND[data.kind]
  const cls = ['ncard', selected ? 'sel' : '', alert || data.state === 'fault' ? 'alert' : ''].join(' ')
  const stateText: Record<CanvasNodeData['state'], string> = {
    online: '已连接', warn: '有告警', fault: '连接中断', offline: '未连接',
  }
  return (
    <div className={cls}>
      <div className="ncard-head">
        {createElement(meta.icon, { size: 15, strokeWidth: 1.8 })}
        <div>
          <div className="ncard-title">{data.name}</div>
          <div className="ncard-kind">{meta.label} · {meta.sub}</div>
        </div>
        {meta.tag ? <span className="tag">{meta.tag}</span> : null}
      </div>
      {data.facts?.length ? (
        <div className="ncard-body">
          {data.facts.slice(0, 3).map(([k, v]) => (
            <div className="krow" key={k}>
              <span className="k">{k}</span>
              <span className="v">{v}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="ncard-foot">
        <span className={`dot ${data.state}`} />
        <span>{stateText[data.state]}</span>
        {data.channel ? <span style={{ marginLeft: 'auto' }}>{data.channel}</span> : null}
      </div>
    </div>
  )
}
