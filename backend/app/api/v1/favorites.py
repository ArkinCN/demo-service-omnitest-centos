"""
Favorites management API endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.external_link import (
    FavoriteFolderCreate,
    FavoriteFolderUpdate,
    FavoriteFolderResponse,
    FavoriteFolderReorderRequest,
    FavoriteAddRequest,
    FavoriteMoveRequest,
    LinkFavoriteResponse,
    FavoriteStatusResponse,
)
from app.schemas.common import success_response
from app.services.favorite_service import FavoriteService
from app.core.config import settings


router = APIRouter(prefix="/favorites", tags=["Favorites"])


# ==================== Folder Endpoints ====================

@router.post("/folders", response_model=dict, summary="Create favorite folder")
def create_folder(
    folder_data: FavoriteFolderCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new favorite folder for the current user
    """
    folder = FavoriteService.create_folder(session, current_user.id, folder_data)

    return success_response(
        data={
            "id": folder.id,
            "name": folder.name,
            "description": folder.description,
            "sort_order": folder.sort_order,
            "is_default": folder.is_default,
            "link_count": 0,
            "created_at": folder.created_at.isoformat() if folder.created_at else None,
            "updated_at": folder.updated_at.isoformat() if folder.updated_at else None
        },
        message="收藏夹创建成功"
    )


@router.get("/folders", response_model=dict, summary="Get user's favorite folders")
def get_folders(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all favorite folders for the current user
    """
    result = FavoriteService.get_user_folders(session, current_user.id)

    # Format datetime for folders
    folders_data = []
    for folder in result["folders"]:
        folder_dict = dict(folder)
        if folder_dict.get("created_at"):
            folder_dict["created_at"] = folder_dict["created_at"].isoformat()
        if folder_dict.get("updated_at"):
            folder_dict["updated_at"] = folder_dict["updated_at"].isoformat()
        folders_data.append(folder_dict)

    return success_response(
        data={
            "folders": folders_data,
            "uncategorized_count": result["uncategorized_count"]
        },
        message="获取收藏夹成功"
    )


@router.put("/folders/{folder_id}", response_model=dict, summary="Update favorite folder")
def update_folder(
    folder_id: int,
    folder_data: FavoriteFolderUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a favorite folder
    """
    folder = FavoriteService.update_folder(session, folder_id, current_user.id, folder_data)

    # Get link count
    from sqlmodel import select, func
    from app.models.external_link import UserLinkFavorite
    link_count = session.exec(
        select(func.count(UserLinkFavorite.id))
        .where(UserLinkFavorite.folder_id == folder.id)
    ).first() or 0

    return success_response(
        data={
            "id": folder.id,
            "name": folder.name,
            "description": folder.description,
            "sort_order": folder.sort_order,
            "is_default": folder.is_default,
            "link_count": link_count,
            "created_at": folder.created_at.isoformat() if folder.created_at else None,
            "updated_at": folder.updated_at.isoformat() if folder.updated_at else None
        },
        message="收藏夹更新成功"
    )


@router.delete("/folders/{folder_id}", response_model=dict, summary="Delete favorite folder")
def delete_folder(
    folder_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a favorite folder (links will be moved to uncategorized)
    """
    FavoriteService.delete_folder(session, folder_id, current_user.id)

    return success_response(
        message="收藏夹删除成功"
    )


@router.post("/folders/reorder", response_model=dict, summary="Reorder favorite folders")
def reorder_folders(
    request: FavoriteFolderReorderRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reorder favorite folders
    """
    updates = [{"folder_id": u.folder_id, "sort_order": u.sort_order} for u in request.updates]
    FavoriteService.reorder_folders(session, current_user.id, updates)

    return success_response(
        message="收藏夹排序更新成功"
    )


# ==================== Favorite Link Endpoints ====================

@router.post("/links/{link_id}", response_model=dict, summary="Add link to favorites")
def add_favorite(
    link_id: int,
    request: FavoriteAddRequest = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a link to favorites
    """
    folder_id = request.folder_id if request else None
    favorite = FavoriteService.add_favorite(session, current_user.id, link_id, folder_id)

    return success_response(
        data={
            "id": favorite.id,
            "link_id": favorite.link_id,
            "folder_id": favorite.folder_id,
            "created_at": favorite.created_at.isoformat() if favorite.created_at else None
        },
        message="收藏成功"
    )


@router.delete("/links/{link_id}", response_model=dict, summary="Remove link from favorites")
def remove_favorite(
    link_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Remove a link from favorites
    """
    FavoriteService.remove_favorite(session, current_user.id, link_id)

    return success_response(
        data={},
        message="取消收藏成功"
    )


@router.put("/links/{link_id}/move", response_model=dict, summary="Move favorite to another folder")
def move_favorite(
    link_id: int,
    request: FavoriteMoveRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Move a favorited link to another folder
    """
    favorite = FavoriteService.move_favorite(session, current_user.id, link_id, request.folder_id)

    return success_response(
        data={
            "id": favorite.id,
            "link_id": favorite.link_id,
            "folder_id": favorite.folder_id
        },
        message="移动成功"
    )


@router.get("/links", response_model=dict, summary="Get user's favorite links")
def get_favorites(
    folder_id: Optional[int] = Query(default=None, description="Filter by folder ID (-1 for uncategorized)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get user's favorite links with optional folder filter
    """
    favorites, total = FavoriteService.get_user_favorites(
        session,
        current_user.id,
        folder_id,
        page,
        page_size
    )

    # Format datetime fields
    items = []
    for fav in favorites:
        fav_dict = dict(fav)
        if fav_dict.get("created_at"):
            fav_dict["created_at"] = fav_dict["created_at"].isoformat() if hasattr(fav_dict["created_at"], 'isoformat') else fav_dict["created_at"]

        # Format link datetime fields
        if fav_dict.get("link"):
            link = fav_dict["link"]
            if link.get("start_time") and hasattr(link["start_time"], 'isoformat'):
                link["start_time"] = link["start_time"].isoformat()
            if link.get("end_time") and hasattr(link["end_time"], 'isoformat'):
                link["end_time"] = link["end_time"].isoformat()
            if link.get("last_accessed_at") and hasattr(link["last_accessed_at"], 'isoformat'):
                link["last_accessed_at"] = link["last_accessed_at"].isoformat()
            if link.get("created_at") and hasattr(link["created_at"], 'isoformat'):
                link["created_at"] = link["created_at"].isoformat()

        items.append(fav_dict)

    total_pages = (total + page_size - 1) // page_size

    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        },
        message="获取收藏列表成功"
    )


@router.get("/links/{link_id}/status", response_model=dict, summary="Check if link is favorited")
def check_favorite_status(
    link_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check if a link is favorited by the current user
    """
    status = FavoriteService.check_favorite_status(session, current_user.id, link_id)

    return success_response(
        data=status,
        message="获取收藏状态成功"
    )
