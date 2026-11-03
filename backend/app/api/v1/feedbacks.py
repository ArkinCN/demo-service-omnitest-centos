"""
Feedback management API endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException, status
from sqlmodel import Session

from app.api.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.models.feedback import Feedback
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackStatusUpdate,
    FeedbackPriorityUpdate,
    FeedbackAssignUpdate,
    FeedbackModuleIdUpdate,
    FeedbackResponse,
    FeedbackListItem,
    FeedbackReplyCreate,
    FeedbackReplyResponse,
    FeedbackStatsResponse
)
from app.schemas.common import success_response
from app.services.feedback_service import FeedbackService
from app.services.image_service import image_service
from app.core.config import settings
import json


router = APIRouter(prefix="/feedbacks", tags=["Feedback Management"])


@router.post("", response_model=dict, summary="Submit feedback")
def submit_feedback(
    feedback_data: FeedbackCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Submit a new feedback

    - **category**: BUG, FEATURE, QUESTION, OTHER
    - **description**: Detailed problem description (10-5000 chars)
    - **contact_info**: Optional contact information
    - **attachments**: Optional screenshot URLs (max 3)

    Returns created feedback
    """
    feedback = FeedbackService.create_feedback(
        session=session,
        user_id=current_user.id,
        feedback_data=feedback_data
    )

    # Convert to response model (field_validator will handle JSON parsing)
    feedback_dict = FeedbackResponse.model_validate(feedback).model_dump()

    return success_response(data=feedback_dict, message="Feedback submitted successfully", code=201)


@router.post("/upload", response_model=dict, summary="Upload feedback attachment")
async def upload_feedback_attachment(
    file: UploadFile = File(...),
    feedback_id: int = Query(..., description="Feedback ID"),
    index: int = Query(..., ge=0, le=2, description="Attachment index (0-2)"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a feedback attachment (screenshot)

    - **file**: Image file (jpg, jpeg, png, webp, max 10MB)
    - **feedback_id**: Feedback ID to attach to
    - **index**: Attachment index (0-2, max 3 attachments per feedback)

    Returns the uploaded attachment URL
    """
    # Get feedback model directly (need actual model for modification)
    feedback = session.get(Feedback, feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail=f"Feedback with ID {feedback_id} not found")

    # Check access permission (owner or admin)
    if not current_user.is_admin and feedback.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have permission to access this feedback")

    # Process and save attachment
    attachment_url = await image_service.process_feedback_attachment(
        file=file,
        feedback_id=feedback_id,
        index=index
    )

    # Update feedback attachments
    attachments = json.loads(feedback.attachments) if isinstance(feedback.attachments, str) else (feedback.attachments or [])

    # Ensure list is large enough
    while len(attachments) <= index:
        attachments.append("")

    # Update the specific index
    attachments[index] = attachment_url

    # Save back to feedback
    feedback.attachments = json.dumps(attachments)
    session.add(feedback)
    session.commit()
    session.refresh(feedback)

    return success_response(
        data={"url": attachment_url},
        message="Attachment uploaded successfully",
        code=201
    )


@router.get("/me", response_model=dict, summary="Get my feedbacks")
def get_my_feedbacks(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get feedbacks submitted by current user (paginated)

    Returns paginated feedback list
    """
    feedbacks, total = FeedbackService.get_user_feedbacks(
        session=session,
        user_id=current_user.id,
        page=page,
        page_size=page_size
    )

    # Convert to list items (field_validator will handle JSON parsing)
    feedback_items = [FeedbackListItem.model_validate(feedback).model_dump() for feedback in feedbacks]

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    # Create paginated response
    paginated_data = {
        "items": feedback_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Feedbacks retrieved successfully")


@router.get("/stats", response_model=dict, summary="Get feedback statistics (Admin only)")
def get_feedback_stats(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get feedback statistics (Admin only)

    Returns counts by status
    """
    stats = FeedbackService.get_stats(session)
    stats_dict = stats.model_dump()

    return success_response(data=stats_dict, message="Statistics retrieved successfully")


@router.get("", response_model=dict, summary="Get all feedbacks (Admin only)")
def get_all_feedbacks(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Items per page"
    ),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    priority: Optional[str] = Query(default=None, description="Filter by priority"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    module_id: Optional[int] = Query(default=None, description="Filter by module ID"),
    keyword: Optional[str] = Query(default=None, description="Search keyword"),
    sort_order: Optional[str] = Query(default="desc", description="Sort by created_at: asc or desc"),
    hide_resolved: bool = Query(default=True, description="Hide resolved and closed feedbacks"),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get all feedbacks with filters (Admin only, paginated)

    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **status**: Filter by status (PENDING/IN_PROGRESS/RESOLVED/CLOSED)
    - **priority**: Filter by priority (LOW/MEDIUM/HIGH/URGENT)
    - **category**: Filter by category (BUG/FEATURE/QUESTION/OTHER)
    - **module_id**: Filter by module ID
    - **keyword**: Search in description
    - **sort_order**: Sort by created_at (asc/desc, default: desc)
    - **hide_resolved**: Hide resolved and closed feedbacks (default: true)

    Returns paginated feedback list
    """
    feedbacks, total = FeedbackService.get_all_feedbacks(
        session=session,
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        category=category,
        module_id=module_id,
        keyword=keyword,
        sort_order=sort_order,
        hide_resolved=hide_resolved
    )

    # Convert to list items (field_validator will handle JSON parsing)
    feedback_items = [FeedbackListItem.model_validate(feedback).model_dump() for feedback in feedbacks]

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    # Create paginated response
    paginated_data = {
        "items": feedback_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(data=paginated_data, message="Feedbacks retrieved successfully")


@router.get("/{feedback_id}", response_model=dict, summary="Get feedback detail")
def get_feedback_detail(
    feedback_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get feedback detail by ID

    Users can view their own feedbacks, admins can view all
    """
    feedback = FeedbackService.get_feedback_by_id(
        session=session,
        feedback_id=feedback_id,
        user_id=current_user.id,
        is_admin=current_user.is_admin
    )

    # Convert to response model (field_validator will handle JSON parsing)
    feedback_dict = FeedbackResponse.model_validate(feedback).model_dump()

    return success_response(data=feedback_dict, message="Feedback retrieved successfully")


@router.put("/{feedback_id}/status", response_model=dict, summary="Update feedback status (Admin only)")
def update_feedback_status(
    feedback_id: int,
    status_data: FeedbackStatusUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Update feedback status (Admin only)

    - **status**: PENDING, IN_PROGRESS, RESOLVED, CLOSED
    """
    feedback = FeedbackService.update_feedback_status(
        session=session,
        feedback_id=feedback_id,
        status=status_data.status
    )

    # Convert to response model (field_validator will handle JSON parsing)
    feedback_dict = FeedbackResponse.model_validate(feedback).model_dump()

    return success_response(data=feedback_dict, message="Feedback status updated successfully")


@router.put("/{feedback_id}/priority", response_model=dict, summary="Update feedback priority (Admin only)")
def update_feedback_priority(
    feedback_id: int,
    priority_data: FeedbackPriorityUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Update feedback priority (Admin only)

    - **priority**: LOW, MEDIUM, HIGH, URGENT
    """
    feedback = FeedbackService.update_feedback_priority(
        session=session,
        feedback_id=feedback_id,
        priority=priority_data.priority
    )

    # Convert to response model (field_validator will handle JSON parsing)
    feedback_dict = FeedbackResponse.model_validate(feedback).model_dump()

    return success_response(data=feedback_dict, message="Feedback priority updated successfully")


@router.put("/{feedback_id}/module", response_model=dict, summary="Update feedback module (Admin only)")
def update_feedback_module(
    feedback_id: int,
    module_data: FeedbackModuleIdUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Update feedback module (Admin only)

    - **module_id**: Module ID, or null to clear
    """
    feedback = FeedbackService.update_feedback_module(
        session=session,
        feedback_id=feedback_id,
        module_id=module_data.module_id
    )

    # Convert to response model (field_validator will handle JSON parsing)
    feedback_dict = FeedbackResponse.model_validate(feedback).model_dump()

    return success_response(data=feedback_dict, message="Feedback module updated successfully")


@router.put("/{feedback_id}/assign", response_model=dict, summary="Assign feedback (Admin only)")
def assign_feedback(
    feedback_id: int,
    assign_data: FeedbackAssignUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Assign feedback to an admin (Admin only)

    - **assigned_to**: Admin user ID
    """
    feedback = FeedbackService.assign_feedback(
        session=session,
        feedback_id=feedback_id,
        admin_id=assign_data.assigned_to
    )

    # Convert to response model (field_validator will handle JSON parsing)
    feedback_dict = FeedbackResponse.model_validate(feedback).model_dump()

    return success_response(data=feedback_dict, message="Feedback assigned successfully")


@router.post("/{feedback_id}/replies", response_model=dict, summary="Add reply to feedback")
def add_feedback_reply(
    feedback_id: int,
    reply_data: FeedbackReplyCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a reply to feedback

    - **content**: Reply content (1-2000 chars)
    - **is_internal**: Whether this is an internal note (admin only)

    All users can reply. Only admins can create internal notes.
    """
    reply = FeedbackService.add_reply(
        session=session,
        feedback_id=feedback_id,
        user_id=current_user.id,
        reply_data=reply_data,
        is_admin=current_user.is_admin
    )

    reply_dict = FeedbackReplyResponse.model_validate(reply).model_dump()

    return success_response(data=reply_dict, message="Reply added successfully", code=201)


@router.get("/{feedback_id}/replies", response_model=dict, summary="Get feedback replies")
def get_feedback_replies(
    feedback_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all replies for a feedback

    Admins see all replies including internal notes.
    Regular users only see public replies.
    """
    replies = FeedbackService.get_replies(
        session=session,
        feedback_id=feedback_id,
        is_admin=current_user.is_admin
    )

    reply_items = [FeedbackReplyResponse.model_validate(reply).model_dump() for reply in replies]

    return success_response(data={"replies": reply_items}, message="Replies retrieved successfully")
