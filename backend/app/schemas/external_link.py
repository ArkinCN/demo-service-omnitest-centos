"""
External Link schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl, field_validator


class ExternalLinkBase(BaseModel):
    """Base external link schema with common fields"""
    title: str = Field(min_length=1, max_length=200, description="链接标题")
    url: str = Field(min_length=1, max_length=1000, description="链接地址")
    description: Optional[str] = Field(default=None, max_length=500, description="链接描述")
    icon_url: Optional[str] = Field(default=None, max_length=500, description="图标URL")
    category: str = Field(min_length=1, max_length=100, description="分类名称")


class RelatedLink(BaseModel):
    """Schema for related link item"""
    name: str = Field(min_length=1, max_length=100, description="关联链接名称")
    url: str = Field(min_length=1, max_length=1000, description="关联链接地址")


class ExternalLinkCreate(ExternalLinkBase):
    """Schema for creating a new external link"""
    tags: List[str] = Field(default_factory=list, description="标签列表")
    maintainer_id: Optional[int] = Field(default=None, description="维护人ID")
    visibility: str = Field(default="ALL", description="可见性：ALL/SPECIFIED")
    allowed_group_ids: List[int] = Field(default_factory=list, description="允许访问的分组ID列表")
    allowed_user_ids: List[int] = Field(default_factory=list, description="允许访问的用户ID列表")
    period_type: str = Field(default="LONG_TERM", description="开放周期：LONG_TERM/SHORT_TERM")
    start_time: Optional[datetime] = Field(default=None, description="开放开始时间")
    end_time: Optional[datetime] = Field(default=None, description="开放结束时间")
    time_pattern: Optional[str] = Field(default=None, max_length=100, description="智能时间模式")
    status: str = Field(default="ACTIVE", description="状态：ACTIVE/INACTIVE/ARCHIVED")
    related_links_url: List[RelatedLink] = Field(default_factory=list, description="关联链接列表")

    @field_validator('visibility')
    @classmethod
    def validate_visibility(cls, v):
        if v not in ['ALL', 'SPECIFIED']:
            raise ValueError('visibility must be ALL or SPECIFIED')
        return v

    @field_validator('period_type')
    @classmethod
    def validate_period_type(cls, v):
        if v not in ['LONG_TERM', 'SHORT_TERM']:
            raise ValueError('period_type must be LONG_TERM or SHORT_TERM')
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in ['ACTIVE', 'INACTIVE', 'ARCHIVED']:
            raise ValueError('status must be ACTIVE, INACTIVE, or ARCHIVED')
        return v


class ExternalLinkUpdate(BaseModel):
    """Schema for updating an external link"""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200, description="链接标题")
    url: Optional[str] = Field(default=None, min_length=1, max_length=1000, description="链接地址")
    description: Optional[str] = Field(default=None, max_length=500, description="链接描述")
    icon_url: Optional[str] = Field(default=None, max_length=500, description="图标URL")
    category: Optional[str] = Field(default=None, min_length=1, max_length=100, description="分类名称")
    tags: Optional[List[str]] = Field(default=None, description="标签列表")
    maintainer_id: Optional[int] = Field(default=None, description="维护人ID")
    visibility: Optional[str] = Field(default=None, description="可见性：ALL/SPECIFIED")
    allowed_group_ids: Optional[List[int]] = Field(default=None, description="允许访问的分组ID列表")
    allowed_user_ids: Optional[List[int]] = Field(default=None, description="允许访问的用户ID列表")
    period_type: Optional[str] = Field(default=None, description="开放周期：LONG_TERM/SHORT_TERM")
    start_time: Optional[datetime] = Field(default=None, description="开放开始时间")
    end_time: Optional[datetime] = Field(default=None, description="开放结束时间")
    time_pattern: Optional[str] = Field(default=None, max_length=100, description="智能时间模式")
    status: Optional[str] = Field(default=None, description="状态：ACTIVE/INACTIVE/ARCHIVED")
    related_links_url: Optional[List[RelatedLink]] = Field(default=None, description="关联链接列表")

    @field_validator('visibility')
    @classmethod
    def validate_visibility(cls, v):
        if v is not None and v not in ['ALL', 'SPECIFIED']:
            raise ValueError('visibility must be ALL or SPECIFIED')
        return v

    @field_validator('period_type')
    @classmethod
    def validate_period_type(cls, v):
        if v is not None and v not in ['LONG_TERM', 'SHORT_TERM']:
            raise ValueError('period_type must be LONG_TERM or SHORT_TERM')
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in ['ACTIVE', 'INACTIVE', 'ARCHIVED']:
            raise ValueError('status must be ACTIVE, INACTIVE, or ARCHIVED')
        return v


class ExternalLinkResponse(BaseModel):
    """Schema for external link response"""
    id: int = Field(description="链接ID")
    title: str = Field(description="链接标题")
    url: str = Field(description="链接地址")
    description: Optional[str] = Field(default=None, description="链接描述")
    icon_url: Optional[str] = Field(default=None, description="图标URL")
    category: str = Field(description="分类名称")
    category_order: int = Field(description="分类排序")
    link_order: int = Field(description="链接排序")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    maintainer_id: Optional[int] = Field(default=None, description="维护人ID")
    maintainer_username: Optional[str] = Field(default=None, description="维护人用户名")
    maintainer_nickname: Optional[str] = Field(default=None, description="维护人昵称")
    maintainer_avatar: Optional[str] = Field(default=None, description="维护人头像URL")
    created_by: int = Field(description="创建人ID")
    creator_username: Optional[str] = Field(default=None, description="创建人用户名")
    visibility: str = Field(description="可见性")
    allowed_group_ids: List[int] = Field(default_factory=list, description="允许访问的分组ID列表")
    allowed_user_ids: List[int] = Field(default_factory=list, description="允许访问的用户ID列表")
    period_type: str = Field(description="开放周期")
    start_time: Optional[datetime] = Field(default=None, description="开放开始时间")
    end_time: Optional[datetime] = Field(default=None, description="开放结束时间")
    time_pattern: Optional[str] = Field(default=None, description="智能时间模式")
    status: str = Field(description="状态")
    click_count: int = Field(description="总点击次数")
    last_accessed_at: Optional[datetime] = Field(default=None, description="最近访问时间")
    reminder_config: dict = Field(default_factory=dict, description="提醒配置")
    related_todo_ids: List[int] = Field(default_factory=list, description="关联待办事项ID")
    related_links_url: List[RelatedLink] = Field(default_factory=list, description="关联链接列表")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class ExternalLinkListItem(BaseModel):
    """Schema for external link list item (simplified for listing)"""
    id: int = Field(description="链接ID")
    title: str = Field(description="链接标题")
    url: str = Field(description="链接地址")
    description: Optional[str] = Field(default=None, description="链接描述")
    icon_url: Optional[str] = Field(default=None, description="图标URL")
    category: str = Field(description="分类名称")
    category_order: int = Field(description="分类排序")
    link_order: int = Field(description="链接排序")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    maintainer_username: Optional[str] = Field(default=None, description="维护人用户名")
    maintainer_nickname: Optional[str] = Field(default=None, description="维护人昵称")
    maintainer_avatar: Optional[str] = Field(default=None, description="维护人头像URL")
    visibility: str = Field(description="可见性")
    period_type: str = Field(description="开放周期")
    start_time: Optional[datetime] = Field(default=None, description="开放开始时间")
    end_time: Optional[datetime] = Field(default=None, description="开放结束时间")
    status: str = Field(description="状态")
    click_count: int = Field(description="总点击次数")
    last_accessed_at: Optional[datetime] = Field(default=None, description="最近访问时间")
    created_at: datetime = Field(description="创建时间")
    related_links_url: List[RelatedLink] = Field(default_factory=list, description="关联链接列表")
    is_favorited: bool = Field(default=False, description="当前用户是否已收藏")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class ExternalLinkBatchUpdateOrder(BaseModel):
    """Schema for batch updating link order"""
    updates: List[dict] = Field(
        description="更新列表，每项包含 id, category_order, link_order"
    )

    @field_validator('updates')
    @classmethod
    def validate_updates(cls, v):
        for item in v:
            if 'id' not in item:
                raise ValueError('Each update item must have an id field')
            if 'category_order' not in item and 'link_order' not in item:
                raise ValueError('Each update item must have at least category_order or link_order field')
        return v


class ExternalLinkClickRequest(BaseModel):
    """Schema for recording a link click"""
    user_agent: Optional[str] = Field(default=None, max_length=500, description="浏览器User-Agent")


class ExternalLinkClickResponse(BaseModel):
    """Schema for link click record response"""
    id: int = Field(description="点击记录ID")
    link_id: int = Field(description="链接ID")
    user_id: int = Field(description="用户ID")
    username: Optional[str] = Field(default=None, description="用户名")
    clicked_at: datetime = Field(description="点击时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class ExternalLinkStatsResponse(BaseModel):
    """Schema for external link statistics"""
    total_links: int = Field(description="总链接数")
    active_links: int = Field(description="活跃链接数")
    total_clicks: int = Field(description="总点击数")
    total_categories: int = Field(description="总分类数")
    top_links: List[ExternalLinkListItem] = Field(default_factory=list, description="热门链接")


class CategoryInfo(BaseModel):
    """Schema for category information"""
    name: str = Field(description="分类名称")
    order: int = Field(description="排序")
    link_count: int = Field(description="链接数量")


class CategoryListResponse(BaseModel):
    """Schema for category list response"""
    categories: List[CategoryInfo] = Field(description="分类列表")


class ExternalLinkByCategoryResponse(BaseModel):
    """Schema for links grouped by category"""
    category: str = Field(description="分类名称")
    category_order: int = Field(description="分类排序")
    links: List[ExternalLinkListItem] = Field(description="链接列表")


class CategoryOrderUpdate(BaseModel):
    """Schema for single category order update"""
    category_name: str = Field(description="分类名称")
    order: int = Field(description="新排序值")


class CategoryBatchUpdateOrder(BaseModel):
    """Schema for batch updating category order"""
    updates: List[CategoryOrderUpdate] = Field(description="更新列表")


# ==================== Favorite Schemas ====================

class FavoriteFolderCreate(BaseModel):
    """Schema for creating a favorite folder"""
    name: str = Field(min_length=1, max_length=100, description="收藏夹名称")
    description: Optional[str] = Field(default=None, max_length=500, description="收藏夹描述")


class FavoriteFolderUpdate(BaseModel):
    """Schema for updating a favorite folder"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="收藏夹名称")
    description: Optional[str] = Field(default=None, max_length=500, description="收藏夹描述")


class FavoriteFolderResponse(BaseModel):
    """Schema for favorite folder response"""
    id: int = Field(description="收藏夹ID")
    name: str = Field(description="收藏夹名称")
    description: Optional[str] = Field(default=None, description="收藏夹描述")
    sort_order: int = Field(description="排序顺序")
    is_default: bool = Field(description="是否为默认收藏夹")
    link_count: int = Field(default=0, description="收藏链接数量")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class FavoriteFolderReorderItem(BaseModel):
    """Schema for single folder reorder item"""
    folder_id: int = Field(description="收藏夹ID")
    sort_order: int = Field(description="新排序值")


class FavoriteFolderReorderRequest(BaseModel):
    """Schema for reordering favorite folders"""
    updates: List[FavoriteFolderReorderItem] = Field(description="排序更新列表")


class FavoriteAddRequest(BaseModel):
    """Schema for adding a link to favorites"""
    folder_id: Optional[int] = Field(default=None, description="收藏夹ID (NULL表示未分类)")


class FavoriteMoveRequest(BaseModel):
    """Schema for moving a favorite to another folder"""
    folder_id: Optional[int] = Field(default=None, description="目标收藏夹ID (NULL表示移到未分类)")


class LinkFavoriteResponse(BaseModel):
    """Schema for link favorite response"""
    id: int = Field(description="收藏记录ID")
    link: ExternalLinkListItem = Field(description="链接信息")
    folder_id: Optional[int] = Field(default=None, description="收藏夹ID")
    folder_name: Optional[str] = Field(default=None, description="收藏夹名称")
    created_at: datetime = Field(description="收藏时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class FavoriteStatusResponse(BaseModel):
    """Schema for checking favorite status"""
    is_favorited: bool = Field(description="是否已收藏")
    folder_id: Optional[int] = Field(default=None, description="所在收藏夹ID")
    folder_name: Optional[str] = Field(default=None, description="所在收藏夹名称")
