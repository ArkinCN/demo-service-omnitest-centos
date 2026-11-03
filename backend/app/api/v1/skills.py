"""
内置 Skill API — 用户端清单下发 + 管理端 CRUD

user_router（/vibe-coding/skills）：CLI 用 vibe token 拉可用 skill 清单
（仅元数据，正文永不出现在此路由——正文只经 skill_expansion 在 messages
代理转发时注入上游）。

admin_router（/skills/admin）：管理后台的上传/版本/分类/项目规则管理。
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from structlog import get_logger

from app.api.deps import get_db, require_admin
from app.core.exceptions import UnauthorizedException
from app.core.security import decode_token
from app.models.skill import (
    ProjectSkillRule,
    Skill,
    SkillCategory,
    SkillExpansionLog,
    SkillResourceFile,
    SkillVersion,
)
from app.models.user import User
from app.schemas.common import success_response, error_response
from app.services.skill_service import SkillService, estimate_tokens
from app.services.vibe_coding_service import VibeCodingService
from app.services.vibe_token_guard import verify_vibe_token

logger = get_logger(__name__)

user_router = APIRouter(prefix="/vibe-coding/skills", tags=["Skills"])
admin_router = APIRouter(prefix="/skills/admin", tags=["Skills Admin"])


# ============================================================================
# 用户端：清单下发（vibe token 鉴权，与 knowledge-search 同范式）
# ============================================================================

@user_router.get("/available", summary="当前用户可用的内置 skill 清单（无正文）")
def list_available_skills(
    request: Request,
    project_type: Optional[str] = None,
    x_api_key: str = Header(..., description="JWT token as Anthropic API key"),
    x_device_fp: Optional[str] = Header(
        None, alias="x-device-fp",
        description="设备指纹(sha-256 hex),与 token 内 dfp claim 绑定校验",
    ),
    session: Session = Depends(get_db),
):
    # 1. 验 JWT（vibe token）
    try:
        payload = decode_token(x_api_key)
    except Exception:
        return error_response(message="Invalid or expired token, please restart terminal", code=401)
    if payload.get("type") != "access":
        return error_response(message="Invalid token type", code=401)
    user_id = payload.get("user_id")
    if not user_id:
        return error_response(message="Invalid token payload", code=401)
    try:
        payload = verify_vibe_token(payload, session, x_device_fp)
    except UnauthorizedException as exc:
        return error_response(message=str(exc), code=401)

    # 2. vibe-coding 访问权限（仅功能开关 + 可见性，不做额度门禁——拉清单是
    #    只读操作，零余额用户也应能看到有哪些内置 skill，真正计费发生在对话轮）
    user_group_ids = VibeCodingService.get_user_group_ids(session, user_id)
    perm = VibeCodingService.check_access(session, user_id, user_group_ids)
    if not perm["allowed"]:
        return error_response(message=perm["reason"], code=403)

    user_row = session.get(User, user_id)
    skills = SkillService.get_available_skills(
        session,
        user_id=user_id,
        user_group_ids=user_group_ids,
        user_email=(user_row.email if user_row else "") or "",
        project_type=project_type,
    )
    return success_response(data={"skills": skills})


# ============================================================================
# 管理端：skill CRUD
# ============================================================================

class SkillResourcePayload(BaseModel):
    path: str
    content: str


class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    category_id: Optional[int] = None
    visibility: str = Field(default="ALL", pattern="^(ALL|INTERNAL|SPECIFIED)$")
    allowed_group_ids: Optional[list[int]] = None
    allowed_user_ids: Optional[list[int]] = None
    sort_order: int = 0
    version: str
    content: str
    changelog: str = ""
    resources: Optional[list[SkillResourcePayload]] = None


class SkillUpdateRequest(BaseModel):
    description: Optional[str] = None
    category_id: Optional[int] = None
    clear_category: Optional[bool] = None
    is_active: Optional[bool] = None
    revoked: Optional[bool] = None
    leak_scan_exempt: Optional[bool] = None
    sort_order: Optional[int] = None
    visibility: Optional[str] = Field(default=None, pattern="^(ALL|INTERNAL|SPECIFIED)$")
    allowed_group_ids: Optional[list[int]] = None
    allowed_user_ids: Optional[list[int]] = None


class SkillVersionCreateRequest(BaseModel):
    version: str
    content: str
    changelog: str = ""
    set_current: bool = True
    resources: Optional[list[SkillResourcePayload]] = None


def _serialize_skill(session: Session, skill: Skill, categories: dict) -> dict:
    import json as _json
    current = SkillService.get_current_version(session, skill.id)
    version_count = len(session.exec(
        select(SkillVersion.id).where(SkillVersion.skill_id == skill.id)
    ).all())
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "category_id": skill.category_id,
        "category": categories.get(skill.category_id, "") if skill.category_id else "",
        "is_active": skill.is_active,
        "revoked": skill.revoked,
        "leak_scan_exempt": skill.leak_scan_exempt,
        "sort_order": skill.sort_order,
        "visibility": skill.visibility,
        "allowed_group_ids": skill.allowed_group_ids
        if isinstance(skill.allowed_group_ids, list)
        else _json.loads(skill.allowed_group_ids or "[]"),
        "allowed_user_ids": skill.allowed_user_ids
        if isinstance(skill.allowed_user_ids, list)
        else _json.loads(skill.allowed_user_ids or "[]"),
        "current_version": current.version if current else None,
        "current_version_id": current.id if current else None,
        "current_version_code": current.version_code if current else None,
        "version_count": version_count,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


def _serialize_version(session: Session, v: SkillVersion, with_content: bool) -> dict:
    resources = SkillService.list_resources(session, v.id)
    data = {
        "id": v.id,
        "skill_id": v.skill_id,
        "version": v.version,
        "version_code": v.version_code,
        "changelog": v.changelog,
        "is_current": v.is_current,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "content_chars": len(v.content or ""),
        "body_tokens": estimate_tokens(v.content or ""),
        "resource_count": len(resources),
    }
    if with_content:
        data["content"] = v.content
        data["resources"] = [
            {"path": r.path, "content": r.content, "body_tokens": r.body_tokens}
            for r in resources
        ]
    else:
        data["resources"] = [
            {"path": r.path, "content_chars": len(r.content or ""), "body_tokens": r.body_tokens}
            for r in resources
        ]
    return data


@admin_router.get("", summary="skill 列表（管理端）")
def admin_list_skills(
    keyword: Optional[str] = None,
    category_id: Optional[int] = None,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(Skill).order_by(Skill.sort_order, Skill.name)
    if category_id is not None:
        query = query.where(Skill.category_id == category_id)
    skills = session.exec(query).all()
    if keyword:
        kw = keyword.strip().lower()
        skills = [
            s for s in skills
            if kw in s.name.lower() or kw in (s.description or "").lower()
        ]
    categories = {c.id: c.name for c in session.exec(select(SkillCategory)).all()}
    return success_response(data=[_serialize_skill(session, s, categories) for s in skills])


@admin_router.post("", summary="创建 skill（首版随建）")
def admin_create_skill(
    body: SkillCreateRequest,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        skill = SkillService.create_skill(
            session,
            name=body.name,
            description=body.description,
            category_id=body.category_id,
            visibility=body.visibility,
            allowed_group_ids=body.allowed_group_ids,
            allowed_user_ids=body.allowed_user_ids,
            sort_order=body.sort_order,
            version=body.version,
            content=body.content,
            changelog=body.changelog,
            resources=[r.model_dump() for r in body.resources] if body.resources else None,
            created_by=admin.id,
        )
    except ValueError as e:
        return error_response(message=str(e))
    categories = {c.id: c.name for c in session.exec(select(SkillCategory)).all()}
    logger.info("skill created", skill=skill.name, admin=admin.username)
    return success_response(
        message=f"已创建 skill: {skill.name}",
        data=_serialize_skill(session, skill, categories),
    )


@admin_router.put("/{skill_id}", summary="更新 skill 元数据/上下架/revoke")
def admin_update_skill(
    skill_id: int,
    body: SkillUpdateRequest,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    import json as _json
    from datetime import datetime, timezone

    skill = session.get(Skill, skill_id)
    if not skill:
        return error_response(message="skill 不存在", code=404)
    if body.description is not None:
        skill.description = body.description.strip()
    if body.clear_category:
        skill.category_id = None
    elif body.category_id is not None:
        skill.category_id = body.category_id
    if body.is_active is not None:
        skill.is_active = body.is_active
    if body.revoked is not None:
        skill.revoked = body.revoked
    if body.leak_scan_exempt is not None:
        skill.leak_scan_exempt = body.leak_scan_exempt
    if body.sort_order is not None:
        skill.sort_order = body.sort_order
    if body.visibility is not None:
        skill.visibility = body.visibility
    if body.allowed_group_ids is not None:
        skill.allowed_group_ids = _json.dumps(body.allowed_group_ids)
    if body.allowed_user_ids is not None:
        skill.allowed_user_ids = _json.dumps(body.allowed_user_ids)
    skill.updated_at = datetime.now(timezone.utc)
    session.add(skill)
    session.commit()
    session.refresh(skill)
    categories = {c.id: c.name for c in session.exec(select(SkillCategory)).all()}
    logger.info("skill updated", skill=skill.name, admin=admin.username)
    return success_response(
        message=f"已更新 skill: {skill.name}",
        data=_serialize_skill(session, skill, categories),
    )


@admin_router.get("/{skill_id}/versions", summary="skill 版本列表")
def admin_list_versions(
    skill_id: int,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    skill = session.get(Skill, skill_id)
    if not skill:
        return error_response(message="skill 不存在", code=404)
    versions = session.exec(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.version_code.desc())  # type: ignore[union-attr]
    ).all()
    return success_response(
        data=[_serialize_version(session, v, with_content=False) for v in versions]
    )


@admin_router.get("/{skill_id}/versions/{version_id}", summary="版本详情（含正文与资源）")
def admin_get_version(
    skill_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    version = session.get(SkillVersion, version_id)
    if not version or version.skill_id != skill_id:
        return error_response(message="版本不存在", code=404)
    return success_response(data=_serialize_version(session, version, with_content=True))


@admin_router.post("/{skill_id}/versions", summary="新增版本")
def admin_add_version(
    skill_id: int,
    body: SkillVersionCreateRequest,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    skill = session.get(Skill, skill_id)
    if not skill:
        return error_response(message="skill 不存在", code=404)
    try:
        version = SkillService.add_version(
            session,
            skill=skill,
            version=body.version,
            content=body.content,
            changelog=body.changelog,
            resources=[r.model_dump() for r in body.resources] if body.resources else None,
            set_current=body.set_current,
            created_by=admin.id,
        )
    except ValueError as e:
        return error_response(message=str(e))
    logger.info("skill version added", skill=skill.name, version=version.version, admin=admin.username)
    return success_response(
        message=f"已新增版本 {version.version}",
        data=_serialize_version(session, version, with_content=False),
    )


@admin_router.post("/{skill_id}/versions/{version_id}/set-current", summary="切换当前版本")
def admin_set_current_version(
    skill_id: int,
    version_id: int,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    skill = session.get(Skill, skill_id)
    if not skill:
        return error_response(message="skill 不存在", code=404)
    try:
        version = SkillService.set_current_version(session, skill_id, version_id)
    except ValueError as e:
        return error_response(message=str(e))
    logger.info("skill current version switched", skill=skill.name, version=version.version, admin=admin.username)
    return success_response(
        message=f"当前版本已切换为 {version.version}",
        data=_serialize_version(session, version, with_content=False),
    )


@admin_router.post("/upload", summary="解析上传的 SKILL.md / skill 目录 zip（回显预填，不落库）")
async def admin_upload_skill(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    data = await file.read()
    try:
        parsed = SkillService.parse_upload(file.filename or "", data)
    except ValueError as e:
        return error_response(message=str(e))
    return success_response(data=parsed)


# ============================================================================
# 管理端：分类
# ============================================================================

class CategoryRequest(BaseModel):
    name: str
    description: str = ""
    sort_order: int = 0


@admin_router.get("/categories", summary="分类列表")
def admin_list_categories(
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    categories = session.exec(
        select(SkillCategory).order_by(SkillCategory.sort_order, SkillCategory.name)
    ).all()
    return success_response(data=[
        {
            "id": c.id, "name": c.name, "description": c.description,
            "sort_order": c.sort_order,
            "skill_count": len(session.exec(
                select(Skill.id).where(Skill.category_id == c.id)
            ).all()),
        }
        for c in categories
    ])


@admin_router.post("/categories", summary="创建分类")
def admin_create_category(
    body: CategoryRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    name = body.name.strip()
    if not name:
        return error_response(message="分类名不能为空")
    if session.exec(select(SkillCategory).where(SkillCategory.name == name)).first():
        return error_response(message=f"分类已存在: {name}")
    category = SkillCategory(name=name, description=body.description, sort_order=body.sort_order)
    session.add(category)
    session.commit()
    session.refresh(category)
    return success_response(message=f"已创建分类: {name}", data={"id": category.id})


@admin_router.put("/categories/{category_id}", summary="更新分类")
def admin_update_category(
    category_id: int,
    body: CategoryRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    from datetime import datetime, timezone

    category = session.get(SkillCategory, category_id)
    if not category:
        return error_response(message="分类不存在", code=404)
    category.name = body.name.strip() or category.name
    category.description = body.description
    category.sort_order = body.sort_order
    category.updated_at = datetime.now(timezone.utc)
    session.add(category)
    session.commit()
    return success_response(message="已更新分类")


@admin_router.delete("/categories/{category_id}", summary="删除分类")
def admin_delete_category(
    category_id: int,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    category = session.get(SkillCategory, category_id)
    if not category:
        return error_response(message="分类不存在", code=404)
    in_use = session.exec(
        select(Skill.id).where(Skill.category_id == category_id)
    ).first()
    if in_use is not None:
        return error_response(message="仍有 skill 挂在该分类下，请先移除")
    rule_in_use = session.exec(
        select(ProjectSkillRule.id).where(ProjectSkillRule.category_id == category_id)
    ).first()
    if rule_in_use is not None:
        return error_response(message="仍有项目规则引用该分类，请先删除规则")
    session.delete(category)
    session.commit()
    return success_response(message="已删除分类")


# ============================================================================
# 管理端：项目类型规则（预留接口）
# ============================================================================

class ProjectRuleRequest(BaseModel):
    project_type: str
    skill_id: Optional[int] = None
    category_id: Optional[int] = None
    mode: str = Field(default="include", pattern="^(include|exclude)$")


@admin_router.get("/project-rules", summary="项目类型规则列表")
def admin_list_project_rules(
    project_type: Optional[str] = None,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(ProjectSkillRule).order_by(
        ProjectSkillRule.project_type, ProjectSkillRule.id
    )
    if project_type:
        query = query.where(ProjectSkillRule.project_type == project_type.strip())
    rules = session.exec(query).all()
    skills = {s.id: s.name for s in session.exec(select(Skill)).all()}
    categories = {c.id: c.name for c in session.exec(select(SkillCategory)).all()}
    return success_response(data=[
        {
            "id": r.id,
            "project_type": r.project_type,
            "skill_id": r.skill_id,
            "skill": skills.get(r.skill_id, "") if r.skill_id else "",
            "category_id": r.category_id,
            "category": categories.get(r.category_id, "") if r.category_id else "",
            "mode": r.mode,
            "is_active": r.is_active,
        }
        for r in rules
    ])


@admin_router.post("/project-rules", summary="创建项目类型规则")
def admin_create_project_rule(
    body: ProjectRuleRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    ptype = body.project_type.strip()
    if not ptype:
        return error_response(message="project_type 不能为空")
    if (body.skill_id is None) == (body.category_id is None):
        return error_response(message="skill_id 与 category_id 必须二选一")
    rule = ProjectSkillRule(
        project_type=ptype,
        skill_id=body.skill_id,
        category_id=body.category_id,
        mode=body.mode,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return success_response(message="已创建规则", data={"id": rule.id})


@admin_router.delete("/project-rules/{rule_id}", summary="删除项目类型规则")
def admin_delete_project_rule(
    rule_id: int,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    rule = session.get(ProjectSkillRule, rule_id)
    if not rule:
        return error_response(message="规则不存在", code=404)
    session.delete(rule)
    session.commit()
    return success_response(message="已删除规则")


# ============================================================================
# 管理端：展开审计查询
# ============================================================================

@admin_router.get("/expansion-logs", summary="skill 展开审计日志")
def admin_list_expansion_logs(
    skill_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: int = 200,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(SkillExpansionLog).order_by(SkillExpansionLog.id.desc())  # type: ignore[union-attr]
    if skill_id is not None:
        query = query.where(SkillExpansionLog.skill_id == skill_id)
    if user_id is not None:
        query = query.where(SkillExpansionLog.user_id == user_id)
    logs = session.exec(query.limit(max(1, min(limit, 1000)))).all()
    skills = {s.id: s.name for s in session.exec(select(Skill)).all()}
    return success_response(data=[
        {
            "id": row.id,
            "user_id": row.user_id,
            "skill_id": row.skill_id,
            "skill": skills.get(row.skill_id, ""),
            "version_code": row.version_code,
            "resource_path": row.resource_path,
            "tool_use_id": row.tool_use_id,
            "request_id": row.request_id,
            "agent_role": row.agent_role,
            "protocol": row.protocol,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in logs
    ])
