"""时间与验证码生成的公共工具。

2026-10-05 清理合并：`utcnow()` 此前在 4 个 service 文件里复制粘贴了四份
（registration / invitation / invitation_application / account_deletion），
连注释「for MySQL compatibility」都逐字相同；`generate_code()` 也在三处重复。
抽到这里统一维护，改时区/编码规则时只改一处。
"""
import random
import string
from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间，返回 timezone-naive datetime（MySQL 兼容：不存 tzinfo）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_code(length: int = 6) -> str:
    """生成随机数字验证码（默认 6 位）。"""
    return "".join(random.choices(string.digits, k=length))
