"""知识库**文档**模型：上传原件的登记与五阶段转化状态（主文档 3.1，P3）。

与 kb_entry 的分工（两者都要，别混）：
  - KbDocument  —— 「一份上传的文件」。记录原件的存放路径、大小、哈希，
                   以及它在五阶段流水线上走到了哪一步。**一份文档产出若干条目**。
  - KbEntry     —— 「一条可检索的知识条目」。文档切片、经验都是条目。

五阶段（主文档 3.1）：识别 → 抽取 → 切片 → 结构化 → 索引，**串行、每阶段可单独重跑**。
阶段之间**只传文件与 JSON，不共享内存状态**——所以每个阶段把产物写到磁盘
（`kb_uploads_dir()/<doc_id>/<stage>.json`），重跑只需删掉该阶段产物再跑。

每份文档状态五值（主文档原文）：
  pending        待处理
  converting     转化中
  indexed        已入库
  failed         转化失败（**必须带失败阶段与原因**）
  needs_review   需人工校对（结构化置信度低于阈值时进此态）

⚠️ 刻意把内部状态与对外五值分开：
  内部用 `stage`（当前/最后完成的阶段，取值即五阶段名）记录进度，
  对外 `status` 只暴露上面五值。这样「推进到哪一步」与「这个词是给谁看的」
  不会互相污染——前端要的是五值，运维要的是阶段。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Text
from sqlmodel import Column, Field, SQLModel

# 五阶段，顺序即串行顺序。**顺序改不得**：串行意味着前一个没成后一个无从谈起。
KB_STAGES = ["recognize", "extract", "chunk", "struct", "index"]

# 阶段名 → 中文（对外文案与日志都用它，避免两处各写一遍）
STAGE_LABEL = {
    "recognize": "识别",
    "extract": "抽取",
    "chunk": "切片",
    "struct": "结构化",
    "index": "索引",
}

# 对外五值（主文档 3.1 原文，一个不多一个不少）
KB_STATUS = ["pending", "converting", "indexed", "failed", "needs_review"]

STATUS_LABEL = {
    "pending": "待处理",
    "converting": "转化中",
    "indexed": "已入库",
    "failed": "转化失败",
    "needs_review": "需人工校对",
}


class KbDocument(SQLModel, table=True):
    """一份上传到知识库的原件及其转化进度。"""

    __tablename__ = "kb_documents"

    id: Optional[int] = Field(default=None, primary_key=True)

    doc_id: str = Field(index=True, unique=True, description="稳定标识，也是产物目录名")
    title: str = Field(max_length=500, description="标题，默认取文件名（去扩展名）")
    file_name: str = Field(max_length=500, description="原文件名（含扩展名，供溯源）")
    file_path: str = Field(max_length=1000, description="原件落盘路径（相对项目根，便于换机器）")
    size_bytes: int = Field(default=0, description="原件字节数")
    sha256: str = Field(default="", max_length=64, description="原件哈希，供去重与完整性校验")
    file_type: str = Field(default="", max_length=20, description="扩展名（pdf/docx/doc/...）")

    # 三轴分类：上传时人可指定，缺省取当前场景包的三级归属
    owner_l1: str = Field(default="", max_length=100)
    owner_l2: str = Field(default="", max_length=100)
    owner_l3: str = Field(default="", max_length=100)
    usage: str = Field(
        default="process", max_length=20,
        description="用途三轴之一：spec / requirement / process（契约固定三类，不加第四类）",
    )
    # 自定义用途标签：比三轴更细的说法（如「启动测试」）。**不占轴线**——
    # 三轴决定筛选与计数，标签只是给人看的补充，所以单独存一列。
    usage_label: str = Field(default="", max_length=100, description="自定义用途标签，可空")

    status: str = Field(
        default="pending", max_length=20, index=True,
        description="对外五值：pending / converting / indexed / failed / needs_review",
    )
    stage: str = Field(
        default="", max_length=20,
        description="当前（或最后完成的）阶段，取值见 KB_STAGES；空表示还没开始",
    )
    # 失败必须说清「哪一步、为什么」——主文档 3.1 明写，不许只给一个 failed
    failed_stage: Optional[str] = Field(default=None, max_length=20)
    fail_reason: Optional[str] = Field(default=None, sa_column=Column(Text))

    # 各阶段产物的相对路径与摘要，形状：{"recognize": {...}, "chunk": {...}}
    artifacts: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # 条目数（索引阶段产出），0 表示还没到索引
    entry_count: int = Field(default=0)
    # 结构化阶段的平均置信度；低于阈值时状态进 needs_review
    confidence: Optional[float] = Field(default=None)

    uploaded_by: str = Field(default="", max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True
