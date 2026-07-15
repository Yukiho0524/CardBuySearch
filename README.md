# CardBuySearch — TCG 缺卡湊齊比價

幫 TCG 玩家找出「能一次買齊整套缺卡」的賣家。
支援：**寶可夢繁中卡**（官方卡查資料）＋ **遊戲王**（百鴿 ygocdb 資料）× **露天拍賣**（即時比價）。

## 功能

1. **卡片搜尋**：
   - 寶可夢：卡名 / 卡片編號（如 `094/081`），可過濾稀有度
   - 遊戲王：卡名（繁中/簡中/日文/英文皆可搜）
   - **以圖搜卡**：上傳卡片照片，用感知雜湊找最相近的卡
     （需先跑 `python crawler/imghash.py --game ygo|pkm` 建索引；
     照片盡量裁到只剩卡片本體）
2. **願望清單**：把缺的卡加入清單、指定數量；
   遊戲王卡可指定**稀有度**（N/R/SR/UR/SEC/CR/20th/QCSE…）與**紙種**（日紙/韓紙）
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

遊戲王（一次匯入全部約 1.4 萬張，來源：百鴿 ygocdb.com 匯出檔）：

```
python crawler/yugioh.py
```

爬蟲有 0.6 秒禮貌延遲並支援斷點續爬，中斷後重跑會接續。

## 架構

```
app.py            Flask 後端（/api/search、/api/compare、/img 卡圖代理快取）
db.py             SQLite schema（cards＝寶可夢印刷版本、ygo_cards＝遊戲王卡）
crawler/pokemon.py  官方繁中卡查爬蟲（兩階段）
crawler/yugioh.py   遊戲王匯入（ygocdb 匯出檔，OpenCC 簡轉繁）
crawler/imghash.py  卡圖感知雜湊索引（以圖搜卡用，可斷點續跑）
ruten.py          露天搜尋 + 商品標題比對（稀有度俗稱字典、日/韓紙判斷、排除套組/同人卡）
static/           前端（純 HTML/JS/CSS，繁中 UI）
```

遊戲王的稀有度與紙種依「印刷版本」而異且無公開資料庫可對照，
因此由使用者在加入願望清單時自行指定，比對時利用標題行話
（亮面/金亮/鑽石/雕鑽…）與卡號（`-JP`=日紙、`-KR`=韓紙）判斷。

### 遊戲王譯名同義詞字典（ygo_aliases.json）

賣家譯名極不統一（例：救祓少女·馬爾法＝驅魔修女 瑪爾法＝救乙女瑪爾法），
露天查詢會把卡名依字典展開成多個變體查詢後合併，標題比對也認得所有變體。
**發現某張卡搜不到時，把賣家常用寫法加進 `ygo_aliases.json` 對應的組即可**
（雙向生效，重啟網站後生效），本站搜尋同樣吃這份字典（搜「驅魔少女」找得到救祓少女）。

字典可自動擴增：`python crawler/learn_aliases.py --write` 會比對百鴿匯出檔中
四套譯名（社群／NWBBS／台版官方／Master Duel）的系列段差異，
把出現於 ≥2 張卡的系列對照自動學進字典（現有 159 組、385 詞）。
賣家口語俗稱（如「詭術星」「烏拉拉」）官方資料學不到，仍靠手動累積。

## 已知限制（第一版）

- 露天用的是其前端網頁呼叫的非官方 JSON API，改版即失效；請勿高頻查詢
- 商品標題比對靠關鍵字規則，會有誤判；結果附「比對信心」標籤供人工判斷
- 賣家只顯示 ID（露天無公開的賣家暱稱 API），點商品連結可見賣場
- 運費以各商品標示的運費取最大值估算，實際以賣場結帳為準
- 遊戲王資料庫、卡拍拍、圖片搜尋為後續階段
