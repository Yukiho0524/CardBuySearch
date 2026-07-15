"""Konami 官方卡片資料庫：抓取遊戲王卡的收錄卡包與稀有度。

用途：使用者把卡加入願望清單時，自動列出「這張卡實際出過的稀有度」。
按需抓取（一卡一次）後快取於 ygo_printings，失敗也記錄避免重複嘗試。
"""
import re
import time

import requests
from bs4 import BeautifulSoup

CARD_URL = ("https://www.db.yugioh-card.com/yugiohdb/card_search.action"
            "?ope=2&cid={cid}&request_locale=ja")
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


def fetch_printings(cid):
    """回傳 [{code, pack, rarity, release}]；抓取/解析失敗回傳 None。"""
    try:
        r = session.get(CARD_URL.format(cid=cid), timeout=30)
        r.raise_for_status()
    except Exception:
        return None
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
    printings = fetch_printings(row["cid"])
    if printings is None:
        return None  # 失敗不記快取，之後可重試
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
