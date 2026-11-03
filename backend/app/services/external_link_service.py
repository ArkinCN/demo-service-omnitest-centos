"""
External Link service for CRUD operations and business logic
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict
from sqlmodel import Session, select, func, or_, delete
import json

from app.models.external_link import ExternalLink, ExternalLinkClick
from app.models.user import User
from app.schemas.external_link import ExternalLinkCreate, ExternalLinkUpdate
from app.core.exceptions import NotFoundException, ConflictException, ForbiddenException
from app.core.logger import logger


class ExternalLinkService:
    """External Link CRUD service"""

    @staticmethod
    def create_link(session: Session, link_data: ExternalLinkCreate, current_user_id: int) -> ExternalLink:
        """
        Create a new external link

        Args:
            session: Database session
            link_data: Link creation data
            current_user_id: Current user ID

        Returns:
            Created link

        Raises:
            NotFoundException: If maintainer not found
        """
        # Verify maintainer exists if specified
        if link_data.maintainer_id:
            maintainer = session.get(User, link_data.maintainer_id)
            if not maintainer:
                raise NotFoundException(f"Maintainer with ID {link_data.maintainer_id} not found")

        # Get max order for category to append at the end
        max_order_stmt = select(func.max(ExternalLink.link_order)).where(
            ExternalLink.category == link_data.category
        )
        max_order = session.exec(max_order_stmt).first() or 0

        # Get category order (use existing or create new)
        category_order_stmt = select(ExternalLink.category_order).where(
            ExternalLink.category == link_data.category
        ).limit(1)
        category_order = session.exec(category_order_stmt).first()

        if category_order is None:
            # New category, get max category order
            max_category_order_stmt = select(func.max(ExternalLink.category_order))
            category_order = (session.exec(max_category_order_stmt).first() or 0) + 1

        # Create link
        link = ExternalLink(
            title=link_data.title,
            url=link_data.url,
            description=link_data.description,
            icon_url=link_data.icon_url,
            category=link_data.category,
            category_order=category_order,
            link_order=max_order + 1,
            maintainer_id=link_data.maintainer_id,
            created_by=current_user_id,
            visibility=link_data.visibility,
            allowed_group_ids=json.dumps(link_data.allowed_group_ids),
            allowed_user_ids=json.dumps(link_data.allowed_user_ids),
            period_type=link_data.period_type,
            start_time=link_data.start_time,
            end_time=link_data.end_time,
            time_pattern=link_data.time_pattern,
            status=link_data.status,
            related_links_url=json.dumps([rl.model_dump() for rl in link_data.related_links_url])
        )

        session.add(link)
        session.commit()
        session.refresh(link)

        logger.info(f"External link created: {link.title} (ID: {link.id}) by user {current_user_id}")
        return link

    @staticmethod
    def get_link_by_id(session: Session, link_id: int) -> ExternalLink:
        """
        Get link by ID

        Args:
            session: Database session
            link_id: Link ID

        Returns:
            Link object

        Raises:
            NotFoundException: If link not found
        """
        link = session.get(ExternalLink, link_id)
        if not link:
            raise NotFoundException(f"Link with ID {link_id} not found")
        return link

    @staticmethod
    def update_link(
        session: Session,
        link_id: int,
        link_data: ExternalLinkUpdate,
        current_user_id: int
    ) -> ExternalLink:
        """
        Update an external link

        Args:
            session: Database session
            link_id: Link ID
            link_data: Update data
            current_user_id: Current user ID

        Returns:
            Updated link

        Raises:
            NotFoundException: If link or maintainer not found
        """
        link = ExternalLinkService.get_link_by_id(session, link_id)

        # Verify maintainer exists if updating
        if link_data.maintainer_id:
            maintainer = session.get(User, link_data.maintainer_id)
            if not maintainer:
                raise NotFoundException(f"Maintainer with ID {link_data.maintainer_id} not found")

        # If category is changing, update category_order
        if link_data.category and link_data.category != link.category:
            category_order_stmt = select(ExternalLink.category_order).where(
                ExternalLink.category == link_data.category
            ).limit(1)
            category_order = session.exec(category_order_stmt).first()

            if category_order is None:
                # New category, get max category order
                max_category_order_stmt = select(func.max(ExternalLink.category_order))
                category_order = (session.exec(max_category_order_stmt).first() or 0) + 1

            link.category_order = category_order

            # Update link_order to append at end of new category
            max_order_stmt = select(func.max(ExternalLink.link_order)).where(
                ExternalLink.category == link_data.category
            )
            max_order = session.exec(max_order_stmt).first() or 0
            link.link_order = max_order + 1

        # Update fields
        update_data = link_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key == 'allowed_group_ids' and value is not None:
                setattr(link, key, json.dumps(value))
            elif key == 'allowed_user_ids' and value is not None:
                setattr(link, key, json.dumps(value))
            elif key == 'related_links_url' and value is not None:
                setattr(link, key, json.dumps([rl if isinstance(rl, dict) else rl.model_dump() for rl in value]))
            else:
                setattr(link, key, value)

        link.updated_at = datetime.now(timezone.utc)

        session.add(link)
        session.commit()
        session.refresh(link)

        logger.info(f"External link updated: {link.title} (ID: {link.id}) by user {current_user_id}")
        return link

    @staticmethod
    def delete_link(session: Session, link_id: int, current_user_id: int) -> None:
        """
        Delete an external link and all associated click records

        Args:
            session: Database session
            link_id: Link ID
            current_user_id: Current user ID

        Raises:
            NotFoundException: If link not found
        """
        link = ExternalLinkService.get_link_by_id(session, link_id)

        # Delete all associated click records first to avoid foreign key constraint error
        click_delete_stmt = delete(ExternalLinkClick).where(ExternalLinkClick.link_id == link_id)
        session.exec(click_delete_stmt)

        # Now delete the link itself
        session.delete(link)
        session.commit()

        logger.info(f"External link deleted: {link.title} (ID: {link.id}) by user {current_user_id}")

    @staticmethod
    def get_links_paginated(
        session: Session,
        page: int = 1,
        page_size: int = 20,
        category: Optional[str] = None,
        status: Optional[str] = None,
        visibility: Optional[str] = None,
        period_type: Optional[str] = None,
        keyword: Optional[str] = None,
        created_by: Optional[int] = None,
        current_user_id: Optional[int] = None,
        current_user_group_ids: Optional[List[int]] = None,
        is_admin: bool = False
    ) -> Tuple[List[ExternalLink], int]:
        """
        Get paginated link list with filters and permission checks

        Args:
            session: Database session
            page: Page number (1-indexed)
            page_size: Items per page
            category: Filter by category
            status: Filter by status
            visibility: Filter by visibility
            period_type: Filter by period type
            keyword: Search keyword (searches title and description)
            created_by: Filter by creator
            current_user_id: Current user ID for permission filtering
            current_user_group_ids: Current user's group IDs for permission filtering
            is_admin: Whether current user is admin (admins see all links)

        Returns:
            Tuple of (links list, total count)
        """
        statement = select(ExternalLink)

        # Apply filters
        if category:
            statement = statement.where(ExternalLink.category == category)

        if status:
            statement = statement.where(ExternalLink.status == status)

        if visibility:
            statement = statement.where(ExternalLink.visibility == visibility)

        if period_type:
            statement = statement.where(ExternalLink.period_type == period_type)

        if created_by:
            statement = statement.where(ExternalLink.created_by == created_by)

        if keyword:
            search_pattern = f"%{keyword}%"
            statement = statement.where(
                or_(
                    ExternalLink.title.ilike(search_pattern),
                    ExternalLink.description.ilike(search_pattern)
                )
            )

        # Permission filtering (only for non-admin users)
        if not is_admin and current_user_id:
            # User can see:
            # 1. Links with visibility=ALL
            # 2. Links where user is in allowed_user_ids
            # 3. Links where user's group is in allowed_group_ids
            # Note: JSON filtering in SQLModel requires raw SQL or post-filtering
            # For now, we'll fetch all and filter in Python (can optimize with raw SQL later)
            pass

        # Order by category and link order
        statement = statement.order_by(
            ExternalLink.category_order,
            ExternalLink.link_order,
            ExternalLink.id
        )

        # Get total count
        count_statement = select(func.count()).select_from(statement.subquery())
        total_count = session.exec(count_statement).first()

        # Apply pagination
        statement = statement.offset((page - 1) * page_size).limit(page_size)
        links = list(session.exec(statement).all())

        # Apply permission filtering in Python if needed
        if not is_admin and current_user_id:
            links = ExternalLinkService._filter_links_by_permission(
                links, current_user_id, current_user_group_ids or []
            )
            total_count = len(links)  # Recalculate after filtering

        return links, total_count

    @staticmethod
    def _filter_links_by_permission(
        links: List[ExternalLink],
        user_id: int,
        user_group_ids: List[int]
    ) -> List[ExternalLink]:
        """
        Filter links based on user permissions

        Args:
            links: List of links to filter
            user_id: Current user ID
            user_group_ids: Current user's group IDs

        Returns:
            Filtered list of links
        """
        filtered = []
        for link in links:
            # ALL visibility - everyone can see
            if link.visibility == "ALL":
                filtered.append(link)
                continue

            # SPECIFIED visibility - check permissions
            if link.visibility == "SPECIFIED":
                allowed_users = json.loads(link.allowed_user_ids)
                allowed_groups = json.loads(link.allowed_group_ids)

                # Check if user is in allowed users
                if user_id in allowed_users:
                    filtered.append(link)
                    continue

                # Check if any of user's groups is in allowed groups
                if any(gid in allowed_groups for gid in user_group_ids):
                    filtered.append(link)
                    continue

        return filtered

    @staticmethod
    def _is_link_within_time_period(link: ExternalLink) -> bool:
        """
        Check if a link is within its valid time period

        Args:
            link: External link to check

        Returns:
            True if link is within valid time period, False otherwise
        """
        now = datetime.now(timezone.utc)

        # Check start_time
        if link.start_time:
            # Ensure start_time has timezone info
            start_time = link.start_time
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            if now < start_time:
                return False

        # Check end_time
        if link.end_time:
            # Ensure end_time has timezone info
            end_time = link.end_time
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)

            if now > end_time:
                return False

        return True

    @staticmethod
    def get_links_by_category(
        session: Session,
        current_user_id: Optional[int] = None,
        current_user_group_ids: Optional[List[int]] = None,
        is_admin: bool = False,
        include_inactive: bool = False
    ) -> Dict[str, List[ExternalLink]]:
        """
        Get all links grouped by category

        Args:
            session: Database session
            current_user_id: Current user ID for permission filtering
            current_user_group_ids: Current user's group IDs
            is_admin: Whether current user is admin
            include_inactive: Whether to include inactive/archived links

        Returns:
            Dictionary mapping category names to link lists
        """
        statement = select(ExternalLink)

        if not include_inactive:
            statement = statement.where(ExternalLink.status == "ACTIVE")

        statement = statement.order_by(
            ExternalLink.category_order,
            ExternalLink.link_order,
            ExternalLink.id
        )

        links = list(session.exec(statement).all())

        # Apply permission filtering (only for non-admin users)
        if not is_admin and current_user_id:
            links = ExternalLinkService._filter_links_by_permission(
                links, current_user_id, current_user_group_ids or []
            )

        # Apply time period filtering (only for non-admin users)
        # Admins should see all links regardless of time period for management purposes
        if not is_admin:
            links = [link for link in links if ExternalLinkService._is_link_within_time_period(link)]

        # Group by category
        result = {}
        for link in links:
            if link.category not in result:
                result[link.category] = []
            result[link.category].append(link)

        return result

    @staticmethod
    def get_categories(session: Session) -> List[Dict[str, any]]:
        """
        Get all unique categories with their orders and link counts

        Args:
            session: Database session

        Returns:
            List of category info dictionaries
        """
        # Get unique categories with their orders and counts
        statement = select(
            ExternalLink.category,
            ExternalLink.category_order,
            func.count(ExternalLink.id).label('link_count')
        ).group_by(
            ExternalLink.category,
            ExternalLink.category_order
        ).order_by(ExternalLink.category_order)

        results = session.exec(statement).all()

        return [
            {
                "name": row[0],
                "order": row[1],
                "link_count": row[2]
            }
            for row in results
        ]

    @staticmethod
    def batch_update_order(
        session: Session,
        updates: List[Dict],
        current_user_id: int
    ) -> None:
        """
        Batch update link and category orders

        Args:
            session: Database session
            updates: List of update dictionaries with id, category_order, link_order
            current_user_id: Current user ID

        Raises:
            NotFoundException: If any link not found
        """
        for update in updates:
            link_id = update.get('id')
            link = ExternalLinkService.get_link_by_id(session, link_id)

            if 'category_order' in update:
                link.category_order = update['category_order']

            if 'link_order' in update:
                link.link_order = update['link_order']

            link.updated_at = datetime.now(timezone.utc)
            session.add(link)

        session.commit()
        logger.info(f"Batch updated order for {len(updates)} links by user {current_user_id}")

    @staticmethod
    def record_click(
        session: Session,
        link_id: int,
        user_id: int,
        user_agent: Optional[str] = None
    ) -> ExternalLinkClick:
        """
        Record a link click

        Args:
            session: Database session
            link_id: Link ID
            user_id: User ID
            user_agent: Optional browser user agent

        Returns:
            Created click record

        Raises:
            NotFoundException: If link not found
        """
        link = ExternalLinkService.get_link_by_id(session, link_id)

        # Update link statistics
        link.click_count += 1
        link.last_accessed_at = datetime.now(timezone.utc)
        session.add(link)

        # Create click record
        click = ExternalLinkClick(
            link_id=link_id,
            user_id=user_id,
            user_agent=user_agent
        )
        session.add(click)

        session.commit()
        session.refresh(click)

        logger.info(f"Click recorded for link {link_id} by user {user_id}")
        return click

    @staticmethod
    def get_click_history(
        session: Session,
        link_id: Optional[int] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[ExternalLinkClick], int]:
        """
        Get click history with filters

        Args:
            session: Database session
            link_id: Filter by link ID
            user_id: Filter by user ID
            page: Page number
            page_size: Items per page

        Returns:
            Tuple of (click records, total count)
        """
        statement = select(ExternalLinkClick)

        if link_id:
            statement = statement.where(ExternalLinkClick.link_id == link_id)

        if user_id:
            statement = statement.where(ExternalLinkClick.user_id == user_id)

        # Order by most recent first
        statement = statement.order_by(ExternalLinkClick.clicked_at.desc())

        # Get total count
        count_statement = select(func.count()).select_from(statement.subquery())
        total_count = session.exec(count_statement).first()

        # Apply pagination
        statement = statement.offset((page - 1) * page_size).limit(page_size)
        clicks = list(session.exec(statement).all())

        return clicks, total_count

    @staticmethod
    def get_statistics(session: Session) -> Dict[str, any]:
        """
        Get overall statistics for external links

        Args:
            session: Database session

        Returns:
            Statistics dictionary
        """
        # Total links
        total_links = session.exec(select(func.count(ExternalLink.id))).first()

        # Active links
        active_links = session.exec(
            select(func.count(ExternalLink.id)).where(ExternalLink.status == "ACTIVE")
        ).first()

        # Total clicks
        total_clicks = session.exec(select(func.sum(ExternalLink.click_count))).first() or 0

        # Total categories
        total_categories = session.exec(
            select(func.count(func.distinct(ExternalLink.category)))
        ).first()

        # Top 10 links by clicks
        top_links_stmt = select(ExternalLink).order_by(
            ExternalLink.click_count.desc()
        ).limit(10)
        top_links = list(session.exec(top_links_stmt).all())

        return {
            "total_links": total_links,
            "active_links": active_links,
            "total_clicks": int(total_clicks),
            "total_categories": total_categories,
            "top_links": top_links
        }
