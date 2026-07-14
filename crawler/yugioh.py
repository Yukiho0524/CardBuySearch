"""遊戲王卡牌資料匯入（資料來源：百鴿 ygocdb.com 全量匯出）。

下載 cards.zip（約 2.4MB、1.4 萬張卡）解析後匯入 SQLite，
簡中卡名以 OpenCC（s2twp）轉為繁中供搜尋。

用法：
  python crawler/yugioh.py            # 下載並匯入（重跑會整批更新）
  python crawler/yugioh.py --file X   # 用本地 cards.json / cards.zip
"""
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import requests
from opencc import OpenCC

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_conn

DUMP_URL = "https://ygocdb.com/api/v0/cards.zip"


def load_dump(path=None):
    if path:
        p = Path(path)
        if p.suffix == ".zip":
            data = p.read_bytes()
        else:
            return json.loads(p.read_text(encoding="utf-8"))
    else:
        print(f"下載 {DUMP_URL} …")
        r = requests.get(DUMP_URL, timeout=120)
        r.raise_for_status()
        data = r.content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.endswith(".json"))
        return json.loads(z.read(name).decode("utf-8"))


def import_cards(dump):
    cc = OpenCC("s2twp")  # 簡→繁（台灣用語）
    conn = get_conn()
    rows = []
    for entry in dump.values():
        card_id = entry.get("id")
        if not card_id:
            continue
        sc = entry.get("cn_name") or entry.get("sc_name") or ""
        rows.append((
            card_id,
            entry.get("cid"),
            cc.convert(sc) if sc else None,
            sc or None,
            entry.get("jp_name") or None,
            entry.get("en_name") or None,
            (entry.get("text") or {}).get("types"),
        ))
    conn.executemany(
        "INSERT INTO ygo_cards (id, cid, name_tc, name_sc, name_jp, name_en, types) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "cid=excluded.cid, name_tc=excluded.name_tc, name_sc=excluded.name_sc, "
        "name_jp=excluded.name_jp, name_en=excluded.name_en, types=excluded.types",
        rows,
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM ygo_cards").fetchone()[0]
    print(f"匯入完成，共 {n} 張遊戲王卡")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="本地 cards.json 或 cards.zip")
    args = ap.parse_args()
    import_cards(load_dump(args.file))
