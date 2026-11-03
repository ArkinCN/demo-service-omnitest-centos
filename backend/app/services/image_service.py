"""
Image processing service for avatar uploads
"""
import io
import os
import uuid
from pathlib import Path
from typing import Optional
from PIL import Image
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings

# Supported image formats
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Avatar processing settings
AVATAR_SIZE = (256, 256)
AVATAR_QUALITY = 85

# Feedback attachment settings
FEEDBACK_MAX_WIDTH = 1920
FEEDBACK_MAX_HEIGHT = 1920
FEEDBACK_QUALITY = 85
FEEDBACK_MAX_SIZE = 10 * 1024 * 1024  # 10MB


class ImageService:
    """Service for handling image uploads and processing"""

    def __init__(self):
        """Initialize image service"""
        self.upload_folder = Path(settings.UPLOAD_FOLDER)
        self.max_size = settings.MAX_AVATAR_SIZE

    def _ensure_upload_folder(self) -> None:
        """Ensure upload folder exists"""
        self.upload_folder.mkdir(parents=True, exist_ok=True)

    def _validate_file(self, file: UploadFile) -> None:
        """
        Validate uploaded file

        Args:
            file: Uploaded file

        Raises:
            HTTPException: If file is invalid
        """
        # Check file exists
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )

        # Check content type
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
            )

        # Check file extension
        if file.filename:
            ext = file.filename.lower().split('.')[-1]
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid file extension. Allowed extensions: {', '.join(ALLOWED_EXTENSIONS)}"
                )

    async def _read_and_validate_size(self, file: UploadFile) -> bytes:
        """
        Read file content and validate size

        Args:
            file: Uploaded file

        Returns:
            File content as bytes

        Raises:
            HTTPException: If file is too large
        """
        content = await file.read()

        if len(content) > self.max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_size / (1024 * 1024):.1f}MB"
            )

        return content

    def _process_image(self, content: bytes) -> Image.Image:
        """
        Process image: resize to 256x256 and compress

        Args:
            content: Image file content

        Returns:
            Processed PIL Image

        Raises:
            HTTPException: If image processing fails
        """
        try:
            # Open image
            image = Image.open(io.BytesIO(content))

            # Convert RGBA to RGB if necessary
            if image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # Resize to 256x256 (crop to square first)
            width, height = image.size
            if width != height:
                # Crop to square (center crop)
                min_dimension = min(width, height)
                left = (width - min_dimension) // 2
                top = (height - min_dimension) // 2
                right = left + min_dimension
                bottom = top + min_dimension
                image = image.crop((left, top, right, bottom))

            # Resize to target size
            image = image.resize(AVATAR_SIZE, Image.Resampling.LANCZOS)

            return image

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process image: {str(e)}"
            )

    def _save_image(self, image: Image.Image, user_id: int) -> str:
        """
        Save processed image to disk

        Args:
            image: Processed PIL Image
            user_id: User ID for filename

        Returns:
            Full URL to saved image
        """
        # Ensure upload folder exists
        self._ensure_upload_folder()

        # Generate unique filename
        filename = f"avatar_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
        file_path = self.upload_folder / filename

        # Save image
        image.save(file_path, 'JPEG', quality=AVATAR_QUALITY, optimize=True)

        # Return relative path (frontend will prepend backend base URL)
        return f"/uploads/avatars/{filename}"

    def delete_avatar(self, avatar_url: Optional[str]) -> None:
        """
        Delete avatar file from disk

        Args:
            avatar_url: Avatar URL to delete (e.g., "/uploads/avatars/avatar_1_abc123.jpg" or full URL)
        """
        if not avatar_url:
            return

        try:
            # Extract filename from URL (handle both relative and absolute URLs)
            if "/uploads/avatars/" in avatar_url:
                filename = avatar_url.split("/")[-1]
                file_path = self.upload_folder / filename

                # Delete file if exists
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()
        except Exception as e:
            # Log error but don't raise exception
            # Failed deletion shouldn't block the upload
            print(f"Warning: Failed to delete old avatar: {str(e)}")

    async def process_avatar(self, file: UploadFile, user_id: int, old_avatar_url: Optional[str] = None) -> str:
        """
        Process and save avatar upload

        Args:
            file: Uploaded file
            user_id: User ID
            old_avatar_url: Old avatar URL to delete (optional)

        Returns:
            New avatar URL

        Raises:
            HTTPException: If upload fails
        """
        # Validate file
        self._validate_file(file)

        # Read and validate size
        content = await self._read_and_validate_size(file)

        # Process image
        image = self._process_image(content)

        # Delete old avatar if exists
        if old_avatar_url:
            self.delete_avatar(old_avatar_url)

        # Save new image
        avatar_url = self._save_image(image, user_id)

        return avatar_url

    def _process_feedback_image(self, content: bytes) -> Image.Image:
        """
        Process feedback attachment: resize to max 1920x1920 while maintaining aspect ratio

        Args:
            content: Image file content

        Returns:
            Processed PIL Image

        Raises:
            HTTPException: If image processing fails
        """
        try:
            # Open image
            image = Image.open(io.BytesIO(content))

            # Convert RGBA to RGB if necessary
            if image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # Resize to max dimensions while maintaining aspect ratio
            width, height = image.size
            if width > FEEDBACK_MAX_WIDTH or height > FEEDBACK_MAX_HEIGHT:
                # Calculate scaling factor
                scale = min(FEEDBACK_MAX_WIDTH / width, FEEDBACK_MAX_HEIGHT / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            return image

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process image: {str(e)}"
            )

    def _save_feedback_image(self, image: Image.Image, feedback_id: int, index: int) -> str:
        """
        Save processed feedback image to disk

        Args:
            image: Processed PIL Image
            feedback_id: Feedback ID
            index: Attachment index

        Returns:
            Full URL to saved image
        """
        # Ensure upload folder exists (use parent of avatar folder + feedbacks)
        feedback_folder = self.upload_folder.parent / "feedbacks"
        feedback_folder.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        filename = f"feedback_{feedback_id}_{index}_{uuid.uuid4().hex[:8]}.jpg"
        file_path = feedback_folder / filename

        # Save image
        image.save(file_path, 'JPEG', quality=FEEDBACK_QUALITY, optimize=True)

        # Return full URL
        return f"https://aiproxy.example.internal/uploads/feedbacks/{filename}"

    def _save_feedback_gif(self, content: bytes, feedback_id: int, index: int) -> str:
        """
        Save GIF file directly without processing (to preserve animation)

        Args:
            content: GIF file content
            feedback_id: Feedback ID
            index: Attachment index

        Returns:
            Full URL to saved GIF
        """
        # Ensure upload folder exists
        feedback_folder = self.upload_folder.parent / "feedbacks"
        feedback_folder.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        filename = f"feedback_{feedback_id}_{index}_{uuid.uuid4().hex[:8]}.gif"
        file_path = feedback_folder / filename

        # Save GIF directly
        with open(file_path, 'wb') as f:
            f.write(content)

        # Return full URL
        return f"https://aiproxy.example.internal/uploads/feedbacks/{filename}"

    async def process_feedback_attachment(self, file: UploadFile, feedback_id: int, index: int) -> str:
        """
        Process and save feedback attachment

        Args:
            file: Uploaded file
            feedback_id: Feedback ID
            index: Attachment index (0-2)

        Returns:
            New attachment URL

        Raises:
            HTTPException: If upload fails
        """
        # Validate file
        self._validate_file(file)

        # Read and validate size (use FEEDBACK_MAX_SIZE)
        content = await file.read()
        if len(content) > FEEDBACK_MAX_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size: {FEEDBACK_MAX_SIZE / (1024 * 1024):.1f}MB"
            )

        # Check if it's a GIF - save directly without processing to preserve animation
        is_gif = file.content_type == "image/gif" or (file.filename and file.filename.lower().endswith('.gif'))
        if is_gif:
            return self._save_feedback_gif(content, feedback_id, index)

        # Process image (non-GIF)
        image = self._process_feedback_image(content)

        # Save image
        attachment_url = self._save_feedback_image(image, feedback_id, index)

        return attachment_url


# Global instance
image_service = ImageService()
