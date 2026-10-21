from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.goldapple.errors import BlockedError, NotFoundError, TransientError
from app.goldapple.fingerprint import USER_AGENT

try:
    import fcntl
except ImportError:
    fcntl = None

log = logging.getLogger(__name__)

BASE = "https://goldapple.ru"

ALLOWED_HOSTS = ("goldapple.ru", "id.facct.ru", "facct.ru")
BLOCKED_RESOURCES = ("image", "media", "font", "stylesheet")

CLEARANCE_COOKIE = "cfidsw-goldapple"

HOST_LOCK_PATH = "/tmp/applespy-browser.lock"
HOST_LOCK_TIMEOUT = 120.0

FETCH_JS = """async (url) => {
    const r = await fetch(url, {
        credentials: 'include',
        headers: {'Accept': 'application/json, text/plain, */*'}
    });
    return {status: r.status, body: await r.text()};
}"""

def _card_path(item_id: str, city_id: str, region_id: str) -> str:
    return (
        "/front/api/catalog/product-card/base/v3"
        f"?locale=ru&cityId={city_id}&regionId={region_id}&itemId={item_id}"
    )

def _is_allowed(url: str) -> bool:
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)

class BrowserSession:
    REAP_INTERVAL = 30

    def __init__(
        self,
        city_id: str,
        region_id: str | None = None,
        ttl: int = 3600,
        idle: int = 180,
    ) -> None:
        self.city_id = city_id
        self.region_id = region_id or city_id
        self.ttl = ttl
        self.idle = idle
        self._last_use: float = 0.0
        self._reaper: asyncio.Task[None] | None = None
        self._host_lock: Any = None
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._ready_at: float = 0.0

    @property
    def _fresh(self) -> bool:
        if self._page is None:
            return False
        now = time.time()
        if now - self._ready_at >= self.ttl:
            return False
        return now - self._last_use < self.idle

    async def fetch_card(self, item_id: str, attempts: int = 3) -> dict[str, Any]:
        async with self._lock:
            last: Exception | None = None
            forgiven_once = False

            for attempt in range(attempts):
                if not self._fresh:
                    await self._open()
                self._last_use = time.time()

                try:
                    return await self._request(item_id)
                except NotFoundError:
                    raise
                except BlockedError as exc:
                    last = exc
                    if not forgiven_once:
                        forgiven_once = True
                        log.info("получен 403, жду и повторяю в той же сессии")
                        await asyncio.sleep(4.0)
                        continue
                    log.warning(
                        "сессия отвергнута (%s), пересоздаю: попытка %d",
                        exc.reason,
                        attempt + 1,
                    )
                    await self._close()
                except TransientError as exc:
                    last = exc
                    log.warning("сбой запроса: %s", exc)

                if attempt < attempts - 1:
                    await asyncio.sleep(2.0 * (attempt + 1))

            raise last or TransientError("не удалось получить карточку")

    async def _request(self, item_id: str) -> dict[str, Any]:
        assert self._page is not None
        path = _card_path(item_id, self.city_id, self.region_id)

        raw = None
        for attempt in range(3):
            try:
                raw = await self._page.evaluate(FETCH_JS, path)
                break
            except Exception as exc:
                if attempt == 2:
                    raise TransientError(f"вкладка не отвечает: {exc!r}") from exc
                await asyncio.sleep(2.0)

        if raw is None:
            raise TransientError("вкладка не вернула ответ")

        status = raw.get("status")
        body = raw.get("body") or ""

        if status == 404:
            raise NotFoundError(f"товар {item_id} не найден")
        if status == 403:
            raise BlockedError("клиренс сессии больше не принимается")
        if status != 200:
            raise TransientError(f"неожиданный статус {status}")

        try:
            return json.loads(body)
        except ValueError as exc:
            raise TransientError(f"ответ не JSON: {body[:200]!r}") from exc

    async def _probe(self, item_id: str) -> int | None:
        assert self._page is not None
        try:
            return await self._page.evaluate(
                "async u => (await fetch(u, {credentials:'include'})).status",
                _card_path(item_id, self.city_id, self.region_id),
            )
        except Exception:
            return None

    async def _acquire_host_lock(self) -> None:
        if fcntl is None:
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + HOST_LOCK_TIMEOUT

        while loop.time() < deadline:
            try:
                handle = open(HOST_LOCK_PATH, "a+b")
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                try:
                    handle.close()
                except Exception:
                    pass
                await asyncio.sleep(2.0)
                continue
            self._host_lock = handle
            return

        raise TransientError(
            "браузер занят другим процессом дольше "
            f"{HOST_LOCK_TIMEOUT:.0f}с — попробую в следующем цикле"
        )

    def _release_host_lock(self) -> None:
        if self._host_lock is None or fcntl is None:
            self._host_lock = None
            return
        try:
            fcntl.flock(self._host_lock, fcntl.LOCK_UN)
            self._host_lock.close()
        except Exception:
            log.debug("не удалось снять файловый замок")
        self._host_lock = None

    async def _open(self) -> None:
        await self._close()
        await self._acquire_host_lock()

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BlockedError(
                "нужен браузер, но playwright не установлен "
                "(pip install -r requirements-browser.txt && "
                "playwright install chromium)"
            ) from exc

        started = time.time()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-features=site-per-process,IsolateOrigins",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=160",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1024, "height": 720},
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
        )
        await self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        page = await self._context.new_page()

        async def gate(route):
            request = route.request
            if request.resource_type in BLOCKED_RESOURCES or not _is_allowed(
                request.url
            ):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", gate)

        probe_item = "19000116114"
        try:
            await page.goto(
                f"{BASE}/{probe_item}-", wait_until="commit", timeout=45000
            )
        except Exception as exc:
            await self._close()
            raise BlockedError(f"страница не открылась: {exc!r}") from exc

        self._page = page

        confirmations = 0
        cleared = False
        deadline = time.time() + 120

        while time.time() < deadline:
            await asyncio.sleep(1.5)
            names = {c["name"] for c in await self._context.cookies()}
            if CLEARANCE_COOKIE not in names:
                confirmations = 0
                continue

            if await self._probe(probe_item) != 200:
                confirmations = 0
                continue

            confirmations += 1
            if confirmations >= 2:
                cleared = True
                break
            await asyncio.sleep(2.5)

        if not cleared:
            self._page = None
            await self._close()
            raise BlockedError("device-check не пройден")

        self._ready_at = time.time()
        self._last_use = self._ready_at
        self._start_reaper()
        log.info("браузерная сессия готова за %.0fс", time.time() - started)

    def _start_reaper(self) -> None:
        if self._reaper is not None and not self._reaper.done():
            return
        self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.REAP_INTERVAL)
                if self._page is None:
                    return
                if time.time() - self._last_use < self.idle:
                    continue
                async with self._lock:
                    if self._page is not None and (
                        time.time() - self._last_use >= self.idle
                    ):
                        log.info("браузер простаивал, закрываю ради памяти")
                        await self._close()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("сторож браузера упал")

    async def _close(self) -> None:
        if self._reaper is not None and self._reaper is not asyncio.current_task():
            self._reaper.cancel()
            self._reaper = None

        for obj, name in (
            (self._context, "context"),
            (self._browser, "browser"),
        ):
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    log.debug("не удалось закрыть %s", name)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                log.debug("не удалось остановить playwright")

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._ready_at = 0.0
        self._release_host_lock()

    async def aclose(self) -> None:
        async with self._lock:
            await self._close()
