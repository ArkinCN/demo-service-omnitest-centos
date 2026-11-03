"""
User management API endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File, BackgroundTasks
from sqlmodel import Session

from app.api.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserUpdateStatus,
    UserResponse,
    UserListItem,
    UserGroupInfo,
    AccountDeleteRequest
)
from app.schemas.common import success_response, PaginatedResponse
from app.services.user_service import UserService
from app.services.account_deletion_service import AccountDeletionService
from app.services.presence_manager import presence_manager
from app.services.user_group_service import UserGroupService
from app.services.image_service import image_service
from app.core.config import settings


router = APIRouter(prefix="/users", tags=["User Management"])


@router.get("", response_model=dict, summary="Get user list (Admin only)")
def get_users(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    keyword: Optional[str] = Query(default=None, description="Search keyword"),
    role: Optional[str] = Query(default=None, description="Filter by role"),
    auth_type: Optional[str] = Query(default=None, description="Filter by auth type (LDAP/EMAIL)"),
    is_active: Optional[bool] = Query(default=None, description="Filter by status"),
    group_id: Optional[int] = Query(default=None, description="Filter by group ID"),
    include_subgroups: bool = Query(default=False, description="Include users from subgroups"),
    sort_by: Optional[str] = Query(default=None, description="Sort by field (e.g., last_active_at, created_at)"),
    sort_order: Optional[str] = Query(default="desc", description="Sort order (asc/desc)"),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get paginated user list with filters (Admin only)

    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **keyword**: Search in username, email, nickname
    - **role**: Filter by role (admin or user)
    - **auth_type**: Filter by authentication type (LDAP or EMAIL)
    - **is_active**: Filter by active status
    - **group_id**: Filter by user group
    - **include_subgroups**: Include users from subgroups when filtering by group
    - **sort_by**: Sort by field (last_active_at, created_at, etc.)
    - **sort_order**: Sort order (asc/desc)

    Returns paginated user list
    """
    users, total = UserService.get_users_paginated(
        session=session,
        page=page,
        page_size=page_size,
        keyword=keyword,
        role=role,
        auth_type=auth_type,
        is_active=is_active,
        group_id=group_id,
        include_subgroups=include_subgroups,
        sort_by=sort_by,
        sort_order=sort_order
    )

    # Convert to list items with groups
    user_items = []
    for user in users:
        item = UserListItem.model_validate(user).model_dump()
        # Get all user groups
        all_groups = UserGroupService.get_user_groups(session, user.id, direct_only=False)

        # Separate LDAP and CUSTOM groups
        ldap_groups = [g for g in all_groups if g.group_type == 'LDAP']
        custom_groups = [g for g in all_groups if g.group_type == 'CUSTOM']

        # Build groups list to return
        groups_to_return = []

        # For LDAP: only return the most direct one (deepest in hierarchy)
        if ldap_groups:
            ldap_ids = {g.id for g in ldap_groups}
            parent_ids = {g.parent_id for g in ldap_groups if g.parent_id is not None}
            direct_ldap = [g for g in ldap_groups if g.id not in parent_ids]
            groups_to_return.append(direct_ldap[0] if direct_ldap else ldap_groups[0])

        # For CUSTOM: return all custom groups
        groups_to_return.extend(custom_groups)

        item["groups"] = [
            UserGroupInfo(id=g.id, name=g.name, group_type=g.group_type).model_dump()
            for g in groups_to_return
        ]
        user_items.append(item)

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    # Create paginated response
    paginated_data = {
        "items": user_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Users retrieved successfully")


@router.post("/me/watermark-consent", response_model=dict, summary="Accept watermark consent")
def accept_watermark_consent(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Accept watermark disclaimer consent.
    Records user's agreement to use AI-generated images without watermarks.
    """
    user = UserService.set_watermark_consent(session, current_user.id)
    user_data = UserResponse.model_validate(user).model_dump()
    return success_response(data=user_data, message="Watermark consent accepted")


@router.delete("/me/watermark-consent", response_model=dict, summary="Revoke watermark consent")
def revoke_watermark_consent(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Revoke watermark disclaimer consent.
    User will need to re-consent before using image generation mode.
    """
    user = UserService.revoke_watermark_consent(session, current_user.id)
    user_data = UserResponse.model_validate(user).model_dump()
    return success_response(data=user_data, message="Watermark consent revoked")


@router.post("/me/deletion-code", response_model=dict, summary="Send account deletion code")
def send_account_deletion_code(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Send an account-deletion verification code to the current user's email.

    Only EMAIL (non-LDAP) accounts can request self-service deletion.
    """
    AccountDeletionService.request_deletion_code(session, current_user)
    return success_response(message="Deletion code sent")


@router.post("/me/delete", response_model=dict, summary="Delete own account with code")
def delete_own_account(
    data: AccountDeleteRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Soft-delete the current user's account after verifying the emailed code.

    Purges user-owned business data (chats, credits, subscriptions, ...) while
    keeping audit trails; invalidates all issued tokens immediately.
    """
    AccountDeletionService.confirm_deletion(session, current_user, data.code)
    # 踢掉该用户全部在线 WebSocket 会话（max_sessions=0 = 无条件全踢）
    background_tasks.add_task(
        presence_manager.force_disconnect_user,
        current_user.id,
        current_user.token_version,
        0,
    )
    return success_response(message="Account deleted")


@router.get("/{user_id}", response_model=dict, summary="Get user by ID")
def get_user(
    user_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get user details by ID

    Users can view their own info, admins can view any user
    """
    # Non-admins can only view their own info
    if not current_user.is_admin and current_user.id != user_id:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("You can only view your own information")

    user = UserService.get_user_by_id(session, user_id)
    user_data = UserResponse.model_validate(user).model_dump()

    return success_response(data=user_data, message="User retrieved successfully")


@router.post("", response_model=dict, summary="Create new user (Admin only)")
def create_user(
    user_data: UserCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Create a new user (Admin only)

    - **username**: Unique username (3-80 chars)
    - **email**: Unique email address
    - **nickname**: Display name (optional)
    - **password**: Password for EMAIL auth (required if auth_type is EMAIL)
    - **auth_type**: LDAP or EMAIL (default: EMAIL)
    - **role**: admin or user (default: user)
    """
    user = UserService.create_user(session, user_data)
    user_data = UserResponse.model_validate(user).model_dump()

    return success_response(data=user_data, message="User created successfully", code=201)


@router.put("/{user_id}", response_model=dict, summary="Update user")
def update_user(
    user_id: int,
    user_data: UserUpdate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update user information

    Users can update their own info (except role).
    Admins can update any user.
    """
    # Non-admins can only update their own info
    if not current_user.is_admin and current_user.id != user_id:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("You can only update your own information")

    # Non-admins cannot change role
    if not current_user.is_admin and user_data.role is not None:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("You cannot change your own role")

    # Non-admins cannot change max_sessions（防止普通用户给自己开多端登录）
    if not current_user.is_admin and user_data.max_sessions is not None:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("You cannot change max sessions")

    user = UserService.update_user(session, user_id, user_data)
    user_validated = UserResponse.model_validate(user)
    user_response = user_validated.model_dump()

    # 通过 WebSocket 通知被修改的用户实时更新（仅管理员修改他人时推送）
    if current_user.id != user_id:
        background_tasks.add_task(
            presence_manager.send_to_user,
            user_id,
            {"type": "user_updated", "user": user_validated.model_dump(mode='json')}
        )

    return success_response(data=user_response, message="User updated successfully")


@router.put("/{user_id}/status", response_model=dict, summary="Update user status (Admin only)")
def update_user_status(
    user_id: int,
    status_data: UserUpdateStatus,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Enable or disable user account (Admin only)

    - **is_active**: true to enable, false to disable
    """
    user = UserService.update_user_status(session, user_id, status_data.is_active)
    user_validated = UserResponse.model_validate(user)
    user_data = user_validated.model_dump()

    # 通过 WebSocket 通知被修改的用户实时更新（mode='json' 保证 datetime 可序列化）
    background_tasks.add_task(
        presence_manager.send_to_user,
        user_id,
        {"type": "user_updated", "user": user_validated.model_dump(mode='json')}
    )

    status_text = "enabled" if status_data.is_active else "disabled"
    return success_response(data=user_data, message=f"User {status_text} successfully")


@router.delete("/{user_id}", response_model=dict, summary="Delete user (Admin only)")
def delete_user(
    user_id: int,
    session: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """
    Delete user account (Admin only)

    Admins cannot delete their own account.
    """
    # Prevent self-deletion
    if current_admin.id == user_id:
        from app.core.exceptions import BadRequestException
        raise BadRequestException("You cannot delete your own account")

    UserService.delete_user(session, user_id)

    return success_response(message="User deleted successfully")


@router.put("/{user_id}/avatar", response_model=dict, summary="Upload user avatar")
async def upload_avatar(
    user_id: int,
    file: UploadFile = File(..., description="Avatar image file"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload and update user avatar

    - **file**: Image file (JPG, PNG, WebP)
    - Maximum file size: 5MB
    - Image will be processed: cropped to square, resized to 256x256, compressed

    Users can only update their own avatar.
    Admins can update any user's avatar.
    """
    # Non-admins can only update their own avatar
    if not current_user.is_admin and current_user.id != user_id:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("You can only update your own avatar")

    # Get target user
    user = UserService.get_user_by_id(session, user_id)

    # Process and save avatar
    new_avatar_url = await image_service.process_avatar(
        file=file,
        user_id=user_id,
        old_avatar_url=user.avatar_url
    )

    # Update user avatar in database
    updated_user = UserService.update_avatar(session, user_id, new_avatar_url)
    user_validated = UserResponse.model_validate(updated_user)
    user_response = user_validated.model_dump()

    # 通过 WebSocket 通知被修改的用户实时更新头像
    if current_user.id != user_id:
        await presence_manager.send_to_user(user_id, {
            "type": "user_updated",
            "user": user_validated.model_dump(mode='json')
        })

    return success_response(data=user_response, message="Avatar updated successfully")


@router.get("/{user_id}/groups", response_model=dict, summary="Get user's groups (Admin only)")
def get_user_groups(
    user_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get all groups a user belongs to (Admin only)

    Returns both LDAP and custom groups.
    """
    # Verify user exists
    UserService.get_user_by_id(session, user_id)

    # Get user's groups (all, not just direct)
    groups = UserGroupService.get_user_groups(session, user_id, direct_only=False)

    group_list = [
        UserGroupInfo(id=g.id, name=g.name, group_type=g.group_type).model_dump()
        for g in groups
    ]

    return success_response(data=group_list, message="User groups retrieved successfully")
