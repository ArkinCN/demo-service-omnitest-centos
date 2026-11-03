"""
Initialize external links management tables in the database
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel, create_engine
from app.core.config import settings
from app.models.user import User
from app.models.external_link import ExternalLink, ExternalLinkClick


def init_external_links_tables():
    """Create external links management tables"""
    print("Initializing external links management tables...")
    print(f"Database URL: {settings.DATABASE_URL}")

    # Create engine
    engine = create_engine(
        settings.DATABASE_URL,
        echo=True,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={
            "init_command": "SET time_zone='+00:00'"  # Force UTC timezone for MySQL
        }
    )

    # Create all tables
    try:
        # Import all models to ensure they're registered with SQLModel metadata
        from app.models.user import User
        from app.models.external_link import ExternalLink, ExternalLinkClick

        SQLModel.metadata.create_all(engine)
        print("\n✓ Successfully created external links management tables:")
        print("  - external_links")
        print("  - external_link_clicks")
        print("\nTables are ready to use!")

        # Print table details
        print("\n📋 Table Structure:")
        print("\n1. external_links table:")
        print("   - id (PRIMARY KEY)")
        print("   - title, url, description, icon_url")
        print("   - category, category_order, link_order")
        print("   - maintainer_id (FOREIGN KEY -> users.id)")
        print("   - created_by (FOREIGN KEY -> users.id)")
        print("   - visibility (ALL/SPECIFIED)")
        print("   - allowed_group_ids (JSON), allowed_user_ids (JSON)")
        print("   - period_type (LONG_TERM/SHORT_TERM)")
        print("   - start_time, end_time, time_pattern")
        print("   - status (ACTIVE/INACTIVE/ARCHIVED)")
        print("   - click_count, last_accessed_at")
        print("   - reminder_config (JSON), related_todo_ids (JSON)")
        print("   - created_at, updated_at")

        print("\n2. external_link_clicks table:")
        print("   - id (PRIMARY KEY)")
        print("   - link_id (FOREIGN KEY -> external_links.id)")
        print("   - user_id (FOREIGN KEY -> users.id)")
        print("   - clicked_at, user_agent")

        print("\n💡 Features:")
        print("   ✓ Category management with custom ordering")
        print("   ✓ Drag-and-drop link reordering")
        print("   ✓ Permission control (visibility settings)")
        print("   ✓ Period management (long-term/short-term)")
        print("   ✓ Smart time patterns (e.g., last week of month)")
        print("   ✓ Click tracking and statistics")
        print("   ✓ User click history")
        print("   ✓ Reserved fields for future features (reminders, todos)")

        print("\n📚 Next Steps:")
        print("   1. Register models in app/models/__init__.py")
        print("   2. Register API routes in app/api/v1/__init__.py")
        print("   3. Create frontend components for link management")
        print("   4. Implement smart time pattern calculations")

    except Exception as e:
        print(f"\n✗ Error creating tables: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    init_external_links_tables()
