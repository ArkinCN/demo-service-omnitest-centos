"""
安全联锁模型（阶段 4.3 引入）。

主文档 4.3：安全联锁是**独立数据结构，不是普通参数**——「能不能点启动」只查联锁，
不查普通参数。每条联锁项数据结构分三组：
- 标识：项名与类别（人员与现场 / 电气量上限 / 流程与基线）
- 判定：判定方式（人工确认 / 阈值监测 / 系统校验）与阈值单位
- 处置：触发动作、是否可临时豁免、豁免需谁批准

闸门 = 三件事同时成立（联锁全满足 + 预检全通过 + 现场安全总闸已开）。
急停独立于闸门：任何时刻可点，先发停机指令，再记录当时全部状态快照。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Interlock(SQLModel, table=True):
    """一条安全联锁项。判定与处置从场景包 safety-interlocks.json 导入。"""

    __tablename__ = "interlocks"

    id: Optional[int] = Field(default=None, primary_key=True)

    interlock_id: str = Field(index=True, description="联锁项标识（如 SI-PROC-01）")
    name: str = Field(max_length=200, description="联锁项名")
    category: str = Field(max_length=50, description="类别：人员与现场 / 电气量上限 / 流程与基线")
    scene_id: str = Field(default="", max_length=200, index=True, description="所属场景")

    # 判定组
    check_method: str = Field(max_length=50, description="人工确认 / 阈值监测 / 系统校验")
    threshold: Optional[float] = Field(default=None, description="阈值（阈值监测类）")
    unit: str = Field(default="", max_length=50, description="阈值单位")

    # 处置组
    trigger_action: str = Field(default="", max_length=50, description="触发动作：停机/降额/仅告警")
    waivable: bool = Field(default=False, description="是否可临时豁免")
    waiver_approver: str = Field(default="", max_length=200, description="豁免需谁批准")

    # 运行态
    satisfied: bool = Field(default=False, description="当前是否满足")
    confirmed_by: Optional[str] = Field(default=None, description="人工确认人（人工类联锁）")

    extra: dict = Field(default_factory=dict, sa_column=Column(JSON), description="扩展字段（快照）")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True


class GateState(SQLModel, table=True):
    """安全确认闸门状态（三件事：联锁全满足 + 预检全通过 + 现场安全总闸已开）。"""

    __tablename__ = "gate_states"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, description="所属运行")
    interlocks_ok: bool = Field(default=False, description="联锁项全部满足")
    precheck_ok: bool = Field(default=False, description="预检全部通过")
    master_switch_on: bool = Field(default=False, description="现场安全总闸已开（必须人当场点，本轮有效）")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True


class EstopRecord(SQLModel, table=True):
    """急停记录。急停独立于闸门，任何时刻可点；先发停机指令，再存当时状态快照。"""

    __tablename__ = "estop_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, description="所属运行")
    triggered_by: str = Field(default="", max_length=200, description="触发人")
    stop_command_sent: bool = Field(default=False, description="停机指令是否已发出（急停先发指令）")
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON), description="触发时全部状态快照")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True
