/**
 * AI 设置建议功能的**业务参数集中处**。
 *
 * 为什么单独一个文件：2026-10-29 之前，模型 id、「人为偏差演示」动哪个字段、
 * 注入成什么值，全是 `demo.ts` 里的字面量（`'deepseek-flash'`、`'.pole_pairs'`、
 * 目标值 6 / 1000、步进 1 / 100）。换场景包或换交付模型就得改逻辑代码，
 * 且单测把这些字面量写死，改动风险高。
 *
 * 约定：本文件只放**数据**，不放流程；数值必须是编辑器允许的合法值。
 */
import type { Stage } from './protocol'

/**
 * 关于「用哪个模型」——**此处不设常量**（2026-10-29 移除原 `SUGGESTION_MODEL_ID`）。
 *
 * 原实现把模型 id 写死成 `'deepseek-flash'`。但网关的 model_id 是由后端 `.env` 的
 * `MOTORDEBUG_LLM_MODEL` **派生**的（`vendor/model` → 末段，例如
 * `deepseek/deepseek-v4.1-flash-1017` → `deepseek-v4.1-flash-1017`），
 * 前端写死必然漂移：一旦 .env 换模型，按钮就报「当前渠道未提供 deepseek-flash」。
 *
 * 现口径：由调用方取 `/api/agent/models` 列表的**首项**（后端按 sort_order 升序返回，
 * 首项即平台主模型）。仍然「只用这一个、不随机挑、失败时不静默换别的模型」，
 * 只是这个 id 由后端决定，不再硬编码。
 */

/** 演示字段的匹配方式：`exact` 完全相等；`suffix` 以该串结尾（字段 id 含分组前缀时用） */
type MatchKind = 'exact' | 'suffix'

export interface DemoFieldRule {
  /** 匹配方式 */
  match: MatchKind
  /** 业务字段标识（场景包里的字段 key 或其尾部） */
  key: string
  /** 演示注入的目标值；selection 阶段不需要 */
  target?: number
  /** 当前值已等于目标值时的步进，用来造一个合法的差异 */
  bump?: number
}

/**
 * 「载入待修正示例」每个阶段注入的偏差。
 *
 * ⚠️ 这是**演示数据，不是模型建议**，也不代表设备推荐值；用途只是给真实模型
 * 一个可纠正的对象。改这些值前先确认对应编辑器的最小值/最大值/步长/精度。
 */
export const DEMO_FIELD_RULES: Readonly<Record<Stage, DemoFieldRule>> = {
  // 设备属性：电机极对数 2 → 6（场景包参考值口径外的合法值）
  init: { match: 'suffix', key: '.pole_pairs', target: 6, bump: 1 },
  // 测试需求：把已选中的判据取消勾选（req 阶段只允许改「是否纳入本轮」）
  req: { match: 'exact', key: 'req.TR-START-01' },
  // 执行检测：启动无位置模式转速 4000 → 1000
  run: { match: 'suffix', key: '.nonemode_speed', target: 1000, bump: 100 },
}
