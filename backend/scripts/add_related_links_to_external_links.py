"""
Add related_links_url field to external_links table
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_related_links_column():
    """Add related_links_url column to external_links table"""
    print("Adding related_links_url column to external_links table...")
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
            AND COLUMN_NAME = 'related_links_url'
        """))

        exists = result.fetchone()[0] > 0

        if exists:
            print("✓ Column 'related_links_url' already exists in external_links table")
            return

        # Add related_links_url column (JSON type, allow NULL first)
        print("  - Adding related_links_url column...")
        conn.execute(text("""
            ALTER TABLE external_links
            ADD COLUMN related_links_url JSON NULL COMMENT 'Related links with name and url'
        """))

        # Update existing rows to have empty array
        print("  - Setting default value for existing rows...")
        conn.execute(text("""
            UPDATE external_links
            SET related_links_url = JSON_ARRAY()
            WHERE related_links_url IS NULL
        """))

        conn.commit()
        print("✓ Successfully added 'related_links_url' column to external_links table")
        print("  All existing links now have empty related_links_url array []")


if __name__ == "__main__":
    print("Adding related_links_url column to external_links table...")
    add_related_links_column()
    print("Done!")
