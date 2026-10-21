from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_session
from app.goldapple.client import get_client
from app.goldapple.errors import BlockedError, NotFoundError, ParseError, TransientError
from app.goldapple.url import extract_item_id
from app.models import PricePoint, Product, User, Watch
from app.schemas import (
    AddWatchIn,
    EventOut,
    MeOut,
    PricePointOut,
    ProductOut,
    UpdateWatchIn,
    WatchDetailOut,
    WatchOut,
)
from app.services import checker, tracking

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

def _product_out(product: Product, extremes: tuple[float | None, float | None] = (None, None)) -> ProductOut:
    out = ProductOut.model_validate(product)
    price = float(product.price) if product.price is not None else None
    old = float(product.old_price) if product.old_price is not None else None
    if price and old and old > price:
        out.discount_percent = round((1 - price / old) * 100)
    out.min_price, out.max_price = extremes
    return out

async def _extremes(session: AsyncSession, product_id: int):
    row = (
        await session.execute(
            select(func.min(PricePoint.price), func.max(PricePoint.price)).where(
                PricePoint.product_id == product_id,
                PricePoint.price.is_not(None),
            )
        )
    ).one()
    low, high = row
    return (float(low) if low is not None else None, float(high) if high is not None else None)

def _watch_out(watch: Watch, product_out: ProductOut) -> WatchOut:
    return WatchOut(
        id=watch.id,
        product=product_out,
        notify_price_drop=watch.notify_price_drop,
        notify_price_rise=watch.notify_price_rise,
        notify_back_in_stock=watch.notify_back_in_stock,
        target_price=float(watch.target_price) if watch.target_price is not None else None,
        created_at=watch.created_at,
    )

@router.get("/me", response_model=MeOut)
async def me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    count = await session.scalar(
        select(func.count(Watch.id)).where(Watch.user_id == user.id)
    )
    return MeOut(
        tg_id=user.tg_id,
        first_name=user.first_name,
        username=user.username,
        watches_count=count or 0,
    )

@router.get("/watches", response_model=list[WatchOut])
async def list_watches(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WatchOut]:
    watches = await tracking.list_watches(session, user)
    result = []
    for watch in watches:
        extremes = await _extremes(session, watch.product_id)
        result.append(_watch_out(watch, _product_out(watch.product, extremes)))
    return result

@router.post(
    "/watches", response_model=WatchDetailOut, status_code=status.HTTP_201_CREATED
)
async def add_watch(
    payload: AddWatchIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchDetailOut:
    item_id = extract_item_id(payload.url)
    if not item_id:
        raise HTTPException(
            status_code=422,
            detail="Не похоже на ссылку Золотого Яблока. "
            "Скопируйте адрес страницы товара целиком.",
        )

    existing = await session.scalar(select(Product).where(Product.item_id == item_id))

    client = get_client()
    try:
        data = await client.get_product(item_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Товар не найден в Золотом Яблоке")
    except BlockedError as exc:
        if existing is None:
            raise HTTPException(
                status_code=503,
                detail="Золотое Яблоко сейчас не отдаёт данные. Попробуйте позже.",
            ) from exc
        product = existing
    except (TransientError, ParseError) as exc:
        if existing is None:
            raise HTTPException(
                status_code=503, detail="Не удалось получить карточку товара"
            ) from exc
        product = existing
    else:
        product = await tracking.upsert_product(session, data)
        await tracking.record_price_point(session, product)

    watch, _created = await tracking.add_watch(session, user, product)
    await session.commit()

    history = await tracking.price_history(session, product.id)
    extremes = await _extremes(session, product.id)
    base = _watch_out(watch, _product_out(product, extremes))
    return WatchDetailOut(
        **base.model_dump(),
        history=[PricePointOut.model_validate(p) for p in history],
    )

@router.get("/watches/{product_id}", response_model=WatchDetailOut)
async def watch_detail(
    product_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchDetailOut:
    watch = await tracking.get_watch(session, user, product_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Вы не отслеживаете этот товар")

    history = await tracking.price_history(session, product_id)
    extremes = await _extremes(session, product_id)
    base = _watch_out(watch, _product_out(watch.product, extremes))
    return WatchDetailOut(
        **base.model_dump(),
        history=[PricePointOut.model_validate(p) for p in history],
    )

@router.patch("/watches/{product_id}", response_model=WatchOut)
async def update_watch(
    product_id: int,
    payload: UpdateWatchIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchOut:
    watch = await tracking.get_watch(session, user, product_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Вы не отслеживаете этот товар")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(watch, field, value)
    await session.commit()

    extremes = await _extremes(session, product_id)
    return _watch_out(watch, _product_out(watch.product, extremes))

@router.delete(
    "/watches/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_watch(
    product_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    removed = await tracking.remove_watch(session, user, product_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Вы не отслеживаете этот товар")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/watches/{product_id}/refresh", response_model=WatchDetailOut)
async def refresh_watch(
    product_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchDetailOut:
    watch = await tracking.get_watch(session, user, product_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Вы не отслеживаете этот товар")

    await checker.refresh_now(session, watch.product)
    await session.refresh(watch.product)

    history = await tracking.price_history(session, product_id)
    extremes = await _extremes(session, product_id)
    base = _watch_out(watch, _product_out(watch.product, extremes))
    return WatchDetailOut(
        **base.model_dump(),
        history=[PricePointOut.model_validate(p) for p in history],
    )

@router.get("/events", response_model=list[EventOut])
async def events(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EventOut]:
    rows = await tracking.recent_events(session, user)
    return [
        EventOut(
            id=e.id,
            kind=e.kind,
            old_value=float(e.old_value) if e.old_value is not None else None,
            new_value=float(e.new_value) if e.new_value is not None else None,
            created_at=e.created_at,
            product=_product_out(e.product),
        )
        for e in rows
    ]

@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    await session.execute(select(1))
    return {"status": "ok"}

@router.get("/diag")
async def diag(user: User = Depends(current_user)) -> dict[str, object]:
    from app.config import settings

    if user.tg_id not in settings.admin_ids:
        raise HTTPException(status_code=403, detail="Только для администратора")
    return {"channels": await get_client().diagnose()}
