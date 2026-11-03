"""
Invitation code management API endpoints (admin only)
"""
import math
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.invitation import InvitationCodeCreate, InvitationCodeResponse
from app.schemas.common import success_response
from app.services.invitation_service import InvitationService


router = APIRouter(prefix="/invitations", tags=["Invitations"])


@router.post("/generate", response_model=dict, summary="Generate invitation codes")
def generate_codes(
    data: InvitationCodeCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    codes = InvitationService.generate_codes(
        session=session,
        created_by=current_user.id,
        count=data.count,
        max_uses=data.max_uses,
        note=data.note,
        expires_days=data.expires_days,
    )
    codes_data = [InvitationCodeResponse.model_validate(c).model_dump() for c in codes]
    return success_response(data=codes_data, message=f"Generated {len(codes)} invitation codes")


@router.get("", response_model=dict, summary="List invitation codes")
def get_codes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: bool = Query(default=None),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    codes, total = InvitationService.get_codes_paginated(
        session=session,
        page=page,
        page_size=page_size,
        is_active=is_active,
    )
    codes_data = [InvitationCodeResponse.model_validate(c).model_dump() for c in codes]
    return success_response(data={
        "items": codes_data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total > 0 else 0,
    })


@router.patch("/{code_id}/toggle", response_model=dict, summary="Toggle invitation code")
def toggle_code(
    code_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    code = InvitationService.toggle_code(session=session, code_id=code_id)
    return success_response(
        data=InvitationCodeResponse.model_validate(code).model_dump(),
        message=f"Invitation code {'enabled' if code.is_active else 'disabled'}",
    )


@router.delete("/{code_id}", response_model=dict, summary="Delete invitation code")
def delete_code(
    code_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    InvitationService.delete_code(session=session, code_id=code_id)
    return success_response(message="Invitation code deleted")
