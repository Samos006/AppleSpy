from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.goldapple.parser import ProductData
from app.models import Event, PricePoint, Product, User, Watch

log = logging.getLogger(__name__)

def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(value, 2)))

async def get_or_create_user(
    session: AsyncSession,
    tg_id: int,
    username: str | None = None,
    first_name: str | None = None,
    language_code: str | None = None,
) -> User:
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if user is None:
        user = User(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        session.add(user)
        await session.flush()
        log.info("новый пользователь tg_id=%s", tg_id)
    else:
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        user.is_blocked = False
    return user

async def upsert_product(session: AsyncSession, data: ProductData) -> Product:
    product = await session.scalar(
        select(Product).where(Product.item_id == data.item_id)
    )
    if product is None:
        product = Product(item_id=data.item_id, url=data.url)
        session.add(product)

    product.url = data.url or product.url
    product.name = data.name or product.name
    product.brand = data.brand or product.brand
    product.image_url = data.image_url or product.image_url
    product.variant = data.variant or product.variant
    product.price = _dec(data.price)
    product.old_price = _dec(data.old_price)
    product.in_stock = data.in_stock
    product.rating = _dec(data.rating)
    product.reviews_count = data.reviews_count
    product.raw = data.raw
    product.last_checked_at = datetime.now(timezone.utc)
    product.last_success_at = product.last_checked_at
    product.last_error = None
    product.fail_count = 0

    await session.flush()
    return product

async def record_price_point(session: AsyncSession, product: Product) -> None:
    last = await session.scalar(
        select(PricePoint)
        .where(PricePoint.product_id == product.id)
        .order_by(PricePoint.captured_at.desc())
        .limit(1)
    )
    if (
        last is not None
        and last.price == product.price
        and last.old_price == product.old_price
        and last.in_stock == product.in_stock
    ):
        return

    session.add(
        PricePoint(
            product_id=product.id,
            price=product.price,
            old_price=product.old_price,
            in_stock=product.in_stock,
        )
    )

async def add_watch(
    session: AsyncSession, user: User, product: Product
) -> tuple[Watch, bool]:
    watch = await session.scalar(
        select(Watch).where(Watch.user_id == user.id, Watch.product_id == product.id)
    )
    if watch is not None:
        return watch, False

    watch = Watch(user_id=user.id, product_id=product.id)
    session.add(watch)
    await session.flush()
    return watch, True

async def remove_watch(session: AsyncSession, user: User, product_id: int) -> bool:
    result = await session.execute(
        delete(Watch).where(Watch.user_id == user.id, Watch.product_id == product_id)
    )
    return bool(result.rowcount)

async def list_watches(session: AsyncSession, user: User) -> list[Watch]:
    result = await session.scalars(
        select(Watch)
        .options(selectinload(Watch.product))
        .where(Watch.user_id == user.id)
        .order_by(Watch.created_at.desc())
    )
    return list(result)

async def get_watch(
    session: AsyncSession, user: User, product_id: int
) -> Watch | None:
    return await session.scalar(
        select(Watch)
        .options(selectinload(Watch.product))
        .where(Watch.user_id == user.id, Watch.product_id == product_id)
    )

async def price_history(
    session: AsyncSession, product_id: int, limit: int = 200
) -> list[PricePoint]:
    result = await session.scalars(
        select(PricePoint)
        .where(PricePoint.product_id == product_id)
        .order_by(PricePoint.captured_at.desc())
        .limit(limit)
    )
    return list(reversed(list(result)))

async def recent_events(
    session: AsyncSession, user: User, limit: int = 30
) -> list[Event]:
    result = await session.scalars(
        select(Event)
        .options(selectinload(Event.product))
        .join(Watch, Watch.product_id == Event.product_id)
        .where(Watch.user_id == user.id)
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    return list(result)

async def watchers_of(session: AsyncSession, product_id: int) -> list[Watch]:
    result = await session.scalars(
        select(Watch)
        .options(selectinload(Watch.user), selectinload(Watch.product))
        .where(Watch.product_id == product_id)
    )
    return list(result)

async def stats(session: AsyncSession) -> dict[str, int]:
    return {
        "users": await session.scalar(select(func.count(User.id))) or 0,
        "products": await session.scalar(select(func.count(Product.id))) or 0,
        "watches": await session.scalar(select(func.count(Watch.id))) or 0,
        "events": await session.scalar(select(func.count(Event.id))) or 0,
    }
