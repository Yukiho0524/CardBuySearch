"""卡圖感知雜湊索引（圖片搜尋用）。

對每張卡圖計算 pHash + dHash 存入 image_hashes。可斷點續跑（跳過已索引的卡）。
  - 遊戲王：ygoprodeck 縮圖（約 10KB/張），全量約 1.4 萬張
  - 寶可夢：官方卡圖（約 300KB/張），只索引已有詳細資料的卡；
    卡圖若已在 data/img_cache 快取則直接用本地檔

用法：
  python crawler/imghash.py --game ygo
  python crawler/imghash.py --game pkm
  python crawler/imghash.py --game ygo --limit 500
"""
import argparse
import io
import sys
import time
from pathlib import Path

import imagehash
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_conn

IMG_CACHE = Path(__file__).parent.parent / "data" / "img_cache"
YGO_SMALL_URL = "https://images.ygoprodeck.com/images/cards_small/{id}.jpg"
DELAY = 0.15

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def hash_image(data):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return str(imagehash.phash(img)), str(imagehash.dhash(img))


def fetch_image(game, card_id, image_url=None):
    """優先用本地快取，否則下載（遊戲王用縮圖以節省流量）。"""
    for ext in ("png", "jpg"):
        cached = IMG_CACHE / game / f"{card_id}.{ext}"
        if cached.exists():
            return cached.read_bytes()
    url = YGO_SMALL_URL.format(id=card_id) if game == "ygo" else image_url
    if not url:
        return None
    r = session.get(url, timeout=20)
    r.raise_for_status()
    time.sleep(DELAY)
    return r.content


def build_index(game, limit=None):
    conn = get_conn()
    if game == "ygo":
        rows = conn.execute(
            "SELECT id, NULL AS image_url FROM ygo_cards WHERE id NOT IN "
            "(SELECT card_id FROM image_hashes WHERE game='ygo')").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, image_url FROM cards WHERE detail_fetched=1 "
            "AND image_url IS NOT NULL AND id NOT IN "
            "(SELECT card_id FROM image_hashes WHERE game='pkm')").fetchall()
    if limit:
        rows = rows[:limit]
    print(f"[{game}] 待索引 {len(rows)} 張")
    done = fail = 0
    for r in rows:
        try:
            data = fetch_image(game, r["id"], r["image_url"])
            if not data:
                continue
            ph, dh = hash_image(data)
        except Exception as e:
            fail += 1
            if fail % 50 == 1:
                print(f"  失敗 {r['id']}: {e}")
            time.sleep(DELAY * 4)
            continue
        # 每筆立即 commit：避免交易橫跨網路抓圖時間、長時間佔住寫入鎖
        # （會與其他爬蟲同時寫同一個 SQLite）
        conn.execute(
            "INSERT OR REPLACE INTO image_hashes VALUES (?,?,?,?)",
            (game, r["id"], ph, dh))
        conn.commit()
        done += 1
        if done % 200 == 0:
            print(f"  進度 {done}/{len(rows)}（失敗 {fail}）")
    conn.commit()
    print(f"[{game}] 完成：新增 {done}、失敗 {fail}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", choices=["pkm", "ygo"], required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    build_index(args.game, args.limit)
