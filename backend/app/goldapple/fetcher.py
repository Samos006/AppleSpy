from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.goldapple.errors import BlockedError, NotFoundError, TransientError
from app.goldapple.fingerprint import CH_PLATFORM, SEC_CH_UA, USER_AGENT

log = logging.getLogger(__name__)

BASE = "https://goldapple.ru"
CARD_ENDPOINT = f"{BASE}/front/api/catalog/product-card/base/v3"

COOKIE_STORE = Path(__file__).resolve().parents[2] / "ga_cookies.json"

CHALLENGE_MARKERS = ("checking device", "ga-gun-init", "idw-goldapple")

WAF_MARKERS = (
    "Доступ к сайту временно ограничен",
    "ограничен владельцем",
)

NO_CLEARANCE_MARKERS = ("An error occurred",)

IP_RE = re.compile(r"IP-адрес[:\s]*([\d.]+)")
REQ_ID_RE = re.compile(r"([0-9a-f]{32})")

def _api_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": CH_PLATFORM,
    }

def _document_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

def classify_block(text: str) -> BlockedError | None:
    head = text[:6000]
    if any(m in head for m in CHALLENGE_MARKERS):
        return BlockedError("device-check: не пройдена проверка устройства")
    if any(m in head for m in WAF_MARKERS):
        ip_match = IP_RE.search(head)
        req_match = REQ_ID_RE.search(head)
        return BlockedError(
            "waf: IP определён как хостинг/VPN и заблокирован",
            ip=ip_match.group(1) if ip_match else None,
            request_id=req_match.group(1) if req_match else None,
        )
    if any(m in head for m in NO_CLEARANCE_MARKERS):
        return BlockedError("нет клиренс-кук: нужен проход device-check")
    return None

@dataclass
class ProxyEntry:
    url: str | None
    fails: int = 0
    cookies: dict[str, str] = field(default_factory=dict)
    cookies_at: float = 0.0

    @property
    def label(self) -> str:
        if not self.url:
            return "direct"
        return re.sub(r"//[^@]*@", "//***@", self.url)

    @property
    def key(self) -> str:
        return re.sub(r"//[^@]*@", "//", self.url) if self.url else "direct"

    def cookies_fresh(self, ttl: int) -> bool:
        return bool(self.cookies) and (time.time() - self.cookies_at) < ttl

class CookieStore:
    def __init__(self, path: Path = COOKIE_STORE) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str, ttl: int) -> tuple[dict[str, str], float] | None:
        row = self._data.get(key)
        if not isinstance(row, dict):
            return None
        saved_at = float(row.get("at", 0))
        cookies = row.get("cookies")
        if not isinstance(cookies, dict) or time.time() - saved_at > ttl:
            return None
        return cookies, saved_at

    def put(self, key: str, cookies: dict[str, str]) -> None:
        self._data[key] = {"at": time.time(), "cookies": cookies}
        self._flush()

    def drop(self, key: str) -> None:
        if self._data.pop(key, None) is not None:
            self._flush()

    def _flush(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("не удалось сохранить куки: %s", exc)

class ProxyPool:
    MAX_FAILS = 4

    def __init__(self, proxies: list[str]) -> None:
        normalized = [self._normalize(p) for p in proxies]
        self._entries = [ProxyEntry(url=p) for p in normalized] or [
            ProxyEntry(url=None)
        ]

    @staticmethod
    def _normalize(proxy: str) -> str:
        if proxy.startswith("socks5://"):
            return "socks5h://" + proxy[len("socks5://") :]
        return proxy

    def pick(self) -> ProxyEntry:
        healthy = [e for e in self._entries if e.fails < self.MAX_FAILS]
        if not healthy:
            for e in self._entries:
                e.fails = 0
            healthy = self._entries
        return random.choice(healthy)

    def report(self, entry: ProxyEntry, ok: bool) -> None:
        entry.fails = 0 if ok else entry.fails + 1

    @property
    def entries(self) -> list[ProxyEntry]:
        return list(self._entries)

class GoldAppleFetcher:
    def __init__(
        self,
        proxies: list[str] | None = None,
        city_id: str | None = None,
        timeout: float | None = None,
        use_browser: bool | None = None,
    ) -> None:
        self.pool = ProxyPool(proxies if proxies is not None else settings.proxies)
        self.city_id = city_id or settings.ga_city_id
        self.timeout = timeout or settings.ga_request_timeout
        self.use_browser = (
            settings.ga_browser_fallback if use_browser is None else use_browser
        )
        self.cookie_ttl = settings.ga_cookie_ttl
        self.store = CookieStore()
        self._browser_lock = asyncio.Lock()

        self._session: Any = None
        self.browser_only = self.use_browser and not any(
            e.url for e in self.pool.entries
        )
        if self.browser_only:
            from app.goldapple.session import BrowserSession

            self._session = BrowserSession(
                self.city_id, settings.region_id, ttl=self.cookie_ttl
            )
            log.info("режим добычи: браузерная сессия (прокси не заданы)")

        for entry in self.pool.entries:
            saved = self.store.get(entry.key, self.cookie_ttl)
            if saved:
                entry.cookies, entry.cookies_at = saved
                log.info("подняты сохранённые куки для %s", entry.label)

    async def fetch_product_card(
        self, item_id: str, attempts: int = 3
    ) -> dict[str, Any]:
        if self._session is not None:
            return await self._session.fetch_card(item_id, attempts=attempts)

        last_block: BlockedError | None = None
        last_transient: TransientError | None = None

        for attempt in range(attempts):
            entry = self.pool.pick()
            try:
                data = await self._attempt(entry, item_id)
            except BlockedError as exc:
                self.pool.report(entry, ok=False)
                last_block = exc
                log.warning("goldapple blocked via %s: %s", entry.label, exc)
            except TransientError as exc:
                self.pool.report(entry, ok=False)
                last_transient = exc
                log.warning("goldapple transient via %s: %s", entry.label, exc)
            except NotFoundError:
                self.pool.report(entry, ok=True)
                raise
            else:
                self.pool.report(entry, ok=True)
                return data

            if attempt < attempts - 1:
                await asyncio.sleep(1.5 * (attempt + 1) + random.random())

        if last_block:
            raise last_block
        raise last_transient or TransientError("не удалось получить карточку")

    async def _attempt(self, entry: ProxyEntry, item_id: str) -> dict[str, Any]:
        if not entry.cookies_fresh(self.cookie_ttl):
            await self._renew_cookies(entry, item_id)

        try:
            return await self._call_api(entry, item_id)
        except BlockedError:
            entry.cookies = {}
            self.store.drop(entry.key)
            await self._renew_cookies(entry, item_id, force=True)
            return await self._call_api(entry, item_id)

    async def _call_api(self, entry: ProxyEntry, item_id: str) -> dict[str, Any]:
        params = {
            "locale": "ru",
            "cityId": self.city_id,
            "regionId": settings.region_id,
            "itemId": str(item_id),
        }
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout),
            "follow_redirects": True,
            "http2": True,
        }
        if entry.url:
            client_kwargs["proxy"] = entry.url

        async with httpx.AsyncClient(**client_kwargs) as client:
            client.cookies.update(entry.cookies)
            try:
                resp = await client.get(
                    CARD_ENDPOINT,
                    params=params,
                    headers=_api_headers(f"{BASE}/{item_id}-"),
                )
            except httpx.HTTPError as exc:
                raise TransientError(f"сеть: {exc!r}") from exc

            text = resp.text
            block = classify_block(text)
            if block:
                raise block

            if resp.status_code == 404:
                raise NotFoundError(f"товар {item_id} не найден")
            if resp.status_code == 403:
                raise BlockedError("403 без опознанной страницы блокировки")
            if resp.status_code >= 500:
                raise TransientError(f"сервер ответил {resp.status_code}")
            if resp.status_code != 200:
                raise TransientError(f"неожиданный статус {resp.status_code}")

            try:
                return resp.json()
            except ValueError as exc:
                raise TransientError(f"ответ не JSON: {text[:200]!r}") from exc

    async def _renew_cookies(
        self, entry: ProxyEntry, item_id: str, force: bool = False
    ) -> None:
        if not force:
            saved = self.store.get(entry.key, self.cookie_ttl)
            if saved:
                entry.cookies, entry.cookies_at = saved
                return

        if self.use_browser:
            async with self._browser_lock:
                if not force:
                    saved = self.store.get(entry.key, self.cookie_ttl)
                    if saved:
                        entry.cookies, entry.cookies_at = saved
                        return

                from app.goldapple.browser import solve_challenge

                log.info("запускаю браузер для device-check через %s", entry.label)
                cookies = await solve_challenge(
                    item_id, proxy_url=entry.url, user_agent=USER_AGENT
                )
                entry.cookies = cookies
                entry.cookies_at = time.time()
                self.store.put(entry.key, cookies)
            return

        await self._warmup(entry, item_id)

    async def _warmup(self, entry: ProxyEntry, item_id: str) -> None:
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout),
            "follow_redirects": True,
        }
        if entry.url:
            client_kwargs["proxy"] = entry.url
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                await client.get(f"{BASE}/{item_id}-", headers=_document_headers())
                entry.cookies = dict(client.cookies)
                entry.cookies_at = time.time()
        except httpx.HTTPError:
            pass

    async def diagnose(self, item_id: str = "19000116114") -> list[dict[str, Any]]:
        if self._session is not None:
            row: dict[str, Any] = {"proxy": "браузерная сессия (без прокси)"}
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    info = (await client.get("https://ipinfo.io/json")).json()
                row["ip"] = info.get("ip")
                row["country"] = info.get("country")
                row["org"] = info.get("org")
            except Exception:
                pass
            try:
                await self._session.fetch_card(item_id, attempts=2)
            except Exception as exc:
                row["ok"] = False
                row["reason"] = f"{type(exc).__name__}: {exc}"
            else:
                row["ok"] = True
                row["reason"] = "карточка отдаётся"
            return [row]

        results: list[dict[str, Any]] = []
        for entry in self.pool.entries:
            row = {"proxy": entry.label}

            client_kwargs: dict[str, Any] = {
                "timeout": httpx.Timeout(20.0),
                "follow_redirects": True,
            }
            if entry.url:
                client_kwargs["proxy"] = entry.url
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    info = (await client.get("https://ipinfo.io/json")).json()
                    row["ip"] = info.get("ip")
                    row["country"] = info.get("country")
                    row["org"] = info.get("org")
            except Exception as exc:
                row["ok"] = False
                row["reason"] = f"прокси недоступен: {exc!r}"
                results.append(row)
                continue

            try:
                await self._attempt(entry, item_id)
            except BlockedError as exc:
                row["ok"] = False
                row["reason"] = exc.reason
            except Exception as exc:
                row["ok"] = False
                row["reason"] = f"{type(exc).__name__}: {exc}"
            else:
                row["ok"] = True
                row["reason"] = "карточка отдаётся"
            results.append(row)
        return results
