import { useT } from '../i18n'
/* ===========================================================================
   知识库模块页 · 空壳。

   第三轮把知识库从流程 1 降级为模块：不进 stepper、不套流程页的四块壳，
   从顶栏右端的常驻按钮进入。整页版式（顶条面包屑、左栏三轴筛选、
   中栏条目列表、右栏详情、底栏助手）由 W2 用 registerModulePage('knowledge', …)
   注册进来，本文件一行版式都不写。触发注册的那一行 import 收尾轮已统一收进
   src/features/index.tsx（扩展装配点），本文件不再自己引。
   =========================================================================== */
import { Library } from 'lucide-react'
import { EmptyState, Panel, PanelHeader } from '../components/ui'
import { hasModulePage, renderModulePage, useRegistryVersion } from '../registry'

export function KnowledgePage() {
  const uiT = useT()

  useRegistryVersion()
  if (hasModulePage('knowledge')) return <>{renderModulePage('knowledge')}</>

  return (
    <div className="flex min-h-0 w-full flex-1 [&>*]:flex-1">
      <Panel>
        <PanelHeader icon={<Library size={17} strokeWidth={1.9} />} title={uiT("知识库")} />
        <div className="min-h-0 flex-1">
          <EmptyState
            icon={<Library size={24} strokeWidth={1.5} />}
            title={uiT("知识库模块待接入")}
            hint={uiT("三轴分类与条目列表由知识库模块提供，本轮先落路由与壳。")}
          />
        </div>
      </Panel>
    </div>
  )
}
