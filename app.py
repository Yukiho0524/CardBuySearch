"""CardBuySearch — TCG 缺卡湊齊比價網站（第一版：寶可夢繁中 × 露天拍賣）。

啟動：python app.py  →  http://localhost:5000
"""
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import requests as _requests
from flask import Flask, abort, jsonify, request, send_from_directory

from opencc import OpenCC

from db import get_conn
from ruten import (GUNDAM_LANGS, YGO_LANGS, YGO_RARITIES, drop_price_outliers,
                   expand_variants, find_listings_for_card,
                   find_listings_for_ga, find_listings_for_gundam,
                   find_listings_for_ygo, resolve_seller)

app = Flask(__name__, static_folder="static", static_url_path="")
# 本機自用：靜態檔（HTML/JS/CSS）不讓瀏覽器快取，改版即生效，
# 避免新舊版本混搭造成的怪異行為（卡圖代理另有自己的快取標頭）
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

_t2s = OpenCC("t2s")    # 讓使用者用繁中搜到簡中卡名
_s2tw = OpenCC("s2twp")  # 讓使用者貼簡中也能搜到繁中卡名

IMG_CACHE = Path(__file__).parent / "data" / "img_cache"
YGO_IMG_URL = "https://images.ygoprodeck.com/images/cards/{id}.jpg"


def ygo_img_url(card_id):
    """日文圖就緒時網址帶 ?v=jp——讓瀏覽器略過先前快取的英文圖。"""
    if (IMG_CACHE / "ygo" / f"{card_id}.jp.jpg").exists():
        return f"/img/ygo/{card_id}?v=jp"
    return f"/img/ygo/{card_id}"

CONFIDENCE_ORDER = {"strong": 0, "weak": 1, "maybe": 2}

# 露天查詢結果快取（10 分鐘），避免重複比價時高頻打露天
_listing_cache = {}
LISTING_CACHE_TTL = 600

# 只允許 Discord 官方 Webhook 網址（避免被填成任意網址亂打）
DISCORD_WEBHOOK_RE = re.compile(
    r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")

# 「立即檢查」的背景執行狀態（避免同時跑多次；供前端輪詢）
_alert_check = {"running": False, "ts": None, "fired": 0}


@app.get("/")
def index():
    """首頁：注入資產版本戳（檔案 mtime），JS/CSS 一更新網址就變，
    瀏覽器必定重抓——根絕舊版快取殘留。HTML 本身不允許快取。"""
    static_dir = Path(app.static_folder)
    v = int(max((static_dir / f).stat().st_mtime for f in ("app.js", "style.css")))
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    resp = app.make_response(html.replace("__V__", str(v)))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/img/gcg/<card_id>")
def img_gcg(card_id):
    """鋼彈卡圖：爬蟲已抓好存在 data/img_cache/gcg/{卡號}.jpg（含異圖 _pN）。"""
    if not re.fullmatch(r"[A-Z]{2}\d+-\d+(?:_p\d+)?", card_id):
        abort(404)
    cache = IMG_CACHE / "gcg" / f"{card_id}.jpg"
    if not cache.exists():
        abort(404)
    resp = send_from_directory(cache.parent, cache.name)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.get("/img/ga/<name>")
def img_ga(name):
    """Grand Archive 卡圖代理＋磁碟快取（來源 api.gatcg.com/cards/images/…）。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.(jpg|jpeg|png|webp)", name):
        abort(404)
    cache = IMG_CACHE / "ga" / name
    if not cache.exists():
        try:
            r = _requests.get(
                f"https://api.gatcg.com/cards/images/{name}", timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            r.raise_for_status()
        except Exception:
            abort(502)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(r.content)
    resp = send_from_directory(cache.parent, cache.name)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.get("/img/<game>/<int:card_id>")
def img_proxy(game, card_id):
    """卡圖代理＋磁碟快取。官方圖伺服器對瀏覽器跨站請求會停滯，改由後端抓取後供應同源圖片。"""
    if game not in ("pkm", "ygo"):
        abort(404)
    if game == "ygo":
        # 官方日文卡圖優先（隨 Konami 收錄抓取進快取），EN 圖為後備
        jp = IMG_CACHE / "ygo" / f"{card_id}.jp.jpg"
        if jp.exists():
            resp = send_from_directory(jp.parent, jp.name)
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
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
    # ygo 的 EN 圖是暫代（等日文圖抓齊會替換），快取時間縮短
    resp.headers["Cache-Control"] = (
        "public, max-age=86400" if game == "ygo" else "public, max-age=604800")
    return resp


_ygo_index = None  # [(card_id, [squashed_names...])]，重新匯入卡片後需重啟


def _squash_q(s):
    """搜尋正規化：大寫、去空白/間隔號/連字號（與 ruten._squash 一致）。"""
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    return (s.upper().replace(" ", "").replace("·", "")
            .replace("・", "").replace("-", ""))


def get_ygo_index():
    global _ygo_index
    if _ygo_index is None:
        conn = get_conn()
        idx = []
        for r in conn.execute(
                "SELECT id, name_tc, name_sc, name_jp, name_en, "
                "name_cnocg, name_md FROM ygo_cards"):
            forms = {_squash_q(n) for n in
                     (r["name_tc"], r["name_sc"], r["name_jp"],
                      r["name_en"], r["name_cnocg"], r["name_md"]) if n}
            idx.append((r["id"], sorted(forms, key=len)))
        conn.close()
        _ygo_index = idx
    return _ygo_index


def search_ygo(conn, q, limit=60):
    """遊戲王搜尋：簡繁互轉＋譯名別名展開＋無視間隔號，依相關性排序。

    排名：完全一致 → 開頭一致 → 包含；同名次時卡名短者優先
    （搜「青眼白龍」時本尊排在「青眼白龍——尊嚴之龍」前面）。
    """
    q_forms = {_squash_q(f) for f in
               expand_variants([q, _s2tw.convert(q), _t2s.convert(q)], cap=12)}
    q_forms.discard("")
    if not q_forms:
        return []
    scored = []
    for card_id, names in get_ygo_index():
        best = None
        for n in names:
            for f in q_forms:
                if f == n:
                    rank = 0
                elif n.startswith(f):
                    rank = 1
                elif f in n:
                    rank = 2
                else:
                    continue
                key = (rank, len(n))
                if best is None or key < best:
                    best = key
        if best is not None:
            scored.append((best, card_id))
    scored.sort()
    cards = []
    for _, cid in scored[:limit]:
        r = conn.execute("SELECT * FROM ygo_cards WHERE id=?", (cid,)).fetchone()
        cards.append({
            "id": r["id"], "game": "ygo", "name": r["name_tc"],
            "name_jp": r["name_jp"], "types": r["types"],
            "collector_number": None, "rarity": None,
            "image_url": ygo_img_url(r["id"]),
        })
    return cards


def gcg_card_dict(r):
    """鋼彈卡列統一格式（供搜尋/一覽/詳情共用）。"""
    return {
        "id": r["id"], "game": "gcg", "name": r["name_tc"],
        "collector_number": r["id"], "rarity": r["rarity"],
        "color": r["color"], "card_type": r["card_type"],
        "level": r["level"], "source": r["source"],
        "image_url": f"/img/gcg/{r['id']}",
    }


def ga_card_dict(r):
    """Grand Archive 卡列統一格式（全英文，卡號＝系列-編號）。"""
    return {
        "id": r["id"], "game": "ga", "name": r["name"],
        "collector_number": f"{r['set_prefix']}-{r['collector_number']}",
        "rarity": r["rarity_label"], "element": r["element"],
        "card_type": r["types"], "set_prefix": r["set_prefix"],
        "image_url": f"/img/ga/{r['image']}",
    }


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
        cards = search_ygo(conn, q)
    elif game == "gcg":
        rows = conn.execute(
            "SELECT * FROM gundam_cards WHERE detail_fetched=1 "
            "AND (name_tc LIKE ? OR id LIKE ?) ORDER BY id LIMIT 60",
            (f"%{q}%", f"%{q}%")).fetchall()
        cards = [gcg_card_dict(r) for r in rows]
    elif game == "ga":
        rows = conn.execute(
            "SELECT * FROM ga_cards WHERE name LIKE ? "
            "OR (set_prefix || '-' || collector_number) LIKE ? "
            "ORDER BY name, set_prefix, collector_number LIMIT 60",
            (f"%{q}%", f"%{q}%")).fetchall()
        cards = [ga_card_dict(r) for r in rows]
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


_ygo_races = None  # 種族清單（從 types 解析一次後快取）

# 寶可夢擴充包代碼 → 中文產品名（官方站抓取，可自行增補）
try:
    PKM_PRODUCTS = json.loads(
        (Path(__file__).parent / "pkm_products.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    PKM_PRODUCTS = {}
_pkm_prod_cache = None  # {product_code: {"name","marks":[set_mark...]}}

# 鋼彈系列代碼 → 官方產品名（GCG 繁中站產品名為英文）
GUNDAM_PRODUCTS = {
    "GD01": "Newtype Rising", "GD02": "Dual Impact", "GD03": "Steel Requiem",
    "GD04": "Phantom Aria", "GD05": "Freedom Ascension",
    "ST01": "Heroic Beginnings", "ST02": "Wings of Advance", "ST03": "Zeon's Rush",
    "ST04": "SEED Strike", "ST05": "Iron Bloom", "ST06": "Clan Unity",
    "ST07": "Celestial Drive", "ST08": "Flash of Radiance", "ST09": "Destiny Ignition",
}


def pkm_product_code(set_mark):
    """set_mark（如 exp_SV8a、mtl_f）→ 產品代碼（SV8A、MTL），合併箔面變體。"""
    s = re.sub(r"exp", "", set_mark or "", flags=re.I)
    s = re.sub(r"_f$", "", s).strip("_").upper()
    return s or "OTHER"


def pkm_products():
    """回傳資料庫實際有的產品清單（新→舊），每項 {value, label}。"""
    global _pkm_prod_cache
    if _pkm_prod_cache is None:
        conn = get_conn()
        groups = {}
        for r in conn.execute(
                "SELECT DISTINCT set_mark FROM cards WHERE set_mark IS NOT NULL "
                "AND detail_fetched=1"):
            code = pkm_product_code(r["set_mark"])
            groups.setdefault(code, []).append(r["set_mark"])
        conn.close()
        _pkm_prod_cache = groups
    items = []
    for code, marks in _pkm_prod_cache.items():
        items.append({"value": code, "label": PKM_PRODUCTS.get(code, code),
                      "named": code in PKM_PRODUCTS})
    # 有中文名的排前面（近期產品），其餘（代碼）排後
    items.sort(key=lambda x: (not x["named"], x["label"]))
    return items


@app.get("/api/browse-options")
def api_browse_options():
    """全卡一覽的篩選選項。"""
    game = request.args.get("game", "pkm")
    conn = get_conn()
    if game == "ygo":
        global _ygo_races
        if _ygo_races is None:
            races = set()
            for r in conn.execute(
                    "SELECT types FROM ygo_cards WHERE types LIKE '[怪獸%'"):
                m = re.search(r"\]\s*([^/\n]+)/", r["types"] or "")
                if m:
                    races.add(m.group(1).strip())
            _ygo_races = sorted(races)
        out = {
            "categories": ["怪獸", "魔法", "陷阱"],
            # 細分類依類別而異（前端連動切換）
            "subtypes_by_cat": {
                "": ["通常", "效果", "儀式", "融合", "同調", "超量",
                     "連結", "靈擺", "調整", "特殊召喚",
                     "速攻", "永續", "場地", "裝備", "反擊"],
                "怪獸": ["通常", "效果", "儀式", "融合", "同調", "超量",
                        "連結", "靈擺", "調整", "特殊召喚"],
                "魔法": ["通常", "速攻", "永續", "場地", "裝備", "儀式"],
                "陷阱": ["通常", "永續", "反擊"],
            },
            "attrs": ["光", "暗", "炎", "水", "地", "風", "神"],
            "races": _ygo_races,
            "levels": ([f"★{i}" for i in range(1, 13)]
                       + [f"LINK-{i}" for i in range(1, 7)]),
        }
    elif game == "gcg":
        def distinct(col):
            return [r[0] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM gundam_cards WHERE {col} IS NOT NULL "
                f"AND detail_fetched=1 ORDER BY {col}")]
        out = {
            "colors": distinct("color"),
            "types": distinct("card_type"),
            "levels": [str(r[0]) for r in conn.execute(
                "SELECT DISTINCT level FROM gundam_cards WHERE level IS NOT NULL "
                "ORDER BY level")],
            "sources": distinct("source"),
            "products": [{"value": p, "label": f"{p}　{GUNDAM_PRODUCTS.get(p, '')}".strip()}
                         for p in distinct("pack")],
            "rarities": distinct("rarity"),
        }
    elif game == "ga":
        def ga_tokens(col):
            """從逗號分隔欄位取出所有單一標記（如 element='EXALTED,FIRE'）。"""
            seen = set()
            for r in conn.execute(
                    f"SELECT {col} FROM ga_cards WHERE {col} IS NOT NULL"):
                for tok in (r[0] or "").split(","):
                    if tok:
                        seen.add(tok)
            return sorted(seen)
        out = {
            "elements": ga_tokens("element"),
            "classes": ga_tokens("classes"),
            "types": ga_tokens("types"),
            "sets": [{"value": r["set_prefix"],
                      "label": f"{r['set_prefix']}　{r['set_name'] or ''}".strip()}
                     for r in conn.execute(
                         "SELECT set_prefix, MAX(set_name) AS set_name FROM ga_cards "
                         "GROUP BY set_prefix ORDER BY set_prefix")],
            "rarities": [r[0] for r in conn.execute(
                "SELECT rarity_label FROM ga_cards WHERE rarity_label IS NOT NULL "
                "GROUP BY rarity_label ORDER BY MIN(rarity)")],
        }
    else:
        out = {
            "kinds": ["寶可夢", "物品卡", "支援者卡", "競技場卡",
                      "寶可夢道具", "能量卡"],
            "ptypes": ["草", "火", "水", "雷", "超", "鬥", "惡", "鋼", "龍", "無色"],
            "stages": ["基礎", "1階進化", "2階進化",
                       "ex", "V", "VMAX", "VSTAR", "GX", "光輝"],
            "products": pkm_products(),
            "sets": [r[0] for r in conn.execute(
                "SELECT DISTINCT set_alpha FROM cards WHERE set_alpha IS NOT NULL "
                "ORDER BY set_alpha DESC")],
            "rarities": [r[0] for r in conn.execute(
                "SELECT DISTINCT rarity FROM cards WHERE rarity IS NOT NULL "
                "AND detail_fetched=1 ORDER BY rarity")],
        }
    conn.close()
    return jsonify(out)


@app.get("/api/browse")
def api_browse():
    """全卡一覽（篩選＋分頁，每頁 60 張、新卡在前）。"""
    game = request.args.get("game", "pkm")
    offset = max(0, int(request.args.get("offset", 0)))
    conn = get_conn()
    if game == "ygo":
        conds, params = [], []
        cat = request.args.get("cat")
        if cat:
            conds.append("types LIKE ?")
            params.append(f"[{cat}%")
        sub = request.args.get("sub")
        if sub:
            sub_term = {"連結": "連線"}.get(sub, sub)  # 資料經簡繁轉換為「連線」
            if sub == "通常" and cat in ("魔法", "陷阱"):
                # 通常魔法/陷阱沒有子類標記，格式就是 [魔法]
                conds.append("types LIKE ?")
                params.append(f"[{cat}]%")
            else:  # 細分類在第一個中括號內，用 | 分隔
                conds.append("(types LIKE ? OR types LIKE ?)")
                params += [f"%|{sub_term}|%", f"%|{sub_term}]%"]
        lv = request.args.get("lv")
        if lv:
            if lv.startswith("LINK-"):
                conds.append("types LIKE ?")
                params.append(f"%[{lv}]%")
            else:  # ★N 同時匹配等級（★）與超量階級（☆）
                n = lv.lstrip("★")
                conds.append("(types LIKE ? OR types LIKE ?)")
                params += [f"%[★{n}]%", f"%[☆{n}]%"]
        attr = request.args.get("attr")
        if attr:  # 屬性格式「種族/屬性」後接換行或字串結尾
            conds.append("(types LIKE ? OR types LIKE ?)")
            params += [f"%/{attr}\n%", f"%/{attr}"]
        race = request.args.get("race")
        if race:  # 種族格式「] 種族/」
            conds.append("types LIKE ?")
            params.append(f"%] {race}/%")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM ygo_cards {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ygo_cards {where} ORDER BY cid DESC LIMIT 60 OFFSET ?",
            params + [offset]).fetchall()
        cards = [{
            "id": r["id"], "game": "ygo", "name": r["name_tc"],
            "name_jp": r["name_jp"], "collector_number": None, "rarity": None,
            "image_url": ygo_img_url(r["id"]),
        } for r in rows]
    elif game == "gcg":
        conds, params = ["detail_fetched=1"], []
        for key, col in (("color", "color"), ("type", "card_type"),
                         ("source", "source"), ("pack", "pack"),
                         ("rarity", "rarity")):
            val = request.args.get(key)
            if val:
                conds.append(f"{col} = ?")
                params.append(val)
        lv = request.args.get("lv")
        if lv:
            conds.append("level = ?")
            params.append(int(lv))
        where = "WHERE " + " AND ".join(conds)
        total = conn.execute(
            f"SELECT COUNT(*) FROM gundam_cards {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM gundam_cards {where} ORDER BY id LIMIT 60 OFFSET ?",
            params + [offset]).fetchall()
        cards = [gcg_card_dict(r) for r in rows]
    elif game == "ga":
        conds, params = [], []
        for key, col in (("element", "element"), ("class", "classes"),
                         ("type", "types")):
            val = request.args.get(key)
            if val:  # 逗號分隔欄位：以整個 token 比對（避免子字串誤中）
                conds.append(f"(','||{col}||',') LIKE ?")
                params.append(f"%,{val},%")
        for key, col in (("set", "set_prefix"), ("rarity", "rarity_label")):
            val = request.args.get(key)
            if val:
                conds.append(f"{col} = ?")
                params.append(val)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM ga_cards {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ga_cards {where} "
            f"ORDER BY set_prefix, collector_number LIMIT 60 OFFSET ?",
            params + [offset]).fetchall()
        cards = [ga_card_dict(r) for r in rows]
    else:
        conds, params = ["detail_fetched=1"], []
        kind = request.args.get("kind")  # 大類：寶可夢/物品卡/支援者卡/...
        if kind:
            conds.append("card_kind = ?")
            params.append(kind)
        ptype = request.args.get("ptype")  # 屬性（僅寶可夢卡有）
        if ptype:
            conds.append("ptype = ?")
            params.append(ptype)
        stage = request.args.get("stage")  # 階段/機制
        if stage in ("基礎", "1階進化", "2階進化"):
            conds.append("evolve_marker = ?")
            params.append(stage)
        elif stage == "光輝":
            conds.append("name LIKE '光輝%'")
        elif stage:  # ex/V/VMAX/VSTAR/GX：卡名字尾（LIKE 不分大小寫，涵蓋舊 EX）
            conds.append("name LIKE ?")
            params.append(f"%{stage}")
        product = request.args.get("product")  # 產品/擴充包
        if product:
            pkm_products()  # 確保 _pkm_prod_cache 已建
            mark_list = (_pkm_prod_cache or {}).get(product, [])
            if mark_list:
                conds.append(f"set_mark IN ({','.join('?' * len(mark_list))})")
                params += mark_list
        set_alpha = request.args.get("set")
        if set_alpha:
            conds.append("set_alpha = ?")
            params.append(set_alpha)
        rarity = request.args.get("rarity")
        if rarity:
            conds.append("rarity = ?")
            params.append(rarity)
        where = "WHERE " + " AND ".join(conds)
        total = conn.execute(
            f"SELECT COUNT(*) FROM cards {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM cards {where} ORDER BY id DESC LIMIT 60 OFFSET ?",
            params + [offset]).fetchall()
        cards = [{**dict(r), "game": "pkm", "image_url": f"/img/pkm/{r['id']}"}
                 for r in rows]
    conn.close()
    return jsonify({"total": total, "offset": offset, "cards": cards})


@app.post("/api/search-by-image")
def api_search_by_image():
    """圖片搜尋：上傳卡片照片，以感知雜湊找最相近的卡。

    照片請盡量裁切到只剩卡片本體；回傳前 12 名（距離越小越像）。
    """
    import io as _io

    import imagehash
    from PIL import Image

    f = request.files.get("image")
    game = request.form.get("game", "pkm")
    if not f:
        return jsonify({"error": "缺少圖片"}), 400
    try:
        img = Image.open(_io.BytesIO(f.read())).convert("RGB")
    except Exception:
        return jsonify({"error": "無法讀取圖片"}), 400
    q_ph = imagehash.phash(img)
    q_dh = imagehash.dhash(img)

    conn = get_conn()
    rows = conn.execute(
        "SELECT card_id, phash, dhash FROM image_hashes WHERE game=?",
        (game,)).fetchall()
    if not rows:
        conn.close()
        return jsonify({"error": "此遊戲的圖片索引尚未建立，請先跑 crawler/imghash.py"}), 400
    scored = []
    for r in rows:
        d = int(q_ph - imagehash.hex_to_hash(r["phash"])) \
            + int(q_dh - imagehash.hex_to_hash(r["dhash"]))
        scored.append((d, r["card_id"]))
    scored.sort()
    top = scored[:12]

    cards = []
    for d, cid in top:
        if game == "ygo":
            row = conn.execute("SELECT * FROM ygo_cards WHERE id=?", (cid,)).fetchone()
            if row:
                cards.append({
                    "id": row["id"], "game": "ygo", "name": row["name_tc"],
                    "name_jp": row["name_jp"], "collector_number": None,
                    "rarity": None, "image_url": ygo_img_url(row["id"]),
                    "distance": d,
                })
        else:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()
            if row:
                cards.append({**dict(row), "game": "pkm",
                              "image_url": f"/img/pkm/{row['id']}", "distance": d})
    conn.close()
    return jsonify({"cards": cards})


@app.get("/api/ygo/options")
def api_ygo_options():
    """遊戲王願望清單可選的稀有度與紙種。

    「簡中」保留在比對字典（選日紙/韓紙時用來排除簡中商品），
    但台灣市場買不到，不列入可選紙種。
    """
    langs = [l for l in YGO_LANGS if l != "簡中"]
    return jsonify({"rarities": list(YGO_RARITIES), "langs": langs})


@app.get("/api/ygo/printings/<int:card_id>")
def api_ygo_printings(card_id):
    """這張卡實際出過的收錄卡包與稀有度（Konami 官方 DB，按需抓取後快取）。"""
    from konami import get_printings

    conn = get_conn()
    printings = get_printings(conn, card_id)
    conn.close()
    if printings is None:
        return jsonify({"printings": [], "rarities": [], "ok": False})
    rarities = list(dict.fromkeys(
        p["rarity"] for p in printings if p["rarity"]))
    return jsonify({"printings": printings, "rarities": rarities, "ok": True})


@app.get("/api/gcg/options")
def api_gcg_options():
    """鋼彈願望清單可選的版本（日版/美版）。"""
    return jsonify({"langs": list(GUNDAM_LANGS)})


@app.get("/api/rarities")
def api_rarities():
    conn = get_conn()
    rows = [r["rarity"] for r in conn.execute(
        "SELECT DISTINCT rarity FROM cards WHERE rarity IS NOT NULL "
        "AND detail_fetched=1 ORDER BY rarity")]
    conn.close()
    return jsonify({"rarities": rows})


@app.get("/api/card/gcg/<card_id>")
def api_card_detail_gcg(card_id):
    """鋼彈卡片詳情：顏色/類型/Lv/COST/AP/HP/特徵/地形/作品/稀有度。"""
    conn = get_conn()
    r = conn.execute(
        "SELECT * FROM gundam_cards WHERE id=?", (card_id,)).fetchone()
    if not r:
        conn.close()
        abort(404)
    # 異圖版本：基礎卡號（去掉 _pN）＋其所有平行卡，供彈窗切換
    base_id = re.sub(r"_p\d+$", "", r["id"])
    variants = [{"id": v["id"], "rarity": v["rarity"],
                 "is_alt": v["id"] != base_id}
                for v in conn.execute(
                    "SELECT id, rarity FROM gundam_cards "
                    "WHERE id=? OR id GLOB ? ORDER BY id",
                    (base_id, base_id + "_p*"))]
    conn.close()
    return jsonify({
        "game": "gcg", "id": r["id"], "name": r["name_tc"],
        "color": r["color"], "card_type": r["card_type"],
        "level": r["level"], "cost": r["cost"], "ap": r["ap"], "hp": r["hp"],
        "terrain": r["terrain"], "traits": r["traits"], "source": r["source"],
        "effect": r["effect"], "rarity": r["rarity"], "pack": r["pack"],
        "image_url": f"/img/gcg/{r['id']}",
        "variants": variants,
        "official_url":
            f"https://www.gundam-gcg.com/zh-tw/cards/detail.php?detailSearch={r['id']}",
    })


@app.get("/api/card/ga/<card_id>")
def api_card_detail_ga(card_id):
    """Grand Archive 卡片詳情：元素/職業/卡種/費用/攻防/效果＋同卡其他版本。"""
    conn = get_conn()
    r = conn.execute("SELECT * FROM ga_cards WHERE id=?", (card_id,)).fetchone()
    if not r:
        conn.close()
        abort(404)
    variants = [{"id": v["id"], "set_prefix": v["set_prefix"],
                 "collector_number": v["collector_number"],
                 "rarity": v["rarity_label"]}
                for v in conn.execute(
                    "SELECT id, set_prefix, collector_number, rarity_label, rarity "
                    "FROM ga_cards WHERE card_id=? "
                    "ORDER BY set_prefix, collector_number", (r["card_id"],))]
    conn.close()
    return jsonify({
        "game": "ga", "id": r["id"], "name": r["name"],
        "element": r["element"], "classes": r["classes"], "types": r["types"],
        "subtypes": r["subtypes"], "cost_memory": r["cost_memory"],
        "cost_reserve": r["cost_reserve"], "level": r["level"],
        "power": r["power"], "life": r["life"], "durability": r["durability"],
        "speed": r["speed"], "effect": r["effect"],
        "set_prefix": r["set_prefix"], "set_name": r["set_name"],
        "collector_number": r["collector_number"], "rarity": r["rarity_label"],
        "image_url": f"/img/ga/{r['image']}",
        "variants": variants,
        "official_url": f"https://index.gatcg.com/cards/{r['slug']}",
    })


@app.get("/api/card/<game>/<int:card_id>")
def api_card_detail(game, card_id):
    """卡片詳情（點卡片彈出的視窗用）。兩遊戲欄位不同：

    ygo：多語卡名、種類/屬性/攻守、效果文字、收錄卡包表（卡號/稀有度/發售日）
    pkm：系列/編號/稀有度、同名卡的其他印刷版本、官方詳細頁連結
    """
    conn = get_conn()
    if game == "ygo":
        r = conn.execute("SELECT * FROM ygo_cards WHERE id=?", (card_id,)).fetchone()
        if not r:
            conn.close()
            abort(404)
        printings = [dict(p) for p in conn.execute(
            "SELECT release, code, rarity, pack FROM ygo_printings "
            "WHERE card_id=? ORDER BY release DESC", (card_id,))]
        detail = {
            "game": "ygo", "id": r["id"],
            "name": r["name_tc"], "name_jp": r["name_jp"], "name_en": r["name_en"],
            "name_cnocg": r["name_cnocg"],
            "types": r["types"], "card_text": r["card_text"],
            "pend_text": r["pend_text"],
            "image_url": ygo_img_url(r["id"]),
            "printings": printings,
        }
    elif game == "pkm":
        r = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not r:
            conn.close()
            abort(404)
        variants = [dict(v) for v in conn.execute(
            "SELECT id, set_alpha, collector_number, rarity FROM cards "
            "WHERE name=? AND detail_fetched=1 ORDER BY id DESC", (r["name"],))]
        detail = {
            "game": "pkm", "id": r["id"],
            "name": r["name"], "evolve_marker": r["evolve_marker"],
            "set_alpha": r["set_alpha"], "collector_number": r["collector_number"],
            "rarity": r["rarity"],
            "image_url": f"/img/pkm/{r['id']}",
            "official_url": f"https://asia.pokemon-card.com/tw/card-search/detail/{r['id']}/",
            "variants": variants,
        }
    else:
        conn.close()
        abort(404)
    conn.close()
    return jsonify(detail)


@app.get("/api/cards")
def api_cards():
    """批次取卡片資料（分享連結還原用）。?game=ygo&ids=1,2,3"""
    game = request.args.get("game", "pkm")
    raw_ids = [x for x in (request.args.get("ids") or "").split(",") if x][:40]
    conn = get_conn()
    cards = []
    if game == "gcg":  # 鋼彈卡號是字串
        for cid in raw_ids:
            r = conn.execute(
                "SELECT * FROM gundam_cards WHERE id=?", (cid,)).fetchone()
            if r:
                cards.append(gcg_card_dict(r))
        conn.close()
        return jsonify({"cards": cards})
    if game == "ga":  # GA edition id 是字串（uuid）
        for cid in raw_ids:
            r = conn.execute(
                "SELECT * FROM ga_cards WHERE id=?", (cid,)).fetchone()
            if r:
                cards.append(ga_card_dict(r))
        conn.close()
        return jsonify({"cards": cards})
    try:
        ids = [int(x) for x in raw_ids]
    except ValueError:
        conn.close()
        return jsonify({"cards": []})
    for cid in ids:
        if game == "ygo":
            r = conn.execute("SELECT * FROM ygo_cards WHERE id=?", (cid,)).fetchone()
            if r:
                cards.append({
                    "id": r["id"], "game": "ygo", "name": r["name_tc"],
                    "name_jp": r["name_jp"], "collector_number": None,
                    "rarity": None, "image_url": ygo_img_url(r["id"])})
        else:
            r = conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()
            if r:
                cards.append({**dict(r), "game": "pkm",
                              "image_url": f"/img/pkm/{r['id']}"})
    conn.close()
    return jsonify({"cards": cards})


def fetch_pkm_deck(deck_code):
    """抓官方訓練家網站的牌組（牌組編碼 → [(card_id, qty)]）。

    牌組頁每張卡是 detail 連結＋count 張數，直接對應本站卡片 ID。
    回傳 (entries, error_message)。
    """
    from bs4 import BeautifulSoup
    url = f"https://asia.pokemon-card.com/tw/deck-build/recipe/{deck_code}/"
    try:
        r = _requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    except Exception:
        return None, "無法連線官方牌組頁，請稍後再試"
    if not r.ok:
        return None, f"找不到牌組編碼 {deck_code}"
    soup = BeautifulSoup(r.text, "html.parser")
    # 頁面含桌機/手機兩份排版（其一無張數標示），依卡片 ID 去重、取最大張數
    merged = {}
    for li in soup.select("li.card"):
        a = li.select_one("a[href*='card-search/detail/']")
        cnt = li.select_one(".count")
        if not a:
            continue
        m = re.search(r"detail/(\d+)/", a["href"])
        if m:
            cid = int(m.group(1))
            qty = int(cnt.get_text(strip=True)) if cnt else 1
            merged[cid] = max(merged.get(cid, 0), qty)
    if not merged:
        return None, f"牌組編碼 {deck_code} 沒有解析到卡片（可能編碼錯誤）"
    return list(merged.items()), None


@app.post("/api/import-deck")
def api_import_deck():
    """牌組匯入：貼牌表文字，解析成卡片清單。

    支援格式：
      - YDK 檔內容（遊戲王，數字行＝卡片密碼，重複＝張數）
      - 「3 灰流麗」「灰流麗 x3」「灰流麗」等文字行
      - 寶可夢可帶卡片編號：「2 噴火龍ex 125/108」
    輸入: {"game": "ygo"|"pkm", "text": "..."}
    輸出: {"items": [{card..., "qty": n}], "unmatched": [...]}
    """
    payload = request.get_json(force=True)
    game = payload.get("game", "ygo")
    text = (payload.get("text") or "").strip()
    conn = get_conn()
    counts = {}   # card_id -> qty
    cards = {}    # card_id -> card dict
    unmatched = []

    # 寶可夢官方牌組編碼（XXXXXX-XXXXXX-XXXXXX 或牌組頁網址）
    code_m = re.search(r"([A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6})", text)
    if game == "pkm" and code_m and len(text) < 200:
        entries, err = fetch_pkm_deck(code_m.group(1))
        if err:
            conn.close()
            return jsonify({"items": [], "unmatched": [err]})
        items = []
        for card_id, qty in entries:
            row = conn.execute(
                "SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if row:
                items.append({"card": {**dict(row), "game": "pkm",
                                       "image_url": f"/img/pkm/{row['id']}"},
                              "qty": qty})
            else:
                unmatched.append(f"卡片 ID {card_id}（資料庫未收錄）")
        conn.close()
        return jsonify({"items": items, "unmatched": unmatched})

    def add(card, qty):
        counts[card["id"]] = counts.get(card["id"], 0) + qty
        cards[card["id"]] = card

    qty_re = re.compile(
        r"^(?:(\d{1,2})[xX×*]?\s+)?(.+?)(?:\s*[xX×*]\s*(\d{1,2}))?$")
    num_re = re.compile(r"\b(\d{1,3}/[0-9A-Za-z-]+)\b")

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!", "//")):
            continue  # YDK 註解/區段行
        if game == "ygo" and re.fullmatch(r"\d{5,9}", line):
            # YDK 卡片密碼
            row = conn.execute(
                "SELECT * FROM ygo_cards WHERE id=?", (int(line),)).fetchone()
            if row:
                add({"id": row["id"], "game": "ygo", "name": row["name_tc"],
                     "name_jp": row["name_jp"], "collector_number": None,
                     "rarity": None, "image_url": ygo_img_url(row["id"])}, 1)
            else:
                unmatched.append(line)
            continue
        m = qty_re.match(line)
        qty = int(m.group(1) or m.group(3) or 1)
        name = m.group(2).strip()
        if not name:
            unmatched.append(raw)
            continue
        if game == "gcg":
            row = conn.execute(
                "SELECT * FROM gundam_cards WHERE detail_fetched=1 "
                "AND (id=? OR name_tc=?) ORDER BY id LIMIT 1",
                (name.upper(), name)).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM gundam_cards WHERE detail_fetched=1 "
                    "AND name_tc LIKE ? ORDER BY id LIMIT 1",
                    (f"%{name}%",)).fetchone()
            if row:
                add(gcg_card_dict(row), qty)
            else:
                unmatched.append(raw)
            continue
        if game == "ygo":
            hits = search_ygo(conn, name, limit=1)
            if hits:
                add(hits[0], qty)
            else:
                unmatched.append(raw)
        else:
            num_m = num_re.search(name)
            row = None
            if num_m:
                name_part = name[:num_m.start()].strip() or None
                sql = ("SELECT * FROM cards WHERE detail_fetched=1 "
                       "AND collector_number=?")
                params = [num_m.group(1)]
                if name_part:
                    sql += " AND name LIKE ?"
                    params.append(f"%{name_part}%")
                row = conn.execute(sql + " ORDER BY id DESC", params).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM cards WHERE detail_fetched=1 AND name=? "
                    "ORDER BY id DESC", (name,)).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM cards WHERE detail_fetched=1 AND name LIKE ? "
                    "ORDER BY length(name), id DESC", (f"%{name}%",)).fetchone()
            if row:
                add({**dict(row), "game": "pkm",
                     "image_url": f"/img/pkm/{row['id']}"}, qty)
            else:
                unmatched.append(raw)
    conn.close()
    return jsonify({
        "items": [{"card": cards[cid], "qty": q} for cid, q in counts.items()],
        "unmatched": unmatched,
    })


def _card_listings(conn, game, card_id, rarity, lang, art):
    """單張卡查露天（濾價格/現貨、依信心＋價格排序）。

    與 /api/compare 共用同一份 `_listing_cache`（10 分鐘），所以剛比過價或
    設過通知的卡再查會直接命中快取，不重打露天。快取鍵的 card_id 型別與
    compare 一致（寶可夢/遊戲王用數字、鋼彈用字串）才吃得到同一份快取。
    """
    key_id = int(card_id) if game in ("pkm", "ygo") else str(card_id)
    # 鋼彈稀有度是卡片固有屬性（含異圖 +／++），前端不會傳，改用卡片實際稀有度，
    # 讓快取鍵與 /api/compare 一致、且異圖過濾生效
    gcg_row = ga_row = None
    if game == "gcg":
        gcg_row = conn.execute(
            "SELECT * FROM gundam_cards WHERE id=?", (key_id,)).fetchone()
        if not gcg_row:
            return []
        rarity = gcg_row["rarity"]
    elif game == "ga":
        # GA 稀有度是版本固有屬性；變動維度是普卡/閃卡（由 lang 承載）
        ga_row = conn.execute(
            "SELECT * FROM ga_cards WHERE id=?", (key_id,)).fetchone()
        if not ga_row:
            return []
        rarity = ga_row["rarity_label"]
    cache_key = (game, key_id, rarity, lang, art)
    cached = _listing_cache.get(cache_key)
    if cached and time.time() - cached[0] < LISTING_CACHE_TTL:
        return cached[1]
    if game == "ygo":
        row = conn.execute(
            "SELECT * FROM ygo_cards WHERE id=?", (key_id,)).fetchone()
        if not row:
            return []
        from konami import get_printings
        printings = get_printings(conn, row["id"]) or []
        codes = list(dict.fromkeys(
            p["code"] for p in reversed(printings) if p["code"]))
        names = [row["name_tc"], row["name_cnocg"], row["name_md"],
                 row["name_sc"], row["name_jp"]]
        listings = find_listings_for_ygo(
            [n for n in names if n], rarity, lang, codes=codes, art=art)
    elif game == "gcg":
        listings = find_listings_for_gundam(
            gcg_row["name_tc"], gcg_row["id"], lang, rarity=rarity)
    elif game == "ga":
        listings = find_listings_for_ga(
            ga_row["name"], ga_row["set_prefix"], ga_row["collector_number"],
            rarity=rarity, foil=lang)
    else:
        row = conn.execute(
            "SELECT * FROM cards WHERE id=?", (key_id,)).fetchone()
        if not row:
            return []
        listings = find_listings_for_card(
            row["name"], row["collector_number"], rarity)
    listings = [l for l in listings if l["price"] and (l["stock"] or 0) > 0]
    listings = drop_price_outliers(listings)
    listings.sort(key=lambda l: (CONFIDENCE_ORDER[l["confidence"]], l["price"]))
    _listing_cache[cache_key] = (time.time(), listings)
    return listings


@app.post("/api/quote")
def api_quote():
    """設目標價前的即時報價：查這張卡（含條件）目前露天最低價。

    輸入 {game, card_id, rarity?, lang?, art?}；回傳最低價與可靠報價筆數
    （可靠＝strong/weak，與到價通知採信的一致）。查露天需數秒。
    """
    p = request.get_json(force=True)
    game = p.get("game")
    card_id = p.get("card_id")
    if game not in ("pkm", "ygo", "gcg") or card_id in (None, ""):
        return jsonify({"error": "缺少卡片資訊"}), 400
    conn = get_conn()
    try:
        listings = _card_listings(
            conn, game, card_id, p.get("rarity") or None,
            p.get("lang") or None, p.get("art") or None)
    except Exception as e:
        conn.close()
        return jsonify({"error": f"查詢失敗：{e}"}), 500
    conn.close()
    reliable = [l for l in listings if l["confidence"] in ("strong", "weak")]
    reliable_min = min((l["price"] for l in reliable), default=None)
    overall_min = min((l["price"] for l in listings), default=None)
    return jsonify({
        "ok": True,
        "count": len(listings),
        "reliable_count": len(reliable),
        # 以可靠報價的最低價為主（與通知觸發一致），沒有才退回全部的最低
        "min_price": reliable_min if reliable_min is not None else overall_min,
        "reliable_min": reliable_min,
    })


@app.post("/api/compare")
def api_compare():
    """核心功能：對願望清單跑露天搜尋，找出能一次湊齊最多卡的賣家。

    輸入: {"items": [{"card_id": 123, "qty": 1}, ...]}
    輸出: 各賣家的覆蓋卡片、單價、預估總價（含運費），以及跨賣家拆買的最便宜組合。
    """
    payload = request.get_json(force=True)
    items = payload.get("items") or []
    if not items or len(items) > 20:
        return jsonify({"error": "願望清單需為 1–20 張卡（張數多時查詢需數分鐘）"}), 400

    conn = get_conn()
    wants = []  # 統一格式：{key, game, card_id, name, collector_number, rarity, lang, qty}
    for it in items:
        game = it.get("game", "pkm")
        qty = max(1, int(it.get("qty", 1)))
        if game == "ygo":
            row = conn.execute(
                "SELECT * FROM ygo_cards WHERE id=?", (it["card_id"],)).fetchone()
            if row:
                # 官方卡號（Konami 收錄，含快取，新→舊）：查詢與比對的最強依據
                from konami import get_printings
                printings = get_printings(conn, row["id"]) or []
                codes = list(dict.fromkeys(
                    p["code"] for p in reversed(printings) if p["code"]))
                wants.append({
                    "key": f"ygo:{row['id']}", "game": "ygo", "card_id": row["id"],
                    "name": row["name_tc"],
                    # 順序即查詢優先序：前三個（繁中主名、台版官方、MD 譯名）
                    # 用於露天查詢生成，全部用於標題比對
                    "names": [row["name_tc"], row["name_cnocg"], row["name_md"],
                              row["name_sc"], row["name_jp"]],
                    "codes": codes,
                    "collector_number": None,
                    "rarity": (it.get("rarity") or None),
                    "lang": (it.get("lang") or None),
                    "art": (it.get("art") or None), "qty": qty,
                })
        elif game == "gcg":
            row = conn.execute(
                "SELECT * FROM gundam_cards WHERE id=?", (it["card_id"],)).fetchone()
            if row:
                wants.append({
                    "key": f"gcg:{row['id']}", "game": "gcg", "card_id": row["id"],
                    "name": row["name_tc"], "names": None,
                    "collector_number": row["id"],
                    "rarity": row["rarity"],
                    "lang": (it.get("lang") or None), "art": None, "qty": qty,
                })
        elif game == "ga":
            row = conn.execute(
                "SELECT * FROM ga_cards WHERE id=?", (it["card_id"],)).fetchone()
            if row:
                wants.append({
                    "key": f"ga:{row['id']}", "game": "ga", "card_id": row["id"],
                    "name": row["name"], "names": None,
                    "collector_number": f"{row['set_prefix']}-{row['collector_number']}",
                    "set_prefix": row["set_prefix"],
                    "ga_number": row["collector_number"],
                    "rarity": row["rarity_label"],
                    # GA 用 lang 欄位承載「普卡/閃卡」（沿用願望清單 lang 機制）
                    "lang": (it.get("foil") or it.get("lang") or None),
                    "art": None, "qty": qty,
                })
        else:
            row = conn.execute(
                "SELECT * FROM cards WHERE id=?", (it["card_id"],)).fetchone()
            if row:
                wants.append({
                    "key": f"pkm:{row['id']}", "game": "pkm", "card_id": row["id"],
                    "name": row["name"], "names": None,
                    "collector_number": row["collector_number"],
                    "rarity": row["rarity"], "lang": None, "art": None,
                    "qty": qty,
                })
    conn.close()
    if not wants:
        return jsonify({"error": "找不到指定卡片"}), 400

    # 每張卡查露天 → 依賣家彙整（10 分鐘 TTL 快取，降低對露天的請求量）
    per_card_listings = {}
    for w in wants:
        cache_key = (w["game"], w["card_id"], w["rarity"], w["lang"], w.get("art"))
        cached = _listing_cache.get(cache_key)
        if cached and time.time() - cached[0] < LISTING_CACHE_TTL:
            listings = cached[1]
        else:
            if w["game"] == "ygo":
                listings = find_listings_for_ygo(
                    [n for n in w["names"] if n], w["rarity"], w["lang"],
                    codes=w.get("codes"), art=w.get("art"))
            elif w["game"] == "gcg":
                listings = find_listings_for_gundam(
                    w["name"], w["card_id"], w["lang"], rarity=w["rarity"])
            elif w["game"] == "ga":
                listings = find_listings_for_ga(
                    w["name"], w["set_prefix"], w["ga_number"],
                    rarity=w["rarity"], foil=w["lang"])
            else:
                listings = find_listings_for_card(
                    w["name"], w["collector_number"], w["rarity"])
            listings = [l for l in listings if l["price"] and (l["stock"] or 0) > 0]
            listings = drop_price_outliers(listings)
            listings.sort(
                key=lambda l: (CONFIDENCE_ORDER[l["confidence"]], l["price"]))
            _listing_cache[cache_key] = (time.time(), listings)
            if listings:  # 累積價格快照（快取命中不重複記錄）
                hist_conn = get_conn()
                hist_conn.execute(
                    "INSERT INTO price_history (game, card_id, rarity, lang, price) "
                    "VALUES (?,?,?,?,?)",
                    (w["game"], w["card_id"], w["rarity"], w["lang"],
                     min(l["price"] for l in listings)))
                hist_conn.commit()
                hist_conn.close()
        per_card_listings[w["key"]] = listings
        # 本次查詢的行情區間（給前端上色/顯示）
        prices = [l["price"] for l in listings]
        w["market"] = ({"low": min(prices), "high": max(prices), "n": len(prices)}
                       if prices else None)

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
                "lang": w["lang"], "art": w.get("art"), "qty": w["qty"]}

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

    # 雙賣家組合：找出「兩家合買湊齊」的最低總價（各計一次運費）
    pair_best = None
    if len(wants) >= 2:
        cand = seller_results[:30]
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                a, b = cand[i], cand[j]
                offer_a, offer_b = sellers[a["seller_id"]], sellers[b["seller_id"]]
                keys = set(offer_a) | set(offer_b)
                if len(keys) < len(wants):
                    continue
                assign = {}  # key -> (listing, seller_id)
                for key in keys:
                    la, lb = offer_a.get(key), offer_b.get(key)
                    if lb is None or (la is not None and la["price"] <= lb["price"]):
                        assign[key] = (la, a["seller_id"])
                    else:
                        assign[key] = (lb, b["seller_id"])
                used = {}
                subtotal = 0
                for key, (l, sid) in assign.items():
                    subtotal += l["price"] * want_by_key[key]["qty"]
                    used[sid] = max(used.get(sid, 0), l["shipping_cost"] or 0)
                if len(used) < 2:
                    continue  # 全部集中在一家＝單賣家情境，不算組合
                total = subtotal + sum(used.values())
                if pair_best is None or total < pair_best["total"]:
                    pair_best = {
                        "seller_ids": sorted(used),
                        "items": [{**want_info(want_by_key[k]),
                                   "listing": l, "seller_id": sid}
                                  for k, (l, sid) in assign.items()],
                        "subtotal": subtotal,
                        "shipping": sum(used.values()),
                        "total": total,
                    }
    # 只有在「沒有單家全齊」或「兩家組合比最便宜的單家全齊更省」時才提供
    best_single = next((s for s in seller_results if s["complete"]), None)
    if pair_best and best_single and pair_best["total"] >= best_single["total"]:
        pair_best = None

    # 前幾名賣家補上賣場暱稱（從商品頁解析，結果有快取）
    conn = get_conn()
    for s in seller_results[:8]:
        info = resolve_seller(conn, s["seller_id"], s["covered"][0]["listing"]["prod_id"])
        if info:
            s["seller_nick"] = info["nick"]
            s["seller_name"] = info["name"]
            s["store_url"] = f"https://www.ruten.com.tw/store/{info['nick']}/"
            s["credit_rate"] = info.get("credit_rate")
            s["credit_cnt"] = info.get("credit_cnt")
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

    # 各卡歷史參考價（同條件的過往快照）
    conn = get_conn()
    for w in wants:
        row = conn.execute(
            "SELECT MIN(price) AS lo, ROUND(AVG(price)) AS avg, COUNT(*) AS n "
            "FROM price_history WHERE game=? AND card_id=? "
            "AND IFNULL(rarity,'')=IFNULL(?,'') AND IFNULL(lang,'')=IFNULL(?,'') "
            "AND ts >= datetime('now', 'localtime', '-30 days')",
            (w["game"], w["card_id"], w["rarity"], w["lang"])).fetchone()
        w["history"] = ({"low": row["lo"], "avg": row["avg"], "samples": row["n"]}
                        if row and row["n"] else None)
        # 走勢圖序列（每日最低價，最近 30 天）
        w["history_series"] = [
            [r["d"], r["p"]] for r in conn.execute(
                "SELECT date(ts) AS d, MIN(price) AS p FROM price_history "
                "WHERE game=? AND card_id=? AND IFNULL(rarity,'')=IFNULL(?,'') "
                "AND IFNULL(lang,'')=IFNULL(?,'') "
                "AND ts >= datetime('now', 'localtime', '-30 days') "
                "GROUP BY date(ts) ORDER BY d",
                (w["game"], w["card_id"], w["rarity"], w["lang"]))]
    conn.close()

    return jsonify({
        "wishlist": [{**want_info(w), "history": w["history"],
                      "history_series": w["history_series"],
                      "market": w["market"],
                      "image_url": f"/img/{w['game']}/{w['card_id']}"
                          if w["game"] != "ygo" else ygo_img_url(w["card_id"])}
                     for w in wants],
        "sellers": seller_results[:20],
        "pair": pair_best,
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


# ==================== 到價通知 ====================


def _get_setting(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


def _mask_webhook(url):
    """遮罩 Webhook（含 token）：只露出結尾幾碼供辨識已設定哪一條。"""
    if not url:
        return ""
    return "…" + url[-6:]


def _client_id():
    """訪客識別：前端每個瀏覽器產一組隨機 ID，以 X-Client-Id 標頭帶上。

    多人連同一站時，各自的 Webhook 與通知清單靠此區隔（免登入、非嚴謹權限）。
    """
    return (request.headers.get("X-Client-Id") or "").strip()


def _webhook_key(client_id):
    return f"webhook:{client_id}"


def _card_snapshot(conn, game, card_id):
    """取卡名與站內卡圖網址（存進通知供清單顯示）。找不到回傳 (None, None)。"""
    if game == "ygo":
        r = conn.execute(
            "SELECT name_tc FROM ygo_cards WHERE id=?", (card_id,)).fetchone()
        return (r["name_tc"], ygo_img_url(int(card_id))) if r else (None, None)
    if game == "gcg":
        r = conn.execute(
            "SELECT name_tc FROM gundam_cards WHERE id=?", (card_id,)).fetchone()
        return (r["name_tc"], f"/img/gcg/{card_id}") if r else (None, None)
    if game == "ga":
        r = conn.execute(
            "SELECT name, image FROM ga_cards WHERE id=?", (card_id,)).fetchone()
        return (r["name"], f"/img/ga/{r['image']}") if r else (None, None)
    r = conn.execute("SELECT name FROM cards WHERE id=?", (card_id,)).fetchone()
    return (r["name"], f"/img/pkm/{card_id}") if r else (None, None)


@app.get("/api/alerts")
def api_alerts_list():
    """該訪客的通知清單＋自己的 Webhook 狀態＋背景檢查狀態（前端輪詢用）。"""
    cid = _client_id()
    if not cid:
        return jsonify({"alerts": [], "webhook_set": False, "webhook_hint": "",
                        "checking": _alert_check["running"]})
    conn = get_conn()
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM price_alerts WHERE client_id=? ORDER BY id DESC", (cid,))]
    webhook = _get_setting(conn, _webhook_key(cid), "") or ""
    conn.close()
    return jsonify({
        "alerts": alerts,
        "webhook_set": bool(webhook),
        "webhook_hint": _mask_webhook(webhook),
        "checking": _alert_check["running"],
    })


@app.post("/api/alerts")
def api_alert_create():
    """新增到價通知：{game, card_id, target_price, rarity?, lang?, art?}"""
    cid = _client_id()
    if not cid:
        return jsonify({"error": "缺少訪客識別"}), 400
    p = request.get_json(force=True)
    game = p.get("game")
    card_id = str(p.get("card_id") or "").strip()
    if game not in ("pkm", "ygo", "gcg") or not card_id:
        return jsonify({"error": "缺少卡片資訊"}), 400
    try:
        target = int(p.get("target_price"))
    except (TypeError, ValueError):
        return jsonify({"error": "目標價需為數字"}), 400
    if target <= 0:
        return jsonify({"error": "目標價需大於 0"}), 400
    conn = get_conn()
    name, image = _card_snapshot(conn, game, card_id)
    if name is None:
        conn.close()
        return jsonify({"error": "找不到指定卡片"}), 400
    conn.execute(
        "INSERT INTO price_alerts "
        "(client_id, game, card_id, card_name, image_url, rarity, lang, art, "
        "target_price) VALUES (?,?,?,?,?,?,?,?,?)",
        (cid, game, card_id, name, image, p.get("rarity") or None,
         p.get("lang") or None, p.get("art") or None, target))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/alerts/<int:alert_id>")
def api_alert_update(alert_id):
    """更新通知：改目標價 / 暫停啟用 / 重設通知狀態（rearm）。僅限本人的通知。"""
    cid = _client_id()
    p = request.get_json(force=True)
    conn = get_conn()
    a = conn.execute(
        "SELECT id FROM price_alerts WHERE id=? AND client_id=?",
        (alert_id, cid)).fetchone()
    if not a:
        conn.close()
        return jsonify({"error": "找不到通知"}), 404
    sets, params = [], []
    if "target_price" in p:
        try:
            sets.append("target_price=?")
            params.append(int(p["target_price"]))
            sets.append("notified=0")  # 改目標價後重置，讓新價位能再觸發
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"error": "目標價需為數字"}), 400
    if p.get("status") in ("active", "paused"):
        sets.append("status=?")
        params.append(p["status"])
    if p.get("rearm"):
        sets.append("notified=0")
    if not sets:
        conn.close()
        return jsonify({"error": "無可更新欄位"}), 400
    conn.execute(
        f"UPDATE price_alerts SET {','.join(sets)} WHERE id=? AND client_id=?",
        params + [alert_id, cid])
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.delete("/api/alerts/<int:alert_id>")
def api_alert_delete(alert_id):
    cid = _client_id()
    conn = get_conn()
    conn.execute(
        "DELETE FROM price_alerts WHERE id=? AND client_id=?", (alert_id, cid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/settings/webhook")
def api_set_webhook():
    """設定 / 清除該訪客自己的 Discord Webhook 網址。"""
    cid = _client_id()
    if not cid:
        return jsonify({"error": "缺少訪客識別"}), 400
    p = request.get_json(force=True)
    url = (p.get("webhook") or "").strip()
    if url and not DISCORD_WEBHOOK_RE.match(url):
        return jsonify({"error": "看起來不是有效的 Discord Webhook 網址"}), 400
    conn = get_conn()
    _set_setting(conn, _webhook_key(cid), url)
    conn.close()
    return jsonify({"ok": True, "webhook_set": bool(url),
                    "webhook_hint": _mask_webhook(url)})


@app.post("/api/settings/webhook/test")
def api_test_webhook():
    """送一則測試訊息到該訪客自己的 Webhook。"""
    from notify import send_test
    cid = _client_id()
    conn = get_conn()
    url = _get_setting(conn, _webhook_key(cid), "") or "" if cid else ""
    conn.close()
    if not url:
        return jsonify({"ok": False, "error": "尚未設定 Webhook"}), 400
    ok = send_test(url)
    return jsonify({"ok": ok,
                    "error": None if ok else "傳送失敗，請確認 Webhook 網址"})


@app.post("/api/alerts/check")
def api_alerts_check():
    """立即檢查該訪客的通知（背景執行；前端輪詢 /api/alerts 的 checking）。"""
    import threading

    import alerts as alerts_mod

    cid = _client_id()
    if not cid:
        return jsonify({"error": "缺少訪客識別"}), 400
    if _alert_check["running"]:
        return jsonify({"running": True, "message": "檢查進行中…"})

    def run():
        _alert_check["running"] = True
        try:
            conn = get_conn()
            res = alerts_mod.check_all(conn, client_id=cid)
            conn.close()
            _alert_check["fired"] = res["fired"]
            _alert_check["ts"] = time.time()
        finally:
            _alert_check["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"running": True, "message": "開始檢查，稍候即可看到結果"})


if __name__ == "__main__":
    # 綁 0.0.0.0：同一內網（區域網路）的其他電腦也能連
    # （用本機 IP:5000 開啟）。純內網自用，非對外公開網站。
    app.run(host="0.0.0.0", port=5000, debug=False)
