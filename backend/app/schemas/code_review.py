"""
Code Review schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
import json


# ============================================================================
# Request Schemas
# ============================================================================

class CodeReviewCreate(BaseModel):
    """Schema for creating a new code review"""
    title: Optional[str] = Field(
        default="代码审查",
        max_length=200,
        description="审查标题"
    )
    group_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="GitLab群组ID"
    )
    project_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="GitLab项目ID"
    )
    branch: str = Field(
        default="master",
        max_length=100,
        description="Git分支"
    )
    check_type: str = Field(
        description="检查类型",
        pattern="^(GROUP|PROJECT)$"
    )
    check_mode: str = Field(
        description="检查模式",
        pattern="^(SINGLE|BATCH)$"
    )
    file_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="单文件检查的文件名"
    )
    ai_model: str = Field(
        max_length=50,
        description="AI模型名称"
    )
    ai_prompt: str = Field(
        min_length=10,
        description="AI提示词"
    )
    ref_issue: Optional[str] = Field(
        default=None,
        max_length=200,
        description="参考议题URL"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="审查描述"
    )
    tags: Optional[List[str]] = Field(
        default=None,
        max_length=10,
        description="标签数组（最多10个）"
    )

    @field_validator("check_type", "check_mode")
    @classmethod
    def validate_uppercase(cls, v: str) -> str:
        """Validate fields are uppercase"""
        return v.upper()


class CodeReviewResultCreate(BaseModel):
    """Schema for creating code review results"""
    review_id: int = Field(description="代码审查ID")
    results: List[Dict[str, Any]] = Field(
        description="审查结果数组"
    )


class CodeReviewShareCreate(BaseModel):
    """Schema for creating a share"""
    review_id: int = Field(description="代码审查ID")
    share_scope: str = Field(
        description="分享范围",
        pattern="^(PRIVATE|TEAM|PUBLIC)$"
    )
    share_message: Optional[str] = Field(
        default=None,
        max_length=500,
        description="分享留言"
    )
    allowed_users: Optional[List[int]] = Field(
        default=None,
        max_length=50,
        description="允许访问的用户ID数组（团队模式）"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="过期时间"
    )

    @field_validator("share_scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        """Validate scope is uppercase"""
        return v.upper()


class CodeReviewShareUpdate(BaseModel):
    """Schema for updating share settings"""
    share_scope: Optional[str] = Field(
        default=None,
        pattern="^(PRIVATE|TEAM|PUBLIC)$",
        description="分享范围"
    )
    share_message: Optional[str] = Field(
        default=None,
        max_length=500,
        description="分享留言"
    )
    allowed_users: Optional[List[int]] = Field(
        default=None,
        description="允许访问的用户ID数组"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="过期时间"
    )

    @field_validator("share_scope")
    @classmethod
    def validate_scope(cls, v: Optional[str]) -> Optional[str]:
        """Validate scope is uppercase"""
        return v.upper() if v else v


class CommentCreate(BaseModel):
    """Schema for creating a comment"""
    content: str = Field(
        min_length=1,
        max_length=2000,
        description="评论内容"
    )
    comment_type: str = Field(
        default="COMMENT",
        pattern="^(COMMENT|QUESTION|SUGGESTION)$",
        description="评论类型"
    )
    result_id: Optional[int] = Field(
        default=None,
        description="审查结果ID（针对具体结果的评论）"
    )
    parent_id: Optional[int] = Field(
        default=None,
        description="父评论ID（用于回复）"
    )

    @field_validator("comment_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate comment type is uppercase"""
        return v.upper()


# ============================================================================
# Response Schemas
# ============================================================================

class CodeReviewResponse(BaseModel):
    """Schema for code review response"""
    id: int = Field(description="审查ID")
    user_id: int = Field(description="审查者用户ID")
    reviewer_name: str = Field(description="审查者昵称")
    reviewer_avatar: Optional[str] = Field(default=None, description="审查者头像")
    title: str = Field(description="审查标题")
    group_id: Optional[str] = Field(default=None, description="群组ID")
    project_id: Optional[str] = Field(default=None, description="项目ID")
    branch: str = Field(description="分支")
    check_type: str = Field(description="检查类型")
    check_mode: str = Field(description="检查模式")
    file_name: Optional[str] = Field(default=None, description="文件名")
    ai_model: str = Field(description="AI模型")
    total_projects: int = Field(description="总项目数")
    normal_count: int = Field(description="检查正常数量")
    issue_count: int = Field(description="发现问题数量")
    error_count: int = Field(description="检查错误数量")
    not_found_count: int = Field(description="未找到文件数量")
    status: str = Field(description="状态")
    is_shared: bool = Field(description="是否分享")
    share_scope: str = Field(description="分享范围")
    view_count: int = Field(description="查看次数")
    tags: List[str] = Field(default_factory=list, description="标签数组")
    description: Optional[str] = Field(default=None, description="审查描述")
    created_at: datetime = Field(description="创建时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")

    # Share information (for owner only)
    share_link: Optional[str] = Field(default=None, description="分享链接")
    is_owner: bool = Field(default=False, description="是否是创建者")

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v):
        """Parse tags from JSON string to list"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if isinstance(v, list) else []

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class CodeReviewListItem(BaseModel):
    """Schema for code review list item (simplified)"""
    id: int
    user_id: int
    reviewer_name: str
    reviewer_avatar: Optional[str] = None
    title: str
    group_id: Optional[str] = None
    project_id: Optional[str] = None
    branch: str
    check_type: str
    check_mode: str
    file_name: Optional[str] = None
    ai_model: str
    ai_prompt: str
    total_projects: int
    normal_count: int = 0
    issue_count: int
    error_count: int = 0
    not_found_count: int = 0
    status: str
    is_shared: bool
    share_scope: str
    share_link: Optional[str] = Field(default=None, description="分享口令（仅owner）")
    view_count: int
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    is_owner: bool = False

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v):
        """Parse tags from JSON string to list"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if isinstance(v, list) else []

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class CodeReviewDetailResponse(BaseModel):
    """Schema for code review detail response (includes config)"""
    id: int
    user_id: int
    reviewer_name: str
    reviewer_avatar: Optional[str] = None
    title: str
    group_id: Optional[str] = None
    project_id: Optional[str] = None
    branch: str
    check_type: str
    check_mode: str
    file_name: Optional[str] = None
    ai_model: str
    ai_prompt: str
    ref_issue: Optional[str] = None
    total_projects: int
    normal_count: int
    issue_count: int
    error_count: int
    not_found_count: int
    status: str
    is_shared: bool
    share_scope: str
    shared_at: Optional[datetime] = None
    view_count: int
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    is_owner: bool = False
    share_link: Optional[str] = None

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v):
        """Parse tags from JSON string to list"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if isinstance(v, list) else []

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class CodeReviewResultResponse(BaseModel):
    """Schema for code review result response"""
    id: int = Field(description="结果ID")
    review_id: int = Field(description="审查ID")
    group_name: str = Field(description="群组名称")
    project_name: str = Field(description="项目名称")
    project_id: str = Field(description="项目ID")
    project_url: Optional[str] = Field(default=None, description="项目完整URL")
    branch: str = Field(description="分支")
    file_links: List[str] = Field(default_factory=list, description="文件链接数组")
    file_count: int = Field(description="文件数量")
    status: str = Field(description="检查状态")
    issue_description: Optional[str] = Field(default=None, description="问题描述")
    severity: Optional[str] = Field(default=None, description="严重程度")
    ai_analysis: Optional[Dict[str, Any]] = Field(default=None, description="AI分析结果")
    created_at: datetime = Field(description="创建时间")

    @field_validator("file_links", mode="before")
    @classmethod
    def parse_file_links(cls, v):
        """Parse file links from JSON string to list"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if isinstance(v, list) else []

    @field_validator("ai_analysis", mode="before")
    @classmethod
    def parse_ai_analysis(cls, v):
        """Parse AI analysis from JSON string to dict"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v if isinstance(v, dict) else None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class CodeReviewShareResponse(BaseModel):
    """Schema for share response"""
    id: int
    review_id: int
    share_link: str
    share_message: Optional[str] = None
    share_scope: str
    allowed_users: List[int] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    created_at: datetime

    @field_validator("allowed_users", mode="before")
    @classmethod
    def parse_allowed_users(cls, v):
        """Parse allowed users from JSON string to list"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if isinstance(v, list) else []

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class CommentResponse(BaseModel):
    """Schema for comment response"""
    id: int
    review_id: int
    result_id: Optional[int] = None
    user_id: int
    user_name: str = Field(description="评论用户昵称")
    user_avatar: Optional[str] = Field(default=None, description="评论用户头像")
    content: str
    comment_type: str
    parent_id: Optional[int] = None
    likes_count: int
    created_at: datetime
    updated_at: datetime

    # Nested replies
    replies: List['CommentResponse'] = Field(default_factory=list, description="回复列表")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


# ============================================================================
# Query Parameters
# ============================================================================

class CodeReviewQueryParams(BaseModel):
    """Schema for code review query parameters"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")
    status: Optional[str] = Field(default=None, description="状态筛选")
    check_type: Optional[str] = Field(default=None, description="检查类型筛选")
    check_mode: Optional[str] = Field(default=None, description="检查模式筛选")
    ai_model: Optional[str] = Field(default=None, description="AI模型筛选")
    keyword: Optional[str] = Field(default=None, description="关键词搜索（标题、描述）")
    sort_by: str = Field(default="created_at", description="排序字段")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$", description="排序方向")


class SharedReviewQueryParams(BaseModel):
    """Schema for shared review query parameters"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")
    scope: Optional[str] = Field(
        default=None,
        pattern="^(TEAM|PUBLIC)$",
        description="分享范围筛选"
    )
    tag: Optional[str] = Field(default=None, description="标签筛选")
    keyword: Optional[str] = Field(default=None, description="关键词搜索")
    sort_by: str = Field(default="shared_at", description="排序字段")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$", description="排序方向")

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: Optional[str]) -> Optional[str]:
        """Validate scope is uppercase"""
        return v.upper() if v else v


# ============================================================================
# Statistics
# ============================================================================

class CodeReviewStatsResponse(BaseModel):
    """Schema for code review statistics response"""
    total_reviews: int = Field(description="总审查次数")
    total_projects: int = Field(description="总审查项目数")
    total_issues_found: int = Field(description="总发现问题数")
    total_shared: int = Field(description="总分享次数")
    total_views_received: int = Field(description="总被查看次数")
    last_review_at: Optional[datetime] = Field(default=None, description="最后审查时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }
