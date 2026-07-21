"""露天拍賣搜尋模組：搜商品、解析標題比對卡片與稀有度。

使用露天前端網頁本身呼叫的公開 JSON API（rtapi.ruten.com.tw）。
注意：此為非官方介面，露天改版即失效；請控制請求頻率避免被封鎖。
"""
import json
import re
import time
from pathlib import Path

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

# 遊戲王稀有度（OCG）：標準標籤 → 標題常見寫法（台灣行話，經露天實證）
# 每組第一個非英文詞＝主要俗稱，會拿去當露天查詢詞
YGO_RARITIES = {
    "N": ["N", "普卡", "平卡", "普通"],
    "R": ["R", "銀字"],
    "NPR": ["NPR", "NP", "普鑽", "彩鑽"],       # 普卡平行閃（20AP/PAC1 等）
    "SR": ["SR", "亮面"],
    "UR": ["UR", "金亮", "金字"],
    "SEC": ["SEC", "半鑽", "SE", "SER", "斜鑽", "鑽石"],
    "EXSEC": ["EXSEC", "全鑽", "EXSE", "ESR", "EX鑽"],
    "UTR": ["UTR", "浮雕"],
    "CR": ["CR", "雕鑽", "雕面"],
    "HR": ["HR", "雷射"],
    "GR": ["GR"],                                # 黃金（「黃金」不入典：黃金卿等卡名誤中）
    "20th": ["20TH", "紅鑽", "20th", "二十"],
    "QCSE": ["QCSE", "金鑽", "QCSER", "QCSR", "25TH", "25th", "QC"],
    "PSER": ["PSER", "白鑽", "PSE"],
    "PGR": ["PGR", "PG"],
}

# 紙種（發行語言）：標籤 → 標題常見寫法；卡號中的 -KR/-EN/-SC 另以 regex 判斷
# 台灣市場慣例：日紙較貴、賣家一定明標；「完全沒標」一律推定為韓紙。
# 因此選日紙只收明標的（卡號 -JP 不算數：韓版卡也常標日版卡號），
# 選韓紙則收明標韓紙＋未標示者。
YGO_LANGS = {
    # 「日文」「日本正版」只是描述卡片語言/正版來源，不等於賣日紙，不列入
    "日紙": ["日紙", "日版"],
    "韓紙": ["韓紙", "韓版", "韓文", "韓字", "KR"],
    "英紙": ["英紙", "美版", "英版", "英文", "美英", "亞英", "EN"],
    "簡中": ["簡中", "简中", "簡體", "简体", "簡版", "SC"],
}
# 插畫版本：超框（插畫超出卡框的異圖版本）標題常見寫法
# 市場慣例與紙種類似：超框版賣家會明標，沒標的視為一般版
YGO_ART_WORDS = ["超框", "異圖", "异图", "OF"]

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

# 遊戲王譯名同義詞字典（ygo_aliases.json，可自行增補）
_ALIAS_PATH = Path(__file__).parent / "ygo_aliases.json"
try:
    YGO_ALIASES = json.loads(_ALIAS_PATH.read_text(encoding="utf-8"))["aliases"]
except (OSError, KeyError, ValueError):
    YGO_ALIASES = {}


def expand_variants(names, cap=24):
    """把卡名清單依同義詞字典做雙向替換展開（遞移、去重、上限 cap）。"""
    variants, stack = [], [n for n in names if n]
    while stack and len(variants) < cap:
        n = stack.pop(0)
        if n in variants:
            continue
        variants.append(n)
        for key, alts in YGO_ALIASES.items():
            forms = [key] + alts
            for src in forms:
                if src in n:
                    for dst in forms:
                        if dst != src:
                            m = n.replace(src, dst)
                            if m not in variants:
                                stack.append(m)
    return variants


def _squash(s):
    """比對用正規化：全形轉半形、大寫、去空白/間隔號/連字號。"""
    return (_norm(s).replace(" ", "").replace("·", "")
            .replace("・", "").replace("-", ""))


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


def title_matches_ygo(title, variants, segments=None, rarity=None, lang=None,
                      codes=None, art=None):
    """判斷露天商品標題是否對應遊戲王卡＋稀有度＋紙種。

    variants：卡名所有變體（含別名展開），標題含任一（忽略間隔號/空白）即算命中。
    codes：這張卡的官方卡號（如 LOCH-JP001）；標題含卡號＝確定是這張卡，
           不受譯名混亂影響。
    segments：人名段變體（「救祓少女·馬爾法」的「馬爾法」等）；
              只命中人名段時信心上限為 weak。
    回傳 'strong' / 'weak' / 'maybe' / None
    """
    t_squash = _squash(title)
    name_hit = any(_squash(v) in t_squash for v in variants if v)
    if not name_hit and codes:
        name_hit = any(_squash(c) in t_squash for c in codes if c)
    seg_only = False
    if not name_hit and segments:
        if any(len(s) >= 2 and _squash(s) in t_squash for s in segments):
            seg_only = True
        else:
            return None
    elif not name_hit:
        return None
    if any(w in title for w in EXCLUDE_WORDS):
        return None
    tokens = set(re.split(r"[^A-Z0-9]+", _norm(title)))

    if art:  # 插畫版本過濾（超框版賣家會明標，沒標的視為一般版）
        art_hit = any((w in tokens) if w.isascii() else (w in title)
                      for w in YGO_ART_WORDS)
        if art == "一般" and art_hit:
            return None
        if art == "超框" and not art_hit:
            return None

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
        others_word = any(word_hits[l] for l in YGO_LANGS if l != lang)
        if lang == "日紙":
            # 台灣慣例：沒明確標日紙一律視為韓紙；-JP 卡號不算證據
            if not word_hits["日紙"]:
                return None
        elif lang == "韓紙":
            if word_hits["韓紙"] or code_hits["韓紙"]:
                pass
            elif others_word or code_hits["英紙"] or code_hits["簡中"]:
                return None  # 明標了別的紙種
            else:
                unknown += 1  # 未標示 → 依台灣慣例推定韓紙（信心降級）
        else:  # 英紙 / 簡中
            if word_hits[lang] or code_hits.get(lang):
                pass
            elif others_word or any(code_hits[l] for l in code_hits if l != lang):
                return None
            else:
                unknown += 1
    if unknown == 0:
        conf = "strong"
    elif unknown == 2:
        conf = "maybe"
    else:
        conf = "weak"
    if seg_only and conf == "strong":
        conf = "weak"  # 只命中人名段時降一級
    return conf


_KANA_RE = re.compile(r"[぀-ヿ]")


def find_listings_for_ygo(names, rarity=None, lang=None, limit=40, codes=None,
                          art=None):
    """遊戲王：搜露天並比對。

    賣家譯名極不統一（官方譯名/社群譯名/音譯差異），策略：
      1. 官方卡號（如 LOCH-JP001）優先查詢——賣家標題幾乎都寫卡號，
         不受譯名影響（codes 來自 Konami 收錄資料）
      2. 卡名依同義詞字典展開成多個變體，依序查露天，結果合併去重
      3. 標題比對認得卡號、所有卡名變體與人名段（信心分級）
    查詢只帶「卡名＋稀有度」（露天是全詞 AND，詞多會搜不到）；
    紙種在標題比對階段過濾（字面優先，卡號 -JP/-KR/-EN 輔助）。
    """
    variants = expand_variants(names)          # 標題比對用（全部）
    query_bases = expand_variants(names[:3])   # 查詢生成用（主名＋台版官方＋MD 譯名）

    def _segments_of(vs):
        """取卡名最後一段當人名段（「·」「・」或空白分隔）。"""
        out = []
        for v in vs:
            parts = re.split(r"[·・\s]+", v.strip())
            if len(parts) >= 2 and parts[-1]:
                out.append(parts[-1])
        return list(dict.fromkeys(out))

    segments = _segments_of(variants)

    # 查詢候選（露天是全詞 AND，詞越多越搜不到）：
    #   多段卡名 → 直接用「系列 人名」兩詞，不加「遊戲王」前綴
    #   單段短卡名 → 加「遊戲王」前綴避免撞到別的商品
    #   人名段查詢保證有配額（擴大召回，靠標題比對把關）
    zh_bases = [v for v in query_bases if not _KANA_RE.search(v)]
    # 稀有度查詢詞：代號＋主要中文俗稱（賣家常只寫「金鑽」不寫 QCSE）
    r_terms = [None]
    if rarity:
        aliases = YGO_RARITIES.get(rarity, [rarity])
        slang = next((a for a in aliases if not a.isascii()), None)
        r_terms = [rarity] + ([slang] if slang else [])
    name_queries, seg_queries = [], []
    for v in zh_bases:
        flat = re.sub(r"[·・\s]+", " ", v).strip()
        for t in r_terms:
            if t:
                name_queries.append(f"{flat} {t}")
            elif " " in flat or len(flat) >= 5:
                name_queries.append(flat)
            else:
                name_queries.append(f"遊戲王 {flat}")
    for s in _segments_of(zh_bases)[:2]:
        seg_queries.append(f"{s} {rarity}" if rarity else f"遊戲王 {s}")
    code_queries = [c for c in (codes or [])][:2]  # 卡號查詢優先、精準度最高
    n_name = 3 if seg_queries else 4
    queries = list(dict.fromkeys(
        code_queries + name_queries[:n_name] + seg_queries))[:6]

    seen_ids, results = set(), []
    for q in queries:
        try:
            products = search_products(q, limit=limit)
        except Exception:
            continue
        for p in products:
            if p["ProdId"] in seen_ids:
                continue
            seen_ids.add(p["ProdId"])
            confidence = title_matches_ygo(
                p.get("ProdName", ""), variants, segments, rarity, lang, codes,
                art)
            if confidence:
                results.append(_listing_dict(p, confidence))
        if len(results) >= 25:  # 已夠多就不再打下一個查詢
            break
    return results


# 鋼彈 GCG 版本（發行語言）：日版／美版（英文）。無韓版。
GUNDAM_LANGS = {
    "日版": ["日版", "日文版", "日紙", "日本", "JAPAN", "JP"],
    "美版": ["美版", "英文版", "英版", "美英", "ENGLISH", "EN"],
}

# 鋼彈異圖平行閃：賣家標題常見寫法（除了稀有度後綴 +／++ 之外的字樣）
GUNDAM_ART_WORDS = ["異圖", "异图", "パラレル"]

# 稀有度後綴 +／++ 偵測：基礎稀有度字母＋緊跟的一串 +（允許中間空白，如「LR +」）。
# 只認「字母後面緊跟 +」的寫法——英文單字（Card→C、Rising→R）字母後不是 +，
# 故不會被誤判成稀有度標記。字母群列長者在前（LR 先於 R）避免 LR 被讀成 R。
_GUNDAM_PLUS_RE = re.compile(r"(LR|SR|UR|RR|R|U|C|P)\s*(\++)", re.I)


def _gundam_rarity_parts(rarity):
    """稀有度 → (基礎稀有度, 平行閃層級)。

    'LR ++' → ('LR', 2)、'C +' → ('C', 1)、'LR' → ('LR', 0)、'P' → ('P', 0)。
    """
    if not rarity:
        return None, 0
    r = rarity.replace(" ", "").replace("＋", "+").upper()
    return r.replace("+", ""), r.count("+")


def _gundam_title_art(title):
    """解析標題的稀有度平行閃標記。回傳 (最大plus層級, 是否標異圖, {(字母, plus數)})。

    tokens 保留「字母＋plus層級」讓比對認得是哪個稀有度的 +（C+ ≠ R+）；
    最大plus層級供基礎版排除任何平行閃用。
    """
    t = title.replace("＋", "+")
    tokens, maxplus = set(), 0
    for m in _GUNDAM_PLUS_RE.finditer(t):
        letter, plus = m.group(1).upper(), len(m.group(2))
        tokens.add((letter, plus))
        maxplus = max(maxplus, plus)
    has_iso = any(w in title for w in GUNDAM_ART_WORDS)
    return maxplus, has_iso, tokens


def find_listings_for_gundam(name, card_no, lang=None, rarity=None, limit=40):
    """鋼彈 GCG：搜露天並比對。

    卡號（GD01-001）是最強訊號、賣家幾乎都會標；卡名（鋼彈/高達互通）為輔。
    版本（日版/美版）與**異圖平行閃**在標題比對階段過濾。

    異圖平行卡（GD01-001_p1）：賣家不標 _pN 後綴，但用稀有度後綴 +／++（如
    LR+、LR++）或「異圖」字樣區分（露天實證：基礎 LR 約 30–120、LR+ 約 279+、
    LR++ 上萬）。用卡片稀有度的 + 層級比對標題的 + 層級——基礎版（無 +）排除掉
    帶 +／異圖 的商品，異圖版只收對應層級。卡號還原成基礎卡號查詢／比對。
    沒帶 rarity 時不做異圖過濾（維持舊行為）。
    """
    card_no = re.sub(r"_p\d+$", "", card_no)
    base_r, want_plus = _gundam_rarity_parts(rarity)
    queries = [f"鋼彈 {card_no}", f"鋼彈 {name}"]
    if want_plus >= 1:
        # 異圖版加一條精準查詢：價格由低到高排序下，昂貴的異圖常被便宜基礎版擠掉
        queries.insert(0, f"鋼彈 {card_no} 異圖")
    seen_ids, results = set(), []
    for q in queries:
        try:
            products = search_products(q, limit=limit)
        except Exception:
            continue
        for p in products:
            if p["ProdId"] in seen_ids:
                continue
            seen_ids.add(p["ProdId"])
            title = p.get("ProdName", "")
            t = _squash(title)
            no_hit = _squash(card_no) in t
            # 卡名比對：鋼彈/高達視為等義，去掉後比對其餘名稱
            name_norm = _squash(name).replace("鋼彈", "").replace("高達", "")
            title_norm = t.replace("鋼彈", "").replace("高達", "")
            name_hit = bool(name_norm) and name_norm in title_norm
            if not (no_hit or name_hit):
                continue
            if any(w in title for w in EXCLUDE_WORDS):
                continue
            # 異圖平行閃過濾（用稀有度字母＋ + 層級；沒帶 rarity 就不過濾）
            title_plus, has_iso, tokens = _gundam_title_art(title)
            if rarity is not None:
                if want_plus == 0:
                    # 基礎版：排除帶任何 +／異圖 的平行閃
                    if title_plus >= 1 or has_iso:
                        continue
                elif (base_r, want_plus) not in tokens:
                    # 異圖版：標題須有「該稀有度字母＋對應 + 層級」（C+ 不算 R+）
                    continue
            conf = "strong" if no_hit else "weak"
            # 異圖版且標題明標「異圖」＋卡號 → 最有把握
            if want_plus >= 1 and has_iso and no_hit:
                conf = "strong"
            if lang:
                aliases = GUNDAM_LANGS.get(lang, [lang])
                others = [a for lbl, al in GUNDAM_LANGS.items()
                          if lbl != lang for a in al]
                if any(a in title for a in aliases):
                    pass
                elif any(a in title for a in others):
                    continue  # 明標了別的版本
                else:
                    conf = "weak" if conf == "strong" else "maybe"
            results.append(_listing_dict(p, conf))
        if len(results) >= 25:
            break
    return results


NICK_RE = re.compile(r'"nick":"([^"]+)"')
BOARD_NAME_RE = re.compile(r'"boardName":"([^"]*)"')
CREDIT_RATE_RE = re.compile(r'"creditRate":([\d.]+)')
CREDIT_CNT_RE = re.compile(r'"creditCnt":(\d+)')


def resolve_seller(conn, seller_id, sample_prod_id):
    """賣家數字 ID → 賣場暱稱＋評價（從該賣家任一商品頁解析後快取）。

    回傳 {nick, name, credit_rate, credit_cnt}；解析失敗回傳 None
    並快取空值避免重複嘗試。
    """
    row = conn.execute(
        "SELECT nick, name, credit_rate, credit_cnt FROM ruten_sellers "
        "WHERE seller_id=?", (str(seller_id),)).fetchone()
    # 舊快取沒有評價欄位時重新抓一次補齊
    if row and (row["credit_rate"] is not None or not row["nick"]):
        return ({"nick": row["nick"], "name": row["name"],
                 "credit_rate": row["credit_rate"], "credit_cnt": row["credit_cnt"]}
                if row["nick"] else None)
    nick = name = rate = cnt = None
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
            m = CREDIT_RATE_RE.search(r.text)
            rate = round(float(m.group(1)), 2) if m else None
            m = CREDIT_CNT_RE.search(r.text)
            cnt = int(m.group(1)) if m else None
    except Exception:
        pass
    conn.execute(
        "INSERT OR REPLACE INTO ruten_sellers VALUES (?,?,?,?,?)",
        (str(seller_id), nick, name, rate, cnt))
    conn.commit()
    time.sleep(DELAY)
    return ({"nick": nick, "name": name, "credit_rate": rate, "credit_cnt": cnt}
            if nick else None)


def drop_price_outliers(listings, rel_floor=0.1, min_n=4):
    """剔除明顯過低的離群價，避免污染「最低價」。

    露天常見雜訊：多規格商品把最便宜規格的價格當商品價（標題對到卡、
    但那個價其實是同賣場另一張便宜卡）、或 1 元起標。做法：商品數達
    min_n 時取中位數，剔除低於「中位數 × rel_floor」者——相對門檻會隨
    卡片價位縮放（便宜卡的便宜商品不會被誤刪），商品太少則不過濾。

    傳入的 listings 應已濾掉無價格者；回傳保留原順序。
    """
    prices = sorted(l["price"] for l in listings if l["price"])
    if len(prices) < min_n:
        return listings
    median = prices[len(prices) // 2]
    floor = median * rel_floor
    return [l for l in listings if l["price"] >= floor]


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
