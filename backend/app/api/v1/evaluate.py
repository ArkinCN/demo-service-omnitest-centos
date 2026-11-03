"""
判据求值路由（阶段 4 引入，判定放后端）。

`POST /api/evaluate`：给定 scene_id 与实测量，对场景包全部判据求值，返回
与前端 `flow-run/evaluate.ts` 的 `evaluateAll` 对齐的判定结果。

判定口径（照抄前端，两边一致）：
- 默认：只要有一个 runtime.measure 取不到 → 未采集（missing），不推 pass:false
- 合取短路：某子句所需变量已全采到且为假 → 直接 fail + partial
- 子句求值抛异常 → 回落 missing

实测量来源：请求体显式传入 measures；未传时从 datasets.json 的 package_stats
取默认值（pass_count，标历史）。前端 evaluate.ts 保留做即时预览，后端此端点
为最终判定权威。
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.common import success_response
from app.services.evaluate import evaluate_all, package_stats_measures

# 鉴权门禁：原先本路由未挂鉴权（2026-09-23 全量审查发现）。
# 判据求值不按人隔离，只要求「已登录」一层，故参数命名为 `_`。
router = APIRouter(prefix="/api", tags=["Evaluate"])

# 场景包数据目录（前端运行时读的 public/scenes）
_FRONTEND_DIR = Path(__file__).resolve().parents[3]  # c/web 的上级？算准：backend/app/api/v1 → 上4级是 backend
_SCENES_DIR = _FRONTEND_DIR.parent / "web" / "public" / "scenes"


class EvaluateRequest(BaseModel):
    scene_id: str = Field(..., description="场景 ID")
    measures: dict = Field(default_factory=dict, description="本轮实测量（未传则从 package_stats 取默认）")
    # 采纳/人工改过的控制参数（key = 场景包参数 key → 当前值）。判据里的
    # control-parameters 变量应读「当前生效值」，否则改了参数、权威判定仍读场景包
    # 原值，结论永远不变。前端把 store.overrides 按回落链折算成 key→value 后传入。
    control_overrides: dict = Field(default_factory=dict, description="采纳/人工改过的控制参数覆盖")


def _load_scene(scene_id: str) -> tuple[list, dict, dict]:
    """加载场景包的 requirements / control_params / datasets。"""
    scene_dir = _SCENES_DIR / scene_id
    reqs = json.loads((scene_dir / "test-requirements.json").read_text(encoding="utf-8"))
    controls = json.loads((scene_dir / "control-parameters.json").read_text(encoding="utf-8"))
    datasets = json.loads((scene_dir / "datasets.json").read_text(encoding="utf-8"))
    # parameters[] → {key: value}
    param_map = {p["key"]: p.get("value") for p in controls.get("parameters", [])}
    return reqs.get("requirements", []), param_map, datasets


@router.post("/evaluate")
async def evaluate(
    body: EvaluateRequest,
    _: User = Depends(get_current_user),  # 门禁
):
    """对场景包全部判据求值。"""
    requirements, control_params, datasets = _load_scene(body.scene_id)

    # 采纳/人工改过的控制参数覆盖场景包原值（改了参数，判定结论要随之变）。
    # control_overrides 的 key 是场景包参数 key（前端已折算好），直接 update 覆盖。
    if body.control_overrides:
        control_params.update(body.control_overrides)

    # 实测量：显式传入优先；未传用 package_stats 默认
    measures = dict(body.measures) if body.measures else package_stats_measures(datasets)

    results = evaluate_all(requirements, measures, control_params)

    # 汇总：pass / fail / missing / manual 计数
    summary = {
        "pass": sum(1 for r in results if r["state"] == "pass"),
        "fail": sum(1 for r in results if r["state"] == "fail"),
        "missing": sum(1 for r in results if r["state"] == "missing"),
        "manual": sum(1 for r in results if r["state"] == "manual"),
        # 本台架不适用（2026-10-08）：单列计数，绝不并入 pass/missing。
        # 「测不了」与「没采到」对决策的含义不同，混在一起就是误导。
        "not_applicable": sum(1 for r in results if r["state"] == "not_applicable"),
    }

    # ⚠️ 必须走 success_response 包装（2026-10-08 修）。
    #
    # 成因：本路由原先直接返回裸 payload（{scene_id, measures, summary, results}），
    # 而前端 `flow-run/api.ts` 的统一 `call()` 只认 `{success, code, message, data}`
    # 这套包装 —— 判 `body.success` 为 undefined 即抛 `HTTP 200`。于是每次跑完一轮：
    #   POST /api/evaluate 200 → 前端 outer catch → 退回前端预览（authState='fallback'）
    #   → persistRun 一次都没跑 → 判定表没落库 → confirmFlow('run') 也没调
    #   → 顶栏「启动测试及结果分析」那一格永远点不亮（真实台架跑完 45s 实测栽过）。
    # 其余所有路由（/api/runs、/api/fan-tests …）都走 success_response，
    # 只有这里漏了，属于**响应包装不一致**，不是前端问题，故在后端修。
    return success_response(
        data={
            "scene_id": body.scene_id,
            "measures": measures,
            "summary": summary,
            "results": results,
        },
        message="判定完成",
    )
