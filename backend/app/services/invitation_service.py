"""
Invitation code service
"""
import secrets
import string
from datetime import timedelta
from typing import List, Tuple, Optional
from sqlmodel import Session, select, func

from app.models.invitation_code import InvitationCode
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logger import logger
from app.utils.timeutil import utcnow as _utcnow


class InvitationService:

    @staticmethod
    def _generate_code() -> str:
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(8))

    @staticmethod
    def generate_codes(
        session: Session,
        created_by: int,
        count: int = 1,
        max_uses: int = 1,
        note: str = None,
        expires_days: int = None,
        assigned_email: str = None,
    ) -> List[InvitationCode]:
        codes = []
        expires_at = None
        if expires_days:
            expires_at = _utcnow() + timedelta(days=expires_days)

        for _ in range(count):
            # Ensure unique code
            while True:
                code_str = InvitationService._generate_code()
                existing = session.exec(
                    select(InvitationCode).where(InvitationCode.code == code_str)
                ).first()
                if not existing:
                    break

            code = InvitationCode(
                code=code_str,
                created_by=created_by,
                max_uses=max_uses,
                note=note,
                assigned_email=assigned_email,
                expires_at=expires_at,
            )
            session.add(code)
            codes.append(code)

        session.commit()
        for c in codes:
            session.refresh(c)

        logger.info(f"Generated {count} invitation codes by user {created_by}")
        return codes

    @staticmethod
    def validate_code(session: Session, code_str: str, email: str = None) -> InvitationCode:
        statement = select(InvitationCode).where(InvitationCode.code == code_str)
        code = session.exec(statement).first()

        if not code:
            raise BadRequestException("Invalid invitation code")

        if not code.is_active:
            raise BadRequestException("Invitation code is disabled")

        if code.use_count >= code.max_uses:
            raise BadRequestException("Invitation code has been fully used")

        if code.expires_at and code.expires_at < _utcnow():
            raise BadRequestException("Invitation code has expired")

        if code.assigned_email and email and code.assigned_email.lower() != email.lower():
            raise BadRequestException("This invitation code is not assigned to your email")

        return code

    @staticmethod
    def consume_code(session: Session, code_str: str, user_id: int) -> None:
        statement = select(InvitationCode).where(InvitationCode.code == code_str)
        code = session.exec(statement).first()
        if code:
            code.use_count += 1
            code.used_by = user_id
            code.used_at = _utcnow()
            session.add(code)
            session.commit()

    @staticmethod
    def get_codes_paginated(
        session: Session,
        page: int = 1,
        page_size: int = 20,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[InvitationCode], int]:
        statement = select(InvitationCode)

        if is_active is not None:
            statement = statement.where(InvitationCode.is_active == is_active)

        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()

        statement = statement.order_by(InvitationCode.created_at.desc())
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        codes = session.exec(statement).all()
        return codes, total

    @staticmethod
    def toggle_code(session: Session, code_id: int) -> InvitationCode:
        code = session.get(InvitationCode, code_id)
        if not code:
            raise NotFoundException("Invitation code not found")

        code.is_active = not code.is_active
        session.add(code)
        session.commit()
        session.refresh(code)
        return code

    @staticmethod
    def delete_code(session: Session, code_id: int) -> None:
        from app.models.invitation_application import InvitationApplication

        code = session.get(InvitationCode, code_id)
        if not code:
            raise NotFoundException("Invitation code not found")

        # Clear foreign key references in invitation_applications
        statement = select(InvitationApplication).where(
            InvitationApplication.invitation_code_id == code_id
        )
        applications = session.exec(statement).all()
        for app in applications:
            app.invitation_code_id = None
            session.add(app)

        session.delete(code)
        session.commit()
        logger.info(f"Invitation code deleted: {code.code} (ID: {code.id})")
