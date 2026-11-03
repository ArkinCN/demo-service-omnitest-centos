"""
Invitation application service
"""
import random
import string
from datetime import timedelta
from typing import List, Tuple, Optional
from sqlmodel import Session, select, func

from app.models.invitation_application import InvitationApplication
from app.models.invitation_application_verification import InvitationApplicationVerification
from app.services.invitation_service import InvitationService
from app.services.email_service import EmailService
from app.services.user_service import UserService
from app.services.update_service import UpdateService
from app.core.config import settings
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logger import logger
from app.utils.timeutil import utcnow as _utcnow


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


class InvitationApplicationService:

    @staticmethod
    def send_verification_code(session: Session, email: str) -> None:
        # Reject emails that already have an account
        existing_user = UserService.get_user_by_email(session, email)
        if existing_user:
            raise BadRequestException("This email is already registered")

        # Rate limit: at most one verification email per 60 seconds
        latest = session.exec(
            select(InvitationApplicationVerification)
            .where(InvitationApplicationVerification.email == email)
            .order_by(InvitationApplicationVerification.created_at.desc())
        ).first()
        if latest and (_utcnow() - latest.created_at).total_seconds() < 60:
            raise BadRequestException("Please wait before requesting another verification code")

        # Invalidate previous unused codes for this email
        old_codes = session.exec(
            select(InvitationApplicationVerification).where(
                InvitationApplicationVerification.email == email,
                InvitationApplicationVerification.used == False,
            )
        ).all()
        for c in old_codes:
            c.used = True
            session.add(c)

        code = _generate_code()
        verification = InvitationApplicationVerification(
            email=email,
            code=code,
            expires_at=_utcnow() + timedelta(minutes=15),
        )
        session.add(verification)
        session.commit()

        EmailService.send_application_verification_code(email, code)
        logger.info(f"Invitation application verification code sent to: {email}")

    @staticmethod
    def create_application(session: Session, email: str, code: str, name: str = None, company: str = None, reason: str = None, sales_email: str = None) -> InvitationApplication:
        # Check if email is already registered
        existing_user = UserService.get_user_by_email(session, email)
        if existing_user:
            raise BadRequestException("This email is already registered")

        # Verify email ownership via the code sent to this address
        verification = session.exec(
            select(InvitationApplicationVerification).where(
                InvitationApplicationVerification.email == email,
                InvitationApplicationVerification.code == code,
                InvitationApplicationVerification.used == False,
            )
        ).first()
        if not verification or verification.expires_at < _utcnow():
            raise BadRequestException("Invalid or expired verification code")

        # Check for existing pending application
        statement = select(InvitationApplication).where(
            InvitationApplication.email == email,
            InvitationApplication.status == "PENDING",
        )
        existing = session.exec(statement).first()
        if existing:
            raise BadRequestException("You already have a pending application")

        verification.used = True
        session.add(verification)

        application = InvitationApplication(
            email=email,
            name=name,
            company=company,
            reason=reason,
            sales_email=sales_email,
        )
        session.add(application)
        session.commit()
        session.refresh(application)

        logger.info(f"Invitation application created: {email} (ID: {application.id})")
        return application

    @staticmethod
    def review_application(
        session: Session,
        application_id: int,
        status: str,
        reviewed_by: int,
    ) -> InvitationApplication:
        application = session.get(InvitationApplication, application_id)
        if not application:
            raise NotFoundException("Application not found")

        if application.status != "PENDING":
            raise BadRequestException("Application has already been reviewed")

        application.status = status
        application.reviewed_by = reviewed_by
        application.reviewed_at = datetime.now(timezone.utc)

        if status == "APPROVED":
            # Generate an invitation code assigned to the applicant's email
            codes = InvitationService.generate_codes(
                session=session,
                created_by=reviewed_by,
                count=1,
                max_uses=1,
                note=f"Auto-generated for application #{application_id}",
                assigned_email=application.email,
            )
            code = codes[0]
            application.invitation_code_id = code.id

            # 附上最新 Windows 稳定版下载链接（经官网域名反代，避免暴露 aiproxy）
            latest = UpdateService.get_latest_version(
                session=session, platform="windows", channel="stable"
            )
            download_url = (
                f"{settings.DOWNLOAD_PUBLIC_BASE_URL}"
                f"/api/v1/updates/download/{latest.version}?platform=windows"
            ) if latest else None
            EmailService.send_invitation_code_email(application.email, code.code, download_url)

        session.add(application)
        session.commit()
        session.refresh(application)

        logger.info(f"Application #{application_id} reviewed: {status}")
        return application

    @staticmethod
    def get_applications_paginated(
        session: Session,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> Tuple[List[InvitationApplication], int]:
        statement = select(InvitationApplication)

        if status:
            statement = statement.where(InvitationApplication.status == status)

        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        statement = statement.order_by(InvitationApplication.created_at.desc())
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        applications = session.exec(statement).all()
        return applications, total
