"""
Registration API endpoints (public, no authentication required)
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db
from app.schemas.registration import (
    RegisterRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.schemas.common import success_response
from app.services.registration_service import RegistrationService
from app.core.config import settings


router = APIRouter(prefix="/auth", tags=["Registration"])


@router.post("/register", response_model=dict, summary="Register new account")
def register(data: RegisterRequest, session: Session = Depends(get_db)):
    user = RegistrationService.register(
        session=session,
        username=data.username,
        email=data.email,
        password=data.password,
        invitation_code=data.invitation_code,
        company=data.company,
        real_name=data.real_name,
    )
    return success_response(
        data={"user_id": user.id, "email": user.email},
        message="Registration successful. Please check your email for the verification code.",
    )


@router.post("/verify-email", response_model=dict, summary="Verify email with code")
def verify_email(data: VerifyEmailRequest, session: Session = Depends(get_db)):
    RegistrationService.verify_email(session=session, email=data.email, code=data.code)
    return success_response(message="Email verified successfully")


@router.post("/resend-verification", response_model=dict, summary="Resend verification code")
def resend_verification(data: ResendVerificationRequest, session: Session = Depends(get_db)):
    RegistrationService.resend_verification(session=session, email=data.email)
    return success_response(message="If the email exists, a verification code has been sent")


@router.post("/forgot-password", response_model=dict, summary="Request password reset code")
def forgot_password(data: ForgotPasswordRequest, session: Session = Depends(get_db)):
    auth_type = RegistrationService.forgot_password(session=session, email=data.email)
    return success_response(
        data={"auth_type": auth_type},
        message="If the email exists, a password reset code has been sent"
    )


@router.post("/reset-password", response_model=dict, summary="Reset password with code")
def reset_password(data: ResetPasswordRequest, session: Session = Depends(get_db)):
    RegistrationService.reset_password(
        session=session, email=data.email, code=data.code, new_password=data.new_password
    )
    return success_response(message="Password reset successfully")


@router.get("/invitation-required", response_model=dict, summary="Check if invitation code is required")
def check_invitation_required():
    return success_response(data={"required": settings.REQUIRE_INVITATION_CODE})
