"""
Initialize AI request tracking table in the database
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel, create_engine
from app.core.config import settings
from app.models.user import User
from app.models.ai_request import AIRequest


def init_ai_request_table():
    """Create AI request tracking table"""
    print("Initializing AI request tracking table...")
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
        from app.models.ai_request import AIRequest

        SQLModel.metadata.create_all(engine)
        print("\n✓ Successfully created AI request tracking table:")
        print("  - ai_requests")
        print("\nTable is ready to use!")

        # Print table details
        print("\n📋 Table Structure:")
        print("\nai_requests table:")
        print("   - id (PRIMARY KEY)")
        print("   - user_id (FOREIGN KEY -> users.id)")
        print("   - module_name (ai_chat, ai_chat_title, code_review, translator, etc.)")
        print("   - model (gpt-5.2, deepseek-v3-2-251201, etc.)")
        print("   - prompt_tokens, completion_tokens, total_tokens")
        print("   - cost_cents (unit: 0.0001 CNY, 10000 = ¥1.00)")
        print("   - success, error_message (TEXT)")
        print("   - ip_address")
        print("   - created_at")

    except Exception as e:
        print(f"\n✗ Error creating table: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    init_ai_request_table()
