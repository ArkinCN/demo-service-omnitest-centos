"""
User service for CRUD operations
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlmodel import Session, select, func, or_, case

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.exceptions import NotFoundException, ConflictException
from app.core.logger import logger


class UserService:
    """User CRUD service"""

    @staticmethod
    def create_user(session: Session, user_data: UserCreate) -> User:
        """
        Create a new user

        Args:
            session: Database session
            user_data: User creation data

        Returns:
            Created user

        Raises:
            ConflictException: If username or email already exists
        """
        # Check if username exists
        statement = select(User).where(User.username == user_data.username)
        existing_user = session.exec(statement).first()
        if existing_user:
            raise ConflictException(f"Username '{user_data.username}' already exists")

        # Check if email exists
        statement = select(User).where(User.email == user_data.email)
        existing_user = session.exec(statement).first()
        if existing_user:
            raise ConflictException(f"Email '{user_data.email}' already exists")

        # Create user
        user = User(
            username=user_data.username,
            email=user_data.email,
            nickname=user_data.nickname,
            company=user_data.company,
            real_name=user_data.real_name,
            auth_type=user_data.auth_type,
            role=user_data.role
        )

        # Set password if provided (for EMAIL auth)
        if user_data.password and user_data.auth_type == "EMAIL":
            user.set_password(user_data.password)

        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info(f"User created: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def get_user_by_id(session: Session, user_id: int) -> User:
        """
        Get user by ID

        Args:
            session: Database session
            user_id: User ID

        Returns:
            User object

        Raises:
            NotFoundException: If user not found
        """
        user = session.get(User, user_id)
        if not user:
            raise NotFoundException(f"User with ID {user_id} not found")
        return user

    @staticmethod
    def get_user_by_username(session: Session, username: str) -> Optional[User]:
        """
        Get user by username

        Args:
            session: Database session
            username: Username

        Returns:
            User object or None
        """
        statement = select(User).where(User.username == username)
        return session.exec(statement).first()

    @staticmethod
    def get_user_by_email(session: Session, email: str) -> Optional[User]:
        """
        Get user by email

        Args:
            session: Database session
            email: Email address

        Returns:
            User object or None
        """
        statement = select(User).where(User.email == email)
        return session.exec(statement).first()

    @staticmethod
    def update_user(session: Session, user_id: int, user_data: UserUpdate) -> User:
        """
        Update user information

        Args:
            session: Database session
            user_id: User ID
            user_data: Update data

        Returns:
            Updated user

        Raises:
            NotFoundException: If user not found
            ConflictException: If email already exists
        """
        user = UserService.get_user_by_id(session, user_id)

        # Check email uniqueness if updating email
        if user_data.email and user_data.email != user.email:
            statement = select(User).where(User.email == user_data.email)
            existing_user = session.exec(statement).first()
            if existing_user:
                raise ConflictException(f"Email '{user_data.email}' already exists")

        # Update fields
        update_data = user_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(user, key, value)

        user.updated_at = datetime.now(timezone.utc)

        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info(f"User updated: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def update_avatar(session: Session, user_id: int, avatar_url: str) -> User:
        """
        Update user avatar URL

        Args:
            session: Database session
            user_id: User ID
            avatar_url: New avatar URL

        Returns:
            Updated user

        Raises:
            NotFoundException: If user not found
        """
        user = UserService.get_user_by_id(session, user_id)
        user.avatar_url = avatar_url
        user.updated_at = datetime.now(timezone.utc)

        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info(f"User avatar updated: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def update_user_status(session: Session, user_id: int, is_active: bool) -> User:
        """
        Update user active status

        Args:
            session: Database session
            user_id: User ID
            is_active: Active status

        Returns:
            Updated user

        Raises:
            NotFoundException: If user not found
        """
        user = UserService.get_user_by_id(session, user_id)
        user.is_active = is_active
        user.updated_at = datetime.now(timezone.utc)

        session.add(user)
        session.commit()
        session.refresh(user)

        status_str = "enabled" if is_active else "disabled"
        logger.info(f"User {status_str}: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def delete_user(session: Session, user_id: int) -> None:
        """
        Delete user

        Args:
            session: Database session
            user_id: User ID

        Raises:
            NotFoundException: If user not found
        """
        from app.models.email_verification import EmailVerification
        from app.models.invitation_code import InvitationCode

        user = UserService.get_user_by_id(session, user_id)

        # Clean up email verifications
        verifications = session.exec(
            select(EmailVerification).where(EmailVerification.user_id == user_id)
        ).all()
        for v in verifications:
            session.delete(v)

        # Clear invitation code references (created_by / used_by)
        created_codes = session.exec(
            select(InvitationCode).where(InvitationCode.created_by == user_id)
        ).all()
        for c in created_codes:
            c.created_by = None
            session.add(c)

        used_codes = session.exec(
            select(InvitationCode).where(InvitationCode.used_by == user_id)
        ).all()
        for c in used_codes:
            c.used_by = None
            session.add(c)

        session.delete(user)
        session.commit()

        logger.info(f"User deleted: {user.username} (ID: {user.id})")

    @staticmethod
    def update_last_login(session: Session, user_id: int) -> None:
        """
        Update user's last login time

        Args:
            session: Database session
            user_id: User ID
        """
        user = UserService.get_user_by_id(session, user_id)
        user.last_login_at = datetime.now(timezone.utc)
        session.add(user)
        session.commit()

    @staticmethod
    def set_watermark_consent(session: Session, user_id: int) -> User:
        """Accept watermark consent"""
        user = UserService.get_user_by_id(session, user_id)
        user.watermark_consent_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"User accepted watermark consent: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def revoke_watermark_consent(session: Session, user_id: int) -> User:
        """Revoke watermark consent"""
        user = UserService.get_user_by_id(session, user_id)
        user.watermark_consent_at = None
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"User revoked watermark consent: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def get_users_paginated(
        session: Session,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        role: Optional[str] = None,
        auth_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        group_id: Optional[int] = None,
        include_subgroups: bool = False,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = "desc"
    ) -> Tuple[List[User], int]:
        """
        Get paginated user list with filters

        Args:
            session: Database session
            page: Page number (1-indexed)
            page_size: Items per page
            keyword: Search keyword (username, email, nickname)
            role: Filter by role
            auth_type: Filter by auth type (LDAP/EMAIL)
            is_active: Filter by active status
            group_id: Filter by group membership
            include_subgroups: Include users from subgroups
            sort_by: Field to sort by (last_active_at, created_at, etc.)
            sort_order: Sort order (asc/desc)

        Returns:
            Tuple of (users list, total count)
        """
        from app.models.user_group import UserGroupMember
        from app.services.user_group_service import UserGroupService

        # Base query (soft-deleted accounts are excluded)
        statement = select(User).where(User.deleted_at.is_(None))

        # Apply group filter if specified
        if group_id is not None:
            if include_subgroups:
                # Get all group IDs including descendants
                group_ids = UserGroupService.get_group_with_descendants_ids(session, group_id)
            else:
                group_ids = [group_id]

            # Join with membership table
            statement = statement.join(
                UserGroupMember,
                User.id == UserGroupMember.user_id
            ).where(UserGroupMember.group_id.in_(group_ids)).distinct()

        # Apply filters
        search_rank = None
        if keyword:
            # Create search condition
            keyword_lower = keyword.lower()
            search_condition = or_(
                User.username.contains(keyword),
                User.email.contains(keyword),
                User.nickname.contains(keyword)
            )
            statement = statement.where(search_condition)

            # Add search ranking for better results ordering
            # Priority: exact match > starts with > contains
            search_rank = case(
                # Exact match (highest priority = 1)
                (or_(
                    func.lower(User.username) == keyword_lower,
                    func.lower(User.email) == keyword_lower,
                    func.lower(User.nickname) == keyword_lower
                ), 1),
                # Starts with (priority = 2)
                (or_(
                    func.lower(User.username).startswith(keyword_lower),
                    func.lower(User.email).startswith(keyword_lower),
                    func.lower(User.nickname).startswith(keyword_lower)
                ), 2),
                # Contains (lowest priority = 3)
                else_=3
            )

        if role:
            statement = statement.where(User.role == role)

        if auth_type:
            statement = statement.where(User.auth_type == auth_type.upper())

        if is_active is not None:
            statement = statement.where(User.is_active == is_active)

        # Get total count
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        # Determine sort column and order
        sort_column = None
        if sort_by:
            # Map sort_by to actual column (whitelist allowed fields for security)
            allowed_sort_fields = {
                'last_active_at': User.last_active_at,
                'created_at': User.created_at,
                'last_login_at': User.last_login_at,
                'username': User.username,
            }
            sort_column = allowed_sort_fields.get(sort_by)

        # Order by search relevance if keyword is provided, then by sort_by or created_at
        if search_rank is not None:
            if sort_column is not None:
                if sort_order == 'asc':
                    statement = statement.order_by(search_rank, sort_column.asc())
                else:
                    statement = statement.order_by(search_rank, sort_column.desc())
            else:
                statement = statement.order_by(search_rank, User.created_at.asc())
        else:
            if sort_column is not None:
                if sort_order == 'asc':
                    statement = statement.order_by(sort_column.asc())
                else:
                    statement = statement.order_by(sort_column.desc())
            else:
                # Default: order by created_at ascending (earlier users first)
                statement = statement.order_by(User.created_at.asc())

        # Apply pagination
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        # Execute query
        users = session.exec(statement).all()

        return users, total

    @staticmethod
    def update_last_active(user_id: int) -> None:
        """
        更新用户最后活跃时间（带节流）

        此方法被 throttle 装饰器包装，同一用户 60 秒内只会更新一次数据库。
        设计用于在 API 请求认证时调用，而非心跳。

        Args:
            user_id: 用户 ID
        """
        _update_last_active_throttled(user_id)


# 模块级别的节流函数，确保 throttle 状态在调用间持久化
def _update_last_active_throttled(user_id: int) -> None:
    """内部节流函数"""
    from app.db.session import get_session

    try:
        for session in get_session():
            user = session.get(User, user_id)
            if user:
                user.last_active_at = datetime.now(timezone.utc)
                session.add(user)
                session.commit()
                logger.debug(f"Updated last_active_at for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to update last_active_at for user {user_id}: {e}")


# 应用 throttle 装饰器
from app.utils.throttle import throttle
_update_last_active_throttled = throttle(60.0)(_update_last_active_throttled)
