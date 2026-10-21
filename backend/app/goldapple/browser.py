from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.goldapple.errors import BlockedError
from app.goldapple.fingerprint import USER_AGENT

log = logging.getLogger(__name__)

CHALLENGE_TITLE = "checking device"

CLEARANCE_COOKIES = ("cfidsw-goldapple",)

PROBE_ENDPOINT = (
    "/front/api/catalog/product-card/base/v3"
    "?locale=ru&cityId={city}&regionId={city}&itemId={item}"
)
MOSCOW_CITY_ID = "0c5b2444-70a0-4932-980c-b4dc0d3f02b5"

ALLOWED_HOSTS = ("goldapple.ru", "id.facct.ru", "facct.ru")

BLOCKED_RESOURCES = ("image", "media", "font", "stylesheet")

DEFAULT_UA = USER_AGENT

@dataclass
class BrowserProxy:
    server: str
    username: str | None = None
    password: str | None = None

    def as_playwright(self) -> dict[str, str]:
        out = {"server": self.server}
        if self.username:
            out["username"] = self.username
        if self.password:
            out["password"] = self.password
        return out

def to_browser_proxy(proxy_url: str | None) -> BrowserProxy | None:
    if not proxy_url:
        return None

    parts = urlsplit(proxy_url)
    if not parts.hostname:
        return None

    if parts.scheme.startswith("socks") and (parts.username or parts.password):
        log.debug(
            "browser: %s — SOCKS5 с авторизацией Chromium не поддерживает, "
            "использую HTTP на том же порту",
            parts.hostname,
        )

    port = f":{parts.port}" if parts.port else ""
    return BrowserProxy(
        server=f"http://{parts.hostname}{port}",
        username=parts.username,
        password=parts.password,
    )

def _is_allowed(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)

async def solve_challenge(
    item_id: str,
    proxy_url: str | None = None,
    user_agent: str = DEFAULT_UA,
    timeout_seconds: float = 60.0,
) -> dict[str, str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BlockedError(
            "нужен браузерный обход, но playwright не установлен "
            "(pip install -r requirements-browser.txt && playwright install chromium)"
        ) from exc

    proxy = to_browser_proxy(proxy_url)
    url = f"https://goldapple.ru/{item_id}-"
    transferred = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            proxy=proxy.as_playwright() if proxy else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            context = await browser.new_context(
                user_agent=user_agent,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                viewport={"width": 1280, "height": 900},
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
            )
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            page = await context.new_page()

            async def gate(route):
                request = route.request
                if request.resource_type in BLOCKED_RESOURCES or not _is_allowed(
                    request.url
                ):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", gate)

            async def count(response):
                nonlocal transferred
                try:
                    transferred += len(await response.body())
                except Exception:
                    pass

            page.on("response", count)

            try:
                await page.goto(url, wait_until="commit", timeout=45000)
            except Exception as exc:
                raise BlockedError(f"страница не открылась: {exc!r}") from exc

            probe_url = PROBE_ENDPOINT.format(city=MOSCOW_CITY_ID, item=item_id)
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            cookies: dict[str, str] = {}
            cleared = False

            while asyncio.get_running_loop().time() < deadline:
                cookies = {c["name"]: c["value"] for c in await context.cookies()}
                if all(name in cookies for name in CLEARANCE_COOKIES):
                    try:
                        status = await page.evaluate(
                            """async (url) => {
                                const r = await fetch(url, {
                                    headers: {'Accept': 'application/json'},
                                    credentials: 'include'
                                });
                                return r.status;
                            }""",
                            probe_url,
                        )
                    except Exception:
                        status = None
                    if status == 200:
                        cleared = True
                        break
                await asyncio.sleep(0.7)
        finally:
            await browser.close()

    if not cleared:
        missing = [name for name in CLEARANCE_COOKIES if name not in cookies]
        detail = (
            f"нет кук: {', '.join(missing)}"
            if missing
            else "куки есть, но API карточку не отдаёт"
        )
        raise BlockedError(f"device-check не пройден ({detail})")

    log.info(
        "browser: device-check пройден, кук %d, трафик %.0f КБ",
        len(cookies),
        transferred / 1024,
    )
    return cookies
