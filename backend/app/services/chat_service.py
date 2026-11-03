"""
Chat service for CRUD operations
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple
import uuid
import json
from sqlmodel import Session, select, func, or_

from app.models.chat import Chat, ChatHelper
from app.schemas.chat import ChatCreate, ChatUpdate
from app.core.exceptions import NotFoundException, ForbiddenException
from app.core.logger import logger


class ChatService:
    """Chat CRUD service"""

    @staticmethod
    def create_chat(
        session: Session,
        user_id: int,
        chat_data: ChatCreate
    ) -> Chat:
        """
        Create a new chat

        Args:
            session: Database session
            user_id: User ID
            chat_data: Chat creation data

        Returns:
            Created chat
        """
        # Create empty history structure
        empty_history = ChatHelper.create_empty_history()

        # 使用前端传递的 id，如果没有则自动生成
        chat_id = chat_data.id if chat_data.id else str(uuid.uuid4())

        # Create chat
        chat = Chat(
            id=chat_id,
            user_id=user_id,
            title=chat_data.title,
            history=ChatHelper.to_json_string(empty_history),
            model=chat_data.model,
            params=json.dumps(chat_data.params or {}),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            pinned=False,
            archived=False,
            message_count=0
        )

        session.add(chat)
        session.commit()
        session.refresh(chat)

        logger.info(f"Chat created: {chat.title} (ID: {chat.id}, User: {user_id})")
        return chat

    @staticmethod
    def get_chat_by_id(
        session: Session,
        chat_id: str,
        user_id: int
    ) -> Chat:
        """
        Get chat by ID (with permission check)

        Args:
            session: Database session
            chat_id: Chat ID
            user_id: User ID

        Returns:
            Chat object

        Raises:
            NotFoundException: If chat not found
            ForbiddenException: If user doesn't own the chat
        """
        chat = session.get(Chat, chat_id)
        if not chat:
            raise NotFoundException(f"Chat with ID {chat_id} not found")

        # Check ownership
        if chat.user_id != user_id:
            raise ForbiddenException("You don't have permission to access this chat")

        return chat

    @staticmethod
    def get_user_chats(
        session: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 50,
        archived: bool = False,
        search: Optional[str] = None
    ) -> Tuple[List[Chat], int]:
        """
        Get user's chat list with pagination

        Args:
            session: Database session
            user_id: User ID
            page: Page number (1-indexed)
            page_size: Items per page
            archived: Filter by archived status
            search: Search keyword for title

        Returns:
            Tuple of (chats list, total count)
        """
        # Base query
        statement = select(Chat).where(
            Chat.user_id == user_id,
            Chat.archived == archived
        )

        # Apply search filter
        if search:
            statement = statement.where(Chat.title.contains(search))

        # Get total count
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        # Apply pagination
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        # Order by pinned first, then by updated_at descending
        statement = statement.order_by(
            Chat.pinned.desc(),
            Chat.updated_at.desc()
        )

        # Execute query
        chats = session.exec(statement).all()

        return chats, total

    @staticmethod
    def update_chat(
        session: Session,
        chat_id: str,
        user_id: int,
        chat_data: ChatUpdate
    ) -> Chat:
        """
        Update chat

        Args:
            session: Database session
            chat_id: Chat ID
            user_id: User ID
            chat_data: Update data

        Returns:
            Updated chat

        Raises:
            NotFoundException: If chat not found
            ForbiddenException: If user doesn't own the chat
        """
        # Get chat with permission check
        chat = ChatService.get_chat_by_id(session, chat_id, user_id)

        # Update fields
        if chat_data.title is not None:
            chat.title = chat_data.title

        if chat_data.history is not None:
            # Validate and convert history to JSON string
            chat.history = ChatHelper.to_json_string(chat_data.history)
            # Update message count
            chat.message_count = ChatHelper.count_messages(chat_data.history)

        if chat_data.model is not None:
            chat.model = chat_data.model

        if chat_data.params is not None:
            chat.params = json.dumps(chat_data.params)

        chat.updated_at = datetime.now(timezone.utc)

        session.add(chat)
        session.commit()
        session.refresh(chat)

        logger.info(f"Chat updated: {chat.title} (ID: {chat_id})")
        return chat

    @staticmethod
    def delete_chat(
        session: Session,
        chat_id: str,
        user_id: int
    ) -> None:
        """
        Delete chat

        Args:
            session: Database session
            chat_id: Chat ID
            user_id: User ID

        Raises:
            NotFoundException: If chat not found
            ForbiddenException: If user doesn't own the chat
        """
        # Get chat with permission check
        chat = ChatService.get_chat_by_id(session, chat_id, user_id)

        session.delete(chat)
        session.commit()

        logger.info(f"Chat deleted: {chat.title} (ID: {chat_id})")

    @staticmethod
    def toggle_pin(
        session: Session,
        chat_id: str,
        user_id: int
    ) -> Chat:
        """
        Toggle chat pin status

        Args:
            session: Database session
            chat_id: Chat ID
            user_id: User ID

        Returns:
            Updated chat

        Raises:
            NotFoundException: If chat not found
            ForbiddenException: If user doesn't own the chat
        """
        # Get chat with permission check
        chat = ChatService.get_chat_by_id(session, chat_id, user_id)

        # Toggle pinned status
        chat.pinned = not chat.pinned
        chat.updated_at = datetime.now(timezone.utc)

        session.add(chat)
        session.commit()
        session.refresh(chat)

        status = "pinned" if chat.pinned else "unpinned"
        logger.info(f"Chat {status}: {chat.title} (ID: {chat_id})")
        return chat

    @staticmethod
    def toggle_archive(
        session: Session,
        chat_id: str,
        user_id: int
    ) -> Chat:
        """
        Toggle chat archive status

        Args:
            session: Database session
            chat_id: Chat ID
            user_id: User ID

        Returns:
            Updated chat

        Raises:
            NotFoundException: If chat not found
            ForbiddenException: If user doesn't own the chat
        """
        # Get chat with permission check
        chat = ChatService.get_chat_by_id(session, chat_id, user_id)

        # Toggle archived status
        chat.archived = not chat.archived
        chat.updated_at = datetime.now(timezone.utc)

        # If archiving, also unpin
        if chat.archived:
            chat.pinned = False

        session.add(chat)
        session.commit()
        session.refresh(chat)

        status = "archived" if chat.archived else "unarchived"
        logger.info(f"Chat {status}: {chat.title} (ID: {chat_id})")
        return chat

    @staticmethod
    def search_chats(
        session: Session,
        user_id: int,
        keyword: str,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[Chat], int]:
        """
        Search chats by keyword

        Args:
            session: Database session
            user_id: User ID
            keyword: Search keyword
            page: Page number
            page_size: Items per page

        Returns:
            Tuple of (chats list, total count)
        """
        # Search in title
        statement = select(Chat).where(
            Chat.user_id == user_id,
            Chat.title.contains(keyword)
        )

        # Get total count
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        # Apply pagination
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        # Order by relevance (exact match first), then by updated_at
        statement = statement.order_by(Chat.updated_at.desc())

        # Execute query
        chats = session.exec(statement).all()

        return chats, total

    @staticmethod
    def delete_all_user_chats(
        session: Session,
        user_id: int
    ) -> int:
        """
        Delete all chats for a user

        Args:
            session: Database session
            user_id: User ID

        Returns:
            Number of chats deleted
        """
        statement = select(Chat).where(Chat.user_id == user_id)
        chats = session.exec(statement).all()

        count = len(chats)
        for chat in chats:
            session.delete(chat)

        session.commit()

        logger.info(f"Deleted {count} chats for user {user_id}")
        return count
