"""
Changelog model for multi-language update notes
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Text
import json


class Changelog(SQLModel, table=True):
    """
    Changelog database model with multi-language support

    Attributes:
        id: Primary key
        version_id: Foreign key to app_versions table
        language: Language code (zh-Hans, en, etc.)
        title: Update title
        description: Full description in Markdown format
        features: JSON array of new features
        improvements: JSON array of improvements
        bugfixes: JSON array of bug fixes
        created_at: Record creation timestamp
    """
    __tablename__ = "changelogs"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key
    version_id: int = Field(
        foreign_key="app_versions.id",
        index=True,
        nullable=False,
        description="版本ID"
    )

    # Language
    language: str = Field(
        default="zh-Hans",
        max_length=10,
        index=True,
        nullable=False,
        description="语言代码: zh-Hans/en"
    )

    # Content
    title: str = Field(
        max_length=200,
        nullable=False,
        description="更新标题"
    )
    description: str = Field(
        sa_column=Column(Text, nullable=False),
        description="更新说明 (Markdown格式)"
    )

    # Categorized changes (stored as JSON arrays)
    features: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="新增功能列表 (JSON数组)"
    )
    improvements: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="优化改进列表 (JSON数组)"
    )
    bugfixes: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="问题修复列表 (JSON数组)"
    )

    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间"
    )

    def get_features_list(self) -> List[str]:
        """Parse features JSON string to list"""
        if not self.features:
            return []
        try:
            return json.loads(self.features)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_features_list(self, features: List[str]) -> None:
        """Set features list from Python list"""
        self.features = json.dumps(features, ensure_ascii=False)

    def get_improvements_list(self) -> List[str]:
        """Parse improvements JSON string to list"""
        if not self.improvements:
            return []
        try:
            return json.loads(self.improvements)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_improvements_list(self, improvements: List[str]) -> None:
        """Set improvements list from Python list"""
        self.improvements = json.dumps(improvements, ensure_ascii=False)

    def get_bugfixes_list(self) -> List[str]:
        """Parse bugfixes JSON string to list"""
        if not self.bugfixes:
            return []
        try:
            return json.loads(self.bugfixes)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_bugfixes_list(self, bugfixes: List[str]) -> None:
        """Set bugfixes list from Python list"""
        self.bugfixes = json.dumps(bugfixes, ensure_ascii=False)

    def to_markdown(self) -> str:
        """
        Generate full Markdown changelog from structured data

        Returns:
            Markdown formatted changelog string
        """
        lines = [f"## {self.title}\n"]

        # Add description if present
        if self.description:
            lines.append(f"{self.description}\n")

        # Add features section
        features = self.get_features_list()
        if features:
            lines.append("### ✨ 新增功能\n" if self.language == "zh-Hans" else "### ✨ New Features\n")
            for feature in features:
                lines.append(f"- {feature}")
            lines.append("")

        # Add improvements section
        improvements = self.get_improvements_list()
        if improvements:
            lines.append("### ⚡ 优化改进\n" if self.language == "zh-Hans" else "### ⚡ Improvements\n")
            for improvement in improvements:
                lines.append(f"- {improvement}")
            lines.append("")

        # Add bugfixes section
        bugfixes = self.get_bugfixes_list()
        if bugfixes:
            lines.append("### 🐛 问题修复\n" if self.language == "zh-Hans" else "### 🐛 Bug Fixes\n")
            for bugfix in bugfixes:
                lines.append(f"- {bugfix}")
            lines.append("")

        return "\n".join(lines)

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class ChangelogHelper:
    """Helper class for changelog operations"""

    @staticmethod
    def create_from_dict(data: Dict[str, Any], version_id: int, language: str) -> Changelog:
        """
        Create a Changelog instance from dictionary

        Args:
            data: Dictionary containing changelog data
            version_id: Version ID to associate with
            language: Language code

        Returns:
            Changelog instance
        """
        changelog = Changelog(
            version_id=version_id,
            language=language,
            title=data.get("title", ""),
            description=data.get("description", "")
        )

        if "features" in data:
            changelog.set_features_list(data["features"])
        if "improvements" in data:
            changelog.set_improvements_list(data["improvements"])
        if "bugfixes" in data:
            changelog.set_bugfixes_list(data["bugfixes"])

        return changelog

    @staticmethod
    def to_dict(changelog: Changelog) -> Dict[str, Any]:
        """
        Convert Changelog instance to dictionary

        Args:
            changelog: Changelog instance

        Returns:
            Dictionary representation
        """
        return {
            "id": changelog.id,
            "version_id": changelog.version_id,
            "language": changelog.language,
            "title": changelog.title,
            "description": changelog.description,
            "features": changelog.get_features_list(),
            "improvements": changelog.get_improvements_list(),
            "bugfixes": changelog.get_bugfixes_list(),
            "markdown": changelog.to_markdown(),
            "created_at": changelog.created_at.isoformat() if changelog.created_at else None
        }
