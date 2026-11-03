import { AgentChat } from './features/agent-chat';
import { MOCK_EVIDENCE, mockAdapter, mockAdapterInstant } from './features/agent-chat/api';
import './App.css';

const PROMPT = '这颗片子空载启动时电流看着有点冲，帮我按规程核一下启动电流是否合格。';

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') ?? 'panel'; // panel | full
  const instant = params.get('instant') === '1';
  const withEvidence = params.get('evidence') === '1';
  // hold=1：停在「待确认」态，用于截图人工确认闸门
  const hold = params.get('hold') === '1';
  const adapter = instant ? mockAdapterInstant : mockAdapter;

  const bare = params.get('bare') === '1';
  const panelHeight = view === 'full' ? 1000 : 420;

  const chat = (
    <AgentChat
      adapter={adapter}
      autoStartPrompt={PROMPT}
      autoConfirm={instant && !hold}
      initialEvidence={withEvidence ? MOCK_EVIDENCE : []}
      evidenceOpenOnMount={withEvidence}
    />
  );

  if (bare) {
    return (
      <div className="demo demo--bare">
        <div className="demo__stage" style={{ width: 1600, height: panelHeight }}>
          {chat}
        </div>
      </div>
    );
  }

  return (
    <div className="demo" data-view={view}>
      <div className="demo__bar">
        <span className="demo__name">测试副驾对话组件 · 演示</span>
        <span className="demo__meta">
          {view === 'full' ? '全屏态 1600 × 1000（依据抽屉展开）' : '右下角面板态 1600 × 420'}
        </span>
      </div>
      <div className="demo__stage" style={{ height: panelHeight }}>
        {chat}
      </div>
    </div>
  );
}
