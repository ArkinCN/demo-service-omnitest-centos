"""
Initialize update management tables in the database
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel, create_engine
from app.core.config import settings
from app.models.user import User
from app.models.chat import Chat
from app.models.app_version import AppVersion
from app.models.changelog import Changelog
from app.models.update_stats import UpdateStats


def init_update_tables():
    """Create update management tables"""
    print("Initializing update management tables...")
    print(f"Database URL: {settings.DATABASE_URL}")

    # Create engine
    engine = create_engine(
        settings.DATABASE_URL,
        echo=True,
        pool_pre_ping=True,
        pool_recycle=3600
    )

    # Create all tables
    try:
        SQLModel.metadata.create_all(engine)
        print("\n✓ Successfully created update management tables:")
        print("  - app_versions")
        print("  - changelogs")
        print("  - update_stats")
        print("\nTables are ready to use!")

    except Exception as e:
        print(f"\n✗ Error creating tables: {str(e)}")
        raise


if __name__ == "__main__":
    init_update_tables()
