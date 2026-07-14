# CardBuySearch — TCG 缺卡湊齊比價

幫 TCG 玩家找出「能一次買齊整套缺卡」的賣家。
第一版支援：**寶可夢繁中卡**（官方卡查資料）× **露天拍賣**（即時比價）。

## 功能

1. **卡片搜尋**：卡名 / 卡片編號（如 `094/081`）搜尋，可過濾稀有度
2. **願望清單**：把缺的卡加入清單、指定數量
3. **同賣家湊齊比價**：即時查露天，列出
   - 能一次湊齊全部卡的賣家（含運費總價）
   - 覆蓋不齊的賣家（標示缺哪幾張）
   - 拆買基準：每張卡取全站最低價、跨賣家運費各計的總價，供對照

## 安裝與啟動

```
python -m pip install -r requirements.txt
python app.py          # → http://localhost:5000
```

## 建立卡牌資料庫

資料庫是本機 SQLite（`data/cards.db`），需先跑爬蟲：

```
# Phase A：建「卡片ID → 稀有度」對照（官方詳細頁不顯示稀有度，必須由此建立）
python crawler/pokemon.py --rarity-map

# Phase B：抓卡片詳細資料（卡名/編號/系列/卡圖），全部約 1.4 萬張、需數小時
python crawler/pokemon.py --details              # 全部
python crawler/pokemon.py --details --limit 500  # 只抓 500 張（可分次跑，自動續爬）

# 或針對特定卡優先建檔
python crawler/pokemon.py --keyword 噴火龍
```

爬蟲有 0.6 秒禮貌延遲並支援斷點續爬，中斷後重跑會接續。

## 架構

```
app.py            Flask 後端（/api/search、/api/compare）
db.py             SQLite schema（cards＝每列一個印刷版本）
crawler/pokemon.py  官方繁中卡查爬蟲（兩階段）
ruten.py          露天搜尋 + 商品標題比對（稀有度俗稱字典、排除套組/同人卡）
static/           前端（純 HTML/JS/CSS，繁中 UI）
```

## 已知限制（第一版）

- 露天用的是其前端網頁呼叫的非官方 JSON API，改版即失效；請勿高頻查詢
- 商品標題比對靠關鍵字規則，會有誤判；結果附「比對信心」標籤供人工判斷
- 賣家只顯示 ID（露天無公開的賣家暱稱 API），點商品連結可見賣場
- 運費以各商品標示的運費取最大值估算，實際以賣場結帳為準
- 遊戲王資料庫、卡拍拍、圖片搜尋為後續階段
