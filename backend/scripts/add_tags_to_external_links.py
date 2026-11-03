"""
Add tags field to external_links table
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_tags_column():
    """Add tags column to external_links table"""
    print("Adding tags column to external_links table...")
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
            AND TABLE_NAME = 'external_links'
            AND COLUMN_NAME = 'tags'
        """))

        exists = result.fetchone()[0] > 0

        if exists:
            print("✓ Column 'tags' already exists in external_links table")
            return

        # Add tags column (JSON type, allow NULL first)
        print("  - Adding tags column...")
        conn.execute(text("""
            ALTER TABLE external_links
            ADD COLUMN tags JSON NULL COMMENT 'Link tags'
        """))

        # Update existing rows to have empty array
        print("  - Setting default value for existing rows...")
        conn.execute(text("""
            UPDATE external_links
            SET tags = JSON_ARRAY()
            WHERE tags IS NULL
        """))

        conn.commit()
        print("✓ Successfully added 'tags' column to external_links table")
        print("  All existing links now have empty tags array []")


if __name__ == "__main__":
    print("Adding tags column to external_links table...")
    add_tags_column()
    print("Done!")
