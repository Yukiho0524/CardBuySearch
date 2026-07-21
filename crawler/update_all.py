"""每週自動更新：新卡入庫＋字典重學＋圖片索引補建。

由 Windows 工作排程器每週執行（也可手動跑）。各步驟獨立 try/except，
單步失敗不中斷整體；輸出寫入 data/update.log。

步驟：
  1. 寶可夢增量：重掃各稀有度前 3 頁補新卡 → 抓新卡詳細頁
  2. 遊戲王：重新下載 ygocdb 全量匯入（含新卡與譯名更新）
  3. 譯名字典重學（learn_aliases --write）
  4. 圖片雜湊索引補建（兩個遊戲，只處理新卡）
  5. Konami 收錄資料預抓（只處理新卡，上限 500 張/次避免跑太久）
"""
import datetime
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "data" / "update.log"


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def step(name, fn):
    log(f"--- {name} 開始")
    try:
        fn()
        log(f"--- {name} 完成")
    except Exception:
        log(f"--- {name} 失敗：\n{traceback.format_exc()}")


def pkm_update():
    from crawler.pokemon import crawl_details, crawl_rarity_map
    from db import get_conn
    conn = get_conn()
    crawl_rarity_map(conn, refresh_pages=3)
    crawl_details(conn)  # 只抓 detail_fetched=0 的新卡
    conn.close()


def ygo_update():
    from crawler.yugioh import import_cards, load_dump
    import_cards(load_dump())


def alias_update():
    import json

    from crawler.learn_aliases import ALIAS_PATH, learn_pairs, load_dump, merge_groups
    doc = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    merged, learned = merge_groups(doc.get("aliases", {}), learn_pairs(load_dump()))
    doc["aliases"] = dict(sorted(merged.items()))
    ALIAS_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"字典更新：{len(merged)} 組")


def imghash_update():
    from crawler.imghash import build_index
    build_index("ygo")
    build_index("pkm")


def printings_update():
    from crawler.prefetch_printings import main
    main(limit=500)


def gundam_update():
    from crawler.gundam import crawl
    crawl()  # 列舉各系列、抓新卡詳細與卡圖（已抓的自動跳過）


if __name__ == "__main__":
    log("========== 每週更新開始 ==========")
    step("寶可夢增量爬蟲", pkm_update)
    step("遊戲王全量匯入", ygo_update)
    step("鋼彈 GCG 更新", gundam_update)
    step("譯名字典重學", alias_update)
    step("圖片索引補建", imghash_update)
    step("Konami 收錄預抓", printings_update)
    log("========== 每週更新結束 ==========")
