"""
Initialize code review management tables in the database
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel, create_engine
from app.core.config import settings
from app.models.user import User
from app.models.code_review import (
    CodeReview,
    CodeReviewResult,
    CodeReviewShare,
    CodeReviewComment,
    CodeReviewStats
)


def init_code_review_tables():
    """Create code review management tables"""
    print("Initializing code review management tables...")
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
        from app.models.code_review import (
            CodeReview,
            CodeReviewResult,
            CodeReviewShare,
            CodeReviewComment,
            CodeReviewStats
        )

        SQLModel.metadata.create_all(engine)
        print("\n✓ Successfully created code review management tables:")
        print("  - code_reviews")
        print("  - code_review_results")
        print("  - code_review_shares")
        print("  - code_review_comments")
        print("  - code_review_stats")
        print("\nTables are ready to use!")

        # Print table details
        print("\n📋 Table Structure:")
        print("\n1. code_reviews table:")
        print("   - id (PRIMARY KEY)")
        print("   - user_id (FOREIGN KEY -> users.id)")
        print("   - reviewer_name, reviewer_avatar")
        print("   - title, group_id, project_id, branch")
        print("   - check_type, check_mode, file_name")
        print("   - ai_model, ai_prompt, ref_issue")
        print("   - total_projects, normal_count, issue_count, error_count, not_found_count")
        print("   - status (PENDING/PROCESSING/COMPLETED/FAILED)")
        print("   - is_shared, share_scope (PRIVATE/TEAM/PUBLIC)")
        print("   - view_count, tags (JSON), description")
        print("   - created_at, updated_at, completed_at, shared_at")

        print("\n2. code_review_results table:")
        print("   - id (PRIMARY KEY)")
        print("   - review_id (FOREIGN KEY -> code_reviews.id)")
        print("   - group_name, project_name, project_id, branch")
        print("   - file_links (JSON), file_count")
        print("   - status (NORMAL/ISSUE/ERROR/NOT_FOUND)")
        print("   - issue_description (TEXT)")
        print("   - severity (LOW/MEDIUM/HIGH/CRITICAL)")
        print("   - ai_analysis (JSON)")
        print("   - created_at")

        print("\n3. code_review_shares table:")
        print("   - id (PRIMARY KEY)")
        print("   - review_id (FOREIGN KEY -> code_reviews.id)")
        print("   - shared_by, viewed_by (FOREIGN KEY -> users.id)")
        print("   - share_link (UNIQUE)")
        print("   - share_message")
        print("   - allowed_users (JSON)")
        print("   - expires_at")
        print("   - created_at, last_viewed_at")

        print("\n4. code_review_comments table:")
        print("   - id (PRIMARY KEY)")
        print("   - review_id (FOREIGN KEY -> code_reviews.id)")
        print("   - result_id (FOREIGN KEY -> code_review_results.id, nullable)")
        print("   - user_id (FOREIGN KEY -> users.id)")
        print("   - content (TEXT)")
        print("   - comment_type (COMMENT/QUESTION/SUGGESTION)")
        print("   - parent_id (FOREIGN KEY -> code_review_comments.id, nullable)")
        print("   - likes_count")
        print("   - created_at, updated_at")

        print("\n5. code_review_stats table:")
        print("   - id (PRIMARY KEY)")
        print("   - user_id (FOREIGN KEY -> users.id, UNIQUE)")
        print("   - total_reviews, total_projects, total_issues_found")
        print("   - total_shared, total_views_received")
        print("   - last_review_at, updated_at")

    except Exception as e:
        print(f"\n✗ Error creating tables: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    init_code_review_tables()
