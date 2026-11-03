"""
Self-service account deletion for EMAIL (non-LDAP) users

流程：发验证码到绑定邮箱 → 提交验证码 → 物理清理业务数据 + 软删除用户行。
软删除（deleted_at 非空）保证 credit_transactions / ai_requests 等审计流水的外键仍有效；
username/email 改写为 deleted_{id}_ 前缀以释放唯一值，供同名/同邮箱再次注册。
"""
import random
import string
from datetime import timedelta

from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.models.user import User
from app.models.email_verification import EmailVerification
from app.models.chat import Chat
from app.models.credits import UserCredits, UserSubscription
from app.models.user_group import UserGroupMember
from app.models.feedback import Feedback, FeedbackReply
from app.models.external_link import UserLinkFavorite, UserFavoriteFolder
from app.models.invitation_code import InvitationCode
from app.services.email_service import EmailService
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.logger import logger
from app.utils.timeutil import utcnow as _utcnow

DELETION_CODE_TYPE = "DELETE"


def _generate_code(length: int = 6) -> str:
    """Generate a random numeric verification code"""
    return "".join(random.choices(string.digits, k=length))


class AccountDeletionService:

    @staticmethod
    def _ensure_email_account(user: User) -> None:
        if user.auth_type != "EMAIL":
            raise ForbiddenException("LDAP accounts cannot be deleted from the app")

    @staticmethod
    def request_deletion_code(session: Session, user: User) -> None:
        """Send an account-deletion verification code to the user's email"""
        AccountDeletionService._ensure_email_account(user)

        # Rate limit: at most one deletion email per 60 seconds
        latest = session.exec(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.type == DELETION_CODE_TYPE,
            ).order_by(EmailVerification.created_at.desc())
        ).first()
        if latest and (_utcnow() - latest.created_at).total_seconds() < 60:
            raise BadRequestException("Please wait before requesting another deletion code")

        # Invalidate old codes
        old_codes = session.exec(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.type == DELETION_CODE_TYPE,
                EmailVerification.used == False,  # noqa: E712
            )
        ).all()
        for c in old_codes:
            c.used = True
            session.add(c)

        code = _generate_code()
        verification = EmailVerification(
            user_id=user.id,
            code=code,
            type=DELETION_CODE_TYPE,
            expires_at=_utcnow() + timedelta(minutes=15),
        )
        session.add(verification)
        session.commit()

        EmailService.send_account_deletion_code(user.email, code)
        logger.info(f"Account deletion code sent to user: {user.username} (ID: {user.id})")

    @staticmethod
    def confirm_deletion(session: Session, user: User, code: str) -> None:
        """Verify the code, purge user-owned data and soft-delete the account"""
        AccountDeletionService._ensure_email_account(user)

        verification = session.exec(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.code == code,
                EmailVerification.type == DELETION_CODE_TYPE,
                EmailVerification.used == False,  # noqa: E712
            )
        ).first()
        if not verification:
            raise BadRequestException("Invalid deletion code")
        if verification.expires_at < _utcnow():
            raise BadRequestException("Deletion code has expired")

        AccountDeletionService._purge_user_data(session, user.id)

        # 软删除：标记 + 双保险失效 token（is_active + token_version）+ 释放唯一值
        # token_version 按 max_sessions 步进：多端用户登录窗口内的所有版本一次性滑出
        user.deleted_at = _utcnow()
        user.is_active = False
        user.token_version += user.effective_max_sessions()
        user.username = f"deleted_{user.id}_{user.username}"[:80]
        user.email = f"deleted_{user.id}_{user.email}"[:120]
        user.password_hash = None
        session.add(user)
        session.commit()

        logger.info(f"Account soft-deleted: {user.username} (ID: {user.id})")

    @staticmethod
    def _purge_user_data(session: Session, user_id: int) -> None:
        """
        物理删除用户拥有的业务数据；审计流水（credit_transactions / ai_requests /
        code_reviews / agreements / external_link_clicks）保留，FK 指向软删除的用户行。
        注意：MySQL 侧无 ON DELETE CASCADE，须按子表在前的顺序手动删。
        """
        # 反馈：先删回复（本人的回复 + 本人反馈下的所有回复），再删本人反馈
        own_feedback_ids = session.exec(
            select(Feedback.id).where(Feedback.user_id == user_id)
        ).all()
        session.execute(sa_delete(FeedbackReply).where(FeedbackReply.user_id == user_id))
        if own_feedback_ids:
            session.execute(
                sa_delete(FeedbackReply).where(FeedbackReply.feedback_id.in_(own_feedback_ids))
            )
        session.execute(sa_delete(Feedback).where(Feedback.user_id == user_id))

        # 别人反馈的处理人是该用户 → 置空
        assigned = session.exec(
            select(Feedback).where(Feedback.assigned_to == user_id)
        ).all()
        for f in assigned:
            f.assigned_to = None
            session.add(f)

        # 对话记录（消息树内嵌在 history JSON 列，无子表）
        session.execute(sa_delete(Chat).where(Chat.user_id == user_id))

        # 订阅与余额（流水 credit_transactions 保留）
        session.execute(sa_delete(UserCredits).where(UserCredits.user_id == user_id))
        session.execute(sa_delete(UserSubscription).where(UserSubscription.user_id == user_id))

        # 分组成员
        session.execute(sa_delete(UserGroupMember).where(UserGroupMember.user_id == user_id))

        # 外链收藏（先删收藏项再删收藏夹）
        session.execute(sa_delete(UserLinkFavorite).where(UserLinkFavorite.user_id == user_id))
        session.execute(sa_delete(UserFavoriteFolder).where(UserFavoriteFolder.user_id == user_id))

        # 邮箱验证码（含本次注销码）
        session.execute(sa_delete(EmailVerification).where(EmailVerification.user_id == user_id))

        # 邀请码引用置空（保留邀请码本身，与 UserService.delete_user 一致）
        for attr in (InvitationCode.created_by, InvitationCode.used_by):
            codes = session.exec(select(InvitationCode).where(attr == user_id)).all()
            for c in codes:
                if c.created_by == user_id:
                    c.created_by = None
                if c.used_by == user_id:
                    c.used_by = None
                session.add(c)
