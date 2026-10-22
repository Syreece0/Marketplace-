"""Validators shared by models and forms."""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image_file(file):
    """Validate size, extension and real content of a newly uploaded image.

    Files already stored (not newly uploaded) are skipped so editing a record
    does not re-validate unchanged images.
    """
    if getattr(file, "_committed", False):
        return

    max_bytes = settings.MAX_IMAGE_UPLOAD_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(
            _("Image is too large. The maximum size is %(mb)s MB."),
            code="image_too_large",
            params={"mb": settings.MAX_IMAGE_UPLOAD_MB},
        )

    extension = os.path.splitext(file.name)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            _("Unsupported image type. Please upload a JPG, PNG or WebP image."),
            code="invalid_image_extension",
        )

    raw = getattr(file, "file", file)
    try:
        raw.seek(0)
        with Image.open(raw) as img:
            image_format = img.format
            img.verify()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValidationError(
            _("The uploaded file is not a valid image."), code="invalid_image"
        )
    finally:
        try:
            raw.seek(0)
        except (OSError, ValueError):
            pass

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            _("Unsupported image format. Please upload a JPG, PNG or WebP image."),
            code="invalid_image_format",
        )
