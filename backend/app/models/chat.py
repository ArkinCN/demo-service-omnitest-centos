"""
Chat model using SQLModel
Support message tree structure with branches (based on open-webui design)
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from sqlmodel import Field, SQLModel, Column, JSON
import json


class Chat(SQLModel, table=True):
    """
    Chat database model with message tree structure

    Attributes:
        id: Primary key (UUID string)
        user_id: Foreign key to users table
        title: Chat title
        history: JSON field storing message tree structure
        model: AI model name (e.g., "gpt-4")
        params: Model parameters (temperature, max_tokens, etc.)
        created_at: Chat creation timestamp
        updated_at: Last update timestamp
        pinned: Whether chat is pinned to top
        archived: Whether chat is archived
        message_count: Total number of messages (for performance)

    History Structure:
        {
            "messages": {
                "msg-uuid-1": {
                    "id": "msg-uuid-1",
                    "role": "user",
                    "content": "Hello",
                    "timestamp": 1699123456789,
                    "parentId": null,
                    "childrenIds": ["msg-uuid-2", "msg-uuid-3"]
                },
                "msg-uuid-2": {
                    "id": "msg-uuid-2",
                    "role": "assistant",
                    "content": "Hi there!",
                    "timestamp": 1699123457000,
                    "parentId": "msg-uuid-1",
                    "childrenIds": [],
                    "done": true
                }
            },
            "currentId": "msg-uuid-2"
        }
    """
    __tablename__ = "chats"

    # Primary key
    id: str = Field(primary_key=True, description="聊天ID (UUID)")

    # Foreign key
    user_id: int = Field(foreign_key="users.id", index=True, description="用户ID")

    # Basic information
    title: str = Field(max_length=500, description="对话标题")

    # Core data - Message tree structure
    history: str = Field(
        sa_column=Column(JSON),
        description="消息树结构 (JSON格式)"
    )

    # AI configuration
    model: str = Field(default="gpt-4", max_length=100, description="AI模型名称")
    params: str = Field(
        default="{}",
        sa_column=Column(JSON),
        description="模型参数"
    )

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")

    # Status flags
    pinned: bool = Field(default=False, index=True, description="是否置顶")
    archived: bool = Field(default=False, index=True, description="是否归档")

    # Statistics (denormalized for performance)
    message_count: int = Field(default=0, description="消息总数")

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class ChatHelper:
    """Helper class for chat operations"""

    @staticmethod
    def create_empty_history() -> Dict[str, Any]:
        """Create an empty history structure"""
        return {
            "messages": {},
            "currentId": None
        }

    @staticmethod
    def parse_history(history_str: str) -> Dict[str, Any]:
        """Parse history from JSON string"""
        try:
            return json.loads(history_str)
        except (json.JSONDecodeError, TypeError):
            return ChatHelper.create_empty_history()

    @staticmethod
    def add_message_to_history(
        history: Dict[str, Any],
        message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add a message to the history tree

        Args:
            history: History structure
            message: Message dict with id, role, content, timestamp, parentId

        Returns:
            Updated history structure
        """
        msg_id = message["id"]
        parent_id = message.get("parentId")

        # Initialize childrenIds if not present
        if "childrenIds" not in message:
            message["childrenIds"] = []

        # Add message to tree
        history["messages"][msg_id] = message

        # Update parent's childrenIds
        if parent_id and parent_id in history["messages"]:
            parent_children = history["messages"][parent_id].get("childrenIds", [])
            if msg_id not in parent_children:
                parent_children.append(msg_id)
                history["messages"][parent_id]["childrenIds"] = parent_children

        # Update currentId to the new message
        history["currentId"] = msg_id

        return history

    @staticmethod
    def get_message_chain(
        history: Dict[str, Any],
        target_id: str
    ) -> List[Dict[str, Any]]:
        """
        Build message chain from root to target message

        Args:
            history: History structure
            target_id: Target message ID

        Returns:
            List of messages from root to target
        """
        chain = []
        current_id = target_id

        while current_id:
            message = history["messages"].get(current_id)
            if not message:
                break

            chain.insert(0, message)
            current_id = message.get("parentId")

        return chain

    @staticmethod
    def count_messages(history: Dict[str, Any]) -> int:
        """Count total number of messages in history"""
        return len(history.get("messages", {}))

    @staticmethod
    def get_branch_count(history: Dict[str, Any], message_id: str) -> int:
        """Get the number of branches (children) for a message"""
        message = history.get("messages", {}).get(message_id)
        if not message:
            return 0
        return len(message.get("childrenIds", []))

    @staticmethod
    def switch_branch(history: Dict[str, Any], target_id: str) -> Dict[str, Any]:
        """
        Switch to a different branch by updating currentId

        Args:
            history: History structure
            target_id: Target message ID to switch to

        Returns:
            Updated history structure
        """
        if target_id in history.get("messages", {}):
            history["currentId"] = target_id
        return history

    @staticmethod
    def to_json_string(history: Dict[str, Any]) -> str:
        """Convert history dict to JSON string"""
        return json.dumps(history, ensure_ascii=False)
