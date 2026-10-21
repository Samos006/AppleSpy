from __future__ import annotations

import asyncio
import logging
import signal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import settings
from app.db import session_scope
from app.goldapple.client import get_client
from app.services.checker import run_cycle
from app.services.notifier import Notifier

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

TICK_SECONDS = 60

async def main() -> None:
    stopping = asyncio.Event()

    def _stop(*_args: object) -> None:
        log.info("получен сигнал остановки")
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, _stop)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    notifier = Notifier(bot)
    client = get_client()

    log.info(
        "воркер запущен: интервал=%dс, пачка=%d, пауза=%.1fс",
        settings.check_interval,
        settings.check_batch_size,
        settings.check_delay_between,
    )

    try:
        while not stopping.is_set():
            try:
                async with session_scope() as session:
                    result = await run_cycle(session, client, notifier)
                if result["checked"]:
                    log.info(
                        "цикл завершён: проверено=%d, событий=%d",
                        result["checked"],
                        result["events"],
                    )
            except Exception:
                log.exception("цикл упал, продолжаю со следующего тика")

            try:
                await asyncio.wait_for(stopping.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                pass
    finally:
        await bot.session.close()
        log.info("воркер остановлен")

if __name__ == "__main__":
    asyncio.run(main())
