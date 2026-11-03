"""
Code Review service for CRUD operations
"""
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from sqlmodel import Session, select, func, or_, and_
import json
import uuid
import random
import string

from app.models.code_review import (
    CodeReview,
    CodeReviewResult,
    CodeReviewShare,
    CodeReviewComment,
    CodeReviewStats
)
from app.models.user import User
from app.schemas.code_review import (
    CodeReviewCreate,
    CodeReviewResultCreate,
    CodeReviewShareCreate,
    CodeReviewShareUpdate,
    CommentCreate,
    CodeReviewStatsResponse
)
from app.core.exceptions import NotFoundException, ForbiddenException, BadRequestException
from app.core.logger import logger


class CodeReviewService:
    """Code Review CRUD service"""

    # ========================================================================
    # Basic CRUD Operations
    # ========================================================================

    @staticmethod
    def create_review(
        session: Session,
        user_id: int,
        review_data: CodeReviewCreate
    ) -> CodeReview:
        """
        Create a new code review

        Args:
            session: Database session
            user_id: User ID who created the review
            review_data: Review creation data

        Returns:
            Created review

        Raises:
            NotFoundException: If user not found
        """
        # Verify user exists and get user info
        user = session.get(User, user_id)
        if not user:
            raise NotFoundException(f"User with ID {user_id} not found")

        # Create review
        review = CodeReview(
            user_id=user_id,
            reviewer_name=user.nickname,
            reviewer_avatar=user.avatar_url,
            title=review_data.title or "代码审查",
            group_id=review_data.group_id,
            project_id=review_data.project_id,
            branch=review_data.branch,
            check_type=review_data.check_type,
            check_mode=review_data.check_mode,
            file_name=review_data.file_name,
            ai_model=review_data.ai_model,
            ai_prompt=review_data.ai_prompt,
            ref_issue=review_data.ref_issue,
            description=review_data.description,
            tags=json.dumps(review_data.tags) if review_data.tags else "[]",
            status="PENDING"
        )

        session.add(review)
        session.commit()
        session.refresh(review)

        logger.info(f"Code review created: ID={review.id}, User={user_id}, Type={review.check_type}")
        return review

    @staticmethod
    def save_results(
        session: Session,
        review_id: int,
        results_data: List[Dict[str, Any]]
    ) -> List[CodeReviewResult]:
        """
        Save code review results

        Args:
            session: Database session
            review_id: Review ID
            results_data: List of result data dicts

        Returns:
            List of created results

        Raises:
            NotFoundException: If review not found
        """
        # Verify review exists
        review = session.get(CodeReview, review_id)
        if not review:
            raise NotFoundException(f"Code review with ID {review_id} not found")

        # Create results - support both snake_case and camelCase
        results = []
        for data in results_data:
            result = CodeReviewResult(
                review_id=review_id,
                group_name=data.get("group_name") or data.get("groupName", ""),
                project_name=data.get("project_name") or data.get("projectName", ""),
                project_id=data.get("project_id") or data.get("projectId", ""),
                project_url=data.get("project_url") or data.get("projectUrl"),
                branch=data.get("branch", ""),
                file_links=json.dumps(data.get("file_links") or data.get("fileLinks", [])),
                file_count=data.get("file_count") or data.get("fileCount", 0),
                status=data.get("status", ""),
                issue_description=data.get("issue_description") or data.get("issueDescription"),
                severity=data.get("severity"),
                ai_analysis=json.dumps(data.get("ai_analysis") or data.get("aiAnalysis")) if (data.get("ai_analysis") or data.get("aiAnalysis")) else None
            )
            results.append(result)
            session.add(result)

        # Update review statistics
        review.total_projects = len(results_data)
        review.normal_count = sum(1 for r in results_data if r.get("status") == "NORMAL")
        review.issue_count = sum(1 for r in results_data if r.get("status") == "ISSUE")
        review.error_count = sum(1 for r in results_data if r.get("status") == "ERROR")
        review.not_found_count = sum(1 for r in results_data if r.get("status") == "NOTFOUND")
        review.status = "COMPLETED"
        review.completed_at = datetime.now(timezone.utc)
        review.updated_at = datetime.now(timezone.utc)

        session.commit()

        # Update user stats
        CodeReviewService.update_stats(session, review.user_id, review)

        logger.info(f"Code review results saved: ReviewID={review_id}, ResultsCount={len(results)}")
        return results

    @staticmethod
    def get_review_detail(
        session: Session,
        review_id: int,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Get code review detail by ID

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID

        Returns:
            Review dict with additional info

        Raises:
            NotFoundException: If review not found
            ForbiddenException: If user doesn't have access
        """
        # Query review
        review = session.get(CodeReview, review_id)
        if not review:
            raise NotFoundException(f"Code review with ID {review_id} not found")

        # Check access permission
        is_owner = review.user_id == user_id

        if not is_owner:
            # If not owner, check if review is shared
            if not review.is_shared:
                raise ForbiddenException("You don't have permission to access this review")

            if review.share_scope == "PRIVATE":
                raise ForbiddenException("This review is private")

            if review.share_scope == "TEAM":
                # Check if user is in allowed_users
                share = session.exec(
                    select(CodeReviewShare)
                    .where(CodeReviewShare.review_id == review_id)
                    .order_by(CodeReviewShare.created_at.desc())
                ).first()

                if share:
                    allowed_users = json.loads(share.allowed_users) if isinstance(share.allowed_users, str) else share.allowed_users
                    if user_id not in allowed_users:
                        raise ForbiddenException("You don't have permission to access this team review")
                else:
                    raise ForbiddenException("Share configuration not found")

            # If PUBLIC or permission granted, increment view count
            if not is_owner:
                review.view_count += 1
                session.add(review)
                session.commit()

        # Convert to dict
        review_dict = {
            "id": review.id,
            "user_id": review.user_id,
            "reviewer_name": review.reviewer_name,
            "reviewer_avatar": review.reviewer_avatar,
            "title": review.title,
            "group_id": review.group_id,
            "project_id": review.project_id,
            "branch": review.branch,
            "check_type": review.check_type,
            "check_mode": review.check_mode,
            "file_name": review.file_name,
            "ai_model": review.ai_model,
            "ai_prompt": review.ai_prompt,
            "ref_issue": review.ref_issue,
            "total_projects": review.total_projects,
            "normal_count": review.normal_count,
            "issue_count": review.issue_count,
            "error_count": review.error_count,
            "not_found_count": review.not_found_count,
            "status": review.status,
            "is_shared": review.is_shared,
            "share_scope": review.share_scope,
            "shared_at": review.shared_at,
            "view_count": review.view_count,
            "tags": review.tags,
            "description": review.description,
            "created_at": review.created_at,
            "updated_at": review.updated_at,
            "completed_at": review.completed_at,
            "is_owner": is_owner,
            "share_link": None
        }

        # Add share link if owner
        if is_owner and review.is_shared:
            share = session.exec(
                select(CodeReviewShare)
                .where(CodeReviewShare.review_id == review_id)
                .order_by(CodeReviewShare.created_at.desc())
            ).first()
            if share:
                review_dict["share_link"] = share.share_link

        return review_dict

    @staticmethod
    def get_user_reviews(
        session: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        check_type_filter: Optional[str] = None,
        keyword: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get user's code reviews (paginated)

        Args:
            session: Database session
            user_id: User ID
            page: Page number
            page_size: Items per page
            status_filter: Filter by status
            check_type_filter: Filter by check type
            keyword: Search keyword
            sort_by: Sort field
            sort_order: Sort order (asc/desc)

        Returns:
            Tuple of (reviews list, total count)
        """
        # Build query
        conditions = [CodeReview.user_id == user_id]

        if status_filter:
            conditions.append(CodeReview.status == status_filter)

        if check_type_filter:
            conditions.append(CodeReview.check_type == check_type_filter)

        if keyword:
            conditions.append(
                or_(
                    CodeReview.title.contains(keyword),
                    CodeReview.description.contains(keyword)
                )
            )

        # Count total
        count_stmt = select(func.count(CodeReview.id)).where(*conditions)
        total = session.exec(count_stmt).one()

        # Get paginated results
        offset = (page - 1) * page_size

        # Dynamic sorting
        order_column = getattr(CodeReview, sort_by, CodeReview.created_at)
        order_func = order_column.desc() if sort_order == "desc" else order_column.asc()

        stmt = (
            select(CodeReview)
            .where(*conditions)
            .order_by(order_func)
            .offset(offset)
            .limit(page_size)
        )
        reviews = session.exec(stmt).all()

        # Convert to dict and add share links
        reviews_list = []
        for review in reviews:
            # Get share link if review is shared
            share_link = None
            if review.is_shared:
                share_stmt = select(CodeReviewShare.share_link).where(
                    CodeReviewShare.review_id == review.id
                ).order_by(CodeReviewShare.created_at.desc()).limit(1)
                share_link_result = session.exec(share_stmt).first()
                share_link = share_link_result if share_link_result else None

            review_dict = {
                "id": review.id,
                "user_id": review.user_id,
                "reviewer_name": review.reviewer_name,
                "reviewer_avatar": review.reviewer_avatar,
                "title": review.title,
                "group_id": review.group_id,
                "project_id": review.project_id,
                "branch": review.branch,
                "check_type": review.check_type,
                "check_mode": review.check_mode,
                "file_name": review.file_name,
                "ai_model": review.ai_model,
                "ai_prompt": review.ai_prompt,
                "total_projects": review.total_projects,
                "normal_count": review.normal_count,
                "issue_count": review.issue_count,
                "error_count": review.error_count,
                "not_found_count": review.not_found_count,
                "status": review.status,
                "is_shared": review.is_shared,
                "share_scope": review.share_scope,
                "share_link": share_link,
                "view_count": review.view_count,
                "tags": review.tags,
                "created_at": review.created_at,
                "is_owner": True
            }
            reviews_list.append(review_dict)

        return reviews_list, total

    @staticmethod
    def delete_review(
        session: Session,
        review_id: int,
        user_id: int
    ) -> bool:
        """
        Delete a code review

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID

        Returns:
            True if deleted

        Raises:
            NotFoundException: If review not found
            ForbiddenException: If user is not the owner
        """
        review = session.get(CodeReview, review_id)
        if not review:
            raise NotFoundException(f"Code review with ID {review_id} not found")

        if review.user_id != user_id:
            raise ForbiddenException("You can only delete your own reviews")

        # Delete related records (cascade would handle this in production)
        session.exec(select(CodeReviewResult).where(CodeReviewResult.review_id == review_id)).all()
        session.exec(select(CodeReviewShare).where(CodeReviewShare.review_id == review_id)).all()
        session.exec(select(CodeReviewComment).where(CodeReviewComment.review_id == review_id)).all()

        session.delete(review)
        session.commit()

        logger.info(f"Code review deleted: ID={review_id}, User={user_id}")
        return True

    # ========================================================================
    # Share Functionality
    # ========================================================================

    @staticmethod
    def share_review(
        session: Session,
        review_id: int,
        user_id: int,
        share_data: CodeReviewShareCreate
    ) -> Dict[str, Any]:
        """
        Share a code review

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID
            share_data: Share configuration

        Returns:
            Share info dict

        Raises:
            NotFoundException: If review not found
            ForbiddenException: If user is not the owner
        """
        review = session.get(CodeReview, review_id)
        if not review:
            raise NotFoundException(f"Code review with ID {review_id} not found")

        if review.user_id != user_id:
            raise ForbiddenException("You can only share your own reviews")

        # Generate 8-character share code: FTR + 5 random uppercase letters
        random_chars = ''.join(random.choices(string.ascii_uppercase, k=5))
        share_link = f"FTR{random_chars}"

        # Create or update share record
        existing_share = session.exec(
            select(CodeReviewShare)
            .where(CodeReviewShare.review_id == review_id)
            .order_by(CodeReviewShare.created_at.desc())
        ).first()

        if existing_share:
            # Update existing share
            existing_share.share_link = share_link
            existing_share.share_message = share_data.share_message
            existing_share.allowed_users = json.dumps(share_data.allowed_users or [])
            existing_share.expires_at = share_data.expires_at
            existing_share.created_at = datetime.now(timezone.utc)
            share = existing_share
        else:
            # Create new share
            share = CodeReviewShare(
                review_id=review_id,
                shared_by=user_id,
                share_link=share_link,
                share_message=share_data.share_message,
                allowed_users=json.dumps(share_data.allowed_users or []),
                expires_at=share_data.expires_at
            )
            session.add(share)

        # Update review
        review.is_shared = True
        review.share_scope = share_data.share_scope
        review.shared_at = datetime.now(timezone.utc)
        review.updated_at = datetime.now(timezone.utc)

        session.commit()
        session.refresh(share)

        # Update stats
        CodeReviewService._increment_share_count(session, user_id)

        logger.info(f"Code review shared: ReviewID={review_id}, Scope={share_data.share_scope}")

        return {
            "id": share.id,
            "review_id": share.review_id,
            "share_link": share.share_link,
            "share_message": share.share_message,
            "share_scope": review.share_scope,
            "allowed_users": share.allowed_users,
            "expires_at": share.expires_at,
            "created_at": share.created_at
        }

    @staticmethod
    def get_shared_reviews(
        session: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        scope_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        keyword: Optional[str] = None,
        sort_by: str = "shared_at",
        sort_order: str = "desc"
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get shared code reviews

        Args:
            session: Database session
            user_id: Current user ID
            page: Page number
            page_size: Items per page
            scope_filter: Filter by scope (TEAM/PUBLIC)
            tag_filter: Filter by tag
            keyword: Search keyword
            sort_by: Sort field
            sort_order: Sort order

        Returns:
            Tuple of (reviews list, total count)
        """
        # Build query conditions
        conditions = [
            CodeReview.is_shared == True,
            CodeReview.user_id != user_id  # Exclude own reviews
        ]

        # PUBLIC reviews or TEAM reviews where user is allowed
        if scope_filter:
            if scope_filter == "PUBLIC":
                conditions.append(CodeReview.share_scope == "PUBLIC")
            elif scope_filter == "TEAM":
                # Need to join with shares table to check allowed_users
                conditions.append(CodeReview.share_scope == "TEAM")
        else:
            # Include both PUBLIC and TEAM (will filter TEAM later)
            conditions.append(or_(
                CodeReview.share_scope == "PUBLIC",
                CodeReview.share_scope == "TEAM"
            ))

        if keyword:
            conditions.append(
                or_(
                    CodeReview.title.contains(keyword),
                    CodeReview.description.contains(keyword)
                )
            )

        # Get reviews
        stmt = select(CodeReview).where(*conditions)
        all_reviews = session.exec(stmt).all()

        # Filter TEAM reviews and tag filter
        filtered_reviews = []
        for review in all_reviews:
            # Check TEAM permission
            if review.share_scope == "TEAM":
                share = session.exec(
                    select(CodeReviewShare)
                    .where(CodeReviewShare.review_id == review.id)
                    .order_by(CodeReviewShare.created_at.desc())
                ).first()

                if share:
                    allowed_users = json.loads(share.allowed_users) if isinstance(share.allowed_users, str) else share.allowed_users
                    if user_id not in allowed_users:
                        continue
                else:
                    continue

            # Tag filter
            if tag_filter:
                tags = json.loads(review.tags) if isinstance(review.tags, str) else review.tags
                if tag_filter not in tags:
                    continue

            filtered_reviews.append(review)

        # Total count
        total = len(filtered_reviews)

        # Sorting
        if sort_by == "shared_at":
            filtered_reviews.sort(key=lambda x: x.shared_at or x.created_at, reverse=(sort_order == "desc"))
        elif sort_by == "view_count":
            filtered_reviews.sort(key=lambda x: x.view_count, reverse=(sort_order == "desc"))
        else:
            filtered_reviews.sort(key=lambda x: x.created_at, reverse=(sort_order == "desc"))

        # Pagination
        offset = (page - 1) * page_size
        paginated_reviews = filtered_reviews[offset:offset + page_size]

        # Convert to dict
        reviews_list = []
        for review in paginated_reviews:
            review_dict = {
                "id": review.id,
                "user_id": review.user_id,
                "reviewer_name": review.reviewer_name,
                "reviewer_avatar": review.reviewer_avatar,
                "title": review.title,
                "group_id": review.group_id,
                "project_id": review.project_id,
                "branch": review.branch,
                "check_type": review.check_type,
                "check_mode": review.check_mode,
                "file_name": review.file_name,
                "ai_model": review.ai_model,
                "ai_prompt": review.ai_prompt,
                "total_projects": review.total_projects,
                "normal_count": review.normal_count,
                "issue_count": review.issue_count,
                "error_count": review.error_count,
                "not_found_count": review.not_found_count,
                "status": review.status,
                "is_shared": review.is_shared,
                "share_scope": review.share_scope,
                "share_link": None,  # 不返回分享口令给非所有者
                "shared_at": review.shared_at,
                "view_count": review.view_count,
                "tags": review.tags,
                "description": review.description,
                "created_at": review.created_at,
                "is_owner": False
            }
            reviews_list.append(review_dict)

        return reviews_list, total

    @staticmethod
    def cancel_share(
        session: Session,
        review_id: int,
        user_id: int
    ) -> bool:
        """
        Cancel sharing a review

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID

        Returns:
            True if cancelled

        Raises:
            NotFoundException: If review not found
            ForbiddenException: If user is not the owner
        """
        review = session.get(CodeReview, review_id)
        if not review:
            raise NotFoundException(f"Code review with ID {review_id} not found")

        if review.user_id != user_id:
            raise ForbiddenException("You can only cancel sharing your own reviews")

        review.is_shared = False
        review.share_scope = "PRIVATE"
        review.updated_at = datetime.now(timezone.utc)

        session.commit()

        logger.info(f"Code review share cancelled: ReviewID={review_id}")
        return True

    @staticmethod
    def verify_share_code(
        session: Session,
        share_code: str,
        user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Verify share code and return review summary

        Args:
            session: Database session
            share_code: 8-character share code (FTR + 5 letters)
            user_id: Current user ID

        Returns:
            Review summary dict if valid, None if invalid

        Raises:
            NotFoundException: If share code not found
            ForbiddenException: If user doesn't have permission
        """
        # Find review by share_link
        share = session.exec(
            select(CodeReviewShare)
            .where(CodeReviewShare.share_link == share_code)
            .order_by(CodeReviewShare.created_at.desc())
        ).first()

        if not share:
            raise NotFoundException("Invalid share code")

        # Get review
        review = session.get(CodeReview, share.review_id)
        if not review or not review.is_shared:
            raise NotFoundException("Share code is invalid or expired")

        # Check permission
        if review.share_scope == "PRIVATE":
            # For PRIVATE scope with allowed_users
            allowed_users = json.loads(share.allowed_users) if isinstance(share.allowed_users, str) else share.allowed_users
            if user_id not in allowed_users:
                raise ForbiddenException("You don't have permission to access this review")

        # Return review summary with all necessary fields
        return {
            "id": review.id,
            "reviewer_name": review.reviewer_name,
            "reviewer_avatar": review.reviewer_avatar,
            "title": review.title,
            "description": review.description,
            "check_type": review.check_type,
            "check_mode": review.check_mode,
            "group_id": review.group_id,
            "project_id": review.project_id,
            "branch": review.branch,
            "file_name": review.file_name,
            "ai_model": review.ai_model,
            "ai_prompt": review.ai_prompt,
            "ref_issue": review.ref_issue,
            "total_projects": review.total_projects,
            "normal_count": review.normal_count,
            "issue_count": review.issue_count,
            "error_count": review.error_count,
            "not_found_count": review.not_found_count,
            "view_count": review.view_count,
            "share_scope": review.share_scope,
            "shared_at": review.shared_at,
            "created_at": review.created_at,
            "tags": review.tags,
            "share_message": share.share_message
        }

    @staticmethod
    def increment_view_count(
        session: Session,
        review_id: int,
        user_id: int
    ) -> bool:
        """
        Increment view count for a shared review

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID

        Returns:
            True if incremented

        Raises:
            NotFoundException: If review not found
        """
        review = session.get(CodeReview, review_id)
        if not review:
            raise NotFoundException(f"Code review with ID {review_id} not found")

        # Only increment if not owner
        if review.user_id != user_id:
            review.view_count += 1
            review.updated_at = datetime.now(timezone.utc)
            session.commit()

            # Update owner's stats
            stats = session.exec(
                select(CodeReviewStats).where(CodeReviewStats.user_id == review.user_id)
            ).first()
            if stats:
                stats.total_views_received += 1
                stats.updated_at = datetime.now(timezone.utc)
                session.commit()

            logger.info(f"View count incremented: ReviewID={review_id}, User={user_id}")

        return True

    # ========================================================================
    # Comment Functionality
    # ========================================================================

    @staticmethod
    def add_comment(
        session: Session,
        review_id: int,
        user_id: int,
        comment_data: CommentCreate
    ) -> Dict[str, Any]:
        """
        Add a comment to a review

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID
            comment_data: Comment data

        Returns:
            Created comment dict

        Raises:
            NotFoundException: If review not found
        """
        # Verify review exists and user has access
        review_dict = CodeReviewService.get_review_detail(session, review_id, user_id)

        # Get user info
        user = session.get(User, user_id)

        # Create comment
        comment = CodeReviewComment(
            review_id=review_id,
            result_id=comment_data.result_id,
            user_id=user_id,
            content=comment_data.content,
            comment_type=comment_data.comment_type,
            parent_id=comment_data.parent_id
        )

        session.add(comment)
        session.commit()
        session.refresh(comment)

        logger.info(f"Comment added: ReviewID={review_id}, CommentID={comment.id}, User={user_id}")

        return {
            "id": comment.id,
            "review_id": comment.review_id,
            "result_id": comment.result_id,
            "user_id": comment.user_id,
            "user_name": user.nickname,
            "user_avatar": user.avatar_url,
            "content": comment.content,
            "comment_type": comment.comment_type,
            "parent_id": comment.parent_id,
            "likes_count": comment.likes_count,
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
            "replies": []
        }

    @staticmethod
    def get_comments(
        session: Session,
        review_id: int,
        user_id: int,
        result_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get comments for a review

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID
            result_id: Optional result ID filter

        Returns:
            List of comment dicts with replies

        Raises:
            NotFoundException: If review not found
        """
        # Verify access
        review_dict = CodeReviewService.get_review_detail(session, review_id, user_id)

        # Build query
        conditions = [
            CodeReviewComment.review_id == review_id,
            CodeReviewComment.parent_id == None  # Top-level comments only
        ]

        if result_id:
            conditions.append(CodeReviewComment.result_id == result_id)

        # Get top-level comments
        stmt = (
            select(CodeReviewComment, User.nickname, User.avatar_url)
            .join(User, CodeReviewComment.user_id == User.id)
            .where(*conditions)
            .order_by(CodeReviewComment.created_at.desc())
        )
        results = session.exec(stmt).all()

        # Build comment tree
        comments_list = []
        for comment, user_name, user_avatar in results:
            comment_dict = {
                "id": comment.id,
                "review_id": comment.review_id,
                "result_id": comment.result_id,
                "user_id": comment.user_id,
                "user_name": user_name,
                "user_avatar": user_avatar,
                "content": comment.content,
                "comment_type": comment.comment_type,
                "parent_id": comment.parent_id,
                "likes_count": comment.likes_count,
                "created_at": comment.created_at,
                "updated_at": comment.updated_at,
                "replies": CodeReviewService._get_comment_replies(session, comment.id)
            }
            comments_list.append(comment_dict)

        return comments_list

    @staticmethod
    def _get_comment_replies(session: Session, parent_id: int) -> List[Dict[str, Any]]:
        """Get replies for a comment (recursive)"""
        stmt = (
            select(CodeReviewComment, User.nickname, User.avatar_url)
            .join(User, CodeReviewComment.user_id == User.id)
            .where(CodeReviewComment.parent_id == parent_id)
            .order_by(CodeReviewComment.created_at.asc())
        )
        results = session.exec(stmt).all()

        replies = []
        for comment, user_name, user_avatar in results:
            reply_dict = {
                "id": comment.id,
                "review_id": comment.review_id,
                "result_id": comment.result_id,
                "user_id": comment.user_id,
                "user_name": user_name,
                "user_avatar": user_avatar,
                "content": comment.content,
                "comment_type": comment.comment_type,
                "parent_id": comment.parent_id,
                "likes_count": comment.likes_count,
                "created_at": comment.created_at,
                "updated_at": comment.updated_at,
                "replies": CodeReviewService._get_comment_replies(session, comment.id)
            }
            replies.append(reply_dict)

        return replies

    @staticmethod
    def like_comment(
        session: Session,
        comment_id: int,
        user_id: int
    ) -> bool:
        """
        Like a comment

        Args:
            session: Database session
            comment_id: Comment ID
            user_id: Current user ID

        Returns:
            True if liked

        Raises:
            NotFoundException: If comment not found
        """
        comment = session.get(CodeReviewComment, comment_id)
        if not comment:
            raise NotFoundException(f"Comment with ID {comment_id} not found")

        # Verify user has access to the review
        CodeReviewService.get_review_detail(session, comment.review_id, user_id)

        comment.likes_count += 1
        comment.updated_at = datetime.now(timezone.utc)

        session.commit()

        logger.info(f"Comment liked: CommentID={comment_id}, User={user_id}")
        return True

    # ========================================================================
    # Results
    # ========================================================================

    @staticmethod
    def get_review_results(
        session: Session,
        review_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get review results (paginated)

        Args:
            session: Database session
            review_id: Review ID
            user_id: Current user ID
            page: Page number
            page_size: Items per page

        Returns:
            Tuple of (results list, total count)
        """
        # Verify access
        review_dict = CodeReviewService.get_review_detail(session, review_id, user_id)

        # Count total
        count_stmt = select(func.count(CodeReviewResult.id)).where(CodeReviewResult.review_id == review_id)
        total = session.exec(count_stmt).one()

        # Get paginated results
        offset = (page - 1) * page_size
        stmt = (
            select(CodeReviewResult)
            .where(CodeReviewResult.review_id == review_id)
            .order_by(CodeReviewResult.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        results = session.exec(stmt).all()

        results_list = []
        for result in results:
            result_dict = {
                "id": result.id,
                "review_id": result.review_id,
                "group_name": result.group_name,
                "project_name": result.project_name,
                "project_id": result.project_id,
                "branch": result.branch,
                "file_links": result.file_links,
                "file_count": result.file_count,
                "status": result.status,
                "issue_description": result.issue_description,
                "severity": result.severity,
                "ai_analysis": result.ai_analysis,
                "created_at": result.created_at
            }
            results_list.append(result_dict)

        return results_list, total

    # ========================================================================
    # Statistics
    # ========================================================================

    @staticmethod
    def get_user_stats(session: Session, user_id: int) -> CodeReviewStatsResponse:
        """
        Get user statistics

        Args:
            session: Database session
            user_id: User ID

        Returns:
            Stats response
        """
        stats = session.exec(
            select(CodeReviewStats).where(CodeReviewStats.user_id == user_id)
        ).first()

        if not stats:
            # Create initial stats
            stats = CodeReviewStats(user_id=user_id)
            session.add(stats)
            session.commit()
            session.refresh(stats)

        return CodeReviewStatsResponse(
            total_reviews=stats.total_reviews,
            total_projects=stats.total_projects,
            total_issues_found=stats.total_issues_found,
            total_shared=stats.total_shared,
            total_views_received=stats.total_views_received,
            last_review_at=stats.last_review_at
        )

    @staticmethod
    def update_stats(session: Session, user_id: int, review: CodeReview) -> None:
        """Update user statistics after review completion"""
        stats = session.exec(
            select(CodeReviewStats).where(CodeReviewStats.user_id == user_id)
        ).first()

        if not stats:
            stats = CodeReviewStats(user_id=user_id)
            session.add(stats)

        stats.total_reviews += 1
        stats.total_projects += review.total_projects
        stats.total_issues_found += review.issue_count
        stats.last_review_at = review.completed_at or datetime.now(timezone.utc)
        stats.updated_at = datetime.now(timezone.utc)

        session.commit()

    @staticmethod
    def _increment_share_count(session: Session, user_id: int) -> None:
        """Increment share count in stats"""
        stats = session.exec(
            select(CodeReviewStats).where(CodeReviewStats.user_id == user_id)
        ).first()

        if not stats:
            stats = CodeReviewStats(user_id=user_id)
            session.add(stats)

        stats.total_shared += 1
        stats.updated_at = datetime.now(timezone.utc)

        session.commit()
