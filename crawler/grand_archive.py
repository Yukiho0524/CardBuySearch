"""Grand Archive TCG（GA）匯入：官方 API api.gatcg.com。

全英文卡（台灣賣美版、無繁中印刷），資料來源是官方公開 JSON API，
不需爬 HTML。分頁抓 /cards/search，每張卡的每個 edition（印刷版本）各存一列
（比照寶可夢/鋼彈），同卡不同版本以 card_id 分群。卡圖走 /img/ga 代理按需快取。

手動執行：python crawler/grand_archive.py
"""
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from db import get_conn  # noqa: E402

API = "https://api.gatcg.com"
SEARCH = API + "/cards/search"
DELAY = 0.4

# 官方稀有度數值 → 字母（來自 /option/search）
RARITY_MAP = {1: "C", 2: "U", 3: "R", 4: "SR", 5: "UR",
              6: "PR", 7: "CSR", 8: "CUR", 9: "CPR"}

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CardBuySearch/1.0")


def _join(xs):
    return ",".join(x for x in (xs or []) if x) or None


def _img_name(edition):
    """edition 的圖檔名（如 2zw7a98f7b.jpg）：取自 image 路徑，退回 uuid。"""
    img = edition.get("image") or ""
    m = re.search(r"([^/]+\.\w+)$", img)
    if m:
        return m.group(1)
    return (edition.get("uuid") or "") + ".jpg"


def _rows_from_card(card):
    """一張卡 → 其所有 edition 的資料列（dict）。"""
    common = {
        "card_id": card.get("uuid"),
        "name": card.get("name"),
        "element": _join(card.get("elements")) or card.get("element"),
        "classes": _join(card.get("classes")),
        "types": _join(card.get("types")),
        "subtypes": _join(card.get("subtypes")),
        "cost_memory": card.get("cost_memory"),
        "cost_reserve": card.get("cost_reserve"),
        "level": card.get("level"),
        "power": card.get("power"),
        "life": card.get("life"),
        "durability": card.get("durability"),
        "speed": card.get("speed"),
        "effect": card.get("effect"),
    }
    rows = []
    for e in card.get("editions") or []:
        s = e.get("set") or {}
        rarity = e.get("rarity")
        rows.append({
            **common,
            "id": e.get("uuid"),
            "slug": e.get("slug"),
            "set_prefix": s.get("prefix"),
            "set_name": s.get("name"),
            "collector_number": e.get("collector_number"),
            "rarity": rarity,
            "rarity_label": RARITY_MAP.get(rarity),
            "image": _img_name(e),
            "language": s.get("language"),
        })
    return rows


COLS = ["id", "card_id", "slug", "name", "element", "classes", "types",
        "subtypes", "cost_memory", "cost_reserve", "level", "power", "life",
        "durability", "speed", "effect", "set_prefix", "set_name",
        "collector_number", "rarity", "rarity_label", "image", "language"]


def crawl():
    conn = get_conn()
    page, total_pages, imported = 1, None, 0
    while True:
        for attempt in range(3):
            try:
                r = session.get(SEARCH, params={"page": page}, timeout=30)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == 2:
                    print(f"第 {page} 頁失敗，跳過：{e}")
                    data = None
                    break
                time.sleep(2)
        if data is None:
            page += 1
            if total_pages and page > total_pages:
                break
            continue
        total_pages = data.get("total_pages") or total_pages
        rows = []
        for card in data.get("data") or []:
            rows += _rows_from_card(card)
        for row in rows:
            if not row["id"]:
                continue
            conn.execute(
                f"INSERT OR REPLACE INTO ga_cards ({','.join(COLS)}) "
                f"VALUES ({','.join('?' * len(COLS))})",
                [row.get(c) for c in COLS])
            imported += 1
        conn.commit()
        print(f"第 {page}/{total_pages} 頁 → 已匯入 {imported} 個版本")
        if not data.get("has_more") or (total_pages and page >= total_pages):
            break
        page += 1
        time.sleep(DELAY)
    total_cards = conn.execute(
        "SELECT COUNT(DISTINCT card_id) FROM ga_cards").fetchone()[0]
    conn.close()
    print(f"完成：{imported} 個版本、{total_cards} 張不同卡。")


if __name__ == "__main__":
    crawl()
