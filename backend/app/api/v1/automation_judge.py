"""
非致命报错判定清单接口（汇报模式 · 编号 1）。

`POST /api/automation-judge`：前端每轮终态后上报一份「逐条判定」，
本接口做入参校验 + 上限保护，然后写入 `logs/error_judge.log`（见
`app/core/judge_logger.py`），返回落盘文件路径与行数。

设计口径：
  · 判定逻辑在**前端纯模块** `web/src/features/automation/nonFatalJudge.ts` 里，
    后端**不重复判定**，只负责接收与落盘（口径唯一，避免两份实现漂移）；
  · 鉴权门禁与 evaluate.py 一致（Depends(get_current_user)）；判定不含个人敏感
    信息，但统一收口到「已登录」一层，与其余 /api/* 保持同一纪律；
  · 上限保护（防超长请求打爆日志文件）：
      entries ≤ 300 条、message ≤ 5000 字符、reason ≤ 500 字符（超出即 400 拒绝，
      由前端先行截断；后端这里做硬兜底，不静默丢弃）。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.judge_logger import record_judge_report
from app.models.user import User
from app.schemas.common import success_response

router = APIRouter(prefix="/api", tags=["Automation Judge"])

# 上限（与前端契约一致）
MAX_ENTRIES = 300
MAX_MESSAGE = 5000
MAX_REASON = 500


class JudgeEntry(BaseModel):
    seq: int = Field(..., description="日志序号（React key）")
    at_ms: int = Field(..., description="日志产生时刻（ms epoch）")
    level: str = Field(..., description="warn | error")
    stage_id: str = Field(default="", description="来源环节 id")
    stage_name: str | None = Field(default=None, description="环节名称")
    stage_final: str | None = Field(default=None, description="环节最终状态")
    verdict: str = Field(..., description="hide | keep")
    reason: str = Field(..., max_length=MAX_REASON, description="中文判定依据")
    message: str = Field(..., max_length=MAX_MESSAGE, description="报错原文")


class JudgeCounts(BaseModel):
    candidates: int = Field(default=0, ge=0)
    hide: int = Field(default=0, ge=0)
    keep: int = Field(default=0, ge=0)


class JudgeRequest(BaseModel):
    run_id: str = Field(..., description="轮次号")
    scene_id: str = Field(default="", description="场景 id")
    terminal_status: str = Field(..., description="completed | failed | stopped")
    uploaded_at: str = Field(default="", description="前端上报时刻（本地 ISO）")
    counts: JudgeCounts = Field(default_factory=JudgeCounts)
    entries: list[JudgeEntry] = Field(default_factory=list, max_length=MAX_ENTRIES)


@router.post("/automation-judge")
async def automation_judge(
    body: JudgeRequest,
    _: User = Depends(get_current_user),  # 门禁：与 evaluate 一致，登录即可
):
    """接收一轮的判定清单并落盘，返回文件路径与写入行数。"""
    result = record_judge_report(body.model_dump())
    return success_response(
        data=result,
        message=f"判定清单已落盘（候选 {body.counts.candidates} 条：可隐藏 {body.counts.hide} / 保留 {body.counts.keep}）",
    )
