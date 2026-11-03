"""部署 Webhook 端点"""
import re
import subprocess
from fastapi import APIRouter, Header, HTTPException
from structlog import get_logger

from app.core.config import settings
from app.schemas.webhook import DeployRequest, DeployResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# tag 格式校验：仅允许 v/V + 数字和点，防止命令注入
TAG_PATTERN = re.compile(r"^[vV][\d.]+$")


@router.post(
    "/deploy",
    response_model=DeployResponse,
    status_code=202,
    summary="触发前端部署",
    description="接收部署 Webhook，验证身份后异步执行部署脚本",
)
async def deploy(
    payload: DeployRequest,
    x_deploy_token: str = Header(..., alias="X-Deploy-Token", description="部署验证密钥"),
):
    """
    部署 Webhook 端点

    - 通过 X-Deploy-Token Header 验证调用者身份
    - 校验 tag 格式（仅允许 v + 数字和点，如 v1.0.0）
    - 使用 subprocess.Popen 异步执行部署脚本，不阻塞请求
    - 立即返回 202 Accepted 响应
    """

    # 验证部署密钥是否匹配
    if x_deploy_token != settings.DEPLOY_SECRET_TOKEN:
        logger.warning("deploy_webhook_auth_failed", project=payload.project)
        raise HTTPException(status_code=403, detail="无效的部署密钥")

    # 校验 tag 格式，防止命令注入
    if not TAG_PATTERN.match(payload.tag):
        logger.warning(
            "deploy_webhook_invalid_tag",
            tag=payload.tag,
            project=payload.project,
        )
        raise HTTPException(
            status_code=422,
            detail="tag 格式不合法，仅允许 v 开头 + 数字和点（如 v1.0.0）",
        )

    # 记录部署触发日志
    logger.info(
        "deploy_webhook_triggered",
        tag=payload.tag,
        project=payload.project,
        script=settings.DEPLOY_SCRIPT_PATH,
    )

    # 使用 subprocess.Popen 异步执行部署脚本，不阻塞当前请求
    # 参数顺序与 scripts/deploy_frontend.py 一致：tag、仓库路径、站点目录。
    # （原文写 deploy_frontend.sh——该 bash 版已于 2026-09-23 改写为跨平台
    #   Python 版并删除，注释同步更正，免得后人按旧名去找文件。）
    try:
        log_file = open(f"{settings.DEPLOY_SITE_DIR}/deploy_process.log", "a")
        _popen_kwargs = dict(stdout=log_file, stderr=log_file, start_new_session=True)
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            _popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [
                settings.DEPLOY_SCRIPT_PATH,
                payload.tag,
                settings.DEPLOY_REPO_PATH,
                settings.DEPLOY_SITE_DIR,
            ],
            **_popen_kwargs,
        )
    except Exception as exc:
        # 脚本启动失败时记录错误，但仍返回 202（脚本可能不存在或无执行权限）
        logger.error(
            "deploy_webhook_script_error",
            tag=payload.tag,
            project=payload.project,
            error=str(exc),
        )

    return DeployResponse(
        success=True,
        message=f"部署已触发，tag: {payload.tag}，项目: {payload.project}",
        tag=payload.tag,
    )
