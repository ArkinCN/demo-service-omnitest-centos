"""
Code Review models using SQLModel
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON, Text


class CodeReview(SQLModel, table=True):
    """
    Code Review database model

    Attributes:
        id: Primary key
        user_id: Foreign key to users table (reviewer)
        reviewer_name: Reviewer's nickname (redundant storage for performance)
        reviewer_avatar: Reviewer's avatar URL
        title: Review title
        group_id: GitLab group ID (optional)
        project_id: GitLab project ID (optional)
        branch: Git branch name
        check_type: Check type (GROUP/PROJECT)
        check_mode: Check mode (SINGLE/BATCH)
        file_name: File name for single file check
        ai_model: AI model used for review
        ai_prompt: AI prompt text
        ref_issue: Reference issue URL
        total_projects: Total number of projects checked
        normal_count: Number of projects with no issues
        issue_count: Number of projects with issues found
        error_count: Number of projects with errors
        not_found_count: Number of projects with files not found
        status: Review status (PENDING/PROCESSING/COMPLETED/FAILED)
        is_shared: Whether this review is shared
        share_scope: Share scope (PRIVATE/TEAM/PUBLIC)
        shared_at: Share timestamp
        view_count: Number of views
        tags: Tags array (JSON)
        description: Review description
        created_at: Creation timestamp
        updated_at: Last update timestamp
        completed_at: Completion timestamp
    """
    __tablename__ = "code_reviews"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # User relation
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="审查者用户ID"
    )
    reviewer_name: str = Field(
        max_length=100,
        nullable=False,
        description="审查者昵称"
    )
    reviewer_avatar: Optional[str] = Field(
        default=None,
        max_length=500,
        description="审查者头像URL"
    )

    # Review configuration
    title: str = Field(
        default="代码审查",
        max_length=200,
        nullable=False,
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
        nullable=False,
        description="Git分支"
    )
    check_type: str = Field(
        max_length=20,
        nullable=False,
        index=True,
        description="检查类型：GROUP/PROJECT"
    )
    check_mode: str = Field(
        max_length=20,
        nullable=False,
        index=True,
        description="检查模式：SINGLE/BATCH"
    )
    file_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="单文件检查的文件名"
    )

    # AI configuration
    ai_model: str = Field(
        max_length=50,
        nullable=False,
        description="AI模型名称"
    )
    ai_prompt: str = Field(
        sa_column=Column(Text, nullable=False),
        description="AI提示词"
    )
    ref_issue: Optional[str] = Field(
        default=None,
        max_length=200,
        description="参考议题URL"
    )

    # Statistics
    total_projects: int = Field(
        default=0,
        nullable=False,
        description="总项目数"
    )
    normal_count: int = Field(
        default=0,
        nullable=False,
        description="检查正常数量"
    )
    issue_count: int = Field(
        default=0,
        nullable=False,
        description="发现问题数量"
    )
    error_count: int = Field(
        default=0,
        nullable=False,
        description="检查错误数量"
    )
    not_found_count: int = Field(
        default=0,
        nullable=False,
        description="未找到文件数量"
    )

    # Status management
    status: str = Field(
        default="PENDING",
        max_length=20,
        nullable=False,
        index=True,
        description="状态：PENDING/PROCESSING/COMPLETED/FAILED"
    )

    # Share functionality
    is_shared: bool = Field(
        default=False,
        nullable=False,
        index=True,
        description="是否分享"
    )
    share_scope: str = Field(
        default="PRIVATE",
        max_length=20,
        nullable=False,
        index=True,
        description="分享范围：PRIVATE/TEAM/PUBLIC"
    )
    shared_at: Optional[datetime] = Field(
        default=None,
        description="分享时间"
    )
    view_count: int = Field(
        default=0,
        nullable=False,
        description="查看次数"
    )

    # Tags and description
    tags: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="标签数组"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="审查描述"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="更新时间"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="完成时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class CodeReviewResult(SQLModel, table=True):
    """
    Code Review Result database model

    Attributes:
        id: Primary key
        review_id: Foreign key to code_reviews table
        group_name: GitLab group name
        project_name: GitLab project name
        project_id: GitLab project ID
        branch: Git branch name
        file_links: JSON array of file links
        file_count: Number of files
        status: Check status (NORMAL/ISSUE/ERROR/NOT_FOUND)
        issue_description: Issue description text
        severity: Issue severity (LOW/MEDIUM/HIGH/CRITICAL)
        ai_analysis: Full AI analysis result (JSON)
        created_at: Creation timestamp
    """
    __tablename__ = "code_review_results"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key
    review_id: int = Field(
        foreign_key="code_reviews.id",
        nullable=False,
        index=True,
        description="代码审查ID"
    )

    # Project information
    group_name: str = Field(
        max_length=200,
        nullable=False,
        description="群组名称"
    )
    project_name: str = Field(
        max_length=200,
        nullable=False,
        index=True,
        description="项目名称"
    )
    project_id: str = Field(
        max_length=100,
        nullable=False,
        description="项目ID"
    )
    branch: str = Field(
        max_length=100,
        nullable=False,
        description="分支名称"
    )
    project_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="项目完整URL"
    )

    # File information
    file_links: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="文件链接数组"
    )
    file_count: int = Field(
        default=0,
        nullable=False,
        description="文件数量"
    )

    # Review result
    status: str = Field(
        max_length=20,
        nullable=False,
        index=True,
        description="检查状态：NORMAL/ISSUE/ERROR/NOT_FOUND"
    )
    issue_description: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="问题描述"
    )
    severity: Optional[str] = Field(
        default=None,
        max_length=20,
        index=True,
        description="严重程度：LOW/MEDIUM/HIGH/CRITICAL"
    )

    # AI analysis details
    ai_analysis: Optional[str] = Field(
        default=None,
        sa_column=Column(JSON),
        description="AI完整分析结果"
    )

    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class CodeReviewShare(SQLModel, table=True):
    """
    Code Review Share database model

    Attributes:
        id: Primary key
        review_id: Foreign key to code_reviews table
        shared_by: Foreign key to users table (sharer)
        viewed_by: Foreign key to users table (viewer, optional)
        share_link: Unique share link UUID
        share_message: Share message
        allowed_users: JSON array of allowed user IDs
        expires_at: Expiration timestamp
        created_at: Creation timestamp
        last_viewed_at: Last view timestamp
    """
    __tablename__ = "code_review_shares"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    review_id: int = Field(
        foreign_key="code_reviews.id",
        nullable=False,
        index=True,
        description="代码审查ID"
    )
    shared_by: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="分享者用户ID"
    )
    viewed_by: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        description="查看者用户ID"
    )

    # Share information
    share_link: str = Field(
        max_length=100,
        nullable=False,
        unique=True,
        index=True,
        description="分享链接UUID"
    )
    share_message: Optional[str] = Field(
        default=None,
        max_length=500,
        description="分享留言"
    )

    # Access control
    allowed_users: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户ID数组"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="过期时间"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )
    last_viewed_at: Optional[datetime] = Field(
        default=None,
        description="最后查看时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class CodeReviewComment(SQLModel, table=True):
    """
    Code Review Comment database model

    Attributes:
        id: Primary key
        review_id: Foreign key to code_reviews table
        result_id: Foreign key to code_review_results table (optional)
        user_id: Foreign key to users table (commenter)
        content: Comment content
        comment_type: Comment type (COMMENT/QUESTION/SUGGESTION)
        parent_id: Foreign key to self for reply support
        likes_count: Number of likes
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "code_review_comments"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    review_id: int = Field(
        foreign_key="code_reviews.id",
        nullable=False,
        index=True,
        description="代码审查ID"
    )
    result_id: Optional[int] = Field(
        default=None,
        foreign_key="code_review_results.id",
        index=True,
        description="审查结果ID（针对具体结果的评论）"
    )
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="评论用户ID"
    )

    # Comment content
    content: str = Field(
        sa_column=Column(Text, nullable=False),
        description="评论内容"
    )
    comment_type: str = Field(
        default="COMMENT",
        max_length=20,
        nullable=False,
        index=True,
        description="评论类型：COMMENT/QUESTION/SUGGESTION"
    )

    # Reply support
    parent_id: Optional[int] = Field(
        default=None,
        foreign_key="code_review_comments.id",
        index=True,
        description="父评论ID（支持回复）"
    )

    # Likes
    likes_count: int = Field(
        default=0,
        nullable=False,
        description="点赞数"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="更新时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class CodeReviewStats(SQLModel, table=True):
    """
    Code Review Statistics database model

    Attributes:
        id: Primary key
        user_id: Foreign key to users table (unique)
        total_reviews: Total number of reviews
        total_projects: Total number of projects reviewed
        total_issues_found: Total number of issues found
        total_shared: Total number of times shared
        total_views_received: Total number of views received
        last_review_at: Last review timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "code_review_stats"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key (unique)
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        unique=True,
        index=True,
        description="用户ID"
    )

    # Statistics
    total_reviews: int = Field(
        default=0,
        nullable=False,
        description="总审查次数"
    )
    total_projects: int = Field(
        default=0,
        nullable=False,
        description="总审查项目数"
    )
    total_issues_found: int = Field(
        default=0,
        nullable=False,
        description="总发现问题数"
    )
    total_shared: int = Field(
        default=0,
        nullable=False,
        description="总分享次数"
    )
    total_views_received: int = Field(
        default=0,
        nullable=False,
        description="总被查看次数"
    )

    # Timestamps
    last_review_at: Optional[datetime] = Field(
        default=None,
        description="最后审查时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="更新时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True
