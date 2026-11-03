"""
数据库迁移脚本：添加功能模块表和修改反馈表
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_feedback_modules():
    """Add feedback_modules table and module_id column to feedbacks table"""
    print("Starting feedback modules migration...")
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
        # Step 1: Check if feedback_modules table exists
        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'feedback_modules'
        """))
        table_exists = result.fetchone()[0] > 0

        if not table_exists:
            print("Creating feedback_modules table...")

            # Create feedback_modules table
            conn.execute(text("""
                CREATE TABLE feedback_modules (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(50) NOT NULL COMMENT '模块名称',
                    parent_id INT DEFAULT NULL COMMENT '父模块ID，NULL表示一级模块',
                    sort_order INT DEFAULT 0 COMMENT '排序顺序',
                    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                    INDEX idx_parent_id (parent_id),
                    INDEX idx_sort_order (sort_order),
                    INDEX idx_is_active (is_active),
                    CONSTRAINT fk_parent_module FOREIGN KEY (parent_id)
                        REFERENCES feedback_modules(id) ON DELETE CASCADE
                ) COMMENT '反馈功能模块表'
            """))
            print("✓ feedback_modules table created")

            # Insert initial data - parent modules
            print("Inserting initial parent modules...")
            conn.execute(text("""
                INSERT INTO feedback_modules (id, name, parent_id, sort_order) VALUES
                (1, 'AI功能', NULL, 1),
                (2, '应用中心', NULL, 2),
                (3, '系统', NULL, 3)
            """))
            print("✓ Parent modules inserted")

            # Insert initial data - child modules
            print("Inserting initial child modules...")
            conn.execute(text("""
                INSERT INTO feedback_modules (name, parent_id, sort_order) VALUES
                ('AI对话', 1, 1),
                ('代码调试', 1, 2),
                ('代码移植', 1, 3),
                ('注释翻译', 1, 4),
                ('快捷入口', 2, 1),
                ('问题反馈', 3, 1),
                ('账号登录', 3, 2)
            """))
            print("✓ Child modules inserted")
        else:
            print("✓ feedback_modules table already exists")

        # Step 2: Check if module_id column exists in feedbacks table
        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'feedbacks'
            AND COLUMN_NAME = 'module_id'
        """))
        column_exists = result.fetchone()[0] > 0

        if not column_exists:
            print("Adding module_id column to feedbacks table...")

            # Add module_id column
            conn.execute(text("""
                ALTER TABLE feedbacks
                ADD COLUMN module_id INT DEFAULT NULL COMMENT '关联的功能模块ID'
            """))
            print("✓ module_id column added")

            # Add index
            conn.execute(text("""
                ALTER TABLE feedbacks
                ADD INDEX idx_module_id (module_id)
            """))
            print("✓ Index idx_module_id added")

            # Add foreign key constraint
            conn.execute(text("""
                ALTER TABLE feedbacks
                ADD CONSTRAINT fk_feedback_module
                    FOREIGN KEY (module_id) REFERENCES feedback_modules(id) ON DELETE SET NULL
            """))
            print("✓ Foreign key constraint added")
        else:
            print("✓ module_id column already exists in feedbacks table")

        conn.commit()
        print("\n✓ Migration completed successfully!")


if __name__ == "__main__":
    print("=" * 50)
    print("Feedback Modules Migration Script")
    print("=" * 50)
    add_feedback_modules()
    print("\nDone!")
