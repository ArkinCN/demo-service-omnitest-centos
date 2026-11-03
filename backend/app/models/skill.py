"""
内置 Skill 云端下发 — 数据模型

设计要点（与 CLI 占位符展开机制配套）：
- Skill 元数据与正文分离：正文在 SkillVersion，**行只增不删**——CLI 占位符
  pin 了 version_code（`[[MOTORDEBUG-SKILL::<name>::v<code>]]`），历史会话恢复时
  必须仍能解析旧版本，否则展开失败、prompt cache 前缀漂移。
- 下架分两档：is_active=False 仅从清单消失（进行中的会话仍可展开历史 pin），
  revoked=True 才硬止血（展开一律替换为兜底文案），用于内容事故。
- 可见性三件套（visibility/allowed_group_ids/allowed_user_ids）与
  AppVersion/ModelPricing 同构，直接复用 check_entity_permission。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, Column, UniqueConstraint
from sqlalchemy import Text, JSON
from sqlalchemy.dialects.mysql import MEDIUMTEXT

# MySQL TEXT 上限 64KB，skill 正文/资源可能超过；SQLite（测试）无 MEDIUMTEXT，
# 用 variant 让两边都能建表。
LONG_TEXT = Text().with_variant(MEDIUMTEXT(), "mysql")


class SkillCategory(SQLModel, table=True):
    """Skill 分类（管理后台维护，ProjectSkillRule 按分类开关技能）"""
    __tablename__ = "skill_categories"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, unique=True, index=True, nullable=False, description="分类名")
    description: str = Field(default="", max_length=500, description="分类说明")
    sort_order: int = Field(default=0, nullable=False, description="排序权重")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Skill(SQLModel, table=True):
    """内置 skill 元数据（正文见 SkillVersion）"""
    __tablename__ = "skills"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(
        max_length=64, unique=True, index=True, nullable=False,
        description="skill 名（小写规范化，^[a-z0-9][a-z0-9_-]{0,63}$，即 CLI 侧调用名）",
    )
    description: str = Field(
        default="", max_length=1000,
        description="一行描述（进入 CLI system prompt 的 <available_skills>，视为半公开）",
    )
    category_id: Optional[int] = Field(
        default=None, foreign_key="skill_categories.id", index=True, description="分类"
    )
    is_active: bool = Field(
        default=True, index=True, nullable=False,
        description="上架状态：False=清单不再下发，但历史占位符仍可展开",
    )
    revoked: bool = Field(
        default=False, nullable=False,
        description="硬止血：True=任何版本一律不展开（替换为兜底文案）",
    )
    leak_scan_exempt: bool = Field(
        default=False, nullable=False,
        description="输出泄漏扫描豁免（输出模板类 skill 的正文本来就该出现在回答里）",
    )
    sort_order: int = Field(default=0, nullable=False, description="排序权重")

    # 可见性门禁（与 AppVersion/ModelPricing 同构，复用 check_entity_permission）
    visibility: str = Field(
        default="ALL", max_length=20, index=True, nullable=False,
        description="可见性：ALL/INTERNAL/SPECIFIED",
    )
    allowed_group_ids: str = Field(default="[]", sa_column=Column(JSON), description="允许的分组ID数组")
    allowed_user_ids: str = Field(default="[]", sa_column=Column(JSON), description="允许的用户ID数组")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SkillVersion(SQLModel, table=True):
    """skill 正文版本。行只增不删；同一 skill 至多一行 is_current=True。"""
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_code", name="uq_skill_version_code"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    version: str = Field(max_length=50, nullable=False, description="版本号（如 1.2.0）")
    version_code: int = Field(
        nullable=False, description="版本码（parse_version_to_code，占位符 pin 的就是它）"
    )
    content: str = Field(
        sa_column=Column(LONG_TEXT, nullable=False),
        description="SKILL.md 正文（Markdown，含 frontmatter 与否均可，原样注入）",
    )
    changelog: str = Field(default="", max_length=2000, description="版本说明")
    is_current: bool = Field(default=False, index=True, nullable=False, description="是否当前版")
    created_by: Optional[int] = Field(default=None, foreign_key="users.id", description="上传者")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SkillResourceFile(SQLModel, table=True):
    """skill 附属资源（references/模板等文本文件），随版本不可变。"""
    __tablename__ = "skill_resource_files"
    __table_args__ = (
        UniqueConstraint("skill_version_id", "path", name="uq_skill_resource_path"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_version_id: int = Field(foreign_key="skill_versions.id", index=True, nullable=False)
    path: str = Field(
        max_length=200, nullable=False,
        description="规范化相对路径（[A-Za-z0-9._/-]，无 ..、无反斜杠、无前导 /）",
    )
    content: str = Field(
        sa_column=Column(LONG_TEXT, nullable=False), description="文本内容（v1 仅文本）"
    )
    body_tokens: int = Field(default=0, nullable=False, description="内容 token 估值（客户端估算辅助）")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectSkillRule(SQLModel, table=True):
    """项目类型 ↔ skill/分类 规则（预留接口：某类项目开启某类 skill）。

    语义：清单请求带 project_type 时——该类型存在任何 include 规则则收窄为
    include 命中集，再剔除 exclude 命中；无任何规则 = 不过滤。
    """
    __tablename__ = "project_skill_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_type: str = Field(max_length=64, index=True, nullable=False, description="项目类型标识")
    skill_id: Optional[int] = Field(
        default=None, foreign_key="skills.id", description="按单个 skill 匹配（与 category_id 二选一）"
    )
    category_id: Optional[int] = Field(
        default=None, foreign_key="skill_categories.id", description="按分类匹配（与 skill_id 二选一）"
    )
    mode: str = Field(
        default="include", max_length=10, nullable=False, description="include / exclude"
    )
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SkillExpansionLog(SQLModel, table=True):
    """占位符展开审计（M4 落库；建表先行）。

    注意：同一占位符随会话历史每轮重放都会再展开一次，审计/限频必须按
    distinct tool_use_id 计数而非展开次数。
    """
    __tablename__ = "skill_expansion_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, nullable=False)
    skill_id: int = Field(index=True, nullable=False)
    version_code: int = Field(nullable=False)
    resource_path: Optional[str] = Field(default=None, max_length=200, description="资源展开时的路径；正文展开为 NULL")
    tool_use_id: str = Field(max_length=128, index=True, nullable=False, description="配对 tool_use/call id（去重键）")
    request_id: Optional[str] = Field(default=None, max_length=64)
    agent_role: str = Field(default="main", max_length=20)
    protocol: str = Field(default="anthropic", max_length=30)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
