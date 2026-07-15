"""Konami 官方卡片資料庫：抓取遊戲王卡的收錄卡包與稀有度。

用途：使用者把卡加入願望清單時，自動列出「這張卡實際出過的稀有度」。
按需抓取（一卡一次）後快取於 ygo_printings，失敗也記錄避免重複嘗試。
"""
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CARD_URL = ("https://www.db.yugioh-card.com/yugiohdb/card_search.action"
            "?ope=2&cid={cid}&request_locale=ja")
BASE = "https://www.db.yugioh-card.com/yugiohdb/"
IMG_CACHE = Path(__file__).parent / "data" / "img_cache" / "ygo"
GET_IMAGE_RE = re.compile(r"get_image\.action\?[^\"' >]+")
DELAY = 0.5

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Konami 日文站稀有度代號 → 本站標準標籤（ruten.YGO_RARITIES 的 key）
RARITY_MAP = {
    "N": "N", "R": "R", "SR": "SR", "UR": "UR",
    "SE": "SEC", "EXSE": "EXSEC", "20THSE": "20th", "QCSE": "QCSE",
    "PSE": "PSER", "UL": "UTR", "CR": "CR", "HR": "HR",
    "PG": "PGR",               # プレミアムゴールドレア
    "M": "MR", "MSE": "MSEC",  # ミレニアム系（少見，保留原樣顯示）
    "NP": "NPR", "P": "PR",    # パラレル系
    "KC": "KC",
}


def fetch_printings(cid, card_id=None):
    """回傳 [{code, pack, rarity, release}]；抓取/解析失敗回傳 None。

    card_id 給定時順路下載官方日文卡圖到 img_cache/ygo/{id}.jp.jpg
    （圖片連結帶時效 token，必須在同一會話立即下載）。
    """
    try:
        r = session.get(CARD_URL.format(cid=cid), timeout=30)
        r.raise_for_status()
    except Exception:
        return None
    if card_id is not None:
        _save_jp_image(r.text, card_id)
    soup = BeautifulSoup(r.text, "html.parser")
    update_area = soup.select_one("#update_list")
    rows = (update_area or soup).select(".t_row")
    printings = []
    for row in rows:
        code = row.select_one(".card_number")
        pack = row.select_one(".pack_name")
        release = row.select_one(".time")
        rarity_el = row.select_one(".icon.rarity .lr_icon p")
        if not (code and pack):
            continue
        raw = (rarity_el.get_text(strip=True).upper().replace(" ", "")
               if rarity_el else "")
        printings.append({
            "code": code.get_text(strip=True),
            "pack": pack.get_text(strip=True),
            "rarity": RARITY_MAP.get(raw, raw or None),
            "release": release.get_text(strip=True) if release else None,
        })
    time.sleep(DELAY)
    return printings


def _save_jp_image(page_html, card_id):
    """從卡片頁抓官方日文卡圖並快取（已存在則跳過）。"""
    jp_path = IMG_CACHE / f"{card_id}.jp.jpg"
    if jp_path.exists():
        return
    m = GET_IMAGE_RE.search(page_html)
    if not m:
        return
    try:
        img = session.get(BASE + m.group(0).replace("&amp;", "&"), timeout=30,
                          headers={"Referer": BASE + "card_search.action"})
        # 官方圖可能是 JPEG 或 PNG，統一轉存 JPEG
        if img.ok and img.content[:3] in (b"\xff\xd8\xff", b"\x89PN"):
            import io

            from PIL import Image
            im = Image.open(io.BytesIO(img.content)).convert("RGB")
            jp_path.parent.mkdir(parents=True, exist_ok=True)
            im.save(jp_path, "JPEG", quality=92)
    except Exception:
        pass


def get_printings(conn, card_id):
    """取收錄卡包（含快取）。回傳 list（可能為空）；來源異常回傳 None。"""
    fetched = conn.execute(
        "SELECT 1 FROM ygo_printings_fetched WHERE card_id=?",
        (card_id,)).fetchone()
    if fetched:
        return [dict(r) for r in conn.execute(
            "SELECT code, pack, rarity, release FROM ygo_printings "
            "WHERE card_id=? ORDER BY release", (card_id,))]
    row = conn.execute(
        "SELECT cid FROM ygo_cards WHERE id=?", (card_id,)).fetchone()
    if not row or not row["cid"]:
        return None
    printings = fetch_printings(row["cid"], card_id=card_id)
    if printings is None:
        return None  # 失敗不記快取，之後可重試
    # 防止與預抓任務並發重複寫入
    conn.execute("DELETE FROM ygo_printings WHERE card_id=?", (card_id,))
    conn.executemany(
        "INSERT INTO ygo_printings (card_id, code, pack, rarity, release) "
        "VALUES (?,?,?,?,?)",
        [(card_id, p["code"], p["pack"], p["rarity"], p["release"])
         for p in printings])
    conn.execute(
        "INSERT OR REPLACE INTO ygo_printings_fetched (card_id) VALUES (?)",
        (card_id,))
    conn.commit()
    return printings
