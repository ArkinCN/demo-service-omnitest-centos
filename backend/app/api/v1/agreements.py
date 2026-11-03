"""
Agreement management API endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.schemas.agreement import (
    AgreementCreate,
    AgreementUpdate,
    AgreementResponse,
    AgreementPublicResponse,
    AcceptanceCheckResponse,
    AgreementAcceptRequest,
)
from app.schemas.common import success_response
from app.services.agreement_service import AgreementService


router = APIRouter(prefix="/agreements", tags=["Agreement Management"])


# ==================== Public Endpoints ====================

@router.get("/latest", response_model=dict, summary="Get latest published agreements")
def get_latest_agreements(
    session: Session = Depends(get_db),
):
    """
    Get the latest published version of each agreement type.
    No authentication required - used on login page.
    """
    agreements = AgreementService.get_all_latest_published(session)
    data = [AgreementPublicResponse.model_validate(a).model_dump() for a in agreements]
    return success_response(data=data)


@router.get("/versions/{agreement_type}", response_model=dict, summary="Get all published versions of an agreement type")
def get_published_versions(
    agreement_type: str,
    session: Session = Depends(get_db),
):
    """
    Get all published versions of a specific agreement type.
    No authentication required - used in settings page.
    """
    agreements = AgreementService.get_published_versions(session, agreement_type)
    data = [AgreementPublicResponse.model_validate(a).model_dump() for a in agreements]
    return success_response(data=data)


# ==================== User Endpoints ====================

@router.get("/check", response_model=dict, summary="Check agreement acceptance status")
def check_agreement_acceptance(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Check if current user needs to accept any new agreements.
    Returns pending agreements if acceptance is needed.
    """
    needs_acceptance, is_first_time, pending = AgreementService.check_acceptance_needed(session, current_user.id)
    data = AcceptanceCheckResponse(
        needs_acceptance=needs_acceptance,
        is_first_time=is_first_time,
        pending_agreements=[AgreementPublicResponse.model_validate(a) for a in pending],
    ).model_dump()
    return success_response(data=data)


@router.post("/accept", response_model=dict, summary="Accept agreements")
def accept_agreements(
    request: AgreementAcceptRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record user acceptance of agreements.
    """
    AgreementService.accept_agreements(session, current_user.id, request.agreement_ids)
    return success_response(message="Agreements accepted successfully")


# ==================== Admin Endpoints ====================

@router.post("", response_model=dict, summary="Create agreement draft")
def create_agreement(
    data: AgreementCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Create a new agreement draft (admin only)"""
    agreement = AgreementService.create_agreement(session, current_user.id, data)
    return success_response(
        data=AgreementResponse.model_validate(agreement).model_dump(),
        message="Agreement draft created",
        code=201,
    )


@router.get("", response_model=dict, summary="List all agreements")
def list_agreements(
    type_filter: Optional[str] = Query(None, alias="type", description="Filter by type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all agreements with optional type filter (admin only)"""
    items, total = AgreementService.list_agreements(session, type_filter, page, page_size)
    total_pages = (total + page_size - 1) // page_size
    data = {
        "items": [AgreementResponse.model_validate(a).model_dump() for a in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
    return success_response(data=data)


@router.get("/{agreement_id}", response_model=dict, summary="Get agreement detail")
def get_agreement(
    agreement_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Get a single agreement by ID (admin only)"""
    agreement = AgreementService.get_agreement(session, agreement_id)
    return success_response(data=AgreementResponse.model_validate(agreement).model_dump())


@router.put("/{agreement_id}", response_model=dict, summary="Update agreement draft")
def update_agreement(
    agreement_id: int,
    data: AgreementUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Update an unpublished agreement draft (admin only)"""
    agreement = AgreementService.update_agreement(session, agreement_id, data)
    return success_response(
        data=AgreementResponse.model_validate(agreement).model_dump(),
        message="Agreement updated",
    )


@router.delete("/{agreement_id}", response_model=dict, summary="Delete agreement draft")
def delete_agreement(
    agreement_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete an unpublished agreement draft (admin only)"""
    AgreementService.delete_agreement(session, agreement_id)
    return success_response(message="Agreement deleted")


@router.post("/{agreement_id}/publish", response_model=dict, summary="Publish agreement")
def publish_agreement(
    agreement_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Publish an agreement (admin only). Users will be prompted to accept it."""
    agreement = AgreementService.publish_agreement(session, agreement_id)
    return success_response(
        data=AgreementResponse.model_validate(agreement).model_dump(),
        message="Agreement published",
    )
