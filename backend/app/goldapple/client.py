from __future__ import annotations

import logging

from app.config import settings
from app.goldapple.errors import GoldAppleError, NotFoundError
from app.goldapple.fetcher import GoldAppleFetcher
from app.goldapple.parser import ProductData, parse_product_card
from app.goldapple.url import extract_item_id

log = logging.getLogger(__name__)

class GoldAppleClient:
    def __init__(self, fetcher: GoldAppleFetcher | None = None) -> None:
        self.fetcher = fetcher or GoldAppleFetcher()

    async def get_product(self, item_id: str) -> ProductData:
        payload = await self.fetcher.fetch_product_card(item_id)
        return parse_product_card(payload, item_id)

    async def get_by_url(self, url: str) -> ProductData:
        item_id = extract_item_id(url)
        if not item_id:
            raise NotFoundError("не похоже на ссылку Золотого Яблока")
        return await self.get_product(item_id)

    async def diagnose(self):
        return await self.fetcher.diagnose()

_client: GoldAppleClient | None = None

def get_client() -> GoldAppleClient:
    global _client
    if _client is None:
        log.info(
            "GoldAppleClient: прокси=%d, город=%s, браузерный фолбэк=%s",
            len(settings.proxies),
            settings.ga_city_id,
            settings.ga_browser_fallback,
        )
        _client = GoldAppleClient()
    return _client

__all__ = [
    "GoldAppleClient",
    "GoldAppleError",
    "ProductData",
    "get_client",
]
