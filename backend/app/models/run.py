"""
轮次产物模型（阶段 4.1 引入）。

主文档 4.1：轮次产物是「整个系统最大的一处空白」。本模块补 Run（运行主表，
含状态机）+ Artifact（七份产物，各带 schema 版本）。

artifact_kind 七值（一律用流程标识，不用序号）：
  config-snapshot     配置快照     init → tune/report
  requirement-baseline 需求基线    req  → tune/report
  run-artifact        轮次产物包    run  → tune/report
  verdict-table       判定结果表    run  → tune/report
  gap-list            未达标项清单  run  → tune
  param-change        参数改动版本  tune → run
  report-instance     报告实例      report → 归档回 init

三条贯穿规则：
1. 每份产物带 schema 并写死版本号（加字段发新版本）；
2. 引用另一份产物一律用标识不内嵌副本（唯一例外是配置快照里的参数值，自包含）；
3. 模型生成的内容必须带可区分人填与机器填的字段。

字段名一律下划线命名，与场景包 JSON 一致，不转驼峰。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

# 运行状态机（主文档 4.2）
RUN_STATUSES = (
    "draft", "queued", "prechecking", "awaiting_approval", "running",
    "collecting", "evaluating", "completed",
    "failed", "stop_requested", "stopped", "unknown",
)

# 七份产物的 schema 标识（写死版本号）
ARTIFACT_SCHEMAS = {
    "config-snapshot": "config-snapshot/v1",
    "requirement-baseline": "requirement-baseline/v1",
    "run-artifact": "run-artifact/v1",
    "verdict-table": "verdict-table/v1",
    "gap-list": "gap-list/v1",
    "param-change": "param-change/v1",
    "report-instance": "report-instance/v1",
}


class Run(SQLModel, table=True):
    """一轮测试运行。run_id 用 uuid hex 字符串，可拼进前端 URL。"""

    __tablename__ = "runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True, description="运行标识（uuid hex，可拼 URL）")
    user_id: int = Field(foreign_key="users.id", index=True, description="归属用户")
    scene_id: str = Field(default="", max_length=200, index=True, description="场景 ID")

    status: str = Field(default="draft", max_length=30, index=True, description="运行状态机状态")
    mode: str = Field(default="mock", max_length=20, description="数据来源模式：mock / real（诚实标记）")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间（运行中为 None）")

    class Config:
        from_attributes = True


# 合法的状态迁移（主文档 4.2 状态机）。draft 只能往前走，failed/unknown 是终态，
# stop_requested 只在 running/collecting/evaluating 期间可达。
_RUN_TRANSITIONS = {
    "draft": {"queued"},
    "queued": {"prechecking", "failed"},
    "prechecking": {"awaiting_approval", "failed"},
    "awaiting_approval": {"running", "failed"},
    "running": {"collecting", "stop_requested", "failed"},
    "collecting": {"evaluating", "stop_requested", "failed"},
    "evaluating": {"completed", "failed"},
    "stop_requested": {"stopped"},
    # completed / failed / stopped / unknown 为终态，不再迁移
}


def can_transition(from_status: str, to_status: str) -> bool:
    """判断状态迁移是否合法。"""
    return to_status in _RUN_TRANSITIONS.get(from_status, set())


class ActionRecord(SQLModel, table=True):
    """运行动作记录（主文档 4.2「先记动作和幂等键，再发命令」）。

    幂等：同一 (run_id, action_key) 只执行一次，重复请求返回同一 action_id。
    idempotency_key 持久化在库里（不是进程内存），服务重启后仍能对账。
    """

    __tablename__ = "run_actions"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, description="所属运行")
    action_id: str = Field(unique=True, index=True, description="动作标识（uuid）")
    action_key: str = Field(index=True, description="幂等键：调用方给的 Idempotency-Key 或派生键")
    action_type: str = Field(max_length=50, description="动作类型，如 start/stop/write_param")
    status: str = Field(default="requested", max_length=20, description="requested/approved/executing/succeeded/failed/unknown")
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON), description="动作参数快照")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True


class Artifact(SQLModel, table=True):
    """一份轮次产物。主键用 run_id + artifact_kind 定位，内容存 JSON 列。"""

    __tablename__ = "run_artifacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, description="所属运行 run_id")
    artifact_kind: str = Field(max_length=50, index=True, description="产物类型（七值之一）")
    # 注意：字段名用 schema_version 而非 schema，避免与 SQLModel 父类 schema 属性同名冲突
    schema_version: str = Field(max_length=50, description="schema 标识 + 版本号，如 config-snapshot/v1")
    content: dict = Field(default_factory=dict, sa_column=Column(JSON), description="产物正文（JSON）")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True
