"""
Chat API endpoints
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from typing import Optional

from app.api.deps import get_db, get_current_active_user
from app.models.user import User
from app.models.chat import ChatHelper
from app.schemas.chat import (
    ChatCreate,
    ChatUpdate,
    ChatResponse,
    ChatListItem,
    ChatListResponse,
    ChatPinToggleResponse,
    ChatArchiveToggleResponse
)
from app.schemas.common import success_response
from app.services.chat_service import ChatService
from app.core.logger import logger
import json


def serialize_datetime(dt: datetime) -> str:
    """确保时间序列化时带有UTC时区信息"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


router = APIRouter(prefix="/chats", tags=["Chats"])


@router.post("", response_model=dict, summary="Create new chat")
def create_chat(
    chat_data: ChatCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new chat conversation

    - **title**: Chat title (default: "新对话")
    - **model**: AI model name (default: "gpt-4")
    - **params**: Model parameters (optional)

    Returns created chat with empty history structure
    """
    chat = ChatService.create_chat(session, current_user.id, chat_data)

    # Manually construct response with parsed JSON fields
    response_data = {
        "id": chat.id,
        "user_id": chat.user_id,
        "title": chat.title,
        "history": json.loads(chat.history) if isinstance(chat.history, str) else chat.history,
        "model": chat.model,
        "params": json.loads(chat.params) if isinstance(chat.params, str) else chat.params,
        "created_at": serialize_datetime(chat.created_at),
        "updated_at": serialize_datetime(chat.updated_at),
        "pinned": chat.pinned,
        "archived": chat.archived,
        "message_count": chat.message_count
    }

    return success_response(
        data=response_data,
        message="Chat created successfully"
    )


@router.get("", response_model=dict, summary="Get chat list")
def get_chats(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    archived: bool = Query(False, description="Show archived chats"),
    search: Optional[str] = Query(None, max_length=200, description="Search keyword"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get user's chat list with pagination

    - **page**: Page number (1-indexed)
    - **page_size**: Items per page (1-100)
    - **archived**: Filter by archived status
    - **search**: Search keyword for title

    Returns paginated chat list ordered by pinned and updated_at
    """
    chats, total = ChatService.get_user_chats(
        session,
        current_user.id,
        page,
        page_size,
        archived,
        search
    )

    # Convert to list items
    items = [ChatListItem.model_validate(chat) for chat in chats]

    response_data = {
        "items": [item.model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size
    }

    return success_response(
        data=response_data,
        message="Chat list retrieved successfully"
    )


@router.get("/{chat_id}", response_model=dict, summary="Get chat details")
def get_chat(
    chat_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get chat details by ID

    - **chat_id**: Chat UUID

    Returns full chat details including message history tree
    """
    chat = ChatService.get_chat_by_id(session, chat_id, current_user.id)

    # Manually construct response with parsed JSON fields
    response_data = {
        "id": chat.id,
        "user_id": chat.user_id,
        "title": chat.title,
        "history": json.loads(chat.history) if isinstance(chat.history, str) else chat.history,
        "model": chat.model,
        "params": json.loads(chat.params) if isinstance(chat.params, str) else chat.params,
        "created_at": serialize_datetime(chat.created_at),
        "updated_at": serialize_datetime(chat.updated_at),
        "pinned": chat.pinned,
        "archived": chat.archived,
        "message_count": chat.message_count
    }

    return success_response(
        data=response_data,
        message="Chat retrieved successfully"
    )


@router.put("/{chat_id}", response_model=dict, summary="Update chat")
def update_chat(
    chat_id: str,
    chat_data: ChatUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update chat information

    - **title**: New chat title (optional)
    - **history**: Updated message tree structure (optional)
    - **model**: AI model name (optional)
    - **params**: Model parameters (optional)

    Returns updated chat
    """
    chat = ChatService.update_chat(session, chat_id, current_user.id, chat_data)

    # Manually construct response with parsed JSON fields
    response_data = {
        "id": chat.id,
        "user_id": chat.user_id,
        "title": chat.title,
        "history": json.loads(chat.history) if isinstance(chat.history, str) else chat.history,
        "model": chat.model,
        "params": json.loads(chat.params) if isinstance(chat.params, str) else chat.params,
        "created_at": serialize_datetime(chat.created_at),
        "updated_at": serialize_datetime(chat.updated_at),
        "pinned": chat.pinned,
        "archived": chat.archived,
        "message_count": chat.message_count
    }

    return success_response(
        data=response_data,
        message="Chat updated successfully"
    )


@router.delete("/{chat_id}", response_model=dict, summary="Delete chat")
def delete_chat(
    chat_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a chat permanently

    - **chat_id**: Chat UUID

    This action cannot be undone
    """
    ChatService.delete_chat(session, chat_id, current_user.id)

    return success_response(
        data={"deleted": True, "chat_id": chat_id},
        message="Chat deleted successfully"
    )


@router.post("/{chat_id}/pin", response_model=dict, summary="Toggle pin status")
def toggle_pin(
    chat_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Toggle chat pin status

    - **chat_id**: Chat UUID

    Pinned chats appear at the top of the list
    """
    chat = ChatService.toggle_pin(session, chat_id, current_user.id)

    response_data = {"pinned": chat.pinned}

    return success_response(
        data=response_data,
        message=f"Chat {'pinned' if chat.pinned else 'unpinned'} successfully"
    )


@router.post("/{chat_id}/archive", response_model=dict, summary="Toggle archive status")
def toggle_archive(
    chat_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Toggle chat archive status

    - **chat_id**: Chat UUID

    Archived chats are hidden from main list
    """
    chat = ChatService.toggle_archive(session, chat_id, current_user.id)

    response_data = {"archived": chat.archived}

    return success_response(
        data=response_data,
        message=f"Chat {'archived' if chat.archived else 'unarchived'} successfully"
    )


@router.get("/search", response_model=dict, summary="Search chats")
def search_chats(
    keyword: str = Query(..., min_length=1, max_length=200, description="Search keyword"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Search chats by keyword

    - **keyword**: Search keyword for title
    - **page**: Page number (1-indexed)
    - **page_size**: Items per page (1-100)

    Returns paginated search results
    """
    chats, total = ChatService.search_chats(
        session,
        current_user.id,
        keyword,
        page,
        page_size
    )

    # Convert to list items
    items = [ChatListItem.model_validate(chat) for chat in chats]

    response_data = {
        "items": [item.model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size
    }

    return success_response(
        data=response_data,
        message=f"Found {total} chat(s)"
    )


@router.delete("", response_model=dict, summary="Delete all chats")
def delete_all_chats(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete all chats for current user

    This action cannot be undone. Use with caution.
    """
    count = ChatService.delete_all_user_chats(session, current_user.id)

    return success_response(
        data={"deleted": True, "count": count},
        message=f"Deleted {count} chat(s) successfully"
    )
