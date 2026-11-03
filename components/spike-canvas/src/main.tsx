import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './tokens.css'
import { FlowSpike } from './FlowSpike'
import { SvgSpike } from './SvgSpike'

function App() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const f = () => setHash(window.location.hash)
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  const svg = hash === '#svg'
  return (
    <div className="stage">
      <div className="stage-hint">
        <strong style={{ color: 'var(--p-700)' }}>C 区统一画布 spike</strong>
        <a href="#flow" style={{ fontWeight: svg ? 400 : 700 }}>方案 A · React Flow</a>
        <a href="#svg" style={{ fontWeight: svg ? 700 : 400 }}>方案 B · 自研 SVG</a>
        <span>滚轮缩放 / 空白处拖拽平移 / 双击复位 / 右侧工具条拖入节点</span>
      </div>
      {svg ? <SvgSpike /> : <FlowSpike />}
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
