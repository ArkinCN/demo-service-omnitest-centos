"""
User Group management API endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.user_group import (
    UserGroupCreate,
    UserGroupUpdate,
    UserGroupResponse,
    UserGroupListItem,
    UserGroupTreeNode,
    UserGroupMemberAdd,
    UserGroupMemberResponse,
    LdapSyncRequest,
    LdapSyncStatusResponse,
    LdapSyncResult
)
from app.schemas.common import success_response
from app.services.user_group_service import UserGroupService
from app.services.ldap_sync_service import LdapSyncService
from app.core.config import settings


router = APIRouter(prefix="/groups", tags=["User Groups"])


@router.get("", response_model=dict, summary="Get user groups list (Admin only)")
def get_groups(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    group_type: Optional[str] = Query(default=None, description="Filter by type (CUSTOM/LDAP)"),
    parent_id: Optional[int] = Query(default=None, description="Filter by parent ID (-1 for root)"),
    keyword: Optional[str] = Query(default=None, description="Search keyword"),
    is_active: Optional[bool] = Query(default=None, description="Filter by status"),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get paginated user groups list with filters (Admin only)

    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **group_type**: Filter by type (CUSTOM or LDAP)
    - **parent_id**: Filter by parent group (-1 for root level only)
    - **keyword**: Search in group name
    - **is_active**: Filter by active status
    """
    groups, total = UserGroupService.get_groups_paginated(
        session=session,
        page=page,
        page_size=page_size,
        group_type=group_type,
        parent_id=parent_id,
        keyword=keyword,
        is_active=is_active
    )

    # Add user count for each group
    group_items = []
    for group in groups:
        item = UserGroupListItem.model_validate(group).model_dump()
        item["user_count"] = UserGroupService.get_group_user_count(session, group.id)
        group_items.append(item)

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    paginated_data = {
        "items": group_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Groups retrieved successfully")


@router.get("/tree", response_model=dict, summary="Get groups as tree (Admin only)")
def get_groups_tree(
    group_type: Optional[str] = Query(default=None, description="Filter by type (CUSTOM/LDAP)"),
    is_active: Optional[bool] = Query(default=True, description="Filter by status"),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get user groups as a tree structure (Admin only)

    Returns root-level groups with nested children.
    """
    root_groups = UserGroupService.get_group_tree(
        session=session,
        group_type=group_type,
        is_active=is_active
    )

    def build_tree_node(group) -> dict:
        node = UserGroupResponse.model_validate(group).model_dump()
        node["user_count"] = UserGroupService.get_group_user_count(session, group.id)
        node["children"] = [build_tree_node(child) for child in group.children]
        return node

    tree = [build_tree_node(group) for group in root_groups]

    return success_response(data=tree, message="Group tree retrieved successfully")


@router.post("", response_model=dict, summary="Create user group (Admin only)")
def create_group(
    group_data: UserGroupCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Create a new custom user group (Admin only)

    LDAP groups are auto-created during sync and cannot be manually created.

    - **name**: Group name (required)
    - **description**: Group description (optional)
    - **parent_id**: Parent group ID (optional)
    """
    group = UserGroupService.create_group(session, group_data)
    group_response = UserGroupResponse.model_validate(group).model_dump()
    group_response["user_count"] = 0

    return success_response(data=group_response, message="Group created successfully", code=201)


@router.get("/{group_id}", response_model=dict, summary="Get group by ID (Admin only)")
def get_group(
    group_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get user group details by ID (Admin only)
    """
    group = UserGroupService.get_group_by_id(session, group_id)
    group_response = UserGroupResponse.model_validate(group).model_dump()
    group_response["user_count"] = UserGroupService.get_group_user_count(session, group_id)

    return success_response(data=group_response, message="Group retrieved successfully")


@router.put("/{group_id}", response_model=dict, summary="Update group (Admin only)")
def update_group(
    group_id: int,
    group_data: UserGroupUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Update a custom user group (Admin only)

    LDAP groups cannot be updated.

    - **name**: Group name
    - **description**: Group description
    - **parent_id**: Parent group ID
    - **is_active**: Active status
    """
    group = UserGroupService.update_group(session, group_id, group_data)
    group_response = UserGroupResponse.model_validate(group).model_dump()
    group_response["user_count"] = UserGroupService.get_group_user_count(session, group_id)

    return success_response(data=group_response, message="Group updated successfully")


@router.delete("/{group_id}", response_model=dict, summary="Delete group (Admin only)")
def delete_group(
    group_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Delete a custom user group (Admin only)

    LDAP groups cannot be deleted.
    All memberships will be removed when group is deleted.
    """
    UserGroupService.delete_group(session, group_id)

    return success_response(data={"deleted": True}, message="Group deleted successfully")


@router.get("/{group_id}/users", response_model=dict, summary="Get group users (Admin only)")
def get_group_users(
    group_id: int,
    include_children: bool = Query(default=False, description="Include users from child groups"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get users in a group (Admin only)

    - **include_children**: If true, includes users from all child groups
    - **page**: Page number
    - **page_size**: Items per page
    """
    users, total = UserGroupService.get_group_users(
        session=session,
        group_id=group_id,
        include_children=include_children,
        page=page,
        page_size=page_size
    )

    total_pages = (total + page_size - 1) // page_size

    paginated_data = {
        "items": users,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Group users retrieved successfully")


@router.post("/{group_id}/users", response_model=dict, summary="Add users to group (Admin only)")
def add_users_to_group(
    group_id: int,
    data: UserGroupMemberAdd,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Add users to a custom group (Admin only)

    Cannot add users to LDAP groups manually.

    - **user_ids**: List of user IDs to add
    """
    added_count = UserGroupService.add_users_to_group(
        session=session,
        group_id=group_id,
        user_ids=data.user_ids,
        source="MANUAL"
    )

    return success_response(
        data={"added_count": added_count},
        message=f"Added {added_count} users to group"
    )


@router.delete("/{group_id}/users/{user_id}", response_model=dict, summary="Remove user from group (Admin only)")
def remove_user_from_group(
    group_id: int,
    user_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Remove a user from a custom group (Admin only)

    Cannot remove users from LDAP groups manually.
    """
    removed_count = UserGroupService.remove_users_from_group(
        session=session,
        group_id=group_id,
        user_ids=[user_id]
    )

    if removed_count > 0:
        return success_response(data={"removed_count": removed_count}, message="User removed from group")
    else:
        return success_response(data={"removed_count": 0}, message="User was not in this group")


# LDAP Sync endpoints
ldap_router = APIRouter(prefix="/ldap", tags=["LDAP Sync"])


@ldap_router.post("/sync", response_model=dict, summary="Trigger LDAP sync (Admin only)")
def trigger_ldap_sync(
    data: LdapSyncRequest = LdapSyncRequest(),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Manually trigger LDAP synchronization (Admin only)

    This will:
    - Fetch all users from LDAP
    - Create/update users in database
    - Create/update LDAP groups based on OU hierarchy
    - Update user group memberships
    - Disable users removed from LDAP

    - **force**: Force sync even if one is already running
    """
    result = LdapSyncService.sync(session, force=data.force)

    return success_response(data=result, message=result.get("message", "Sync completed"))


@ldap_router.get("/sync/status", response_model=dict, summary="Get LDAP sync status (Admin only)")
def get_ldap_sync_status(
    _: User = Depends(require_admin)
):
    """
    Get current LDAP sync status (Admin only)

    Returns information about the last sync and whether a sync is in progress.
    """
    status = LdapSyncService.get_status()

    return success_response(data=status, message="Sync status retrieved")
