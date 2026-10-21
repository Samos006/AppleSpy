from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.services.tracking import get_or_create_user

log = logging.getLogger(__name__)

MAX_AGE_SECONDS = 86400

def _secret_key(token: str) -> bytes:
    return hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()

def verify_init_data(init_data: str, token: str) -> dict[str, Any]:
    if not init_data:
        raise ValueError("initData пустая")

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as exc:
        raise ValueError("initData не разбирается") from exc

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("в initData нет hash")

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    expected = hmac.new(
        _secret_key(token), check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise ValueError("подпись не совпала")

    auth_date = pairs.get("auth_date")
    if auth_date and auth_date.isdigit():
        if time.time() - int(auth_date) > MAX_AGE_SECONDS:
            raise ValueError("initData протухла")

    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("в initData нет пользователя")

    try:
        pairs["user"] = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("поле user не является JSON") from exc

    return pairs

async def current_user(
    authorization: str | None = Header(default=None),
    x_init_data: str | None = Header(default=None, alias="X-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> User:
    init_data = x_init_data
    if not init_data and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() in ("tma", "twa", "bearer"):
            init_data = value

    if not init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нет initData - откройте приложение через Telegram",
        )

    try:
        parsed = verify_init_data(init_data, settings.bot_token)
    except ValueError as exc:
        log.warning("отклонена initData: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    tg_user = parsed["user"]
    user = await get_or_create_user(
        session,
        tg_id=int(tg_user["id"]),
        username=tg_user.get("username"),
        first_name=tg_user.get("first_name"),
        language_code=tg_user.get("language_code"),
    )
    await session.commit()
    return user
