"""
Add user groups tables to the database

This script adds:
1. user_groups table - for storing group information
2. user_group_members table - for user-group relationships
3. ldap_dn column to users table - for LDAP user DN tracking

Safe to run on existing database with user data.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_user_groups_tables():
    """Create user groups related tables and columns"""
    print("Adding user groups tables...")
    print(f"Database URL: {settings.DATABASE_URL}")

    # Create engine
    engine = create_engine(
        settings.DATABASE_URL,
        echo=True,
        pool_pre_ping=True,
        pool_recycle=3600
    )

    with engine.connect() as conn:
        try:
            # 1. Create user_groups table
            print("\n[1/4] Creating user_groups table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_groups (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    description VARCHAR(500),
                    parent_id INT,
                    group_type VARCHAR(20) NOT NULL DEFAULT 'CUSTOM',
                    ldap_dn VARCHAR(500) UNIQUE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_id) REFERENCES user_groups(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            print("  - user_groups table created")

            # 2. Create indexes for user_groups
            print("\n[2/4] Creating indexes for user_groups...")
            # MySQL doesn't support IF NOT EXISTS for indexes, so we try-catch each one
            try:
                conn.execute(text("CREATE INDEX idx_user_groups_parent_id ON user_groups(parent_id)"))
            except Exception:
                pass  # Index already exists
            try:
                conn.execute(text("CREATE INDEX idx_user_groups_group_type ON user_groups(group_type)"))
            except Exception:
                pass  # Index already exists
            try:
                conn.execute(text("CREATE INDEX idx_user_groups_name ON user_groups(name)"))
            except Exception:
                pass  # Index already exists
            print("  - Indexes created")

            # 3. Create user_group_members table
            print("\n[3/4] Creating user_group_members table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_group_members (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    group_id INT NOT NULL,
                    source VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_user_group (user_id, group_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (group_id) REFERENCES user_groups(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            print("  - user_group_members table created")

            # Create indexes for user_group_members
            try:
                conn.execute(text("CREATE INDEX idx_user_group_members_user_id ON user_group_members(user_id)"))
            except Exception:
                pass  # Index already exists
            try:
                conn.execute(text("CREATE INDEX idx_user_group_members_group_id ON user_group_members(group_id)"))
            except Exception:
                pass  # Index already exists
            print("  - Indexes created")

            # 4. Add ldap_dn column to users table (if not exists)
            print("\n[4/4] Adding ldap_dn column to users table...")
            # Check if column exists first
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'ldap_dn'
            """))
            if result.fetchone() is None:
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN ldap_dn VARCHAR(500)
                """))
                print("  - ldap_dn column added to users table")
            else:
                print("  - ldap_dn column already exists, skipping")

            # Commit all changes
            conn.commit()

            print("\n" + "=" * 50)
            print("SUCCESS! User groups tables created:")
            print("  - user_groups (with indexes)")
            print("  - user_group_members (with indexes)")
            print("  - users.ldap_dn column")
            print("=" * 50)

        except Exception as e:
            conn.rollback()
            print(f"\nERROR: {str(e)}")
            raise


def rollback_user_groups_tables():
    """Remove user groups related tables and columns (for rollback)"""
    print("Rolling back user groups tables...")
    print(f"Database URL: {settings.DATABASE_URL}")

    engine = create_engine(
        settings.DATABASE_URL,
        echo=True,
        pool_pre_ping=True,
        pool_recycle=3600
    )

    with engine.connect() as conn:
        try:
            # Drop in reverse order due to foreign key constraints
            print("\n[1/3] Dropping user_group_members table...")
            conn.execute(text("DROP TABLE IF EXISTS user_group_members CASCADE"))
            print("  - Done")

            print("\n[2/3] Dropping user_groups table...")
            conn.execute(text("DROP TABLE IF EXISTS user_groups CASCADE"))
            print("  - Done")

            print("\n[3/3] Removing ldap_dn column from users table...")
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'ldap_dn'
            """))
            if result.fetchone() is not None:
                conn.execute(text("ALTER TABLE users DROP COLUMN ldap_dn"))
                print("  - ldap_dn column removed")
            else:
                print("  - ldap_dn column doesn't exist, skipping")

            conn.commit()
            print("\nRollback completed successfully!")

        except Exception as e:
            conn.rollback()
            print(f"\nERROR during rollback: {str(e)}")
            raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="User groups database migration")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback the migration (remove tables)"
    )
    args = parser.parse_args()

    if args.rollback:
        rollback_user_groups_tables()
    else:
        add_user_groups_tables()
