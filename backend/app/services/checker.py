from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.goldapple.client import GoldAppleClient, get_client
from app.goldapple.errors import BlockedError, NotFoundError, ParseError, TransientError
from app.models import Event, Product, Watch
from app.services import tracking
from app.services.notifier import Notifier

log = logging.getLogger(__name__)

def _to_float(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)

async def due_products(session: AsyncSession, limit: int) -> list[Product]:
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=settings.check_interval)

    result = await session.scalars(
        select(Product)
        .join(Watch, Watch.product_id == Product.id)
        .where(
            or_(
                Product.last_checked_at.is_(None),
                Product.last_checked_at < threshold,
            )
        )
        .group_by(Product.id)
        .order_by(Product.last_checked_at.asc().nulls_first())
        .limit(limit)
    )
    products = list(result)

    ready: list[Product] = []
    for product in products:
        if product.fail_count and product.last_checked_at:
            backoff = min(2**product.fail_count, 32) * settings.check_interval
            if product.last_checked_at > now - timedelta(seconds=backoff):
                continue
        ready.append(product)
    return ready

def confirm_stock(product: Product, observed: bool) -> bool:
    if observed == product.in_stock:
        product.pending_in_stock = None
        product.pending_count = 0
        return product.in_stock

    if product.pending_in_stock == observed:
        product.pending_count += 1
    else:
        product.pending_in_stock = observed
        product.pending_count = 1

    if product.pending_count >= settings.stock_confirmations:
        product.pending_in_stock = None
        product.pending_count = 0
        return observed

    log.info(
        "наличие %s: %s -> %s пока не подтверждено (%d из %d)",
        product.item_id,
        product.in_stock,
        observed,
        product.pending_count,
        settings.stock_confirmations,
    )
    return product.in_stock

async def recently_notified(
    session: AsyncSession, product_id: int, kind: str
) -> bool:
    since = datetime.now(timezone.utc) - timedelta(seconds=settings.notify_cooldown)
    found = await session.scalar(
        select(Event.id)
        .where(
            Event.product_id == product_id,
            Event.kind == kind,
            Event.created_at >= since,
        )
        .order_by(Event.created_at.desc())
        .offset(1)
        .limit(1)
    )
    return found is not None

def diff_events(
    product: Product,
    old_price: float | None,
    old_in_stock: bool,
) -> list[Event]:
    events: list[Event] = []
    new_price = _to_float(product.price)

    if old_in_stock and not product.in_stock:
        events.append(Event(product_id=product.id, kind="out_of_stock"))
    elif not old_in_stock and product.in_stock:
        events.append(
            Event(
                product_id=product.id,
                kind="back_in_stock",
                new_value=product.price,
            )
        )

    if old_price is not None and new_price is not None and old_price != new_price:
        kind = "price_drop" if new_price < old_price else "price_rise"
        events.append(
            Event(
                product_id=product.id,
                kind=kind,
                old_value=Decimal(str(old_price)),
                new_value=product.price,
            )
        )

    return events

def wants(watch: Watch, event: Event, new_price: float | None) -> bool:
    if event.kind == "price_drop":
        if watch.target_price is not None and new_price is not None:
            return new_price <= float(watch.target_price)
        return watch.notify_price_drop
    if event.kind == "price_rise":
        return watch.notify_price_rise
    if event.kind == "back_in_stock":
        return watch.notify_back_in_stock
    if event.kind == "out_of_stock":
        return False
    return True

async def check_product(
    session: AsyncSession,
    client: GoldAppleClient,
    product: Product,
    notifier: Notifier | None = None,
) -> list[Event]:
    old_price = _to_float(product.price)
    old_in_stock = product.in_stock

    try:
        data = await client.get_product(product.item_id)
    except NotFoundError as exc:
        product.last_checked_at = datetime.now(timezone.utc)
        product.last_error = f"товар не найден: {exc}"
        product.fail_count += 1
        return []
    except (BlockedError, TransientError, ParseError) as exc:
        product.last_checked_at = datetime.now(timezone.utc)
        product.last_error = f"{type(exc).__name__}: {exc}"
        product.fail_count += 1
        log.warning("проверка %s не удалась: %s", product.item_id, exc)
        return []

    data.in_stock = confirm_stock(product, data.in_stock)

    await tracking.upsert_product(session, data)
    await tracking.record_price_point(session, product)

    events = diff_events(product, old_price, old_in_stock)
    for event in events:
        session.add(event)
    if not events:
        return []

    await session.flush()

    if notifier is not None:
        await dispatch(session, notifier, product, events)
    return events

async def dispatch(
    session: AsyncSession,
    notifier: Notifier,
    product: Product,
    events: list[Event],
) -> None:
    watches = await tracking.watchers_of(session, product.id)
    new_price = _to_float(product.price)

    for event in events:
        if await recently_notified(session, product.id, event.kind):
            log.info(
                "событие %s по %s уже приходило недавно, не дублирую",
                event.kind,
                product.item_id,
            )
            continue
        for watch in watches:
            if watch.user.is_blocked or not wants(watch, event, new_price):
                continue
            alive = await notifier.send_event(watch.user.tg_id, event, product)
            if not alive:
                watch.user.is_blocked = True
            await asyncio.sleep(0.05)

async def run_cycle(
    session: AsyncSession,
    client: GoldAppleClient,
    notifier: Notifier | None = None,
) -> dict[str, int]:
    products = await due_products(session, settings.check_batch_size)
    if not products:
        return {"checked": 0, "events": 0}

    log.info("цикл: %d товаров к проверке", len(products))
    total_events = 0

    for index, product in enumerate(products):
        events = await check_product(session, client, product, notifier)
        total_events += len(events)
        await session.commit()

        if index < len(products) - 1:
            delay = settings.check_delay_between * random.uniform(0.7, 1.4)
            await asyncio.sleep(delay)

    return {"checked": len(products), "events": total_events}

async def refresh_now(
    session: AsyncSession, product: Product, client: GoldAppleClient | None = None
) -> Product:
    client = client or get_client()
    await check_product(session, client, product, notifier=None)
    await session.commit()
    return product
