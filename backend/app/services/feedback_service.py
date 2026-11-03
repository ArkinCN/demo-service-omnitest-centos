"""
Feedback service for CRUD operations
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from sqlmodel import Session, select, func, or_
import json

from app.models.feedback import Feedback, FeedbackReply, FeedbackModule
from app.models.user import User
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackUpdate,
    FeedbackReplyCreate,
    FeedbackStatsResponse
)
from app.core.exceptions import NotFoundException, ForbiddenException
from app.core.logger import logger


def _to_dict(feedback: Feedback, nickname: str, module_name: str) -> Dict[str, Any]:
    """把 Feedback 行转成接口返回 dict（附昵称与模块名）。

    2026-10-05 清理合并：此前这段 16 字段 dict 在 `get_feedback_by_id` 与
    `get_all_feedbacks` 里各复制了一份，字段一改就漏一边。抽成单一构造点。
    """
    return {
        "id": feedback.id,
        "user_id": feedback.user_id,
        "nickname": nickname,
        "module_id": feedback.module_id,
        "module_name": module_name,
        "category": feedback.category,
        "description": feedback.description,
        "contact_info": feedback.contact_info,
        "attachments": feedback.attachments,
        "status": feedback.status,
        "priority": feedback.priority,
        "assigned_to": feedback.assigned_to,
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
        "resolved_at": feedback.resolved_at,
    }


class FeedbackService:
    """Feedback CRUD service"""

    @staticmethod
    def create_feedback(session: Session, user_id: int, feedback_data: FeedbackCreate) -> Feedback:
        """
        Create a new feedback

        Args:
            session: Database session
            user_id: User ID who submitted the feedback
            feedback_data: Feedback creation data

        Returns:
            Created feedback

        Raises:
            NotFoundException: If user not found
        """
        # Verify user exists
        user = session.get(User, user_id)
        if not user:
            raise NotFoundException(f"User with ID {user_id} not found")

        # Create feedback
        feedback = Feedback(
            user_id=user_id,
            module_id=feedback_data.module_id,
            category=feedback_data.category,
            description=feedback_data.description,
            contact_info=feedback_data.contact_info,
            attachments=json.dumps(feedback_data.attachments),
            status="PENDING",
            priority="MEDIUM"
        )

        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        logger.info(f"Feedback created: ID={feedback.id}, User={user_id}, Category={feedback.category}")
        return feedback

    @staticmethod
    def get_feedback_by_id(session: Session, feedback_id: int, user_id: int, is_admin: bool = False) -> Dict[str, Any]:
        """
        Get feedback by ID

        Args:
            session: Database session
            feedback_id: Feedback ID
            user_id: Current user ID
            is_admin: Whether the user is an admin

        Returns:
            Feedback dict with nickname and module_name

        Raises:
            NotFoundException: If feedback not found
            ForbiddenException: If user doesn't have access
        """
        # Query feedback with nickname and module_name (left join for module)
        statement = (
            select(Feedback, User.nickname, FeedbackModule.name)
            .join(User, Feedback.user_id == User.id)
            .outerjoin(FeedbackModule, Feedback.module_id == FeedbackModule.id)
            .where(Feedback.id == feedback_id)
        )
        result = session.exec(statement).first()

        if not result:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        feedback, nickname, module_name = result

        # Check access permission (owner or admin)
        if not is_admin and feedback.user_id != user_id:
            raise ForbiddenException("You don't have permission to access this feedback")

        return _to_dict(feedback, nickname, module_name)

    @staticmethod
    def get_user_feedbacks(
        session: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Feedback], int]:
        """
        Get feedbacks submitted by a specific user (paginated)

        Args:
            session: Database session
            user_id: User ID
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Tuple of (feedbacks list, total count)
        """
        # Count total
        statement = select(func.count(Feedback.id)).where(Feedback.user_id == user_id)
        total = session.exec(statement).one()

        # Get paginated results
        offset = (page - 1) * page_size
        statement = (
            select(Feedback)
            .where(Feedback.user_id == user_id)
            .order_by(Feedback.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        feedbacks = session.exec(statement).all()

        return list(feedbacks), total

    @staticmethod
    def get_all_feedbacks(
        session: Session,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        module_id: Optional[int] = None,
        keyword: Optional[str] = None,
        sort_order: Optional[str] = "desc",
        hide_resolved: bool = True
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get all feedbacks with optional filters (admin only, paginated)

        Args:
            session: Database session
            page: Page number (1-indexed)
            page_size: Number of items per page
            status: Filter by status
            priority: Filter by priority
            category: Filter by category
            module_id: Filter by module ID
            keyword: Search keyword (searches in description)
            sort_order: Sort order for created_at (asc/desc, default: desc)
            hide_resolved: Hide resolved and closed feedbacks (default: True)

        Returns:
            Tuple of (feedback dicts with nickname and module_name, total count)
        """
        # Build query joining with User table and FeedbackModule table
        statement = (
            select(Feedback, User.nickname, FeedbackModule.name)
            .join(User, Feedback.user_id == User.id)
            .outerjoin(FeedbackModule, Feedback.module_id == FeedbackModule.id)
        )

        # Apply filters
        if status:
            statement = statement.where(Feedback.status == status.upper())
        elif hide_resolved:
            # 如果没有指定状态筛选，且 hide_resolved 为 True，则排除已解决和已关闭的反馈
            statement = statement.where(Feedback.status.notin_(["RESOLVED", "CLOSED"]))
        if priority:
            statement = statement.where(Feedback.priority == priority.upper())
        if category:
            statement = statement.where(Feedback.category == category.upper())
        if module_id is not None:
            statement = statement.where(Feedback.module_id == module_id)
        if keyword:
            statement = statement.where(
                or_(
                    Feedback.description.contains(keyword),
                    Feedback.contact_info.contains(keyword)
                )
            )

        # Count total
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        # Get paginated results with sort order
        offset = (page - 1) * page_size
        if sort_order == "asc":
            statement = statement.order_by(Feedback.created_at.asc()).offset(offset).limit(page_size)
        else:
            statement = statement.order_by(Feedback.created_at.desc()).offset(offset).limit(page_size)
        results = session.exec(statement).all()

        # Convert to dict and add nickname and module_name
        feedbacks = [_to_dict(feedback, nickname, module_name) for feedback, nickname, module_name in results]

        return feedbacks, total

    @staticmethod
    def update_feedback_status(
        session: Session,
        feedback_id: int,
        status: str
    ) -> Feedback:
        """
        Update feedback status (admin only)

        Args:
            session: Database session
            feedback_id: Feedback ID
            status: New status

        Returns:
            Updated feedback

        Raises:
            NotFoundException: If feedback not found
        """
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        old_status = feedback.status
        feedback.status = status.upper()
        feedback.updated_at = datetime.now(timezone.utc)

        # Set resolved_at if status changed to RESOLVED
        if status.upper() == "RESOLVED" and old_status != "RESOLVED":
            feedback.resolved_at = datetime.now(timezone.utc)

        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        logger.info(f"Feedback {feedback_id} status updated: {old_status} -> {status}")
        return feedback

    @staticmethod
    def update_feedback_priority(
        session: Session,
        feedback_id: int,
        priority: str
    ) -> Feedback:
        """
        Update feedback priority (admin only)

        Args:
            session: Database session
            feedback_id: Feedback ID
            priority: New priority

        Returns:
            Updated feedback

        Raises:
            NotFoundException: If feedback not found
        """
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        old_priority = feedback.priority
        feedback.priority = priority.upper()
        feedback.updated_at = datetime.now(timezone.utc)

        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        logger.info(f"Feedback {feedback_id} priority updated: {old_priority} -> {priority}")
        return feedback

    @staticmethod
    def update_feedback_module(
        session: Session,
        feedback_id: int,
        module_id: Optional[int]
    ) -> Feedback:
        """
        Update feedback module (admin only)

        Args:
            session: Database session
            feedback_id: Feedback ID
            module_id: New module ID (None to clear)

        Returns:
            Updated feedback

        Raises:
            NotFoundException: If feedback not found
        """
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        old_module_id = feedback.module_id
        feedback.module_id = module_id
        feedback.updated_at = datetime.now(timezone.utc)

        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        logger.info(f"Feedback {feedback_id} module updated: {old_module_id} -> {module_id}")
        return feedback

    @staticmethod
    def assign_feedback(
        session: Session,
        feedback_id: int,
        admin_id: int
    ) -> Feedback:
        """
        Assign feedback to an admin (admin only)

        Args:
            session: Database session
            feedback_id: Feedback ID
            admin_id: Admin user ID to assign to

        Returns:
            Updated feedback

        Raises:
            NotFoundException: If feedback or admin not found
        """
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        # Verify admin exists and is admin
        admin = session.get(User, admin_id)
        if not admin:
            raise NotFoundException(f"User with ID {admin_id} not found")
        if admin.role != "admin":
            raise ForbiddenException(f"User {admin_id} is not an admin")

        feedback.assigned_to = admin_id
        feedback.updated_at = datetime.now(timezone.utc)

        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        logger.info(f"Feedback {feedback_id} assigned to admin {admin_id}")
        return feedback

    @staticmethod
    def add_reply(
        session: Session,
        feedback_id: int,
        user_id: int,
        reply_data: FeedbackReplyCreate,
        is_admin: bool = False
    ) -> FeedbackReply:
        """
        Add a reply to feedback

        Args:
            session: Database session
            feedback_id: Feedback ID
            user_id: User ID who is replying
            reply_data: Reply data
            is_admin: Whether the user is an admin

        Returns:
            Created reply

        Raises:
            NotFoundException: If feedback not found
            ForbiddenException: If non-admin tries to create internal note
        """
        # Verify feedback exists
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        # Only admins can create internal notes
        if reply_data.is_internal and not is_admin:
            raise ForbiddenException("Only admins can create internal notes")

        # Create reply
        reply = FeedbackReply(
            feedback_id=feedback_id,
            user_id=user_id,
            content=reply_data.content,
            is_internal=reply_data.is_internal
        )

        session.add(reply)

        # Update feedback's updated_at
        feedback.updated_at = datetime.now(timezone.utc)
        session.add(feedback)

        session.commit()
        session.refresh(reply)

        logger.info(f"Reply added to feedback {feedback_id} by user {user_id}")
        return reply

    @staticmethod
    def get_replies(
        session: Session,
        feedback_id: int,
        is_admin: bool = False
    ) -> List[FeedbackReply]:
        """
        Get all replies for a feedback

        Args:
            session: Database session
            feedback_id: Feedback ID
            is_admin: Whether the user is an admin (admins see internal notes)

        Returns:
            List of replies

        Raises:
            NotFoundException: If feedback not found
        """
        # Verify feedback exists
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            raise NotFoundException(f"Feedback with ID {feedback_id} not found")

        # Build query
        statement = select(FeedbackReply).where(FeedbackReply.feedback_id == feedback_id)

        # Filter out internal notes for non-admins
        if not is_admin:
            statement = statement.where(FeedbackReply.is_internal == False)

        statement = statement.order_by(FeedbackReply.created_at.asc())
        replies = session.exec(statement).all()

        return list(replies)

    @staticmethod
    def get_stats(session: Session) -> FeedbackStatsResponse:
        """
        Get feedback statistics (admin only)

        Args:
            session: Database session

        Returns:
            Statistics response
        """
        # Count by status
        pending_count = session.exec(
            select(func.count(Feedback.id)).where(Feedback.status == "PENDING")
        ).one()

        in_progress_count = session.exec(
            select(func.count(Feedback.id)).where(Feedback.status == "IN_PROGRESS")
        ).one()

        resolved_count = session.exec(
            select(func.count(Feedback.id)).where(Feedback.status == "RESOLVED")
        ).one()

        total_count = session.exec(select(func.count(Feedback.id))).one()

        return FeedbackStatsResponse(
            pending_count=pending_count,
            in_progress_count=in_progress_count,
            resolved_count=resolved_count,
            total_count=total_count
        )
