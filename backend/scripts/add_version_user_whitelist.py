"""
数据库迁移脚本：为 app_versions 表添加用户名单字段

运行方式：
    python scripts/add_version_user_whitelist.py

新增字段：
    - visibility: 可见性 (ALL/SPECIFIED)
    - allowed_group_ids: 允许更新的分组ID数组
    - allowed_user_ids: 允许更新的用户ID数组
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel import create_engine
from app.core.config import settings


def add_version_user_whitelist():
    """为 app_versions 表添加用户名单相关字段"""
    print("=" * 60)
    print("开始执行版本用户名单迁移...")
    print("=" * 60)

    engine = create_engine(
        settings.DATABASE_URL,
        echo=True,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"init_command": "SET time_zone='+00:00'"}
    )

    with engine.connect() as conn:
        # 1. 检查并添加 visibility 字段
        print("\n[1/3] 检查 visibility 字段...")
        result = conn.execute(text("""
            SELECT COUNT(*) as count FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'app_versions'
            AND COLUMN_NAME = 'visibility'
        """))
        if result.fetchone()[0] == 0:
            print("  添加 visibility 字段...")
            conn.execute(text("""
                ALTER TABLE app_versions
                ADD COLUMN visibility VARCHAR(20) DEFAULT 'ALL' NOT NULL
                COMMENT '可见性：ALL(全员)/SPECIFIED(指定人员)'
            """))
            conn.execute(text("""
                ALTER TABLE app_versions
                ADD INDEX idx_visibility (visibility)
            """))
            print("  ✓ visibility 字段添加成功")
        else:
            print("  - visibility 字段已存在，跳过")

        # 2. 检查并添加 allowed_group_ids 字段
        print("\n[2/3] 检查 allowed_group_ids 字段...")
        result = conn.execute(text("""
            SELECT COUNT(*) as count FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'app_versions'
            AND COLUMN_NAME = 'allowed_group_ids'
        """))
        if result.fetchone()[0] == 0:
            print("  添加 allowed_group_ids 字段...")
            # MySQL JSON 字段不能有默认值，需要先添加字段再更新
            conn.execute(text("""
                ALTER TABLE app_versions
                ADD COLUMN allowed_group_ids JSON
                COMMENT '允许更新的分组ID数组'
            """))
            # 设置初始值为空数组
            conn.execute(text("""
                UPDATE app_versions SET allowed_group_ids = '[]' WHERE allowed_group_ids IS NULL
            """))
            print("  ✓ allowed_group_ids 字段添加成功")
        else:
            print("  - allowed_group_ids 字段已存在，跳过")

        # 3. 检查并添加 allowed_user_ids 字段
        print("\n[3/3] 检查 allowed_user_ids 字段...")
        result = conn.execute(text("""
            SELECT COUNT(*) as count FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'app_versions'
            AND COLUMN_NAME = 'allowed_user_ids'
        """))
        if result.fetchone()[0] == 0:
            print("  添加 allowed_user_ids 字段...")
            # MySQL JSON 字段不能有默认值，需要先添加字段再更新
            conn.execute(text("""
                ALTER TABLE app_versions
                ADD COLUMN allowed_user_ids JSON
                COMMENT '允许更新的用户ID数组'
            """))
            # 设置初始值为空数组
            conn.execute(text("""
                UPDATE app_versions SET allowed_user_ids = '[]' WHERE allowed_user_ids IS NULL
            """))
            print("  ✓ allowed_user_ids 字段添加成功")
        else:
            print("  - allowed_user_ids 字段已存在，跳过")

        # 提交事务
        conn.commit()

    print("\n" + "=" * 60)
    print("✓ 版本用户名单迁移完成！")
    print("=" * 60)


if __name__ == "__main__":
    add_version_user_whitelist()
