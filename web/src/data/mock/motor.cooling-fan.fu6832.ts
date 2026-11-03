import type { ScenePackage } from '../types'

/* 临时 mock 场景包：电机 › 家电电机 › 散热风扇（FU6832 驱动板）
   内容对齐设计规格第 9 节六流程页面规格；真实场景包到位后由 loadScene() 覆盖。 */

export const MOCK_SCENE: ScenePackage = {
  meta: {
    id: 'motor.cooling-fan.fortior-fu6832',
    scene: '电机',
    subclass: '家电电机',
    productType: '散热风扇',
    packName: '散热风扇场景包',
    packVersion: 'v0.3',
    bench: '涵道逆风台架 · 工位 A',
  },

  toolGroups: [
    {
      id: 'acquire',
      title: '数据采集',
      tools: [
        { id: 'scope', label: '波形采集', glyph: '∿', state: 'online', hint: '示波器采集 · 最近一次 12 分钟前' },
        { id: 'deep', label: '深存储', glyph: '⊟', state: 'online', hint: '深存储抓取脚本' },
        { id: 'rpm', label: '转速读取', glyph: '◉', state: 'online' },
        { id: 'shot', label: '截图留档', glyph: '▣', state: 'offline' },
      ],
    },
    {
      id: 'stimulus',
      title: '环境与激励',
      tools: [
        { id: 'psu', label: '程控电源', glyph: '⚡', state: 'online' },
        { id: 'wind', label: '逆风调速', glyph: '≋', state: 'online' },
        { id: 'temp', label: '温箱设定', glyph: '◈', state: 'offline' },
      ],
    },
    {
      id: 'device',
      title: '对象调试',
      tools: [
        { id: 'write', label: '参数写入', glyph: '✎', state: 'online' },
        { id: 'flash', label: '编译烧录', glyph: '⌘', state: 'online' },
        { id: 'reg', label: '寄存器', glyph: '⟡', state: 'fault', hint: '上次读写超时' },
      ],
    },
    {
      id: 'session',
      title: '会话与远程',
      tools: [
        { id: 'cli', label: '命令行', glyph: '⌁', state: 'online', hint: '台架机远程登录会话' },
        { id: 'vnc', label: '远程桌面', glyph: '▤', state: 'offline' },
      ],
    },
  ],

  flows: {
    init: {
      greeting:
        '已按散热风扇场景包解析三份文档并回填左栏：数据手册给出本体属性，Customer.h 解析出 812 条宏、本次纳入可调清单 14 项。母线电压上限文档里没写，我按联锁模板占位 30 V，这一项需要你拍板。',
      verifyLine: '已填 14 / 16，1 项与文档冲突，1 项缺来源',
      checklist: [
        { id: 'c1', index: '01', name: '测试对象标识', status: 'done', groupId: 'A' },
        { id: 'c2', index: '02', name: '产品本体属性', status: 'done', groupId: 'B' },
        { id: 'c3', index: '03', name: '驱动与固件', status: 'done', groupId: 'C' },
        { id: 'c4', index: '04', name: '功能清单', status: 'na', groupId: 'D' },
        { id: 'c5', index: '05', name: '安全联锁', status: 'alert', groupId: 'E' },
        { id: 'c6', index: '06', name: '设备与通道', status: 'empty', groupId: 'F' },
      ],
      cards: [
        { id: 'product-view', active: true, summary: '散热风扇本体与被测点标注' },
        { id: 'schematic', summary: '标准方案 · 第 2 页 / 共 6 页' },
        { id: 'project-tree', summary: 'Keil 工程 · Customer.h 已解析 812 宏' },
        { id: 'interlock', alert: '1 项未满足', summary: '联锁 3 / 4 满足' },
      ],
      canvas: {
        nodes: [
          { id: 'product-view', x: 40, y: 40, w: 300, h: 190 },
          { id: 'schematic', x: 400, y: 24, w: 320, h: 160 },
          { id: 'project-tree', x: 420, y: 220, w: 300, h: 150 },
          { id: 'interlock', x: 60, y: 260, w: 260, h: 120 },
        ],
        links: [
          { from: 'schematic', to: 'product-view', kind: 'belong', label: '同一块驱动板' },
          { from: 'product-view', to: 'interlock', kind: 'signal', label: '母线 → 联锁监测' },
        ],
      },
      groups: [
        {
          id: 'A',
          index: 'A',
          title: '测试对象标识',
          subgroups: [
            {
              id: 'A1',
              title: '基本信息',
              items: [
                { id: 'sn', name: '样机编号', value: 'CF-2609-018', kind: 'readonly', source: '人工', status: 'done' },
                { id: 'batch', name: '批次', value: '2026-W37', kind: 'readonly', source: '人工', status: 'done' },
                { id: 'purpose', name: '测试目的', value: '出厂回归', kind: 'select', options: ['出厂回归', '设计验证', '问题复现'], source: '人工', status: 'done' },
              ],
            },
            {
              id: 'A2',
              title: '关联工程',
              items: [
                { id: 'proj', name: '工程目录', value: 'FTC6804A.uvproj', kind: 'file', source: '文档', status: 'done', evidence: '散热风扇 Keil 工程' },
              ],
            },
          ],
        },
        {
          id: 'B',
          index: 'B',
          title: '产品本体属性',
          subgroups: [
            {
              id: 'B1',
              title: '电气',
              items: [
                { id: 'vn', name: '额定电压', value: 24, unit: 'V', kind: 'number', step: 1, min: 0, max: 60, source: '文档', status: 'done', evidence: 'FU6832 数据手册 §2.1', note: '母线范围 18 ~ 30 V' },
                { id: 'in', name: '额定电流', value: 2.4, unit: 'A', kind: 'number', step: 0.1, precision: 1, min: 0, max: 20, source: '文档', status: 'done' },
              ],
            },
            {
              id: 'B2',
              title: '结构常数',
              items: [
                { id: 'poles', name: '极对数', value: 2, kind: 'number', step: 1, min: 1, max: 12, source: '文档', status: 'done', evidence: '样机铭牌', note: '决定两路转速反馈的频率比判据' },
                { id: 'phase', name: '相数', value: 3, kind: 'number', step: 1, min: 1, max: 6, source: '文档', status: 'done' },
              ],
            },
            {
              id: 'B3',
              title: '额定工况',
              items: [
                { id: 'rpm', name: '额定转速', value: 4200, unit: 'rpm', kind: 'number', step: 100, min: 0, max: 20000, source: '文档', status: 'done' },
                { id: 'rpmmax', name: '最高转速', value: 5200, unit: 'rpm', kind: 'number', step: 100, min: 0, max: 20000, source: '人工', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'C',
          index: 'C',
          title: '驱动与固件',
          defaultOpen: false,
          subgroups: [
            {
              id: 'C1',
              title: '参数头文件',
              items: [
                { id: 'hdr', name: '头文件', value: 'Customer.h', kind: 'file', source: '文档', status: 'done' },
                { id: 'macro', name: '宏总数 / 已解析', value: '812 / 812', kind: 'readonly', source: '文档', status: 'done' },
                { id: 'tunable', name: '纳入可调清单', value: 14, unit: '项', kind: 'number', step: 1, min: 0, max: 100, source: '建议', status: 'done', note: '启动电流、启动角度、环路增益、载波与死区' },
              ],
            },
          ],
        },
        {
          id: 'E',
          index: 'E',
          title: '安全联锁',
          subgroups: [
            {
              id: 'E1',
              title: '人员与现场',
              items: [
                { id: 'person', name: '人员离场确认', value: '未确认', kind: 'select', options: ['已确认', '未确认'], source: '人工', status: 'alert', note: '需确认人签字，启动前必须满足' },
                { id: 'guard', name: '防护罩到位', value: '已确认', kind: 'select', options: ['已确认', '未确认'], source: '人工', status: 'done' },
              ],
            },
            {
              id: 'E2',
              title: '电气量上限',
              items: [
                { id: 'vmax', name: '母线电压上限', value: 30, unit: 'V', kind: 'number', step: 1, min: 0, max: 60, source: '建议', status: 'done', note: '触发后动作：停机', evidence: '联锁模板 · 场景包 v0.3' },
                { id: 'imax', name: '相电流上限', value: 8, unit: 'A', kind: 'number', step: 0.5, precision: 1, min: 0, max: 30, source: '文档', status: 'done' },
                { id: 'dur', name: '单次连续运行上限', value: 30, unit: 'min', kind: 'number', step: 5, min: 1, max: 240, source: '人工', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'F',
          index: 'F',
          title: '设备与通道',
          defaultOpen: false,
          subgroups: [
            {
              id: 'F1',
              title: '通道映射',
              items: [
                { id: 'ch1', name: 'CH1', value: '电气转速反馈', kind: 'select', options: ['电气转速反馈', '机械转速反馈', '驱动输出'], source: '人工', status: 'done' },
                { id: 'ch2', name: 'CH2', value: '机械转速反馈', kind: 'select', options: ['电气转速反馈', '机械转速反馈', '驱动输出'], source: '人工', status: 'done' },
                { id: 'ch3', name: 'CH3', value: '未接入', kind: 'select', options: ['未接入', '驱动输出'], status: 'empty' },
              ],
            },
          ],
        },
      ],
    },

    /* ---------------------------------------------------------------- 3 测试需求确认 */
    req: {
      greeting:
        '从客户质量要求里抽出三条判据，两条致命一条主要。有一处对不上：判据里要判稳态转速偏差，但工作流里没有一步采集稳态段，要我在第 4 步后面补一个采集节点吗？',
      verifyLine: '判据 3 条已抽取，工作流 6 步，1 处判据无对应采集步骤',
      checklist: [
        { id: 'c1', index: '01', name: '需求来源', status: 'done', groupId: 'A' },
        { id: 'c2', index: '02', name: '质量判据', status: 'done', groupId: 'B' },
        { id: 'c3', index: '03', name: '工作流', status: 'alert', groupId: 'C' },
        { id: 'c4', index: '04', name: '测试案例', status: 'empty', groupId: 'D' },
      ],
      cards: [
        { id: 'workflow', active: true, summary: '启停回归模板 · 6 步 · 当前停在第 4 步' },
        { id: 'verdict', summary: '判据表预览 · 3 条 · 本阶段只列不判' },
        { id: 'history', summary: '同产品同模板近 5 次成绩' },
        { id: 'evidence', summary: '判据出自 客户质量要求 QR-2026-03 §5' },
      ],
      groups: [
        {
          id: 'A',
          index: 'A',
          title: '需求来源',
          subgroups: [
            {
              id: 'A1',
              title: '来源文件',
              items: [
                { id: 'std', name: '标准与规范', value: 'QR-2026-03', kind: 'file', source: '文档', status: 'done', evidence: '客户质量要求 QR-2026-03' },
                { id: 'base', name: '上一版需求基线', value: 'v0.2 · 2026-08-30', kind: 'readonly', source: '文档', status: 'done' },
              ],
            },
            {
              id: 'A2',
              title: '适用范围',
              items: [
                { id: 'cond', name: '适用工况', value: '常温逆风', kind: 'select', options: ['常温逆风', '常温顺风', '高温'], source: '人工', status: 'done' },
                { id: 'n', name: '样本量', value: 3, unit: '台', kind: 'number', step: 1, min: 1, max: 50, source: '人工', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'B',
          index: 'B',
          title: '质量判据',
          subgroups: [
            {
              id: 'B1',
              title: '判据条目',
              items: [
                { id: 'j1', name: '两路转速反馈频率比', value: 2.0, kind: 'number', step: 0.01, precision: 2, min: 0, max: 20, source: '文档', status: 'done', note: '容差 ±0.05 · 等级致命' },
                { id: 'j2', name: '启动成功率下限', value: 95, unit: '%', kind: 'number', step: 1, min: 0, max: 100, source: '文档', status: 'done', note: '等级致命' },
                { id: 'j3', name: '稳态转速偏差上限', value: 5, unit: '%', kind: 'number', step: 1, min: 0, max: 50, source: '文档', status: 'alert', note: '等级主要 · 工作流缺对应采集步骤' },
              ],
            },
            {
              id: 'B2',
              title: '整体结论规则',
              items: [
                { id: 'rule', name: '致命项', value: '全部通过', kind: 'readonly', source: '文档', status: 'done' },
                { id: 'rule2', name: '主要项通过率下限', value: 90, unit: '%', kind: 'number', step: 5, min: 0, max: 100, source: '人工', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'C',
          index: 'C',
          title: '工作流',
          subgroups: [
            {
              id: 'C1',
              title: '模板与循环',
              items: [
                { id: 'tpl', name: '模板', value: '启停回归', kind: 'select', options: ['启停回归', '顺风重启', '温升保持'], source: '建议', status: 'done', note: '6 步 · 预计 42 分钟' },
                { id: 'rep', name: '重复次数', value: 100, unit: '次', kind: 'number', step: 10, min: 1, max: 1000, source: '人工', status: 'done' },
                { id: 'wait', name: '档间等待', value: 3, unit: 's', kind: 'number', step: 1, min: 0, max: 60, source: '人工', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'D',
          index: 'D',
          title: '测试案例',
          defaultOpen: false,
          subgroups: [
            {
              id: 'D1',
              title: '案例选择',
              items: [
                { id: 'case1', name: '散热风扇启动实验集', value: '未勾选', kind: 'switch', options: ['已勾选', '未勾选'], status: 'empty', note: '历史通过率 78%' },
              ],
            },
          ],
        },
      ],
    },

    /* ---------------------------------------------------------------- 4 启动测试及结果分析 */
    run: {
      greeting:
        '预检过了四项里的三项：设备连通、通道有信号、基线快照已存都通过；现场安全总闸还没开。总闸打开后启动按钮才会亮。运行中我会逐步播报，越线先停机再叫你。',
      verifyLine: '闸门 2 / 3 成立：联锁差 1 项、总闸未开',
      checklist: [
        { id: 'c1', index: '01', name: '控制参数', status: 'done', groupId: 'A' },
        { id: 'c2', index: '02', name: '本轮运行设置', status: 'done', groupId: 'B' },
        { id: 'c3', index: '03', name: '安全确认闸门', status: 'alert', groupId: 'C' },
      ],
      cards: [
        // 第三轮删「安全联锁状态盘」：与左栏安全闸门是同一组联锁的第二次呈现（06d 第 3.1 节）
        { id: 'timeseries', active: true, alert: '第 63 轮越线', summary: '两路转速反馈 + 母线电流 · 实时' },
        { id: 'progress', summary: '第 63 / 100 轮 · 已用 26 分钟' },
        { id: 'verdict', summary: '致命 2 条通过 1 条待定 · 主要 1 条' },
      ],
      canvas: {
        nodes: [
          { id: 'timeseries', x: 32, y: 30, w: 420, h: 200 },
          { id: 'progress', x: 490, y: 30, w: 240, h: 130 },
          { id: 'verdict', x: 60, y: 260, w: 300, h: 120 },
        ],
        links: [
          { from: 'timeseries', to: 'verdict', kind: 'signal', label: 'CH1 → 判据 1' },
          { from: 'progress', to: 'timeseries', kind: 'belong' },
        ],
      },
      groups: [
        {
          id: 'A',
          index: 'A',
          title: '控制参数',
          subgroups: [
            {
              id: 'A1',
              title: '目标设定',
              items: [
                { id: 'target', name: '目标转速', value: 3800, unit: 'rpm', kind: 'number', step: 100, min: 0, max: 20000, source: '人工', status: 'done' },
                { id: 'istart', name: '启动电流', value: 6.0, unit: 'A', kind: 'number', step: 0.1, precision: 1, min: 0.1, max: 20, source: '建议', status: 'done', note: '取值 0.1 ~ 20 A', evidence: '调参经验 · 案例 A-118' },
              ],
            },
            {
              id: 'A2',
              title: '过程整定',
              items: [
                { id: 'acc', name: '加速时间', value: 1.5, unit: 's', kind: 'number', step: 0.1, precision: 1, min: 0.1, max: 10, source: '文档', status: 'done' },
                { id: 'ang', name: '启动角度', value: 30, unit: '°', kind: 'number', step: 5, min: 0, max: 180, source: '建议', status: 'done' },
              ],
            },
            {
              id: 'A3',
              title: '参数来源',
              items: [
                { id: 'from', name: '本组参数来自', value: '初始基线 + 第 2 轮调优采纳', kind: 'readonly', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'B',
          index: 'B',
          title: '本轮运行设置',
          subgroups: [
            {
              id: 'B1',
              title: '轮次与采集',
              items: [
                { id: 'rep', name: '重复次数', value: 100, unit: '次', kind: 'number', step: 10, min: 1, max: 1000, source: '人工', status: 'done' },
                { id: 'rate', name: '采样率', value: 100, unit: 'kSa', kind: 'number', step: 10, min: 1, max: 1000, source: '人工', status: 'done' },
                { id: 'keep', name: '留档策略', value: '全存', kind: 'select', options: ['全存', '仅异常存', '抽样存'], source: '人工', status: 'done' },
              ],
            },
            {
              id: 'B2',
              title: '失败处理',
              items: [
                { id: 'fail', name: '失败动作', value: '继续记录', kind: 'select', options: ['失败即停', '继续记录', '连续失败 3 次即停'], source: '人工', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'C',
          index: 'C',
          title: '安全确认闸门',
          subgroups: [
            {
              id: 'C1',
              title: '联锁逐条确认',
              items: [
                { id: 'l1', name: '人员离场', value: '未确认', kind: 'select', options: ['已确认', '未确认'], source: '人工', status: 'alert', note: '确认人与时间会记入报告附录' },
                { id: 'l2', name: '母线电压上限已写入', value: '已确认', kind: 'select', options: ['已确认', '未确认'], source: '人工', status: 'done' },
                { id: 'l3', name: '基线快照已保存', value: '已确认', kind: 'select', options: ['已确认', '未确认'], source: '文档', status: 'done' },
              ],
            },
            {
              id: 'C2',
              title: '预检结果',
              items: [
                { id: 'p1', name: '设备连通', value: '通过', kind: 'readonly', status: 'done' },
                { id: 'p2', name: '通道有信号', value: '通过', kind: 'readonly', status: 'done' },
              ],
            },
            {
              id: 'C3',
              title: '总闸',
              items: [
                { id: 'gate', name: '我已确认现场安全', value: '未开', kind: 'switch', options: ['已开', '未开'], source: '人工', status: 'alert', note: '每轮测试后自动复位' },
              ],
            },
          ],
        },
      ],
    },

    /* ---------------------------------------------------------------- 5 调优确认及运行 */
    tune: {
      greeting:
        '未达标的是启动成功率，实测 78%、要求 95%，失败集中在逆风档位。候选给了三组，第一组只动启动电流、影响面最小；第三组改环路增益，效果预期最好但要重新烧录。采纳哪一组由你点。',
      verifyLine: '候选 3 组已排序，采纳后需重新编译烧录',
      checklist: [
        { id: 'c1', index: '01', name: '未达标项', status: 'alert', groupId: 'A' },
        { id: 'c2', index: '02', name: '候选参数队列', status: 'done', groupId: 'B' },
        { id: 'c3', index: '03', name: '采纳与写回', status: 'empty', groupId: 'C' },
      ],
      cards: [
        // 第三轮删「判定卡」：与左栏未达标 / 已通过 / 未采集是同一件事的第二次呈现
        { id: 'history', active: true, summary: '历次调参与结果对照 · 5 轮' },
        { id: 'evidence', summary: '候选依据 · 规程 §3.2 与案例 A-118 / A-203' },
        { id: 'timeseries', summary: '本轮与上一轮波形叠加' },
      ],
      groups: [
        {
          id: 'A',
          index: 'A',
          title: '未达标项',
          subgroups: [
            {
              id: 'A1',
              title: '逐条列出',
              items: [
                { id: 'g1', name: '启动成功率', value: 78, unit: '%', kind: 'readonly', status: 'alert', note: '目标 95% · 差 17pp · 等级致命 · 第 1~100 轮' },
                { id: 'g2', name: '稳态转速偏差', value: 3.2, unit: '%', kind: 'readonly', status: 'done', note: '目标 ≤5% · 通过' },
              ],
            },
            {
              id: 'A2',
              title: '归因',
              items: [
                { id: 'r1', name: '逆风档启动力矩不足', value: '置信度 0.72', kind: 'readonly', status: 'alert', evidence: '案例 A-118 · 失败案例 12 条' },
                { id: 'r2', name: '启动角度与转子初始位置失配', value: '置信度 0.41', kind: 'readonly', status: 'empty', evidence: '测试规程 §3.2' },
              ],
            },
          ],
        },
        {
          id: 'B',
          index: 'B',
          title: '候选参数队列',
          subgroups: [
            {
              id: 'B1',
              title: '候选一 · 只动启动电流',
              items: [
                { id: 'c1i', name: '启动电流', value: 7.0, unit: 'A', kind: 'number', step: 0.1, precision: 1, min: 0.1, max: 20, source: '建议', status: 'done', note: '当前 6.0 A · 预期 +12pp · 风险低' },
              ],
            },
            {
              id: 'B2',
              title: '候选二 · 电流与角度组合',
              items: [
                { id: 'c2i', name: '启动电流', value: 6.5, unit: 'A', kind: 'number', step: 0.1, precision: 1, min: 0.1, max: 20, source: '建议', status: 'done' },
                { id: 'c2a', name: '启动角度', value: 45, unit: '°', kind: 'number', step: 5, min: 0, max: 180, source: '建议', status: 'done', note: '当前 30° · 预期 +15pp · 风险中' },
              ],
            },
          ],
        },
        {
          id: 'C',
          index: 'C',
          title: '采纳与写回',
          subgroups: [
            {
              id: 'C1',
              title: '写回目标',
              items: [
                { id: 'w1', name: '写到哪', value: '参数文件', kind: 'select', options: ['参数文件', '设备寄存器', '运行时配置'], source: '人工', status: 'empty' },
                { id: 'w2', name: '需重新编译烧录', value: '是', kind: 'readonly', status: 'empty' },
                { id: 'w3', name: '版本号', value: 'cfg-2026w38-03', kind: 'readonly', status: 'empty', note: '上一版 cfg-2026w38-02，可一键回滚' },
              ],
            },
          ],
        },
      ],
    },

    /* ---------------------------------------------------------------- 6 测试报告及产出 */
    report: {
      greeting:
        '模板 14 个字段填上了 12 个，缺测试负责人与送样批次号。结论段我写好了草稿，标了待复核——里面每个数值都能点回对应轮次，导出前请你过一遍。',
      verifyLine: '字段 12 / 14 已映射，结论段待人工复核',
      checklist: [
        { id: 'c1', index: '01', name: '模板选择', status: 'done', groupId: 'A' },
        { id: 'c2', index: '02', name: '信息确认', status: 'alert', groupId: 'B' },
        { id: 'c3', index: '03', name: '内容组装', status: 'done', groupId: 'C' },
        { id: 'c4', index: '04', name: '导出与归档', status: 'empty', groupId: 'D' },
      ],
      cards: [
        { id: 'report-preview', active: true, summary: '分页预览 · 11 页 · 结论段待复核' },
        { id: 'artifacts', summary: '本轮产物 248 MB · 波形 9 张 · 快照 3 份' },
        { id: 'verdict', summary: '致命 2 条 · 主要 1 条 · 总体待定' },
        { id: 'history', summary: '历史报告对照 · 近 3 份' },
      ],
      groups: [
        {
          id: 'A',
          index: 'A',
          title: '模板选择',
          subgroups: [
            {
              id: 'A1',
              title: '模板与字段映射',
              items: [
                { id: 't1', name: '报告模板', value: '散热风扇出厂测试报告 v3', kind: 'select', options: ['散热风扇出厂测试报告 v3', '设计验证报告 v1'], source: '文档', status: 'done', note: '适用产品类型：散热风扇 · 字段 14' },
                { id: 't2', name: '已映射字段', value: '12 / 14', kind: 'readonly', status: 'alert' },
              ],
            },
          ],
        },
        {
          id: 'B',
          index: 'B',
          title: '信息确认',
          subgroups: [
            {
              id: 'B1',
              title: '人员与单位',
              items: [
                { id: 'owner', name: '测试负责人', value: '未填写', kind: 'readonly', status: 'alert' },
                { id: 'checker', name: '复核人', value: '李工', kind: 'readonly', source: '人工', status: 'done' },
              ],
            },
            {
              id: 'B2',
              title: '产品信息',
              items: [
                { id: 'batch', name: '送样批次号', value: '未填写', kind: 'readonly', status: 'alert', note: '流程 2 未带出，需人工补' },
                { id: 'sn', name: '样机编号', value: 'CF-2609-018', kind: 'readonly', source: '文档', status: 'done' },
              ],
            },
          ],
        },
        {
          id: 'C',
          index: 'C',
          title: '内容组装',
          subgroups: [
            {
              id: 'C1',
              title: '章节开关',
              items: [
                { id: 'ch1', name: '异常说明章节', value: '纳入', kind: 'switch', options: ['纳入', '不纳入'], source: '人工', status: 'done' },
                { id: 'ch2', name: '附录：联锁豁免记录', value: '纳入', kind: 'switch', options: ['纳入', '不纳入'], source: '人工', status: 'done' },
                { id: 'ch3', name: '结论生成方式', value: '助手撰写', kind: 'select', options: ['模板套话', '助手撰写', '人工撰写'], source: '人工', status: 'done', note: '助手稿强制人工复核' },
              ],
            },
          ],
        },
        {
          id: 'D',
          index: 'D',
          title: '导出与归档',
          defaultOpen: false,
          subgroups: [
            {
              id: 'D1',
              title: '导出',
              items: [
                { id: 'fmt', name: '格式', value: 'PDF + 原始数据包', kind: 'select', options: ['PDF', 'PDF + 原始数据包', 'Excel'], source: '人工', status: 'empty' },
                { id: 'arch', name: '归档分类', value: '电机 › 家电电机 › 散热风扇', kind: 'readonly', status: 'empty' },
              ],
            },
          ],
        },
      ],
    },
  },
}
