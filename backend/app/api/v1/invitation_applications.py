"""
Invitation application API endpoints
"""
import math
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.invitation import (
    InvitationApplicationCreate,
    InvitationApplicationSendCode,
    InvitationApplicationReview,
    InvitationApplicationResponse,
)
from app.schemas.common import success_response
from app.services.invitation_application_service import InvitationApplicationService


router = APIRouter(prefix="/invitation-applications", tags=["Invitation Applications"])


@router.post("/send-code", response_model=dict, summary="Send application email verification code")
def send_application_code(
    data: InvitationApplicationSendCode,
    session: Session = Depends(get_db),
):
    InvitationApplicationService.send_verification_code(session=session, email=data.email)
    return success_response(message="Verification code sent")


@router.post("", response_model=dict, summary="Submit invitation application")
def submit_application(
    data: InvitationApplicationCreate,
    session: Session = Depends(get_db),
):
    application = InvitationApplicationService.create_application(
        session=session,
        email=data.email,
        code=data.code,
        name=data.name,
        company=data.company,
        reason=data.reason,
        sales_email=data.sales_email,
    )
    return success_response(
        data=InvitationApplicationResponse.model_validate(application).model_dump(),
        message="Application submitted successfully",
    )


@router.get("", response_model=dict, summary="List invitation applications")
def get_applications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str = Query(default=None),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    applications, total = InvitationApplicationService.get_applications_paginated(
        session=session,
        page=page,
        page_size=page_size,
        status=status,
    )
    apps_data = [InvitationApplicationResponse.model_validate(a).model_dump() for a in applications]
    return success_response(data={
        "items": apps_data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total > 0 else 0,
    })


@router.post("/{application_id}/review", response_model=dict, summary="Review invitation application")
def review_application(
    application_id: int,
    data: InvitationApplicationReview,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    application = InvitationApplicationService.review_application(
        session=session,
        application_id=application_id,
        status=data.status,
        reviewed_by=current_user.id,
    )
    return success_response(
        data=InvitationApplicationResponse.model_validate(application).model_dump(),
        message=f"Application {data.status.lower()}",
    )
