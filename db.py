"""SQLite 資料庫層：卡牌資料 schema 與共用連線。"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "cards.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id              INTEGER PRIMARY KEY,   -- 官方卡查的卡片 ID（每一列 = 一個印刷版本）
    name            TEXT,                  -- 卡名（同名卡可能有多個印刷版本）
    evolve_marker   TEXT,                  -- 基礎 / 1階進化 / 物品卡 等
    set_alpha       TEXT,                  -- 系列字母（H、J...）
    set_mark        TEXT,                  -- 擴充包標記代碼（如 exp_M5、mth_f）
    collector_number TEXT,                 -- 卡片編號（如 094/081）
    rarity          TEXT,                  -- 稀有度標籤（C/U/R/RR/SR/SAR/AR/UR...）
    image_url       TEXT,
    detail_fetched  INTEGER DEFAULT 0      -- 是否已抓取詳細頁
);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_number ON cards(collector_number);
CREATE INDEX IF NOT EXISTS idx_cards_rarity ON cards(rarity);

-- 爬蟲進度：記錄每個稀有度列表爬到第幾頁，支援斷點續爬
CREATE TABLE IF NOT EXISTS crawl_progress (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 遊戲王卡（資料來源：百鴿 ygocdb.com 全量匯出，簡中以 OpenCC 轉繁中）
-- 遊戲王的稀有度/語言（日紙、韓紙）依印刷版本而異且無公開資料庫，
-- 由使用者在加入願望清單時指定。
CREATE TABLE IF NOT EXISTS ygo_cards (
    id       INTEGER PRIMARY KEY,  -- 卡片密碼（8位數，對應卡圖）
    cid      INTEGER,              -- ygocdb 卡片編號
    name_tc  TEXT,                 -- 繁中卡名（OpenCC 轉換）
    name_sc  TEXT,                 -- 簡中卡名
    name_jp  TEXT,
    name_en  TEXT,
    types    TEXT                  -- 卡片種類描述
);
CREATE INDEX IF NOT EXISTS idx_ygo_name_tc ON ygo_cards(name_tc);
CREATE INDEX IF NOT EXISTS idx_ygo_name_jp ON ygo_cards(name_jp);

-- 露天賣家暱稱快取（數字 ID → 賣場暱稱，從商品頁解析）
CREATE TABLE IF NOT EXISTS ruten_sellers (
    seller_id TEXT PRIMARY KEY,
    nick      TEXT,
    name      TEXT   -- 賣場名稱（boardName）
);

-- 卡圖感知雜湊索引（圖片搜尋用）
CREATE TABLE IF NOT EXISTS image_hashes (
    game    TEXT NOT NULL,       -- pkm / ygo
    card_id INTEGER NOT NULL,
    phash   TEXT NOT NULL,       -- 64-bit pHash（hex）
    dhash   TEXT NOT NULL,       -- 64-bit dHash（hex）
    PRIMARY KEY (game, card_id)
);

-- 遊戲王收錄卡包（來源：Konami 官方 DB，加入願望清單時按需抓取後快取）
CREATE TABLE IF NOT EXISTS ygo_printings (
    card_id INTEGER NOT NULL,   -- 卡片密碼
    code    TEXT,               -- 卡號（如 PAC1-JP016）
    pack    TEXT,               -- 卡包名稱
    rarity  TEXT,               -- 標準化稀有度（N/R/SR/UR/SEC/...）
    release TEXT                -- 發售日
);
CREATE INDEX IF NOT EXISTS idx_ygo_printings ON ygo_printings(card_id);
CREATE TABLE IF NOT EXISTS ygo_printings_fetched (
    card_id INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 鋼彈卡片遊戲 GCG（來源：官方繁中站 gundam-gcg.com/zh-tw）
-- 卡號即主鍵（如 GD01-001）；一張卡可能有多種稀有度平行卡，rarity 存主要版本
CREATE TABLE IF NOT EXISTS gundam_cards (
    id        TEXT PRIMARY KEY,   -- 卡號 GD01-001
    name_tc   TEXT,               -- 繁中卡名
    color     TEXT,               -- 顏色 Blue/Green/Red/White
    card_type TEXT,               -- 卡牌類型 UNIT/PILOT/COMMAND/BASE
    level     INTEGER,            -- Lv.
    cost      INTEGER,
    ap        INTEGER,
    hp        INTEGER,
    terrain   TEXT,               -- 地形
    traits    TEXT,               -- 特徵
    effect    TEXT,               -- 效果文字
    source    TEXT,               -- 來源作品
    rarity    TEXT,               -- 稀有度 C/U/R/SR/LR...
    pack      TEXT,               -- 系列 GD01/ST01...
    detail_fetched INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gundam_name ON gundam_cards(name_tc);
CREATE INDEX IF NOT EXISTS idx_gundam_pack ON gundam_cards(pack);

-- Grand Archive TCG（GA，來源：官方 API api.gatcg.com）。
-- 全英文（台灣賣美版、無繁中印刷），每一列 = 一個 edition（可買的印刷版本），
-- 比照寶可夢/鋼彈；同一張卡的不同版本以 card_id 分群。
CREATE TABLE IF NOT EXISTS ga_cards (
    id           TEXT PRIMARY KEY,   -- edition uuid（每個印刷版本唯一）
    card_id      TEXT,               -- 母卡 id（分群同卡不同版本用）
    slug         TEXT,               -- edition slug（官方頁連結）
    name         TEXT,               -- 英文卡名
    element      TEXT,               -- NORM/FIRE/WATER/WIND/...
    classes      TEXT,               -- 職業（逗號分隔）WARRIOR/MAGE/...
    types        TEXT,               -- 卡種 CHAMPION/ALLY/ACTION/ITEM/REGALIA...
    subtypes     TEXT,
    cost_memory  INTEGER,
    cost_reserve INTEGER,
    level        INTEGER,
    power        INTEGER,
    life         INTEGER,
    durability   INTEGER,
    speed        INTEGER,
    effect       TEXT,
    set_prefix   TEXT,               -- 系列代碼（DTR/RDO/DOA/FTC...）
    set_name     TEXT,
    set_release  TEXT,               -- 系列發售日（排序用，越新越前）
    collector_number TEXT,           -- 卡號（如 015、369）
    rarity       INTEGER,            -- 數值稀有度（1..9）
    rarity_label TEXT,               -- 對照字母 C/U/R/SR/UR/PR/CSR/CUR/CPR
    image        TEXT,               -- 圖片 uuid（供 /img/ga 代理）
    language     TEXT,
    detail_fetched INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ga_name ON ga_cards(name);
CREATE INDEX IF NOT EXISTS idx_ga_card ON ga_cards(card_id);
CREATE INDEX IF NOT EXISTS idx_ga_set ON ga_cards(set_prefix);

-- 價格快照：每次比價時記錄各卡（含條件）在露天的最低價
CREATE TABLE IF NOT EXISTS price_history (
    game    TEXT NOT NULL,
    card_id INTEGER NOT NULL,
    rarity  TEXT,                -- 查詢條件（可為 NULL）
    lang    TEXT,
    price   INTEGER NOT NULL,    -- 當次最低價
    ts      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_price_hist ON price_history(game, card_id);

-- 收藏庫存：使用者「已經有的卡」，與願望清單（我還缺什麼）互補。
-- 主要用途是匯入牌組後扣掉已收藏的數量，只把真正缺的送去比價。
-- unit_price 為購入單價（可空），搭配 price_history 現價可算收藏市值與損益。
-- card_id 存為 TEXT 以相容鋼彈/GA 的字串卡號（比照 price_alerts）。
CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  TEXT NOT NULL,          -- 訪客識別（同 price_alerts）
    game       TEXT NOT NULL,          -- pkm / ygo / gcg / ga
    card_id    TEXT NOT NULL,
    card_name  TEXT,                   -- 顯示用快照
    image_url  TEXT,                   -- 顯示用快照（站內相對路徑）
    rarity     TEXT,                   -- 版本條件，語意同願望清單
    lang       TEXT,
    art        TEXT,
    qty        INTEGER NOT NULL DEFAULT 1,
    unit_price INTEGER,                -- 購入單價（可空＝沒記成本）
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
-- 同一張卡的不同版本（稀有度/紙種/異圖）各自一列，故唯一鍵含這三個條件
CREATE UNIQUE INDEX IF NOT EXISTS idx_collections_uniq ON collections(
    client_id, game, card_id,
    IFNULL(rarity, ''), IFNULL(lang, ''), IFNULL(art, ''));
CREATE INDEX IF NOT EXISTS idx_collections_client ON collections(client_id);

-- 我的牌組：把當下的願望清單存起來，之後一鍵載回。
-- items 存 JSON（與分享連結同一套精簡格式 [{g,id,q,r,l,a}]），刻意不拆成
-- deck_cards 子表——這個站的規模用不到關聯查詢，一欄 JSON 少一半程式碼。
CREATE TABLE IF NOT EXISTS decks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    game       TEXT,                   -- 主要遊戲（混牌組時取張數最多者，僅供顯示）
    items      TEXT NOT NULL,          -- JSON 陣列
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_decks_client ON decks(client_id);

-- 應用設定（鍵值，如 Discord Webhook 網址）
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 到價通知：指定卡＋目標價，定期到露天檢查，達標時透過 Discord 推播。
-- card_id 存為 TEXT 以相容鋼彈的字串卡號（如 GD01-001）。
CREATE TABLE IF NOT EXISTS price_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    TEXT,                   -- 訪客識別（瀏覽器隨機 ID，多人各自清單用）
    game         TEXT NOT NULL,          -- pkm / ygo / gcg
    card_id      TEXT NOT NULL,
    card_name    TEXT,                   -- 顯示用快照
    image_url    TEXT,                   -- 顯示用快照（站內相對路徑）
    rarity       TEXT,                   -- 查詢條件（可為 NULL）
    lang         TEXT,
    art          TEXT,
    target_price INTEGER NOT NULL,       -- 目標價：露天最低 <= 此值即觸發
    status       TEXT DEFAULT 'active',  -- active / paused
    notified     INTEGER DEFAULT 0,      -- 已推播未重置（避免重複通知）
    last_price   INTEGER,                -- 最近一次檢查到的最低價（顯示用）
    hit_price    INTEGER,                -- 觸發當下的最低價
    hit_title    TEXT,                   -- 觸發當下的露天商品標題
    hit_url      TEXT,                   -- 觸發當下的露天商品連結
    last_checked TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_price_alerts_status ON price_alerts(status);
"""


_schema_ready = False  # schema/遷移每個行程只需跑一次


def _ensure_schema(conn):
    conn.executescript(SCHEMA)
    # 遷移：舊資料庫補欄位（SQLite 無 ADD COLUMN IF NOT EXISTS）
    for table, col, typ in (
        ("ygo_cards", "name_cnocg", "TEXT"),
        ("ygo_cards", "name_md", "TEXT"),
        ("ygo_cards", "card_text", "TEXT"),   # 效果文字（繁中）
        ("ygo_cards", "pend_text", "TEXT"),   # 靈擺效果（繁中）
        ("ruten_sellers", "credit_rate", "REAL"),   # 賣家評價（如 4.99）
        ("ruten_sellers", "credit_cnt", "INTEGER"),  # 評價數
        ("cards", "card_kind", "TEXT"),   # 寶可夢/物品卡/支援者卡/競技場卡/寶可夢道具/能量卡
        ("cards", "ptype", "TEXT"),       # 寶可夢屬性（草火水雷超鬥惡鋼龍無色）
        ("cards", "hp", "INTEGER"),
        ("gundam_cards", "effect", "TEXT"),  # 鋼彈效果文字
        ("price_alerts", "client_id", "TEXT"),  # 舊庫補：訪客識別
        ("ga_cards", "set_release", "TEXT"),    # GA 系列發售日（排序用）
        # 流動性快照（露天 API 本來就回 SoldQty/StockQty，之前只是沒存）：
        # 用來判斷「這個價位是真的便宜，還是根本沒人買」
        ("price_history", "listings", "INTEGER"),  # 當次符合的商品數
        ("price_history", "stock", "INTEGER"),     # 這些商品的在售總量
        ("price_history", "sold", "INTEGER"),      # 這些商品的累計成交量
    ):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # 欄位已存在


def get_conn():
    global _schema_ready
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    if not _schema_ready:
        # 建表/補欄位每個行程只做一次（冪等，避免每個請求都重跑）
        _ensure_schema(conn)
        _schema_ready = True
    return conn
