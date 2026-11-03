import { uiMessage } from '../../i18n/messages'
import type { FlowId } from '../../data/types'
import type { EvidenceItem } from '../agent-chat'
import { headerFieldName, sourceLine, type RawPack } from '../scene/pack'
import { demoOn } from '../shared/tiers'
import type { Step } from './adapter'

/* ===========================================================================
   六条流程各一段短脚本。

   数值、路径、条目名全部从当前场景包取，脚本本身不带任何产品知识——
   换场景包时这里一个字都不用改，助手说的数会跟着换。凡是场景包里没有的东西
   一律不提，宁可少说一句，也不拿上一个场景的结论套到这个场景上。
   =========================================================================== */

function ev(id: string, kind: EvidenceItem['kind'], title: string, excerpt: string, src: string): EvidenceItem {
  const [file, loc] = src.split('（')
  return {
    id,
    kind,
    title,
    excerpt,
    source: file,
    locator: loc ? loc.replace(/）$/, '') : '—',
  }
}

export function scriptFor(flow: FlowId, p: RawPack): Step[] {
  const exps = p.experience.experiences
  const gate = p.interlocks.interlocks.filter((i) => i.type === '人员' || i.type === '流程')
  const tuneExps = exps.filter((e) => e.tags.flow?.startsWith('F5'))
  // 首选那一条要与候选队列同一个口径：证据级「台架实测数据」优先（06d 第 2.2 节）。
  // 原来取的是 tuneExps[0]，即场景包登记顺序的第一条（规程条款级的 EXP-001），
  // 与候选队列排在第一位的那条对不上，助手会讲一条屏幕上没推的经验。
  const EV_RANK: Record<string, number> = { 台架实测数据: 3, 台架经验: 2, 判定工具输出: 2, 规程条款: 1 }
  const topExp =
    [...tuneExps].sort((a, b) => (EV_RANK[b.evidence_level] ?? 1) - (EV_RANK[a.evidence_level] ?? 1))[0] ??
    exps[0]
  // 演示模式下脚本按分镜收到最短：只留「开场 → 动作 → 结论」三拍，
  // 中间那几次工具调用与证据卡切全量模式才给（06d 第 4 节分层方案）。
  const demo = demoOn()
  // 已标注批次的统计（datasets.json 的 package_stats）。没有这一段就是 null，
  // 助手那句话跟着换，不编。
  const ps = p.datasets.package_stats as Record<string, unknown> | undefined
  const batch =
    ps && typeof ps.pass === 'number' && typeof ps.labeled === 'number'
      ? { pass: ps.pass as number, labeled: ps.labeled as number }
      : null
  const holes = p.attributes.attributes.filter((a) => a._placeholder)
  const na = p.attributes.attributes.filter((a) => a.not_applicable)

  switch (flow) {
    case 'init':
      return [
        {
          kind: 'say',
          text: `本体属性 ${p.attributes.attributes.length} 项已从客户工程读出，其中 ${holes.length} 项是占位、${na.length} 项不适用。源材料没写的一律留空不编。`,
          uiText: uiMessage("本体属性 {v1} 项已从客户工程读出，其中 {v2} 项是占位、{v3} 项不适用。源材料没写的一律留空不编。", { v1: p.attributes.attributes.length, v2: holes.length, v3: na.length }),
        },
        {
          kind: 'tool',
          callId: 'init-1',
          name: 'attributes_load',
          title: '读取本体属性',
          args: { groups: p.attributes.groups, count: p.attributes.attributes.length },
          argsSummary: `按 ${p.attributes.groups.length} 个分组读 product-attributes.json`,
          durationMs: 610,
          resultSummary: `本体属性 ${p.attributes.attributes.length} 项，占位 ${holes.length} 处，不适用 ${na.length} 项`,
          result: {
            attributes: p.attributes.attributes.length,
            placeholders: holes.map((a) => a.name),
            notApplicable: na.map((a) => a.name),
          },
        },
        {
          kind: 'say',
          text: `${holes.length ? `占位的 ${holes.length} 项（${holes.slice(0, 3).map((a) => a.name).join('、')}${holes.length > 3 ? ' 等' : ''}）源材料确实没给，已标「待确认」，需要向客户索取，不要拿占位值当真值用。` : '没有占位项。'}${na.length ? ` ${na.map((a) => a.name).join('、')} 在本产品上不适用——${na[0].note?.slice(0, 48) ?? '控制器不需要这个量'}，所以标「不适用」而不是留空。` : ''}`,
          uiText: uiMessage("{v1}{v2}", { v1: holes.length ? `占位的 ${holes.length} 项（${holes.slice(0, 3).map((a) => a.name).join('、')}${holes.length > 3 ? ' 等' : ''}）源材料确实没给，已标「待确认」，需要向客户索取，不要拿占位值当真值用。` : '没有占位项。', v2: na.length ? ` ${na.map((a) => a.name).join('、')} 在本产品上不适用——${na[0].note?.slice(0, 48) ?? '控制器不需要这个量'}，所以标「不适用」而不是留空。` : '' }, ["v1","v2"]),
        },
      ]

    case 'req':
      return [
        {
          kind: 'say',
          text: `判据 ${p.requirements.requirements.length} 条按 ${p.requirements.categories.length} 类列出，可自动求值 ${p.requirements.evaluable_count} 条。我先对一遍判据与工作流步骤。`,
          uiText: uiMessage("判据 {v1} 条按 {v2} 类列出，可自动求值 {v3} 条。我先对一遍判据与工作流步骤。", { v1: p.requirements.requirements.length, v2: p.requirements.categories.length, v3: p.requirements.evaluable_count }),
        },
        {
          kind: 'tool',
          callId: 'req-1',
          name: 'criteria_extract',
          title: '判据抽取',
          args: { source: 'test-requirements.json', categories: p.requirements.categories.length },
          argsSummary: `按 ${p.requirements.categories.length} 类抽判据`,
          durationMs: 1180,
          resultSummary: `判据 ${p.requirements.requirements.length} 条，可自动求值 ${p.requirements.evaluable_count} 条、只能人工判 ${p.requirements.not_evaluable_count} 条`,
          result: { total: p.requirements.requirements.length, categories: p.requirements.categories },
        },
        {
          kind: 'tool',
          callId: 'req-2',
          name: 'workflow_index',
          title: '工作流库检索',
          args: { source: p.caps.workflowSource, total: p.workflows.total },
          argsSummary:
            p.caps.workflowSource === 'pack-assets'
              ? '读场景包自带的 assets/workflows/*.json'
              : '读 public/data 下的归档 .wfw',
          durationMs: 420,
          resultSummary: `库内 ${p.workflows.total} 条，分 ${Object.keys(p.workflows.count_by_group).length} 组${p.workflows.all_placeholder ? '，全部是示例占位' : ''}`,
          result: { total: p.workflows.total, byGroup: p.workflows.count_by_group },
        },
        {
          kind: 'say',
          text: `${p.requirements.not_evaluable_count} 条判据写不出布尔表达式——排程规则与目视检查那一类，标准本身就没给可测量的量，不硬凑。${p.workflows.all_placeholder ? '工作流这边一条真实文件都没有，4 条示例是本包自建的骨架，跑之前要按现场台架重做。' : ''}`,
          uiText: uiMessage("{v1} 条判据写不出布尔表达式——排程规则与目视检查那一类，标准本身就没给可测量的量，不硬凑。{v2}", { v1: p.requirements.not_evaluable_count, v2: p.workflows.all_placeholder ? '工作流这边一条真实文件都没有，4 条示例是本包自建的骨架，跑之前要按现场台架重做。' : '' }, ["v2"]),
        },
      ]

    case 'run':
      return [
        {
          kind: 'say',
          text: `控制参数 ${p.controls.parameters.length} 项已载入，安全确认闸门 ${gate.length} 条未全绿前「启动测试」保持置灰。我先跑预检再回放时序，启动属改动类动作，我不点。`,
          uiText: uiMessage("控制参数 {v1} 项已载入，安全确认闸门 {v2} 条未全绿前「启动测试」保持置灰。我先跑预检再回放时序，启动属改动类动作，我不点。", { v1: p.controls.parameters.length, v2: gate.length }),
        },
        {
          kind: 'tool',
          callId: 'run-1',
          name: 'precheck',
          title: '预检自检',
          args: { items: gate.slice(0, 3).map((g) => g.id) },
          argsSummary: `硬件项自检 + ${gate.length} 条人工闸门清点`,
          durationMs: 2260,
          resultSummary: `硬件项通过，安全确认闸门 ${gate.length} 条待人工逐条确认`,
          result: { hardware: 'ok', pendingGates: gate.map((g) => g.id) },
        },
        {
          kind: 'tool',
          callId: 'run-2',
          name: 'test_start',
          title: '启动测试',
          args: { gates: gate.length },
          argsSummary: '改动类动作，闸门全绿后由人点',
          mutating: true,
          durationMs: 0,
          resultSummary: '（需人工确认）',
          result: {},
        },
        ...(demo ? [] : [{
          kind: 'tool' as const,
          callId: 'run-3',
          name: 'waveform_replay',
          title: '时序回放与取指标',
          args: {
            datasets: p.datasets.datasets.map((d) => d.id),
            rate: p.datasets.datasets[0]?.sample_rate_sa_per_s ?? null,
          },
          argsSummary: `回放 ${p.datasets.datasets.length} 条登记时序`,
          durationMs: 3120,
          resultSummary: p.caps.syntheticData
            ? `${p.datasets.datasets.length} 条全部是合成数据，不是实测`
            : `${p.datasets.datasets.length} 条实测时序`,
          result: { synthetic: p.caps.syntheticData, datasets: p.datasets.datasets.map((d) => d.id) },
        }]),
        {
          kind: 'say',
          // 结论这句跟着判定卡的真实求值走，不写死：批次统计里有已标注的通过次数时，
          // 起动成功率这一条按合取短路判得出「不通过」；没有这一段登记的场景包
          // （例如合成的玻璃升降器包）照旧说判不了。
          text: batch
            ? `起动成功率这一条判不通过：已标注 ${batch.labeled} 次里通过 ${batch.pass} 次，判据要的是每次都成功。fault 标志与 FG2 最小转速本轮没采，但合取式里已经有一项为假，补齐也翻不过来。其余判据缺实测量，一律标未采集，不拿别的量顶替。${p.caps.syntheticData ? ` ${p.caps.syntheticBanner}` : ''}`
            : `判定这一步我给不出结论：判据要的现场实测量本轮一个都没采到。缺什么已逐条列在判定卡上，不拿别的量顶替。${p.caps.syntheticData ? ` ${p.caps.syntheticBanner}` : ''}${p.caps.probeUnconfirmed ? ` ${p.caps.probeNote}` : ''}`,
        },
        ...(demo
          ? []
          : [
              {
                kind: 'evidence' as const,
                items: [
                  ev(
                    'run-ev-1',
                    'case',
                    p.datasets.datasets[0]?.name ?? '本场景登记的时序数据',
                    p.datasets.datasets[0]?.note ?? '',
                    sourceLine(p.datasets.datasets[0]?._source),
                  ),
                ],
              },
            ]),
      ]

    case 'tune':
      return [
        {
          kind: 'say',
          text: `经验库 ${exps.length} 条里有 ${tuneExps.length} 条属调优流程。我按判定结果归因，只推能在本包控制参数里按宏名对上的候选。`,
          uiText: uiMessage("经验库 {v1} 条里有 {v2} 条属调优流程。我按判定结果归因，只推能在本包控制参数里按宏名对上的候选。", { v1: exps.length, v2: tuneExps.length }),
        },
        {
          kind: 'tool',
          callId: 'tune-1',
          name: 'experience_search',
          title: '经验检索',
          args: { flow: 'F5', parameters: topExp?.tags.parameters ?? [] },
          argsSummary: '按流程与参数名检索经验库',
          durationMs: 760,
          resultSummary: `命中 ${tuneExps.length} 条 F5 经验${topExp ? `，首选 ${topExp.id}（${topExp.evidence_level}）` : ''}`,
          result: { hits: tuneExps.map((e) => e.id) },
        },
        topExp
          ? {
              kind: 'say',
              text: `${topExp.id}（${topExp.evidence_level}）给的动作是：${topExp.action}`,
          uiText: uiMessage("{v1}（{v2}）给的动作是：{v3}", { v1: topExp.id, v2: topExp.evidence_level, v3: topExp.action }, ["v2"]),
            }
          : { kind: 'say', text: '经验库里没有能对上本场景参数名的 F5 条目，这一轮我不给推荐。' },
        ...(demo || !topExp
          ? []
          : [
              {
                kind: 'evidence' as const,
                items: [
                  ev(
                    'tune-ev-1',
                    'procedure',
                    `${topExp.id} · ${topExp.evidence_level}`,
                    topExp.cause,
                    sourceLine(topExp._source),
                  ),
                ],
              },
            ]),
        {
          kind: 'say',
          // 排序口径已改成证据级优先（06d 第 2.2 节），这句话原来写的是「按能否给出
          // 具体数值排队」，与代码里的 useCandidates() 对不上，一并改过来。
          text: '候选按证据级排队，台架实测数据那一级排在规程条款前面，一次只动一项。采纳与写回都要你点，我不写回也不触发重跑。',
        },
      ]

    case 'report':
    default:
      return [
        {
          kind: 'say',
          text: `报告模板表头 ${p.report.header_fields.length} 字段，我按模板填一遍。填不上的字段单独列出来，不编。`,
          uiText: uiMessage("报告模板表头 {v1} 字段，我按模板填一遍。填不上的字段单独列出来，不编。", { v1: p.report.header_fields.length }),
        },
        {
          kind: 'tool',
          callId: 'rep-1',
          name: 'template_fill',
          title: '模板填充',
          args: { template: p.report.template_file, sections: p.report.spec_sections.length },
          argsSummary: `表头 ${p.report.header_fields.length} 字段 + 分节 ${p.report.spec_sections.length} 节`,
          durationMs: 1540,
          resultSummary: `可由上游流程带入 ${p.report.header_fields.filter((f) => !f.from_flow.startsWith('F6')).length} 项，需本流程补全 ${p.report.header_fields.filter((f) => f.from_flow.startsWith('F6')).length} 项`,
          result: {
            header: p.report.header_fields.map((f) => ({
              // 演示脚本的工具返回同样随界面语言（2026-10-15）：英文界面下给英文名，模型不会照抄中文
              name: headerFieldName(f),
              labelSlot: f.label_slot,
              valueSlot: f.value_slot,
              section: f.label_section ?? null,
              from: f.from_flow,
            })),
          },
        },
        {
          kind: 'say',
          text: `字段定位统一成「一个标题位 + 一个取值位」，Excel 模板与 PDF 样张共用同一套填充逻辑。图片位共 ${p.report.artifact_groups.reduce((a, b) => a + b.count, 0)} 张。${p.caps.syntheticData ? '注意：本场景时序全部是合成数据，按场景包的流程联锁，不得进入任何合规报告。' : ''}导出与归档要你点，我不做。`,
          uiText: uiMessage("字段定位统一成「一个标题位 + 一个取值位」，Excel 模板与 PDF 样张共用同一套填充逻辑。图片位共 {v1} 张。{v2}导出与归档要你点，我不做。", { v1: p.report.artifact_groups.reduce((a, b) => a + b.count, 0), v2: p.caps.syntheticData ? '注意：本场景时序全部是合成数据，按场景包的流程联锁，不得进入任何合规报告。' : '' }, ["v2"]),
        },
      ]
  }
}
