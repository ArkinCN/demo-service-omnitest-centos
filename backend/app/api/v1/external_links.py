"""
External Link management API endpoints
"""
import os
import uuid
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from sqlmodel import Session
import json

from app.api.deps import get_db, require_admin, get_current_user
from app.models.user import User
from app.models.external_link import ExternalLink
from app.schemas.external_link import (
    ExternalLinkCreate,
    ExternalLinkUpdate,
    ExternalLinkResponse,
    ExternalLinkListItem,
    ExternalLinkBatchUpdateOrder,
    ExternalLinkClickRequest,
    ExternalLinkClickResponse,
    ExternalLinkStatsResponse,
    CategoryListResponse,
    CategoryInfo,
    ExternalLinkByCategoryResponse,
    CategoryBatchUpdateOrder,
)
from app.schemas.common import success_response
from app.services.external_link_service import ExternalLinkService
from app.core.config import settings


router = APIRouter(prefix="/external-links", tags=["External Links"])

# Server base URL for static files
SERVER_BASE_URL = "https://aiproxy.example.internal"


def _get_full_url(relative_url: Optional[str]) -> Optional[str]:
    """Convert relative URL to full URL"""
    if not relative_url:
        return None
    # If already a full URL, return as is
    if relative_url.startswith("http://") or relative_url.startswith("https://"):
        return relative_url
    # Otherwise, prepend server base URL
    return f"{SERVER_BASE_URL}{relative_url}"


def _link_to_dict(link: ExternalLink, session: Session = None, is_favorited: bool = False) -> dict:
    """Convert ExternalLink model to dict with JSON fields parsed"""
    data = {
        "id": link.id,
        "title": link.title,
        "url": link.url,
        "description": link.description,
        "icon_url": _get_full_url(link.icon_url),
        "category": link.category,
        "category_order": link.category_order,
        "link_order": link.link_order,
        "tags": json.loads(link.tags) if isinstance(link.tags, str) else link.tags,
        "related_links_url": json.loads(link.related_links_url) if isinstance(link.related_links_url, str) else (link.related_links_url or []),
        "maintainer_id": link.maintainer_id,
        "visibility": link.visibility,
        "period_type": link.period_type,
        "start_time": link.start_time.isoformat() if link.start_time else None,
        "end_time": link.end_time.isoformat() if link.end_time else None,
        "status": link.status,
        "click_count": link.click_count,
        "last_accessed_at": link.last_accessed_at.isoformat() if link.last_accessed_at else None,
        "created_at": link.created_at,
        "is_favorited": is_favorited,
    }

    # Add maintainer info if session is provided
    if session and link.maintainer_id:
        maintainer = session.get(User, link.maintainer_id)
        if maintainer:
            data["maintainer_username"] = maintainer.username
            data["maintainer_nickname"] = maintainer.nickname
            data["maintainer_avatar"] = maintainer.avatar_url
        else:
            data["maintainer_username"] = None
            data["maintainer_nickname"] = None
            data["maintainer_avatar"] = None

    return data


@router.get("", response_model=dict, summary="Get external links list")
def get_links(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    visibility: Optional[str] = Query(default=None, description="Filter by visibility"),
    period_type: Optional[str] = Query(default=None, description="Filter by period type"),
    keyword: Optional[str] = Query(default=None, description="Search keyword"),
    created_by: Optional[int] = Query(default=None, description="Filter by creator"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get paginated external links list with filters

    Non-admin users only see links they have permission to view.
    Admin users see all links.

    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **category**: Filter by category
    - **status**: Filter by status (ACTIVE/INACTIVE/ARCHIVED)
    - **visibility**: Filter by visibility (ALL/SPECIFIED)
    - **period_type**: Filter by period type (LONG_TERM/SHORT_TERM)
    - **keyword**: Search in title and description
    - **created_by**: Filter by creator user ID
    """
    # Get user's group IDs for permission filtering
    user_group_ids = []
    if not current_user.is_admin:
        # Fetch user's groups (you'll need to implement this query)
        from app.models.user_group import UserGroupMember
        from sqlmodel import select

        member_stmt = select(UserGroupMember.group_id).where(
            UserGroupMember.user_id == current_user.id
        )
        user_group_ids = list(session.exec(member_stmt).all())

    links, total = ExternalLinkService.get_links_paginated(
        session=session,
        page=page,
        page_size=page_size,
        category=category,
        status=status,
        visibility=visibility,
        period_type=period_type,
        keyword=keyword,
        created_by=created_by,
        current_user_id=current_user.id,
        current_user_group_ids=user_group_ids,
        is_admin=current_user.is_admin
    )

    # Build response items with additional info
    link_items = []
    for link in links:
        # Convert link to dict with JSON fields parsed (now includes maintainer_username)
        link_dict = _link_to_dict(link, session)
        item = ExternalLinkListItem.model_validate(link_dict).model_dump()
        link_items.append(item)

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    paginated_data = {
        "items": link_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Links retrieved successfully")


@router.get("/by-category", response_model=dict, summary="Get links grouped by category")
def get_links_by_category(
    include_inactive: bool = Query(default=False, description="Include inactive/archived links"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all links grouped by category

    Returns a list of categories, each containing its links.
    Non-admin users only see links they have permission to view.
    """
    from app.models.external_link import UserLinkFavorite
    from sqlmodel import select

    # Get user's group IDs
    user_group_ids = []
    if not current_user.is_admin:
        from app.models.user_group import UserGroupMember

        member_stmt = select(UserGroupMember.group_id).where(
            UserGroupMember.user_id == current_user.id
        )
        user_group_ids = list(session.exec(member_stmt).all())

    links_by_category = ExternalLinkService.get_links_by_category(
        session=session,
        current_user_id=current_user.id,
        current_user_group_ids=user_group_ids,
        is_admin=current_user.is_admin,
        include_inactive=include_inactive
    )

    # Get user's favorited link IDs
    favorite_stmt = select(UserLinkFavorite.link_id).where(
        UserLinkFavorite.user_id == current_user.id
    )
    favorited_link_ids = set(session.exec(favorite_stmt).all())

    # Build response
    result = []
    for category, links in links_by_category.items():
        category_data = {
            "category": category,
            "category_order": links[0].category_order if links else 0,
            "links": [
                ExternalLinkListItem.model_validate(
                    _link_to_dict(link, session, is_favorited=link.id in favorited_link_ids)
                ).model_dump()
                for link in links
            ]
        }
        result.append(category_data)

    # Sort by category order
    result.sort(key=lambda x: x["category_order"])

    return success_response(data=result, message="Links by category retrieved successfully")


@router.get("/categories", response_model=dict, summary="Get all categories")
def get_categories(
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user)
):
    """
    Get all unique categories with their orders and link counts
    """
    categories = ExternalLinkService.get_categories(session)

    category_list = [
        CategoryInfo(**cat)
        for cat in categories
    ]

    return success_response(
        data={"categories": category_list},
        message="Categories retrieved successfully"
    )


@router.get("/stats", response_model=dict, summary="Get link statistics (Admin only)")
def get_statistics(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get overall statistics for external links (Admin only)

    Returns total links, active links, total clicks, categories, and top links.
    """
    stats = ExternalLinkService.get_statistics(session)

    # Format top links
    top_links = [
        ExternalLinkListItem.model_validate(_link_to_dict(link, session)).model_dump()
        for link in stats["top_links"]
    ]

    stats_response = ExternalLinkStatsResponse(
        total_links=stats["total_links"],
        active_links=stats["active_links"],
        total_clicks=stats["total_clicks"],
        total_categories=stats["total_categories"],
        top_links=top_links
    )

    return success_response(data=stats_response.model_dump(), message="Statistics retrieved successfully")


@router.post("", response_model=dict, summary="Create external link (Admin only)")
def create_link(
    link_data: ExternalLinkCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Create a new external link (Admin only)

    - **title**: Link title (required)
    - **url**: Link URL (required)
    - **description**: Link description (optional)
    - **icon_url**: Icon URL (optional)
    - **category**: Category name (required)
    - **maintainer_id**: Maintainer user ID (optional)
    - **visibility**: ALL or SPECIFIED (default: ALL)
    - **allowed_group_ids**: List of allowed group IDs (for SPECIFIED visibility)
    - **allowed_user_ids**: List of allowed user IDs (for SPECIFIED visibility)
    - **period_type**: LONG_TERM or SHORT_TERM (default: LONG_TERM)
    - **start_time**: Opening start time (optional)
    - **end_time**: Opening end time (optional)
    - **time_pattern**: Smart time pattern (optional)
    - **status**: ACTIVE/INACTIVE/ARCHIVED (default: ACTIVE)
    """
    link = ExternalLinkService.create_link(session, link_data, current_user.id)

    # Parse JSON fields from database strings
    tags = json.loads(link.tags) if isinstance(link.tags, str) else link.tags
    allowed_group_ids = json.loads(link.allowed_group_ids) if isinstance(link.allowed_group_ids, str) else link.allowed_group_ids
    allowed_user_ids = json.loads(link.allowed_user_ids) if isinstance(link.allowed_user_ids, str) else link.allowed_user_ids
    reminder_config = json.loads(link.reminder_config) if isinstance(link.reminder_config, str) else link.reminder_config
    related_todo_ids = json.loads(link.related_todo_ids) if isinstance(link.related_todo_ids, str) else link.related_todo_ids
    related_links_url = json.loads(link.related_links_url) if isinstance(link.related_links_url, str) else (link.related_links_url or [])

    # Get usernames
    creator = session.get(User, link.created_by)
    creator_username = creator.username if creator else None

    maintainer_username = None
    maintainer_nickname = None
    maintainer_avatar = None
    if link.maintainer_id:
        maintainer = session.get(User, link.maintainer_id)
        if maintainer:
            maintainer_username = maintainer.username
            maintainer_nickname = maintainer.nickname
            maintainer_avatar = maintainer.avatar_url

    # Build response dict manually
    link_response = {
        "id": link.id,
        "title": link.title,
        "url": link.url,
        "description": link.description,
        "icon_url": link.icon_url,
        "category": link.category,
        "category_order": link.category_order,
        "link_order": link.link_order,
        "tags": tags,
        "maintainer_id": link.maintainer_id,
        "maintainer_username": maintainer_username,
        "maintainer_nickname": maintainer_nickname,
        "maintainer_avatar": maintainer_avatar,
        "created_by": link.created_by,
        "creator_username": creator_username,
        "visibility": link.visibility,
        "allowed_group_ids": allowed_group_ids,
        "allowed_user_ids": allowed_user_ids,
        "period_type": link.period_type,
        "start_time": link.start_time.isoformat() if link.start_time else None,
        "end_time": link.end_time.isoformat() if link.end_time else None,
        "time_pattern": link.time_pattern,
        "status": link.status,
        "click_count": link.click_count,
        "last_accessed_at": link.last_accessed_at.isoformat() if link.last_accessed_at else None,
        "reminder_config": reminder_config,
        "related_todo_ids": related_todo_ids,
        "related_links_url": related_links_url,
        "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat(),
    }

    return success_response(data=link_response, message="Link created successfully", code=201)


@router.get("/{link_id}", response_model=dict, summary="Get link by ID")
def get_link(
    link_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get external link details by ID

    Non-admin users can only view links they have permission to see.
    """
    link = ExternalLinkService.get_link_by_id(session, link_id)

    # Check permission for non-admin users
    if not current_user.is_admin:
        # Get user's group IDs
        from app.models.user_group import UserGroupMember
        from sqlmodel import select

        member_stmt = select(UserGroupMember.group_id).where(
            UserGroupMember.user_id == current_user.id
        )
        user_group_ids = list(session.exec(member_stmt).all())

        # Filter by permission
        allowed_links = ExternalLinkService._filter_links_by_permission(
            [link], current_user.id, user_group_ids
        )

        if not allowed_links:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("You don't have permission to view this link")

    # Parse JSON fields from database strings
    tags = json.loads(link.tags) if isinstance(link.tags, str) else link.tags
    allowed_group_ids = json.loads(link.allowed_group_ids) if isinstance(link.allowed_group_ids, str) else link.allowed_group_ids
    allowed_user_ids = json.loads(link.allowed_user_ids) if isinstance(link.allowed_user_ids, str) else link.allowed_user_ids
    reminder_config = json.loads(link.reminder_config) if isinstance(link.reminder_config, str) else link.reminder_config
    related_todo_ids = json.loads(link.related_todo_ids) if isinstance(link.related_todo_ids, str) else link.related_todo_ids
    related_links_url = json.loads(link.related_links_url) if isinstance(link.related_links_url, str) else (link.related_links_url or [])

    # Get usernames
    creator = session.get(User, link.created_by)
    creator_username = creator.username if creator else None

    maintainer_username = None
    maintainer_nickname = None
    maintainer_avatar = None
    if link.maintainer_id:
        maintainer = session.get(User, link.maintainer_id)
        if maintainer:
            maintainer_username = maintainer.username
            maintainer_nickname = maintainer.nickname
            maintainer_avatar = maintainer.avatar_url

    # Build response dict manually
    link_response = {
        "id": link.id,
        "title": link.title,
        "url": link.url,
        "description": link.description,
        "icon_url": link.icon_url,
        "category": link.category,
        "category_order": link.category_order,
        "link_order": link.link_order,
        "tags": tags,
        "maintainer_id": link.maintainer_id,
        "maintainer_username": maintainer_username,
        "maintainer_nickname": maintainer_nickname,
        "maintainer_avatar": maintainer_avatar,
        "created_by": link.created_by,
        "creator_username": creator_username,
        "visibility": link.visibility,
        "allowed_group_ids": allowed_group_ids,
        "allowed_user_ids": allowed_user_ids,
        "period_type": link.period_type,
        "start_time": link.start_time.isoformat() if link.start_time else None,
        "end_time": link.end_time.isoformat() if link.end_time else None,
        "time_pattern": link.time_pattern,
        "status": link.status,
        "click_count": link.click_count,
        "last_accessed_at": link.last_accessed_at.isoformat() if link.last_accessed_at else None,
        "reminder_config": reminder_config,
        "related_todo_ids": related_todo_ids,
        "related_links_url": related_links_url,
        "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat(),
    }

    return success_response(data=link_response, message="Link retrieved successfully")


@router.put("/{link_id}", response_model=dict, summary="Update link (Admin only)")
def update_link(
    link_id: int,
    link_data: ExternalLinkUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Update an external link (Admin only)

    All fields are optional. Only provided fields will be updated.
    """
    link = ExternalLinkService.update_link(session, link_id, link_data, current_user.id)

    # Parse JSON fields from database strings
    tags = json.loads(link.tags) if isinstance(link.tags, str) else link.tags
    allowed_group_ids = json.loads(link.allowed_group_ids) if isinstance(link.allowed_group_ids, str) else link.allowed_group_ids
    allowed_user_ids = json.loads(link.allowed_user_ids) if isinstance(link.allowed_user_ids, str) else link.allowed_user_ids
    reminder_config = json.loads(link.reminder_config) if isinstance(link.reminder_config, str) else link.reminder_config
    related_todo_ids = json.loads(link.related_todo_ids) if isinstance(link.related_todo_ids, str) else link.related_todo_ids
    related_links_url = json.loads(link.related_links_url) if isinstance(link.related_links_url, str) else (link.related_links_url or [])

    # Get usernames
    creator = session.get(User, link.created_by)
    creator_username = creator.username if creator else None

    maintainer_username = None
    maintainer_nickname = None
    maintainer_avatar = None
    if link.maintainer_id:
        maintainer = session.get(User, link.maintainer_id)
        if maintainer:
            maintainer_username = maintainer.username
            maintainer_nickname = maintainer.nickname
            maintainer_avatar = maintainer.avatar_url

    # Build response dict manually
    link_response = {
        "id": link.id,
        "title": link.title,
        "url": link.url,
        "description": link.description,
        "icon_url": link.icon_url,
        "category": link.category,
        "category_order": link.category_order,
        "link_order": link.link_order,
        "tags": tags,
        "maintainer_id": link.maintainer_id,
        "maintainer_username": maintainer_username,
        "maintainer_nickname": maintainer_nickname,
        "maintainer_avatar": maintainer_avatar,
        "created_by": link.created_by,
        "creator_username": creator_username,
        "visibility": link.visibility,
        "allowed_group_ids": allowed_group_ids,
        "allowed_user_ids": allowed_user_ids,
        "period_type": link.period_type,
        "start_time": link.start_time.isoformat() if link.start_time else None,
        "end_time": link.end_time.isoformat() if link.end_time else None,
        "time_pattern": link.time_pattern,
        "status": link.status,
        "click_count": link.click_count,
        "last_accessed_at": link.last_accessed_at.isoformat() if link.last_accessed_at else None,
        "reminder_config": reminder_config,
        "related_todo_ids": related_todo_ids,
        "related_links_url": related_links_url,
        "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat(),
    }

    return success_response(data=link_response, message="Link updated successfully")


@router.delete("/{link_id}", response_model=dict, summary="Delete link (Admin only)")
def delete_link(
    link_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Delete an external link (Admin only)

    This will also delete all associated click records.
    """
    ExternalLinkService.delete_link(session, link_id, current_user.id)

    return success_response(data={}, message="Link deleted successfully")


@router.post("/batch-update-order", response_model=dict, summary="Batch update link order (Admin only)")
def batch_update_order(
    update_data: ExternalLinkBatchUpdateOrder,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Batch update link and category orders (Admin only)

    Used for drag-and-drop reordering in the frontend.

    - **updates**: List of {id, category_order?, link_order?} objects
    """
    ExternalLinkService.batch_update_order(
        session, update_data.updates, current_user.id
    )

    return success_response(data={}, message="Order updated successfully")


@router.post("/{link_id}/click", response_model=dict, summary="Record link click")
def record_click(
    link_id: int,
    click_data: ExternalLinkClickRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Record a link click

    This increments the link's click count and creates a click history record.
    Non-admin users can only click links they have permission to view.
    """
    # Check if link exists and user has permission
    link = ExternalLinkService.get_link_by_id(session, link_id)

    if not current_user.is_admin:
        # Get user's group IDs
        from app.models.user_group import UserGroupMember
        from sqlmodel import select

        member_stmt = select(UserGroupMember.group_id).where(
            UserGroupMember.user_id == current_user.id
        )
        user_group_ids = list(session.exec(member_stmt).all())

        # Filter by permission
        allowed_links = ExternalLinkService._filter_links_by_permission(
            [link], current_user.id, user_group_ids
        )

        if not allowed_links:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("You don't have permission to access this link")

    # Record click
    click = ExternalLinkService.record_click(
        session, link_id, current_user.id, click_data.user_agent
    )

    # Build response
    click_response = ExternalLinkClickResponse(
        id=click.id,
        link_id=click.link_id,
        user_id=click.user_id,
        username=current_user.username,
        clicked_at=click.clicked_at
    )

    return success_response(data=click_response.model_dump(), message="Click recorded successfully")


@router.get("/{link_id}/clicks", response_model=dict, summary="Get link click history (Admin only)")
def get_link_clicks(
    link_id: int,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get click history for a specific link (Admin only)

    Returns paginated list of click records with user information.
    """
    clicks, total = ExternalLinkService.get_click_history(
        session, link_id=link_id, page=page, page_size=page_size
    )

    # Build response items
    click_items = []
    for click in clicks:
        user = session.get(User, click.user_id)
        click_item = ExternalLinkClickResponse(
            id=click.id,
            link_id=click.link_id,
            user_id=click.user_id,
            username=user.username if user else None,
            clicked_at=click.clicked_at
        )
        click_items.append(click_item.model_dump())

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    paginated_data = {
        "items": click_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Click history retrieved successfully")


@router.get("/users/{user_id}/clicks", response_model=dict, summary="Get user click history")
def get_user_clicks(
    user_id: int,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get click history for a specific user

    Users can only view their own history. Admins can view anyone's history.
    """
    # Permission check
    if not current_user.is_admin and current_user.id != user_id:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("You can only view your own click history")

    clicks, total = ExternalLinkService.get_click_history(
        session, user_id=user_id, page=page, page_size=page_size
    )

    # Build response items with link info
    click_items = []
    for click in clicks:
        link = session.get(ExternalLink, click.link_id)
        click_item = {
            "id": click.id,
            "link_id": click.link_id,
            "link_title": link.title if link else None,
            "link_url": link.url if link else None,
            "user_id": click.user_id,
            "clicked_at": click.clicked_at
        }
        click_items.append(click_item)

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    paginated_data = {
        "items": click_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="User click history retrieved successfully")


# ==================== Category Management APIs ====================

@router.post("/categories", response_model=dict, summary="Create or update category (Admin only)")
def create_or_update_category(
    category_name: str,
    new_category_name: Optional[str] = None,
    category_order: Optional[int] = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Create a new category or update existing category name/order (Admin only)

    - **category_name**: Current category name (for update) or new category name (for create)
    - **new_category_name**: New category name (only for rename operation)
    - **category_order**: Category display order
    """
    from sqlmodel import select

    # Check if category exists
    stmt = select(ExternalLink).where(ExternalLink.category == category_name).limit(1)
    existing_link = session.exec(stmt).first()

    if existing_link:
        # Update existing category
        if new_category_name and new_category_name != category_name:
            # Rename category - update all links in this category
            stmt = select(ExternalLink).where(ExternalLink.category == category_name)
            links = session.exec(stmt).all()

            for link in links:
                link.category = new_category_name
                if category_order is not None:
                    link.category_order = category_order

            session.commit()
            message = f"Category renamed from '{category_name}' to '{new_category_name}'"
        elif category_order is not None:
            # Update category order
            stmt = select(ExternalLink).where(ExternalLink.category == category_name)
            links = session.exec(stmt).all()

            for link in links:
                link.category_order = category_order

            session.commit()
            message = f"Category '{category_name}' order updated"
        else:
            message = f"Category '{category_name}' already exists"
    else:
        # Create new category with a placeholder link (will be replaced when first link is created)
        # Actually, we don't need to create anything - categories are created automatically
        # when links are created with new category names
        message = f"Category '{category_name}' will be created when first link is added"

    return success_response(data={"category": new_category_name or category_name}, message=message)


@router.delete("/categories/{category_name}", response_model=dict, summary="Delete category (Admin only)")
def delete_category(
    category_name: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Delete a category and all its links (Admin only)

    - **category_name**: Name of category to delete
    """
    from sqlmodel import select

    # Find all links in this category
    stmt = select(ExternalLink).where(ExternalLink.category == category_name)
    links = session.exec(stmt).all()

    if not links:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(f"Category '{category_name}' not found")

    # Delete all links in this category
    for link in links:
        # Delete associated click records first
        from app.models.external_link import ExternalLinkClick
        click_stmt = select(ExternalLinkClick).where(ExternalLinkClick.link_id == link.id)
        clicks = session.exec(click_stmt).all()
        for click in clicks:
            session.delete(click)

        # Delete the link
        session.delete(link)

    session.commit()

    return success_response(
        data={"deleted_links": len(links)},
        message=f"Category '{category_name}' and {len(links)} links deleted successfully"
    )


@router.post("/categories/batch-update-order", response_model=dict, summary="Batch update category order (Admin only)")
def batch_update_category_order(
    update_data: CategoryBatchUpdateOrder,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Batch update category orders (Admin only)

    Used for drag-and-drop reordering of categories.

    - **updates**: List of {category_name, order} objects
    """
    from sqlmodel import select

    updated_count = 0
    for update in update_data.updates:
        # Find all links in this category and update their category_order
        stmt = select(ExternalLink).where(ExternalLink.category == update.category_name)
        links = session.exec(stmt).all()

        for link in links:
            link.category_order = update.order
            updated_count += 1

    session.commit()

    return success_response(
        data={"updated_categories": len(update_data.updates), "updated_links": updated_count},
        message="Category order updated successfully"
    )


# ==================== Image Upload API ====================

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload-image", response_model=dict, summary="Upload link cover image (Admin only)")
async def upload_link_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin)
):
    """
    Upload a cover image for external links (Admin only)

    Returns the URL of the uploaded image that can be used in icon_url field.

    - **file**: Image file (jpg, png, webp, gif, max 5MB)
    """
    # Validate file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持的类型: jpg, png, webp, gif"
        )

    # Validate file extension
    file_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件扩展名。支持的扩展名: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制。最大: {MAX_IMAGE_SIZE // 1024 // 1024}MB"
        )

    # Generate unique filename
    unique_id = str(uuid.uuid4())
    new_filename = f"{unique_id}{file_ext}"

    # Save file
    upload_dir = Path("uploads/link_images")
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / new_filename
    with open(file_path, "wb") as f:
        f.write(content)

    # Generate URL
    image_url = f"/uploads/link_images/{new_filename}"

    return success_response(
        data={
            "url": image_url,
            "filename": new_filename,
            "size": len(content),
            "content_type": file.content_type
        },
        message="图片上传成功"
    )


@router.delete("/delete-image", response_model=dict, summary="Delete link cover image (Admin only)")
def delete_link_image(
    image_url: str = Query(..., description="Image URL to delete"),
    current_user: User = Depends(require_admin)
):
    """
    Delete a previously uploaded link cover image (Admin only)

    - **image_url**: The URL of the image to delete (as returned by upload-image)
    """
    # Extract filename from URL
    if not image_url.startswith("/uploads/link_images/"):
        raise HTTPException(
            status_code=400,
            detail="无效的图片URL"
        )

    filename = image_url.replace("/uploads/link_images/", "")

    # Validate filename to prevent directory traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=400,
            detail="无效的图片文件名"
        )

    # Build file path
    file_path = Path("uploads/link_images") / filename

    # Check if file exists and delete
    if file_path.exists():
        os.remove(file_path)
        return success_response(
            data={"deleted": image_url},
            message="图片删除成功"
        )
    else:
        raise HTTPException(
            status_code=404,
            detail="图片文件不存在"
        )
