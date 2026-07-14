"""露天拍賣搜尋模組：搜商品、解析標題比對卡片與稀有度。

使用露天前端網頁本身呼叫的公開 JSON API（rtapi.ruten.com.tw）。
注意：此為非官方介面，露天改版即失效；請控制請求頻率避免被封鎖。
"""
import json
import re
import time

import requests

SEARCH_URL = "https://rtapi.ruten.com.tw/api/search/v3/index.php/core/prod"
PROD_URL = "https://rtapi.ruten.com.tw/api/prod/v2/index.php/prod"
ITEM_PAGE = "https://www.ruten.com.tw/item/show?{id}"
DELAY = 0.4

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 稀有度俗稱字典：標題裡的寫法 → 標準標籤
RARITY_ALIASES = {
    "SAR": ["SAR", "特典藝術"],
    "AR": ["AR"],
    "SR": ["SR"],
    "SSR": ["SSR"],
    "HR": ["HR"],
    "UR": ["UR", "金卡"],
    "RR": ["RR"],
    "RRR": ["RRR"],
    "R": ["R"],
    "U": ["U"],
    "C": ["C"],
    "S": ["S"],
    "K": ["K"],
    "A": ["A"],
    "ACE": ["ACE"],
    "MA": ["MA"],
    "MUR": ["MUR"],
    "BWR": ["BWR"],
    "PR": ["PR", "PROMO", "普卡促銷"],
    "TR": ["TR"],
}

# 遊戲王稀有度（OCG）：標準標籤 → 標題常見寫法（含台灣行話）
YGO_RARITIES = {
    "N": ["N", "普卡", "平卡", "普通"],
    "R": ["R", "銀字"],
    "SR": ["SR", "亮面"],
    "UR": ["UR", "金亮", "金字"],
    "SEC": ["SEC", "SE", "SER", "鑽石"],
    "UTR": ["UTR", "浮雕"],
    "EXSEC": ["EXSEC", "EX鑽"],
    "CR": ["CR", "雕鑽", "雕面"],
    "HR": ["HR", "雷射"],
    "20th": ["20TH", "20th", "紅鑽", "二十"],
    "QCSE": ["QCSE", "25TH", "25th", "QC", "銀鑽"],
    "PSER": ["PSER", "白鑽"],
}

# 紙種（發行語言）：標籤 → 標題常見寫法；卡號中的 -JP/-KR/-EN 另以 regex 判斷
# 「英紙」含美版/亞英：選日紙或韓紙時，寫明美英版的商品會被排除
YGO_LANGS = {
    "日紙": ["日紙", "日版", "日文", "日字", "JP"],
    "韓紙": ["韓紙", "韓版", "韓文", "韓字", "KR"],
    "英紙": ["英紙", "美版", "英版", "英文", "美英", "亞英", "EN"],
    "簡中": ["簡中", "简中", "簡體", "简体", "簡版", "SC"],
}
YGO_LANG_CODE_RE = {
    "日紙": re.compile(r"-JP[A-Z]?\d+", re.I),   # 如 PAC1-JP016、TT01-JPB11
    "韓紙": re.compile(r"-KR[A-Z]?\d+", re.I),
    "英紙": re.compile(r"-(EN|AE)[A-Z]?\d+", re.I),  # 如 MP19-EN137、DI02-AE011
    "簡中": re.compile(r"-SC[A-Z]?\d+", re.I),
}

# 明顯不是單卡的商品（套組、代抓、福袋等）
EXCLUDE_WORDS = ["整盒", "整箱", "福袋", "抽獎", "代抽", "禮盒", "補充包",
                 "未拆", "原盒", "卡冊", "卡套", "自組", "牌組出租",
                 "同人", "工藝卡", "自製", "自印", "DIY", "代購"]


def search_products(query, limit=40):
    """搜露天，回傳商品詳情 list。"""
    r = session.get(SEARCH_URL, params={
        "q": query, "type": "direct", "sort": "prc/ac",  # 價格由低到高
        "offset": 1, "limit": limit,
    }, timeout=20)
    r.raise_for_status()
    rows = r.json().get("Rows", [])
    ids = [row["Id"] for row in rows]
    if not ids:
        return []
    time.sleep(DELAY)
    details = []
    # prod API 一次最多帶 20 個 id
    for i in range(0, len(ids), 20):
        batch = ids[i:i + 20]
        r2 = session.get(PROD_URL, params={"id": ",".join(batch)}, timeout=20)
        r2.raise_for_status()
        details += r2.json()
        time.sleep(DELAY)
    return details


def _norm(s):
    """全形轉半形、去空白、轉大寫，用於標題比對。"""
    s = s or ""
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    return s.upper()


def title_matches_card(title, card_name, collector_number=None, rarity=None):
    """判斷露天商品標題是否對應指定卡片＋稀有度。

    規則：
      1. 標題須包含卡名（去掉空白比對）
      2. 排除明顯的套組/周邊商品
      3. 若指定卡片編號（如 094/081），標題含該編號 → 強匹配
      4. 若指定稀有度，用字典比對標題中的稀有度字樣；
         標題完全沒提稀有度時視為「不確定」（回傳 'maybe'）
    回傳 'strong' / 'weak' / 'maybe' / None
    """
    t = _norm(title).replace(" ", "")
    name = _norm(card_name).replace(" ", "")
    if name not in t:
        return None
    if any(w in title for w in EXCLUDE_WORDS):
        return None

    num_hit = False
    if collector_number:
        # 094/081 也可能寫成 94/81 或 094-081
        m = re.match(r"(\d+)/(\d+)", collector_number)
        if m:
            a, b = m.group(1), m.group(2)
            variants = [f"{a}/{b}", f"{a}-{b}",
                        f"{int(a)}/{int(b)}", f"{int(a)}-{int(b)}"]
            num_hit = any(v in t for v in variants)

    if rarity:
        aliases = RARITY_ALIASES.get(rarity.upper(), [rarity.upper()])
        # 用 token 邊界比對，避免 "SR" 誤中 "SSR"、"R" 誤中 "SR"
        tokens = set(re.split(r"[^A-Z0-9]+", _norm(title)))
        rarity_hit = any(a in tokens for a in aliases if re.match(r"^[A-Z]+$", a)) \
            or any(a in title for a in aliases if not re.match(r"^[A-Z]+$", _norm(a)))
        conflicting = [lbl for lbl, als in RARITY_ALIASES.items()
                       if lbl != rarity.upper()
                       and any(a in tokens for a in als if re.match(r"^[A-Z]+$", a))]
        if rarity_hit and num_hit:
            return "strong"
        if rarity_hit:
            return "weak"
        if conflicting:
            return None  # 標題寫了別的稀有度
        return "maybe"  # 標題沒提稀有度
    return "strong" if num_hit else "weak"


def title_matches_ygo(title, names, rarity=None, lang=None):
    """判斷露天商品標題是否對應遊戲王卡＋稀有度＋紙種（日紙/韓紙）。

    names：可接受的卡名清單（繁中/簡中/日文），標題含任一即算命中。
    回傳 'strong'（稀有度+紙種都符合）/ 'weak'（部分符合）/ 'maybe'（標題未標示）/ None
    """
    t_norm = _norm(title).replace(" ", "")
    if not any(_norm(n).replace(" ", "") in t_norm for n in names if n):
        return None
    if any(w in title for w in EXCLUDE_WORDS):
        return None
    tokens = set(re.split(r"[^A-Z0-9]+", _norm(title)))

    def hit(aliases):
        return any(
            (a.upper() in tokens) if re.fullmatch(r"[A-Za-z0-9]+", a) else (a in title)
            for a in aliases)

    unknown = 0
    if rarity:
        aliases = YGO_RARITIES.get(rarity, [rarity])
        conflicting = any(
            lbl != rarity and hit(als) for lbl, als in YGO_RARITIES.items()
            # SR/UR 的字母別名是 SEC/EXSEC 等的子字串已用 token 邊界處理
        )
        if hit(aliases):
            pass
        elif conflicting:
            return None  # 標題寫了別的稀有度
        else:
            unknown += 1
    if lang:
        # 字面聲明優先於卡號推斷：韓版卡常被標日版卡號（如「韓紙 LOCH-JP016」）
        word_hits = {lbl: hit(als) for lbl, als in YGO_LANGS.items()}
        code_hits = {lbl: bool(rx.search(title))
                     for lbl, rx in YGO_LANG_CODE_RE.items()}
        if word_hits[lang]:
            pass
        elif any(word_hits[l] for l in YGO_LANGS if l != lang):
            return None  # 標題明寫了別的紙種
        elif code_hits.get(lang):
            pass
        elif any(code_hits.values()):
            return None  # 卡號屬於別的語言版本
        else:
            unknown += 1
    if unknown == 0:
        return "strong"
    return "maybe" if unknown == 2 else "weak"


def find_listings_for_ygo(names, rarity=None, lang=None, limit=40):
    """遊戲王：搜露天並比對。names[0] 用於搜尋（繁中名），全部用於標題比對。

    查詢只帶「卡名＋稀有度」（露天是全詞 AND，詞多會搜不到）；
    紙種在標題比對階段過濾（含卡號 -JP/-KR 判斷）。
    """
    query = f"{names[0]} {rarity}" if rarity else f"遊戲王 {names[0]}"
    products = search_products(query, limit=limit)
    results = []
    for p in products:
        confidence = title_matches_ygo(p.get("ProdName", ""), names, rarity, lang)
        if not confidence:
            continue
        results.append(_listing_dict(p, confidence))
    return results


NICK_RE = re.compile(r'"nick":"([^"]+)"')
BOARD_NAME_RE = re.compile(r'"boardName":"([^"]*)"')


def resolve_seller(conn, seller_id, sample_prod_id):
    """賣家數字 ID → 賣場暱稱（露天無公開 API，從該賣家任一商品頁解析後快取）。

    回傳 {nick, name}；解析失敗回傳 None 並快取空值避免重複嘗試。
    """
    row = conn.execute(
        "SELECT nick, name FROM ruten_sellers WHERE seller_id=?",
        (str(seller_id),)).fetchone()
    if row:
        return {"nick": row["nick"], "name": row["name"]} if row["nick"] else None
    nick = name = None
    try:
        r = session.get(
            f"https://www.ruten.com.tw/item/{sample_prod_id}/", timeout=15)
        if r.ok:
            m = NICK_RE.search(r.text)
            nick = m.group(1) if m else None
            m = BOARD_NAME_RE.search(r.text)
            if m:
                try:  # 內容是 JSON 字串（含 \uXXXX 轉義）
                    name = json.loads(f'"{m.group(1)}"')
                except ValueError:
                    name = None
    except Exception:
        pass
    conn.execute(
        "INSERT OR REPLACE INTO ruten_sellers VALUES (?,?,?)",
        (str(seller_id), nick, name))
    conn.commit()
    time.sleep(DELAY)
    return {"nick": nick, "name": name} if nick else None


def _listing_dict(p, confidence):
    price_range = p.get("PriceRange") or [None, None]
    return {
        "prod_id": p["ProdId"],
        "title": p.get("ProdName"),
        "seller_id": str(p.get("SellerId")),
        "price": price_range[0],
        "shipping_cost": p.get("ShippingCost"),
        "stock": p.get("StockQty"),
        "sold": p.get("SoldQty"),
        "image": ("https://gcs.rimg.com.tw" + p["Image"]) if p.get("Image") else None,
        "url": ITEM_PAGE.format(id=p["ProdId"]),
        "confidence": confidence,
    }


def find_listings_for_card(card_name, collector_number=None, rarity=None, limit=40):
    """搜露天並比對，回傳符合的商品清單。"""
    query = card_name
    if rarity and rarity not in ("無標記",):
        query += f" {rarity}"
    products = search_products(query, limit=limit)
    results = []
    for p in products:
        confidence = title_matches_card(
            p.get("ProdName", ""), card_name, collector_number, rarity)
        if not confidence:
            continue
        results.append(_listing_dict(p, confidence))
    return results
