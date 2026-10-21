from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config import settings
from app.db import session_scope
from app.goldapple.client import get_client
from app.goldapple.errors import BlockedError, NotFoundError, ParseError, TransientError
from app.goldapple.url import extract_item_id
from app.services import tracking
from app.services.notifier import money

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

dp = Dispatcher()

def webapp_url(product_id: int | None = None) -> str:
    base = settings.webapp_url.rstrip("/")
    return f"{base}/?product={product_id}" if product_id else base + "/"

def open_app_keyboard(product_id: int | None = None, ga_url: str | None = None):
    rows = [
        [
            InlineKeyboardButton(
                text="Открыть в приложении",
                web_app=WebAppInfo(url=webapp_url(product_id)),
            )
        ]
    ]
    if ga_url:
        rows.append([InlineKeyboardButton(text="Открыть в ЗЯ", url=ga_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Мои товары", web_app=WebAppInfo(url=webapp_url())
                )
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Пришлите ссылку на товар ЗЯ",
    )

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    async with session_scope() as session:
        await tracking.get_or_create_user(
            session,
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
            language_code=user.language_code,
        )

    await message.answer(
        "<b>AppleSpy</b> — слежу за ценами в Золотом Яблоке.\n\n"
        "Пришлите ссылку на товар, и я сообщу, когда цена изменится "
        "или товар вернётся в наличие.\n\n"
        "Вся история цен, графики и настройки — в приложении.",
        reply_markup=open_app_keyboard(),
    )
    await message.answer("Меню всегда под рукой:", reply_markup=main_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Как пользоваться:\n\n"
        "1. Скопируйте ссылку на товар в Золотом Яблоке\n"
        "2. Пришлите её сюда\n"
        "3. Я буду проверять цену и наличие и напишу при изменении\n\n"
        "Графики цен, минимумы, настройки уведомлений и целевая цена — "
        "всё в приложении.",
        reply_markup=open_app_keyboard(),
    )

@dp.message(Command("list"))
async def cmd_list(message: Message) -> None:
    if message.from_user is None:
        return
    async with session_scope() as session:
        user = await tracking.get_or_create_user(session, tg_id=message.from_user.id)
        watches = await tracking.list_watches(session, user)

    if not watches:
        await message.answer(
            "Вы пока ничего не отслеживаете. Пришлите ссылку на товар.",
            reply_markup=open_app_keyboard(),
        )
        return

    lines = [f"Отслеживается товаров: <b>{len(watches)}</b>\n"]
    for watch in watches[:10]:
        product = watch.product
        name = product.name or f"Товар {product.item_id}"
        status = money(product.price) if product.in_stock else "нет в наличии"
        lines.append(f"• {name[:60]} — {status}")
    if len(watches) > 10:
        lines.append(f"\n…и ещё {len(watches) - 10}")

    await message.answer("\n".join(lines), reply_markup=open_app_keyboard())

@dp.message(Command("diag"))
async def cmd_diag(message: Message) -> None:
    if message.from_user is None:
        return
    if message.from_user.id not in settings.admin_ids:
        return

    await message.answer("Проверяю доступ к Золотому Яблоку…")
    rows = await get_client().diagnose()
    lines = []
    for row in rows:
        mark = "✅" if row.get("ok") else "⛔"
        lines.append(f"{mark} <code>{row['proxy']}</code>")
        if row.get("ip"):
            lines.append(f"    {row['ip']} ({row.get('country')}) {row.get('org')}")
        lines.append(f"    {row.get('reason')}")
    await message.answer("\n".join(lines) or "Каналы не настроены")

@dp.message(F.text)
async def on_link(message: Message) -> None:
    if message.from_user is None or not message.text:
        return

    item_id = extract_item_id(message.text.strip())
    if not item_id:
        await message.answer(
            "Это не похоже на ссылку Золотого Яблока.\n\n"
            "Нужен адрес вида\n"
            "<code>https://goldapple.ru/19000116114-...</code>"
        )
        return

    notice = await message.answer("Смотрю карточку…")
    client = get_client()

    try:
        data = await client.get_product(item_id)
    except NotFoundError:
        await notice.edit_text("Такого товара в Золотом Яблоке нет.")
        return
    except BlockedError:
        await notice.edit_text(
            "Золотое Яблоко сейчас не отдаёт данные — сработала защита от ботов.\n"
            "Попробуйте через несколько минут."
        )
        return
    except (TransientError, ParseError) as exc:
        log.warning("не удалось получить %s: %s", item_id, exc)
        await notice.edit_text("Не получилось получить карточку. Попробуйте позже.")
        return

    async with session_scope() as session:
        user = await tracking.get_or_create_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        product = await tracking.upsert_product(session, data)
        await tracking.record_price_point(session, product)
        watch, created = await tracking.add_watch(session, user, product)
        product_id = product.id
        product_url = product.url

    head = "Добавил в отслеживание" if created else "Этот товар уже отслеживается"
    parts = [f"<b>{head}</b>", ""]
    if data.brand:
        parts.append(f"<b>{data.brand}</b>")
    parts.append(data.name or f"Товар {item_id}")
    parts.append("")
    if data.in_stock:
        line = f"Цена: <b>{money(data.price)}</b>"
        if data.old_price:
            line += f"  <s>{money(data.old_price)}</s>"
        parts.append(line)
    else:
        parts.append("Сейчас нет в наличии — сообщу, когда появится")

    await notice.edit_text(
        "\n".join(parts),
        reply_markup=open_app_keyboard(product_id, product_url),
        disable_web_page_preview=True,
    )

async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать"),
            BotCommand(command="list", description="Мои товары"),
            BotCommand(command="help", description="Как пользоваться"),
        ]
    )
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Приложение", web_app=WebAppInfo(url=webapp_url())
        )
    )

async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    await set_commands(bot)

    if settings.bot_mode == "webhook":
        log.info("режим webhook: %s", settings.webhook_url)
        await bot.set_webhook(
            settings.webhook_url,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
        )
        await asyncio.Event().wait()
    else:
        log.info("режим polling")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("бот остановлен")
