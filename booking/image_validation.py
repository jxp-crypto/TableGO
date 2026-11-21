from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_SIZE = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def inspect_restaurant_image(upload):
    if upload.size > MAX_IMAGE_SIZE:
        raise ValidationError("Restaurant images must be 5 MB or smaller.")
    try:
        with Image.open(upload) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError("Upload a valid JPG, PNG, or WEBP image.") from exc
    if image_format not in IMAGE_EXTENSIONS:
        raise ValidationError("Upload a JPG, PNG, or WEBP image.")
    if width > 6000 or height > 6000 or width * height > 20_000_000:
        raise ValidationError("Image dimensions must not exceed 20 megapixels.")
    upload.seek(0)
    return IMAGE_EXTENSIONS[image_format]


def validate_restaurant_image(upload):
    inspect_restaurant_image(upload)
