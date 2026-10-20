import base64
import hashlib
import io
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException

Image.MAX_IMAGE_PIXELS = 20000000


def decode_image(data):
    try:
        header, encoded = data.split(",", 1)
        if header not in [
            "data:image/png;base64",
            "data:image/jpeg;base64",
            "data:image/webp;base64",
        ]:
            raise ValueError("Use PNG, JPEG or WebP")
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise ValueError("Image must be at most 10 MB")
        with Image.open(io.BytesIO(raw)) as source:
            if (
                source.format not in ["PNG", "JPEG", "WEBP"]
                or source.width * source.height > 20000000
            ):
                raise ValueError("Unsupported image or too many pixels (20 MP limit)")
            expected_mime = {
                "PNG": "image/png",
                "JPEG": "image/jpeg",
                "WEBP": "image/webp",
            }[source.format]
            if header.split(";")[0][5:] != expected_mime:
                raise ValueError("Image MIME type does not match decoded bytes")
            source.load()
            image = source.convert("RGB")
        return raw, image, header.split(";")[0][5:]
    except (
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(422, f"Invalid artwork: {exc}") from exc


def store_image(root: Path, data):
    raw, image, mime = decode_image(data)
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "artwork"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / digest
    if not path.exists():
        import os, tempfile

        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as temporary:
            temporary.write(raw)
            name = temporary.name
        os.replace(name, path)
    return dict(
        id=digest,
        path=f"artwork/{digest}",
        mime=mime,
        width=image.width,
        height=image.height,
    )
