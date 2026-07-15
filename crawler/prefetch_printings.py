"""全卡池預抓 Konami 收錄資料＋官方日文卡圖。

逐張呼叫 konami.get_printings（含快取，已抓過自動跳過），
一次搞定：收錄卡包/稀有度（稀有度自動篩選、卡號查詢用）＋日文卡圖。
約 1.4 萬張、禮貌延遲下需數小時，可中斷續跑。

用法：
  python crawler/prefetch_printings.py
  python crawler/prefetch_printings.py --limit 500
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_conn
from konami import get_printings


def main(limit=None):
    conn = get_conn()
    todo = [r["id"] for r in conn.execute(
        "SELECT id FROM ygo_cards WHERE cid IS NOT NULL AND id NOT IN "
        "(SELECT card_id FROM ygo_printings_fetched) ORDER BY id")]
    if limit:
        todo = todo[:limit]
    print(f"待抓 {len(todo)} 張")
    done = fail = 0
    for n, card_id in enumerate(todo, 1):
        p = get_printings(conn, card_id)
        if p is None:
            fail += 1
            if fail % 20 == 1:
                print(f"  [{card_id}] 抓取失敗（累計 {fail}）")
        else:
            done += 1
        if n % 100 == 0:
            print(f"  進度 {n}/{len(todo)}（成功 {done}、失敗 {fail}）")
    print(f"完成：成功 {done}、失敗 {fail}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    main(args.limit)
