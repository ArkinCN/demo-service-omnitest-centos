"""
Authentication service
"""
from typing import Dict, Optional
from sqlmodel import Session

from app.models.user import User
from app.schemas.user import UserCreate
from app.schemas.auth import TokenResponse
from app.services.ldap_service import LDAPService
from app.services.user_service import UserService
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.core.exceptions import UnauthorizedException, BadRequestException, EmailNotVerifiedException
from app.core.logger import logger


class AuthService:
    """Authentication service"""

    @staticmethod
    def login(session: Session, username: str, password: str, auth_type: str = None) -> Dict:
        """
        User login with automatic authentication type detection

        Args:
            session: Database session
            username: Username
            password: Password
            auth_type: Optional auth type (LDAP or EMAIL)

        Returns:
            Dict containing user info and tokens

        Raises:
            UnauthorizedException: If authentication fails
            BadRequestException: If user is disabled
        """
        # 无密码模式：任意用户名/密码都换回本地管理员的有效 token，
        # 前端登录页与自动登录都无需分支处理。
        if settings.AUTH_DISABLED:
            return AuthService._login_without_auth(session)

        # If auth_type explicitly LDAP, go directly to LDAP
        if auth_type == "LDAP":
            return AuthService._login_with_ldap(session, username, password)

        # Auto-detect or EMAIL: check if user exists in database (by username or email)
        user = UserService.get_user_by_username(session, username)
        if not user:
            user = UserService.get_user_by_email(session, username)

        if user and user.auth_type == "LDAP":
            # LDAP user — always use username for LDAP auth (even if user entered email)
            return AuthService._login_with_ldap(session, user.username, password)
        elif user and user.auth_type == "EMAIL":
            return AuthService._login_with_email(session, username, password)
        elif auth_type == "EMAIL":
            # User not found, let _login_with_email handle the error
            return AuthService._login_with_email(session, username, password)
        else:
            # User doesn't exist or uses LDAP, try LDAP authentication
            return AuthService._login_with_ldap(session, username, password)

    @staticmethod
    def _login_without_auth(session: Session) -> Dict:
        """无密码模式登录：直接签发本地管理员 token。

        不自增 token_version——单机模式允许多窗口/多进程并存，不做设备互踢。
        """
        from app.services.local_admin_service import (
            accept_all_agreements,
            get_or_create_local_admin,
            grant_vibe_coding_access,
        )

        user = get_or_create_local_admin(session)
        accept_all_agreements(session, user)
        grant_vibe_coding_access(session, user)
        UserService.update_last_login(session, user.id)
        session.refresh(user)

        logger.info(f"AUTH_DISABLED: issued local token for {user.username} (ID: {user.id})")

        return {
            "user": user,
            "tokens": AuthService._generate_tokens(user),
        }

    @staticmethod
    def _login_with_ldap(session: Session, username: str, password: str) -> Dict:
        """
        LDAP authentication

        Args:
            session: Database session
            username: LDAP username
            password: Password

        Returns:
            Dict containing user info and tokens

        Raises:
            UnauthorizedException: If authentication fails
        """
        # Authenticate with LDAP
        ldap_user = LDAPService.authenticate(username, password)
        if not ldap_user:
            raise UnauthorizedException("Username or password incorrect")

        # Get or create user
        user = UserService.get_user_by_username(session, username)

        if user:
            # User exists, check if disabled
            if not user.is_active:
                raise BadRequestException("User account is disabled")

            # Update user info from LDAP
            from app.schemas.user import UserUpdate
            user_update = UserUpdate(
                nickname=ldap_user["displayName"],
                email=ldap_user["mail"]
            )
            user = UserService.update_user(session, user.id, user_update)
        else:
            # First login, create user
            user_create = UserCreate(
                username=ldap_user["username"],
                email=ldap_user["mail"],
                nickname=ldap_user["displayName"],
                auth_type="LDAP",
                role="user"
            )
            user = UserService.create_user(session, user_create)

        # Update last login
        UserService.update_last_login(session, user.id)

        # Increment token_version for single-device login
        user.token_version += 1
        session.add(user)
        session.commit()
        session.refresh(user)

        # Generate tokens
        tokens = AuthService._generate_tokens(user)

        logger.info(f"LDAP user logged in: {username} (ID: {user.id})")

        return {
            "user": user,
            "tokens": tokens
        }

    @staticmethod
    def _login_with_email(session: Session, username_or_email: str, password: str) -> Dict:
        """
        EMAIL authentication

        Args:
            session: Database session
            username_or_email: Username or email
            password: Password

        Returns:
            Dict containing user info and tokens

        Raises:
            UnauthorizedException: If authentication fails
        """
        # Try to find user by username
        user = UserService.get_user_by_username(session, username_or_email)

        # If not found, try email
        if not user:
            user = UserService.get_user_by_email(session, username_or_email)

        if not user:
            raise UnauthorizedException("Username/email or password incorrect")

        # Verify password
        if not user.check_password(password):
            raise UnauthorizedException("Username/email or password incorrect")

        # Check if email is verified (EMAIL users only, admins exempt)
        if user.auth_type == "EMAIL" and not user.email_verified and user.role != "admin":
            # Resend verification code automatically
            from app.services.registration_service import RegistrationService
            try:
                RegistrationService.resend_verification(session, user.email)
            except Exception as e:
                logger.warning(f"Failed to resend verification email to {user.email}: {e}")
            raise EmailNotVerifiedException(email=user.email, detail="Email not verified. Verification code has been resent.")

        # Check if disabled
        if not user.is_active:
            raise BadRequestException("User account is disabled")

        # Update last login
        UserService.update_last_login(session, user.id)

        # Increment token_version for single-device login
        user.token_version += 1
        session.add(user)
        session.commit()
        session.refresh(user)

        # Generate tokens
        tokens = AuthService._generate_tokens(user)

        logger.info(f"EMAIL user logged in: {username_or_email} (ID: {user.id})")

        return {
            "user": user,
            "tokens": tokens
        }

    @staticmethod
    def _generate_tokens(user: User) -> TokenResponse:
        """
        Generate JWT tokens for user

        Args:
            user: User object

        Returns:
            TokenResponse with access and refresh tokens
        """
        # Token payload
        token_data = {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
            "token_version": user.token_version
        }

        # Generate tokens
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer"
        )

    @staticmethod
    def refresh_access_token(user: User, token_version: Optional[int] = None) -> Dict:
        """
        Refresh access token using refresh token

        Args:
            user: User from refresh token
            token_version: 原 refresh token 携带的版本号。刷新是续命同一会话，
                新 token 必须继承原版本而非取用户当前值——否则多端用户的旧设备
                每次刷新都会"升级"到最新版本，实际在线设备数会超过 max_sessions。
                None（旧 token 无版本号）时用当前值。

        Returns:
            Dict with new access token and refresh token
        """
        # Generate new token data
        token_data = {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
            "token_version": token_version if token_version is not None else user.token_version
        }

        # Generate new access token and refresh token
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer"
        }
