"""
Favorite service for managing user link favorites and folders
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlmodel import Session, select, func, delete

from app.models.external_link import ExternalLink, UserFavoriteFolder, UserLinkFavorite
from app.models.user import User
from app.schemas.external_link import FavoriteFolderCreate, FavoriteFolderUpdate
from app.core.exceptions import NotFoundException, ConflictException, ForbiddenException
from app.core.logger import logger


class FavoriteService:
    """Favorite management service"""

    # ==================== Folder Operations ====================

    @staticmethod
    def create_folder(
        session: Session,
        user_id: int,
        folder_data: FavoriteFolderCreate
    ) -> UserFavoriteFolder:
        """
        Create a new favorite folder

        Args:
            session: Database session
            user_id: Owner user ID
            folder_data: Folder creation data

        Returns:
            Created folder

        Raises:
            ConflictException: If folder with same name already exists
        """
        # Check if folder with same name already exists for this user
        existing = session.exec(
            select(UserFavoriteFolder).where(
                UserFavoriteFolder.user_id == user_id,
                UserFavoriteFolder.name == folder_data.name
            )
        ).first()

        if existing:
            raise ConflictException(f"收藏夹 '{folder_data.name}' 已存在")

        # Get max sort_order for this user
        max_order_stmt = select(func.max(UserFavoriteFolder.sort_order)).where(
            UserFavoriteFolder.user_id == user_id
        )
        max_order = session.exec(max_order_stmt).first() or 0

        folder = UserFavoriteFolder(
            user_id=user_id,
            name=folder_data.name,
            description=folder_data.description,
            sort_order=max_order + 1,
            is_default=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(folder)
        session.commit()
        session.refresh(folder)

        logger.info(f"Favorite folder created: {folder.name} (ID: {folder.id}) by user {user_id}")
        return folder

    @staticmethod
    def get_folder_by_id(session: Session, folder_id: int, user_id: int) -> UserFavoriteFolder:
        """
        Get folder by ID with ownership check

        Args:
            session: Database session
            folder_id: Folder ID
            user_id: User ID for ownership check

        Returns:
            Folder object

        Raises:
            NotFoundException: If folder not found
            ForbiddenException: If folder belongs to another user
        """
        folder = session.get(UserFavoriteFolder, folder_id)
        if not folder:
            raise NotFoundException(f"收藏夹不存在")

        if folder.user_id != user_id:
            raise ForbiddenException("无权访问此收藏夹")

        return folder

    @staticmethod
    def get_user_folders(session: Session, user_id: int) -> List[dict]:
        """
        Get all folders for a user with link counts

        Args:
            session: Database session
            user_id: User ID

        Returns:
            List of folders with link counts
        """
        # Get all folders for user
        folders = session.exec(
            select(UserFavoriteFolder)
            .where(UserFavoriteFolder.user_id == user_id)
            .order_by(UserFavoriteFolder.sort_order)
        ).all()

        result = []
        for folder in folders:
            # Count links in this folder
            link_count = session.exec(
                select(func.count(UserLinkFavorite.id))
                .where(UserLinkFavorite.folder_id == folder.id)
            ).first() or 0

            result.append({
                "id": folder.id,
                "name": folder.name,
                "description": folder.description,
                "sort_order": folder.sort_order,
                "is_default": folder.is_default,
                "link_count": link_count,
                "created_at": folder.created_at,
                "updated_at": folder.updated_at
            })

        # Add "uncategorized" count
        uncategorized_count = session.exec(
            select(func.count(UserLinkFavorite.id))
            .where(
                UserLinkFavorite.user_id == user_id,
                UserLinkFavorite.folder_id == None
            )
        ).first() or 0

        return {
            "folders": result,
            "uncategorized_count": uncategorized_count
        }

    @staticmethod
    def update_folder(
        session: Session,
        folder_id: int,
        user_id: int,
        folder_data: FavoriteFolderUpdate
    ) -> UserFavoriteFolder:
        """
        Update a favorite folder

        Args:
            session: Database session
            folder_id: Folder ID
            user_id: User ID for ownership check
            folder_data: Update data

        Returns:
            Updated folder

        Raises:
            NotFoundException: If folder not found
            ForbiddenException: If folder belongs to another user
            ConflictException: If new name already exists
        """
        folder = FavoriteService.get_folder_by_id(session, folder_id, user_id)

        # Check name uniqueness if changing name
        if folder_data.name and folder_data.name != folder.name:
            existing = session.exec(
                select(UserFavoriteFolder).where(
                    UserFavoriteFolder.user_id == user_id,
                    UserFavoriteFolder.name == folder_data.name,
                    UserFavoriteFolder.id != folder_id
                )
            ).first()

            if existing:
                raise ConflictException(f"收藏夹 '{folder_data.name}' 已存在")

            folder.name = folder_data.name

        if folder_data.description is not None:
            folder.description = folder_data.description

        folder.updated_at = datetime.now(timezone.utc)

        session.add(folder)
        session.commit()
        session.refresh(folder)

        logger.info(f"Favorite folder updated: {folder.name} (ID: {folder.id})")
        return folder

    @staticmethod
    def delete_folder(session: Session, folder_id: int, user_id: int) -> None:
        """
        Delete a favorite folder

        Args:
            session: Database session
            folder_id: Folder ID
            user_id: User ID for ownership check

        Raises:
            NotFoundException: If folder not found
            ForbiddenException: If folder belongs to another user
        """
        folder = FavoriteService.get_folder_by_id(session, folder_id, user_id)

        # Move favorites in this folder to uncategorized (folder_id = NULL)
        session.exec(
            select(UserLinkFavorite)
            .where(UserLinkFavorite.folder_id == folder_id)
        )
        # Update all favorites in this folder to uncategorized
        favorites_in_folder = session.exec(
            select(UserLinkFavorite).where(UserLinkFavorite.folder_id == folder_id)
        ).all()

        for fav in favorites_in_folder:
            fav.folder_id = None
            session.add(fav)

        # Delete the folder
        session.delete(folder)
        session.commit()

        logger.info(f"Favorite folder deleted: {folder.name} (ID: {folder_id})")

    @staticmethod
    def reorder_folders(
        session: Session,
        user_id: int,
        updates: List[dict]
    ) -> None:
        """
        Reorder favorite folders

        Args:
            session: Database session
            user_id: User ID
            updates: List of {folder_id, sort_order}
        """
        for update in updates:
            folder_id = update.get("folder_id")
            sort_order = update.get("sort_order")

            folder = session.get(UserFavoriteFolder, folder_id)
            if folder and folder.user_id == user_id:
                folder.sort_order = sort_order
                folder.updated_at = datetime.now(timezone.utc)
                session.add(folder)

        session.commit()
        logger.info(f"Favorite folders reordered for user {user_id}")

    # ==================== Favorite Operations ====================

    @staticmethod
    def add_favorite(
        session: Session,
        user_id: int,
        link_id: int,
        folder_id: Optional[int] = None
    ) -> UserLinkFavorite:
        """
        Add a link to favorites

        Args:
            session: Database session
            user_id: User ID
            link_id: Link ID to favorite
            folder_id: Optional folder ID

        Returns:
            Created favorite record

        Raises:
            NotFoundException: If link or folder not found
            ConflictException: If already favorited
        """
        # Verify link exists
        link = session.get(ExternalLink, link_id)
        if not link:
            raise NotFoundException("外链不存在")

        # Verify folder exists if specified
        if folder_id:
            folder = session.get(UserFavoriteFolder, folder_id)
            if not folder or folder.user_id != user_id:
                raise NotFoundException("收藏夹不存在")

        # Check if already favorited
        existing = session.exec(
            select(UserLinkFavorite).where(
                UserLinkFavorite.user_id == user_id,
                UserLinkFavorite.link_id == link_id
            )
        ).first()

        if existing:
            raise ConflictException("该链接已收藏")

        favorite = UserLinkFavorite(
            user_id=user_id,
            link_id=link_id,
            folder_id=folder_id,
            created_at=datetime.now(timezone.utc)
        )

        session.add(favorite)
        session.commit()
        session.refresh(favorite)

        logger.info(f"Link {link_id} added to favorites by user {user_id}")
        return favorite

    @staticmethod
    def remove_favorite(session: Session, user_id: int, link_id: int) -> None:
        """
        Remove a link from favorites

        Args:
            session: Database session
            user_id: User ID
            link_id: Link ID to unfavorite

        Raises:
            NotFoundException: If favorite not found
        """
        favorite = session.exec(
            select(UserLinkFavorite).where(
                UserLinkFavorite.user_id == user_id,
                UserLinkFavorite.link_id == link_id
            )
        ).first()

        if not favorite:
            raise NotFoundException("未收藏此链接")

        session.delete(favorite)
        session.commit()

        logger.info(f"Link {link_id} removed from favorites by user {user_id}")

    @staticmethod
    def move_favorite(
        session: Session,
        user_id: int,
        link_id: int,
        folder_id: Optional[int]
    ) -> UserLinkFavorite:
        """
        Move a favorite to another folder

        Args:
            session: Database session
            user_id: User ID
            link_id: Link ID
            folder_id: Target folder ID (None for uncategorized)

        Returns:
            Updated favorite record

        Raises:
            NotFoundException: If favorite or folder not found
        """
        favorite = session.exec(
            select(UserLinkFavorite).where(
                UserLinkFavorite.user_id == user_id,
                UserLinkFavorite.link_id == link_id
            )
        ).first()

        if not favorite:
            raise NotFoundException("未收藏此链接")

        # Verify folder exists if specified
        if folder_id:
            folder = session.get(UserFavoriteFolder, folder_id)
            if not folder or folder.user_id != user_id:
                raise NotFoundException("收藏夹不存在")

        favorite.folder_id = folder_id
        session.add(favorite)
        session.commit()
        session.refresh(favorite)

        logger.info(f"Favorite {link_id} moved to folder {folder_id} by user {user_id}")
        return favorite

    @staticmethod
    def get_user_favorites(
        session: Session,
        user_id: int,
        folder_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[dict], int]:
        """
        Get user's favorite links

        Args:
            session: Database session
            user_id: User ID
            folder_id: Filter by folder (None for all, -1 for uncategorized only)
            page: Page number
            page_size: Items per page

        Returns:
            Tuple of (favorites list, total count)
        """
        # Build base query
        query = select(UserLinkFavorite).where(UserLinkFavorite.user_id == user_id)

        # Filter by folder
        if folder_id == -1:
            # Uncategorized only
            query = query.where(UserLinkFavorite.folder_id == None)
        elif folder_id is not None:
            query = query.where(UserLinkFavorite.folder_id == folder_id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = session.exec(count_query).first() or 0

        # Get paginated results
        query = query.order_by(UserLinkFavorite.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        favorites = session.exec(query).all()

        # Build result with link details
        result = []
        for fav in favorites:
            link = session.get(ExternalLink, fav.link_id)
            if not link:
                continue

            # Get folder name
            folder_name = None
            if fav.folder_id:
                folder = session.get(UserFavoriteFolder, fav.folder_id)
                folder_name = folder.name if folder else None

            # Get maintainer info
            maintainer_username = None
            maintainer_nickname = None
            maintainer_avatar = None
            if link.maintainer_id:
                maintainer = session.get(User, link.maintainer_id)
                if maintainer:
                    maintainer_username = maintainer.username
                    maintainer_nickname = maintainer.nickname
                    maintainer_avatar = maintainer.avatar

            import json
            tags = json.loads(link.tags) if isinstance(link.tags, str) else link.tags

            result.append({
                "id": fav.id,
                "link": {
                    "id": link.id,
                    "title": link.title,
                    "url": link.url,
                    "description": link.description,
                    "icon_url": link.icon_url,
                    "category": link.category,
                    "category_order": link.category_order,
                    "link_order": link.link_order,
                    "tags": tags,
                    "maintainer_username": maintainer_username,
                    "maintainer_nickname": maintainer_nickname,
                    "maintainer_avatar": maintainer_avatar,
                    "visibility": link.visibility,
                    "period_type": link.period_type,
                    "start_time": link.start_time,
                    "end_time": link.end_time,
                    "status": link.status,
                    "click_count": link.click_count,
                    "last_accessed_at": link.last_accessed_at,
                    "created_at": link.created_at,
                    "is_favorited": True
                },
                "folder_id": fav.folder_id,
                "folder_name": folder_name,
                "created_at": fav.created_at
            })

        return result, total

    @staticmethod
    def check_favorite_status(
        session: Session,
        user_id: int,
        link_id: int
    ) -> dict:
        """
        Check if a link is favorited by user

        Args:
            session: Database session
            user_id: User ID
            link_id: Link ID

        Returns:
            Favorite status info
        """
        favorite = session.exec(
            select(UserLinkFavorite).where(
                UserLinkFavorite.user_id == user_id,
                UserLinkFavorite.link_id == link_id
            )
        ).first()

        if not favorite:
            return {
                "is_favorited": False,
                "folder_id": None,
                "folder_name": None
            }

        folder_name = None
        if favorite.folder_id:
            folder = session.get(UserFavoriteFolder, favorite.folder_id)
            folder_name = folder.name if folder else None

        return {
            "is_favorited": True,
            "folder_id": favorite.folder_id,
            "folder_name": folder_name
        }

    @staticmethod
    def get_user_favorited_link_ids(session: Session, user_id: int) -> set:
        """
        Get set of link IDs favorited by user (for batch checking)

        Args:
            session: Database session
            user_id: User ID

        Returns:
            Set of favorited link IDs
        """
        favorites = session.exec(
            select(UserLinkFavorite.link_id).where(UserLinkFavorite.user_id == user_id)
        ).all()
        return set(favorites)
