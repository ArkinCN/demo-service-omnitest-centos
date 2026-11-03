"""
内置 Skill 业务服务 — 清单查询 / 版本内容解析 / 上传解析 / 管理 CRUD

清单端点只下发元数据（name/description/category/version_code），正文永不进清单；
正文只在占位符展开（skill_expansion.py）时按 (name, version_code) 查询。
"""
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.core.config import settings
from app.models.skill import (
    ProjectSkillRule,
    Skill,
    SkillCategory,
    SkillResourceFile,
    SkillVersion,
)
from app.models.app_version import AppVersion
from app.services.permission import check_entity_permission

# 与 CLI 侧占位符 regex 的捕获组保持一致（接口契约）
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RESOURCE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")

# 允许入库的资源文件后缀（v1 仅文本，可执行/二进制拒收）
TEXT_RESOURCE_SUFFIXES = (
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".csv", ".xml", ".html", ".css", ".svg",
)


def estimate_tokens(text: str) -> int:
    """粗略 token 估值（清单里给客户端做上下文估算用，不参与计费）。"""
    if not text:
        return 0
    return max(1, len(text) // 3)


def normalize_resource_path(path: str) -> Optional[str]:
    """资源路径规范化；非法返回 None。

    规则：反斜杠归一为 /、去前导 ./ 与 /、折叠重复 /；拒绝 ``..`` 段与
    契约字符集之外的字符。展开侧与上传侧共用，保证同一路径两边算出同一形态。
    """
    if not path:
        return None
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    p = re.sub(r"/{2,}", "/", p)
    if not p or not RESOURCE_PATH_RE.match(p):
        return None
    if any(seg in ("..", "", ".") for seg in p.split("/")):
        return None
    return p


class SkillService:
    """静态方法集合（仿 VibeCodingService / UpdateService 风格）"""

    # ── 用户端：清单 ──

    @staticmethod
    def get_available_skills(
        session: Session,
        user_id: int,
        user_group_ids: list[int],
        user_email: str = "",
        project_type: Optional[str] = None,
    ) -> list[dict]:
        """当前用户可见的内置 skill 清单（仅元数据，无正文）。"""
        skills = session.exec(
            select(Skill)
            .where(Skill.is_active == True, Skill.revoked == False)  # noqa: E712
            .order_by(Skill.sort_order, Skill.name)
        ).all()
        skills = [
            s for s in skills
            if check_entity_permission(s, user_id, user_group_ids, user_email)
        ]
        skills = SkillService._apply_project_rules(session, skills, project_type)
        if not skills:
            return []

        categories = {
            c.id: c.name for c in session.exec(select(SkillCategory)).all()
        }
        manifest: list[dict] = []
        for s in skills:
            current = SkillService.get_current_version(session, s.id)
            if current is None:
                continue  # 无已发布版本的 skill 不下发
            manifest.append({
                "name": s.name,
                "description": s.description,
                "category": categories.get(s.category_id, "") if s.category_id else "",
                "version": current.version,
                "version_code": current.version_code,
                "body_tokens": estimate_tokens(current.content),
            })
        return manifest

    @staticmethod
    def _apply_project_rules(
        session: Session, skills: list[Skill], project_type: Optional[str]
    ) -> list[Skill]:
        """项目类型规则过滤（预留接口）：无规则=不过滤。"""
        ptype = (project_type or "").strip()
        if not ptype or not skills:
            return skills
        rules = session.exec(
            select(ProjectSkillRule).where(
                ProjectSkillRule.project_type == ptype,
                ProjectSkillRule.is_active == True,  # noqa: E712
            )
        ).all()
        if not rules:
            return skills

        def matches(rule: ProjectSkillRule, skill: Skill) -> bool:
            if rule.skill_id is not None:
                return rule.skill_id == skill.id
            if rule.category_id is not None:
                return rule.category_id == skill.category_id
            return False

        includes = [r for r in rules if r.mode == "include"]
        excludes = [r for r in rules if r.mode == "exclude"]
        result = skills
        if includes:
            result = [s for s in result if any(matches(r, s) for r in includes)]
        if excludes:
            result = [s for s in result if not any(matches(r, s) for r in excludes)]
        return result

    # ── 展开侧：内容解析 ──

    @staticmethod
    def get_skill_by_name(session: Session, name: str) -> Optional[Skill]:
        return session.exec(select(Skill).where(Skill.name == name)).first()

    @staticmethod
    def get_current_version(session: Session, skill_id: int) -> Optional[SkillVersion]:
        return session.exec(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.is_current == True,  # noqa: E712
            )
        ).first()

    @staticmethod
    def get_version_by_code(
        session: Session, skill_id: int, version_code: int
    ) -> Optional[SkillVersion]:
        return session.exec(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.version_code == version_code,
            )
        ).first()

    @staticmethod
    def list_resources(session: Session, skill_version_id: int) -> list[SkillResourceFile]:
        """按 path 排序（展开时生成资源清单指引，顺序必须确定）。"""
        return session.exec(
            select(SkillResourceFile)
            .where(SkillResourceFile.skill_version_id == skill_version_id)
            .order_by(SkillResourceFile.path)
        ).all()

    @staticmethod
    def get_resource(
        session: Session, skill_version_id: int, path: str
    ) -> Optional[SkillResourceFile]:
        return session.exec(
            select(SkillResourceFile).where(
                SkillResourceFile.skill_version_id == skill_version_id,
                SkillResourceFile.path == path,
            )
        ).first()

    # ── 管理端：CRUD ──

    @staticmethod
    def create_skill(
        session: Session,
        *,
        name: str,
        description: str,
        category_id: Optional[int] = None,
        visibility: str = "ALL",
        allowed_group_ids: Optional[list] = None,
        allowed_user_ids: Optional[list] = None,
        sort_order: int = 0,
        version: str,
        content: str,
        changelog: str = "",
        resources: Optional[list[dict]] = None,
        created_by: Optional[int] = None,
    ) -> Skill:
        name = name.strip().lower()
        if not SKILL_NAME_RE.match(name):
            raise ValueError("skill 名不合法（^[a-z0-9][a-z0-9_-]{0,63}$）")
        if SkillService.get_skill_by_name(session, name):
            raise ValueError(f"skill 已存在: {name}")
        skill = Skill(
            name=name,
            description=description.strip(),
            category_id=category_id,
            visibility=visibility,
            allowed_group_ids=json.dumps(allowed_group_ids or []),
            allowed_user_ids=json.dumps(allowed_user_ids or []),
            sort_order=sort_order,
        )
        session.add(skill)
        session.commit()
        session.refresh(skill)
        SkillService.add_version(
            session,
            skill=skill,
            version=version,
            content=content,
            changelog=changelog,
            resources=resources,
            set_current=True,
            created_by=created_by,
        )
        return skill

    @staticmethod
    def add_version(
        session: Session,
        *,
        skill: Skill,
        version: str,
        content: str,
        changelog: str = "",
        resources: Optional[list[dict]] = None,
        set_current: bool = True,
        created_by: Optional[int] = None,
    ) -> SkillVersion:
        version = version.strip()
        code = AppVersion.parse_version_to_code(version)
        if code <= 0:
            raise ValueError(f"版本号不合法: {version}")
        if not (content or "").strip():
            raise ValueError("skill 正文不能为空")
        if SkillService.get_version_by_code(session, skill.id, code):
            raise ValueError(f"版本已存在: {version}（version_code={code}）")

        row = SkillVersion(
            skill_id=skill.id,
            version=version,
            version_code=code,
            content=content,
            changelog=changelog,
            created_by=created_by,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        for res in resources or []:
            path = normalize_resource_path(res.get("path", ""))
            if path is None:
                raise ValueError(f"资源路径不合法: {res.get('path')}")
            session.add(SkillResourceFile(
                skill_version_id=row.id,
                path=path,
                content=res.get("content", ""),
                body_tokens=estimate_tokens(res.get("content", "")),
            ))
        session.commit()

        if set_current:
            SkillService.set_current_version(session, skill.id, row.id)
        return row

    @staticmethod
    def set_current_version(session: Session, skill_id: int, version_id: int) -> SkillVersion:
        target = session.get(SkillVersion, version_id)
        if not target or target.skill_id != skill_id:
            raise ValueError("版本不存在")
        for v in session.exec(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.is_current == True,  # noqa: E712
            )
        ).all():
            v.is_current = False
            session.add(v)
        target.is_current = True
        session.add(target)
        skill = session.get(Skill, skill_id)
        if skill:
            skill.updated_at = datetime.now(timezone.utc)
            session.add(skill)
        session.commit()
        session.refresh(target)
        return target

    # ── 上传解析（不落库，仅解析回显供管理端预填）──

    @staticmethod
    def parse_upload(filename: str, data: bytes) -> dict:
        """解析上传的单 .md 或 skill 目录 zip 包。

        返回 {name, description, content, resources: [{path, content}]}；
        name/description 从 SKILL.md frontmatter 提取（与 CLI 手写解析同规则），
        解析失败留空由管理端手填。
        """
        lower = (filename or "").lower()
        if lower.endswith(".zip"):
            return SkillService._parse_zip_upload(data)
        if lower.endswith((".md", ".markdown")):
            content = SkillService._decode_text(filename or "SKILL.md", data)
            meta = SkillService._parse_frontmatter(content)
            return {**meta, "content": content, "resources": []}
        raise ValueError("仅支持 .md 或 .zip（skill 目录打包）")

    @staticmethod
    def _parse_zip_upload(data: bytes) -> dict:
        if len(data) > settings.SKILL_UPLOAD_MAX_TOTAL_BYTES:
            raise ValueError("zip 包超出大小限制")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ValueError(f"zip 包无法解析: {e}") from e

        entries: list[tuple[str, bytes]] = []
        total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.file_size > settings.SKILL_UPLOAD_MAX_FILE_BYTES:
                raise ValueError(f"文件超出大小限制: {info.filename}")
            total += info.file_size
            if total > settings.SKILL_UPLOAD_MAX_TOTAL_BYTES:
                raise ValueError("zip 包内容总量超出限制")
            entries.append((info.filename, zf.read(info)))
        if not entries:
            raise ValueError("zip 包为空")

        # 找 SKILL.md：允许根目录或统一的单层顶目录（目录打包的常见形态）
        skill_md = next(
            (n for n, _ in entries if n.replace("\\", "/").lower() == "skill.md"), None
        )
        prefix = ""
        if skill_md is None:
            tops = {n.replace("\\", "/").split("/", 1)[0] for n, _ in entries}
            if len(tops) == 1:
                candidate = f"{next(iter(tops))}/SKILL.md"
                skill_md = next(
                    (n for n, _ in entries
                     if n.replace("\\", "/").lower() == candidate.lower()),
                    None,
                )
                if skill_md is not None:
                    prefix = f"{next(iter(tops))}/"
        if skill_md is None:
            raise ValueError("zip 包中未找到 SKILL.md")

        content = ""
        resources: list[dict] = []
        for raw_name, raw in entries:
            norm_name = raw_name.replace("\\", "/")
            if norm_name == skill_md.replace("\\", "/"):
                content = SkillService._decode_text(raw_name, raw)
                continue
            rel = norm_name[len(prefix):] if prefix and norm_name.startswith(prefix) else norm_name
            path = normalize_resource_path(rel)
            if path is None:
                raise ValueError(f"资源路径不合法: {raw_name}")
            if not path.lower().endswith(TEXT_RESOURCE_SUFFIXES):
                raise ValueError(f"仅支持文本资源（{path}）；脚本/二进制不支持云端下发")
            resources.append({
                "path": path,
                "content": SkillService._decode_text(raw_name, raw),
            })
        resources.sort(key=lambda r: r["path"])
        meta = SkillService._parse_frontmatter(content)
        return {**meta, "content": content, "resources": resources}

    @staticmethod
    def _decode_text(name: str, raw: bytes) -> str:
        if b"\x00" in raw:
            raise ValueError(f"检测到二进制文件: {name}（v1 仅支持文本资源）")
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise ValueError(f"文件不是合法 UTF-8 文本: {name}") from e

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """与 CLI parse_skill_frontmatter 同规则的宽松解析：首行 ---，逐行取
        name:/description:，再遇 --- 结束。"""
        name, description = "", ""
        lines = content.splitlines()
        if lines and lines[0].strip() == "---":
            for line in lines[1:]:
                stripped = line.strip()
                if stripped == "---":
                    break
                if stripped.startswith("name:") and not name:
                    name = stripped[len("name:"):].strip().strip("'\"")
                elif stripped.startswith("description:") and not description:
                    description = stripped[len("description:"):].strip().strip("'\"")
        return {"name": name.lower(), "description": description}
