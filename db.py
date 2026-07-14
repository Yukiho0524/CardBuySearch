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
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
