from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.goldapple.client import GoldAppleClient
from app.goldapple.errors import GoldAppleError
from app.goldapple.url import extract_item_id

DUMP_PATH = "probe_dump.json"

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

async def cmd_diag() -> int:
    client = GoldAppleClient()
    rows = await client.diagnose()
    print(f"Проверяю {len(rows)} канал(ов) доступа\n")
    any_ok = False
    for row in rows:
        mark = "OK  " if row.get("ok") else "БЛОК"
        print(f"[{mark}] {row['proxy']}")
        if row.get("ip"):
            print(f"        IP:  {row['ip']} ({row.get('country')}) {row.get('org')}")
        print(f"        Итог: {row.get('reason')}")
        print()
        any_ok = any_ok or bool(row.get("ok"))

    if not any_ok:
        print(
            "Ни один канал не пропущен. Напомню: ЗЯ режет хостинг- и VPN-подсети\n"
            "по ASN, поэтому датацентровые прокси (в том числе индивидуальные\n"
            "IPv4 у любого провайдера) не подходят. Нужны резидентные или\n"
            "мобильные прокси с российским гео."
        )
        return 1
    return 0

async def cmd_card(target: str, dump_raw: bool) -> int:
    item_id = extract_item_id(target)
    if not item_id:
        print(f"Не смог выделить itemId из {target!r}", file=sys.stderr)
        return 2

    client = GoldAppleClient()
    print(f"itemId = {item_id}")
    try:
        product = await client.get_product(item_id)
    except GoldAppleError as exc:
        print(f"Ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Название:  {product.name}")
    print(f"Бренд:     {product.brand}")
    print(f"Цена:      {product.price}")
    print(f"Старая:    {product.old_price}")
    print(f"Скидка:    {product.discount_percent}")
    print(f"В наличии: {product.in_stock}")
    print(f"Рейтинг:   {product.rating} ({product.reviews_count} отзывов)")
    print(f"Картинка:  {product.image_url}")
    print(f"Ссылка:    {product.url}")

    if dump_raw:
        with open(DUMP_PATH, "w", encoding="utf-8") as fh:
            json.dump(product.raw, fh, ensure_ascii=False, indent=2)
        print(f"\nСырой ответ сохранён в {DUMP_PATH}")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="probe",
        description="Проверка доступа к Золотому Яблоку и снятие карточки товара.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diag", help="проверить доступность ЗЯ по каждому прокси")
    card = sub.add_parser("card", help="забрать карточку товара")
    card.add_argument("target", help="ссылка на товар или голый itemId")
    card.add_argument("--raw", action="store_true", help="сохранить сырой JSON")

    args = parser.parse_args()
    if args.cmd == "diag":
        return asyncio.run(cmd_diag())
    return asyncio.run(cmd_card(args.target, args.raw))

if __name__ == "__main__":
    raise SystemExit(main())
