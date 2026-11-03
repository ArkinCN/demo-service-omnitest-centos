"""
Add last_active_at field to users table

用于追踪用户的最后活跃时间（通过 WebSocket 心跳更新）
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_last_active_at_column():
    """Add last_active_at column to users table"""
    print("Adding last_active_at column to users table...")
    print(f"Database URL: {settings.DATABASE_URL}")

    # Create engine
    engine = create_engine(
        settings.DATABASE_URL,
        echo=True,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={
            "init_command": "SET time_zone='+00:00'"
        }
    )

    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'users'
            AND COLUMN_NAME = 'last_active_at'
        """))

        exists = result.fetchone()[0] > 0

        if exists:
            print("✓ Column 'last_active_at' already exists in users table")
            return

        # Add last_active_at column
        print("  - Adding last_active_at column...")
        conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN last_active_at DATETIME NULL
            COMMENT 'Last active timestamp from WebSocket heartbeat'
            AFTER last_login_at
        """))

        conn.commit()
        print("✓ Successfully added 'last_active_at' column to users table")


if __name__ == "__main__":
    print("=" * 50)
    print("Adding last_active_at column to users table")
    print("=" * 50)
    add_last_active_at_column()
    print("Done!")
