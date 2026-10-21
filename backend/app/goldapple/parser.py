from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.goldapple.errors import ParseError
from app.goldapple.url import product_url

IMAGE_SCREEN = "fullhd"
IMAGE_FORMAT = "webp"

@dataclass
class ProductData:
    item_id: str
    name: str | None = None
    brand: str | None = None
    image_url: str | None = None
    variant: str | None = None
    price: float | None = None
    old_price: float | None = None
    in_stock: bool = False
    rating: float | None = None
    reviews_count: int | None = None
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def discount_percent(self) -> int | None:
        if not self.price or not self.old_price or self.old_price <= self.price:
            return None
        return round((1 - self.price / self.old_price) * 100)

def _money(node: Any) -> float | None:
    if node is None:
        return None
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return float(node)
    if isinstance(node, str):
        cleaned = "".join(ch for ch in node if ch.isdigit() or ch in ".,")
        cleaned = cleaned.replace(",", ".").strip(".")
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
    if isinstance(node, dict):
        amount = node.get("amount")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            denominator = node.get("denominator") or 1
            try:
                return float(amount) / float(denominator)
            except (TypeError, ZeroDivisionError):
                return float(amount)
        for key in ("value", "price", "current"):
            if key in node:
                return _money(node[key])
    return None

def _walk(node: Any, depth: int = 0):
    if depth > 8:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for item in node[:40]:
            yield from _walk(item, depth + 1)

def _find_first(root: Any, keys: tuple[str, ...], caster) -> Any:
    for key, value in _walk(root):
        if key in keys:
            result = caster(value)
            if result is not None:
                return result
    return None

def _resolve_image(variant: dict[str, Any]) -> str | None:
    images = variant.get("imageUrls")
    if not isinstance(images, list) or not images:
        return None

    first = images[0]
    if isinstance(first, str):
        template = first
        formats: list[str] = []
        screens: list[str] = []
    elif isinstance(first, dict):
        template = first.get("url") or ""
        formats = first.get("format") or []
        screens = first.get("screen") or []
    else:
        return None

    if not template:
        return None

    fmt = IMAGE_FORMAT if IMAGE_FORMAT in formats else (formats[0] if formats else IMAGE_FORMAT)
    screen = IMAGE_SCREEN if IMAGE_SCREEN in screens else (screens[0] if screens else IMAGE_SCREEN)

    return template.replace("${screen}", screen).replace("${format}", fmt)

def _pick_variant(root: dict[str, Any], item_id: str) -> dict[str, Any]:
    variants = root.get("variants")
    if not isinstance(variants, list) or not variants:
        return {}

    for variant in variants:
        if isinstance(variant, dict) and str(variant.get("itemId")) == str(item_id):
            return variant
    first = variants[0]
    return first if isinstance(first, dict) else {}

def parse_product_card(payload: dict[str, Any], item_id: str) -> ProductData:
    if not isinstance(payload, dict):
        raise ParseError("ожидался объект JSON")

    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(root, dict):
        raise ParseError("не найден корневой объект карточки")

    variant = _pick_variant(root, item_id)

    name = root.get("name") or variant.get("name")
    brand = root.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    product_type = root.get("productType")
    if isinstance(product_type, str) and isinstance(name, str):
        if product_type.lower() not in name.lower():
            name = f"{product_type} {name}"

    price_block = variant.get("price") if isinstance(variant.get("price"), dict) else {}
    price = _money(price_block.get("actual"))
    if price is None:
        price = _find_first(root, ("actual",), _money)

    old_price = _money(price_block.get("old"))
    if old_price is None:
        regular = _money(price_block.get("regular"))
        if regular is not None and price is not None and regular > price:
            old_price = regular
    if old_price is not None and price is not None and old_price <= price:
        old_price = None

    in_stock = variant.get("inStock")
    if not isinstance(in_stock, bool):
        found = _find_first(
            root,
            ("inStock", "isAvailable", "available"),
            lambda v: v if isinstance(v, bool) else None,
        )
        in_stock = found if isinstance(found, bool) else price is not None

    units = None
    attributes = variant.get("attributesValue")
    if isinstance(attributes, dict):
        units = attributes.get("units") or None
        if units:
            units = f"{units} мл"

    url_value = variant.get("url") or root.get("url")
    if isinstance(url_value, str) and url_value.startswith("/"):
        url_value = "https://goldapple.ru" + url_value
    if not isinstance(url_value, str) or not url_value.startswith("http"):
        url_value = product_url(item_id)

    rating = _find_first(
        root,
        ("rating", "averageRating"),
        lambda v: _money(v) if isinstance(v, (int, float, str)) else None,
    )
    if rating is not None and (rating > 5 or rating < 0):
        rating = None

    reviews_count = _find_first(
        root,
        ("reviewsCount", "reviewCount", "totalReviews"),
        lambda v: int(v) if isinstance(v, int) and not isinstance(v, bool) else None,
    )

    data = ProductData(
        item_id=str(item_id),
        name=name if isinstance(name, str) else None,
        brand=brand if isinstance(brand, str) else None,
        image_url=_resolve_image(variant),
        variant=units,
        price=price,
        old_price=old_price,
        in_stock=bool(in_stock),
        rating=rating,
        reviews_count=reviews_count,
        url=url_value,
        raw=payload,
    )

    if data.name is None and data.price is None:
        raise ParseError(
            "не удалось найти ни название, ни цену - структура ответа изменилась"
        )
    return data
