"""
User Group schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field


class UserGroupBase(BaseModel):
    """Base user group schema with common fields"""
    name: str = Field(min_length=1, max_length=100, description="分组名称")
    description: Optional[str] = Field(default=None, max_length=500, description="分组描述")


class UserGroupCreate(UserGroupBase):
    """Schema for creating a new user group (CUSTOM type only)"""
    parent_id: Optional[int] = Field(default=None, description="父分组ID")


class UserGroupUpdate(BaseModel):
    """Schema for updating a user group (CUSTOM type only)"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="分组名称")
    description: Optional[str] = Field(default=None, max_length=500, description="分组描述")
    parent_id: Optional[int] = Field(default=None, description="父分组ID")
    is_active: Optional[bool] = Field(default=None, description="启用状态")


class UserGroupResponse(BaseModel):
    """Schema for user group response"""
    id: int = Field(description="分组ID")
    name: str = Field(description="分组名称")
    description: Optional[str] = Field(default=None, description="分组描述")
    parent_id: Optional[int] = Field(default=None, description="父分组ID")
    group_type: str = Field(description="分组类型：CUSTOM/LDAP")
    ldap_dn: Optional[str] = Field(default=None, description="LDAP DN")
    is_active: bool = Field(description="启用状态")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    user_count: Optional[int] = Field(default=None, description="成员数量")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class UserGroupTreeNode(UserGroupResponse):
    """Schema for user group tree node with children"""
    children: List["UserGroupTreeNode"] = Field(default_factory=list, description="子分组")


class UserGroupListItem(BaseModel):
    """Schema for user group list item (simplified)"""
    id: int = Field(description="分组ID")
    name: str = Field(description="分组名称")
    description: Optional[str] = Field(default=None, description="分组描述")
    parent_id: Optional[int] = Field(default=None, description="父分组ID")
    group_type: str = Field(description="分组类型")
    ldap_dn: Optional[str] = Field(default=None, description="LDAP DN")
    is_active: bool = Field(description="启用状态")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    user_count: Optional[int] = Field(default=None, description="成员数量")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class UserGroupMemberAdd(BaseModel):
    """Schema for adding users to a group"""
    user_ids: List[int] = Field(min_length=1, description="用户ID列表")


class UserGroupMemberRemove(BaseModel):
    """Schema for removing users from a group"""
    user_ids: List[int] = Field(min_length=1, description="用户ID列表")


class UserGroupMemberResponse(BaseModel):
    """Schema for user group member response"""
    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: Optional[str] = Field(default=None, description="用户昵称")
    email: str = Field(description="邮箱地址")
    role: str = Field(description="角色")
    is_active: bool = Field(description="启用状态")
    auth_type: str = Field(description="认证方式")
    avatar_url: Optional[str] = Field(default=None, description="头像URL")
    source: str = Field(description="成员来源：MANUAL/LDAP")
    joined_at: datetime = Field(description="加入时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class LdapSyncRequest(BaseModel):
    """Schema for manual LDAP sync request"""
    force: bool = Field(default=False, description="强制同步（忽略正在进行的同步）")


class LdapSyncStatusResponse(BaseModel):
    """Schema for LDAP sync status response"""
    is_running: bool = Field(description="是否正在同步")
    last_sync_at: Optional[datetime] = Field(default=None, description="上次同步时间")
    last_sync_status: Optional[str] = Field(default=None, description="上次同步状态")
    last_sync_message: Optional[str] = Field(default=None, description="上次同步消息")
    users_created: Optional[int] = Field(default=None, description="上次同步创建用户数")
    users_updated: Optional[int] = Field(default=None, description="上次同步更新用户数")
    users_disabled: Optional[int] = Field(default=None, description="上次同步禁用用户数")
    groups_synced: Optional[int] = Field(default=None, description="上次同步分组数")
    next_sync_at: Optional[datetime] = Field(default=None, description="下次同步时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class LdapSyncResult(BaseModel):
    """Schema for LDAP sync result"""
    status: str = Field(description="同步状态：SUCCESS/FAILED")
    message: str = Field(description="同步消息")
    users_created: int = Field(default=0, description="创建用户数")
    users_updated: int = Field(default=0, description="更新用户数")
    users_disabled: int = Field(default=0, description="禁用用户数")
    groups_synced: int = Field(default=0, description="同步分组数")
    started_at: datetime = Field(description="开始时间")
    completed_at: datetime = Field(description="完成时间")
    errors: List[str] = Field(default_factory=list, description="错误列表")

    class Config:
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


# Enable forward reference for self-referential model
UserGroupTreeNode.model_rebuild()
