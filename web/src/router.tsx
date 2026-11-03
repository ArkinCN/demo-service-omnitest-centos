import { createBrowserRouter, Navigate } from 'react-router'
import { FlowScreen } from './app/FlowScreen'
import { KnowledgePage } from './app/KnowledgePage'
import { Shell } from './app/Shell'
import { FLOWS } from './data/flows'
import { FanDemoPage } from './features/fan-trend'
import './features'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/init" replace /> },
      ...FLOWS.map((f) => ({
        path: f.path.slice(1),
        element: <FlowScreen flow={f.id} />,
      })),
      // 知识库是模块不是流程，走独立路由；/kb 是第三轮之前的旧路径，保留重定向
      { path: 'knowledge', element: <KnowledgePage /> },
      { path: 'kb', element: <Navigate to="/knowledge" replace /> },
      // 风扇趋势实验演示页（阶段 5 接入 v0.6 硬件交接包）
      { path: 'fan-demo', element: <FanDemoPage /> },
      { path: '*', element: <Navigate to="/init" replace /> },
    ],
  },
])
