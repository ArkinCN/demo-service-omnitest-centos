import { useT } from '../i18n'
import { STAGE_PRESENTATION } from './configPresentation'
import { useState, type ReactNode } from 'react'
import { CheckCircle2, Lock, Sliders } from 'lucide-react'
import {
  Badge,
  Button,
  Collapsible,
  Panel,
  PanelHeader,
  Select,
  SourceTag,
  StatusDot,
  Stepper,
  Tooltip,
  cn,
} from '../components/ui'
import type {
  FlowId,
  ParamGroup,
  ParamItem,
  ParamSubGroup,
  ScenePackage,
} from '../data/types'
import { hasLeftPanel, renderLeftPanel, useRegistryVersion } from '../registry'
import { paramKey, useAppStore } from '../state/useAppStore'
import { KnowledgeDrawer } from '../features/knowledge/KnowledgeDrawer'

/** B 区 · 参数与确认（规格 6）：输入清单 + 分组手风琴 + 底部确认条 */

function Checklist({
  items,
  onLocate,
}: {
  items: ScenePackage['flows'][FlowId]['checklist']
  onLocate: (groupId: string) => void
}) {
  const uiT = useT()

  return (
    <div className="shrink-0 border-b border-line bg-sunk/60">
      <div className="flex items-center gap-2 px-3 pt-1.5 pb-1">
        <span className="text-[12px] text-t2">{uiT("本流程输入清单")}</span>
        <span className="num ml-auto text-[11px] text-t3">
          {items.filter((i) => i.status === 'done').length} / {items.length}
        </span>
      </div>
      {/* 窄屏自适应（2026-10-15）：加 flow-left-checklist 钩子 —— 堆叠档（≤860px）
          左栏只拿到容器高约 5/13，索引条上限由 index.css 从 152px 收到 72px
          （≤720px 再收到 48px），避免固定块挤爆内容区、底部确认按钮被裁。 */}
      <ul className="flow-left-checklist max-h-[152px] overflow-y-auto pb-1">
        {items.map((it) => (
          <li
            key={it.id}
            className={cn(
              'group flex h-[26px] items-center gap-2 px-3',
              it.status === 'alert' && 'bg-alert-wash/60',
            )}
          >
            <span className="num w-[16px] shrink-0 text-[11px] text-t3">{it.index}</span>
            <span
              className={cn(
                'truncate text-[12px]',
                it.status === 'alert'
                  ? 'text-alert'
                  : it.status === 'na'
                    ? 'text-t3'
                    : 'text-t1',
              )}
            >
              {it.name}
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-2">
              <StatusDot status={it.status} />
              <button
                type="button"
                onClick={() => onLocate(it.groupId)}
                className="rounded-tps border border-line px-1.5 text-[11px] leading-[18px] text-t3 transition-colors hover:border-ink hover:text-ink"
              >
                {uiT("定位")}</button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ParamRow({
  flow,
  group,
  sub,
  item,
  locked,
}: {
  flow: FlowId
  group: string
  sub: string
  item: ParamItem
  locked: boolean
}) {
  const uiT = useT()

  const key = paramKey(flow, group, sub, item.id)
  const override = useAppStore((s) => s.overrides[key])
  const touched = useAppStore((s) => s.touched[key])
  const setParam = useAppStore((s) => s.setParam)
  const value = override ?? item.value
  const alert = item.status === 'alert'
  const source = touched ? '人工' : item.source

  return (
    <div
      className={cn(
        'flex min-h-[32px] items-center gap-2 border-l-2 py-1 pr-3 pl-3',
        alert ? 'border-l-alert bg-alert-wash/45' : 'border-l-transparent',
      )}
    >
      <div className="w-[40%] min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={cn('truncate text-[13px]', alert ? 'text-alert' : 'text-t1')}>
            {item.name}
          </span>
          {item.pending ? (
            // 「待核实」≠「异常」：数值有来源、可以用，只是来源本身还没定版。
            // 所以给的是弱描边角标，不进暗红异常态，不占每屏 ≤3 处的暗红名额。
            <span
              className="shrink-0 rounded-tps border border-line px-1 text-[10px] leading-[15px] text-t3"
              title={uiT("待核实 · {v1}", { v1: item.pending })}
            >
              {uiT("待核实")}</span>
          ) : null}
          {source ? (
            <span className="shrink-0">
            <SourceTag
              source={source}
              title={
                touched
                  ? uiT("人工改过，原值 {v1}{v2}", { v1: item.value, v2: item.unit ?? '' })
                  : item.evidence
              }
            />
            </span>
          ) : null}
        </div>
        {item.note ? (
          <div className="truncate text-[11px] leading-4 text-t3">{item.note}</div>
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {item.kind === 'number' && typeof value === 'number' ? (
          <Stepper
            label={uiT(item.name)}
            value={value}
            unit={item.unit}
            step={item.step ?? 1}
            min={item.min}
            max={item.max}
            precision={item.precision ?? 0}
            disabled={locked}
            onChange={(n) => setParam(key, n)}
          />
        ) : item.kind === 'select' || item.kind === 'switch' ? (
          <Select
            size="sm"
            // 窄屏自适应（2026-10-15）：加 flow-param-select 钩子 —— 左栏在 ≤1024px
            // 只有 216~264px 宽，写死的 168px 会把参数名挤到只剩十几像素，
            // 由 index.css 在该档收到 132px。
            className="flow-param-select w-[168px]"
            label={item.name}
            options={(item.options ?? [String(value)]).map((o, i) => ({
              value: o,
              label: item.optionLabels?.[i] ?? o,
            }))}
            value={String(value)}
            disabled={locked}
            onChange={(v) => !locked && setParam(key, v)}
          />
        ) : (
          // 窄屏自适应（2026-10-15）：flow-param-value —— 同 flow-param-select，
          // 188px 的只读值在 216px 宽左栏里会顶出容器被 Panel 裁掉。
          <span
            className={cn(
              'flow-param-value num max-w-[188px] truncate rounded-tps border px-1.5 py-1 text-[12px]',
              alert
                ? 'border-alert/40 bg-white text-alert'
                : value === '不适用'
                  ? 'border-line-soft border-dashed bg-white text-t3'
                  : 'border-line-soft bg-sunk text-t2',
            )}
            title={value === '不适用' ? item.note : undefined}
          >
            {String(value)}
            {item.unit ? ` ${item.unit}` : ''}
          </span>
        )}
        {item.evidence ? (
          <button
            type="button"
            title={uiT("依据：{v1}", { v1: item.evidence })}
            className="h-[18px] w-[18px] shrink-0 rounded-tps border border-line text-[10px] leading-none text-t3 transition-colors hover:border-ink hover:text-ink"
          >
            ?
          </button>
        ) : null}
      </div>
    </div>
  )
}

function SubGroup({
  flow,
  group,
  sub,
  locked,
}: {
  flow: FlowId
  group: string
  sub: ParamSubGroup
  locked: boolean
}) {
  const uiT = useT()
  return (
    <div className="border-t border-line-soft first:border-t-0">
      <div className="flex h-[22px] items-center gap-2 bg-sunk/50 px-3">
        <span className="text-[11px] text-t2">{uiT(sub.title)}</span>
        <span className="num ml-auto text-[11px] text-t3">{sub.items.length}</span>
      </div>
      <div className="divide-y divide-line-soft">
        {sub.items.map((it) => (
          <ParamRow
            key={it.id}
            flow={flow}
            group={group}
            sub={sub.id}
            item={it}
            locked={locked}
          />
        ))}
      </div>
    </div>
  )
}

function GroupBlock({
  flow,
  group,
  locked,
  open,
}: {
  flow: FlowId
  group: ParamGroup
  locked: boolean
  open?: boolean
}) {
  const uiT = useT()
  const total = group.subgroups.reduce((n, s) => n + s.items.length, 0)
  const done = group.subgroups.reduce(
    (n, s) => n + s.items.filter((i) => i.status === 'done').length,
    0,
  )
  const alerts = group.subgroups.reduce(
    (n, s) => n + s.items.filter((i) => i.status === 'alert').length,
    0,
  )
  return (
    <div id={`grp-${group.id}`}>
      <Collapsible
        index={group.index}
        title={uiT(group.title)}
        defaultOpen={open ?? group.defaultOpen ?? true}
        right={
          <span className="flex items-center gap-2">
            {alerts ? (
              <span className="rounded-tps border border-alert px-1 text-[10px] leading-[15px] text-alert">
                {alerts} {uiT("异常")}</span>
            ) : null}
            <span className="num text-[11px] text-t3">
              {uiT("已填")}{done}/{total}
            </span>
          </span>
        }
      >
        {group.subgroups.map((s) => (
          <SubGroup key={s.id} flow={flow} group={group.id} sub={s} locked={locked} />
        ))}
      </Collapsible>
    </div>
  )
}

export function LeftPanel({ flow, scene }: { flow: FlowId; scene: ScenePackage }) {
  const uiT = useT()

  const content = scene.flows[flow]
  const locked = !!useAppStore((s) => s.confirmed[flow])
  const confirmFlow = useAppStore((s) => s.confirmFlow)
  const unconfirmFlow = useAppStore((s) => s.unconfirmFlow)
  const [forceOpen, setForceOpen] = useState<string | null>(null)
  useRegistryVersion()
  const custom = hasLeftPanel(flow)

  const locate = (groupId: string) => {
    setForceOpen(groupId)
    document
      .getElementById(`grp-${groupId}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const alerts = content.checklist.filter((c) => c.status === 'alert').length

  // 第三轮：五个流程页的 B 区顶部统一挂一条「本流程可用知识」窄条。
  // 各流程页用 registerLeftPanel 接管了左栏，所以窄条只能挂在这一层，
  // 接管与不接管两条分支都要挂。
  if (custom) {
    return (
      <Panel>
        <KnowledgeDrawer flow={flow} />
        {renderLeftPanel(flow, { flow, scene })}
      </Panel>
    )
  }

  return (
    <Panel>
      <PanelHeader
        icon={<Sliders size={17} strokeWidth={1.9} />}
        title={uiT("参数")}
        right={
          locked ? (
            <Badge tone="soft" dot>
              {uiT("已锁定")}</Badge>
          ) : alerts ? (
            <Badge tone="warn" dot>
              {alerts} {uiT("待处理")}</Badge>
          ) : null
        }
      />

      <KnowledgeDrawer flow={flow} />
      <Checklist items={content.checklist} onLocate={locate} />
      <div key={flow} className="animate-rise fade-b min-h-0 flex-1 overflow-y-auto">
        {content.groups.map((g) => (
          <GroupBlock
            key={g.id}
            flow={flow}
            group={g}
            locked={locked}
            open={forceOpen === g.id ? true : undefined}
          />
        ))}
      </div>

      <footer className="shrink-0 border-t border-line-soft bg-white/85 px-4 py-3 backdrop-blur">
        <Tooltip content={content.verifyLine}>
          <span className="mb-2 flex w-full items-center gap-2 text-[12px] text-t3">
            <span className="num">
              {content.checklist.filter((c) => c.status === 'done').length}/{content.checklist.length}
            </span>
            <span className="truncate">{uiT("已就绪")}</span>
          </span>
        </Tooltip>
        {locked ? (
          <Button block size="lg" variant="secondary" icon={<Lock size={15} strokeWidth={2} />} onClick={() => unconfirmFlow(flow)}>
            {uiT("解除确认")}</Button>
        ) : (
          <Button block size="lg" variant="primary" icon={<CheckCircle2 size={15} strokeWidth={2} />} onClick={() => confirmFlow(flow)}>
            {uiT("确认参数")}</Button>
        )}
      </footer>
    </Panel>
  )
}

/** Stage purpose followed by one category-based view of the source fields. */
export function ConfigOverview({ flow, children, actions, assist }: { flow: FlowId; children: ReactNode; count: number; actions?: ReactNode; assist?: ReactNode }) {
  // 2026-10-29：阶段标题/描述只存中文，英文统一由 catalog.ts 提供，不再在这里判 locale。
  const uiT = useT()
  const stage = STAGE_PRESENTATION[flow]
  return <section className="config-overview" data-flow={flow} aria-label={uiT('本阶段配置')}>
    <header className="stage-purpose">
      <div><span className="stage-purpose-index">{stage.index} / 05</span><h3>{uiT(stage.title)}</h3></div>
      <p>{uiT(stage.description)}</p>
    </header>
    {assist}
    {actions}
    <div className="config-complete">{children}</div>
  </section>
}
