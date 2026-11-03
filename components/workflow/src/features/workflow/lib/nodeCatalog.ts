/**
 * 节点类型目录。
 *
 * 数据源：峰岹前端引擎
 *   models/types.ts      —— WorkflowNodeType 枚举（58 个成员）
 *   models/nodeTypes.ts  —— NODE_PALETTE_ITEMS 的 category 字段与 NODE_CATEGORIES
 * 其中 57 个类型在节点面板里有分组归属，'_deprecated' 仅用于加载老文件时兜底、
 * 不出现在面板中，这里归入 basic。
 */
import type { NodeGroupId } from '../types'

export interface NodeGroupMeta {
  id: NodeGroupId
  /** 客户端面板里的中文分组名。 */
  label: string
  /** 面板排序权重，沿用 NODE_CATEGORIES.order。 */
  order: number
  /** 主色 #2E5E45 同色相的明度档，深→浅表示从执行主干到辅助节点。 */
  color: string
  /** 节点卡片底色，同色相极浅档。 */
  fill: string
}

export const NODE_GROUPS: Record<NodeGroupId, NodeGroupMeta> = {
  basic: { id: 'basic', label: '基础', order: 1, color: '#1F4232', fill: '#E3EDE6' },
  hid: { id: 'hid', label: 'HID 通信', order: 2, color: '#2A5741', fill: '#E6EFE9' },
  hid_presets: { id: 'hid_presets', label: '功能设置', order: 3, color: '#2E5E45', fill: '#EAF2EC' },
  debugging: { id: 'debugging', label: '代码调试', order: 4, color: '#3A6E53', fill: '#EDF4EF' },
  hid_query: { id: 'hid_query', label: '参数查询', order: 5, color: '#457C5F', fill: '#EFF5F1' },
  logic: { id: 'logic', label: '逻辑控制', order: 6, color: '#54896C', fill: '#F1F6F3' },
  data: { id: 'data', label: '数据处理', order: 7, color: '#65977A', fill: '#F3F8F5' },
  verify: { id: 'verify', label: '验证', order: 8, color: '#77A489', fill: '#F5F9F6' },
  subsystems: { id: 'subsystems', label: '子系统', order: 9, color: '#8CB39B', fill: '#F7FAF8' },
  instruments: { id: 'instruments', label: '仪器设备', order: 10, color: '#A8C5B5', fill: '#F9FBFA' },
  report: { id: 'report', label: '报告输出', order: 11, color: '#BCD2C6', fill: '#FBFCFB' },
  unknown: { id: 'unknown', label: '未识别', order: 99, color: '#9A9A9A', fill: '#F2F2F2' },
}

/** 节点类型字符串 → 分组。键与 WorkflowNodeType 枚举的字符串值一一对应。 */
export const NODE_TYPE_GROUP: Record<string, NodeGroupId> = {
  start: 'basic',
  end: 'basic',
  subworkflow: 'basic',
  subworkflow_input: 'basic',
  subworkflow_output: 'basic',
  agent_debug: 'basic',
  param_identification: 'basic',
  hid_preset_base_parameter_set: 'basic',
  motor_start_via_asic_debugger: 'basic',
  motor_start_test_ac: 'basic',
  motor_start_test_end_ac: 'basic',
  motor_start_debug_ac: 'basic',
  motor_stop_via_asic_debugger: 'basic',
  voltage_step_ac: 'basic',
  test_end_alert_ac: 'basic',
  _deprecated: 'basic',

  hid_send: 'hid',
  hid_receive: 'hid',

  hid_preset_voltage_set: 'hid_presets',
  hid_preset_temperature_set: 'hid_presets',
  hid_preset_pwm_set: 'hid_presets',
  hid_preset_start_stop_test: 'hid_presets',
  hid_preset_power_on: 'hid_presets',
  hid_preset_power_off: 'hid_presets',
  hid_preset_relay_close: 'hid_presets',
  hid_preset_relay_open: 'hid_presets',
  hid_preset_headwind_set: 'hid_presets',
  hid_preset_wind_close: 'hid_presets',
  hid_preset_tailwind_set: 'hid_presets',
  hid_preset_tailwind_exit: 'hid_presets',
  hid_preset_fan_start_test: 'hid_presets',
  hid_preset_speed_test: 'hid_presets',
  overshoot_test_ac: 'hid_presets',
  iic_speed_control_ac: 'hid_presets',

  phase_loss_debug_ac: 'debugging',

  hid_query_voltage: 'hid_query',
  hid_query_temperature: 'hid_query',
  hid_query_speed: 'hid_query',
  hid_query_current: 'hid_query',
  hid_query_power: 'hid_query',
  hid_query_hall_omega: 'hid_query',
  hid_query_me_status: 'hid_query',
  hid_query_fault_status: 'hid_query',
  loop_query: 'hid_query',
  phase_loss_speed_query_ac: 'hid_query',
  waveform_analysis: 'hid_query',

  condition: 'logic',
  condition_register_ac: 'logic',
  loop: 'logic',
  loop_break: 'logic',
  delay: 'logic',

  parse: 'data',
  variable: 'data',
  curve_lookup: 'data',

  assert: 'verify',
  log: 'verify',

  rigol_oscilloscope: 'instruments',
  report_generator: 'report',
}

/**
 * 样例文件里出现、但不在 WorkflowNodeType 枚举中的类型。
 * 保留映射以免旧文件被整片归为「未识别」。
 */
export const LEGACY_NODE_TYPE_GROUP: Record<string, NodeGroupId> = {
  hid_preset_pwm_speed_set: 'hid_presets',
}

/** 节点类型的中文回退名，用于 data.label 缺失时。 */
export const NODE_TYPE_LABEL: Record<string, string> = {
  start: '开始',
  end: '结束',
  subworkflow: '子工作流',
  delay: '延时等待',
  loop: '循环执行',
  loop_break: '循环跳出',
  condition: '条件判断',
  variable: '变量操作',
  parse: '数据解析',
  curve_lookup: '曲线插值查找',
  assert: '断言检查',
  log: '日志记录',
  rigol_oscilloscope: 'RIGOL 示波器',
  report_generator: '写入报告',
  agent_debug: 'AI 代码调试',
  param_identification: '电机参数辨识',
}

export function groupOf(type: string): NodeGroupId {
  return NODE_TYPE_GROUP[type] ?? LEGACY_NODE_TYPE_GROUP[type] ?? 'unknown'
}

/** 分组按面板顺序排列。 */
export const GROUP_ORDER: NodeGroupId[] = (
  Object.values(NODE_GROUPS) as NodeGroupMeta[]
)
  .slice()
  .sort((a, b) => a.order - b.order)
  .map((g) => g.id)
