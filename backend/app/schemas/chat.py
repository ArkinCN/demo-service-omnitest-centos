"""
Chat schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field, field_serializer


class MessageSchema(BaseModel):
    """
    Message schema for chat history

    Represents a single message in the conversation tree
    """
    id: str = Field(description="消息ID (UUID)")
    role: str = Field(description="角色 (user|assistant|system)")
    content: str = Field(description="消息内容")
    timestamp: int = Field(description="时间戳 (毫秒)")
    parentId: Optional[str] = Field(default=None, description="父消息ID")
    childrenIds: List[str] = Field(default_factory=list, description="子消息ID列表")
    done: Optional[bool] = Field(default=None, description="是否完成 (用于assistant消息)")
    error: Optional[Dict[str, Any]] = Field(default=None, description="错误信息")
    responseChatItemId: Optional[str] = Field(default=None, description="FastGPT响应ID (用于反馈)")
    feedback: Optional[str] = Field(default=None, description="用户反馈 (good|bad|null)")
    reasoningContent: Optional[str] = Field(default=None, description="AI思考过程内容")


class HistorySchema(BaseModel):
    """
    History schema containing message tree structure

    Based on open-webui design:
    - messages: Dict mapping message IDs to Message objects
    - currentId: ID of the current message in the active branch
    """
    messages: Dict[str, MessageSchema] = Field(
        default_factory=dict,
        description="消息树（messageId -> Message）"
    )
    currentId: Optional[str] = Field(default=None, description="当前分支的消息ID")


class ChatCreate(BaseModel):
    """Schema for creating a new chat"""
    id: Optional[str] = Field(default=None, max_length=50, description="对话ID（可选，不提供则自动生成）")
    title: str = Field(default="新对话", max_length=500, description="对话标题")
    model: str = Field(default="gpt-4", max_length=100, description="AI模型名称")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="模型参数")


class ChatUpdate(BaseModel):
    """Schema for updating an existing chat"""
    title: Optional[str] = Field(default=None, max_length=500, description="对话标题")
    history: Optional[Dict[str, Any]] = Field(default=None, description="消息树结构")
    model: Optional[str] = Field(default=None, max_length=100, description="AI模型名称")
    params: Optional[Dict[str, Any]] = Field(default=None, description="模型参数")


class ChatResponse(BaseModel):
    """Schema for chat response (full details)"""
    id: str = Field(description="对话ID (UUID)")
    user_id: int = Field(description="用户ID")
    title: str = Field(description="对话标题")
    history: Dict[str, Any] = Field(description="消息树结构")
    model: str = Field(description="AI模型名称")
    params: Dict[str, Any] = Field(description="模型参数")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    pinned: bool = Field(description="是否置顶")
    archived: bool = Field(description="是否归档")
    message_count: int = Field(description="消息总数")

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value: datetime) -> str:
        """确保时间序列化时带有UTC时区信息"""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()


class ChatListItem(BaseModel):
    """Schema for chat list item (lightweight)"""
    id: str = Field(description="对话ID")
    title: str = Field(description="对话标题")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    pinned: bool = Field(description="是否置顶")
    message_count: int = Field(description="消息总数")

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value: datetime) -> str:
        """确保时间序列化时带有UTC时区信息"""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()


class ChatListResponse(BaseModel):
    """Schema for chat list response with pagination"""
    items: List[ChatListItem] = Field(description="对话列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")

    class Config:
        from_attributes = True


class ChatSearchQuery(BaseModel):
    """Schema for chat search query"""
    keyword: Optional[str] = Field(default=None, max_length=200, description="搜索关键词")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=50, ge=1, le=100, description="每页数量")


class ChatPinToggleResponse(BaseModel):
    """Schema for pin toggle response"""
    pinned: bool = Field(description="当前置顶状态")


class ChatArchiveToggleResponse(BaseModel):
    """Schema for archive toggle response"""
    archived: bool = Field(description="当前归档状态")
