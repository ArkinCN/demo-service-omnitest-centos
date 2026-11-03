/**
 * 前端工具执行器装配（2026-10-10，权限切换修复）。
 *
 * 在 `features/index.tsx` 里以**副作用导入**方式加载（与 knowledge/register 同手法），
 * 把写类工具的真实执行逻辑注册进 agent-chat 的注册表。这样 agent-chat 保持通用、
 * 不认识报告业务；业务侧只负责「确认放行后怎么真正写」。
 *
 * 本批只实现 WriteReportHeader（方案 A 的最小闭环）：
 *   ① 写 store.reportHeader（报告页左栏即时可见）；
 *   ② 落库 report-instance（复用 persistReportInstance；无轮次时如实报失败）。
 * 成功/失败都以 {ok, summary} 如实返回——绝不谎报「已完成」。
 */
import { registerToolExecutor } from '../agent-chat/toolExec'
import { useAppStore } from '../../state/useAppStore'
import { getPack, headerFieldName, type RawHeaderField } from '../scene/pack'
import { persistReportInstance } from '../flow-report/reportApi'
import {
  applyWrite,
  findSimilar,
  listEditableFields,
  readValue,
  resolveField,
  validate,
  type FlowScope,
} from './fieldRegistry'
import { translate, initialLocale } from '../../i18n'
import type { TranslationParams } from '../../i18n/runtime'
import type { ParamValue } from '../../state/useAppStore'

/**
 * 工具摘要文案的翻译助手（2026-10-15）。
 *
 * 这些摘要**既给用户看（工具卡片），也给模型看（tool_result）**：
 * 英文界面下若仍是中文，模型会照抄中文作答（本文件早期版本实测踩到），所以必须跟随界面语言。
 * 本模块是**纯函数模块**（无 hook 作用域），故用 `translate + initialLocale()`，
 * 口径与 `context.ts` 的 `ctxT()` 一致。
 *
 * 取值的 `{vN}` 占位**一律显式传 params**：走「精确查表 + 替换」这条最稳的路径，
 * 不依赖模板正则反匹配（那条路径留给 UI 里拼接好的整串用）。
 */
const t = (source: string, params?: TranslationParams): string =>
  translate(source, initialLocale(), params)

/**
 * 把模型给的字段标识解析成场景包里的表头字段定义。
 * 优先按 key（customer_name）精确匹配，其次按**中/英两个名字**（客戶名稱 / Customer name）
 * 匹配，再退一步做「去掉空白后包含」的模糊匹配。解析不出返回 null（如实报错）。
 *
 * 2026-10-15 起 `f.name` 恒为中文原文、英文名在 `f.name_en`（B 方案），
 * 且英文界面下模型更可能给出英文名，故**两种名字都必须能解析**。
 */
function resolveHeaderField(field: string): RawHeaderField | null {
  const fields = getPack()?.report.header_fields ?? []
  const raw = (field ?? '').trim()
  if (!raw) return null
  const byKey = fields.find((f) => f.key === raw)
  if (byKey) return byKey
  const byName = fields.find((f) => f.name === raw || f.name_en === raw)
  if (byName) return byName
  return (
    fields.find(
      (f) =>
        f.name.includes(raw) ||
        raw.includes(f.name) ||
        (f.name_en != null && (f.name_en.includes(raw) || raw.includes(f.name_en))),
    ) ?? null
  )
}

/**
 * 取当前页面流程 id（AI 只能操作「当前页面」的字段）。
 *
 * 来源是 `ActionDock` 每次构建现场上下文时写入的 `window.__heldEnv`（见
 * `app/Shell.tsx` 把 heldEnv 挂到 window 供验收脚本读）。取不到时退回 `init`
 * —— 这是**保守**选择：init 是本批唯一完整开放的流程，且其字段集合最全，
 * 不会出现「以为是 report 页而放开了控制参数」的越权。
 */
function currentFlow(): FlowScope {
  try {
    // ⚠️ `window.__heldEnv` 在 `Shell.tsx` 里挂的是**函数**（`() => heldEnv`），不是对象！
    // 初版写成 `env?.flow?.id`（把函数当对象点属性）→ 永远拿不到 flow.id
    // → 一直走兜底 'init'，导致报告页也能读写本体属性（跨页隔离失效，实测踩到）。
    // 必须 `env()` 先取出 envelope 再读 flow.id。
    const reader = (window as unknown as { __heldEnv?: () => { flow?: { id?: string } } | null })
      .__heldEnv
    const env = typeof reader === 'function' ? reader() : undefined
    const id = env?.flow?.id
    if (id === 'init' || id === 'req' || id === 'run' || id === 'tune' || id === 'report') return id
  } catch {
    /* 读不到就走兜底 */
  }
  return 'init'
}

/**
 * ReadField（2026-10-14）：读当前页面字段，**无副作用、免确认**。
 *
 * 两种用法：`all=true` 列本页全部可编辑字段；否则按 field 查单项。
 * 找不到时给相似候选（Top3），让模型能自纠重试，而不是直接宣告失败。
 */
registerToolExecutor('ReadField', async (args) => {
  const flow = currentFlow()
  const pack = getPack()

  if (args.all === true || String(args.all ?? '').toLowerCase() === 'true') {
    const list = listEditableFields(flow, pack)
    if (!list.length) {
      return { ok: false, summary: t('本页没有可编辑字段（场景包可能未加载）。') }
    }
    const lines = list.map((f) => {
      const cur = readValue(flow, f)
      // ⚠️ 值分两类：**占位字段的值**是约定标记（「未知」这类，词典里有译法）→ 过 t()；
      // **真实数据值**（客户名称「张工」等）绝不翻译 → 原样。判据用 f.placeholder。
      const shown =
        cur === null || cur === '' ? t('（空）') : f.placeholder ? t(cur) : cur
      const extra: string[] = []
      if (f.unit) extra.push(f.unit)
      if (f.options?.length) extra.push(t('可选 {v1}', { v1: f.options.map((o) => o.label).join('/') }))
      else if (f.min !== null && f.min !== undefined && f.max !== null && f.max !== undefined)
        extra.push(`${f.min}~${f.max}`)
      return `- ${f.path}：${shown}${extra.length ? `（${extra.join('，')}）` : ''}${f.placeholder ? t('［待现场确认］') : ''}`
    })
    return {
      ok: true,
      summary: t('本页共 {v1} 个可编辑字段：\n{v2}', { v1: list.length, v2: lines.join('\n') }),
      data: { count: list.length },
    }
  }

  const ident = String(args.field ?? '').trim()
  if (!ident) {
    return { ok: false, summary: t('请给出要查询的字段（路径 / 名称 / 键），或传 all=true 列出全部。') }
  }
  const field = resolveField(flow, pack, ident)
  if (!field) {
    const cands = findSimilar(flow, pack, ident)
    const hint = cands.length
      ? t('你是不是想查：{v1}？', { v1: cands.map((c) => c.path).join('；') })
      : t('本页字段清单可用 all=true 获取。')
    return { ok: false, summary: t('本页没有找到字段「{v1}」。{v2}', { v1: ident, v2: hint }) }
  }
  const cur = readValue(flow, field)
  const extra: string[] = []
  if (field.unit) extra.push(t('单位 {v1}', { v1: field.unit }))
  if (field.options?.length) extra.push(t('可选 {v1}', { v1: field.options.map((o) => o.label).join('/') }))
  else if (field.min !== null && field.min !== undefined && field.max !== null && field.max !== undefined)
    extra.push(t('范围 {v1}~{v2}', { v1: field.min, v2: field.max }))
  return {
    ok: true,
    summary:
      t('{v1}：当前值 {v2}', {
        v1: field.path,
        // 同 all 分支：仅占位字段的值（约定标记）翻译，真实数据值原样
        v2:
          cur === null || cur === ''
            ? t('（空）')
            : field.placeholder
              ? t(cur)
              : cur,
      }) +
      `${extra.length ? `（${extra.join('，')}）` : ''}；` +
      `${field.editable ? t('可编辑') : t('不可编辑（{v1}）', { v1: field.reason ?? '' })}` +
      `${field.placeholder ? t('；源材料没给这一项，待现场确认') : ''}`,
    data: { key: field.key, value: cur, editable: field.editable },
  }
})

/**
 * WriteField（2026-10-14）：通用字段写入（本体属性 / 控制参数 / 报告表头）。
 *
 * · 一次调用可带多项变更，**逐项独立执行、分条如实回报**（避免单项非法让用户重走确认）；
 * · 报告表头字段写入后沿用既有落库通道（persistReportInstance）；
 *   本体属性 / 控制参数**不自动落库**——流程 1 的落库入口是「确认并锁定」，
 *   AI 绕过会破坏「人确认才落库」的纪律，故在回报里明确说明。
 */
registerToolExecutor('WriteField', async (args) => {
  const flow = currentFlow()
  const pack = getPack()
  const rawChanges = Array.isArray(args.changes) ? args.changes : []
  if (!rawChanges.length) {
    return { ok: false, summary: t('没有给出任何要写入的字段（changes 为空），未执行写入。') }
  }

  // value 保持 ParamValue：数值字段是 number，文本字段是 string（见 fieldRegistry.validate 注释）
  const applied: { key: string; value: ParamValue; name: string }[] = []
  const failed: { field: string; reason: string }[] = []
  let headerWritten = false

  for (const c of rawChanges) {
    const ident = String((c as { field?: unknown }).field ?? '').trim()
    const rawValue = String((c as { value?: unknown }).value ?? '')
    if (!ident) {
      failed.push({ field: t('（未给出字段名）'), reason: t('缺少字段名') })
      continue
    }
    const field = resolveField(flow, pack, ident)
    if (!field) {
      const cands = findSimilar(flow, pack, ident)
      failed.push({
        field: ident,
        reason: cands.length
          ? t('本页没有这个字段，相似的有：{v1}', { v1: cands.map((x) => x.path).join('；') })
          : t('本页没有这个字段（可用 ReadField all=true 查看本页字段）'),
      })
      continue
    }
    const v = validate(flow, pack, field, rawValue)
    if (!v.ok) {
      failed.push({ field: field.path, reason: v.reason })
      continue
    }
    applyWrite(flow, field, v.value)
    if (field.leaf.k === 'field') headerWritten = true
    applied.push({ key: field.key, value: v.value, name: field.path })
  }

  // 报告表头有写入时，沿用既有落库通道落一份（与本页既有行为一致）
  let dbNote = ''
  if (headerWritten) {
    try {
      const st = useAppStore.getState()
      const header = { ...st.reportHeader }
      // 落库 payload 固定用中文规范名（f.name 恒为中文原文，2026-10-15），不随界面语言漂移
      const fields = (pack?.report.header_fields ?? []).map((f) => ({
        key: f.key,
        name: f.name,
        from_flow: f.from_flow,
        value_slot: f.value_slot,
      }))
      const { runId } = await persistReportInstance({
        sceneId: st.sceneId,
        runId: st.runId,
        header,
        fields,
        operator: st.operator,
      })
      dbNote = t('；报告表头已落库到轮次 {v1}', { v1: runId })
    } catch (e) {
      dbNote = t('；报告表头界面已更新但落库未成功：{v1}', {
        v1: e instanceof Error ? e.message : String(e),
      })
    }
  } else if (applied.length) {
    // 本体属性/控制参数：只写界面，不落库（口径：人点「确认并锁定」才落库）
    dbNote = t('；界面已更新，点「确认并锁定」后才落库')
  }

  const okParts = applied.map((a) =>
    `${a.name} → ${a.value === '' ? t('（清空）') : a.value}`,
  )
  const failParts = failed.map((f) => `${f.field}（${f.reason}）`)

  if (!failed.length) {
    return {
      ok: true,
      summary: t('已写入 {v1} 项：{v2}{v3}。', {
        v1: applied.length,
        v2: okParts.join('；'),
        v3: dbNote,
      }),
      data: { applied, failed },
    }
  }
  if (!applied.length) {
    return {
      ok: false,
      summary: t('未执行任何写入。失败 {v1} 项：{v2}。', {
        v1: failed.length,
        v2: failParts.join('；'),
      }),
      data: { applied, failed },
    }
  }
  // 部分成功：ok=false 但必须把已写项说清楚，别让操作员以为全没写
  return {
    ok: false,
    summary:
      t('部分成功：已写入 {v1} 项（{v2}）{v3}；', {
        v1: applied.length,
        v2: okParts.join('；'),
        v3: dbNote,
      }) + t('失败 {v1} 项：{v2}。', { v1: failed.length, v2: failParts.join('；') }),
    data: { applied, failed },
  }
})

registerToolExecutor('WriteReportHeader', async (args) => {
  const fieldRaw = String(args.field ?? '').trim()
  const value = String(args.value ?? '')
  if (!fieldRaw) {
    return { ok: false, summary: t('未提供要填写的字段名，未执行写入。') }
  }
  if (!value) {
    return { ok: false, summary: t('字段「{v1}」的值为空，未执行写入。', { v1: fieldRaw }) }
  }

  const def = resolveHeaderField(fieldRaw)
  if (!def) {
    const fields = getPack()?.report.header_fields ?? []
    // 可用字段清单随界面语言（2026-10-15）：英文界面下列英文名，模型照抄的就是英文名
    const names = fields.map((f) => headerFieldName(f)).join('、') || t('（场景包未加载）')
    return {
      ok: false,
      summary: t('找不到报告表头字段「{v1}」。可用字段：{v2}。未执行写入。', {
        v1: fieldRaw,
        v2: names,
      }),
    }
  }

  const st = useAppStore.getState()
  // ① 写 store（报告页左栏 FieldRow 立即反映）
  st.setReportHeader(def.key, value)

  // ② 落库 report-instance：把当前全部有值表头 + 完整字段定义落一份
  const header = { ...useAppStore.getState().reportHeader, [def.key]: value }
  // 落库 payload 固定用中文规范名（f.name 恒为中文原文，2026-10-15）：这份定义写进轮次
  // 报告实例，**不随界面语言漂移**，保证同一轮产物在中/英文下内容一致
  const fields = (getPack()?.report.header_fields ?? []).map((f) => ({
    key: f.key,
    name: f.name,
    from_flow: f.from_flow,
    value_slot: f.value_slot,
  }))
  try {
    const { runId } = await persistReportInstance({
      sceneId: st.sceneId,
      runId: st.runId,
      header,
      fields,
      operator: st.operator,
    })
    return {
      ok: true,
      summary: t('已将报告表头「{v1}」填写为「{v2}」，并落库到轮次 {v3}。', {
        // 回执给用户与模型看，名字随界面语言；落库的 fields 里仍是中文规范名
        v1: headerFieldName(def),
        v2: value,
        v3: runId,
      }),
      data: { key: def.key, value, runId },
    }
  } catch (e) {
    // 界面已写（store 生效），但落库失败——如实说清「界面已改、未落库」，别谎报全成功
    return {
      ok: false,
      summary:
        t('已把报告表头「{v1}」填为「{v2}」（界面已更新），', { v1: headerFieldName(def), v2: value }) +
        t('但落库未成功：{v1}。', { v1: e instanceof Error ? e.message : String(e) }),
      data: { key: def.key, value },
    }
  }
})
