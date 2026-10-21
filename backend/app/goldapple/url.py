from __future__ import annotations

import re
from urllib.parse import urlparse

ITEM_ID_RE = re.compile(r"(?<!\d)(\d{6,20})(?:-|$)")
BARE_ID_RE = re.compile(r"^\d{6,20}$")

CANONICAL_HOSTS = {"goldapple.ru", "www.goldapple.ru", "goldapple.by", "goldapple.kz"}

def extract_item_id(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None

    if BARE_ID_RE.match(value):
        return value

    if "://" not in value:
        value = "https://" + value

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.netloc and parsed.netloc.lower() not in CANONICAL_HOSTS:
        return None

    for segment in parsed.path.split("/"):
        if not segment:
            continue
        match = ITEM_ID_RE.match(segment)
        if match:
            return match.group(1)
    return None

def product_url(item_id: str, slug: str | None = None) -> str:
    tail = f"-{slug}" if slug else ""
    return f"https://goldapple.ru/{item_id}{tail}"
