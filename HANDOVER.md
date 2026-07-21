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
| **鋼彈 GCG** | 官方繁中站 gundam-gcg.com/zh-tw（爬蟲） | 官方卡圖（日文卡面） | 785 |
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

4. **稀有度中文俗稱**（`ruten.py` 的 `YGO_RARITIES`）：以露天實證建立——金鑽=QCSE、半鑽=SEC、全鑽=EXSEC、紅鑽=20th、白鑽=PSER…改動前務必實測，別憑印象。

5. **UI 隱藏元素的坑**（踩過兩次）：`display:flex/grid` 會蓋過 HTML `hidden` 屬性。已加全域保險絲 `[hidden]{display:none!important}`（style.css 開頭），**勿移除**。驗證 UI 顯示/隱藏一定要看 computed style，不能只查 `.hidden` 屬性。

6. **殭屍伺服器**：Windows 允許多程序綁同一埠，重啟時舊 server 會搶請求造成「怎麼改都是舊的」。`start.bat` 啟動前會自動清掉 5000 埠上的舊 Python 程序。

7. **靜態檔快取**：`app.py` 設 `SEND_FILE_MAX_AGE_DEFAULT=0`＋首頁資產版本戳，改版重新整理即生效，不必 Ctrl+F5。

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

---

## 七、已知限制 / 可能的下一步

- **遊戲王「產品」篩選未做**：一張卡收錄在多個卡包（平均 2.8 個、共 818 種），多對多不好用單選下拉呈現。寶可夢/鋼彈的產品篩選已完成。
- **未部署對外**：目前僅本機/內網。要對外需 Cloudflare Tunnel 或 VPS（使用者目前不需要）。
- 露天為非官方介面，長期維護成本主要在「露天改版時修爬蟲」。
- 遊戲王/鋼彈卡圖有官方 SAMPLE 浮水印（官方資料庫的圖都這樣），不影響辨識。

---

## 八、程式碼慣例

- Commit 訊息用 **`[Hibari] `** 前綴，並 push 到 origin（github.com/Yukiho0524/CardBuySearch）。
- 每完成一個階段就 commit＋push。
- 註解、變數用繁體中文，與現有風格一致。
- 資料檔可手動編輯：`ygo_aliases.json`（遊戲王譯名別名）、`pkm_products.json`（寶可夢產品名）。
