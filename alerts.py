"""到價通知的核心檢查邏輯（Flask 端點的「立即檢查」與排程腳本共用）。

每筆通知依其條件重跑露天搜尋（重用 ruten.py，與 /api/compare 同一套比對），
達標時透過 notify.send_alert 推播。防重複通知：達標推播一次後標記 notified，
價格回到目標以上時自動重置，之後再跌破才會再次推播。
"""
import datetime

from db import get_conn
from notify import send_alert
from ruten import (drop_price_outliers, find_listings_for_card,
                   find_listings_for_ga, find_listings_for_gundam,
                   find_listings_for_ygo)

# 只採信標題明確對應的商品（strong/weak），排除 maybe——maybe 代表標題
# 沒標稀有度/紙種，可能是別的版本，拿來觸發通知容易誤報。
TRIGGER_CONFIDENCES = {"strong", "weak"}


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_webhook(conn, client_id):
    """該訪客的 Discord Webhook（存 app_settings，鍵為 webhook:<client_id>）。"""
    if not client_id:
        return ""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key=?",
        (f"webhook:{client_id}",)).fetchone()
    return (row["value"] if row else "") or ""


def _search(conn, a):
    """依通知條件跑露天，回傳符合的商品（已濾信心度＋有現貨），最低價在前。

    比對條件的組法與 app.py 的 /api/compare 一致（遊戲王用官方卡號＋多譯名，
    鋼彈用卡號還原基礎卡號，寶可夢用卡名＋編號＋稀有度）。
    """
    game = a["game"]
    if game == "ygo":
        row = conn.execute(
            "SELECT * FROM ygo_cards WHERE id=?", (a["card_id"],)).fetchone()
        if not row:
            return []
        from konami import get_printings
        printings = get_printings(conn, row["id"]) or []
        codes = list(dict.fromkeys(
            p["code"] for p in reversed(printings) if p["code"]))
        names = [row["name_tc"], row["name_cnocg"], row["name_md"],
                 row["name_sc"], row["name_jp"]]
        listings = find_listings_for_ygo(
            [n for n in names if n], a["rarity"], a["lang"],
            codes=codes, art=a["art"])
    elif game == "gcg":
        row = conn.execute(
            "SELECT * FROM gundam_cards WHERE id=?", (a["card_id"],)).fetchone()
        if not row:
            return []
        listings = find_listings_for_gundam(
            row["name_tc"], row["id"], a["lang"], rarity=row["rarity"])
    elif game == "ga":
        row = conn.execute(
            "SELECT * FROM ga_cards WHERE id=?", (a["card_id"],)).fetchone()
        if not row:
            return []
        listings = find_listings_for_ga(
            row["name"], row["set_prefix"], row["collector_number"],
            rarity=row["rarity_label"], foil=a["lang"])
    else:
        row = conn.execute(
            "SELECT * FROM cards WHERE id=?", (a["card_id"],)).fetchone()
        if not row:
            return []
        listings = find_listings_for_card(
            row["name"], row["collector_number"], a["rarity"])
    listings = [l for l in listings
                if l["price"] and (l["stock"] or 0) > 0
                and l["confidence"] in TRIGGER_CONFIDENCES]
    listings = drop_price_outliers(listings)
    listings.sort(key=lambda l: l["price"])
    return listings


def check_alert(conn, a, webhook):
    """檢查單筆通知並更新狀態；達標且未通知過就推播。

    回傳 {id, min_price, hit, fired}（fired 表示這次確實送出了 Discord）。
    """
    listings = _search(conn, a)
    now = _now()
    low = listings[0] if listings else None
    min_price = low["price"] if low else None

    if min_price is not None:  # 順便累積價格歷史（與比價共用同一張表）
        try:
            conn.execute(
                "INSERT INTO price_history (game, card_id, rarity, lang, price) "
                "VALUES (?,?,?,?,?)",
                (a["game"], a["card_id"], a["rarity"], a["lang"], min_price))
        except Exception:
            pass

    hit = min_price is not None and min_price <= a["target_price"]
    fired = False

    if hit and not a["notified"]:
        # 首次達標 → 推播並記錄觸發資訊。
        # 有設 webhook 但送失敗 → 不標記 notified，下次檢查再試（避免漏通知）；
        # 送出成功或根本沒設 webhook → 標記 notified（後者僅控制站內「已達標」狀態）。
        fired = send_alert(webhook, a, low) if webhook else False
        mark = 1 if (fired or not webhook) else 0
        conn.execute(
            "UPDATE price_alerts SET notified=?, last_price=?, hit_price=?, "
            "hit_title=?, hit_url=?, last_checked=? WHERE id=?",
            (mark, min_price, min_price, low["title"], low["url"], now, a["id"]))
    elif not hit and a["notified"]:
        # 價格已高於目標 → 重置，之後再跌破可再次通知
        conn.execute(
            "UPDATE price_alerts SET notified=0, last_price=?, last_checked=? "
            "WHERE id=?", (min_price, now, a["id"]))
    else:
        conn.execute(
            "UPDATE price_alerts SET last_price=?, last_checked=? WHERE id=?",
            (min_price, now, a["id"]))
    conn.commit()
    return {"id": a["id"], "min_price": min_price, "hit": hit, "fired": fired}


def check_all(conn, client_id=None, verbose=False):
    """檢查啟用中的通知（給 client_id 只查該訪客的，否則全部）。

    每筆用「該通知主人的 Webhook」推播；回傳 {checked, fired, results}。
    """
    if client_id:
        alerts = [dict(r) for r in conn.execute(
            "SELECT * FROM price_alerts WHERE status='active' AND client_id=? "
            "ORDER BY id", (client_id,))]
    else:
        alerts = [dict(r) for r in conn.execute(
            "SELECT * FROM price_alerts WHERE status='active' ORDER BY id")]
    webhooks = {}  # client_id -> webhook（快取，避免每筆重查）
    results = []
    for a in alerts:
        cid = a.get("client_id")
        if cid not in webhooks:
            webhooks[cid] = get_webhook(conn, cid)
        try:
            res = check_alert(conn, a, webhooks[cid])
        except Exception as e:  # 單筆失敗不影響其他
            res = {"id": a["id"], "error": str(e)}
        if verbose:
            print(f"[{a['game']}] {a.get('card_name')} 目標{a['target_price']} "
                  f"→ {res}")
        results.append(res)
    return {"checked": len(alerts),
            "fired": sum(1 for r in results if r.get("fired")),
            "results": results}
