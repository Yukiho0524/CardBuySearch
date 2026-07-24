# CardBuySearch — TCG 缺卡湊齊比價

幫 TCG 玩家找出「能一次買齊整套缺卡」的賣家。
支援：**寶可夢繁中卡**（官方卡查）＋ **遊戲王**（百鴿 ygocdb）＋ **鋼彈 GCG**（官方繁中站）＋ **Grand Archive**（官方 API，英文）× **露天拍賣**（即時比價）。

## 功能

1. **卡片搜尋**：
   - 寶可夢：卡名 / 卡片編號（如 `094/081`），可過濾稀有度
   - 遊戲王：卡名（繁中/簡中/日文/英文皆可搜）
   - **以圖搜卡**：上傳卡片照片，用感知雜湊找最相近的卡
     （需先跑 `python crawler/imghash.py --game ygo|pkm` 建索引；
     照片盡量裁到只剩卡片本體）
   - **牌組匯入**：貼 YDK 檔內容或文字牌表（「3 灰流麗」）直接生成清單
2. **願望清單**：把缺的卡加入清單、指定數量；
   遊戲王卡可指定**稀有度**（自動只列該卡出過的）、**紙種**（日紙/韓紙/英紙/簡中）
   與**版本**（一般/超框異圖）；清單自動保存於瀏覽器，可產生分享連結
3. **比價**：單賣家全齊排序、雙賣家組合、拆買基準、價位視覺化、
   賣家評價、30 天價格走勢（查詢紀錄累積）
4. **同賣家湊齊比價**：即時查露天，列出
   - 能一次湊齊全部卡的賣家（含運費總價）
   - 覆蓋不齊的賣家（標示缺哪幾張）
   - 拆買基準：每張卡取全站最低價、跨賣家運費各計的總價，供對照
5. **到價通知**：為想要的卡設定目標價，程式定期到露天查詢，
   當最低價跌破目標時透過**你自己填的 Discord Webhook** 推播通知。
   在願望清單每張卡按 🔔 設定（沿用該卡已選的稀有度/紙種/版本條件），
   於「🔔 到價通知」面板管理。Webhook 只存在本機、僅用於推播。

## 安裝與啟動

最簡單：**雙擊 `start.bat`**——自動檢查套件（缺才安裝）、啟動網站並開啟瀏覽器。
啟動後視窗會顯示「同內網的人開啟」的網址（本機 IP:5000），同一區域網路的
同事在瀏覽器輸入即可使用。首次若同事連不上，對 `start.bat` 按右鍵「以系統
管理員身分執行」一次以開放防火牆連接埠。

手動：

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

鋼彈 GCG（約 785 張，來源：官方繁中站 gundam-gcg.com/zh-tw，可斷點續爬）：

```
python crawler/gundam.py
```

Grand Archive（約 2,240 張/4,504 版本，全英文，來源：官方 API api.gatcg.com）：

```
python crawler/grand_archive.py
```

爬蟲有 0.6 秒禮貌延遲並支援斷點續爬，中斷後重跑會接續。

### 自動更新

已註冊 Windows 工作排程「CardBuySearch-Weekly-Update」（每週日 04:00），
執行 `crawler/update_all.py`：寶可夢增量爬蟲（重掃各稀有度前 3 頁）、
ygocdb 全量重匯、譯名字典重學、圖片索引補建、Konami 收錄預抓。
日誌在 `data/update.log`。移除排程：`schtasks /Delete /TN CardBuySearch-Weekly-Update /F`

### 到價通知（Discord）

在「🔔 到價通知」面板填入你自己的 Discord Webhook 網址
（Discord 伺服器設定 → 整合 → Webhook → 新增，複製網址），
再到願望清單每張卡按 🔔 設定目標價即可。網頁上按「🔄 立即檢查一次」可手動觸發；
要背景自動定期檢查，自行註冊 Windows 排程（電腦需開著）：

```
schtasks /Create /TN CardBuySearch-Alerts /SC HOURLY /MO 3 ^
  /TR "\"C:\path\to\python.exe\" \"%CD%\crawler\check_alerts.py\""
```

達標時會推播到你的 Discord。防重複通知：達標推播一次後，價格回到目標以上才會重置。
日誌在 `data/alerts.log`。移除排程：`schtasks /Delete /TN CardBuySearch-Alerts /F`

## 架構

```
app.py            Flask 後端（/api/search、/api/compare、/img 卡圖代理快取）
konami.py         Konami 官方 DB：抓卡片收錄卡包/稀有度（加入清單時按需快取）
db.py             SQLite schema（cards＝寶可夢印刷版本、ygo_cards＝遊戲王卡）
crawler/pokemon.py  官方繁中卡查爬蟲（兩階段）
crawler/yugioh.py   遊戲王匯入（ygocdb 匯出檔，OpenCC 簡轉繁）
crawler/imghash.py  卡圖感知雜湊索引（以圖搜卡用，可斷點續跑）
ruten.py          露天搜尋 + 商品標題比對（稀有度俗稱字典、日/韓紙判斷、排除套組/同人卡）
alerts.py         到價通知檢查邏輯（端點與排程共用，重用 ruten 比對）
notify.py         Discord Webhook 推播（達標通知／測試訊息）
crawler/check_alerts.py  到價通知排程 CLI（達標則推播，日誌 data/alerts.log）
static/           前端（純 HTML/JS/CSS，繁中 UI）
```

遊戲王的稀有度與紙種依「印刷版本」而異，由使用者在加入願望清單時指定；
加入清單時會向 Konami 官方 DB 查這張卡的收錄紀錄（快取於 ygo_printings），
**稀有度下拉只列這張卡實際出過的稀有度**。比對時利用標題行話
（亮面/金亮/鑽石/雕鑽…）判斷稀有度。

紙種依台灣市場慣例判斷：**日紙較貴、賣家一定明標，完全沒標的一律推定韓紙**。
選日紙只收標題明寫「日紙」「日版」的——「日文」「日本正版」只是描述語言/正版來源
不算數，卡號 `-JP` 也不算證據（韓版卡常標日版卡號）；
選韓紙收明標韓紙＋未標示者（未標示者信心降級提示）。

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
