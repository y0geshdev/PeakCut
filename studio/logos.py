"""Uploaded clip logos, kept privately with each user's data."""
import io
import re
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, ctx


MAX_BYTES = 5 * 1024 * 1024
DEFAULTS = {"width": 15, "x": 96, "y": 4}


def path(lid: str) -> Path:
    if not isinstance(lid, str) or not re.fullmatch(r"[a-f0-9]{32}", lid):
        raise ValueError("Choose an uploaded logo.")
    return config.user_dir(ctx.uid()) / "logos" / f"{lid}.png"


def clean(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Logo settings must include an uploaded image, size and position.")
    lid = value.get("id")
    if not path(lid).is_file():
        raise ValueError("That logo isn't available. Upload it again.")
    out = {"id": lid}
    for key, default in DEFAULTS.items():
        number = value.get(key, default)
        low, high = (1, 100) if key == "width" else (0, 100)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not low <= number <= high:
            raise ValueError(f"Logo {key} must be a number from {low} to {high}.")
        out[key] = round(number, 2)
    with Image.open(path(lid)) as image:
        width = max(1, round(config.OUT_W * out["width"] / 100))
        if round(width * image.height / image.width) > config.OUT_H:
            raise ValueError("That logo is too tall at this size. Choose a smaller width.")
    return out


def upload(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("The logo must be 5 MB or smaller.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Use a still PNG, JPEG or WebP image for the logo.")
            if max(image.size) > 4096 or image.width * image.height > 16_000_000:
                raise ValueError("The logo must be no larger than 4096 pixels on either side.")
            image.load()
            normalized = ImageOps.exif_transpose(image).convert("RGBA")
            normalized.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Couldn't read that logo. Use a PNG, JPEG or WebP image.") from error
    lid = uuid.uuid4().hex
    target = path(lid)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output:
        normalized.save(output, format="PNG")
    ctx.bump()
    return {"id": lid, **DEFAULTS}


def prepare(value: dict, work: Path) -> tuple[int, int, int, int]:
    """Copy into the short render folder, and keep the whole logo inside the finished frame."""
    value = clean(value)
    if value is None:
        raise ValueError("Choose an uploaded logo.")
    with Image.open(path(value["id"])) as image:
        width = max(1, round(config.OUT_W * value["width"] / 100))
        height = max(1, round(width * image.height / image.width))
        image.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS).save(work / "logo.png")
    x = round((config.OUT_W - width) * value["x"] / 100)
    y = round((config.OUT_H - height) * value["y"] / 100)
    return width, height, x, y
