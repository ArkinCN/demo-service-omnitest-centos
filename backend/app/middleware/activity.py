"""
Activity middleware - Update user last_active_at on API requests
"""
from app.core.security import decode_token
from app.services.user_service import UserService
from app.core.logger import logger


def update_user_activity(auth_header: str | None) -> None:
    """
    Update user's last_active_at based on Authorization header.

    This function is called from the request logging middleware
    after a successful response. It extracts the user_id from
    the JWT token and updates the last_active_at timestamp.

    The actual update is throttled (60s per user) in UserService.

    Args:
        auth_header: Authorization header value (e.g., "Bearer xxx")
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return

    try:
        token = auth_header.replace("Bearer ", "")
        payload = decode_token(token)

        if payload.get("type") != "access":
            return

        user_id = payload.get("user_id")
        if user_id:
            UserService.update_last_active(user_id)
    except Exception as e:
        # Silently ignore errors - this is a best-effort update
        # Token validation errors are handled by the actual auth flow
        logger.debug(f"Activity update skipped: {e}")
