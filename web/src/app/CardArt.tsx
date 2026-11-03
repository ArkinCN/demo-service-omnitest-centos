import type { CardId } from '../data/types'

/* 卡片占位图形：统一墨绿线条稿，填充只用 #EAF2EC，异常线用暗红。
   真实内容由 features 注册组件替换（registerPanelCard），这里保证壳层可独立跑通。 */

const INK = '#2E5E45'
const SOFT = '#A8C5B5'
const WASH = '#EAF2EC'
const RED = '#A6353A'
const GREY = '#C8C5BD'

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 200 120"
      className="h-full w-full"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

const ProductView = () => (
  <Frame>
    <rect x="44" y="20" width="112" height="80" rx="4" fill="none" stroke={INK} strokeWidth="1.4" />
    <circle cx="100" cy="60" r="24" fill={WASH} stroke={INK} strokeWidth="1.4" />
    {[0, 60, 120, 180, 240, 300].map((a) => (
      <path key={a} d="M100 60 L100 38 A22 22 0 0 1 119 49 Z" fill="none" stroke={SOFT} strokeWidth="1" transform={`rotate(${a} 100 60)`} />
    ))}
    <circle cx="100" cy="60" r="5" fill="none" stroke={INK} strokeWidth="1.4" />
    <path d="M52 30 h12 M52 90 h12" stroke={SOFT} strokeWidth="1" />
    <circle cx="150" cy="88" r="3" fill="none" stroke={RED} strokeWidth="1.2" />
    <path d="M150 88 h-14" stroke={RED} strokeWidth="1" strokeDasharray="3 3" />
  </Frame>
)

const Schematic = () => (
  <Frame>
    <path d="M22 28 H72 M72 28 V52 M72 52 H104" stroke={INK} strokeWidth="1.2" fill="none" />
    <rect x="80" y="18" width="28" height="14" fill="none" stroke={INK} strokeWidth="1.2" />
    <rect x="104" y="38" width="44" height="30" rx="2" fill={WASH} stroke={INK} strokeWidth="1.3" />
    <path d="M148 53 H180 M22 92 H180 M56 52 V92 M126 68 V92" stroke={SOFT} strokeWidth="1" fill="none" />
    <circle cx="56" cy="92" r="2" fill={INK} />
    <circle cx="126" cy="92" r="2" fill={INK} />
  </Frame>
)

const ProjectTree = () => (
  <Frame>
    <path d="M40 24 V96" stroke={SOFT} strokeWidth="1" />
    {[32, 48, 64, 80].map((y, i) => (
      <g key={y}>
        <path d={`M40 ${y} h${i === 1 || i === 2 ? 18 : 12}`} stroke={SOFT} strokeWidth="1" />
        <rect x={i === 1 || i === 2 ? 58 : 52} y={y - 6} width={i === 1 ? 88 : 74} height="12" rx="2" fill={i === 1 ? WASH : 'none'} stroke={i === 1 ? INK : GREY} strokeWidth="1" />
      </g>
    ))}
    <path d="M40 24 h-6 v-6" stroke={INK} strokeWidth="1.2" fill="none" />
  </Frame>
)

const Tools = () => (
  <Frame>
    {[0, 1, 2, 3].map((r) => (
      <g key={r}>
        <rect x="34" y={22 + r * 20} width="132" height="14" rx="2" fill={r === 0 ? WASH : 'none'} stroke={r === 0 ? INK : GREY} strokeWidth="1" />
        <circle cx="42" cy={29 + r * 20} r="2.5" fill={r === 3 ? RED : r === 2 ? GREY : INK} />
        <path d={`M52 ${29 + r * 20} h${r === 1 ? 64 : 48}`} stroke={SOFT} strokeWidth="1" />
      </g>
    ))}
  </Frame>
)

const BenchLive = () => (
  <Frame>
    <rect x="22" y="26" width="72" height="68" rx="3" fill="none" stroke={INK} strokeWidth="1.3" />
    <circle cx="58" cy="60" r="20" fill="none" stroke={SOFT} strokeWidth="1.2" />
    <path d="M58 40 V60 L73 69" stroke={INK} strokeWidth="1.2" fill="none" />
    <rect x="108" y="30" width="70" height="34" rx="3" fill={WASH} stroke={INK} strokeWidth="1.2" />
    <path d="M116 48 h14 l6 -11 l7 19 l6 -8 h18" stroke={INK} strokeWidth="1.1" fill="none" />
    <rect x="108" y="72" width="32" height="14" rx="2" fill="none" stroke={GREY} strokeWidth="1" />
    <rect x="146" y="72" width="32" height="14" rx="2" fill="none" stroke={GREY} strokeWidth="1" />
  </Frame>
)

const RemoteDevice = () => (
  <Frame>
    <rect x="30" y="22" width="140" height="76" rx="3" fill="none" stroke={INK} strokeWidth="1.3" />
    <path d="M30 34 H170" stroke={SOFT} strokeWidth="1" />
    {[46, 58, 70, 82].map((y, i) => (
      <path key={y} d={`M42 ${y} h${[60, 86, 44, 70][i]}`} stroke={i === 1 ? INK : SOFT} strokeWidth="1" />
    ))}
    <rect x="42" y="88" width="7" height="2" fill={INK} />
    <circle cx="38" cy="28" r="2" fill={SOFT} />
  </Frame>
)

const Interlock = () => (
  <Frame>
    <path d="M100 18 L138 34 V62 C138 80 120 92 100 100 C80 92 62 80 62 62 V34 Z" fill="none" stroke={INK} strokeWidth="1.4" />
    <path d="M84 58 l11 12 l22 -24" stroke={INK} strokeWidth="1.6" fill="none" />
    <path d="M100 18 L138 34 V62 C138 72 132 80 124 87" stroke={RED} strokeWidth="1.3" fill="none" strokeDasharray="5 4" />
    <circle cx="140" cy="88" r="7" fill="none" stroke={RED} strokeWidth="1.2" />
    <path d="M140 84 v5 M140 92 v1" stroke={RED} strokeWidth="1.2" />
  </Frame>
)

const Workflow = () => {
  const xs = [18, 54, 90, 126, 162]
  return (
    <Frame>
      {xs.map((x, i) => (
        <g key={x}>
          <rect x={x} y="46" width="24" height="24" rx="3" fill={i === 3 ? WASH : 'none'} stroke={i === 3 ? INK : SOFT} strokeWidth="1.3" />
          {i < xs.length - 1 ? <path d={`M${x + 24} 58 H${x + 36}`} stroke={SOFT} strokeWidth="1" /> : null}
          <text x={x + 12} y={86} textAnchor="middle" fontSize="7" fill="#9A9A9A" fontFamily="monospace">{`0${i + 1}`}</text>
        </g>
      ))}
      <path d="M126 40 v-10 h24" stroke={RED} strokeWidth="1" fill="none" strokeDasharray="4 3" />
    </Frame>
  )
}

const Timeseries = () => {
  const a = Array.from({ length: 62 }, (_, i) => {
    const x = 16 + i * 2.85
    const y = 56 - Math.sin(i / 4.2) * 18 * (1 - i / 180) - (i > 38 ? 7 : 0)
    return `${x},${y.toFixed(1)}`
  }).join(' ')
  const b = Array.from({ length: 62 }, (_, i) => `${16 + i * 2.85},${90 - (i % 8 < 4 ? 10 : 0)}`).join(' ')
  return (
    <Frame>
      {[26, 46, 66].map((y) => (
        <path key={y} d={`M16 ${y} H190`} stroke={SOFT} strokeWidth="0.6" strokeDasharray="3 5" />
      ))}
      <polyline points={a} fill="none" stroke={INK} strokeWidth="1.4" />
      <polyline points={b} fill="none" stroke={SOFT} strokeWidth="1.1" />
      <path d="M16 12 V102 H190" stroke={GREY} strokeWidth="1" fill="none" />
      <rect x="120" y="12" width="18" height="90" fill={RED} opacity="0.08" />
      <path d="M120 12 V102" stroke={RED} strokeWidth="1" strokeDasharray="4 3" />
    </Frame>
  )
}

const Progress = () => (
  <Frame>
    <rect x="22" y="22" width="156" height="10" rx="2" fill="none" stroke={GREY} strokeWidth="1" />
    <rect x="22" y="22" width="98" height="10" rx="2" fill={WASH} stroke={INK} strokeWidth="1" />
    {[46, 58, 70, 82, 94].map((y, i) => (
      <g key={y}>
        <path d={`M22 ${y} h${[120, 96, 140, 86, 110][i]}`} stroke={i === 2 ? INK : SOFT} strokeWidth="1" />
        {i === 2 ? <circle cx="16" cy={y} r="2.5" fill={RED} /> : null}
      </g>
    ))}
  </Frame>
)

const Verdict = () => (
  <Frame>
    <path d="M22 26 H178" stroke={GREY} strokeWidth="1" />
    {[40, 60, 80].map((y, i) => (
      <g key={y}>
        <path d={`M22 ${y + 10} H178`} stroke={SOFT} strokeWidth="0.8" />
        <path d={`M30 ${y} h${[70, 84, 60][i]}`} stroke={SOFT} strokeWidth="1" />
        {i === 2 ? (
          <g stroke={RED} strokeWidth="1.5"><path d="M150 -6 l8 8 M158 -6 l-8 8" transform={`translate(0 ${y})`} /></g>
        ) : (
          <path d={`M150 ${y} l4 5 l9 -11`} stroke={INK} strokeWidth="1.5" fill="none" />
        )}
      </g>
    ))}
  </Frame>
)

const Evidence = () => (
  <Frame>
    <rect x="36" y="18" width="74" height="78" rx="3" fill="none" stroke={SOFT} strokeWidth="1.1" />
    <rect x="48" y="26" width="74" height="78" rx="3" fill={WASH} stroke={INK} strokeWidth="1.3" />
    {[42, 54, 66, 78].map((y) => (
      <path key={y} d={`M60 ${y} H${y === 78 ? 98 : 110}`} stroke={INK} strokeWidth="1" opacity="0.5" />
    ))}
    <circle cx="142" cy="74" r="16" fill="none" stroke={INK} strokeWidth="1.3" />
    <path d="M153 85 L166 98" stroke={INK} strokeWidth="1.5" />
  </Frame>
)

const History = () => {
  const bars = [30, 44, 38, 56, 66]
  return (
    <Frame>
      {bars.map((h, i) => (
        <rect key={i} x={34 + i * 28} y={92 - h} width="16" height={h} fill={i === bars.length - 1 ? WASH : 'none'} stroke={i === bars.length - 1 ? INK : SOFT} strokeWidth="1.1" />
      ))}
      <path d="M26 92 H180" stroke={GREY} strokeWidth="1" />
      <path d="M34 60 H180" stroke={RED} strokeWidth="1" strokeDasharray="4 3" />
      <polyline points="42,62 70,50 98,56 126,38 154,28" fill="none" stroke={INK} strokeWidth="1.2" />
    </Frame>
  )
}

const Artifacts = () => (
  <Frame>
    {[0, 1, 2].map((i) => (
      <rect key={i} x={40 + i * 10} y={26 + i * 8} width="80" height="62" rx="3" fill={i === 2 ? WASH : 'none'} stroke={i === 2 ? INK : SOFT} strokeWidth="1.2" />
    ))}
    {[54, 66, 78].map((y) => (
      <path key={y} d={`M70 ${y} h${y === 78 ? 34 : 52}`} stroke={INK} strokeWidth="1" opacity="0.5" />
    ))}
    <path d="M150 50 v34 M140 74 l10 10 l10 -10" stroke={INK} strokeWidth="1.3" fill="none" />
  </Frame>
)

const ReportPreview = () => (
  <Frame>
    <rect x="30" y="18" width="64" height="84" rx="3" fill="none" stroke={SOFT} strokeWidth="1.1" />
    <rect x="102" y="18" width="64" height="84" rx="3" fill={WASH} stroke={INK} strokeWidth="1.3" />
    {[34, 44, 54, 64, 74].map((y) => (
      <g key={y}>
        <path d={`M40 ${y} h${y === 74 ? 28 : 44}`} stroke={SOFT} strokeWidth="1" />
        <path d={`M112 ${y} h${y === 54 ? 28 : 44}`} stroke={INK} strokeWidth="1" opacity="0.5" />
      </g>
    ))}
    <path d="M112 88 h20" stroke={RED} strokeWidth="1.3" />
  </Frame>
)

const ART: Record<CardId, () => React.ReactElement> = {
  'product-view': ProductView,
  schematic: Schematic,
  'project-tree': ProjectTree,
  tools: Tools,
  'bench-live': BenchLive,
  'remote-device': RemoteDevice,
  interlock: Interlock,
  workflow: Workflow,
  'wf-lib': ProjectTree,
  timeseries: Timeseries,
  progress: Progress,
  pipeline: Progress,
  candidates: Verdict,
  'param-changes': Verdict,
  verdict: Verdict,
  evidence: Evidence,
  history: History,
  experience: Evidence,
  artifacts: Artifacts,
  'report-preview': ReportPreview,
  'template-fields': ProjectTree,
}

export function CardArt({ id }: { id: CardId }) {
  const C = ART[id] ?? Evidence
  return (
    <div className="flex h-full w-full items-center justify-center">
      <C />
    </div>
  )
}
