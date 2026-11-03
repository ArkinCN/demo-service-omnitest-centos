"""
Initialize feedback management tables in the database
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel, create_engine
from app.core.config import settings
from app.models.user import User
from app.models.feedback import Feedback, FeedbackReply


def init_feedback_tables():
    """Create feedback management tables"""
    print("Initializing feedback management tables...")
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
        from app.models.feedback import Feedback, FeedbackReply

        SQLModel.metadata.create_all(engine)
        print("\n✓ Successfully created feedback management tables:")
        print("  - feedbacks")
        print("  - feedback_replies")
        print("\nTables are ready to use!")

        # Print table details
        print("\n📋 Table Structure:")
        print("\n1. feedbacks table:")
        print("   - id (PRIMARY KEY)")
        print("   - user_id (FOREIGN KEY -> users.id)")
        print("   - assigned_to (FOREIGN KEY -> users.id, nullable)")
        print("   - category (VARCHAR)")
        print("   - description (TEXT)")
        print("   - contact_info (VARCHAR, nullable)")
        print("   - attachments (JSON)")
        print("   - status (VARCHAR, default='PENDING')")
        print("   - priority (VARCHAR, default='MEDIUM')")
        print("   - created_at, updated_at, resolved_at")

        print("\n2. feedback_replies table:")
        print("   - id (PRIMARY KEY)")
        print("   - feedback_id (FOREIGN KEY -> feedbacks.id)")
        print("   - user_id (FOREIGN KEY -> users.id)")
        print("   - content (TEXT)")
        print("   - is_internal (BOOLEAN, default=False)")
        print("   - created_at")

    except Exception as e:
        print(f"\n✗ Error creating tables: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    init_feedback_tables()
