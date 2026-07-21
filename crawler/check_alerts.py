"""到價通知排程檢查：對所有啟用中的通知跑露天，達標則 Discord 推播。

手動執行：python crawler/check_alerts.py
建議用 Windows 工作排程器定期跑（如每 3 小時，前提是電腦開著）：

  schtasks /create /tn CardBuySearch-Alerts /sc HOURLY /mo 3 ^
    /tr "\"C:\\Path\\to\\python.exe\" \"C:\\Users\\hibari.kuo\\CardBuySearch\\crawler\\check_alerts.py\""

輸出寫入 data/alerts.log。
"""
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "data" / "alerts.log"


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    from db import get_conn
    import alerts

    log("========== 到價檢查開始 ==========")
    conn = get_conn()
    try:
        res = alerts.check_all(conn, verbose=True)
        log(f"檢查 {res['checked']} 筆，觸發 {res['fired']} 筆通知")
    except Exception:
        import traceback
        log("檢查失敗：\n" + traceback.format_exc())
    finally:
        conn.close()
    log("========== 到價檢查結束 ==========")
