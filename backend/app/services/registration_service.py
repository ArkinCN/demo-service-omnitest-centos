"""
Registration service for email-based user registration and password reset
"""
import random
import string
from datetime import timedelta

from sqlmodel import Session, select

from app.models.user import User
from app.models.email_verification import EmailVerification
from app.schemas.user import UserCreate
from app.services.user_service import UserService
from app.services.email_service import EmailService
from app.services.invitation_service import InvitationService
from app.core.config import settings
from app.utils.timeutil import utcnow as _utcnow
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.core.logger import logger


def _generate_code(length: int = 6) -> str:
    """Generate a random numeric verification code"""
    return "".join(random.choices(string.digits, k=length))


class RegistrationService:

    @staticmethod
    def register(session: Session, username: str, email: str, password: str,
                 invitation_code: str = None, company: str = None, real_name: str = None) -> User:
        # Validate invitation code if required
        if settings.REQUIRE_INVITATION_CODE:
            if not invitation_code:
                raise BadRequestException("Invitation code is required")
            InvitationService.validate_code(session, invitation_code, email=email)

        # Create user
        user_create = UserCreate(
            username=username,
            email=email,
            password=password,
            auth_type="EMAIL",
            role="user",
            company=company,
            real_name=real_name,
        )
        user = UserService.create_user(session, user_create)

        # Mark email as not verified
        user.email_verified = False
        session.add(user)
        session.commit()
        session.refresh(user)

        # Consume invitation code
        if settings.REQUIRE_INVITATION_CODE and invitation_code:
            InvitationService.consume_code(session, invitation_code, user.id)

        # Generate verification code and send email
        code = _generate_code()
        verification = EmailVerification(
            user_id=user.id,
            code=code,
            type="VERIFY",
            expires_at=_utcnow() + timedelta(minutes=15),
        )
        session.add(verification)
        session.commit()

        EmailService.send_verification_code(email, code)

        logger.info(f"User registered: {username} (ID: {user.id})")
        return user

    @staticmethod
    def verify_email(session: Session, email: str, code: str) -> User:
        user = UserService.get_user_by_email(session, email)
        if not user:
            raise BadRequestException("Invalid verification code")

        statement = select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.code == code,
            EmailVerification.type == "VERIFY",
            EmailVerification.used == False,
        )
        verification = session.exec(statement).first()

        if not verification:
            raise BadRequestException("Invalid verification code")

        if verification.expires_at < _utcnow():
            raise BadRequestException("Verification code has expired")

        # Mark code as used
        verification.used = True
        session.add(verification)

        # Activate user email
        user.email_verified = True
        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info(f"Email verified for user: {user.username} (ID: {user.id})")
        return user

    @staticmethod
    def resend_verification(session: Session, email: str) -> None:
        user = UserService.get_user_by_email(session, email)
        if not user:
            # Don't reveal whether email exists
            return

        if user.email_verified:
            raise BadRequestException("Email is already verified")

        # Rate limit: at most one verification email per 60 seconds
        latest = session.exec(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.type == "VERIFY",
            ).order_by(EmailVerification.created_at.desc())
        ).first()
        if latest and (_utcnow() - latest.created_at).total_seconds() < 60:
            raise BadRequestException("Please wait before requesting another verification code")

        # Invalidate old codes
        statement = select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.type == "VERIFY",
            EmailVerification.used == False,
        )
        old_codes = session.exec(statement).all()
        for c in old_codes:
            c.used = True
            session.add(c)

        # Generate new code
        code = _generate_code()
        verification = EmailVerification(
            user_id=user.id,
            code=code,
            type="VERIFY",
            expires_at=_utcnow() + timedelta(minutes=15),
        )
        session.add(verification)
        session.commit()

        EmailService.send_verification_code(email, code)
        logger.info(f"Verification code resent to: {email}")

    @staticmethod
    def forgot_password(session: Session, email: str) -> str:
        """
        Request password reset. Returns auth_type for frontend routing.
        """
        user = UserService.get_user_by_email(session, email)
        if not user:
            # Don't reveal whether email exists
            return "EMAIL"

        if user.auth_type != "EMAIL":
            return user.auth_type

        # Rate limit: at most one reset email per 60 seconds
        latest = session.exec(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.type == "RESET",
            ).order_by(EmailVerification.created_at.desc())
        ).first()
        if latest and (_utcnow() - latest.created_at).total_seconds() < 60:
            raise BadRequestException("Please wait before requesting another reset code")

        # Generate reset code
        code = _generate_code()
        verification = EmailVerification(
            user_id=user.id,
            code=code,
            type="RESET",
            expires_at=_utcnow() + timedelta(minutes=15),
        )
        session.add(verification)
        session.commit()

        EmailService.send_password_reset_code(email, code)
        logger.info(f"Password reset code sent to: {email}")
        return "EMAIL"

    @staticmethod
    def reset_password(session: Session, email: str, code: str, new_password: str) -> None:
        user = UserService.get_user_by_email(session, email)
        if not user:
            raise BadRequestException("Invalid reset code")

        statement = select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.code == code,
            EmailVerification.type == "RESET",
            EmailVerification.used == False,
        )
        verification = session.exec(statement).first()

        if not verification:
            raise BadRequestException("Invalid reset code")

        if verification.expires_at < _utcnow():
            raise BadRequestException("Reset code has expired")

        # Mark code as used
        verification.used = True
        session.add(verification)

        # Update password
        user.set_password(new_password)
        session.add(user)
        session.commit()

        logger.info(f"Password reset for user: {user.username} (ID: {user.id})")
