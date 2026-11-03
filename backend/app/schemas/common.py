"""
Common schemas and response models
"""
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse


DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """
    Standard API response format

    Attributes:
        success: Operation success status
        code: HTTP status code
        message: Response message
        data: Response data payload
    """
    success: bool = Field(description="Operation success status")
    code: int = Field(description="HTTP status code")
    message: str = Field(description="Response message")
    data: Optional[DataT] = Field(default=None, description="Response data")

    class Config:
        from_attributes = True


class PaginationParams(BaseModel):
    """
    Pagination parameters

    Attributes:
        page: Page number (1-indexed)
        page_size: Items per page
    """
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel, Generic[DataT]):
    """
    Paginated response format

    Attributes:
        items: List of items for current page
        total: Total number of items
        page: Current page number
        page_size: Items per page
        total_pages: Total number of pages
    """
    items: list[DataT] = Field(description="Items for current page")
    total: int = Field(description="Total number of items")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total number of pages")

    class Config:
        from_attributes = True


def success_response(
    data: Any = None,
    message: str = "Success",
    code: int = 200
) -> dict:
    """
    Create a success response

    Args:
        data: Response data
        message: Success message
        code: HTTP status code

    Returns:
        Formatted success response dictionary
    """
    return {
        "success": True,
        "code": code,
        "message": message,
        "data": data
    }


def error_response(
    message: str = "Error",
    code: int = 400,
    data: Any = None
) -> JSONResponse:
    """
    Create an error response with correct HTTP status code

    Args:
        message: Error message
        code: HTTP status code
        data: Additional error data

    Returns:
        JSONResponse with matching HTTP status code
    """
    return JSONResponse(
        status_code=code,
        content={
            "success": False,
            "code": code,
            "message": message,
            "data": data
        }
    )
