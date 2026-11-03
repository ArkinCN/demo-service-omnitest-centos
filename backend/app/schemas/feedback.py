"""
Feedback schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional, List, ForwardRef
from pydantic import BaseModel, Field, field_validator
import json


# =============================================================================
# Feedback Module Schemas
# =============================================================================

class FeedbackModuleCreate(BaseModel):
    """Schema for creating a new feedback module"""
    name: str = Field(
        min_length=1,
        max_length=50,
        description="模块名称"
    )
    parent_id: Optional[int] = Field(
        default=None,
        description="父模块ID，NULL表示一级模块"
    )
    sort_order: int = Field(
        default=0,
        description="排序顺序"
    )
    is_active: bool = Field(
        default=True,
        description="是否启用"
    )


class FeedbackModuleUpdate(BaseModel):
    """Schema for updating a feedback module"""
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="模块名称"
    )
    parent_id: Optional[int] = Field(
        default=None,
        description="父模块ID"
    )
    sort_order: Optional[int] = Field(
        default=None,
        description="排序顺序"
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="是否启用"
    )


class FeedbackModuleResponse(BaseModel):
    """Schema for feedback module response"""
    id: int = Field(description="模块ID")
    name: str = Field(description="模块名称")
    parent_id: Optional[int] = Field(default=None, description="父模块ID")
    sort_order: int = Field(description="排序顺序")
    is_active: bool = Field(description="是否启用")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class FeedbackModuleTreeNode(BaseModel):
    """Schema for feedback module tree node (with children)"""
    id: int = Field(description="模块ID")
    name: str = Field(description="模块名称")
    parent_id: Optional[int] = Field(default=None, description="父模块ID")
    sort_order: int = Field(description="排序顺序")
    is_active: bool = Field(description="是否启用")
    children: List["FeedbackModuleTreeNode"] = Field(default_factory=list, description="子模块列表")

    class Config:
        from_attributes = True


# Rebuild model to resolve forward reference
FeedbackModuleTreeNode.model_rebuild()


class FeedbackModuleReorderItem(BaseModel):
    """Schema for reordering a single module"""
    id: int = Field(description="模块ID")
    sort_order: int = Field(description="新的排序顺序")


class FeedbackModuleReorderRequest(BaseModel):
    """Schema for batch reordering modules"""
    updates: List[FeedbackModuleReorderItem] = Field(description="排序更新列表")


# =============================================================================
# Feedback Schemas
# =============================================================================

class FeedbackCreate(BaseModel):
    """Schema for creating a new feedback"""
    module_id: Optional[int] = Field(
        default=None,
        description="关联的功能模块ID"
    )
    category: str = Field(
        description="意见建议分类",
        pattern="^(BUG|FEATURE|QUESTION|OTHER)$"
    )
    description: str = Field(
        min_length=10,
        max_length=5000,
        description="问题描述"
    )
    contact_info: Optional[str] = Field(
        default=None,
        max_length=200,
        description="联系方式"
    )
    attachments: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="截图URL数组（最多3张）"
    )

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is uppercase"""
        return v.upper()


class FeedbackUpdate(BaseModel):
    """Schema for updating feedback (admin only)"""
    status: Optional[str] = Field(
        default=None,
        pattern="^(PENDING|IN_PROGRESS|RESOLVED|CLOSED)$",
        description="状态"
    )
    priority: Optional[str] = Field(
        default=None,
        pattern="^(LOW|MEDIUM|HIGH|URGENT)$",
        description="优先级"
    )
    assigned_to: Optional[int] = Field(
        default=None,
        description="分配给的管理员ID"
    )

    @field_validator("status", "priority")
    @classmethod
    def validate_uppercase(cls, v: Optional[str]) -> Optional[str]:
        """Validate fields are uppercase"""
        return v.upper() if v else v


class FeedbackStatusUpdate(BaseModel):
    """Schema for updating feedback status"""
    status: str = Field(
        pattern="^(PENDING|IN_PROGRESS|RESOLVED|CLOSED)$",
        description="状态"
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status is uppercase"""
        return v.upper()


class FeedbackPriorityUpdate(BaseModel):
    """Schema for updating feedback priority"""
    priority: str = Field(
        pattern="^(LOW|MEDIUM|HIGH|URGENT)$",
        description="优先级"
    )

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Validate priority is uppercase"""
        return v.upper()


class FeedbackAssignUpdate(BaseModel):
    """Schema for assigning feedback to admin"""
    assigned_to: int = Field(description="分配给的管理员ID")


class FeedbackModuleIdUpdate(BaseModel):
    """Schema for updating feedback module"""
    module_id: Optional[int] = Field(default=None, description="功能模块ID，NULL表示不关联任何模块")


class FeedbackResponse(BaseModel):
    """Schema for feedback response"""
    id: int = Field(description="反馈ID")
    user_id: int = Field(description="提交用户ID")
    nickname: Optional[str] = Field(default=None, description="提交用户昵称")
    module_id: Optional[int] = Field(default=None, description="关联的功能模块ID")
    module_name: Optional[str] = Field(default=None, description="功能模块名称")
    category: str = Field(description="意见建议分类")
    description: str = Field(description="问题描述")
    contact_info: Optional[str] = Field(default=None, description="联系方式")
    attachments: List[str] = Field(default_factory=list, description="截图URL数组")
    status: str = Field(description="状态")
    priority: str = Field(description="优先级")
    assigned_to: Optional[int] = Field(default=None, description="分配给的管理员ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    resolved_at: Optional[datetime] = Field(default=None, description="解决时间")

    @field_validator("attachments", mode="before")
    @classmethod
    def parse_attachments(cls, v):
        """Parse attachments from JSON string to list"""
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


class FeedbackListItem(BaseModel):
    """Schema for feedback list item (simplified)"""
    id: int
    user_id: int
    nickname: Optional[str] = None
    module_id: Optional[int] = None
    module_name: Optional[str] = None
    category: str
    description: str
    attachments: List[str] = Field(default_factory=list, description="截图URL数组")
    status: str
    priority: str
    assigned_to: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("attachments", mode="before")
    @classmethod
    def parse_attachments(cls, v):
        """Parse attachments from JSON string to list"""
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


class FeedbackReplyCreate(BaseModel):
    """Schema for creating a feedback reply"""
    content: str = Field(
        min_length=1,
        max_length=2000,
        description="回复内容"
    )
    is_internal: bool = Field(
        default=False,
        description="是否为内部备注（仅管理员可见）"
    )


class FeedbackReplyResponse(BaseModel):
    """Schema for feedback reply response"""
    id: int = Field(description="回复ID")
    feedback_id: int = Field(description="反馈ID")
    user_id: int = Field(description="回复用户ID")
    content: str = Field(description="回复内容")
    is_internal: bool = Field(description="是否为内部备注")
    created_at: datetime = Field(description="创建时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class FeedbackStatsResponse(BaseModel):
    """Schema for feedback statistics response"""
    pending_count: int = Field(description="待处理数量")
    in_progress_count: int = Field(description="处理中数量")
    resolved_count: int = Field(description="已解决数量")
    total_count: int = Field(description="总数")


class FeedbackQueryParams(BaseModel):
    """Schema for feedback query parameters"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")
    status: Optional[str] = Field(default=None, description="状态筛选")
    priority: Optional[str] = Field(default=None, description="优先级筛选")
    category: Optional[str] = Field(default=None, description="分类筛选")
    module_id: Optional[int] = Field(default=None, description="功能模块ID筛选")
    keyword: Optional[str] = Field(default=None, description="关键词搜索")
