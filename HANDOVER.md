# CardBuySearch 交接文件

> 這份文件是給接手者（或新的 AI 對話）的完整說明。讀完應能理解「這網站做什麼、怎麼建的、資料哪來、怎麼維護」。
> 詳細操作指令另見 [README.md](README.md)。

---

## 一、這網站在做什麼

**一句話**：幫 TCG 玩家找出「能一次買齊整套缺卡」的露天賣家。

**使用情境**：玩家組一套牌、缺幾張卡，想在同一個賣家一次買齊（省運費、省溝通）。把缺的卡加進「願望清單」，網站即時去露天拍賣搜尋，列出：
- 哪些賣家能**一次湊齊**全部缺卡（依含運總價排序）
- 覆蓋不齊的賣家（標示缺哪幾張）
- **雙賣家組合**（單一賣家湊不齊、但兩家合買更省時）
- **拆買基準**（每張卡各買最便宜的，當比較基準）

**第三大功能——到價通知**：使用者為想要的卡設定目標價，程式定期到露天查詢，當最低價跌破目標時透過**使用者自己填的 Discord Webhook** 推播通知（見第九節）。

**支援三款遊戲**：寶可夢（繁中）、遊戲王、鋼彈卡片遊戲 GCG。

---

## 二、技術架構（很簡單，刻意的）

```
純 Python + 原生 HTML/JS/CSS，本機自用網站。無框架、無建置步驟。

┌─ 前端 static/（原生，無 React/Vue）
│    index.html  單頁、三大區塊（搜尋／願望清單／比價結果）＋卡片詳情彈窗
│    app.js      所有互動邏輯（搜尋/一覽/篩選/清單/比價/彈窗/深色模式）
│    style.css   含深色模式（CSS 變數 + html[data-theme=dark]）
│
├─ 後端 app.py（Flask，單檔）
│    提供 JSON API（見下方路由表），並注入資產版本戳解決快取
│
├─ 資料層 db.py（SQLite，單檔 data/cards.db）
│    cards（寶可夢）／ygo_cards（遊戲王）／gundam_cards（鋼彈）
│    ＋ ygo_printings、image_hashes、price_history、ruten_sellers 等
│
├─ 露天比對 ruten.py
│    呼叫露天非官方 JSON API、解析商品標題比對卡片
│
├─ Konami 官方 konami.py（遊戲王收錄資料＋日文卡圖）
│
└─ 爬蟲 crawler/*.py（建庫、更新、圖片索引、字典學習）
```

**為什麼這麼樸素**：使用者自用（本機 `python app.py`，或雙擊 `start.bat`），不需要正式部署、不需要框架。這是刻意的取捨——好維護、零建置。

---

## 三、資料來源（每款遊戲不同，這是關鍵）

| 遊戲 | 卡片資料來源 | 卡圖 | 卡數 |
|---|---|---|---|
| **寶可夢** | 官方繁中卡查 asia.pokemon-card.com/tw（爬蟲） | 官方繁中卡圖 | ~14,179 |
| **遊戲王** | 百鴿 ygocdb.com 全量匯出檔（簡中，OpenCC 轉繁） | Konami 官方日文卡圖 | ~14,195 |
| **鋼彈 GCG** | 官方繁中站 gundam-gcg.com/zh-tw（爬蟲） | 官方卡圖（日文卡面） | ~1,355（含異圖平行卡） |
| **比價（三款共用）** | 露天拍賣公開 JSON API（rtapi.ruten.com.tw） | — | 即時 |

**重要限制**：
- 露天用的是「其前端網頁呼叫的非官方 JSON API」，**露天改版即可能失效**，需控制請求頻率避免被封。
- 各官方卡圖有版權，本站只作查詢/比價用途。
- 卡拍拍（第二賣場）評估過：網站僅 App 導購頁、無公開 API，**不整合**，維持談合作路線。

---

## 四、後端 API 路由表（app.py）

| 路由 | 用途 |
|---|---|
| `GET /` | 首頁（注入資產版本戳，防瀏覽器快取舊 JS/CSS） |
| `GET /api/search?game=&q=&rarity=` | 卡名/卡號搜尋 |
| `GET /api/browse?game=&<篩選>&offset=` | 全卡一覽＋條件篩選＋分頁 |
| `GET /api/browse-options?game=` | 該遊戲可用的篩選選項 |
| `POST /api/search-by-image` | 以圖搜卡（感知雜湊） |
| `GET /api/card/<game>/<id>` | 卡片詳情（彈窗用，`/api/card/gcg/<id>` 另一條因鋼彈卡號是字串） |
| `POST /api/compare` | **核心**：對願望清單跑露天比價 |
| `POST /api/import-deck` | 牌組匯入（YDK／文字牌表／寶可夢官方牌組編碼） |
| `GET /api/cards?game=&ids=` | 批次取卡（分享連結還原用） |
| `GET /img/<game>/<id>` | 卡圖代理＋磁碟快取 |
| `GET /api/ygo/options`、`/api/ygo/printings/<id>`、`/api/gcg/options`、`/api/rarities` | 各種選項 |
| `GET/POST /api/alerts`、`POST/DELETE /api/alerts/<id>` | 到價通知增查改刪 |
| `POST /api/settings/webhook`、`/api/settings/webhook/test` | 設定 Discord Webhook／送測試訊息 |
| `POST /api/alerts/check` | 立即檢查一次（背景執行緒跑，前端輪詢 `GET /api/alerts` 的 `checking`） |
| `POST /api/quote` | 單張卡即時報價（設目標價前參考用；與比價共用 `_listing_cache`） |

---

## 五、幾個關鍵設計 / 踩過的坑（接手必讀）

1. **卡圖代理快取**：官方圖伺服器對瀏覽器跨站請求會停滯，所以卡圖一律走後端 `/img/...` 代理、抓下來存 `data/img_cache/` 再供應同源圖片。遊戲王日文圖就緒的卡網址帶 `?v=jp` 讓瀏覽器換掉舊英文圖。

2. **遊戲王譯名極亂**（最難的部分）：一張卡有社群名/台版官方名/Master Duel 名/日文名，賣家又亂寫（救祓少女＝驅魔修女＝救乙女）。解法三層：
   - `ygo_aliases.json` 同義詞字典（可 `crawler/learn_aliases.py` 自動從四套官方譯名學習）
   - 露天查詢用**官方卡號**（如 LOCH-JP001）優先——賣家幾乎都標卡號，不受譯名影響
   - 標題比對認得所有變體＋人名段

3. **紙種/版本判定（台灣市場慣例）**：
   - 遊戲王：日紙較貴、賣家必明標；**沒明標一律推定韓紙**。「日文」「日本正版」不算日紙聲明（只認「日紙」「日版」）。簡中已從選單移除（台灣買不到）。
   - 鋼彈：只有日版/美版（無韓版）。

4. **鋼彈異圖平行卡（比照寶可夢）**：一張卡的異圖版本在官方站是**獨立卡號**，卡號後綴 `_p1`、`_p2`…（如 `GD01-001_p1`），各有自己的 detail 頁與稀有度（基礎「LR」→異圖「LR +」「LR ++」）。存法：直接當獨立列存進 `gundam_cards`（`id` 是字串主鍵，天然容納後綴），一覽/搜尋跟寶可夢一樣每版本各一張。彈窗「異圖版本」清單靠**基礎卡號**分群（`WHERE id=base OR id GLOB base||'_p*'`，見 `app.py` 的 `/api/card/gcg`），與寶可夢用「同名卡」分群不同。
   - ⚠️ **比價還原基礎卡號**：`ruten.py` 的 `find_listings_for_gundam` 開頭把 `_pN` 剝成基礎卡號才查露天——賣家不會在標題寫 `_p1` 後綴。**代價**：異圖卡與基礎卡**共用同一批露天商品、價格不區分異圖溢價**。要精準隔離異圖售價得先實測賣家實際標法（有人寫「異圖」「P」「+」、有人只寫基礎卡號），比照遊戲王 `YGO_ART_WORDS`（超框/異圖）那套做標題過濾——**動之前務必實測，別憑印象**（同稀有度俗稱的原則）。

5. **稀有度中文俗稱**（`ruten.py` 的 `YGO_RARITIES`）：以露天實證建立——金鑽=QCSE、半鑽=SEC、全鑽=EXSEC、紅鑽=20th、白鑽=PSER…改動前務必實測，別憑印象。

6. **UI 隱藏元素的坑**（踩過兩次）：`display:flex/grid` 會蓋過 HTML `hidden` 屬性。已加全域保險絲 `[hidden]{display:none!important}`（style.css 開頭），**勿移除**。驗證 UI 顯示/隱藏一定要看 computed style，不能只查 `.hidden` 屬性。

7. **殭屍伺服器**：Windows 允許多程序綁同一埠，重啟時舊 server 會搶請求造成「怎麼改都是舊的」。`start.bat` 啟動前會自動清掉 5000 埠上的舊 Python 程序。

8. **靜態檔快取**：`app.py` 設 `SEND_FILE_MAX_AGE_DEFAULT=0`＋首頁資產版本戳，改版重新整理即生效，不必 Ctrl+F5。

9. **離群價過濾**（`ruten.py` 的 `drop_price_outliers`）：露天「多規格商品」會把最便宜規格的價當商品價（標題對到卡、但那價其實是同賣場另一張便宜卡），或有 1 元起標，污染「最低價」。做法：商品數 ≥4 時取中位數，剔除低於「中位數 × 0.1」者（相對門檻會隨卡價縮放，便宜卡的便宜商品不誤刪）。**比價、即時報價、到價通知三處都套用**（compare 的 per-card 迴圈、`app.py` 的 `_card_listings`、`alerts._search`），確保三邊「最低價」一致。實測 GD01-001：中位數 60→門檻 6，剔除 2.53/3.06/3.55/4 這批雜訊。要調鬆緊改 `rel_floor`／`min_n`。

---

## 六、怎麼跑 / 怎麼維護

**啟動**：雙擊 `start.bat`（自動檢查套件、清舊程序、開防火牆、顯示內網網址）。
綁 `0.0.0.0`，**同內網的人**可用「本機 IP:5000」開啟。

**建資料庫**（首次或換機，見 README 詳細指令）：
```
python crawler/pokemon.py --rarity-map     # 寶可夢稀有度對照
python crawler/pokemon.py --details        # 寶可夢詳細（約 2-3 小時）
python crawler/pokemon.py --ext            # 寶可夢大類/屬性/HP
python crawler/yugioh.py                   # 遊戲王匯入
python crawler/prefetch_printings.py       # 遊戲王收錄＋日文卡圖（數小時）
python crawler/gundam.py                   # 鋼彈
python crawler/imghash.py --game ygo|pkm   # 以圖搜卡索引
```

**自動更新**：已註冊 Windows 排程 `CardBuySearch-Weekly-Update`（**每週日 04:00**），跑 `crawler/update_all.py`（三款遊戲一起更新）。日誌 `data/update.log`。前提是那時電腦開著。

**手動全量更新**：`python crawler/update_all.py`

**到價通知檢查**：`crawler/check_alerts.py` 對所有啟用中的通知跑露天、達標則推播。要背景自動跑需自行註冊 Windows 排程（見第九節），日誌 `data/alerts.log`。手動：`python crawler/check_alerts.py`。網頁上的「立即檢查一次」則走 `/api/alerts/check`。

---

## 七、已知限制 / 可能的下一步

- **遊戲王「產品」篩選未做**：一張卡收錄在多個卡包（平均 2.8 個、共 818 種），多對多不好用單選下拉呈現。寶可夢/鋼彈的產品篩選已完成。
- **未部署對外**：目前僅本機/內網。要對外需 Cloudflare Tunnel 或 VPS（使用者目前不需要）。
- 露天為非官方介面，長期維護成本主要在「露天改版時修爬蟲」。
- 遊戲王/鋼彈卡圖有官方 SAMPLE 浮水印（官方資料庫的圖都這樣），不影響辨識。
- **鋼彈異圖比價不區分溢價**：異圖平行卡目前與基礎卡共用同一批露天商品（見第五節第 4 點），售價 = 該卡號整批行情。要精準隔離異圖售價需先實測賣家標法再做標題過濾。

---

## 八、程式碼慣例

- Commit 訊息用 **`[Hibari] `** 前綴，並 push 到 origin（github.com/Yukiho0524/CardBuySearch）。
- 每完成一個階段就 commit＋push。
- 註解、變數用繁體中文，與現有風格一致。
- 資料檔可手動編輯：`ygo_aliases.json`（遊戲王譯名別名）、`pkm_products.json`（寶可夢產品名）。

---

## 九、到價通知（Discord 推播）

**檔案**：`notify.py`（送 Discord webhook）、`alerts.py`（檢查邏輯，端點與排程共用）、`crawler/check_alerts.py`（排程 CLI）。資料表 `price_alerts`＋`app_settings`（存 webhook）。前端在「🔔 到價通知」面板，願望清單每張卡有 🔔 可設定。

**流程**：使用者在自己的 Discord 伺服器建 Webhook（伺服器設定 → 整合 → Webhook），把網址填進網頁 → 存進 `app_settings`。為某張卡設目標價 → 存進 `price_alerts`（沿用願望清單當下選的稀有度/紙種/版本條件）。檢查時 `alerts._search` 依條件重跑露天（**與 `/api/compare` 同一套比對邏輯**：遊戲王用官方卡號＋多譯名、鋼彈還原基礎卡號、寶可夢用卡名＋編號），取最低價與目標比。

**幾個設計重點**：
1. **只採信 strong/weak 商品**（`TRIGGER_CONFIDENCES`），排除 `maybe`（標題沒標稀有度/紙種，觸發通知容易誤報）。
2. **防重複通知**：達標推播一次後標記 `notified=1`；價格回到目標以上時自動 `notified=0` 重置，之後再跌破才會再推播。使用者也可手動「重設」或「暫停」。
3. **送失敗不吞通知**：有設 webhook 但 Discord 送失敗時**不**標記 `notified`，下次檢查再試；沒設 webhook 則仍標記（只當站內「已達標」狀態，不外送）。
4. **Webhook 只收 Discord 官方網址**（`DISCORD_WEBHOOK_RE` 驗證），回傳前端時遮罩（只露結尾 6 碼），避免 token 外流。
5. **順便累積歷史價**：每次檢查把最低價寫進 `price_history`，與比價共用同一張表，即使沒開網頁比價也會累積走勢。
6. **card_id 存 TEXT**：相容鋼彈字串卡號（`GD01-001`）；寶可夢/遊戲王的數字 id 以字串存，查詢靠 SQLite 型別親和自動轉換。

**排程（選用，要背景自動跑才需要）**——比照週更新那套，自行註冊 Windows 排程（電腦要開著）：
```
schtasks /Create /TN CardBuySearch-Alerts /SC HOURLY /MO 3 ^
  /TR "\"C:\path\to\python.exe\" \"%CD%\crawler\check_alerts.py\""
```
移除：`schtasks /Delete /TN CardBuySearch-Alerts /F`。日誌 `data/alerts.log`。
不註冊排程也能用——按網頁上的「🔄 立即檢查一次」手動觸發。

**已知取捨**：檢查頻率越高越快通知、但對露天請求量越大（非官方 API，別太密）。目前建議 3 小時一次。多筆通知是逐一查露天（每筆數秒），通知很多時「立即檢查」會跑一陣子（背景執行、前端輪詢顯示進度）。
