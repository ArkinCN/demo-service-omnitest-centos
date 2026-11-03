"""
Update management API endpoints
"""
import os
import json
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Header
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select, and_, func
from structlog import get_logger

from app.db.session import get_session
from app.api.deps import get_current_user, get_current_active_user, get_optional_user
from app.models.user import User
from app.models.app_version import AppVersion
from app.models.changelog import Changelog, ChangelogHelper
from app.models.update_stats import UpdateStats, UpdateStatsHelper
from app.schemas.common import success_response, error_response, PaginatedResponse, PaginationParams
from app.schemas.update import (
    CheckUpdateRequest, CheckUpdateResponse,
    VersionCreate, VersionUpdate, VersionResponse, VersionDetailResponse,
    VersionListItem, ChangelogCreate, ChangelogUpdate, ChangelogResponse,
    UpdateStatsCreate, DashboardStatsResponse, VersionStatsResponse,
    ActivateVersionRequest, VersionSettingsUpdate, VersionFileInfo
)
from app.services.update_service import UpdateService
from app.core.config import settings

logger = get_logger(__name__)
router = APIRouter()


# ==================== Public Endpoints (Authenticated) ====================

@router.get("/check")
async def check_update_get(
    current_version: Optional[str] = None,
    platform: str = "windows",
    channel: str = "stable",
    language: str = "zh-Hans",
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user),
    request: Request = None
):
    """
    Check if update is available (GET method for Tauri updater)

    Optional authentication. User info is tracked if authenticated.
    Query parameters (all optional):
    - current_version: Current app version (optional, will return latest if not provided)
    - platform: Target platform (default: windows)
    - channel: Release channel (default: stable)
    - language: Language for changelog (default: zh-Hans)

    Returns Tauri updater compatible format
    """
    try:
        # If no current_version provided, get latest version directly
        if not current_version:
            latest = UpdateService.get_latest_version(
                session=session,
                platform=platform,
                channel=channel
            )

            if not latest:
                # No version available at all
                raise HTTPException(status_code=404, detail="No version available")

            # Get changelog
            changelog_query = select(Changelog).where(
                and_(
                    Changelog.version_id == latest.id,
                    Changelog.language == language
                )
            )
            changelog_obj = session.exec(changelog_query).first()
            changelog_dict = ChangelogHelper.to_dict(changelog_obj) if changelog_obj else {}

            # Return Tauri format with platforms structure
            pub_date = latest.published_at if latest.published_at else datetime.now(timezone.utc)
            # Ensure ISO 8601 format with Z suffix
            pub_date_str = pub_date.isoformat().replace('+00:00', 'Z')
            if not pub_date_str.endswith('Z'):
                pub_date_str += 'Z'

            return {
                "version": latest.version,
                "notes": changelog_dict.get("description", "New version available"),
                "pub_date": pub_date_str,
                "platforms": {
                    "windows-x86_64": {
                        "signature": latest.signature,
                        "url": f"https://aiproxy.example.internal/api/v1/updates/download/{latest.version}?platform={platform}"
                    }
                }
            }

        # If current_version provided, use normal check logic
        check_request = CheckUpdateRequest(
            current_version=current_version,
            platform=platform,
            channel=channel,
            language=language
        )
        result = UpdateService.check_update(
            session=session,
            request=check_request,
            user_id=current_user.id if current_user else None
        )

        # Return Tauri updater compatible format
        if result.has_update:
            # Ensure ISO 8601 format with Z suffix
            pub_date = result.published_at if result.published_at else datetime.now(timezone.utc)
            pub_date_str = pub_date.isoformat().replace('+00:00', 'Z')
            if not pub_date_str.endswith('Z'):
                pub_date_str += 'Z'

            return {
                "version": result.version,
                "notes": result.changelog.get("description", ""),
                "pub_date": pub_date_str,
                "platforms": {
                    "windows-x86_64": {
                        "signature": result.signature,
                        "url": f"https://aiproxy.example.internal/api/v1/updates/download/{result.version}?platform={platform}"
                    }
                }
            }
        else:
            # No update available - Tauri expects 204 or the response format
            # Return current version to indicate no update
            raise HTTPException(status_code=204, detail="No update available")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking update (GET): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to check update")


@router.post("/check", response_model=dict)
async def check_update(
    request: CheckUpdateRequest,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    Check if update is available (POST method for API calls)

    Optional authentication. User info is tracked if authenticated.
    """
    try:
        result = UpdateService.check_update(
            session=session,
            request=request,
            user_id=current_user.id if current_user else None
        )
        return success_response(data=result.dict())
    except Exception as e:
        logger.error(f"Error checking update: {str(e)}", exc_info=True)
        return error_response(message="Failed to check update", code=500)


@router.get("/download/{version}", response_class=StreamingResponse)
async def download_update(
    version: str,
    platform: str = "windows",
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user),
    request: Request = None
):
    """
    Download update file

    Optional authentication. User info is tracked if authenticated.
    """
    try:
        # Find version
        query = select(AppVersion).where(
            and_(
                AppVersion.version == version,
                AppVersion.platform == platform,
                AppVersion.is_active == True
            )
        )
        app_version = session.exec(query).first()

        if not app_version:
            raise HTTPException(status_code=404, detail="Version not found")

        # Check if file exists
        file_path = app_version.file_path
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            raise HTTPException(status_code=404, detail="Update file not found")

        # Record download stats
        UpdateService._record_stats(
            session=session,
            version_id=app_version.id,
            action=UpdateStatsHelper.ACTION_DOWNLOAD,
            client_version="unknown",  # Can be passed as query param
            platform=platform,
            user_id=current_user.id if current_user else None,
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None
        )

        # Stream file
        def iterfile():
            with open(file_path, mode="rb") as file_like:
                yield from file_like

        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={os.path.basename(file_path)}",
                "Content-Length": str(app_version.file_size)
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to download update")


@router.get("/changelog/{version}/{language}", response_model=dict)
async def get_changelog(
    version: str,
    language: str = "zh-Hans",
    session: Session = Depends(get_session)
):
    """
    Get changelog for a specific version and language

    Public endpoint - no authentication required.
    """
    try:
        # Find version
        version_query = select(AppVersion).where(AppVersion.version == version)
        app_version = session.exec(version_query).first()

        if not app_version:
            return error_response(message="Version not found", code=404)

        # Get changelog
        changelog_query = select(Changelog).where(
            and_(
                Changelog.version_id == app_version.id,
                Changelog.language == language
            )
        )
        changelog = session.exec(changelog_query).first()

        if not changelog:
            return error_response(message="Changelog not found", code=404)

        return success_response(data=ChangelogHelper.to_dict(changelog))

    except Exception as e:
        logger.error(f"Error getting changelog: {str(e)}", exc_info=True)
        return error_response(message="Failed to get changelog", code=500)


@router.post("/stats", response_model=dict)
async def record_stats(
    stats_data: UpdateStatsCreate,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_user),
    request: Request = None
):
    """
    Record update statistics

    Optional authentication. User info is tracked if authenticated.
    """
    try:
        # Find latest version for the platform
        latest = UpdateService.get_latest_version(
            session=session,
            platform=stats_data.platform
        )

        if not latest:
            return error_response(message="No version found", code=404)

        UpdateService._record_stats(
            session=session,
            version_id=latest.id,
            action=stats_data.action,
            client_version=stats_data.client_version,
            platform=stats_data.platform,
            user_id=current_user.id if current_user else None,
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None,
            error_message=stats_data.error_message
        )

        return success_response(message="Stats recorded successfully")

    except Exception as e:
        logger.error(f"Error recording stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to record stats", code=500)


# ==================== Admin Endpoints ====================

def require_admin(current_user: User = Depends(get_current_active_user)):
    """Dependency to require admin role"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/admin/versions", response_model=dict)
async def list_versions(
    pagination: PaginationParams = Depends(),
    platform: Optional[str] = None,
    channel: Optional[str] = None,
    is_active: Optional[bool] = None,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    List all versions with pagination and filtering

    Admin only.
    """
    try:
        # Build query
        query = select(AppVersion)

        # Apply filters
        conditions = []
        if platform:
            conditions.append(AppVersion.platform == platform)
        if channel:
            conditions.append(AppVersion.channel == channel)
        if is_active is not None:
            conditions.append(AppVersion.is_active == is_active)

        if conditions:
            query = query.where(and_(*conditions))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = session.exec(count_query).one()

        # Apply pagination
        query = query.order_by(AppVersion.created_at.desc())
        query = query.offset((pagination.page - 1) * pagination.page_size)
        query = query.limit(pagination.page_size)

        versions = session.exec(query).all()

        # Build response with stats
        items = []
        for version in versions:
            stats = UpdateService.get_version_stats(session, version.id)
            items.append(
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

        paginated = PaginatedResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=(total + pagination.page_size - 1) // pagination.page_size
        )

        return success_response(data=paginated.dict())

    except Exception as e:
        logger.error(f"Error listing versions: {str(e)}", exc_info=True)
        return error_response(message="Failed to list versions", code=500)


@router.get("/admin/versions/{version_id}", response_model=dict)
async def get_version_detail(
    version_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get detailed version information including changelogs

    Admin only.
    """
    try:
        version = session.get(AppVersion, version_id)
        if not version:
            return error_response(message="Version not found", code=404)

        # Get all changelogs
        changelog_query = select(Changelog).where(Changelog.version_id == version_id)
        changelogs = session.exec(changelog_query).all()

        changelogs_dict = {
            changelog.language: ChangelogHelper.to_dict(changelog)
            for changelog in changelogs
        }

        # Build response dict with proper JSON fields parsing
        version_dict = version.dict()
        # Ensure allowed_group_ids and allowed_user_ids are lists
        version_dict['allowed_group_ids'] = version.allowed_group_ids if isinstance(version.allowed_group_ids, list) else []
        version_dict['allowed_user_ids'] = version.allowed_user_ids if isinstance(version.allowed_user_ids, list) else []

        response = VersionDetailResponse(
            **version_dict,
            changelogs=changelogs_dict
        )

        return success_response(data=response.dict())

    except Exception as e:
        logger.error(f"Error getting version detail: {str(e)}", exc_info=True)
        return error_response(message="Failed to get version detail", code=500)


@router.post("/admin/versions", response_model=dict)
async def create_version(
    version_data: VersionCreate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Create a new version or update existing one (metadata only, file uploaded separately)

    Admin only. If version already exists, updates it instead of failing.
    """
    try:
        # Check if version already exists
        existing = session.exec(
            select(AppVersion).where(
                and_(
                    AppVersion.version == version_data.version,
                    AppVersion.platform == version_data.platform
                )
            )
        ).first()

        if existing:
            # Update existing version
            existing.title = version_data.title
            existing.channel = version_data.channel
            existing.is_forced = version_data.is_forced
            existing.min_version = version_data.min_version
            existing.rollout_percentage = version_data.rollout_percentage
            existing.visibility = version_data.visibility
            existing.allowed_group_ids = version_data.allowed_group_ids
            existing.allowed_user_ids = version_data.allowed_user_ids

            session.add(existing)
            session.commit()
            session.refresh(existing)

            # Update changelogs if provided
            if version_data.changelogs:
                for lang, changelog_data in version_data.changelogs.items():
                    # Check if changelog exists for this language
                    existing_changelog = session.exec(
                        select(Changelog).where(
                            and_(
                                Changelog.version_id == existing.id,
                                Changelog.language == lang
                            )
                        )
                    ).first()

                    changelog_dict = changelog_data.model_dump() if hasattr(changelog_data, 'model_dump') else changelog_data.dict()

                    if existing_changelog:
                        # Update existing changelog
                        existing_changelog.title = changelog_dict.get('title', '')
                        existing_changelog.description = changelog_dict.get('description', '')
                        existing_changelog.features = changelog_dict.get('features', [])
                        existing_changelog.improvements = changelog_dict.get('improvements', [])
                        existing_changelog.bugfixes = changelog_dict.get('bugfixes', [])
                        session.add(existing_changelog)
                    else:
                        # Create new changelog
                        changelog = ChangelogHelper.create_from_dict(
                            data=changelog_dict,
                            version_id=existing.id,
                            language=lang
                        )
                        session.add(changelog)
                session.commit()

            return success_response(
                message="Version updated successfully.",
                data={
                    "id": existing.id,
                    "version": existing.version,
                    "version_code": existing.version_code,
                    "title": existing.title,
                    "channel": existing.channel,
                    "platform": existing.platform,
                    "is_active": existing.is_active,
                    "is_updated": True
                }
            )

        # Create version record (placeholder for file upload)
        version_code = AppVersion.parse_version_to_code(version_data.version)

        new_version = AppVersion(
            version=version_data.version,
            version_code=version_code,
            title=version_data.title,
            channel=version_data.channel,
            platform=version_data.platform,
            file_path="",  # Will be set during upload
            file_size=0,  # Will be set during upload
            file_hash="",  # Will be set during upload
            signature="",  # Will be set during upload
            is_forced=version_data.is_forced,
            min_version=version_data.min_version,
            rollout_percentage=version_data.rollout_percentage,
            visibility=version_data.visibility,
            allowed_group_ids=version_data.allowed_group_ids,
            allowed_user_ids=version_data.allowed_user_ids,
            published_by=admin.id,
            is_active=False  # Not active until files are uploaded
        )

        session.add(new_version)
        session.commit()
        session.refresh(new_version)

        # Create changelogs if provided
        if version_data.changelogs:
            for lang, changelog_data in version_data.changelogs.items():
                # Convert Pydantic model to dict
                changelog_dict = changelog_data.model_dump() if hasattr(changelog_data, 'model_dump') else changelog_data.dict()
                changelog = ChangelogHelper.create_from_dict(
                    data=changelog_dict,
                    version_id=new_version.id,
                    language=lang
                )
                session.add(changelog)
            session.commit()

        return success_response(
            message="Version created. Please upload files next.",
            data={
                "id": new_version.id,
                "version": new_version.version,
                "version_code": new_version.version_code,
                "title": new_version.title,
                "channel": new_version.channel,
                "platform": new_version.platform,
                "is_active": new_version.is_active,
                "is_updated": False
            }
        )

    except Exception as e:
        logger.error(f"Error creating version: {str(e)}", exc_info=True)
        session.rollback()
        return error_response(message="Failed to create version", code=500)


@router.post("/admin/versions/{version_id}/upload", response_model=dict)
async def upload_version_file(
    version_id: int,
    file: UploadFile = File(...),
    signature: UploadFile = File(...),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Upload update file and signature for a version

    Admin only. Files are saved to uploads/updates/{version}/
    """
    try:
        version = session.get(AppVersion, version_id)
        if not version:
            return error_response(message="Version not found", code=404)

        # Create upload directory
        upload_dir = os.path.join("uploads", "updates", version.version)
        os.makedirs(upload_dir, exist_ok=True)

        # Save update file
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Save signature file
        sig_path = os.path.join(upload_dir, signature.filename)
        with open(sig_path, "wb") as f:
            sig_content = await signature.read()
            f.write(sig_content)

        # Calculate file hash
        file_hash = UpdateService.calculate_file_hash(file_path)

        # Read signature content
        with open(sig_path, "r") as f:
            sig_text = f.read().strip()

        # Update version with file info
        version.file_path = file_path
        version.file_size = os.path.getsize(file_path)
        version.file_hash = file_hash
        version.signature = sig_text
        version.published_at = datetime.now(timezone.utc)
        version.published_by = admin.id

        session.add(version)
        session.commit()

        return success_response(
            message="Files uploaded successfully",
            data={
                "file_path": file_path,
                "file_size": version.file_size,
                "file_hash": file_hash
            }
        )

    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}", exc_info=True)
        return error_response(message="Failed to upload files", code=500)


@router.put("/admin/versions/{version_id}", response_model=dict)
async def update_version(
    version_id: int,
    update_data: VersionUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Update version metadata

    Admin only.
    """
    try:
        version = UpdateService.update_version(session, version_id, update_data)
        if not version:
            return error_response(message="Version not found", code=404)

        return success_response(message="Version updated successfully")

    except Exception as e:
        logger.error(f"Error updating version: {str(e)}", exc_info=True)
        return error_response(message="Failed to update version", code=500)


@router.delete("/admin/versions/{version_id}", response_model=dict)
async def delete_version(
    version_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Delete a version and its files

    Admin only.
    """
    try:
        success = UpdateService.delete_version(session, version_id)
        if not success:
            return error_response(message="Version not found", code=404)

        return success_response(message="Version deleted successfully")

    except Exception as e:
        logger.error(f"Error deleting version: {str(e)}", exc_info=True)
        return error_response(message="Failed to delete version", code=500)


@router.post("/admin/versions/{version_id}/activate", response_model=dict)
async def activate_version(
    version_id: int,
    request: ActivateVersionRequest,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Activate or deactivate a version

    Admin only.
    """
    try:
        version = session.get(AppVersion, version_id)
        if not version:
            return error_response(message="Version not found", code=404)

        version.is_active = request.is_active
        session.add(version)
        session.commit()

        status = "activated" if request.is_active else "deactivated"
        return success_response(message=f"Version {status} successfully")

    except Exception as e:
        logger.error(f"Error activating version: {str(e)}", exc_info=True)
        return error_response(message="Failed to activate version", code=500)


@router.put("/admin/versions/{version_id}/settings", response_model=dict)
async def update_version_settings(
    version_id: int,
    settings_data: VersionSettingsUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Update version settings (rollout, forced update, etc.)

    Admin only.
    """
    try:
        version = session.get(AppVersion, version_id)
        if not version:
            return error_response(message="Version not found", code=404)

        if settings_data.is_forced is not None:
            version.is_forced = settings_data.is_forced
        if settings_data.min_version is not None:
            version.min_version = settings_data.min_version
        if settings_data.rollout_percentage is not None:
            version.rollout_percentage = settings_data.rollout_percentage
        if settings_data.channel is not None:
            version.channel = settings_data.channel
        if settings_data.visibility is not None:
            version.visibility = settings_data.visibility
        if settings_data.allowed_group_ids is not None:
            version.allowed_group_ids = settings_data.allowed_group_ids
        if settings_data.allowed_user_ids is not None:
            version.allowed_user_ids = settings_data.allowed_user_ids

        session.add(version)
        session.commit()

        return success_response(message="Settings updated successfully")

    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}", exc_info=True)
        return error_response(message="Failed to update settings", code=500)


@router.put("/admin/versions/{version_id}/changelog", response_model=dict)
async def update_changelog(
    version_id: int,
    language: str,
    changelog_data: ChangelogUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Update or create changelog for a version

    Admin only.
    """
    try:
        # Find existing changelog
        existing = session.exec(
            select(Changelog).where(
                and_(
                    Changelog.version_id == version_id,
                    Changelog.language == language
                )
            )
        ).first()

        if existing:
            # Update existing
            update_dict = changelog_data.dict(exclude_unset=True)
            for key, value in update_dict.items():
                if key in ["features", "improvements", "bugfixes"] and value is not None:
                    setattr(existing, key, json.dumps(value, ensure_ascii=False))
                else:
                    setattr(existing, key, value)
            session.add(existing)
        else:
            # Create new
            new_changelog = ChangelogHelper.create_from_dict(
                data=changelog_data.dict(),
                version_id=version_id,
                language=language
            )
            session.add(new_changelog)

        session.commit()
        return success_response(message="Changelog updated successfully")

    except Exception as e:
        logger.error(f"Error updating changelog: {str(e)}", exc_info=True)
        return error_response(message="Failed to update changelog", code=500)


@router.get("/admin/stats", response_model=dict)
async def get_dashboard_stats(
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get overall dashboard statistics

    Admin only.
    """
    try:
        stats = UpdateService.get_dashboard_stats(session)
        return success_response(data=stats.dict())

    except Exception as e:
        logger.error(f"Error getting dashboard stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get stats", code=500)


@router.get("/admin/versions/{version_id}/stats", response_model=dict)
async def get_version_stats(
    version_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get statistics for a specific version

    Admin only.
    """
    try:
        version = session.get(AppVersion, version_id)
        if not version:
            return error_response(message="Version not found", code=404)

        stats = UpdateService.get_version_stats(session, version_id)
        if not stats:
            return error_response(message="No stats available", code=404)

        response = VersionStatsResponse(
            version=version.version,
            version_code=version.version_code,
            title=version.title,
            channel=version.channel,
            platform=version.platform,
            published_at=version.published_at,
            stats=stats
        )

        return success_response(data=response.dict())

    except Exception as e:
        logger.error(f"Error getting version stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get version stats", code=500)
