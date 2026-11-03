"""
Feedback modules management API endpoints
"""
from typing import List
from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.api.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.schemas.feedback import (
    FeedbackModuleCreate,
    FeedbackModuleUpdate,
    FeedbackModuleResponse,
    FeedbackModuleTreeNode,
    FeedbackModuleReorderRequest,
)
from app.schemas.common import success_response
from app.services.feedback_module_service import FeedbackModuleService


router = APIRouter(prefix="/feedback-modules", tags=["Feedback Modules"])


@router.get("/tree", response_model=dict, summary="Get feedback modules tree")
def get_modules_tree(
    session: Session = Depends(get_db),
):
    """
    Get feedback modules as a tree structure (public endpoint)

    Returns active parent modules with children nested.
    This endpoint is public to allow anonymous feedback submission.
    """
    modules = FeedbackModuleService.get_modules_tree(
        session=session,
        include_inactive=False
    )

    # Convert to dict for response
    modules_dict = [module.model_dump() for module in modules]

    return success_response(data=modules_dict, message="Modules tree retrieved successfully")


@router.get("", response_model=dict, summary="Get all feedback modules (Admin only)")
def get_all_modules(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get all feedback modules as a flat list (Admin only)

    Returns all modules for management purposes
    """
    modules = FeedbackModuleService.get_all_modules(session=session)

    # Convert to response format
    modules_dict = [FeedbackModuleResponse.model_validate(m).model_dump() for m in modules]

    return success_response(data=modules_dict, message="Modules retrieved successfully")


@router.get("/{module_id}", response_model=dict, summary="Get feedback module by ID (Admin only)")
def get_module_by_id(
    module_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Get a specific feedback module by ID (Admin only)
    """
    module = FeedbackModuleService.get_module_by_id(session=session, module_id=module_id)
    module_dict = FeedbackModuleResponse.model_validate(module).model_dump()

    return success_response(data=module_dict, message="Module retrieved successfully")


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED, summary="Create feedback module (Admin only)")
def create_module(
    data: FeedbackModuleCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Create a new feedback module (Admin only)

    - **name**: Module name (1-50 chars)
    - **parent_id**: Parent module ID (NULL for top-level modules)
    - **sort_order**: Sort order (default: 0)
    - **is_active**: Whether the module is active (default: true)

    Note: Only two levels of modules are supported (parent -> child)
    """
    module = FeedbackModuleService.create_module(session=session, data=data)
    module_dict = FeedbackModuleResponse.model_validate(module).model_dump()

    return success_response(data=module_dict, message="Module created successfully", code=201)


@router.put("/{module_id}", response_model=dict, summary="Update feedback module (Admin only)")
def update_module(
    module_id: int,
    data: FeedbackModuleUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Update a feedback module (Admin only)

    All fields are optional - only provided fields will be updated
    """
    module = FeedbackModuleService.update_module(session=session, module_id=module_id, data=data)
    module_dict = FeedbackModuleResponse.model_validate(module).model_dump()

    return success_response(data=module_dict, message="Module updated successfully")


@router.delete("/{module_id}", response_model=dict, summary="Delete feedback module (Admin only)")
def delete_module(
    module_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Delete a feedback module (Admin only)

    Note: Deleting a parent module will also delete all its children due to CASCADE
    """
    FeedbackModuleService.delete_module(session=session, module_id=module_id)

    return success_response(data=None, message="Module deleted successfully")


@router.put("/reorder/batch", response_model=dict, summary="Batch reorder feedback modules (Admin only)")
def reorder_modules(
    data: FeedbackModuleReorderRequest,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """
    Batch update module sort orders (Admin only)

    - **updates**: List of {id, sort_order} pairs
    """
    modules = FeedbackModuleService.reorder_modules(session=session, updates=data.updates)
    modules_dict = [FeedbackModuleResponse.model_validate(m).model_dump() for m in modules]

    return success_response(data=modules_dict, message="Modules reordered successfully")
