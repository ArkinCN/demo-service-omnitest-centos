"""
Add user_favorite_folders and user_link_favorites tables for link favorites feature
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_favorites_tables():
    """Add favorites-related tables"""
    print("Creating favorites tables...")
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
        # ==================== 1. Create user_favorite_folders table ====================
        print("\n[1/4] Creating user_favorite_folders table...")

        # Check if table already exists
        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'user_favorite_folders'
        """))

        if result.fetchone()[0] > 0:
            print("  ✓ Table 'user_favorite_folders' already exists")
        else:
            conn.execute(text("""
                CREATE TABLE user_favorite_folders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    description VARCHAR(500),
                    sort_order INT DEFAULT 0,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_user_folder_name (user_id, name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                COMMENT='用户收藏夹'
            """))
            print("  ✓ Created table 'user_favorite_folders'")

        # ==================== 2. Create index for user_favorite_folders ====================
        print("\n[2/4] Creating indexes for user_favorite_folders...")

        try:
            conn.execute(text("""
                CREATE INDEX idx_folder_user ON user_favorite_folders(user_id)
            """))
            print("  ✓ Created index 'idx_folder_user'")
        except Exception as e:
            if "Duplicate key name" in str(e):
                print("  ✓ Index 'idx_folder_user' already exists")
            else:
                print(f"  ! Warning: {e}")

        # ==================== 3. Create user_link_favorites table ====================
        print("\n[3/4] Creating user_link_favorites table...")

        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'user_link_favorites'
        """))

        if result.fetchone()[0] > 0:
            print("  ✓ Table 'user_link_favorites' already exists")
        else:
            conn.execute(text("""
                CREATE TABLE user_link_favorites (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    link_id INT NOT NULL,
                    folder_id INT DEFAULT NULL COMMENT 'NULL表示默认收藏(未分类)',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (link_id) REFERENCES external_links(id) ON DELETE CASCADE,
                    FOREIGN KEY (folder_id) REFERENCES user_favorite_folders(id) ON DELETE SET NULL,
                    UNIQUE KEY unique_user_link (user_id, link_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                COMMENT='用户收藏的外链'
            """))
            print("  ✓ Created table 'user_link_favorites'")

        # ==================== 4. Create indexes for user_link_favorites ====================
        print("\n[4/4] Creating indexes for user_link_favorites...")

        indexes = [
            ("idx_favorites_user", "user_link_favorites(user_id)"),
            ("idx_favorites_link", "user_link_favorites(link_id)"),
            ("idx_favorites_folder", "user_link_favorites(folder_id)"),
        ]

        for idx_name, idx_def in indexes:
            try:
                conn.execute(text(f"CREATE INDEX {idx_name} ON {idx_def}"))
                print(f"  ✓ Created index '{idx_name}'")
            except Exception as e:
                if "Duplicate key name" in str(e):
                    print(f"  ✓ Index '{idx_name}' already exists")
                else:
                    print(f"  ! Warning creating {idx_name}: {e}")

        conn.commit()
        print("\n" + "="*50)
        print("✓ Successfully created favorites tables!")
        print("  - user_favorite_folders: 用户收藏夹表")
        print("  - user_link_favorites: 用户收藏的外链关联表")
        print("="*50)


def rollback_favorites_tables():
    """Rollback: remove favorites tables"""
    print("Rolling back favorites tables...")
    print(f"Database URL: {settings.DATABASE_URL}")

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
        # Drop tables in reverse order (due to foreign key constraints)
        print("Dropping user_link_favorites table...")
        conn.execute(text("DROP TABLE IF EXISTS user_link_favorites"))

        print("Dropping user_favorite_folders table...")
        conn.execute(text("DROP TABLE IF EXISTS user_favorite_folders"))

        conn.commit()
        print("✓ Successfully rolled back favorites tables")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Add or rollback favorites tables")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()

    if args.rollback:
        rollback_favorites_tables()
    else:
        add_favorites_tables()

    print("\nDone!")
