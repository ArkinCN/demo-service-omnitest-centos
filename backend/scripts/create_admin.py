"""
Create admin user

Interactive script to create the first admin user
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.init_db import create_first_admin
from app.core.logger import logger


def main():
    """Create admin user interactively"""
    print("=" * 50)
    print("Create Admin User")
    print("=" * 50)

    # Get user input
    username = input("Enter admin username: ").strip()
    if not username:
        print("Error: Username cannot be empty")
        sys.exit(1)

    email = input("Enter admin email: ").strip()
    if not email:
        print("Error: Email cannot be empty")
        sys.exit(1)

    nickname = input("Enter admin nickname (default: Administrator): ").strip()
    if not nickname:
        nickname = "Administrator"

    password = input("Enter admin password (min 6 characters): ").strip()
    if not password or len(password) < 6:
        print("Error: Password must be at least 6 characters")
        sys.exit(1)

    password_confirm = input("Confirm password: ").strip()
    if password != password_confirm:
        print("Error: Passwords do not match")
        sys.exit(1)

    # Create admin user
    try:
        admin = create_first_admin(
            username=username,
            email=email,
            password=password,
            nickname=nickname
        )

        print("\n" + "=" * 50)
        print("Admin user created successfully!")
        print("=" * 50)
        print(f"ID: {admin.id}")
        print(f"Username: {admin.username}")
        print(f"Email: {admin.email}")
        print(f"Nickname: {admin.nickname}")
        print(f"Role: {admin.role}")
        print("=" * 50)

    except ValueError as e:
        print(f"\nError: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error creating admin user: {str(e)}")
        print(f"\nError creating admin user: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
