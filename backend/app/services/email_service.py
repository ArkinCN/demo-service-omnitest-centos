"""
Email service for sending verification codes and notification emails
"""
import smtplib
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid

from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import InternalServerException


class EmailService:

    @staticmethod
    def send_email(to: str, subject: str, html_body: str) -> None:
        if not settings.SMTP_HOST:
            logger.warning("SMTP not configured, skipping email send")
            raise InternalServerException("Email service is not configured")

        sender_domain = settings.SMTP_FROM_EMAIL.rsplit("@", 1)[-1] or None
        message_id = make_msgid(domain=sender_domain)

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
            msg["To"] = to
            msg["Subject"] = subject
            # Date 与 Message-ID 必须显式设置：smtplib 不会补这两个头，
            # 缺失时阿里云会把主题相同的连续验证码邮件判定为重复邮件并静默丢弃
            # （SMTP 返回 250，但邮件不入队、发信日志中也查不到）。
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = message_id
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if settings.SMTP_USE_SSL:
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
            else:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
                server.starttls()

            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            refused = server.sendmail(settings.SMTP_FROM_EMAIL, [to], msg.as_string())
            server.quit()
        except Exception as e:
            logger.error(f"Failed to send email to {to} (Message-ID: {message_id}): {e}")
            raise InternalServerException("Failed to send email")

        if refused:
            logger.error(f"Email refused for {to} (Message-ID: {message_id}): {refused}")
            raise InternalServerException("Failed to send email")

        logger.info(f"Email sent to {to}: {subject} (Message-ID: {message_id})")

    @staticmethod
    def send_verification_code(email: str, code: str) -> None:
        html_body = f"""
        <div style="max-width:600px;margin:0 auto;padding:20px;font-family:sans-serif;">
            <h2 style="color:#333;">验证您的邮箱</h2>
            <p>感谢您注册 MotorDebug，请在应用中输入以下验证码完成邮箱验证：</p>
            <div style="text-align:center;margin:30px 0;">
                <div style="background:#f5f5f5;padding:16px 32px;border-radius:8px;display:inline-block;">
                    <span style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#3964fe;">{code}</span>
                </div>
            </div>
            <p style="color:#999;font-size:12px;">此验证码15分钟内有效。如果您没有注册 MotorDebug，请忽略此邮件。</p>
        </div>
        """
        return EmailService.send_email(email, "MotorDebug - 邮箱验证码", html_body)

    @staticmethod
    def send_password_reset_code(email: str, code: str) -> None:
        html_body = f"""
        <div style="max-width:600px;margin:0 auto;padding:20px;font-family:sans-serif;">
            <h2 style="color:#333;">重置密码</h2>
            <p>您请求重置 MotorDebug 账号密码，请在应用中输入以下验证码：</p>
            <div style="text-align:center;margin:30px 0;">
                <div style="background:#f5f5f5;padding:16px 32px;border-radius:8px;display:inline-block;">
                    <span style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#3964fe;">{code}</span>
                </div>
            </div>
            <p style="color:#999;font-size:12px;">此验证码15分钟内有效。如果您没有请求重置密码，请忽略此邮件。</p>
        </div>
        """
        return EmailService.send_email(email, "MotorDebug - 密码重置验证码", html_body)

    @staticmethod
    def send_account_deletion_code(email: str, code: str) -> None:
        html_body = f"""
        <div style="max-width:600px;margin:0 auto;padding:20px;font-family:sans-serif;">
            <h2 style="color:#333;">账号注销确认</h2>
            <p>您正在申请注销 MotorDebug 账号。注销后账号将无法登录，对话记录、订阅与额度等数据将被删除且<strong>不可恢复</strong>。请在应用中输入以下验证码确认注销：</p>
            <div style="text-align:center;margin:30px 0;">
                <div style="background:#f5f5f5;padding:16px 32px;border-radius:8px;display:inline-block;">
                    <span style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#e5484d;">{code}</span>
                </div>
            </div>
            <p style="color:#999;font-size:12px;">此验证码15分钟内有效。如果您没有申请注销账号，请忽略此邮件并考虑修改密码。</p>
        </div>
        """
        return EmailService.send_email(email, "MotorDebug - 账号注销验证码", html_body)

    @staticmethod
    def send_application_verification_code(email: str, code: str) -> None:
        html_body = f"""
        <div style="max-width:600px;margin:0 auto;padding:20px;font-family:sans-serif;">
            <h2 style="color:#333;">验证您的邮箱</h2>
            <p>您正在申请 MotorDebug 内测资格，请在申请页面输入以下验证码以确认此邮箱归您所有：</p>
            <div style="text-align:center;margin:30px 0;">
                <div style="background:#f5f5f5;padding:16px 32px;border-radius:8px;display:inline-block;">
                    <span style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#3964fe;">{code}</span>
                </div>
            </div>
            <p style="color:#999;font-size:12px;">此验证码15分钟内有效。如果您没有申请 MotorDebug 内测，请忽略此邮件。</p>
        </div>
        """
        return EmailService.send_email(email, "MotorDebug - 内测申请邮箱验证码", html_body)

    @staticmethod
    def send_invitation_code_email(email: str, code: str, download_url: Optional[str] = None) -> None:
        download_section = ""
        if download_url:
            download_section = f"""
            <div style="text-align:center;margin:30px 0;">
                <a href="{download_url}" style="display:inline-block;background:#3964fe;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-size:15px;">下载 MotorDebug for Windows（最新版）</a>
            </div>
            """
        html_body = f"""
        <div style="max-width:600px;margin:0 auto;padding:20px;font-family:sans-serif;">
            <h2 style="color:#333;">内测码</h2>
            <p>您的 MotorDebug 内测申请已通过审核！以下是您的内测码：</p>
            <div style="text-align:center;margin:30px 0;">
                <div style="background:#f5f5f5;padding:16px 32px;border-radius:8px;display:inline-block;">
                    <span style="font-size:24px;font-weight:bold;letter-spacing:4px;color:#3964fe;">{code}</span>
                </div>
            </div>
            <p>请使用此内测码在注册页面完成注册。</p>
            {download_section}
            <p style="color:#999;font-size:12px;">此内测码仅限一次使用，请勿分享给他人。</p>
        </div>
        """
        return EmailService.send_email(email, "MotorDebug - 内测码", html_body)
