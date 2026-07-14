"""CardBuySearch — TCG 缺卡湊齊比價網站（第一版：寶可夢繁中 × 露天拍賣）。

啟動：python app.py  →  http://localhost:5000
"""
from collections import defaultdict
from pathlib import Path

import requests as _requests
from flask import Flask, abort, jsonify, request, send_from_directory

from opencc import OpenCC

from db import get_conn
from ruten import (YGO_LANGS, YGO_RARITIES, find_listings_for_card,
                   find_listings_for_ygo, resolve_seller)

app = Flask(__name__, static_folder="static", static_url_path="")

_t2s = OpenCC("t2s")   # 讓使用者用繁中搜到簡中卡名

IMG_CACHE = Path(__file__).parent / "data" / "img_cache"
YGO_IMG_URL = "https://images.ygoprodeck.com/images/cards/{id}.jpg"

CONFIDENCE_ORDER = {"strong": 0, "weak": 1, "maybe": 2}


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/img/<game>/<int:card_id>")
def img_proxy(game, card_id):
    """卡圖代理＋磁碟快取。官方圖伺服器對瀏覽器跨站請求會停滯，改由後端抓取後供應同源圖片。"""
    if game not in ("pkm", "ygo"):
        abort(404)
    ext = "png" if game == "pkm" else "jpg"
    cache = IMG_CACHE / game / f"{card_id}.{ext}"
    if not cache.exists():
        if game == "pkm":
            conn = get_conn()
            row = conn.execute(
                "SELECT image_url FROM cards WHERE id=?", (card_id,)).fetchone()
            conn.close()
            if not row or not row["image_url"]:
                abort(404)
            url = row["image_url"]
        else:
            url = YGO_IMG_URL.format(id=card_id)
        try:
            r = _requests.get(url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            r.raise_for_status()
        except Exception:
            abort(502)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(r.content)
    resp = send_from_directory(cache.parent, cache.name)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.get("/api/search")
def api_search():
    """卡片搜尋：game＝pkm/ygo，q＝卡名或編號，rarity＝稀有度過濾（僅寶可夢）。"""
    game = request.args.get("game", "pkm")
    q = (request.args.get("q") or "").strip()
    rarity = (request.args.get("rarity") or "").strip()
    if not q and not rarity:
        return jsonify({"cards": []})
    conn = get_conn()
    if game == "ygo":
        q_sc = _t2s.convert(q)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM ygo_cards WHERE name_tc LIKE ? OR name_sc LIKE ? "
            "OR name_jp LIKE ? OR name_en LIKE ? LIMIT 60",
            (f"%{q}%", f"%{q_sc}%", f"%{q}%", f"%{q}%"))]
        cards = [{
            "id": r["id"], "game": "ygo", "name": r["name_tc"],
            "name_jp": r["name_jp"], "types": r["types"],
            "collector_number": None, "rarity": None,
            "image_url": f"/img/ygo/{r['id']}",
        } for r in rows]
    else:
        sql = "SELECT * FROM cards WHERE detail_fetched=1"
        params = []
        if q:
            sql += " AND (name LIKE ? OR collector_number LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        if rarity:
            sql += " AND rarity = ?"
            params.append(rarity)
        sql += " ORDER BY id DESC LIMIT 60"
        cards = [dict(r) for r in conn.execute(sql, params)]
        for r in cards:
            r["image_url"] = f"/img/pkm/{r['id']}"
            r["game"] = "pkm"
    conn.close()
    return jsonify({"cards": cards})


@app.get("/api/ygo/options")
def api_ygo_options():
    """遊戲王願望清單可選的稀有度與紙種。"""
    return jsonify({"rarities": list(YGO_RARITIES), "langs": list(YGO_LANGS)})


@app.get("/api/rarities")
def api_rarities():
    conn = get_conn()
    rows = [r["rarity"] for r in conn.execute(
        "SELECT DISTINCT rarity FROM cards WHERE rarity IS NOT NULL "
        "AND detail_fetched=1 ORDER BY rarity")]
    conn.close()
    return jsonify({"rarities": rows})


@app.post("/api/compare")
def api_compare():
    """核心功能：對願望清單跑露天搜尋，找出能一次湊齊最多卡的賣家。

    輸入: {"items": [{"card_id": 123, "qty": 1}, ...]}
    輸出: 各賣家的覆蓋卡片、單價、預估總價（含運費），以及跨賣家拆買的最便宜組合。
    """
    payload = request.get_json(force=True)
    items = payload.get("items") or []
    if not items or len(items) > 12:
        return jsonify({"error": "願望清單需為 1–12 張卡"}), 400

    conn = get_conn()
    wants = []  # 統一格式：{key, game, card_id, name, collector_number, rarity, lang, qty}
    for it in items:
        game = it.get("game", "pkm")
        qty = max(1, int(it.get("qty", 1)))
        if game == "ygo":
            row = conn.execute(
                "SELECT * FROM ygo_cards WHERE id=?", (it["card_id"],)).fetchone()
            if row:
                wants.append({
                    "key": f"ygo:{row['id']}", "game": "ygo", "card_id": row["id"],
                    "name": row["name_tc"], "names": [row["name_tc"], row["name_sc"], row["name_jp"]],
                    "collector_number": None,
                    "rarity": (it.get("rarity") or None),
                    "lang": (it.get("lang") or None), "qty": qty,
                })
        else:
            row = conn.execute(
                "SELECT * FROM cards WHERE id=?", (it["card_id"],)).fetchone()
            if row:
                wants.append({
                    "key": f"pkm:{row['id']}", "game": "pkm", "card_id": row["id"],
                    "name": row["name"], "names": None,
                    "collector_number": row["collector_number"],
                    "rarity": row["rarity"], "lang": None, "qty": qty,
                })
    conn.close()
    if not wants:
        return jsonify({"error": "找不到指定卡片"}), 400

    # 每張卡查露天 → 依賣家彙整
    per_card_listings = {}
    for w in wants:
        if w["game"] == "ygo":
            listings = find_listings_for_ygo(
                [n for n in w["names"] if n], w["rarity"], w["lang"])
        else:
            listings = find_listings_for_card(
                w["name"], w["collector_number"], w["rarity"])
        listings = [l for l in listings if l["price"] and (l["stock"] or 0) > 0]
        listings.sort(key=lambda l: (CONFIDENCE_ORDER[l["confidence"]], l["price"]))
        per_card_listings[w["key"]] = listings

    sellers = defaultdict(dict)  # seller_id -> {want_key: best_listing}
    for key, listings in per_card_listings.items():
        for l in listings:
            cur = sellers[l["seller_id"]].get(key)
            if cur is None or (CONFIDENCE_ORDER[l["confidence"]], l["price"]) < \
                    (CONFIDENCE_ORDER[cur["confidence"]], cur["price"]):
                sellers[l["seller_id"]][key] = l

    def want_info(w):
        return {"card_id": w["card_id"], "game": w["game"], "card_name": w["name"],
                "collector_number": w["collector_number"], "rarity": w["rarity"],
                "lang": w["lang"], "qty": w["qty"]}

    want_by_key = {w["key"]: w for w in wants}
    seller_results = []
    for sid, offer in sellers.items():
        covered, subtotal, shipping = [], 0, 0
        for key, l in offer.items():
            w = want_by_key[key]
            covered.append({**want_info(w), "listing": l})
            subtotal += l["price"] * w["qty"]
            shipping = max(shipping, l["shipping_cost"] or 0)
        seller_results.append({
            "seller_id": sid,
            "covered_count": len(covered),
            "total_count": len(wants),
            "complete": len(covered) == len(wants),
            "covered": covered,
            "missing": [want_info(w) for w in wants if w["key"] not in offer],
            "subtotal": subtotal,
            "shipping": shipping,
            "total": subtotal + shipping,
        })
    # 排序：湊齊優先 → 覆蓋數多 → 總價低
    seller_results.sort(key=lambda s: (-s["covered_count"], s["total"]))

    # 前幾名賣家補上賣場暱稱（從商品頁解析，結果有快取）
    conn = get_conn()
    for s in seller_results[:8]:
        info = resolve_seller(conn, s["seller_id"], s["covered"][0]["listing"]["prod_id"])
        if info:
            s["seller_nick"] = info["nick"]
            s["seller_name"] = info["name"]
            s["store_url"] = f"https://www.ruten.com.tw/store/{info['nick']}/"
    conn.close()

    # 跨賣家拆買基準：每張卡取全站最便宜，運費按涉及的賣家各計一次
    split_items, split_sellers = [], {}
    for w in wants:
        listings = per_card_listings[w["key"]]
        if listings:
            best = listings[0]
            split_items.append({**want_info(w), "listing": best})
            sid = best["seller_id"]
            split_sellers[sid] = max(
                split_sellers.get(sid, 0), best["shipping_cost"] or 0)
    split_subtotal = sum(i["listing"]["price"] * i["qty"] for i in split_items)
    split_shipping = sum(split_sellers.values())

    return jsonify({
        "wishlist": [{**want_info(w), "image_url": f"/img/{w['game']}/{w['card_id']}"}
                     for w in wants],
        "sellers": seller_results[:20],
        "split_baseline": {
            "items": split_items,
            "found_count": len(split_items),
            "total_count": len(wants),
            "seller_count": len(split_sellers),
            "subtotal": split_subtotal,
            "shipping": split_shipping,
            "total": split_subtotal + split_shipping,
        },
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
