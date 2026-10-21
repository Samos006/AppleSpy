from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

class PricePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: float | None
    old_price: float | None
    in_stock: bool
    captured_at: datetime

class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: str
    url: str
    name: str | None
    brand: str | None
    image_url: str | None
    variant: str | None
    price: float | None
    old_price: float | None
    in_stock: bool
    rating: float | None
    reviews_count: int | None
    last_checked_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None

    discount_percent: int | None = None
    min_price: float | None = None
    max_price: float | None = None

class WatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: ProductOut
    notify_price_drop: bool
    notify_price_rise: bool
    notify_back_in_stock: bool
    target_price: float | None
    created_at: datetime

class WatchDetailOut(WatchOut):
    history: list[PricePointOut] = Field(default_factory=list)

class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    old_value: float | None
    new_value: float | None
    created_at: datetime
    product: ProductOut

class AddWatchIn(BaseModel):
    url: str = Field(description="Ссылка на товар ЗЯ или голый itemId")

class UpdateWatchIn(BaseModel):
    notify_price_drop: bool | None = None
    notify_price_rise: bool | None = None
    notify_back_in_stock: bool | None = None
    target_price: float | None = None

class MeOut(BaseModel):
    tg_id: int
    first_name: str | None
    username: str | None
    watches_count: int

class ErrorOut(BaseModel):
    detail: str
