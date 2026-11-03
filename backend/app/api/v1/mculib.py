"""
MCU 头文件版本查询路由（群组ID版本）
"""
import re
from typing import Optional, List, Dict

import httpx
from fastapi import APIRouter, Depends, Query

from app.api.deps import verify_token_only
from app.core.config import settings
from app.core.logger import logger

router = APIRouter(prefix="/mculib", tags=["MCU Library"])

# ============================================================
# 版本注释提取正则
# ============================================================
_VERSION_PATTERN = re.compile(
    r"Application\s+Department\s+Version\s+(V\d+\.\d+(?:\.\d+)?)"
)


def _extract_version(content: str) -> str:
    """
    从头文件内容中提取 Application Department Version 格式的版本号

    Returns:
        提取到的版本号字符串（如 "V1.2.3"），未找到时返回空字符串
    """
    match = _VERSION_PATTERN.search(content)
    if match:
        return match.group(1).strip()
    return ""


async def _get_group_projects(
    client: httpx.AsyncClient,
    gitlab_base: str,
    group_id: str,
    headers: Dict,
) -> List[Dict]:
    """
    获取 GitLab 群组内的所有项目（含子群组）

    Returns:
        项目信息字典列表，每项包含 id、name、path_with_namespace 等
    """
    projects = []
    page = 1

    while True:
        # 使用 include_subgroups=true 确保覆盖所有子群组中的项目
        url = (
            f"{gitlab_base}/api/v4/groups/{group_id}/projects"
            f"?include_subgroups=true&per_page=100&page={page}&simple=true"
        )
        logger.info(f"[mculib] 获取群组项目列表: 第{page}页")

        try:
            resp = await client.get(url, headers=headers)
        except Exception as e:
            logger.error(f"[mculib] 群组项目列表请求失败: {e}")
            break

        if not resp.is_success:
            logger.warning(f"[mculib] 群组API返回错误: {resp.status_code} - {resp.text[:200]}")
            break

        page_projects = resp.json()
        if not page_projects:
            break

        projects.extend(page_projects)
        logger.info(f"[mculib] 第{page}页获取到 {len(page_projects)} 个项目，累计 {len(projects)} 个")

        if len(page_projects) < 100:
            break  # 最后一页
        page += 1

    return projects


async def _find_mcu_file_in_project(
    client: httpx.AsyncClient,
    gitlab_base: str,
    project_id: int,
    headers: Dict,
    branch: str,
    target_filename: Optional[str],
) -> List[Dict]:
    """
    在单个项目中递归搜索 _MCU.h 文件并提取版本号

    Returns:
        匹配文件的信息列表，格式与 Rust VendorApiFileInfo 对应
    """
    result = []
    page = 1

    while True:
        tree_url = (
            f"{gitlab_base}/api/v4/projects/{project_id}"
            f"/repository/tree?recursive=true&per_page=100&page={page}&ref={branch}"
        )

        try:
            tree_resp = await client.get(tree_url, headers=headers)
        except Exception as e:
            logger.warning(f"[mculib] 项目{project_id}文件树请求失败: {e}")
            break

        if not tree_resp.is_success:
            # 404 说明该项目此分支不存在，正常跳过
            if tree_resp.status_code != 404:
                logger.warning(f"[mculib] 项目{project_id}文件树返回: {tree_resp.status_code}")
            break

        nodes = tree_resp.json()
        if not nodes:
            break

        for node in nodes:
            # 只处理文件类型（blob），跳过目录（tree）
            if node.get("type") != "blob":
                continue
            # 只处理 _MCU.h 结尾的文件
            if not node["name"].endswith("_MCU.h"):
                continue
            # 如果指定了目标文件名，进行大小写不敏感的精确匹配
            if target_filename and node["name"].lower() != target_filename.lower():
                continue

            # 获取文件原始内容以提取版本注释
            file_path_encoded = node["path"].replace("/", "%2F")
            raw_url = (
                f"{gitlab_base}/api/v4/projects/{project_id}"
                f"/repository/files/{file_path_encoded}/raw?ref={branch}"
            )

            version = ""
            try:
                raw_resp = await client.get(raw_url, headers=headers)
                if raw_resp.is_success:
                    version = _extract_version(raw_resp.text)
                else:
                    logger.warning(f"[mculib] 获取文件内容失败: {node['path']} -> {raw_resp.status_code}")
            except Exception as e:
                logger.warning(f"[mculib] 获取文件内容异常: {node['path']} -> {e}")

            result.append({
                "file": node["path"],
                "name": node["name"],
                # version 为空字符串时存 None，与 Rust Option<String> 对应
                "version": version if version else None,
            })
            logger.info(f"[mculib] 找到文件: {node['name']} -> Application Department Version: {version or '未找到'}")

        if len(nodes) < 100:
            break  # 最后一页
        page += 1

    return result


@router.get(
    "/versions",
    summary="查询 MCU 头文件 Application Department Version",
    description=(
        "通过 GitLab 群组ID（固定7390）遍历群组内项目，"
        "查找 _MCU.h 文件并提取 Application Department Version VX.X.X 格式版本号"
    ),
)
async def get_mculib_versions(
    filename: Optional[str] = Query(
        default=None,
        description="目标文件名（如 FU6832_MCU.h），指定后提前返回跳过其余项目",
    ),
    branch: str = Query(default="master", description="GitLab 仓库分支名"),
    _payload: dict = Depends(verify_token_only),
):
    """
    通过 GitLab 群组ID 查询 MCU 头文件 Application Department Version

    Returns:
        直接返回 dict，格式与 Rust VendorApiVersionsResponse 完全对应：
        {"branch": str, "total": int, "files": [{"file": str, "name": str, "version": str | null}]}
    """
    # 从配置读取 GitLab 连接参数（禁止硬编码）
    group_id = settings.GITLAB_MCULIB_GROUP_ID
    gitlab_base = settings.GITLAB_BASE_URL

    # 构建 GitLab 认证请求头
    request_headers: Dict = {}
    if settings.GITLAB_MCULIB_TOKEN:
        request_headers["PRIVATE-TOKEN"] = settings.GITLAB_MCULIB_TOKEN

    files_result: List[Dict] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 步骤1：获取群组内所有项目
        projects = await _get_group_projects(client, gitlab_base, group_id, request_headers)
        logger.info(f"[mculib] 群组 {group_id} 共 {len(projects)} 个项目，开始搜索 MCU 头文件")

        # 步骤2：在每个项目中搜索 _MCU.h 文件
        for project in projects:
            project_id = project["id"]
            project_name = project.get("name", str(project_id))

            mcu_files = await _find_mcu_file_in_project(
                client, gitlab_base, project_id, request_headers, branch, filename
            )

            if mcu_files:
                logger.info(f"[mculib] 项目 [{project_name}] 找到 {len(mcu_files)} 个匹配文件")
                files_result.extend(mcu_files)

            # 优化：指定了文件名且已找到结果时，提前结束遍历
            if filename and files_result:
                logger.info(f"[mculib] 已找到目标文件 {filename}，提前结束群组遍历")
                break

    logger.info(f"[mculib] 搜索完成，共找到 {len(files_result)} 个 MCU 头文件")

    # 直接返回 dict，格式与 Rust VendorApiVersionsResponse 完全对应
    # 注意：不使用 success_response 包装，保持与 Rust 反序列化结构一致
    return {
        "branch": branch,
        "total": len(files_result),
        "files": files_result,
    }
