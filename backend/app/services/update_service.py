"""
Update service for managing application versions and updates
"""
import hashlib
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlmodel import Session, select, func, and_, or_
from structlog import get_logger

from app.models.app_version import AppVersion
from app.models.changelog import Changelog, ChangelogHelper
from app.models.update_stats import UpdateStats, UpdateStatsHelper
from app.models.user_group import UserGroupMember
from app.schemas.update import (
    VersionCreate, VersionUpdate, ChangelogCreate,
    CheckUpdateRequest, CheckUpdateResponse,
    StatsAggregation, VersionStatsResponse, DashboardStatsResponse,
    VersionListItem, PlatformDistribution, ChannelDistribution
)

logger = get_logger(__name__)


class UpdateService:
    """Service for handling update operations"""

    @staticmethod
    def check_update(
        session: Session,
        request: CheckUpdateRequest,
        user_id: Optional[int] = None
    ) -> CheckUpdateResponse:
        """
        Check if update is available for the client

        Args:
            session: Database session
            request: Check update request parameters
            user_id: Optional user ID for gradual rollout

        Returns:
            CheckUpdateResponse with update information
        """
        try:
            # Parse current version code
            current_code = AppVersion.parse_version_to_code(request.current_version)

            # Query for newer active versions
            # Include all channels - user eligibility is determined by whitelist/rollout logic
            query = select(AppVersion).where(
                and_(
                    AppVersion.is_active == True,
                    AppVersion.platform == request.platform,
                    AppVersion.version_code > current_code
                )
            ).order_by(AppVersion.version_code.desc())

            versions = session.exec(query).all()

            if not versions:
                # No update available
                logger.info(f"No update available for {request.current_version} on {request.platform}")
                return CheckUpdateResponse(
                    has_update=False,
                    current_version=request.current_version
                )

            # Find the highest version that user is eligible for
            # Priority: check all versions from newest to oldest
            # User gets the newest version they have access to (via whitelist or stable channel)
            for version in versions:
                # For non-stable channels (beta/alpha), user must be in whitelist
                # For stable channel with visibility=ALL, apply normal rollout logic
                if version.channel != 'stable' and version.visibility != 'SPECIFIED':
                    # Non-stable version without whitelist restriction - skip for normal users
                    logger.debug(f"Skipping {version.channel} version {version.version} (no whitelist)")
                    continue

                # Check gradual rollout eligibility (with user whitelist support)
                if not UpdateService._is_user_in_rollout(version, user_id, session):
                    logger.debug(f"User {user_id} not in rollout for version {version.version}")
                    continue

                # Check compatibility
                if not version.is_compatible_with(request.current_version):
                    logger.debug(f"Version {version.version} not compatible with {request.current_version}")
                    continue

                # Found eligible version
                logger.info(f"Update available: {version.version} for user {user_id}")

                # Get changelog in preferred language
                changelog_query = select(Changelog).where(
                    and_(
                        Changelog.version_id == version.id,
                        Changelog.language == request.language
                    )
                )
                changelog = session.exec(changelog_query).first()

                # Fallback to default language if not found
                if not changelog:
                    changelog_query = select(Changelog).where(
                        Changelog.version_id == version.id
                    ).limit(1)
                    changelog = session.exec(changelog_query).first()

                changelog_data = None
                if changelog:
                    changelog_data = ChangelogHelper.to_dict(changelog)

                # Record check statistics
                UpdateService._record_stats(
                    session=session,
                    version_id=version.id,
                    action=UpdateStatsHelper.ACTION_CHECK,
                    client_version=request.current_version,
                    platform=request.platform,
                    user_id=user_id
                )

                return CheckUpdateResponse(
                    has_update=True,
                    current_version=request.current_version,
                    version=version.version,
                    version_code=version.version_code,
                    title=version.title,
                    channel=version.channel,
                    is_forced=version.is_forced,
                    file_size=version.file_size,
                    file_hash=version.file_hash,
                    signature=version.signature,
                    download_url=f"/api/v1/updates/download/{version.version}",
                    changelog=changelog_data,
                    published_at=version.published_at
                )

            # No eligible version found
            logger.info(f"No eligible update for {request.current_version} (rollout/compatibility)")
            return CheckUpdateResponse(
                has_update=False,
                current_version=request.current_version
            )

        except Exception as e:
            logger.error(f"Error checking update: {str(e)}", exc_info=True)
            return CheckUpdateResponse(
                has_update=False,
                current_version=request.current_version
            )

    @staticmethod
    def _is_user_in_rollout(
        version: AppVersion,
        user_id: Optional[int],
        session: Optional[Session] = None
    ) -> bool:
        """
        Determine if user is in the gradual rollout for this version

        Uses consistent hashing based on user_id to ensure same user always
        gets same result for a given version.

        Flow:
        1. Check visibility setting:
           - ALL: Apply rollout percentage to all users
           - SPECIFIED: First check if user is in whitelist, then apply rollout percentage
        2. Apply rollout percentage filter

        Args:
            version: App version to check
            user_id: User ID (None for anonymous users)
            session: Database session (required for SPECIFIED visibility)

        Returns:
            True if user should receive this update
        """
        # Step 1: Check visibility
        if version.visibility == "SPECIFIED":
            if user_id is None:
                # Anonymous users cannot receive SPECIFIED updates
                return False

            # Check if user is in whitelist
            if not UpdateService._is_user_in_whitelist(version, user_id, session):
                logger.debug(f"User {user_id} not in whitelist for version {version.version}")
                return False

        # Step 2: Apply rollout percentage
        if version.rollout_percentage >= 100:
            return True

        if version.rollout_percentage <= 0:
            return False

        if user_id is None:
            # For anonymous users with visibility=ALL, allow by default
            return True

        # Hash user_id + version to get consistent result
        hash_input = f"{user_id}-{version.version}".encode()
        hash_value = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
        bucket = hash_value % 100

        return bucket < version.rollout_percentage

    @staticmethod
    def _is_user_in_whitelist(
        version: AppVersion,
        user_id: int,
        session: Optional[Session] = None
    ) -> bool:
        """
        Check if user is in the version whitelist

        Args:
            version: App version to check
            user_id: User ID
            session: Database session

        Returns:
            True if user is in allowed_user_ids or belongs to a group in allowed_group_ids
        """
        # Parse JSON fields (they are stored as JSON in database)
        allowed_user_ids = version.allowed_user_ids if isinstance(version.allowed_user_ids, list) else []
        allowed_group_ids = version.allowed_group_ids if isinstance(version.allowed_group_ids, list) else []

        # Check if user is directly in allowed list
        if user_id in allowed_user_ids:
            return True

        # Check if user belongs to any allowed group
        if allowed_group_ids and session:
            user_group_ids = UpdateService._get_user_group_ids(session, user_id)
            if any(gid in allowed_group_ids for gid in user_group_ids):
                return True

        return False

    @staticmethod
    def _get_user_group_ids(session: Session, user_id: int) -> List[int]:
        """
        Get all group IDs that a user belongs to

        Args:
            session: Database session
            user_id: User ID

        Returns:
            List of group IDs
        """
        try:
            query = select(UserGroupMember.group_id).where(
                UserGroupMember.user_id == user_id
            )
            result = session.exec(query).all()
            return list(result)
        except Exception as e:
            logger.error(f"Error getting user groups: {str(e)}", exc_info=True)
            return []

    @staticmethod
    def _record_stats(
        session: Session,
        version_id: int,
        action: str,
        client_version: str,
        platform: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Record update statistics"""
        try:
            stats = UpdateStats(
                version_id=version_id,
                user_id=user_id,
                action=action,
                client_version=client_version,
                platform=platform,
                ip_address=ip_address,
                user_agent=user_agent,
                error_message=error_message
            )
            session.add(stats)
            session.commit()
        except Exception as e:
            logger.error(f"Error recording stats: {str(e)}", exc_info=True)
            session.rollback()

    @staticmethod
    def get_latest_version(
        session: Session,
        platform: str = "windows",
        channel: str = "stable"
    ) -> Optional[AppVersion]:
        """Get the latest active version for a platform and channel"""
        query = select(AppVersion).where(
            and_(
                AppVersion.is_active == True,
                AppVersion.platform == platform,
                AppVersion.channel == channel
            )
        ).order_by(AppVersion.version_code.desc()).limit(1)

        return session.exec(query).first()

    @staticmethod
    def create_version(
        session: Session,
        version_data: VersionCreate,
        file_path: str,
        file_size: int,
        file_hash: str,
        signature: str,
        published_by: int
    ) -> AppVersion:
        """
        Create a new application version

        Args:
            session: Database session
            version_data: Version creation data
            file_path: Path to the update file
            file_size: File size in bytes
            file_hash: SHA256 hash of the file
            signature: Tauri signature content
            published_by: User ID of publisher

        Returns:
            Created AppVersion instance
        """
        try:
            # Calculate version code
            version_code = AppVersion.parse_version_to_code(version_data.version)

            # Create version
            version = AppVersion(
                version=version_data.version,
                version_code=version_code,
                title=version_data.title,
                channel=version_data.channel,
                platform=version_data.platform,
                file_path=file_path,
                file_size=file_size,
                file_hash=file_hash,
                signature=signature,
                is_forced=version_data.is_forced,
                min_version=version_data.min_version,
                rollout_percentage=version_data.rollout_percentage,
                visibility=version_data.visibility,
                allowed_group_ids=version_data.allowed_group_ids,
                allowed_user_ids=version_data.allowed_user_ids,
                published_by=published_by,
                published_at=datetime.now(timezone.utc),
                is_active=True
            )

            session.add(version)
            session.flush()  # Get version.id

            # Create changelogs
            for lang_code, changelog_data in version_data.changelogs.items():
                changelog = ChangelogHelper.create_from_dict(
                    data=changelog_data.dict(),
                    version_id=version.id,
                    language=lang_code
                )
                session.add(changelog)

            session.commit()
            session.refresh(version)

            logger.info(f"Created version {version.version} (ID: {version.id})")
            return version

        except Exception as e:
            logger.error(f"Error creating version: {str(e)}", exc_info=True)
            session.rollback()
            raise

    @staticmethod
    def update_version(
        session: Session,
        version_id: int,
        update_data: VersionUpdate
    ) -> Optional[AppVersion]:
        """Update version metadata"""
        try:
            version = session.get(AppVersion, version_id)
            if not version:
                return None

            update_dict = update_data.dict(exclude_unset=True)
            for key, value in update_dict.items():
                setattr(version, key, value)

            version.updated_at = datetime.now(timezone.utc)
            session.add(version)
            session.commit()
            session.refresh(version)

            logger.info(f"Updated version {version.version} (ID: {version_id})")
            return version

        except Exception as e:
            logger.error(f"Error updating version: {str(e)}", exc_info=True)
            session.rollback()
            raise

    @staticmethod
    def delete_version(session: Session, version_id: int) -> bool:
        """Delete a version and its associated data"""
        try:
            version = session.get(AppVersion, version_id)
            if not version:
                return False

            # Delete associated changelogs first
            changelog_query = select(Changelog).where(Changelog.version_id == version_id)
            changelogs = session.exec(changelog_query).all()
            for changelog in changelogs:
                session.delete(changelog)

            # Flush to ensure changelogs are deleted before version
            session.flush()

            # Delete associated update stats
            stats_query = select(UpdateStats).where(UpdateStats.version_id == version_id)
            stats = session.exec(stats_query).all()
            for stat in stats:
                session.delete(stat)

            # Flush to ensure stats are deleted before version
            session.flush()

            # Delete file
            if version.file_path and os.path.exists(version.file_path):
                try:
                    os.remove(version.file_path)
                    # Try to remove signature file
                    sig_path = version.file_path + ".sig"
                    if os.path.exists(sig_path):
                        os.remove(sig_path)
                except Exception as file_error:
                    logger.warning(f"Error deleting file: {str(file_error)}")

            # Delete version
            session.delete(version)
            session.commit()

            logger.info(f"Deleted version {version.version} (ID: {version_id})")
            return True

        except Exception as e:
            logger.error(f"Error deleting version: {str(e)}", exc_info=True)
            session.rollback()
            raise

    @staticmethod
    def get_version_stats(
        session: Session,
        version_id: int
    ) -> Optional[StatsAggregation]:
        """Get aggregated statistics for a version"""
        try:
            # Count total downloads (action = 'download')
            # Note: Each download produces 2 records (app version + tauri-plugin-updater)
            raw_downloads = session.exec(
                select(func.count(UpdateStats.id)).where(
                    and_(
                        UpdateStats.version_id == version_id,
                        UpdateStats.action == UpdateStatsHelper.ACTION_DOWNLOAD
                    )
                )
            ).one() or 0

            # Count downloads with errors (error_message is not null and not empty)
            raw_errors = session.exec(
                select(func.count(UpdateStats.id)).where(
                    and_(
                        UpdateStats.version_id == version_id,
                        UpdateStats.action == UpdateStatsHelper.ACTION_DOWNLOAD,
                        UpdateStats.error_message.isnot(None),
                        UpdateStats.error_message != ""
                    )
                )
            ).one() or 0

            # Actual counts (divided by 2)
            total_downloads = raw_downloads // 2
            total_errors = raw_errors // 2

            # Calculate success rate based on downloads without errors
            if total_downloads > 0:
                success_rate = ((total_downloads - total_errors) / total_downloads) * 100
            else:
                success_rate = 0.0

            return StatsAggregation(
                total_checks=0,  # Not used
                total_downloads=total_downloads,
                total_installs=0,  # Not used
                total_completes=0,  # Not used
                total_errors=total_errors,
                success_rate=round(success_rate, 2)
            )

        except Exception as e:
            logger.error(f"Error getting version stats: {str(e)}", exc_info=True)
            return None

    @staticmethod
    def get_dashboard_stats(session: Session) -> DashboardStatsResponse:
        """Get overall dashboard statistics"""
        try:
            # Total and active versions
            total_versions = session.exec(select(func.count(AppVersion.id))).one()
            active_versions = session.exec(
                select(func.count(AppVersion.id)).where(AppVersion.is_active == True)
            ).one()

            # Overall download count (divided by 2 since each download produces 2 records)
            raw_downloads = session.exec(
                select(func.count(UpdateStats.id)).where(
                    UpdateStats.action == UpdateStatsHelper.ACTION_DOWNLOAD
                )
            ).one() or 0
            total_downloads = raw_downloads // 2

            # Count downloads with errors
            raw_errors = session.exec(
                select(func.count(UpdateStats.id)).where(
                    and_(
                        UpdateStats.action == UpdateStatsHelper.ACTION_DOWNLOAD,
                        UpdateStats.error_message.isnot(None),
                        UpdateStats.error_message != ""
                    )
                )
            ).one() or 0
            total_errors = raw_errors // 2

            # Overall success rate based on downloads without errors
            success_rate = ((total_downloads - total_errors) / total_downloads * 100) if total_downloads > 0 else 0.0

            # total_installs is set to successful downloads for backwards compatibility
            total_installs = total_downloads - total_errors

            # Platform distribution
            platform_query = select(
                UpdateStats.platform,
                func.count(UpdateStats.id).label("count")
            ).group_by(UpdateStats.platform)
            platform_results = session.exec(platform_query).all()
            total_platform_stats = sum(count for _, count in platform_results)

            platform_distribution = [
                PlatformDistribution(
                    platform=platform,
                    count=count,
                    percentage=round((count / total_platform_stats * 100) if total_platform_stats > 0 else 0, 2)
                )
                for platform, count in platform_results
            ]

            # Channel distribution
            channel_query = select(
                AppVersion.channel,
                func.count(AppVersion.id).label("count")
            ).group_by(AppVersion.channel)
            channel_results = session.exec(channel_query).all()
            total_channel_stats = sum(count for _, count in channel_results)

            channel_distribution = [
                ChannelDistribution(
                    channel=channel,
                    count=count,
                    percentage=round((count / total_channel_stats * 100) if total_channel_stats > 0 else 0, 2)
                )
                for channel, count in channel_results
            ]

            # Recent versions with stats
            recent_query = select(AppVersion).order_by(
                AppVersion.created_at.desc()
            ).limit(10)
            recent_versions_data = session.exec(recent_query).all()

            recent_versions = []
            for version in recent_versions_data:
                stats = UpdateService.get_version_stats(session, version.id)
                recent_versions.append(
                    VersionListItem(
                        id=version.id,
                        version=version.version,
                        version_code=version.version_code,
                        title=version.title,
                        channel=version.channel,
                        platform=version.platform,
                        file_size=version.file_size,
                        is_forced=version.is_forced,
                        rollout_percentage=version.rollout_percentage,
                        visibility=version.visibility,
                        allowed_group_ids=version.allowed_group_ids if isinstance(version.allowed_group_ids, list) else [],
                        allowed_user_ids=version.allowed_user_ids if isinstance(version.allowed_user_ids, list) else [],
                        is_active=version.is_active,
                        published_at=version.published_at,
                        created_at=version.created_at,
                        download_count=stats.total_downloads if stats else 0,
                        install_count=stats.total_completes if stats else 0
                    )
                )

            return DashboardStatsResponse(
                total_versions=total_versions,
                active_versions=active_versions,
                total_downloads=total_downloads,
                total_installs=total_installs,
                overall_success_rate=round(success_rate, 2),
                platform_distribution=platform_distribution,
                channel_distribution=channel_distribution,
                recent_versions=recent_versions
            )

        except Exception as e:
            logger.error(f"Error getting dashboard stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
