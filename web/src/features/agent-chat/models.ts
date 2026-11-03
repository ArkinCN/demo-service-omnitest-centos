// AI 助手模型列表：从后端动态拉取（2026-10-14）。
//
// 此前模型候选是 types.ts 里的**硬编码字面量**，与后端 model_pricing 表脱钩：
// 后台新增/停用模型后前端不会同步，还会出现「下拉点得到、一用就报模型不可用」。
//
// 现在统一走后端 `GET /api/agent/models`（与 `/api/agent/stream` 同源同鉴权）：
// 后端按 chat_enabled=True && is_active=True + 模型级 permissions 过滤、
// 按 sort_order 排序后返回。后台增删模型 → 前端刷新即同步，无需改代码。
import type { ModelOption } from './types';

interface RawModel {
  id?: string;
  name?: string;
  vision?: boolean;
  reasoning?: boolean;
  provider_name?: string;
  description?: string;
}

/** 归一化后端返回的一条模型记录 → 前端下拉用的 ModelOption。 */
function toOption(raw: RawModel): ModelOption | null {
  const value = (raw.id ?? '').trim();
  if (!value) return null;
  return {
    value,
    label: (raw.name ?? '').trim() || value,
    vision: Boolean(raw.vision),
    reasoning: Boolean(raw.reasoning),
    providerName: raw.provider_name ?? '',
    description: raw.description ?? '',
  };
}

/**
 * 拉取 AI 助手可选模型。失败（网络/401/后端未起）时抛错，
 * 由调用方决定回退到 FALLBACK_MODEL_OPTIONS —— 这里不吞错误，
 * 免得把「后端坏了」伪装成「只有兜底模型可用」。
 */
export async function fetchModels(signal?: AbortSignal): Promise<ModelOption[]> {
  const resp = await fetch('/api/agent/models', { signal });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const body = (await resp.json()) as { data?: RawModel[] };
  const list = Array.isArray(body?.data) ? body.data : [];
  return list.map(toOption).filter((m): m is ModelOption => m !== null);
}
