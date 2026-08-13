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

**第四大功能——我的收藏**：記錄「已經有的卡」，匯入牌組後可一鍵扣掉手上已有的張數，只把真正缺的送去比價；填了購入成本還能對照行情看損益（見第十節）。

**支援四款遊戲**：寶可夢（繁中）、遊戲王、鋼彈卡片遊戲 GCG、Grand Archive（GA，英文）。

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
| **Grand Archive** | 官方公開 JSON API api.gatcg.com（免爬 HTML） | 官方卡圖 api.gatcg.com/cards/images | 2,240 張／4,504 版本（全英文，美版） |
| **比價（四款共用）** | 露天拍賣公開 JSON API（rtapi.ruten.com.tw） | — | 即時 |

**重要限制**：
- 露天用的是「其前端網頁呼叫的非官方 JSON API」，**露天改版即可能失效**，需控制請求頻率避免被封。
- 各官方卡圖有版權，本站只作查詢/比價用途。
- 卡拍拍（第二賣場）**不整合**（2026-08-13 重查更新結論）：它其實有網頁版 `trade.kapaipai.tw` 與免登入 JSON API（`/api/card/*`、`/api/product/*`），四款遊戲代碼 `pkmtw`／`ygojp`／`gdamjp`／`gaen` 全有，技術上很好接。**卡在服務條款 6.2(dd)**：明文禁止以自動化程式/爬蟲/未經授權呼叫 API 做系統性擷取，7.5(a) 把「大量擷取平台資料」列為永久封鎖事由。條款同時載明「事先取得書面同意」不在此限，故維持談合作路線。功能面則已對標，見第十節。

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
| `GET /api/collection` | 收藏清單＋成本/市值統計 |
| `POST /api/collection` | 加入收藏（同卡同版本累加；qty 給負數即扣減） |
| `POST /api/collection/<id>`、`DELETE /api/collection/<id>` | 改數量/成本、刪除 |
| `POST /api/collection/deduct` | **只試算不寫入**：回報願望清單各卡已有幾張、還缺幾張 |
| `GET/POST /api/decks`、`GET/POST/DELETE /api/decks/<id>` | 我的牌組：存清單、載回、改名、刪除 |

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
   - **比價還原基礎卡號＋稀有度層級分版**（2026-07-21 實作）：`find_listings_for_gundam` 開頭把 `_pN` 剝成基礎卡號查露天（賣家不寫 `_p1` 後綴），再用**卡片稀有度**把不同版本分開。露天實證：賣家用稀有度後綴 `+`／`++`（如 `LR+`、`LR++`）與「異圖」字樣區分平行閃——**基礎 LR 約 30–120、LR+ 約 279+、LR++ 上萬**。做法：`_gundam_rarity_parts` 把稀有度拆成（字母, plus 層級），標題比對認得「字母＋plus」token（`_gundam_title_art`）：基礎版（plus 0）排除任何帶 `+`／異圖 的商品；異圖版須命中「該字母＋對應 plus」（**C+ 不算 R+**，避免撞到同號不同卡的資源卡）。**關鍵細節**：token 只認「字母後緊跟 `+`」的寫法，故英文字（Card→C、Rising→R）不會被誤判成稀有度。異圖版另加一條 `鋼彈 {卡號} 異圖` 查詢（價格升冪排序下昂貴異圖會被便宜基礎版擠出前 40 筆）。三處呼叫（compare／`_card_listings`／`alerts._search`）都傳 `rarity=卡片實際稀有度`。
   - ⚠️ **仍存的限制**：同稀有度平行卡（如 GD01-004 base R 與 `_p1`/`_p3` 也是 R、無 `+` 差異）無法只靠 `+` 分辨——賣家頂多用「異圖」但寫法不一，這類會落在同一批 R 商品裡（價位相近、影響小）。改法需傳 is_alt 旗標並靠「異圖」字樣分，但賣家標法不穩，**動前務必實測**。

5. **稀有度中文俗稱**（`ruten.py` 的 `YGO_RARITIES`）：以露天實證建立——金鑽=QCSE、半鑽=SEC、全鑽=EXSEC、紅鑽=20th、白鑽=PSER…改動前務必實測，別憑印象。

6. **UI 隱藏元素的坑**（踩過兩次）：`display:flex/grid` 會蓋過 HTML `hidden` 屬性。已加全域保險絲 `[hidden]{display:none!important}`（style.css 開頭），**勿移除**。驗證 UI 顯示/隱藏一定要看 computed style，不能只查 `.hidden` 屬性。

7. **殭屍伺服器**：Windows 允許多程序綁同一埠，重啟時舊 server 會搶請求造成「怎麼改都是舊的」。`start.bat` 啟動前會自動清掉 5000 埠上的舊 Python 程序。

8. **靜態檔快取**：`app.py` 設 `SEND_FILE_MAX_AGE_DEFAULT=0`＋首頁資產版本戳，改版重新整理即生效，不必 Ctrl+F5。

9. **離群價過濾**（`ruten.py` 的 `drop_price_outliers`）：露天「多規格商品」會把最便宜規格的價當商品價（標題對到卡、但那價其實是同賣場另一張便宜卡），或有 1 元起標，污染「最低價」。做法：商品數 ≥4 時取中位數，剔除低於「中位數 × 0.1」者（相對門檻會隨卡價縮放，便宜卡的便宜商品不誤刪）。**比價、即時報價、到價通知三處都套用**（compare 的 per-card 迴圈、`app.py` 的 `_card_listings`、`alerts._search`），確保三邊「最低價」一致。要調鬆緊改 `rel_floor`／`min_n`。

10. **海外美金商品過濾**（`search_products`，2026-07-21）：露天會混入海外賣場商品，其 prod API 的 **`Currency` 欄位是 `USD`**、`PriceRange` 是美金數字——若當台幣顯示會變離譜低價（US$2.53 → NT$2.53，就是先前那批英文標題「Gundam … Japanese」的來源）。做法：`search_products` 回傳前**只留 `Currency in (None, "TWD")`**（缺欄位保守保留，避免 API 變動誤刪）。這是**單一 choke point**，四款遊戲全受惠。⚠️ 目前是「濾掉不換算」——沒做 USD→TWD 匯率換算（匯率會浮動、跨境運費/報關也不同，台灣買家多半不會買）。要顯示海外價得另存 `Currency` 並在前端標示幣別。

11. **Grand Archive（GA）＝全英文**（2026-07-21 新增）：台灣賣美版、無繁中印刷，官方/露天賣家全用英文卡名。資料來源是官方公開 API `api.gatcg.com`（免爬 HTML，2240 卡/4504 版本，稀有度數值 1..9 →字母見 `crawler/grand_archive.py` 的 `RARITY_MAP`）。每個 edition（印刷版本）一列存 `ga_cards`，同卡不同版本以 `card_id` 分群。**搜尋走英文名或卡號**（如 Volnia、RDO-204），非中文。
    - **露天比對** `find_listings_for_ga`（實證賣家標法：`Grand Archive/GA + 英文名 + 系列+卡號 + 稀有度/普閃`）：一律要求標題含 **GA/Grand Archive 關鍵字**排除跨遊戲誤中（如遊戲王「Ga P.U.N.K.」）；「系列+卡號」都中＝定位到該版本→strong，只中卡名→weak。長名標題常被截斷，靠卡號定位。
    - **普卡/閃卡**價差大（普卡 5、閃卡 180），用願望清單的 **`lang` 欄位承載**（值「普卡」「閃卡」，比照鋼彈用 lang 裝版本）——所以 GA 沒有獨立 foil 欄位，前端 GA 的「lang 選單」顯示普/閃。稀有度是版本固有屬性不需選。
    - ⚠️ **同名不同號會弱命中**：卡名是另一張卡名的子字串時（如「Volnia」命中「Zinn, Volnia Abbess」）會以 weak 混入；已靠 strong 優先＋離群價過濾緩解，要更準需比對標題卡號差異。

12. **一覽排序：新系列在前**（四款一致）：寶可夢 `id DESC`、遊戲王 `cid DESC` 天然新→舊；鋼彈無發售日欄位，用 **`app.py` 的 `GUNDAM_SET_ORDER`**（手寫發售順序清單，舊→新）建 `CASE` 排序鍵，一覽與產品下拉都依此新→舊——**出新系列時往清單末端補代碼即可**。GA 用官方 API 的 **`set_release`**（發售日，crawler 存入 `ga_cards.set_release`）`ORDER BY DESC`，新系列自動排前、免手動維護。

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
- **鋼彈異圖比價**：已用稀有度 `+`／`++` 層級分版（見第五節第 4 點，2026-07-21 實作），基礎／LR+／LR++ 各自精準。**唯一例外**：同稀有度平行卡（base 與異圖同為 R、無 `+`）無法只靠 `+` 分辨，會落在同一批（價位相近、影響小）。

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
7. **多人各自的清單（2026-07-21）**：同內網多人連同一站時，各自有獨立的 Webhook 與通知清單。做法**輕量、免登入**：前端每個瀏覽器產一組隨機 `client_id`（存 localStorage，`clientId()`），到價相關請求都以 **`X-Client-Id` 標頭**帶上（`alertFetch()`）。後端 `price_alerts` 加 `client_id` 欄位、Webhook 存 `app_settings` 的 `webhook:<client_id>` 鍵；所有端點按 `client_id` 過濾＋驗證擁有者（改/刪別人的通知回 404）。背景檢查 `check_all(client_id=None)` 跑**全部人**、每筆用**該通知主人的 Webhook**（`get_webhook(conn, client_id)`，逐 client 快取）；網頁「立即檢查」只查**自己**的（`check_all(client_id=cid)`）。⚠️ **非嚴謹權限**：靠瀏覽器隨機 ID 認人，清掉瀏覽器資料＝重置自己那份；且各訪客的 Webhook 存在主機 DB（主機端看得到）。適用朋友群內網自用，不是對外多租戶。舊資料若有 `client_id=NULL` 的通知（前一版單人時建的）不屬於任何 client、UI 不顯示，排程仍會查但無 webhook 不推播。

**排程（選用，要背景自動跑才需要）**——比照週更新那套，自行註冊 Windows 排程（電腦要開著）：
```
schtasks /Create /TN CardBuySearch-Alerts /SC HOURLY /MO 3 ^
  /TR "\"C:\path\to\python.exe\" \"%CD%\crawler\check_alerts.py\""
```
移除：`schtasks /Delete /TN CardBuySearch-Alerts /F`。日誌 `data/alerts.log`。
不註冊排程也能用——按網頁上的「🔄 立即檢查一次」手動觸發。

**已知取捨**：檢查頻率越高越快通知、但對露天請求量越大（非官方 API，別太密）。目前建議 3 小時一次。多筆通知是逐一查露天（每筆數秒），通知很多時「立即檢查」會跑一陣子（背景執行、前端輪詢顯示進度）。

---

## 十、我的收藏（庫存 / 扣除已收藏）

**動機**：原本網站只回答「我缺什麼」（願望清單），沒有「我已經有什麼」。玩家匯入牌組後得自己用腦扣掉手上已有的卡，才知道真正要買哪幾張——這步一直是手動的。收藏補上這塊，把流程接成一條線：**匯入牌組 → 扣掉收藏 → 只把真正缺的送去比價**。

**資料表 `collections`**（見 `db.py`）：`client_id / game / card_id / rarity / lang / art / qty / unit_price`。同卡的不同版本各自一列，唯一鍵是 `(client_id, game, card_id, rarity, lang, art)`（用 `IFNULL(...,'')` 運算式索引，因為這三個條件常是 NULL）。

**幾個設計重點**：

1. **存後端不存 localStorage**：收藏是長期資料又帶成本價，清瀏覽器不該蒸發。沿用到價通知那套 `client_id`＋`X-Client-Id` 標頭做多人隔離（同樣是免登入、非嚴謹權限）。
2. **`/api/collection/deduct` 只算不寫**：回傳每張卡「已有幾張、還缺幾張、扣到哪幾筆收藏」，前端顯示明細讓使用者確認後才真的改清單。故意不做成一鍵靜默扣除——扣錯了使用者要能看出來。
3. **條件比對刻意寬鬆**（`_cond_match`）：稀有度/紙種/異圖三個條件，**任一邊沒指定就不算衝突，兩邊都指定才需相等**。因為使用者常常沒把收藏的版本填完整，嚴格比對會變成「明明有卡卻扣不掉」。代價是條件標示不全時可能多扣，所以第 2 點的確認明細是配套、不能拿掉。
4. **一張收藏不會被重複計算**：`deduct` 用 `remaining` 逐項扣、先到先得。條件寬鬆時同一筆收藏可能同時符合多個願望項目，沒有這層會把同一張卡算兩次。
5. **市值來自 `price_history`，不另外查露天**：`_market_price()` 先找同版本條件的最近一筆快照，沒有才退回「同卡不分條件」（前端標 `＊`）。**沒比價過的卡就是沒有市值，據實留白不猜**。因此市值只有在使用者跑過比價/到價檢查之後才會逐漸長出來。
6. **成本是選填**：只有部分收藏記了成本時，統計列會加註「損益不含未記的」，避免把 0 成本當成免費入手而誤讀損益。
7. **願望清單的 📦（買到了）**：把該筆連同目前選的版本條件整筆移進收藏並移出清單，數量會與既有收藏合併。這是「買完之後」的收尾動作，讓清單→收藏形成循環。

**動到的既有程式**：卡片格子原本只有一顆按鈕，改成 `.card-btns` 包「加入清單＋📦」兩顆，因此所有 `.card-item ... button` 的選取器都改成 **`button.add`**（漏改會讓「已加入」狀態復原時誤觸收藏鈕）。`.card-item > button { margin-top: auto }` 的釘底規則同步改到 `.card-btns` 上，維持同列卡片按鈕對齊。

---

## 十一、一覽行情、我的牌組、流動性（對標卡拍拍第二批）

### 1. 一覽/搜尋顯示「$X 起」

卡拍拍每張卡都掛 `lowestPrice`，一覽的資訊密度差很多。做法是 `_attach_prices()`（`app.py`）把 `price_history` **最近一次**的最低價批次掛到 `/api/search` 與 `/api/browse` 的回傳上。

- **不即時查露天**：一頁 60 張要查 60 次，不可行。顯示的是歷史快照，前端 tooltip 標明日期與「非即時」。
- **沒比價過的卡就是沒有價格**，據實留空不推估（同收藏市值的原則）。所以這個欄位是隨使用累積出來的。
- 一次批次查完整頁（`ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY ts DESC)`），避免 N+1。
- ⚠️ **卡號型別**：`price_history.card_id` 是 INTEGER 親和欄位，寶可夢/遊戲王的數字卡號存進去會變 int，鋼彈/GA 的字串卡號維持 text。比對時**兩邊都轉字串**，否則會變成寶可夢對得到、鋼彈對不到。

### 2. 我的牌組（`decks` 表）

原本「匯入牌組」是一次性的——匯完就散成願望清單，牌組本身沒留下。存起來才能「我有三套牌，切換看各自缺什麼」。

- `items` 存 **JSON**，格式與分享連結完全相同（`[{g,id,q,r,l,a}]`），**刻意不拆 deck_cards 子表**：這個站的規模用不到關聯查詢，一欄 JSON 少一半程式碼。
- 前端載入牌組走**既有的 `/api/cards` 還原路徑**——把分享連結那段抽成 `hydrateIntoWishlist()`，兩邊共用；`wishlistCompact()` 同理讓「分享」與「存牌組」用同一套序列化，不會走鐘。
- **同名視為覆蓋**（回傳 `overwritten` 讓前端講清楚），避免存一存冒出五個「主牌」。
- 載入會蓋掉目前清單，所以先 `confirm`；載入後會重算搜尋結果區的「已加入」狀態。
- `/api/cards` 的 ids 上限從 40 放寬到 **200**（遊戲王主+額外的卡種數可破 40，原本會被默默截斷）。

### 3. 流動性（在售量／累計成交量）

露天 prod API 本來就回 `StockQty`／`SoldQty`，之前只用來濾掉缺貨商品，沒存下來。現在 `ruten.liquidity()` 把一批商品彙總成 `(商品數, 在售總量, 累計成交量)`，**比價與到價通知兩個寫入點都存進 `price_history`** 的新欄位（`listings`/`stock`/`sold`），比價結果也直接顯示。

用途是分辨「這個價位是真的便宜」還是「這卡根本沒人買」。商品數 ≤2 且無成交紀錄時標 ⚠ 提醒參考性低。

⚠️ **`sold` 是賣場商品的累計成交量、不是本期增量**，只能看相對熱度，不要拿來算成交速度。舊資料列的三個欄位是 NULL（遷移只加欄位，不回填）。

---

## 十二、匯入校對、追蹤排行、歷史瀏覽、相對目標價（對標卡拍拍第三批）

### 1. 匯入校對頁（對標 `/batchmatch/result`）

**牌組匯入不再直接塞進願望清單**，改成先出校對頁：逐張列出比對到的卡、張數、**原始牌表行**，可逐項取消勾選，確認後才加入。

關鍵是 `/api/import-deck` 現在多回 **`match`（`exact`／`fuzzy`）與 `sources`（原始行）**：

- `exact` = 卡號或完整卡名命中；`fuzzy` = 退到 `LIKE`／`search_ygo` 模糊比對才對到。
- **同一張卡被多行對到時，只要有一行是模糊的就整筆標模糊**（保守提醒）。
- 前端把 fuzzy 那幾列標 ⚠ 並上底色。這是這頁存在的理由——遊戲王譯名亂、寶可夢同名多版本、鋼彈異圖，錯的幾乎都出在模糊比對那幾行。

### 2. 你最常查的卡（`/api/trending`）

⚠️ **這不是市場熱門榜**。資料來自 `price_history`，也就是**這台機器查過的紀錄**；卡拍拍那種全站熱門需要平台級成交資料，本站沒有。UI 文案已據實寫明，**別改成「熱門卡」之類的說法**。

至少查過 2 次才列入（單次算不出漲跌）；漲跌 = 期間最後一次 vs 第一次的最低價。依 `(card_id, rarity, lang)` 分組，所以同卡不同版本各自一列。

### 3. 歷史瀏覽

純前端（`localStorage` 的 `cbs_history`，上限 24 筆）。開過卡片詳情就記一筆、重複的往前挪。橫向捲動不換行，紀錄再多也只佔一列高度。

### 4. 相對目標價（`parseTargetPrice`）

設/改到價目標時除了純數字，還可填 **`-10%`**（比基準低一成）或 **`-30`**（比基準少 30）。基準優先用當下露天最低價，查不到才退回 30 天均價；**基準為 null 時只接受純數字**，避免相對於「沒有」算出怪數字。`/api/quote` 因此多回 `avg_price`／`hist_low`／`hist_samples`／`stock`／`sold`。

### 5. 刻意沒做的兩項（別誤以為漏了）

- **賣家賣場頁**：比價結果**已經**有賣家的露天賣場連結（`store_url`）＋該賣家能供應清單中哪幾張＋評價，等於卡拍拍賣場頁的實用部分。要再做「站內列出該賣家全部庫存」得新增一支**露天未公開的賣場列表端點**，與「露天改版即失效／控制請求頻率」的既有取捨衝突，效益又低，故不做。
- **寶可夢繁中↔日文版互查**（卡拍拍會在繁中卡同時查日文版商品）：本站寶可夢資料**只有繁中**（來源是官方繁中卡查），要做得先建一份日文寶可夢卡庫＋爬蟲，等於再加一款遊戲的工作量，**不是小功能**，需要先決定要不要投入。
