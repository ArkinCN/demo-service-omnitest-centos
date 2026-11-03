"""
Update management schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


# ==================== Changelog Schemas ====================

class ChangelogBase(BaseModel):
    """Base changelog schema"""
    title: str = Field(min_length=1, max_length=200, description="更新标题")
    description: str = Field(min_length=1, description="更新说明 (Markdown格式)")
    features: Optional[List[str]] = Field(default=None, description="新增功能列表")
    improvements: Optional[List[str]] = Field(default=None, description="优化改进列表")
    bugfixes: Optional[List[str]] = Field(default=None, description="问题修复列表")


class ChangelogCreate(ChangelogBase):
    """Schema for creating a changelog"""
    language: str = Field(default="zh-Hans", pattern="^(zh-Hans|en)$", description="语言代码")

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Ensure language code is lowercase with dash"""
        return v.lower()


class ChangelogUpdate(BaseModel):
    """Schema for updating a changelog"""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200, description="更新标题")
    description: Optional[str] = Field(default=None, min_length=1, description="更新说明")
    features: Optional[List[str]] = Field(default=None, description="新增功能列表")
    improvements: Optional[List[str]] = Field(default=None, description="优化改进列表")
    bugfixes: Optional[List[str]] = Field(default=None, description="问题修复列表")


class ChangelogResponse(BaseModel):
    """Schema for changelog response"""
    id: int
    version_id: int
    language: str
    title: str
    description: str
    features: List[str]
    improvements: List[str]
    bugfixes: List[str]
    markdown: str
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


# ==================== Version Schemas ====================

class VersionBase(BaseModel):
    """Base version schema"""
    version: str = Field(min_length=1, max_length=50, description="版本号 (如 1.0.0)")
    title: str = Field(min_length=1, max_length=200, description="版本标题")
    channel: str = Field(default="stable", pattern="^(stable|beta|alpha)$", description="发布渠道")
    platform: str = Field(default="windows", pattern="^(windows|macos|linux)$", description="平台")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Remove 'v' prefix if present"""
        return v.lstrip('v')


class VersionCreate(VersionBase):
    """Schema for creating a new version"""
    is_forced: bool = Field(default=False, description="是否强制更新")
    min_version: Optional[str] = Field(default=None, description="最低兼容版本")
    rollout_percentage: int = Field(default=100, ge=0, le=100, description="灰度发布百分比")

    # User whitelist for update
    visibility: str = Field(default="ALL", pattern="^(ALL|SPECIFIED)$", description="可见性：ALL(全员)/SPECIFIED(指定人员)")
    allowed_group_ids: List[int] = Field(default_factory=list, description="允许更新的分组ID列表")
    allowed_user_ids: List[int] = Field(default_factory=list, description="允许更新的用户ID列表")

    # Changelogs for different languages
    changelogs: Dict[str, ChangelogCreate] = Field(
        default_factory=dict,
        description="多语言更新日志 (key: language code)"
    )


class VersionUpdate(BaseModel):
    """Schema for updating version metadata"""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    channel: Optional[str] = Field(default=None, pattern="^(stable|beta|alpha)$")
    is_forced: Optional[bool] = None
    min_version: Optional[str] = None
    rollout_percentage: Optional[int] = Field(default=None, ge=0, le=100)

    # User whitelist for update
    visibility: Optional[str] = Field(default=None, pattern="^(ALL|SPECIFIED)$", description="可见性：ALL(全员)/SPECIFIED(指定人员)")
    allowed_group_ids: Optional[List[int]] = Field(default=None, description="允许更新的分组ID列表")
    allowed_user_ids: Optional[List[int]] = Field(default=None, description="允许更新的用户ID列表")


class VersionSettingsUpdate(BaseModel):
    """Schema for updating version settings"""
    is_forced: Optional[bool] = Field(default=None, description="是否强制更新")
    min_version: Optional[str] = Field(default=None, description="最低兼容版本")
    rollout_percentage: Optional[int] = Field(default=None, ge=0, le=100, description="灰度发布百分比")
    channel: Optional[str] = Field(default=None, pattern="^(stable|beta)$", description="发布渠道: stable/beta")

    # User whitelist for update
    visibility: Optional[str] = Field(default=None, pattern="^(ALL|SPECIFIED)$", description="可见性：ALL(全员)/SPECIFIED(指定人员)")
    allowed_group_ids: Optional[List[int]] = Field(default=None, description="允许更新的分组ID列表")
    allowed_user_ids: Optional[List[int]] = Field(default=None, description="允许更新的用户ID列表")


class VersionFileInfo(BaseModel):
    """Schema for version file information"""
    file_size: int = Field(description="文件大小(字节)")
    file_hash: str = Field(description="文件SHA256哈希")
    signature: str = Field(description="Tauri签名内容")


class VersionResponse(BaseModel):
    """Schema for version response"""
    id: int
    version: str
    version_code: int
    title: str
    channel: str
    platform: str
    file_path: str
    file_size: int
    file_hash: str
    signature: str
    is_forced: bool
    min_version: Optional[str]
    rollout_percentage: int
    visibility: str
    allowed_group_ids: List[int]
    allowed_user_ids: List[int]
    published_by: Optional[int]
    published_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class VersionDetailResponse(VersionResponse):
    """Schema for detailed version response with changelogs"""
    changelogs: Dict[str, ChangelogResponse] = Field(default_factory=dict, description="多语言更新日志")


class VersionListItem(BaseModel):
    """Schema for version list item (simplified)"""
    id: int
    version: str
    version_code: int
    title: str
    channel: str
    platform: str
    file_size: int
    is_forced: bool
    rollout_percentage: int
    visibility: str
    allowed_group_ids: List[int]
    allowed_user_ids: List[int]
    is_active: bool
    published_at: Optional[datetime]
    created_at: datetime
    download_count: int = Field(default=0, description="下载次数")
    install_count: int = Field(default=0, description="安装次数")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


# ==================== Update Check Schemas ====================

class CheckUpdateRequest(BaseModel):
    """Schema for check update request"""
    current_version: str = Field(description="客户端当前版本")
    platform: str = Field(default="windows", pattern="^(windows|macos|linux)$", description="平台")
    channel: str = Field(default="stable", pattern="^(stable|beta|alpha)$", description="渠道")
    language: str = Field(default="zh-Hans", description="语言偏好")


class CheckUpdateResponse(BaseModel):
    """Schema for check update response"""
    has_update: bool = Field(description="是否有可用更新")
    current_version: Optional[str] = Field(default=None, description="当前版本")
    version: Optional[str] = Field(default=None, description="最新版本号")
    version_code: Optional[int] = Field(default=None, description="最新版本码")
    title: Optional[str] = Field(default=None, description="版本标题")
    channel: Optional[str] = Field(default=None, description="发布渠道: stable/beta/alpha")
    is_forced: Optional[bool] = Field(default=None, description="是否强制更新")
    file_size: Optional[int] = Field(default=None, description="文件大小")
    file_hash: Optional[str] = Field(default=None, description="文件哈希")
    signature: Optional[str] = Field(default=None, description="文件签名")
    download_url: Optional[str] = Field(default=None, description="下载地址")
    changelog: Optional[Dict[str, Any]] = Field(default=None, description="更新日志")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


# ==================== Statistics Schemas ====================

class UpdateStatsCreate(BaseModel):
    """Schema for creating update statistics"""
    action: str = Field(pattern="^(check|download|install|complete|error)$", description="操作类型")
    client_version: str = Field(description="客户端版本")
    platform: str = Field(pattern="^(windows|macos|linux)$", description="平台")
    error_message: Optional[str] = Field(default=None, description="错误信息")


class UpdateStatsResponse(BaseModel):
    """Schema for update statistics response"""
    id: int
    version_id: int
    user_id: Optional[int]
    action: str
    client_version: str
    platform: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class StatsAggregation(BaseModel):
    """Schema for aggregated statistics"""
    total_checks: int = Field(description="检查次数")
    total_downloads: int = Field(description="下载次数")
    total_installs: int = Field(description="安装次数")
    total_completes: int = Field(description="完成次数")
    total_errors: int = Field(description="错误次数")
    success_rate: float = Field(description="成功率 (0-100)")


class VersionStatsResponse(BaseModel):
    """Schema for version statistics response"""
    version: str
    version_code: int
    title: str
    channel: str
    platform: str
    published_at: Optional[datetime]
    stats: StatsAggregation

    class Config:
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class PlatformDistribution(BaseModel):
    """Schema for platform distribution"""
    platform: str
    count: int
    percentage: float


class ChannelDistribution(BaseModel):
    """Schema for channel distribution"""
    channel: str
    count: int
    percentage: float


class DashboardStatsResponse(BaseModel):
    """Schema for dashboard statistics response"""
    total_versions: int = Field(description="总版本数")
    active_versions: int = Field(description="激活版本数")
    total_downloads: int = Field(description="总下载次数")
    total_installs: int = Field(description="总安装次数")
    overall_success_rate: float = Field(description="总体成功率")
    platform_distribution: List[PlatformDistribution] = Field(description="平台分布")
    channel_distribution: List[ChannelDistribution] = Field(description="渠道分布")
    recent_versions: List[VersionListItem] = Field(description="最近版本列表")


# ==================== File Upload Schemas ====================

class UploadInitiateRequest(BaseModel):
    """Schema for initiating file upload"""
    version: str = Field(description="版本号")
    filename: str = Field(description="文件名")
    file_size: int = Field(description="文件大小(字节)")
    content_type: str = Field(default="application/octet-stream", description="内容类型")


class UploadInitiateResponse(BaseModel):
    """Schema for upload initiation response"""
    upload_id: str = Field(description="上传ID")
    chunk_size: int = Field(description="分块大小(字节)")
    total_chunks: int = Field(description="总分块数")


class UploadChunkRequest(BaseModel):
    """Schema for uploading a chunk"""
    upload_id: str = Field(description="上传ID")
    chunk_index: int = Field(description="分块索引(0-based)")


class UploadChunkResponse(BaseModel):
    """Schema for chunk upload response"""
    chunk_index: int
    uploaded: bool
    progress: float = Field(description="上传进度 (0-100)")


class UploadCompleteRequest(BaseModel):
    """Schema for completing upload"""
    upload_id: str = Field(description="上传ID")
    file_hash: str = Field(description="文件SHA256哈希")


class UploadCompleteResponse(BaseModel):
    """Schema for upload completion response"""
    file_path: str = Field(description="文件路径")
    file_size: int = Field(description="文件大小")
    file_hash: str = Field(description="文件哈希")


# ==================== Admin Operations Schemas ====================

class ActivateVersionRequest(BaseModel):
    """Schema for activating/deactivating a version"""
    is_active: bool = Field(description="是否激活")


class RollbackVersionRequest(BaseModel):
    """Schema for rolling back to a previous version"""
    target_version: str = Field(description="目标版本号")


class BulkDeleteRequest(BaseModel):
    """Schema for bulk delete operations"""
    version_ids: List[int] = Field(description="版本ID列表")
