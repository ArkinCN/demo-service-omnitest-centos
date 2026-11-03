import { uiMessage, rememberScriptMessages } from '../../i18n/messages'
import { useT } from '../../i18n'
/* ===========================================================================
   知识库模块页 /knowledge 的整页版式。

   第三轮把知识库从流程 1 降级为五条流程共用的基础模块：不进 stepper、
   不套流程页的四块壳、没有动作条、没有 3×2 卡片网格、没有右侧竖工具条。
   版式按 06a 第 4.2 节的线框：顶条（归属面包屑 + 三枚操作按钮）、
   左栏三轴筛选、中栏条目列表（内部滚动 + 分页）、右栏选中条目详情、
   底栏助手（满宽，可收起为一行输入框）。

   三条平铺规则（《07-第三轮实施计划》第三节第 7 条）的落法：
   - 规则一：左栏三个轴的组内条目分别是 3 / 2 / 3 条，都不超过 5；
     中栏列表分页，每页 12 条。
   - 规则二：左栏首屏可见元素 = 3 个轴头 + 归属轴 3 行 = 6 个。
   - 规则三：初次进入只展开归属轴，展开条目 3 条。
   =========================================================================== */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Library,
  MessageSquare,
  RefreshCw,
} from 'lucide-react'
import {
  Badge,
  Button,
  Collapsible,
  EmptyState,
  Modal,
  Panel,
  PanelHeader,
  Skeleton,
  Tooltip,
  cn,
} from '../../components/ui'
import { KNOWLEDGE_ICON } from '../../app/icons'
import {
  KNOWLEDGE_ORIGIN_LABEL,
  KNOWLEDGE_USAGE_LABEL,
  type KnowledgeOrigin,
  type KnowledgeUsage,
} from '../../data/types'
import { collapseKey, useAppStore } from '../../state/useAppStore'
import { AgentChat, type AgentChatApi } from '../agent-chat'
import { Markdown } from '../agent-chat/components/Markdown'
import { ActionDock } from '../copilot'
import { useKnowledgeAdapter } from '../copilot/knowledgeAdapter'
import {
  DocContentError,
  extractDownloadUrl,
  fetchCombined,
  fetchDocContent,
  kbExportUrl,
  rememberDocId,
  type CombinedDoc,
  type DocContent,
} from './knowledgeApi'
import { sizeText } from '../scene/pack'
import { filterKnowledge, useKnowledge, type KnowledgeEntry } from './data'
import { UploadPanel } from './UploadPanel'

const USAGES: KnowledgeUsage[] = ['spec', 'requirement', 'process']
const ORIGINS: KnowledgeOrigin[] = ['doc', 'experience']
const PAGE_SIZE = 12
const GAP = 'clamp(14px, 1.25vw, 24px)'

/* 本页会话级持久化：页码与「只看新增」开关。
   用户实测「每次刷新所有状态都初始化」——kbFilter/kbSelectedId 走 store（见 useAppStore），
   这两个纯视图态留在本页，与 `omnitest.kb.assistantHeight` 同一套 localStorage 做法。 */
const LS_KB_PAGE = 'omnitest.kb.page.v1'
const LS_KB_SCOPE_NEW = 'omnitest.kb.scopeNew.v1'

function readPage(): number {
  try {
    const n = Number(localStorage.getItem(LS_KB_PAGE))
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0
  } catch {
    return 0
  }
}
function writePage(p: number) {
  try {
    localStorage.setItem(LS_KB_PAGE, String(p))
  } catch {
    /* 存不下只在本次会话生效 */
  }
}
function readScopeNew(): boolean {
  try {
    return localStorage.getItem(LS_KB_SCOPE_NEW) === '1'
  } catch {
    return false
  }
}
function writeScopeNew(on: boolean) {
  try {
    localStorage.setItem(LS_KB_SCOPE_NEW, on ? '1' : '0')
  } catch {
    /* 同上 */
  }
}

/** 数组开关：有就去掉、没有就加上 */
const toggle = <T,>(list: T[], v: T): T[] =>
  list.includes(v) ? list.filter((x) => x !== v) : [...list, v]

/* ------------------------------------------------------------------ 筛选一行 */

function FilterRow({
  label,
  count,
  active,
  onClick,
  indent,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
  indent?: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'flex h-[30px] w-full items-center gap-2 pr-4 text-left transition-colors',
        active ? 'bg-p50 text-p700' : 'text-t2 hover:bg-p50/60',
      )}
      style={{ paddingLeft: 16 + (indent ?? 0) * 14 }}
    >
      <span
        className={cn(
          'h-[6px] w-[6px] shrink-0 rounded-full',
          active ? 'bg-p600' : 'bg-line',
        )}
      />
      <span className="min-w-0 flex-1 truncate text-[12.5px]">{label}</span>
      <span className="num text-[11.5px] text-t3">{count}</span>
    </button>
  )
}

/* -------------------------------------------------------------------- 左栏 */

function FilterColumn({ entries }: { entries: KnowledgeEntry[] }) {
  const uiT = useT()

  const kbFilter = useAppStore((s) => s.kbFilter)
  const setKbFilter = useAppStore((s) => s.setKbFilter)
  const owner = entries[0]?.owner ?? ['', '', '']

  /** 某一轴的计数按「其余两轴已生效」算，这样数字跟点下去的结果对得上 */
  const countFor = (axis: 'usage' | 'origin' | 'owner', value: string) => {
    const base = {
      usage: axis === 'usage' ? [] : kbFilter.usage,
      origin: axis === 'origin' ? [] : kbFilter.origin,
      owner: axis === 'owner' ? [] : kbFilter.owner,
    }
    const pool = filterKnowledge(entries, base)
    if (axis === 'usage') return pool.filter((e) => e.usage === value).length
    if (axis === 'origin') return pool.filter((e) => e.origin === value).length
    return pool.filter((e) => e.owner.includes(value)).length
  }

  const dirty =
    kbFilter.usage.length + kbFilter.origin.length + kbFilter.owner.length > 0

  const Owner = KNOWLEDGE_ICON.owner
  const Origin = KNOWLEDGE_ICON.origin
  const Usage = KNOWLEDGE_ICON.usage
  const Filter = KNOWLEDGE_ICON.filter

  return (
    <Panel style={{ width: 'clamp(248px, 17vw, 320px)' }} className="knowledge-axis-panel shrink-0">
      <PanelHeader
        icon={<Filter size={17} strokeWidth={1.9} />}
        title={uiT("分类筛选")}
        right={
          dirty ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setKbFilter({ usage: [], origin: [], owner: [] })}
            >
              {uiT("重置")}</Button>
          ) : (
            <Badge tone="neutral">{uiT("三轴")}</Badge>
          )
        }
      />
      <div className="fade-b min-h-0 flex-1 overflow-y-auto">
        <Collapsible
          title={uiT("归属 ")}
          icon={<Owner size={14} strokeWidth={1.9} />}
          meta={kbFilter.owner.length ? uiT("{v1} 项", { v1: kbFilter.owner.length }) : uiT('三级')}
          defaultOpen
          storeKey={collapseKey('knowledge', 'owner')}
          dense
        >
          {owner.map((lv, i) =>
            lv ? (
              <FilterRow
                key={lv}
                label={uiT(lv)}
                indent={i}
                count={countFor('owner', lv)}
                active={kbFilter.owner.includes(lv)}
                onClick={() => setKbFilter({ owner: toggle(kbFilter.owner, lv) })}
              />
            ) : null,
          )}
        </Collapsible>

        <Collapsible
          title={uiT("来源")}
          icon={<Origin size={14} strokeWidth={1.9} />}
          meta={kbFilter.origin.length ? uiT("{v1} 项", { v1: kbFilter.origin.length }) : uiT('两类')}
          defaultOpen={false}
          storeKey={collapseKey('knowledge', 'origin')}
          dense
        >
          {ORIGINS.map((o) => (
            <FilterRow
              key={o}
              label={uiT(KNOWLEDGE_ORIGIN_LABEL[o])}
              count={countFor('origin', o)}
              active={kbFilter.origin.includes(o)}
              onClick={() => setKbFilter({ origin: toggle(kbFilter.origin, o) })}
            />
          ))}
        </Collapsible>

        <Collapsible
          title={uiT("用途 ")}
          icon={<Usage size={14} strokeWidth={1.9} />}
          meta={kbFilter.usage.length ? uiT("{v1} 项", { v1: kbFilter.usage.length }) : uiT('三类')}
          defaultOpen={false}
          storeKey={collapseKey('knowledge', 'usage')}
          dense
        >
          {USAGES.map((u) => (
            <FilterRow
              key={u}
              label={uiT(KNOWLEDGE_USAGE_LABEL[u])}
              count={countFor('usage', u)}
              active={kbFilter.usage.includes(u)}
              onClick={() => setKbFilter({ usage: toggle(kbFilter.usage, u) })}
            />
          ))}
        </Collapsible>
      </div>
    </Panel>
  )
}

/* -------------------------------------------------------------------- 中栏 */

const USAGE_TONE: Record<KnowledgeUsage, 'ink' | 'soft' | 'neutral'> = {
  spec: 'neutral',
  requirement: 'ink',
  process: 'soft',
}

function EntryRow({
  entry,
  active,
  isNew,
  onClick,
}: {
  entry: KnowledgeEntry
  active: boolean
  /** 新导入、还没看过：行末挂一枚绿色「新增」角标 */
  isNew: boolean
  onClick: () => void
}) {
  const uiT = useT()

  const Doc = KNOWLEDGE_ICON.doc
  const Exp = KNOWLEDGE_ICON.experience
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex h-[40px] w-full items-center gap-3 border-b border-line-soft px-4 text-left transition-colors',
        active ? 'bg-p50' : 'hover:bg-p50/60',
      )}
    >
      <Badge tone={USAGE_TONE[entry.usage]} className="w-[76px] justify-center">
        {uiT(KNOWLEDGE_USAGE_LABEL[entry.usage])}
      </Badge>
      {entry.origin === 'doc' ? (
        <Doc size={14} strokeWidth={1.8} className="shrink-0 text-p600" />
      ) : (
        <Exp size={14} strokeWidth={1.8} className="shrink-0 text-p500" />
      )}
      {/* ⚠️ 显示处包 uiT（词条在 catalog.ts / autoCatalog.ts）；但**不要**改 entry.title 本身——
          后端按 title 反查 doc_id（见 SourceFileField 注释），改了会让正文/下载 404。 */}
      <span
        className="min-w-0 flex-1 truncate text-[13px] text-t1"
        title={uiT(entry.title)}
      >
        {uiT(entry.title)}
      </span>
      {/* 新增角标：看过就消失（见 markKbSeen）。绿色与「已接入」同色系，
          但形状用圆角胶囊，不会与三轴徽标混淆。 */}
      {isNew ? (
        <span className="shrink-0 rounded-full border border-p300 bg-p50 px-1.5 text-[10.5px] leading-[16px] text-p700">
          {uiT("新增")}</span>
      ) : null}
      <span className="shrink-0 truncate text-[12px] text-t3" style={{ maxWidth: 140 }}>
        {uiT(entry.docType ?? entry.evidenceLevel ?? '')}
      </span>
      <span className="num shrink-0 text-[12px] text-t3">{entry.id}</span>
    </button>
  )
}

/* -------------------------------------------------------------------- 右栏 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  if (children == null || children === '') return null
  return (
    <div className="border-b border-line-soft py-2">
      <div className="pb-1 text-[12px] text-t3">{label}</div>
      {/* leading-5（20px）在 12.5px 字号上对长路径这类连续字符偏紧，抬到 leading-[1.65] */}
      <div className="text-[12.5px] leading-[1.65] break-words text-t2">{children}</div>
    </div>
  )
}

/**
 * 「源文件」字段：左侧下载图标 + 可点击文本，点击弹窗看抽取稿内容。
 *
 * ⚠️ 诚实边界：客户原始 PDF 不在本机（`[源]` 是脱敏占位前缀），这里读/下的都是
 * **系统抽取稿 Markdown**，不是原件。所以在弹窗与悬浮提示里都写明这一点。
 * 查不到抽取稿时（后端 404）两个入口置灰并说明原因，不弹空窗、不假装有内容。
 */
function SourceFileField({ entry }: { entry: KnowledgeEntry }) {
  const uiT = useT()

  const label = entry.path ?? entry.url ?? ''
  const ownerL3 = entry.owner[2]
  const setNotice = useAppStore((s) => s.setNotice)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [content, setContent] = useState<DocContent | null>(null)
  /** 合成图文稿（正文 + 插图）。有就用它渲染，没有则回退纯 Markdown。 */
  const [combined, setCombined] = useState<CombinedDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 首次尝试过读取后，若 404（无抽取稿）就把入口置灰，不再反复请求
  const [unavailable, setUnavailable] = useState<string | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      // ⚠️ 后端按 **title** 反查 doc_id（比对数据侧 index.json 的 title），
      // 不是按 path——所以这里必须传 entry.title，不能传 label（文件路径，
      // 形如 `[源] 调试经验文档/xxx.pdf`，与 title 不等，传它会一律 404）。
      // 先取合成图文稿（最好看）；没有（404）再取纯 Markdown 兜底。
      const cb = await fetchCombined(entry.title, ownerL3)
      if (cb) {
        setCombined(cb)
        rememberDocId(label, cb.docId)
        return cb
      }
      const c = await fetchDocContent(entry.title, ownerL3)
      setContent(c)
      rememberDocId(label, c.docId)
      return c
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (e instanceof DocContentError && e.status === 404) setUnavailable(msg)
      setError(msg)
      return null
    } finally {
      setBusy(false)
    }
  }, [entry.title, label, ownerL3])

  // 切换到另一条目时清空上一条的缓存内容——否则弹窗会显示"上一条"的正文/合成稿
  // （组件被复用，state 不会因 entry 变而自动重置）。
  useEffect(() => {
    setContent(null)
    setCombined(null)
    setError(null)
    setUnavailable(null)
    setOpen(false)
  }, [entry.id])

  const onOpen = async () => {
    if (unavailable) return
    setOpen(true)
    // ⚠️ 只要**没有合成稿**就尝试取一次（合成稿是首选渲染件）。
    // 不能写成「有 content 就不取」——那会让先取到 Markdown 缓存的条目永远拿不到合成稿。
    if (!combined) await load()
  }

  const onDownload = async () => {
    if (unavailable || busy) return
    try {
      const c = content ?? (await load())
      if (!c) return
      const a = document.createElement('a')
      a.href = extractDownloadUrl(c.docId)
      a.download = ''
      document.body.appendChild(a)
      a.click()
      a.remove()
      setNotice('已开始下载抽取稿（Markdown，非客户原件 PDF）')
    } catch (e) {
      setNotice(`下载失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  if (!label) return null
  const disabled = !!unavailable || busy
  const tip = unavailable
    ? `${unavailable}（原件在客户侧，未随包交付）`
    : '点击查看抽取稿内容；左侧图标下载（Markdown 抽取稿，非客户原件 PDF）'

  return (
    <>
      <div className="border-b border-line-soft py-2">
        <div className="pb-1 text-[12px] text-t3">{uiT("源文件")}</div>
        <div className="flex items-start gap-1.5">
          <Tooltip content={tip}>
            <button
              type="button"
              disabled={disabled}
              aria-label={uiT("下载源文件抽取稿")}
              onClick={onDownload}
              className={cn(
                'mt-[1px] flex h-5 w-5 shrink-0 items-center justify-center rounded-tpx transition-colors',
                disabled ? 'cursor-not-allowed text-t3 opacity-50' : 'text-t3 hover:bg-p50 hover:text-p700',
              )}
            >
              <Download size={13} strokeWidth={1.8} />
            </button>
          </Tooltip>
          <Tooltip className="min-w-0" content={tip}>
            <button
              type="button"
              disabled={disabled}
              onClick={onOpen}
              className={cn(
                'min-w-0 text-left text-[12.5px] leading-[1.65] break-words transition-colors',
                disabled
                  ? 'cursor-not-allowed text-t3 opacity-60'
                  : 'cursor-pointer text-t2 hover:text-p700 hover:underline',
              )}
            >
              {label}
            </button>
          </Tooltip>
        </div>
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={uiT(entry.title)}
        meta={combined ? uiT('系统合成图文稿') : uiT('系统抽取稿 · Markdown')}
        width={920}
      >
        {busy ? (
          <div className="py-10 text-center text-[12.5px] text-t3">{uiT("正在读取内容…")}</div>
        ) : error ? (
          <div className="py-10 text-center text-[12.5px] text-alert">
            {uiT(error)}
            <div className="pt-2">
              <Button size="sm" onClick={() => void load()}>
                {uiT("重试")}</Button>
            </div>
          </div>
        ) : combined ? (
          // 合成图文稿：正文 + 按序插图。用 iframe srcDoc 隔离样式（合成稿自带 CSS），
          // 图片 src 指向后端 figure 端点（同源，srcDoc 下可解析）。
          <iframe
            title={uiT(entry.title)}
            srcDoc={combined.html}
            sandbox="allow-same-origin"
            className="h-[72vh] w-full rounded-tpx border border-line-soft bg-white"
          />
        ) : content ? (
          <div className="max-h-[70vh] overflow-y-auto">
            <div className="mb-3 rounded-tpx border border-line-soft bg-p50 px-3 py-2 text-[12px] text-t2">
              {uiT("⚠️ 本内容为**系统抽取稿**（docling 从原件抽出的 Markdown），不是客户原件 PDF。 原件在客户侧、未随包交付，故只能查看/下载抽取稿。")}</div>
            <Markdown text={content.text} />
          </div>
        ) : null}
      </Modal>
    </>
  )
}

/**
 * 右栏条目详情。
 *
 * 底部留白挂在末个字段上（`[&>div:last-child]:pb-7`），不挂在滚动容器上。
 * 原先写的是容器自己 `pb-4`：`.fade-b::after` 是 `position: sticky; bottom: 0`，
 * 它的定位基准是滚动容器的内边距盒，容器只要有 padding-bottom，渐隐带就被顶到
 * 离底 16px 处，最后那 16px 正文既不渐隐、又被面板的 overflow-hidden 硬切，
 * 于是「备注」这种多行长文的末行与卡片下边界叠成一团。把留白改挂到末个字段上，
 * 渐隐带回到视口真正的下沿；末个字段的下框线一并去掉，免得与卡底连成双线。
 */
function DetailColumn({ entry }: { entry: KnowledgeEntry | null }) {
  const uiT = useT()

  const Usage = KNOWLEDGE_ICON.usage
  return (
    /* 窄屏自适应（2026-10-15）：加 knowledge-detail-panel 钩子 ——
       宽度是内联 clamp（下限 300），@media 覆盖不动，由 index.css 用
       !important 在 ≤1024px 下调低（与上方 html[lang='en'] 同手法）。 */
    <Panel style={{ width: 'clamp(300px, 21vw, 400px)' }} className="knowledge-detail-panel shrink-0">
      <PanelHeader
        icon={<Usage size={17} strokeWidth={1.9} />}
        title={uiT("条目详情")}
        right={entry ? <Badge tone="neutral" mono>{entry.id}</Badge> : null}
      />
      {!entry ? (
        <div className="min-h-0 flex-1">
          <EmptyState
            icon={<Library size={24} strokeWidth={1.5} />}
            title={uiT("选一条看详情")}
            hint={uiT("中栏点任意一行，这里出它的三轴取值、归类依据与源文件全名。")}
          />
        </div>
      ) : (
        <div className="fade-b min-h-0 flex-1 overflow-y-auto px-4 [&>div:last-child]:border-b-0 [&>div:last-child]:pb-7">
          <h3 className="pt-3 pb-2 text-[14px] leading-6 font-semibold text-t1">
            {uiT(entry.title)}
          </h3>
          <div className="flex flex-wrap gap-1.5 pb-2">
            <Badge tone={USAGE_TONE[entry.usage]}>{uiT(KNOWLEDGE_USAGE_LABEL[entry.usage])}</Badge>
            <Badge tone="neutral">{uiT(KNOWLEDGE_ORIGIN_LABEL[entry.origin])}</Badge>
            <Badge tone="neutral">{uiT(entry.owner[2])}</Badge>
            {entry.needsReview ? <Badge tone="warn">{uiT("待人工复核")}</Badge> : null}
          </div>
          {/* 以下「值」全部包 uiT：它们来自库表，是中文数据文本（英文界面下需要机翻兜底）。
              未收录的文本 uiT 会原样返回，等于保持现状，不会变差。 */}
          <Field label={uiT("归类依据")}>{uiT(entry.usageClass)}</Field>
          <Field label={uiT("材料类型")}>{uiT(entry.docType)}</Field>
          <Field label={uiT("证据级")}>{uiT(entry.evidenceLevel)}</Field>
          {entry.case ? (
            <>
              <Field label={uiT("现象")}>{uiT(entry.case.symptom)}</Field>
              <Field label={uiT("成因")}>{uiT(entry.case.cause)}</Field>
              <Field label={uiT("动作")}>{uiT(entry.case.action)}</Field>
              <Field label={uiT("结果")}>{uiT(entry.case.result)}</Field>
            </>
          ) : null}
          <Field label={uiT("转化状态")}>
            {entry.conversion
              // v1 是数据文本，需单独过一遍 uiT（uiT 的 {vN} 参数只做替换、不再翻译参数值）
              ? uiT("{v1}{v2}{v3}", { v1: uiT(entry.conversion), v2: entry.chunks ? ` · ${entry.chunks} 切片` : '', v3: entry.pages ? ` · ${entry.pages} 页` : '' })
              : ''}
          </Field>
          <Field label={uiT("体量")}>{entry.sizeBytes ? sizeText(entry.sizeBytes) : ''}</Field>
          <SourceFileField entry={entry} />
          <Field label={uiT("待核实")}>{uiT(entry.status)}</Field>
          <Field label={uiT("备注")}>{uiT(entry.note)}</Field>
        </div>
      )}
    </Panel>
  )
}

/* ------------------------------------------------------------------ 底栏助手 */

const GREETING =
  '知识库模块。左栏三轴筛选、中栏条目、右栏详情；条目的用途轴取自场景包里每条新补的 usage 字段。'
rememberScriptMessages([GREETING])

/* 知识库助手高度（像素）。为什么用像素不用比例：
   流程页是「上内容 / 下助手」两行按比例分，比例语义成立；知识库页助手是 flex 纵列
   最后一个子项、上面是中栏内容区，用户诉求是「能拉到看见对话」，像素高度更直观。
   持久化独立键，不与流程页的比例键互相干扰。 */
const KB_ASSISTANT_MIN = 300

function readKbAssistH(fallback: number): number {
  try {
    const raw = localStorage.getItem('omnitest.kb.assistantHeight')
    const n = raw ? Number(raw) : NaN
    return Number.isFinite(n) && n >= KB_ASSISTANT_MIN ? n : fallback
  } catch {
    return fallback
  }
}

function maxKbAssistH(): number {
  // 上限：不超过半屏、且给中栏留出空间（不小于 300）
  if (typeof window === 'undefined') return 560
  return Math.max(KB_ASSISTANT_MIN, Math.min(720, Math.round(window.innerHeight * 0.62)))
}

function AssistantBar({ total }: { total: number }) {
  const uiT = useT()

  const sceneId = useAppStore((s) => s.sceneId)
  const noteChatRound = useAppStore((s) => s.noteChatRound)
  const [open, setOpen] = useState(true)
  // 知识库模块页不挂 FlowCopilot，预置动作按钮条自己接：
  // 那四枚的定义已由 copilot 包整份登记好（scope = 'knowledge'），这里只负责渲染与代发。
  const [api, setApi] = useState<AgentChatApi | null>(null)
  const [busy, setBusy] = useState(false)
  const send = useCallback((text: string) => api?.send(text, uiMessage(text)), [api])
  const adapter = useKnowledgeAdapter()

  // 高度：可拖（像素），初值 320、范围 [300, maxKbAssistH()]
  const [h, setH] = useState(() => readKbAssistH(320))
  const dragging = useRef(false)
  const startY = useRef(0)
  const startH = useRef(0)
  // onUp 里要拿去写入的"当前值"：用 ref 跟随，避免闭包拿到旧 h
  const hRef = useRef(h)
  hRef.current = h

  // 与流程页同款：拖拽期间在 window 上监听 pointer 事件（指针易滑出细条，绑自身会丢事件）
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return
      // 助手在下方，向下拖（clientY 增大）→ 高度减小
      const next = startH.current - (e.clientY - startY.current)
      setH(Math.max(KB_ASSISTANT_MIN, Math.min(maxKbAssistH(), next)))
    }
    const onUp = () => {
      if (!dragging.current) return
      dragging.current = false
      document.body.style.removeProperty('cursor')
      document.body.style.removeProperty('user-select')
      try {
        localStorage.setItem('omnitest.kb.assistantHeight', String(Math.round(hRef.current)))
      } catch {
        /* 存不下就只在本次会话生效 */
      }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

  const startDrag = (e: React.PointerEvent) => {
    dragging.current = true
    startY.current = e.clientY
    startH.current = h
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
  }
  const resetH = () => {
    setH(320)
    try {
      localStorage.setItem('omnitest.kb.assistantHeight', '320')
    } catch {
      /* 忽略 */
    }
  }

  // 忙态下降沿记一轮对话（与流程页 noteChatRound 同款），供上下文包的 transcript_summary 用
  const wasBusy = useRef(false)
  const handleBusy = useCallback(
    (b: boolean) => {
      setBusy(b)
      if (wasBusy.current && !b) noteChatRound()
      wasBusy.current = b
    },
    [noteChatRound],
  )

  return (
    <Panel className="shrink-0" style={{ height: open ? h : 44 }}>
      {open ? (
        // 拖拽条：只在展开态渲染（窄条上不该抓）。双击复位；聚焦后上下键微调。
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label={uiT("拖动调整助手高度（双击复位）")}
          aria-valuenow={Math.round(h)}
          aria-valuemin={KB_ASSISTANT_MIN}
          aria-valuemax={maxKbAssistH()}
          tabIndex={0}
          title={uiT("拖动调整助手高度（双击复位）")}
          onPointerDown={startDrag}
          onDoubleClick={resetH}
          onKeyDown={(e) => {
            const step = e.shiftKey ? 60 : 20
            if (e.key === 'ArrowUp') {
              e.preventDefault()
              setH((v) => Math.min(maxKbAssistH(), v + step))
            } else if (e.key === 'ArrowDown') {
              e.preventDefault()
              setH((v) => Math.max(KB_ASSISTANT_MIN, v - step))
            }
          }}
          className="group flex h-[8px] shrink-0 cursor-row-resize items-center justify-center focus-visible:outline-none"
        >
          <span className="h-[3px] w-12 rounded-full bg-line transition-all group-hover:h-[4px] group-hover:bg-ink group-focus-visible:bg-ink" />
        </div>
      ) : null}
      <PanelHeader
        icon={<MessageSquare size={16} strokeWidth={1.9} />}
        title={uiT("助手")}
        meta={uiT("本产品 {v1} 条知识", { v1: total })}
        right={
          <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
            {open ? uiT('收起') : uiT('展开')}
          </Button>
        }
      />
      {open ? (
        <div className="min-h-0 flex-1">
          <AgentChat
            adapter={adapter}
            assistantName={uiT("助手")}
            operator="张工"
            defaultPermission="readonly"
            initialItems={[
              { kind: 'message', id: 'kb-hello', role: 'assistant', text: GREETING, uiText: uiMessage(GREETING) },
            ]}
            // 会话标识与流程页同构（shell-<场景>-<scope>），后端据此维护上下文，避免与流程页串会话
            sessionId={`shell-${sceneId}-knowledge`}
            // 会话持久化键同源：知识库助手收起 / 切页 / 刷新后对话都还在。
            // ⚠️ 下边的 initialItems 只是「从没聊过」时的问候语种子——有落盘历史时
            // AgentChat 会用历史顶掉它，不会出现「历史 + 问候语」叠在一张对话里。
            persistKey={`shell-${sceneId}-knowledge`}
            onReady={setApi}
            onBusyChange={handleBusy}
            actionSlot={<ActionDock scope="knowledge" send={send} busy={busy} />}
          />
        </div>
      ) : null}
    </Panel>
  )
}

/* -------------------------------------------------------------------- 整页 */

export function KnowledgeModule() {
  const uiT = useT()

  const { entries, loading, error } = useKnowledge()
  const kbFilter = useAppStore((s) => s.kbFilter)
  const sceneId = useAppStore((s) => s.sceneId)
  const setNotice = useAppStore((s) => s.setNotice)
  const nav = useNavigate()
  /** 导出中：打包含上百张图，给个忙态防连点（连点会并发打大包）。 */
  const [exporting, setExporting] = useState(false)
  /** 页码持久化（刷新后停在原页；筛选变化时仍回第一页，见下方 lastKey 逻辑）。
      支持函数式更新（分页按钮用 `setPage(p => p ± 1)`，与 useState 同签名）。 */
  const [page, setPageState] = useState(readPage)
  const setPage = (p: number | ((prev: number) => number)) => {
    setPageState((prev) => {
      const next = typeof p === 'function' ? p(prev) : p
      writePage(next)
      return next
    })
  }
  // 选中态上提到 store：副驾读不到组件内的局部 useState，上提之后
  // 上下文包的 zoneB.selected_document 才有真值，依赖它的按钮才可能从恒灰转可用
  // （主文档 3.2.2 的前置改造）。
  const picked = useAppStore((s) => s.kbSelectedId)
  const setPicked = useAppStore((s) => s.setKbSelectedId)
  const kbSeen = useAppStore((s) => s.kbSeen)
  const markKbSeen = useAppStore((s) => s.markKbSeen)
  const markKbSeenBatch = useAppStore((s) => s.markKbSeenBatch)
  const setKbFilter = useAppStore((s) => s.setKbFilter)

  // 「新增」= 从没被人点开看过（kbSeen 持久在本地，刷新不回弹）。
  const newIds = useMemo(
    () => new Set(entries.filter((e) => !kbSeen.includes(e.id)).map((e) => e.id)),
    [entries, kbSeen],
  )

  /** 「只看新增」开关。点顶条那枚「N 条新增」打开；三轴任一被改就自动关掉，
      避免出现「筛选写着全部、其实只显示新增」这种看不懂的状态。
      持久化：刷新后保持上次的开关态（用户要求「知识库页面也要持久化」）。 */
  const [scopeNew, setScopeNewState] = useState(readScopeNew)
  const setScopeNew = (on: boolean) => {
    writeScopeNew(on)
    setScopeNewState(on)
  }
  /** 本页自己开的开关（点顶条「上传」用） */
  const [uploadLocal, setUploadLocal] = useState(false)

  /**
   * 面板是否打开 = 本页开关 **或** 左栏跨页信号。
   *
   * ⚠️ 不要用 effect 把跨页信号搬进 state（首版那么写过，两处都出问题：
   * 在 render 期写 store 被判「Cannot access refs / set state during render」，
   * 改成 effect 又被判 set-state-in-effect，而且效果还依赖 effect 的执行时机）。
   * 直接**派生**最稳：信号为真就是开着，关面板时顺手把信号清掉即可。
   */
  const uploadReq = useAppStore((s) => s.kbUploadRequest)
  const requestKbUpload = useAppStore((s) => s.requestKbUpload)
  const uploadOpen = uploadLocal || uploadReq
  const closeUpload = () => {
    setUploadLocal(false)
    // 顺手清掉跨页信号，否则离开再回来又弹一次
    if (uploadReq) requestKbUpload(false)
  }

  const shown = useMemo(() => {
    const base = filterKnowledge(entries, kbFilter)
    return scopeNew ? base.filter((e) => newIds.has(e.id)) : base
  }, [entries, kbFilter, scopeNew, newIds])
  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE))

  // 三轴一变就回第一页。在 render 期直接改本组件自己的 state，
  // 不用 effect——用 effect 会多一轮渲染，也过不了 oxlint 的 set-state-in-effect。
  //
  // ⚠️ 首帧不重置：page 已持久化（readPage），但刷新时 `entries` 是**异步**加载的
  //    （先 [] 再填满），key 必然从空态变到实态；若首帧就按「key 变了」重置，
  //    持久化的页码会被立刻打回 0，等于没持久化。所以首帧只记 key、不重置。
  const key = `${entries.length}|${kbFilter.usage}|${kbFilter.origin}|${kbFilter.owner}|${scopeNew}`
  const [lastKey, setLastKey] = useState<string | null>(null)
  if (lastKey === null) {
    setLastKey(key)
  } else if (lastKey !== key) {
    setLastKey(key)
    setPage(0)
  }

  const rows = shown.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)
  // 没点过就默认选中当前页第一条，右栏不空着进场
  const entry = shown.find((e) => e.id === picked) ?? rows[0] ?? null
  const owner = entries[0]?.owner ?? ['', '', '']
  const newCount = newIds.size

  /**
   * 新导入的条目**自动进入分类筛选**：把人直接带到它所在的用途轴。
   *
   * 只在「有新增且当前没有任何筛选」时自动跳一次——否则人在自由浏览时
   * 一切轴就被程序改掉，比不跳更烦。跳的是新增条目里最常见的那一个用途轴，
   * 并同时按归属收窄到本产品（与左栏三轴口径一致）。
   */
  const autoFocusRef = useRef(false)
  useEffect(() => {
    if (autoFocusRef.current) return
    if (!newCount || !entries.length) return
    const hasFilter = kbFilter.usage.length || kbFilter.origin.length
    if (hasFilter) return
    autoFocusRef.current = true
    // 取第一条新增条目的用途与归属：它是这一批导入里最有代表性的那一类
    const firstNew = entries.find((e) => newIds.has(e.id))
    if (!firstNew) return
    setKbFilter({ usage: [firstNew.usage] })
  }, [newCount, entries, kbFilter, newIds, setKbFilter])

  /** 点开一条 = 看过了，「新增」角标随之消失（并要求持久化） */
  const openEntry = (id: string) => {
    setPicked(id)
    markKbSeen(id)
  }

  // 逐项过 uiT：list 里是归属/来源/用途的**数据取值**，all 是面包屑文本，
  // 两者在英文界面下都需译出（整串拼接后命中不了词条，必须逐项译再拼）
  const axisText = (list: string[], all: string) => (list.length ? list.map((x) => uiT(x)).join(' / ') : uiT(all))

  const Usage = KNOWLEDGE_ICON.usage
  const Upload = KNOWLEDGE_ICON.upload

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col" style={{ gap: GAP }}>
      {/* 顶条：归属面包屑 + 三枚操作按钮。红线六动作一律人点，这里只是入口。 */}
      {/* 窄屏自适应（2026-10-15）：加 kb-topbar 钩子 —— 原来是 h-[52px] **固定高**，
          投屏/小窗口下顶条内容（面包屑 + 返回 + 新增 + 三枚按钮）换行就会被裁，
          由 index.css 在窄屏改为 min-height + flex-wrap。 */}
      <Panel
        className="kb-topbar h-[52px] shrink-0 items-center gap-3 px-4"
        style={{ flexDirection: 'row' }}
      >
        <span className="flex h-[30px] w-[30px] items-center justify-center rounded-tpx bg-p50 text-p700">
          <Library size={17} strokeWidth={1.9} />
        </span>
        <span className="text-[16px] font-semibold tracking-tight text-t1">{uiT("知识库")}</span>
        <span className="h-[22px] w-px bg-line" />
        <span className="truncate text-[13px] text-t2">
          {owner.filter(Boolean).map((x) => uiT(x)).join(' › ')}
        </span>
        <span className="num text-[12px] text-t3">{entries.length} {uiT(" 条")}</span>
        {/* 「返回」= 回到知识库**首页**（不是跳别的页）：把三轴筛选、只看新增、页码
            一并重置，看到本库全部条目。
            用户口径（2026-09-29）：筛成只剩 8 条时点它，应回到 134 条的原始首页，
            而不是跳去初始化流程页（上一版理解错了，改这里）。
            选中条目不动——右栏详情继续显示当前那条，避免"点返回右栏空了"。 */}
        <button
          type="button"
          onClick={() => {
            setKbFilter({ usage: [], origin: [], owner: [] })
            setScopeNew(false)
            setPage(0)
          }}
          className="flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-[2px] text-[11.5px] text-t2 transition-colors hover:bg-p50 hover:text-p700"
        >
          <ChevronLeft size={11} strokeWidth={2.2} />
          {uiT("返回")}</button>
        {/* 「查看新增」：一眼看到有哪几条是刚导入还没看的，点了就把三轴放开只看新增。
            没有新增时不显示——一个永远点不出东西的按钮比没有更糟。 */}
        {newCount ? (
          <button
            type="button"
            onClick={() => {
              setKbFilter({ usage: [], origin: [], owner: [] })
              setPage(0)
              // 只看新增：把已看过的排除在外，靠一个临时标记实现（见下方 scopeNew）
              setScopeNew(true)
            }}
            className="flex items-center gap-1 rounded-full border border-p300 bg-p50 px-2 py-[2px] text-[11.5px] text-p700 transition-colors hover:bg-p100"
          >
            <span className="num">{newCount}</span>
            {uiT("条新增")}<ChevronRight size={11} strokeWidth={2.2} />
          </button>
        ) : null}
        {/* 取数失败必须说在页面上：不显示的话，人会把「后端没起」当成「这个产品
            没有知识条目」，而静态回退又会让人以为看的是新数据——两头都不能骗。 */}
        {error ? <span className="text-[12px] text-danger">{uiT("取数失败：")}{uiT(error)}</span> : null}
        {loading ? <span className="text-[12px] text-t3">{uiT("取数中…")}</span> : null}
        <div className="ml-auto flex items-center gap-2">
          {/* 「上传」开上传面板（选文件 → 定归属/用途 → 五阶段转化），
              不是跳到别处——这里就是知识库页，没有更"里面"的地方可跳。 */}
          <Button
            size="sm"
            variant="secondary"
            icon={<Upload size={14} strokeWidth={1.9} />}
            onClick={() => setUploadLocal(true)}
          >
            {uiT("上传")}</Button>
          {/* 「重跑流水线」此前是空壳（无 onClick，点了没反应）。现按用户口径
              改为跳转到「阶段3 启动测试」（路由 /run），与流程 2 确认后 nav('/run')
              同一落点；不在此处真跑五阶段重转（那是上传面板里按文档触发的重活）。 */}
          <Button
            size="sm"
            icon={<RefreshCw size={14} strokeWidth={1.9} />}
            onClick={() => nav('/run')}
          >
            {uiT("重跑流水线")}</Button>
          {/* 「导出」此前是空壳（无 onClick，点了没反应）。现在真下载一个 zip：
              整个所属知识库的全量条目清单 + 有产物的文档文件（含插图与合成稿）。

              ⚠️ 范围用 owner（产品三级名）而非页面筛选态：用户口径是「导出整个
              所属知识库」，筛选只是当前视图，不该决定导出内容。
              ⚠️ 下载用原生 <a download> 导航，不用 fetch——要拿的是文件流，
              fetch 还得手动转 blob 且拿不到服务端给的文件名。 */}
          <Button
            size="sm"
            icon={<Download size={14} strokeWidth={1.9} />}
            disabled={exporting || !owner[2]}
            onClick={() => {
              const l3 = owner[2]
              if (!l3) {
                setNotice('导出失败：没取到产品归属，等条目加载完再试')
                return
              }
              setExporting(true)
              setNotice(uiT("正在打包「{v1}」知识库…（含插图，约需几秒）", { v1: l3 }))
              // 先探一次：后端打包失败会返回非 2xx（空 owner / 无条目 / 打包异常），
              // 这时不能让浏览器去下那个错误 JSON 当 zip——如实报错，不假装成功。
              void fetch(kbExportUrl(l3, sceneId), { method: 'GET' })
                .then(async (resp) => {
                  if (!resp.ok) {
                    const msg = await resp
                      .json()
                      .then((b: { message?: string }) => b.message || `HTTP ${resp.status}`)
                      .catch(() => `HTTP ${resp.status}`)
                    setNotice(uiT("导出失败：{v1}", { v1: msg }))
                    return
                  }
                  const a = document.createElement('a')
                  a.href = kbExportUrl(l3, sceneId)
                  a.download = ''
                  document.body.appendChild(a)
                  a.click()
                  a.remove()
                  setNotice(uiT("已开始下载「{v1}」知识库压缩包（全量 {v2} 条）", { v1: l3, v2: entries.length }))
                })
                .catch((e: unknown) => {
                  setNotice(uiT("导出失败：{v1}", { v1: e instanceof Error ? e.message : String(e) }))
                })
                .finally(() => setExporting(false))
            }}
          >
            {exporting ? uiT('导出中…') : uiT('导出')}
          </Button>
        </div>
      </Panel>

      <div className="flex min-h-0 flex-1" style={{ gap: GAP }}>
        <FilterColumn entries={entries} />

        {/* 中栏是本页唯一的视觉主体：描边加深、带柔阴影 */}
        <Panel className="min-w-0 flex-1 border border-p200 shadow-tp2">
          <PanelHeader
            icon={<Usage size={17} strokeWidth={1.9} />}
            title={uiT("知识条目")}
            meta={uiT("{v1} 条", { v1: shown.length })}
            right={
              <div className="flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={uiT("上一页")}
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  icon={<ChevronLeft size={14} strokeWidth={1.9} />}
                />
                <span className="num text-[12px] text-t3">
                  {page + 1} / {pages}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={uiT("下一页")}
                  disabled={page + 1 >= pages}
                  onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
                  icon={<ChevronRight size={14} strokeWidth={1.9} />}
                />
              </div>
            }
          />

          {/* 三轴当前取值，一行讲清这一屏是怎么筛出来的 */}
          {/* 窄屏自适应（2026-10-15）：kb-filterbar —— 原 h-[30px] 固定高，
              三轴面包屑在窄屏会折行，折行后会被 30px 卡住裁掉半行字。 */}
          <div className="kb-filterbar flex h-[30px] shrink-0 items-center gap-2 border-b border-line-soft bg-p50/50 px-4 text-[12px] text-t2">
            {/* ⚠️ 第二个参数（面包屑）必须**逐项译完再 join**：
                axisText 里对 all 只做 uiT(整串)，而整串在词典里命中不了
                （词典只有「电机」「散热风扇」这样的单项），会漏翻成中文。 */}
            <span>{uiT("归属")}{' '}{axisText(kbFilter.owner, owner.filter(Boolean).map((x) => uiT(x)).join(' › '))}</span>
            <span className="text-t3">·</span>
            <span>
              {uiT("来源")}{' '}
              {axisText(kbFilter.origin.map((o) => KNOWLEDGE_ORIGIN_LABEL[o]), uiT('全部'))}
            </span>
            <span className="text-t3">·</span>
            <span>
              {uiT("用途")}{' '}{axisText(kbFilter.usage.map((u) => KNOWLEDGE_USAGE_LABEL[u]), uiT('全部'))}
            </span>
            {/* 「只看新增」开着时必须说出来：否则人看到条数变少会以为库出问题了。
                ⚠️ 点「取消」= **整批把这批新增标记为已看过**（不只是退出视图）：
                此前只 setScopeNew(false)，条目仍标「新增」、顶部角标也不消，
                用户实测报「下方取消了但上方 118 条新增还在」。现在一次清干净并持久化。 */}
            {scopeNew ? (
              <button
                type="button"
                onClick={() => {
                  markKbSeenBatch([...newIds])
                  setScopeNew(false)
                }}
                className="ml-1 flex items-center gap-1 rounded-full border border-p300 bg-p50 px-1.5 text-[11px] text-p700 hover:bg-p100"
              >
                {uiT("只看新增 ")}{shown.length} {uiT(" 条 · 点此取消")}</button>
            ) : null}
          </div>

          <div className="fade-b min-h-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex flex-col gap-2 p-4">
                {Array.from({ length: 8 }, (_, i) => (
                  <Skeleton key={i} className="h-[32px]" />
                ))}
              </div>
            ) : rows.length ? (
              rows.map((e) => (
                <EntryRow
                  key={e.id}
                  entry={e}
                  active={e.id === picked}
                  isNew={newIds.has(e.id)}
                  onClick={() => openEntry(e.id)}
                />
              ))
            ) : (
              <EmptyState
                icon={<Library size={24} strokeWidth={1.5} />}
                title={uiT("没有命中的条目")}
                hint={uiT("把左栏的三轴筛选放宽一点再看。")}
              />
            )}
          </div>
        </Panel>

        <DetailColumn entry={entry} />
      </div>

      {/* 上传面板：选文件 → 定归属/用途 → 五阶段进度 */}
      <UploadPanel open={uploadOpen} onClose={closeUpload} />

      <AssistantBar total={entries.length} />
    </div>
  )
}
