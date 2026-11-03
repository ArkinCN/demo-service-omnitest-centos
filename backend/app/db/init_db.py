"""
Database initialization utilities
"""
from sqlmodel import Session, select
from app.db.session import engine
from app.models.user import User
from app.core.logger import logger


def check_first_run() -> bool:
    """
    Check if this is the first run (no users exist)

    Returns:
        True if no users exist, False otherwise
    """
    with Session(engine) as session:
        statement = select(User)
        users = session.exec(statement).all()
        return len(users) == 0


def create_first_admin(
    username: str,
    email: str,
    password: str,
    nickname: str = "Administrator"
) -> User:
    """
    Create the first admin user

    Args:
        username: Admin username
        email: Admin email
        password: Admin password
        nickname: Admin display name

    Returns:
        Created admin user

    Raises:
        ValueError: If admin user already exists
    """
    with Session(engine) as session:
        # Check if user exists
        statement = select(User).where(User.username == username)
        existing_user = session.exec(statement).first()

        if existing_user:
            raise ValueError(f"User '{username}' already exists")

        # Create admin user
        admin = User(
            username=username,
            email=email,
            nickname=nickname,
            auth_type="EMAIL",
            role="admin",
            is_active=True
        )
        admin.set_password(password)

        session.add(admin)
        session.commit()
        session.refresh(admin)

        logger.info(f"Admin user created: {username}")
        return admin


def get_user_count() -> int:
    """
    Get total number of users

    Returns:
        Total user count
    """
    with Session(engine) as session:
        statement = select(User)
        users = session.exec(statement).all()
        return len(users)
