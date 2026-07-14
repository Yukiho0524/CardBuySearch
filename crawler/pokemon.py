"""寶可夢官方繁中卡查爬蟲（asia.pokemon-card.com/tw）。

兩階段：
  Phase A（--rarity-map）：依 21 種稀有度過濾列表，建立 卡片ID → 稀有度 對照。
    詳細頁不顯示稀有度，這是唯一可靠的稀有度來源。
  Phase B（--details）：逐張抓詳細頁，補卡名 / 系列 / 卡片編號 / 卡圖。

可斷點續爬：Phase A 進度存在 crawl_progress，Phase B 只抓 detail_fetched=0 的卡。

用法：
  python crawler/pokemon.py --rarity-map            # 建稀有度對照（約 700 個請求）
  python crawler/pokemon.py --details --limit 300   # 抓 300 張詳細資料
  python crawler/pokemon.py --keyword 噴火龍         # 針對關鍵字的卡優先抓詳細資料
"""
import argparse
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_conn

BASE = "https://asia.pokemon-card.com"
LIST_URL = BASE + "/tw/card-search/list/"
DETAIL_URL = BASE + "/tw/card-search/detail/{id}/"
DELAY = 0.6  # 禮貌性延遲（秒）

RARITIES = {
    1: "C", 2: "U", 3: "R", 4: "RR", 5: "RRR", 6: "PR", 7: "TR",
    8: "SR", 9: "HR", 10: "UR", 11: "無標記", 12: "K", 13: "A",
    14: "AR", 15: "SAR", 16: "S", 17: "SSR", 18: "ACE",
    19: "BWR", 20: "MUR", 21: "MA",
}

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

DETAIL_ID_RE = re.compile(r"card-search/detail/(\d+)/")
TOTAL_PAGES_RE = re.compile(r"共\s*(\d+)\s*頁")


def fetch_list_page(page_no, rarity_code=None, keyword=None):
    """抓一頁列表，回傳 (card_ids, total_pages)。"""
    params = {"pageNo": page_no}
    if rarity_code is not None:
        params["rarity[]"] = rarity_code
    if keyword:
        params["keyword"] = keyword
    r = session.get(LIST_URL, params=params, timeout=30)
    r.raise_for_status()
    ids = [int(m) for m in DETAIL_ID_RE.findall(r.text)]
    m = TOTAL_PAGES_RE.search(r.text)
    total = int(m.group(1)) if m else 1
    return list(dict.fromkeys(ids)), total


def crawl_rarity_map(conn, max_pages_per_rarity=None):
    """Phase A：依稀有度過濾列表，寫入 卡片ID→稀有度。"""
    for code, label in RARITIES.items():
        progress_key = f"rarity_{code}_next_page"
        row = conn.execute(
            "SELECT value FROM crawl_progress WHERE key=?", (progress_key,)
        ).fetchone()
        page = int(row["value"]) if row else 1
        if page == -1:  # 已完成
            continue
        pages_done = 0
        while True:
            ids, total = fetch_list_page(page, rarity_code=code)
            if not ids:
                break
            conn.executemany(
                "INSERT INTO cards (id, rarity) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET rarity=excluded.rarity",
                [(i, label) for i in ids],
            )
            conn.execute(
                "INSERT OR REPLACE INTO crawl_progress VALUES (?, ?)",
                (progress_key, str(page + 1)),
            )
            conn.commit()
            print(f"[rarity {label}] 第 {page}/{total} 頁，{len(ids)} 張")
            pages_done += 1
            if page >= total:
                page = -1
                break
            if max_pages_per_rarity and pages_done >= max_pages_per_rarity:
                break
            page += 1
            time.sleep(DELAY)
        if page == -1:
            conn.execute(
                "INSERT OR REPLACE INTO crawl_progress VALUES (?, ?)",
                (progress_key, "-1"),
            )
            conn.commit()
            print(f"[rarity {label}] 完成")
        time.sleep(DELAY)


def parse_detail(html):
    """解析詳細頁 → dict(name, evolve_marker, set_alpha, set_mark, collector_number, image_url)。"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    h1 = soup.select_one("h1.pageHeader.cardDetail")
    if h1:
        marker = h1.select_one(".evolveMarker")
        out["evolve_marker"] = marker.get_text(strip=True) if marker else None
        if marker:
            marker.extract()
        out["name"] = h1.get_text(strip=True)
    img = soup.select_one(".cardImage img")
    out["image_url"] = img["src"] if img else None
    alpha = soup.select_one(".expansionColumn .alpha")
    out["set_alpha"] = alpha.get_text(strip=True) if alpha else None
    num = soup.select_one(".expansionColumn .collectorNumber")
    out["collector_number"] = num.get_text(strip=True) if num else None
    mark_img = soup.select_one(".expansionColumn .expansionSymbol img")
    out["set_mark"] = None
    if mark_img and mark_img.get("src"):
        m = re.search(r"twhk_(\w+?)\.png", mark_img["src"])
        out["set_mark"] = m.group(1) if m else None
    return out


def crawl_details(conn, limit=None, ids=None):
    """Phase B：抓詳細頁。ids 指定時只抓那些卡，否則抓所有未抓的。"""
    if ids:
        rows = [(i,) for i in ids]
        conn.executemany("INSERT OR IGNORE INTO cards (id) VALUES (?)", rows)
        conn.commit()
        todo = [
            r["id"] for r in conn.execute(
                f"SELECT id FROM cards WHERE detail_fetched=0 AND id IN "
                f"({','.join('?' * len(ids))})", ids)
        ]
    else:
        q = "SELECT id FROM cards WHERE detail_fetched=0 ORDER BY id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        todo = [r["id"] for r in conn.execute(q)]
    print(f"待抓詳細頁：{len(todo)} 張")
    for n, card_id in enumerate(todo, 1):
        try:
            r = session.get(DETAIL_URL.format(id=card_id), timeout=30)
            r.raise_for_status()
            d = parse_detail(r.text)
        except Exception as e:
            print(f"  [{card_id}] 失敗：{e}")
            time.sleep(DELAY * 3)
            continue
        conn.execute(
            "UPDATE cards SET name=?, evolve_marker=?, set_alpha=?, set_mark=?, "
            "collector_number=?, image_url=?, detail_fetched=1 WHERE id=?",
            (d.get("name"), d.get("evolve_marker"), d.get("set_alpha"),
             d.get("set_mark"), d.get("collector_number"), d.get("image_url"),
             card_id),
        )
        conn.commit()
        print(f"  [{n}/{len(todo)}] {d.get('name')} {d.get('collector_number')} (id={card_id})")
        time.sleep(DELAY)


def crawl_keyword(conn, keyword):
    """以關鍵字搜尋官方卡查，將結果卡片抓完詳細資料（稀有度需另跑 --rarity-map）。"""
    page, all_ids = 1, []
    while True:
        ids, total = fetch_list_page(page, keyword=keyword)
        all_ids += ids
        print(f"[keyword {keyword}] 第 {page}/{total} 頁，{len(ids)} 張")
        if page >= total or not ids:
            break
        page += 1
        time.sleep(DELAY)
    crawl_details(conn, ids=all_ids)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rarity-map", action="store_true", help="Phase A：建稀有度對照")
    ap.add_argument("--max-pages", type=int, default=None, help="Phase A 每個稀有度最多爬幾頁")
    ap.add_argument("--details", action="store_true", help="Phase B：抓詳細頁")
    ap.add_argument("--limit", type=int, default=None, help="Phase B 最多抓幾張")
    ap.add_argument("--keyword", type=str, default=None, help="針對關鍵字抓卡")
    args = ap.parse_args()

    conn = get_conn()
    if args.rarity_map:
        crawl_rarity_map(conn, max_pages_per_rarity=args.max_pages)
    if args.keyword:
        crawl_keyword(conn, args.keyword)
    if args.details:
        crawl_details(conn, limit=args.limit)
    if not (args.rarity_map or args.details or args.keyword):
        ap.print_help()
