from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings
from app.models import Event, Product

log = logging.getLogger(__name__)

KIND_TITLES = {
    "price_drop": "Цена снизилась",
    "price_rise": "Цена выросла",
    "back_in_stock": "Снова в наличии",
    "out_of_stock": "Товар закончился",
    "target_reached": "Цель по цене достигнута",
}

KIND_ICONS = {
    "price_drop": "\U0001f4c9",
    "price_rise": "\U0001f4c8",
    "back_in_stock": "✅",
    "out_of_stock": "⚠️",
    "target_reached": "\U0001f3af",
}

def money(value) -> str:
    if value is None:
        return "—"
    number = f"{float(value):,.0f}".replace(",", " ")
    return f"{number} ₽"

def escape(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def build_keyboard(product: Product) -> InlineKeyboardMarkup:
    webapp_link = f"{settings.webapp_url.rstrip('/')}/?product={product.id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть в приложении",
                    web_app=WebAppInfo(url=webapp_link),
                )
            ],
            [InlineKeyboardButton(text="Открыть в ЗЯ", url=product.url)],
        ]
    )

def render_event(event: Event, product: Product) -> str:
    icon = KIND_ICONS.get(event.kind, "\U0001f514")
    title = KIND_TITLES.get(event.kind, "Изменение")

    lines = [f"{icon} <b>{title}</b>", ""]

    name = escape(product.name) or f"Товар {product.item_id}"
    if product.brand:
        lines.append(f"<b>{escape(product.brand)}</b>")
    lines.append(name)
    lines.append("")

    if event.kind in ("price_drop", "price_rise", "target_reached"):
        old = money(event.old_value)
        new = money(event.new_value)
        lines.append(f"<s>{old}</s> → <b>{new}</b>")
        if event.old_value and event.new_value:
            delta = float(event.old_value) - float(event.new_value)
            percent = abs(delta) / float(event.old_value) * 100
            sign = "−" if delta > 0 else "+"
            lines.append(
                f"{sign}{money(abs(delta))} ({percent:.0f}%)"
            )
    elif event.kind == "back_in_stock":
        lines.append(f"Цена: <b>{money(product.price)}</b>")
    elif event.kind == "out_of_stock":
        lines.append("Товар пропал из наличия")

    return "\n".join(lines)

class Notifier:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_event(self, tg_id: int, event: Event, product: Product) -> bool:
        text = render_event(event, product)
        try:
            await self.bot.send_message(
                chat_id=tg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=build_keyboard(product),
                disable_web_page_preview=True,
            )
        except TelegramForbiddenError:
            log.info("пользователь %s заблокировал бота", tg_id)
            return False
        except TelegramRetryAfter as exc:
            log.warning("флуд-контроль, ждём %s c", exc.retry_after)
            return True
        except Exception:
            log.exception("не удалось отправить уведомление %s", tg_id)
            return True
        return True
