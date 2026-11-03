"""
Create database tables

This script initializes the database and creates all tables
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import init_db
from app.db.init_db import get_user_count
from app.core.logger import logger


def main():
    """Create database tables"""
    try:
        logger.info("Creating database tables...")
        init_db()
        logger.info("Database tables created successfully!")

        # Show current user count
        count = get_user_count()
        logger.info(f"Current user count: {count}")

        if count == 0:
            logger.info("No users found. Run 'create_admin.py' to create an admin user.")

    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
