import { useT } from '../../i18n'
/* ===========================================================================
   知识库上传面板（主文档 3.1，P3）。

   为什么是「先开面板再选文件」而不是直接弹文件框：
   上传前要定**归属（三级）与用途（三类）**——这两个决定这份资料进哪个库、
   在哪些流程里被调用。直接弹文件框的话，文件落进来却不知道归哪，
   后面要靠人再改一遍条目属性。面板把这一步前置。

   面板里做三件事、按顺序出现：
     ① 选文件（拖入或点选）+ 定归属/用途；
     ② 上传 → 立刻消失为「已上传，开始转化」；
     ③ 五阶段进度条（识别→抽取→切片→结构化→索引），逐节点亮；
        结束按状态说人话：已入库 / 需人工校对 / 转化失败（哪个阶段、为什么）。
   =========================================================================== */
import { useCallback, useRef, useState } from 'react'

import { AlertTriangle, Check, FileText, Loader2, Upload, X } from 'lucide-react'
import { Badge, Button, Drawer } from '../../components/ui'
import { getPack } from '../scene/pack'
import { OwnerPicker, type OwnerTriple } from './OwnerPicker'
import { UsagePicker, type UsageChoice } from './UsagePicker'
import {
  KB_STAGES,
  STATUS_LABEL,
  STAGE_LABEL,
  pollUntilSettled,
  runPipeline,
  uploadDocument,
  type KbDocStage,
  type KbDocument,
} from './uploadApi'

/** 人类可读的大小 */
function sizeText(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function StageBar({ stages }: { stages: KbDocStage[] }) {
  const uiT = useT()

  const done = stages.filter((s) => s.done).length
  return (
    <div className="flex items-center gap-1 pt-1">
      {KB_STAGES.map((key, i) => {
        const st = stages.find((s) => s.key === key)
        const ok = !!st?.done
        const active = !ok && i === done
        return (
          <div key={key} className="flex min-w-0 flex-1 items-center gap-1">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1">
                <span
                  className={
                    'grid h-[16px] w-[16px] shrink-0 place-items-center rounded-full text-[10px] ' +
                    (ok
                      ? 'bg-p600 text-white'
                      : active
                        ? 'border border-p400 text-p700'
                        : 'border border-line text-t3')
                  }
                >
                  {ok ? <Check size={10} strokeWidth={2.6} /> : i + 1}
                </span>
                <span className={`truncate text-[11px] ${ok ? 'text-p700' : 'text-t3'}`}>
                  {uiT(STAGE_LABEL[key])}
                </span>
              </div>
              <div
                className={`mt-[3px] h-[3px] rounded-full ${ok ? 'bg-p500' : active ? 'bg-p200' : 'bg-line'}`}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function UploadPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const uiT = useT()

  const pack = getPack()
  const [file, setFile] = useState<File | null>(null)
  // 用途 = 三轴之一 + 可空的自定义标签（见 UsagePicker 的契约说明）
  const [usage, setUsage] = useState<UsageChoice>({ usage: 'process', customLabel: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [doc, setDoc] = useState<KbDocument | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // 当前产品的归属三级（取自场景包，与左栏/知识库三轴同一份来源）——
  // 它是**缺省值**，不是固定值：人可以在归属选择器里改或新建。
  const owner = [
    pack?.scene?.taxonomy?.level1_scene?.name ?? '',
    pack?.scene?.taxonomy?.level2_category?.name ?? '',
    pack?.scene?.taxonomy?.level3_product_type?.name ?? '',
  ]
  /**
   * 归属选择：**人只要手动选过就以人选的为准**，没选过才跟随当前产品。
   *
   * ⚠️ 不要用 ref 在 render 期比对（首版就是这么写的，被 oxlint 判为
   * 「Cannot access/update refs during render」——React 编译器会丢弃这类副作用，
   * 表现是「换产品后归属不跟着变」）。改用「存 null 表示未手动选过」：
   * 未选过 → 用当前产品；选过 → 一直用它，直到人再改。
   * 副作用由 `setOwnerSel(null)` 在关闭面板/重传时显式发生，不在 render 里做。
   */
  const [ownerPicked, setOwnerPicked] = useState<OwnerTriple | null>(null)
  const ownerSel: OwnerTriple = ownerPicked ?? { l1: owner[0], l2: owner[1], l3: owner[2] }
  const setOwnerSel = (v: OwnerTriple) => setOwnerPicked(v)

  const reset = useCallback(() => {
    setFile(null)
    setError(null)
    setDoc(null)
    setBusy(false)
    // 「再传一份」回到跟随当前产品的缺省归属，而不是沿用上一份的手动选择
    setOwnerPicked(null)
  }, [])

  const close = () => {
    // 转化在后台跑，关面板不中断；下次打开重来即可
    reset()
    onClose()
  }

  async function submit() {
    if (!file) {
      setError('先选一份文件')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const { doc: d } = await uploadDocument({
        file,
        title: file.name.replace(/\.[^.]+$/, ''),
        owner_l1: ownerSel.l1,
        owner_l2: ownerSel.l2,
        owner_l3: ownerSel.l3,
        usage: usage.usage,
        // 自定义标签随正文一起传给后端存下来（不占三轴，只是更细的说法）
        usageLabel: usage.customLabel,
      })
      setDoc(d)
      // 上传完立刻推一次五阶段。失败也留在面板上——**不假装成功**。
      await runPipeline(d.doc_id, { until: 'index' })
      const settled = await pollUntilSettled(d.doc_id, { onTick: setDoc })
      setDoc(settled)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      // 失败时再拉一次详情：要把 failed_stage / fail_reason 显示出来
      if (doc?.doc_id) {
        try {
          const { getDocument } = await import('./uploadApi')
          setDoc(await getDocument(doc.doc_id))
        } catch {
          /* 详情都取不到就只留上面那条 error */
        }
      }
    } finally {
      setBusy(false)
    }
  }

  const settled = doc && ['indexed', 'needs_review', 'failed'].includes(doc.status)

  return (
    <Drawer
      open={open}
      onClose={close}
      title={uiT("上传资料到知识库")}
      // 面包屑显示**即将使用的归属**（不是当前产品）——人改了归属要立刻看到改到哪了
      meta={[ownerSel.l1, ownerSel.l2, ownerSel.l3].filter(Boolean).join(' › ')}
      width={480}
    >
      <div className="flex flex-col gap-3 px-1">
        {/* ① 选文件 */}
        {!doc ? (
          <>
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                const f = e.dataTransfer.files?.[0]
                if (f) setFile(f)
              }}
              onClick={() => fileRef.current?.click()}
              className={
                'flex cursor-pointer flex-col items-center gap-1.5 rounded-tps border border-dashed px-4 py-6 transition-colors ' +
                (dragOver ? 'border-p400 bg-p50' : 'border-line hover:border-p300 hover:bg-p50/60')
              }
            >
              <Upload size={20} strokeWidth={1.8} className="text-p600" />
              <span className="text-[12.5px] text-t2">
                {file ? file.name : uiT('拖一份文件到这里，或点击选择')}
              </span>
              <span className="text-[11px] text-t3">
                {uiT("支持 PDF / DOCX / DOC / MD / TXT / 源码；单份不超过 100 MB")}</span>
              {file ? (
                <span className="num text-[11px] text-t3">{sizeText(file.size)}</span>
              ) : null}
            </div>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.doc,.md,.txt,.h,.c"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />

            {/* 用途：三轴选一，另可新建自定义标签（见 UsagePicker 的契约说明） */}
            <UsagePicker value={usage} onChange={setUsage} />
            {/* 归属：三级可选已有，也能**新建**。
                此前是只读的「取自当前产品」——资料不属于任何已登记产品时，
                人就只能放弃上传或硬挂到不相关的产品下（用户提出的问题）。 */}
            <OwnerPicker
              value={ownerSel}
              onChange={setOwnerSel}
              defaultOwner={{
                l1: owner[0],
                l2: owner[1],
                l3: owner[2],
              }}
            />

            {error ? (
              <p className="flex items-start gap-1.5 rounded-tps border border-alert/40 bg-alert-wash px-2.5 py-2 text-[12px] leading-5 text-alert">
                <AlertTriangle size={13} strokeWidth={2} className="mt-[3px] shrink-0" />
                {uiT(error)}
              </p>
            ) : null}

            <div className="flex items-center gap-2 pt-1">
              <Button
                size="sm"
                disabled={!file || busy}
                icon={busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
                onClick={() => void submit()}
              >
                {busy ? uiT('上传并转化…') : uiT('上传并转化')}
              </Button>
              <Button size="sm" variant="secondary" onClick={close}>
                {uiT("取消")}</Button>
            </div>
          </>
        ) : (
          /* ② ③ 已上传：显示五阶段进度与结局 */
          <>
            <div className="flex items-center gap-2">
              <FileText size={15} strokeWidth={1.8} className="shrink-0 text-p600" />
              <span className="min-w-0 flex-1 truncate text-[13px] text-t1">{doc.title}</span>
              <Badge
                tone={
                  doc.status === 'indexed'
                    ? 'ink'
                    : doc.status === 'failed'
                      ? 'alert'
                      : 'warn'
                }
              >
                {STATUS_LABEL[doc.status] ?? doc.status}
              </Badge>
            </div>
            <div className="num flex items-center gap-2 text-[11px] text-t3">
              <span>{doc.file_name}</span>
              <span>·</span>
              <span>{sizeText(doc.size_bytes)}</span>
              {doc.confidence !== null ? (
                <>
                  <span>·</span>
                  <span>{uiT("置信度 ")}{doc.confidence}</span>
                </>
              ) : null}
            </div>

            <StageBar stages={doc.stages ?? []} />

            {doc.status === 'failed' ? (
              <p className="rounded-tps border border-alert/40 bg-alert-wash px-2.5 py-2 text-[12px] leading-5 text-alert">
                {uiT("转化失败于「")}{STAGE_LABEL[doc.failed_stage as keyof typeof STAGE_LABEL] ?? doc.failed_stage}{uiT("」阶段：")}{doc.fail_reason ?? uiT('未给出原因')}
              </p>
            ) : null}
            {doc.status === 'needs_review' ? (
              <p className="rounded-tps border border-warn/40 bg-warn-wash px-2.5 py-2 text-[12px] leading-5 text-t2">
                {uiT("已解析但**结构化置信度低于阈值**，进「需人工校对」——不静默通过。 这类文件的层级信息不全，建议人工核对后再用于判定。")}</p>
            ) : null}
            {doc.status === 'indexed' ? (
              <p className="rounded-tps border border-p200 bg-p50 px-2.5 py-2 text-[12px] leading-5 text-t2">
                {uiT("五个阶段全部完成，")}<span className="num">{doc.entry_count}</span> {uiT(" 条已写入知识库， 助手现在检索得到这份资料。")}</p>
            ) : null}
            {!settled && busy ? (
              <p className="flex items-center gap-1.5 text-[12px] text-t3">
                <Loader2 size={12} className="animate-spin" />
                {uiT("正在转化…")}</p>
            ) : null}

            {error ? (
              <p className="flex items-start gap-1.5 rounded-tps border border-alert/40 bg-alert-wash px-2.5 py-2 text-[12px] leading-5 text-alert">
                <AlertTriangle size={13} strokeWidth={2} className="mt-[3px] shrink-0" />
                {uiT(error)}
              </p>
            ) : null}

            <div className="flex items-center gap-2 pt-1">
              <Button size="sm" variant="secondary" icon={<X size={13} />} onClick={close}>
                {uiT("关闭")}</Button>
              <Button size="sm" onClick={reset}>
                {uiT("再传一份")}</Button>
            </div>
          </>
        )}
      </div>
    </Drawer>
  )
}
