"""
User Group service for CRUD operations
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlmodel import Session, select, func, text

from app.models.user import User
from app.models.user_group import UserGroup, UserGroupMember
from app.schemas.user_group import UserGroupCreate, UserGroupUpdate
from app.core.exceptions import NotFoundException, ConflictException, ForbiddenException
from app.core.logger import logger


class UserGroupService:
    """User Group CRUD service"""

    @staticmethod
    def create_group(session: Session, group_data: UserGroupCreate) -> UserGroup:
        """
        Create a new custom user group

        Args:
            session: Database session
            group_data: Group creation data

        Returns:
            Created group

        Raises:
            ConflictException: If group name already exists at same level
            NotFoundException: If parent group not found
        """
        # Check parent exists if specified
        if group_data.parent_id:
            parent = session.get(UserGroup, group_data.parent_id)
            if not parent:
                raise NotFoundException(f"Parent group with ID {group_data.parent_id} not found")

        # Check name uniqueness within same parent
        statement = select(UserGroup).where(
            UserGroup.name == group_data.name,
            UserGroup.parent_id == group_data.parent_id,
            UserGroup.group_type == "CUSTOM"
        )
        existing = session.exec(statement).first()
        if existing:
            raise ConflictException(f"Group '{group_data.name}' already exists at this level")

        # Create group
        group = UserGroup(
            name=group_data.name,
            description=group_data.description,
            parent_id=group_data.parent_id,
            group_type="CUSTOM"
        )

        session.add(group)
        session.commit()
        session.refresh(group)

        logger.info(f"User group created: {group.name} (ID: {group.id})")
        return group

    @staticmethod
    def get_group_by_id(session: Session, group_id: int) -> UserGroup:
        """
        Get group by ID

        Args:
            session: Database session
            group_id: Group ID

        Returns:
            Group object

        Raises:
            NotFoundException: If group not found
        """
        group = session.get(UserGroup, group_id)
        if not group:
            raise NotFoundException(f"Group with ID {group_id} not found")
        return group

    @staticmethod
    def update_group(session: Session, group_id: int, group_data: UserGroupUpdate) -> UserGroup:
        """
        Update a custom user group (LDAP groups cannot be updated)

        Args:
            session: Database session
            group_id: Group ID
            group_data: Update data

        Returns:
            Updated group

        Raises:
            NotFoundException: If group not found
            ForbiddenException: If trying to update LDAP group
            ConflictException: If name conflicts
        """
        group = UserGroupService.get_group_by_id(session, group_id)

        # Cannot update LDAP groups
        if group.is_ldap_group:
            raise ForbiddenException("Cannot update LDAP groups")

        # Check name uniqueness if updating name
        if group_data.name and group_data.name != group.name:
            parent_id = group_data.parent_id if group_data.parent_id is not None else group.parent_id
            statement = select(UserGroup).where(
                UserGroup.name == group_data.name,
                UserGroup.parent_id == parent_id,
                UserGroup.group_type == "CUSTOM",
                UserGroup.id != group_id
            )
            existing = session.exec(statement).first()
            if existing:
                raise ConflictException(f"Group '{group_data.name}' already exists at this level")

        # Check parent exists if updating parent
        if group_data.parent_id is not None and group_data.parent_id != group.parent_id:
            if group_data.parent_id:
                parent = session.get(UserGroup, group_data.parent_id)
                if not parent:
                    raise NotFoundException(f"Parent group with ID {group_data.parent_id} not found")
                # Prevent circular reference
                if group_data.parent_id == group_id:
                    raise ConflictException("Cannot set group as its own parent")

        # Update fields
        update_data = group_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(group, key, value)

        group.updated_at = datetime.now(timezone.utc)

        session.add(group)
        session.commit()
        session.refresh(group)

        logger.info(f"User group updated: {group.name} (ID: {group.id})")
        return group

    @staticmethod
    def delete_group(session: Session, group_id: int) -> None:
        """
        Delete a custom user group (LDAP groups cannot be deleted)

        Args:
            session: Database session
            group_id: Group ID

        Raises:
            NotFoundException: If group not found
            ForbiddenException: If trying to delete LDAP group
        """
        group = UserGroupService.get_group_by_id(session, group_id)

        # Cannot delete LDAP groups
        if group.is_ldap_group:
            raise ForbiddenException("Cannot delete LDAP groups")

        # 该分组可能被统计页勾选（stat_group_selections 外键引用），需先清理
        from app.models.stat_group import StatGroupSelection
        selection = session.exec(
            select(StatGroupSelection).where(StatGroupSelection.user_group_id == group_id)
        ).first()
        if selection:
            session.delete(selection)

        session.delete(group)
        session.commit()

        logger.info(f"User group deleted: {group.name} (ID: {group.id})")

    @staticmethod
    def get_groups_paginated(
        session: Session,
        page: int = 1,
        page_size: int = 20,
        group_type: Optional[str] = None,
        parent_id: Optional[int] = None,
        keyword: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Tuple[List[UserGroup], int]:
        """
        Get paginated group list with filters

        Args:
            session: Database session
            page: Page number (1-indexed)
            page_size: Items per page
            group_type: Filter by group type (CUSTOM/LDAP)
            parent_id: Filter by parent ID (use -1 for root level)
            keyword: Search keyword
            is_active: Filter by active status

        Returns:
            Tuple of (groups list, total count)
        """
        statement = select(UserGroup)

        # Apply filters
        if group_type:
            statement = statement.where(UserGroup.group_type == group_type)

        if parent_id is not None:
            if parent_id == -1:
                # Root level groups
                statement = statement.where(UserGroup.parent_id.is_(None))
            else:
                statement = statement.where(UserGroup.parent_id == parent_id)

        if keyword:
            statement = statement.where(UserGroup.name.contains(keyword))

        if is_active is not None:
            statement = statement.where(UserGroup.is_active == is_active)

        # Get total count
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        # Apply pagination
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)
        statement = statement.order_by(UserGroup.name)

        groups = session.exec(statement).all()
        return groups, total

    @staticmethod
    def get_group_tree(
        session: Session,
        group_type: Optional[str] = None,
        is_active: Optional[bool] = True
    ) -> List[UserGroup]:
        """
        Get groups as a tree structure (root level groups with children)

        Args:
            session: Database session
            group_type: Filter by group type
            is_active: Filter by active status

        Returns:
            List of root-level groups (children populated via relationship)
        """
        statement = select(UserGroup).where(UserGroup.parent_id.is_(None))

        if group_type:
            statement = statement.where(UserGroup.group_type == group_type)

        if is_active is not None:
            statement = statement.where(UserGroup.is_active == is_active)

        statement = statement.order_by(UserGroup.name)
        return list(session.exec(statement).all())

    @staticmethod
    def get_group_user_count(session: Session, group_id: int) -> int:
        """Get direct member count for a group"""
        statement = select(func.count()).where(UserGroupMember.group_id == group_id)
        return session.exec(statement).one()

    @staticmethod
    def get_group_with_descendants_ids(session: Session, group_id: int) -> List[int]:
        """
        Get a group and all its descendant group IDs
        Uses iterative approach for MySQL 5.7 compatibility

        Args:
            session: Database session
            group_id: Root group ID

        Returns:
            List of group IDs (including the root group)
        """
        # Iterative approach compatible with MySQL 5.7
        result_ids = [group_id]
        current_level = [group_id]

        # Keep finding children until no more children exist
        while current_level:
            statement = select(UserGroup.id).where(UserGroup.parent_id.in_(current_level))
            children = session.exec(statement).all()

            if not children:
                break

            current_level = list(children)
            result_ids.extend(current_level)

        return result_ids

    @staticmethod
    def get_group_users(
        session: Session,
        group_id: int,
        include_children: bool = False,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[dict], int]:
        """
        Get users in a group

        Args:
            session: Database session
            group_id: Group ID
            include_children: Include users from child groups
            page: Page number
            page_size: Items per page

        Returns:
            Tuple of (users list with source info, total count)
        """
        # Verify group exists
        UserGroupService.get_group_by_id(session, group_id)

        if include_children:
            group_ids = UserGroupService.get_group_with_descendants_ids(session, group_id)
        else:
            group_ids = [group_id]

        # Query users with membership info
        statement = (
            select(User, UserGroupMember.source, UserGroupMember.created_at)
            .join(UserGroupMember, User.id == UserGroupMember.user_id)
            .where(UserGroupMember.group_id.in_(group_ids))
            .distinct(User.id)
        )

        # Get total count
        count_statement = select(func.count(func.distinct(User.id))).select_from(
            select(User.id)
            .join(UserGroupMember, User.id == UserGroupMember.user_id)
            .where(UserGroupMember.group_id.in_(group_ids))
            .subquery()
        )
        total = session.exec(count_statement).one()

        # Apply pagination
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)
        statement = statement.order_by(User.username)

        results = session.exec(statement).all()

        users = []
        for user, source, joined_at in results:
            user_dict = {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "auth_type": user.auth_type,
                "avatar_url": user.avatar_url,
                "source": source,
                "joined_at": joined_at
            }
            users.append(user_dict)

        return users, total

    @staticmethod
    def add_users_to_group(
        session: Session,
        group_id: int,
        user_ids: List[int],
        source: str = "MANUAL"
    ) -> int:
        """
        Add users to a group

        Args:
            session: Database session
            group_id: Group ID
            user_ids: List of user IDs
            source: Membership source (MANUAL/LDAP)

        Returns:
            Number of users added

        Raises:
            NotFoundException: If group not found
            ForbiddenException: If trying to manually add to LDAP group
        """
        group = UserGroupService.get_group_by_id(session, group_id)

        # Cannot manually add to LDAP groups
        if group.is_ldap_group and source == "MANUAL":
            raise ForbiddenException("Cannot manually add users to LDAP groups")

        added_count = 0
        for user_id in user_ids:
            # Check user exists
            user = session.get(User, user_id)
            if not user:
                logger.warning(f"User {user_id} not found, skipping")
                continue

            # Check if already member
            statement = select(UserGroupMember).where(
                UserGroupMember.user_id == user_id,
                UserGroupMember.group_id == group_id
            )
            existing = session.exec(statement).first()
            if existing:
                continue

            # Add membership
            member = UserGroupMember(
                user_id=user_id,
                group_id=group_id,
                source=source
            )
            session.add(member)
            added_count += 1

        session.commit()
        logger.info(f"Added {added_count} users to group {group.name} (ID: {group_id})")
        return added_count

    @staticmethod
    def remove_users_from_group(
        session: Session,
        group_id: int,
        user_ids: List[int],
        source_filter: Optional[str] = None
    ) -> int:
        """
        Remove users from a group

        Args:
            session: Database session
            group_id: Group ID
            user_ids: List of user IDs
            source_filter: Only remove if source matches (for LDAP sync)

        Returns:
            Number of users removed
        """
        group = UserGroupService.get_group_by_id(session, group_id)

        # Cannot manually remove from LDAP groups
        if group.is_ldap_group and source_filter != "LDAP":
            raise ForbiddenException("Cannot manually remove users from LDAP groups")

        removed_count = 0
        for user_id in user_ids:
            statement = select(UserGroupMember).where(
                UserGroupMember.user_id == user_id,
                UserGroupMember.group_id == group_id
            )
            if source_filter:
                statement = statement.where(UserGroupMember.source == source_filter)

            member = session.exec(statement).first()
            if member:
                session.delete(member)
                removed_count += 1

        session.commit()
        logger.info(f"Removed {removed_count} users from group {group.name} (ID: {group_id})")
        return removed_count

    @staticmethod
    def get_user_groups(session: Session, user_id: int, direct_only: bool = False) -> List[UserGroup]:
        """
        Get all groups a user belongs to

        Args:
            session: Database session
            user_id: User ID
            direct_only: If True, only return the most specific (direct) group

        Returns:
            List of groups
        """
        statement = (
            select(UserGroup)
            .join(UserGroupMember, UserGroup.id == UserGroupMember.group_id)
            .where(UserGroupMember.user_id == user_id)
            .order_by(UserGroup.name)
        )
        groups = list(session.exec(statement).all())

        if direct_only and groups:
            # Find the most specific group (the one that has no children in user's groups)
            # For LDAP groups, this is the deepest level in the OU hierarchy
            group_ids = {g.id for g in groups}
            direct_groups = [g for g in groups if g.parent_id in group_ids or g.parent_id is None]
            # Actually we want groups whose id is NOT a parent of any other group
            parent_ids = {g.parent_id for g in groups if g.parent_id is not None}
            direct_groups = [g for g in groups if g.id not in parent_ids]
            return direct_groups[:1] if direct_groups else groups[:1]

        return groups

    @staticmethod
    def get_or_create_ldap_group(
        session: Session,
        name: str,
        ldap_dn: str,
        parent_id: Optional[int] = None
    ) -> UserGroup:
        """
        Get or create an LDAP group

        Args:
            session: Database session
            name: Group name (OU name)
            ldap_dn: Full LDAP DN for this OU
            parent_id: Parent group ID

        Returns:
            UserGroup object
        """
        # Try to find by ldap_dn
        statement = select(UserGroup).where(UserGroup.ldap_dn == ldap_dn)
        group = session.exec(statement).first()

        if group:
            # Update name if changed
            if group.name != name:
                group.name = name
                group.updated_at = datetime.now(timezone.utc)
                session.add(group)
            return group

        # Create new LDAP group
        group = UserGroup(
            name=name,
            ldap_dn=ldap_dn,
            parent_id=parent_id,
            group_type="LDAP"
        )
        session.add(group)
        session.flush()  # Get ID without committing

        logger.info(f"LDAP group created: {name} (DN: {ldap_dn})")
        return group

    @staticmethod
    def update_user_ldap_groups(
        session: Session,
        user_id: int,
        group_ids: List[int]
    ) -> None:
        """
        Update a user's LDAP group memberships (full replacement)

        Args:
            session: Database session
            user_id: User ID
            group_ids: New list of LDAP group IDs
        """
        # Remove existing LDAP memberships
        statement = select(UserGroupMember).where(
            UserGroupMember.user_id == user_id,
            UserGroupMember.source == "LDAP"
        )
        existing = session.exec(statement).all()
        for member in existing:
            session.delete(member)

        # Flush to ensure deletes are executed before inserts
        session.flush()

        # Add new memberships (check for duplicates to avoid constraint violations)
        for group_id in group_ids:
            # Check if membership already exists (could be MANUAL source)
            check_statement = select(UserGroupMember).where(
                UserGroupMember.user_id == user_id,
                UserGroupMember.group_id == group_id
            )
            existing_member = session.exec(check_statement).first()

            if not existing_member:
                member = UserGroupMember(
                    user_id=user_id,
                    group_id=group_id,
                    source="LDAP"
                )
                session.add(member)
