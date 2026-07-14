"""露天拍賣搜尋模組：搜商品、解析標題比對卡片與稀有度。

使用露天前端網頁本身呼叫的公開 JSON API（rtapi.ruten.com.tw）。
注意：此為非官方介面，露天改版即失效；請控制請求頻率避免被封鎖。
"""
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
        price_range = p.get("PriceRange") or [None, None]
        results.append({
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
        })
    return results
