# 台股技術與籌碼分析系統（tw-stock-Mchart）

## 一、 系統模組架構
- `app.py`：主介面與狀態生命週期（唯一系統版本號權威源，動態掃描各模組最大版本號）。頂部採三主頁籤架構（`📊 操作儀錶板` / `📈 個股` / `⚙️ 參數設定`），預設收合側邊欄；「個股」主頁籤內含四大子頁籤（`📊 指標` / `💰 籌碼` / `📊 分點統計` / `📈 分點日況`）。
- `frontend.py`：Plotly 前端圖表、跨圖同步 JS（動態偵測所有 `xaxis\d*` 軸鍵名同步雙次軸平移縮放）、大盤加權（`^TWII`）與櫃買（`^TWOII`）緊緻雙列資訊列與分點雙頁籤（分點統計排行榜、分點日況逐日柱狀圖）HTML 渲染。
- `chart_builder.py`：K 線主圖（藍色加大標題）、指標頁籤（KD/MACD/OBV/20-120-240-1200日乖離率）與籌碼頁籤建置（個股 6 列副圖；`^TWII` 與 `^TWOII` 專屬緊緻雙列副圖，消除空白區，大戶線標註 `1%約=xxxx張`）。
- `indicators.py`：均線、乖離率、技術指標、5MA 波段轉折、有效流通張數週轉率（扣除近 15 週 1,000 張以上大於 0 最小持股比例）、大戶週對齊計算，以及 `^TWII` / `^TWOII` 融資金額（億）與長期／季融資及融券維持率計算。
- `data_fetcher.py`：日 K 線、三大法人、個股資券、上市全市場資券（`^TWII`）、上櫃全市場彙總資券（`^TWOII`）、集保大戶、操作儀錶板報價與富邦分點爬蟲引擎（含跨日去重歷史分點批次增補與全市資券／法人／大戶指定基準日區間批次增補）。
- `storage.py`：本地 SQLite（`data_{code}.db`）與歷史紀錄管理（與操作儀錶板自選清單雙向同步，`margin_short` 資料表含 `margin_money_diff` 與 `margin_money_bal` 億元欄位並具備舊庫自動遷移防呆）。
- `cloud_sync.py`：Google Drive 雙向同步（Service Account / Colab）。

---

## 二、 開發防呆憲法（新對話必讀，未經允許嚴禁產出程式碼）

### 1. 程式開發五項紀律與架構鐵律
- **紀律 1（先確認再動手）**：先確認問題與發生原因，再確認解決方案；**必要時須先提供 Colab 測試碼，來做確認**；非得到明確允許，嚴禁擅自產出程式碼。
- **紀律 2（依據 GitHub 實際程式碼修訂）**：維護或修改程式時，不可憑空臆測或依賴舊記憶，必須依據 GitHub 最新原始碼落實修訂。
- **紀律 3（溝通扼要直接）**：初步溝通扼要（40 字內為原則），不復述雙方已知內容，不使用情緒化、誇張或煽情形容詞。
- **紀律 4（附精確修改備註）**：修訂程式碼時，必須在修改處附帶精確的文字備註說明（標註「修改目的」與「防呆防錯原因」），保留修改依據供後續對話追蹤，避免誤刪或重工。
- **紀律 5（局部精準修訂、不重寫）**：僅針對要修訂的部分修改程式碼，未要求修改的部分（尤其已驗證之資料源與既有功能）必須完整保留，不可擅自重寫。
- **交付規範**：提供程式碼時一次只出一個完整檔案，待確認儲存完成後再出下一個；不使用教科書樣本資料敷衍應對。
- **UI 頁籤架構鐵律**：頂部三主頁籤必須維持 `st.radio(horizontal=True)`（`📊 操作儀錶板` / `📈 個股` / `⚙️ 參數設定`）並保持側邊欄收合，嚴禁改回 `st.tabs` 或側邊欄配置；「個股」內必須維持四大獨立子頁籤（`📊 指標` / `💰 籌碼` / `📊 分點統計` / `📈 分點日況`）。

### 2. 已驗證且不可隨意變動的核心資料源與演算法（個股皆以 `1303` 南亞為測試範例）
1. **5MA 波段轉折（`indicators.py`）**：收盤價相對於 5MA 切換當日必須同時納入原波段與新波段之極值（`〔頭〕`／`〔底〕`）計算，不可將轉換日排除。
2. **歷史日 K 線資料查詢（個股以 `1303` 為例）**：
   - Yahoo Finance 支援 `1y`、`2y`、`5y`、`10y`、`max`（上市代號 `1303.TW`、上櫃代號 `4749.TWO`；測試網址：`https://query1.finance.yahoo.com/v8/finance/chart/1303.TW?range=1y&interval=1d`），支援含英文後綴之台股 ETF（如 `00632R.TW`、`00664R.TW`、`00676R.TW`、`00631L.TW`）。
   - 最新交易日延遲缺口自動補齊：
     - 上市個股（如 `1303`）：證交所盤後個股日成交資訊 `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261101&stockNo=1303`
     - 上櫃個股（如 `4749`）：櫃買中心個股日成交資訊 `https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d=115/11&stkno=4749`
3. **大盤加權指數（`^TWII`）與櫃買指數（`^TWOII`）資券與融資金額**：
   - `^TWII`：主資料源 FinMind `TaiwanStockTotalMarginPurchaseShortSale`（`https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTotalMarginPurchaseShortSale&start_date=2026-10-01`，`MarginPurchaseMoney` 除以 `1e8` 轉為億元），最新單日備援補齊為證交所信用交易統計 `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&selectType=MS&date=20261127`（`融資金額(千元)` 除以 `1e5` 轉為億元）。
   - `^TWOII`：主資料源嗨投資 `https://histock.tw/stock/three.aspx?m=mg&no=TWOI`（直接讀取彙總欄位：`融資餘額(億)`、`融資增加(億)`、`融券餘額(張)`、`融券增加(張)`）；上櫃全市場彙總無融資總張數，`margin_diff` / `margin_bal` 必須維持 `0.0`，絕不可將金額誤充當張數。
4. **集保大戶股權分散表（`data_fetcher.py`，個股以 `1303` 為例）**：
   - 個股多週歷史查詢：集保官網 `https://www.tdcc.com.tw/portal/zh/smWeb/qryStock`（POST 帶入 `scaDate=YYYYMMDD`、`sqlMethod=StockNo`、`stockNo=1303`，必須逐輪更新表單回傳之 `SYNCHRONIZER_TOKEN`，且嚴格過濾 `1 <= level <= 15`，排除第 16 差異數與第 17 合計列）。
   - 單週批次更新：集保開放資料 `https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`（CSV 全市場當週資料，依 `證券代號 == '1303'` 過濾）。
   - 嚴禁使用免費版無授權之 FinMind `TaiwanStockHoldingSharesPer`。
5. **券商分點進出排行與逐日明細（`data_fetcher.py`，個股以 `1303` 為例）**：
   - 個股分點進出排行主頁（富邦 e點通）：
     - 預設最新交易日：`https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a=1303`
     - 指定日期區間（`e=起日`、`f=迄日`）：`https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a=1303&e=2026-11-27&f=2026-11-27`
     - 支援「左買超 5 欄＋右賣超 5 欄（共 10 欄並排）」與上下分表格式。
   - **單一分點歷史明細表（`zco0.djhtm`）測試網址（以 `1303` 南亞、富邦證券總公司 `9600` 為例）**：
     - `https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco0/zco0.djhtm?a=1303&b=9600&c=E&e=2026-11-01&f=2026-11-27`
     - **實測固定 5 欄結構**：`['日期', '買進(張)', '賣出(張)', '買賣總額(張)', '買賣超(張)']`（索引 `0` 至 `4`），其中**第 5 欄（`cells[4]`）為「買賣超(張)」且網頁本身即帶正確正負號**，第 4 欄（`cells[3]`）為恆正之「買賣總額(張)」。
   - 富邦每日 15:00 後更新當日分點資料；15:00（含）前預設對齊前一交易日（跳過週六日）。
   - 大盤／櫃買八大官股買賣超排行（嗨投資）：
     - 上市：`https://histock.tw/stock/public.aspx`
     - 上櫃：`https://histock.tw/stock/public.aspx?m=otc`
6. **三大法人買賣超（個股以 `1303` 為例）**：
   - 上市全市場（篩選 `證券代號 == '1303'`）：證交所 `https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date=20261127`
   - 上櫃全市場（篩選 `代號 == '4749'`）：櫃買中心 `https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d=115/11/27`
   - 單一個股歷史備援（以 `1303` 為例）：FinMind `https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=1303&start_date=2026-10-01`
7. **個股信用交易（資券，以 `1303` 為例）**：
   - 主資料源 FinMind：`https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id=1303&start_date=2026-10-01`
   - 上市當日備援補齊（篩選 `股票代號 == '1303'`）：證交所 `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&selectType=ALL&date=20261127`

### 3. 除錯與重大重工教訓實錄（嚴禁重蹈覆轍）
- **【2026-11-22 重大重工事故實錄】未先以 Colab 實測網頁真實欄位，誤將富邦明細第 4 欄「買賣總額(張)」抓成第 5 欄「買賣超(張)」，且錯誤推卸歸責網站**：
  1. **事故經過**：在未先以 Colab 印出富邦單一分點逐日明細網頁（`zco0.djhtm`）真實表頭前，主觀假設該網頁僅有 4 欄 `['日期', '買進(張)', '賣出(張)', '買賣超(張)']`，實際上網頁固定為 **5 欄** `['日期', '買進(張)', '賣出(張)', '買賣總額(張)', '買賣超(張)']`。程式讀取 `cells[3]` 時，抓到的其實是恆為正值的「買賣總額（買進＋賣出）」，而非 `cells[4]`（已自帶正確正負號的「買賣超(張)」）。
  2. **錯誤診斷與推卸行為**：當前端分點日況柱狀圖出現買超、賣超分點天天全數顯示紅柱時，AI 未先驗證原始 HTML 表格結構，便在溝通中以「通常」臆測欄位，甚至錯誤歸責為「富邦網頁將賣超分點每日明細提供為正值」、提議在前端或抓檔層做正負號反轉補丁，誤導使用者在資料庫層反覆排查，最終導致使用者花費時間執行 **27 檔股票近 120 日分點批次抓取**後，分點日況逐日明細全部作廢重工。
  3. **永久鐵律**：
     - **任何外部網頁爬蟲欄位索引修改或新增前，必須先在 Colab 印出實際 `<tr>` / `<td>` 完整欄位清單與表頭，禁止用「通常」、「可能」臆測欄位位置。**
     - **禁止在未檢視原始網頁 HTML 表格前，將資料異常推卸給外部網站格式問題，更禁止為掩蓋欄位抓錯而寫特例補丁。**
- **跨頁籤與圖表同步教訓**：
  - 使用 `st.radio` 切換主頁籤或切換股票時，圖表元件須帶入隨標的與查詢次序變動之動態 `chart_id`，防止 Streamlit 重複使用舊 iframe 導致跨標的數據殘留。
  - 籌碼副圖雙次軸（雙 Y 軸）平移同步時，必須動態擷取 `_fullLayout` 內所有 `/^xaxis\d*$/` 鍵名一併 `relayout`，不可寫死僅同步 `xaxis`～`xaxis5`。
  - 隱藏頁籤內之 Plotly 圖表（如「📈 分點日況」）須於容器實際可見寬度 `> 0` 時再繪製或透過 `ResizeObserver` 重繪，避免預設 700px 寬度導致手機版右側遭裁切。
