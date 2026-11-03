"""临时脚本：造一个普通测试用户，用于阶段 2 验收第 4 项「另一无权限用户读不到」。

运行方式（在 backend 目录下）：
    python scripts/create_test_user.py

说明：
- 仅写库造一个 role=user、email_verified=True 的账号，不做任何鉴权开关；
- 幂等：已存在则跳过；
- 用完可删。
"""
import sys
from pathlib import Path

# 让脚本能 import backend 根目录下的 app 包（脚本位于 backend/scripts/）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.db.session import engine
from app.models.user import User

USERNAME = "testuser"
EMAIL = "testuser@example.internal"
PASSWORD = "test123456"

with Session(engine) as session:
    existing = session.exec(select(User).where(User.username == USERNAME)).first()
    if existing:
        print(f"用户 {USERNAME} 已存在，id={existing.id}，跳过")
    else:
        u = User(
            username=USERNAME,
            nickname="测试用户",
            email=EMAIL,
            auth_type="EMAIL",
            role="user",
            is_active=True,
            email_verified=True,
        )
        u.set_password(PASSWORD)
        session.add(u)
        session.commit()
        session.refresh(u)
        print(f"已创建用户 {USERNAME}（id={u.id}，role=user，密码={PASSWORD}）")
