"""Discord Webhook 推播：到價通知與測試訊息。

Webhook 只是一個 POST JSON 的網址，使用者在自己的 Discord 伺服器建立後
（伺服器設定 → 整合 → Webhook），把網址填進網頁即可。此檔不儲存網址，
只負責把訊息送出去（網址由呼叫端從 app_settings 取出後傳入）。
"""
import requests

GAME_LABEL = {"pkm": "寶可夢", "ygo": "遊戲王", "gcg": "鋼彈"}
EMBED_COLOR = 0x7C3AED  # 與站上主色一致


def _nt(n):
    return f"NT${int(n):,}"


def send_alert(webhook_url, alert, listing):
    """達標通知：卡片達到目標價時推播一則 Discord embed。

    alert：price_alerts 的一列（dict）；listing：露天最低價的商品（dict）。
    回傳 True 表示送出成功（HTTP 204/200）。
    """
    cond = "・".join(x for x in (alert.get("rarity"), alert.get("lang"),
                                 alert.get("art")) if x)
    game = GAME_LABEL.get(alert.get("game"), alert.get("game"))
    title = alert.get("card_name") or str(alert.get("card_id"))
    embed = {
        "title": f"🔔 {title} 到價了！",
        "url": listing.get("url"),
        "description": (f"目標價 **{_nt(alert['target_price'])}**，"
                        f"現在露天最低 **{_nt(listing['price'])}**（未含運）"),
        "color": EMBED_COLOR,
        "fields": [
            {"name": "條件", "value": game + (f"・{cond}" if cond else ""),
             "inline": True},
            {"name": "露天商品",
             "value": (listing.get("title") or "")[:200] or "（無標題）",
             "inline": False},
        ],
    }
    # 露天商品縮圖是公開網址（gcs.rimg.com.tw），Discord 抓得到；
    # 站內卡圖是本機網址、外部連不到，故不使用。
    if listing.get("image"):
        embed["thumbnail"] = {"url": listing["image"]}
    return _post(webhook_url, {"embeds": [embed]})


def send_test(webhook_url):
    """測試訊息：確認使用者填的 Webhook 可正常送達。"""
    return _post(webhook_url, {
        "content": "✅ CardBuySearch 到價通知測試訊息——Webhook 設定成功！"})


def _post(webhook_url, payload):
    try:
        r = requests.post(webhook_url, json=payload, timeout=15)
        return r.status_code in (200, 204)
    except Exception:
        return False
