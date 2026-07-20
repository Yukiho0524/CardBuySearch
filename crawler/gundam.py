"""鋼彈卡片遊戲 GCG 爬蟲（來源：官方繁中站 gundam-gcg.com/zh-tw）。

流程：
  1. 逐系列（GD01-05、ST01-09）以 ?freeword=<系列> 取卡號清單
  2. 每張卡抓 detail.php 解析欄位（顏色/類型/Lv/COST/AP/HP/特徵/作品/稀有度）
  3. 下載官方繁中卡圖（webp）轉存 jpg 快取

可斷點續爬（略過 detail_fetched=1）。

用法：
  python crawler/gundam.py            # 全部系列
  python crawler/gundam.py --pack GD01
  python crawler/gundam.py --limit 30
"""
import argparse
import io
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_conn

BASE = "https://www.gundam-gcg.com"
LIST_URL = BASE + "/zh-tw/cards/index.php?freeword={pack}"
DETAIL_URL = BASE + "/zh-tw/cards/detail.php?detailSearch={cid}"
IMG_URL = BASE + "/jp/images/cards/card/{cid}.webp"
IMG_CACHE = Path(__file__).parent.parent / "data" / "img_cache" / "gcg"
PACKS = [f"GD0{i}" for i in range(1, 6)] + [f"ST0{i}" for i in range(1, 10)]
DELAY = 0.5

CARD_NO_RE = re.compile(r"[GS][DT]\d+-\d+")

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def list_pack(pack):
    """回傳該系列的卡號清單（去重、排序）。"""
    r = session.get(LIST_URL.format(pack=pack), timeout=30)
    r.raise_for_status()
    nums = [n for n in CARD_NO_RE.findall(r.text) if n.startswith(pack)]
    return sorted(dict.fromkeys(nums))


def _int(s):
    m = re.search(r"-?\d+", s or "")
    return int(m.group(0)) if m else None


def parse_detail(html, cid):
    soup = BeautifulSoup(html, "html.parser")
    out = {"id": cid, "pack": cid.split("-")[0]}
    h1 = soup.select_one("h1")
    out["name_tc"] = h1.get_text(strip=True) if h1 else None
    rar = soup.select_one(".rarity")
    out["rarity"] = rar.get_text(strip=True) if rar else None
    fields = {}
    for dt in soup.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            fields[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)
    out["level"] = _int(fields.get("Lv."))
    out["cost"] = _int(fields.get("COST"))
    out["ap"] = _int(fields.get("AP"))
    out["hp"] = _int(fields.get("HP"))
    out["color"] = fields.get("顏色")
    out["card_type"] = fields.get("卡牌類型")
    out["terrain"] = fields.get("地形")
    out["traits"] = fields.get("特徵")
    out["source"] = fields.get("來源作品")
    return out


def save_image(cid):
    dst = IMG_CACHE / f"{cid}.jpg"
    if dst.exists():
        return
    try:
        r = session.get(IMG_URL.format(cid=cid), timeout=30)
        if r.ok and r.content[:4] == b"RIFF":  # webp magic
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.save(dst, "JPEG", quality=90)
    except Exception:
        pass


def crawl(packs=None, limit=None):
    conn = get_conn()
    packs = packs or PACKS
    # 收集所有卡號
    todo = []
    for pack in packs:
        try:
            nums = list_pack(pack)
        except Exception as e:
            print(f"[{pack}] 列表失敗：{e}")
            continue
        print(f"[{pack}] {len(nums)} 張")
        conn.executemany(
            "INSERT OR IGNORE INTO gundam_cards (id, pack) VALUES (?, ?)",
            [(n, pack) for n in nums])
        conn.commit()
        todo += nums
        time.sleep(DELAY)
    # 只抓未完成的
    done = {r["id"] for r in conn.execute(
        "SELECT id FROM gundam_cards WHERE detail_fetched=1")}
    todo = [n for n in todo if n not in done]
    if limit:
        todo = todo[:limit]
    print(f"待抓詳細：{len(todo)} 張")
    for i, cid in enumerate(todo, 1):
        try:
            r = session.get(DETAIL_URL.format(cid=cid), timeout=30)
            r.raise_for_status()
            d = parse_detail(r.text, cid)
        except Exception as e:
            print(f"  [{cid}] 失敗：{e}")
            time.sleep(DELAY * 3)
            continue
        save_image(cid)
        conn.execute(
            "UPDATE gundam_cards SET name_tc=?, color=?, card_type=?, level=?, "
            "cost=?, ap=?, hp=?, terrain=?, traits=?, source=?, rarity=?, "
            "detail_fetched=1 WHERE id=?",
            (d["name_tc"], d["color"], d["card_type"], d["level"], d["cost"],
             d["ap"], d["hp"], d["terrain"], d["traits"], d["source"],
             d["rarity"], cid))
        conn.commit()
        if i % 20 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} {d['name_tc']} {cid} [{d['rarity']}]")
        time.sleep(DELAY)
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", help="只爬指定系列（GD01/ST01…）")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    crawl([args.pack] if args.pack else None, args.limit)
