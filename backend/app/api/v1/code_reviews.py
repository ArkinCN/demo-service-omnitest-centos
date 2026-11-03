"""
Code Review management API endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.code_review import (
    CodeReviewCreate,
    CodeReviewResultCreate,
    CodeReviewShareCreate,
    CodeReviewShareUpdate,
    CommentCreate,
    CodeReviewResponse,
    CodeReviewListItem,
    CodeReviewDetailResponse,
    CodeReviewResultResponse,
    CodeReviewShareResponse,
    CommentResponse,
    CodeReviewQueryParams,
    SharedReviewQueryParams,
    CodeReviewStatsResponse
)
from app.schemas.common import success_response, PaginatedResponse
from app.services.code_review_service import CodeReviewService
import math


router = APIRouter(prefix="/code-reviews", tags=["Code Review"])


# ============================================================================
# Basic CRUD Operations
# ============================================================================

@router.post("", response_model=dict, summary="Create code review")
def create_review(
    review_data: CodeReviewCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new code review

    - **title**: Review title
    - **check_type**: GROUP or PROJECT
    - **check_mode**: SINGLE or BATCH
    - **ai_model**: AI model name
    - **ai_prompt**: AI prompt text
    - **tags**: Optional tags array
    - **description**: Optional description

    Returns created review
    """
    review = CodeReviewService.create_review(
        session=session,
        user_id=current_user.id,
        review_data=review_data
    )

    # Convert to response model
    review_dict = CodeReviewResponse.model_validate(review).model_dump()

    return success_response(
        data=review_dict,
        message="Code review created successfully",
        code=201
    )


@router.post("/{review_id}/results", response_model=dict, summary="Save review results")
def save_results(
    review_id: int,
    results_data: CodeReviewResultCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Save code review results (batch)

    - **review_id**: Review ID
    - **results**: Array of result objects

    Returns success status
    """
    results = CodeReviewService.save_results(
        session=session,
        review_id=review_id,
        results_data=results_data.results
    )

    return success_response(
        data={"count": len(results)},
        message="Results saved successfully"
    )


@router.get("/me", response_model=dict, summary="Get my reviews")
def get_my_reviews(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Status filter"),
    check_type: Optional[str] = Query(None, description="Check type filter"),
    keyword: Optional[str] = Query(None, description="Search keyword"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get my code reviews (paginated)

    - **page**: Page number (1-indexed)
    - **page_size**: Items per page (max 100)
    - **status**: Filter by status (PENDING/PROCESSING/COMPLETED/FAILED)
    - **check_type**: Filter by check type (GROUP/PROJECT)
    - **keyword**: Search in title and description
    - **sort_by**: Sort field (created_at, title, total_projects, etc.)
    - **sort_order**: Sort order (asc/desc)

    Returns paginated list of reviews
    """
    reviews, total = CodeReviewService.get_user_reviews(
        session=session,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        status_filter=status,
        check_type_filter=check_type,
        keyword=keyword,
        sort_by=sort_by,
        sort_order=sort_order
    )

    # Convert to response models
    reviews_list = [CodeReviewListItem.model_validate(r).model_dump() for r in reviews]

    # Calculate total pages
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    pagination_data = {
        "items": reviews_list,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(
        data=pagination_data,
        message="Reviews retrieved successfully"
    )


@router.get("/{review_id}", response_model=dict, summary="Get review detail")
def get_review_detail(
    review_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get code review detail

    - **review_id**: Review ID

    Returns review detail with configuration and statistics
    """
    review_dict = CodeReviewService.get_review_detail(
        session=session,
        review_id=review_id,
        user_id=current_user.id
    )

    # Convert to response model
    review_data = CodeReviewDetailResponse.model_validate(review_dict).model_dump()

    return success_response(
        data=review_data,
        message="Review detail retrieved successfully"
    )


@router.get("/{review_id}/results", response_model=dict, summary="Get review results")
def get_review_results(
    review_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get review results (paginated)

    - **review_id**: Review ID
    - **page**: Page number
    - **page_size**: Items per page

    Returns paginated list of results
    """
    results, total = CodeReviewService.get_review_results(
        session=session,
        review_id=review_id,
        user_id=current_user.id,
        page=page,
        page_size=page_size
    )

    # Convert to response models
    results_list = [CodeReviewResultResponse.model_validate(r).model_dump() for r in results]

    # Calculate total pages
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    pagination_data = {
        "items": results_list,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(
        data=pagination_data,
        message="Results retrieved successfully"
    )


@router.delete("/{review_id}", response_model=dict, summary="Delete review")
def delete_review(
    review_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a code review

    - **review_id**: Review ID

    Only the owner can delete the review
    """
    CodeReviewService.delete_review(
        session=session,
        review_id=review_id,
        user_id=current_user.id
    )

    return success_response(
        message="Review deleted successfully"
    )


# ============================================================================
# Share Functionality
# ============================================================================

@router.post("/{review_id}/share", response_model=dict, summary="Share review")
def share_review(
    review_id: int,
    share_data: CodeReviewShareCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Share a code review

    - **review_id**: Review ID
    - **share_scope**: PRIVATE, TEAM, or PUBLIC
    - **share_message**: Optional share message
    - **allowed_users**: Optional user IDs (for TEAM scope)
    - **expires_at**: Optional expiration datetime

    Returns share information with link
    """
    share_dict = CodeReviewService.share_review(
        session=session,
        review_id=review_id,
        user_id=current_user.id,
        share_data=share_data
    )

    # Convert to response model
    share_response = CodeReviewShareResponse.model_validate(share_dict).model_dump()

    return success_response(
        data=share_response,
        message="Review shared successfully"
    )


@router.put("/{review_id}/share", response_model=dict, summary="Update share settings")
def update_share(
    review_id: int,
    share_data: CodeReviewShareUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update share settings

    - **review_id**: Review ID
    - **share_scope**: Optional new scope
    - **share_message**: Optional new message
    - **allowed_users**: Optional new user list
    - **expires_at**: Optional new expiration

    Returns updated share information
    """
    # Convert update to create schema (for reuse)
    # First get current review to get review_id
    review_dict = CodeReviewService.get_review_detail(
        session=session,
        review_id=review_id,
        user_id=current_user.id
    )

    create_data = CodeReviewShareCreate(
        review_id=review_id,
        share_scope=share_data.share_scope or review_dict["share_scope"],
        share_message=share_data.share_message,
        allowed_users=share_data.allowed_users,
        expires_at=share_data.expires_at
    )

    share_dict = CodeReviewService.share_review(
        session=session,
        review_id=review_id,
        user_id=current_user.id,
        share_data=create_data
    )

    share_response = CodeReviewShareResponse.model_validate(share_dict).model_dump()

    return success_response(
        data=share_response,
        message="Share settings updated successfully"
    )


@router.delete("/{review_id}/share", response_model=dict, summary="Cancel share")
def cancel_share(
    review_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cancel sharing a review

    - **review_id**: Review ID

    Sets review back to PRIVATE
    """
    CodeReviewService.cancel_share(
        session=session,
        review_id=review_id,
        user_id=current_user.id
    )

    return success_response(
        data={"cancelled": True},
        message="Share cancelled successfully"
    )


@router.get("/shared/list", response_model=dict, summary="Get shared reviews")
def get_shared_reviews(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    scope: Optional[str] = Query(None, description="Scope filter (TEAM/PUBLIC)"),
    tag: Optional[str] = Query(None, description="Tag filter"),
    keyword: Optional[str] = Query(None, description="Search keyword"),
    sort_by: str = Query("shared_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get shared code reviews from others

    - **page**: Page number
    - **page_size**: Items per page
    - **scope**: Filter by scope (TEAM/PUBLIC)
    - **tag**: Filter by specific tag
    - **keyword**: Search in title and description
    - **sort_by**: Sort field (shared_at, view_count, etc.)
    - **sort_order**: Sort order (asc/desc)

    Returns paginated list of shared reviews
    """
    reviews, total = CodeReviewService.get_shared_reviews(
        session=session,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        scope_filter=scope,
        tag_filter=tag,
        keyword=keyword,
        sort_by=sort_by,
        sort_order=sort_order
    )

    # Convert to response models
    reviews_list = [CodeReviewListItem.model_validate(r).model_dump() for r in reviews]

    # Calculate total pages
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    pagination_data = {
        "items": reviews_list,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

    return success_response(
        data=pagination_data,
        message="Shared reviews retrieved successfully"
    )


@router.get("/shared/verify", response_model=dict, summary="Verify share code")
def verify_share_code(
    code: str = Query(..., description="8-character share code (e.g., FTRABCDE)"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verify a share code and return review summary

    - **code**: 8-character share code (FTR + 5 uppercase letters)

    Returns review summary if valid
    """
    review_summary = CodeReviewService.verify_share_code(
        session=session,
        share_code=code,
        user_id=current_user.id
    )

    return success_response(
        data=review_summary,
        message="Share code verified successfully"
    )


@router.post("/{review_id}/view", response_model=dict, summary="Increment view count")
def increment_view_count(
    review_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Increment view count for a shared review

    - **review_id**: Review ID

    Increments view count (only if not owner)
    """
    CodeReviewService.increment_view_count(
        session=session,
        review_id=review_id,
        user_id=current_user.id
    )

    return success_response(
        data={"incremented": True},
        message="View count incremented successfully"
    )


# ============================================================================
# Comment Functionality
# ============================================================================

@router.post("/{review_id}/comments", response_model=dict, summary="Add comment")
def add_comment(
    review_id: int,
    comment_data: CommentCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a comment to a review

    - **review_id**: Review ID
    - **content**: Comment content (1-2000 chars)
    - **comment_type**: COMMENT, QUESTION, or SUGGESTION
    - **result_id**: Optional result ID (for result-specific comments)
    - **parent_id**: Optional parent comment ID (for replies)

    Returns created comment
    """
    comment_dict = CodeReviewService.add_comment(
        session=session,
        review_id=review_id,
        user_id=current_user.id,
        comment_data=comment_data
    )

    # Convert to response model
    comment_response = CommentResponse.model_validate(comment_dict).model_dump()

    return success_response(
        data=comment_response,
        message="Comment added successfully",
        code=201
    )


@router.get("/{review_id}/comments", response_model=dict, summary="Get comments")
def get_comments(
    review_id: int,
    result_id: Optional[int] = Query(None, description="Result ID filter"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get comments for a review

    - **review_id**: Review ID
    - **result_id**: Optional filter for result-specific comments

    Returns list of comments with replies (nested)
    """
    comments = CodeReviewService.get_comments(
        session=session,
        review_id=review_id,
        user_id=current_user.id,
        result_id=result_id
    )

    # Convert to response models
    comments_list = [CommentResponse.model_validate(c).model_dump() for c in comments]

    return success_response(
        data={"comments": comments_list, "total": len(comments_list)},
        message="Comments retrieved successfully"
    )


@router.post("/comments/{comment_id}/like", response_model=dict, summary="Like comment")
def like_comment(
    comment_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Like a comment

    - **comment_id**: Comment ID

    Increments like count
    """
    CodeReviewService.like_comment(
        session=session,
        comment_id=comment_id,
        user_id=current_user.id
    )

    return success_response(
        message="Comment liked successfully"
    )


# ============================================================================
# Statistics
# ============================================================================

@router.get("/stats/me", response_model=dict, summary="Get my statistics")
def get_my_stats(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get my code review statistics

    Returns:
    - Total reviews count
    - Total projects reviewed
    - Total issues found
    - Total shares count
    - Total views received
    - Last review timestamp
    """
    stats = CodeReviewService.get_user_stats(
        session=session,
        user_id=current_user.id
    )

    stats_dict = CodeReviewStatsResponse.model_validate(stats).model_dump()

    return success_response(
        data=stats_dict,
        message="Statistics retrieved successfully"
    )
