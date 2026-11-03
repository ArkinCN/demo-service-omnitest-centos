"""
通用实体可见性/权限检查。

适用于任何带 visibility / allowed_user_ids / allowed_group_ids 字段的实体
（ModelPricing、FeatureRoute 等）。从 chat_model_service 解耦而来。
"""
import json


def check_entity_permission(
    entity, user_id: int, user_group_ids: list[int], user_email: str = ""
) -> bool:
    """实体对该用户是否可见。

    - visibility == "ALL"：全员可见
    - visibility == "INTERNAL"：仅 @example.internal 邮箱
    - visibility == "SPECIFIED"：命中 allowed_user_ids 或 allowed_group_ids
    """
    if entity.visibility == "ALL":
        return True
    if entity.visibility == "INTERNAL":
        return bool(user_email) and user_email.endswith("@example.internal")
    if entity.visibility == "SPECIFIED":
        allowed_users = (
            entity.allowed_user_ids
            if isinstance(entity.allowed_user_ids, list)
            else json.loads(entity.allowed_user_ids or "[]")
        )
        allowed_groups = (
            entity.allowed_group_ids
            if isinstance(entity.allowed_group_ids, list)
            else json.loads(entity.allowed_group_ids or "[]")
        )
        if user_id in allowed_users:
            return True
        if any(gid in allowed_groups for gid in user_group_ids):
            return True
    return False
