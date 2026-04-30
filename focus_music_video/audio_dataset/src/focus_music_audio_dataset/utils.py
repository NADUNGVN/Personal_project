from __future__ import annotations

import hashlib
import re


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return slug or "youtube_source"


def short_url_key(value: str) -> str:
    digest = hashlib.sha1(value.strip().encode("utf-8")).hexdigest()
    return digest[:10]
