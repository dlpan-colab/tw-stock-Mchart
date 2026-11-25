"""
storage.py - 本地 SQLite 資料庫與股票歷史紀錄管理器（對外統一入口）
(依邏輯職責拆分為 strg_cloud_names.py、strg_history_maint.py、strg_broker_mixin.py 與本核心檔案，維持 100% 向後相容匯出)
版本: 202611252208
"""

import os
import sqlite3
import pandas as pd

MODULE_NAME = "storage"
MODULE_VERSION = "202611252208"

from strg_cloud_names import (
    STORAGE_DIR,
    HISTORY_FILE,
    NAMES_CACHE_FILE,
    COMMON_STOCK_NAMES,
    is_tw_stock_or_etf,
    is_tw_index_with_gov_brokers,
    _async_run,
    _do_sync_cloud_pull,
    _sync_cloud_pull,
    _do_sync_cloud_push,
    _sync_cloud_push,
    _do_sync_db_pull,
    sync_db_pull,
    _do_sync_db_push,
    sync_db_push,
    _load_name_cache,
    _save_name_cache,
    load_stock_names_dict,
    get_stock_chinese_name,
)

# 【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
# 1. 修改目的：補匯出 `clear_all_stocks_chip_all`（清除所有資券/法人/大戶籌碼資料）
#    與 `clear_tw_index_gov_broker_range`（清除指定期間八大官股資料），供 `app_settings.py` 呼叫。
# 2. 防呆防錯原因：維持 `storage.py` 作為所有子模組之統一對外匯出入口，確保既有引用路徑 100% 相容。
from strg_history_maint import (
    _recover_history_from_databases,
    load_stock_history,
    save_stock_history,
    update_stock_name_only,
    clear_stock_history,
    remove_stocks_from_history,
    clear_recent_margin_data,
    clear_recent_institutional_data,
    _collect_all_stock_codes_local_and_cloud,
    clear_all_stocks_chip_range,
    clear_all_stocks_chip_all,
    clear_all_stocks_broker_range,
    clear_all_broker_data,
    clear_tw_index_gov_broker_range,
    clear_tw_index_gov_broker_data,
)

from strg_broker_mixin import BrokerStorageMixin


class StockChipStorage(BrokerStorageMixin):
    def __init__(self, pure_code: str):
        self.pure_code = str(pure_code).strip().upper()
        self.db_name = f"data_{self.pure_code}.db"
        self.db_path = os.path.join(STORAGE_DIR, self.db_name)
        sync_db_pull(self.pure_code)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_k (
                    date TEXT PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS institutional_investors (
                    date TEXT PRIMARY KEY,
                    foreign_net REAL,
                    trust_net REAL,
                    dealer_net REAL
                )
            ''')
            # 【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
            # 新增 margin_money_diff（融資金額增減，億元）與 margin_money_bal（融資金額餘額，億元）兩欄位，
            # 供上市加權指數（^TWII）與櫃買指數（^TWOII）儲存融資金額變動，並自動為舊資料庫執行 ALTER TABLE 補欄。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS margin_short (
                    date TEXT PRIMARY KEY,
                    margin_diff REAL,
                    short_diff REAL,
                    margin_bal REAL,
                    short_bal REAL,
                    margin_money_diff REAL DEFAULT 0.0,
                    margin_money_bal REAL DEFAULT 0.0
                )
            ''')
            cursor.execute("PRAGMA table_info(margin_short)")
            ms_cols = {row[1] for row in cursor.fetchall()}
            if "margin_money_diff" not in ms_cols:
                cursor.execute("ALTER TABLE margin_short ADD COLUMN margin_money_diff REAL DEFAULT 0.0")
            if "margin_money_bal" not in ms_cols:
                cursor.execute("ALTER TABLE margin_short ADD COLUMN margin_money_bal REAL DEFAULT 0.0")

            # 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
            # 修改目的：檢查既有資料庫之 shareholding_distribution 欄位結構，若缺少 holders 或 shares 欄位，
            # 自動執行 ALTER TABLE 補欄，解決舊版 .db 寫入 5 欄時觸發 sqlite3.OperationalError 的問題。
            # 防呆防錯原因：完整保留舊表既有日期與持股比例資料，僅補齊缺漏欄位。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shareholding_distribution (
                    date TEXT,
                    level INTEGER,
                    holders INTEGER,
                    shares INTEGER,
                    percent REAL,
                    PRIMARY KEY (date, level)
                )
            ''')
            cursor.execute("PRAGMA table_info(shareholding_distribution)")
            sh_cols = {row[1] for row in cursor.fetchall()}
            if sh_cols:
                if "holders" not in sh_cols:
                    cursor.execute("ALTER TABLE shareholding_distribution ADD COLUMN holders INTEGER DEFAULT 0")
                if "shares" not in sh_cols:
                    cursor.execute("ALTER TABLE shareholding_distribution ADD COLUMN shares INTEGER DEFAULT 0")

            # 【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
            # 修改目的：檢查舊版資料庫（如 data_6669.db）之 broker_daily_trades 與 broker_range_rank 欄位結構，
            # 若缺少新版欄位，自動重建為最新資料表結構，避免寫入或查詢時觸發 OperationalError: table ... has no column named ...。
            # 防呆防錯原因：僅重建可重新抓取之分點資料表，完整保留 daily_k、institutional_investors、margin_short 與 shareholding_distribution。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broker_daily_trades (
                    broker_name TEXT,
                    trade_date TEXT,
                    buy_sheets INTEGER DEFAULT 0,
                    sell_sheets INTEGER DEFAULT 0,
                    net_sheets INTEGER DEFAULT 0,
                    PRIMARY KEY (broker_name, trade_date)
                )
            ''')
            cursor.execute("PRAGMA table_info(broker_daily_trades)")
            bdt_cols = {row[1] for row in cursor.fetchall()}
            required_bdt_cols = {"broker_name", "trade_date", "buy_sheets", "sell_sheets", "net_sheets"}
            if bdt_cols and not required_bdt_cols.issubset(bdt_cols):
                cursor.execute("DROP TABLE IF EXISTS broker_daily_trades")
                cursor.execute('''
                    CREATE TABLE broker_daily_trades (
                        broker_name TEXT,
                        trade_date TEXT,
                        buy_sheets INTEGER DEFAULT 0,
                        sell_sheets INTEGER DEFAULT 0,
                        net_sheets INTEGER DEFAULT 0,
                        PRIMARY KEY (broker_name, trade_date)
                    )
                ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broker_range_rank (
                    range_date TEXT,
                    win_days INTEGER,
                    side TEXT,
                    rank INTEGER,
                    broker_name TEXT,
                    broker_sys TEXT,
                    buy_sheets INTEGER DEFAULT 0,
                    sell_sheets INTEGER DEFAULT 0,
                    net_sheets INTEGER DEFAULT 0,
                    ratio_str TEXT,
                    range_label TEXT,
                    PRIMARY KEY (range_date, win_days, side, rank)
                )
            ''')
            cursor.execute("PRAGMA table_info(broker_range_rank)")
            br_cols = {row[1] for row in cursor.fetchall()}
            required_br_cols = {
                "range_date", "win_days", "side", "rank",
                "broker_name", "broker_sys", "buy_sheets", "sell_sheets",
                "net_sheets", "ratio_str", "range_label"
            }
            if br_cols and not required_br_cols.issubset(br_cols):
                cursor.execute("DROP TABLE IF EXISTS broker_range_rank")
                cursor.execute('''
                    CREATE TABLE broker_range_rank (
                        range_date TEXT,
                        win_days INTEGER,
                        side TEXT,
                        rank INTEGER,
                        broker_name TEXT,
                        broker_sys TEXT,
                        buy_sheets INTEGER DEFAULT 0,
                        sell_sheets INTEGER DEFAULT 0,
                        net_sheets INTEGER DEFAULT 0,
                        ratio_str TEXT,
                        range_label TEXT,
                        PRIMARY KEY (range_date, win_days, side, rank)
                    )
                ''')

            # 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
            # 修改目的：建立關注交易日專屬分點日況資料表 broker_focus_daily_series，
            # 明確以 (focus_date, window_days, side, rank_no, trade_date) 作為複合主鍵，綁定各關注交易日對應 W10/W20/W60 前五名分點之逐日買賣超值。
            # 防呆防錯原因：徹底隔離不同關注交易日之分點日況柱狀圖，避免滑鼠切換至無逐日明細的歷史關注日（如 10/22）時誤抓最新交易日（如 11/20）重疊邊界日殘影。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broker_focus_daily_series (
                    focus_date TEXT,
                    window_days INTEGER,
                    side TEXT,
                    rank_no INTEGER,
                    broker_name TEXT,
                    total_net INTEGER DEFAULT 0,
                    trade_date TEXT,
                    buy_sheets INTEGER DEFAULT 0,
                    sell_sheets INTEGER DEFAULT 0,
                    net_sheets INTEGER DEFAULT 0,
                    PRIMARY KEY (focus_date, window_days, side, rank_no, trade_date)
                )
            ''')

            # 【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
            # 1. 修改目的：建立大盤加權（^TWII）與櫃買指數（^TWOII）八大官股個股逐日分欄明細資料表 gov_index_stock_daily，
            #    記錄每個交易日、每檔個股（股票名稱）的 8 家官股行庫各自買賣超（萬元）與合計（萬元）。
            # 2. 防呆防錯原因：以 (trade_date, stock_name) 為主鍵並以 source_side 區分當日買超前30或賣超前30來源，避免跨日或重複寫入覆蓋錯亂。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gov_index_stock_daily (
                    trade_date TEXT,
                    stock_name TEXT,
                    source_side TEXT,
                    b_heku REAL DEFAULT 0.0,
                    b_land REAL DEFAULT 0.0,
                    b_bot REAL DEFAULT 0.0,
                    b_tbb REAL DEFAULT 0.0,
                    b_ccb REAL DEFAULT 0.0,
                    b_first REAL DEFAULT 0.0,
                    b_mega REAL DEFAULT 0.0,
                    b_hncb REAL DEFAULT 0.0,
                    total_wan REAL DEFAULT 0.0,
                    PRIMARY KEY (trade_date, stock_name)
                )
            ''')

            cursor.execute("DELETE FROM shareholding_distribution WHERE level > 15 OR level < 1")
            conn.commit()

    def get_latest_daily_k_date(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT MAX(date) FROM daily_k").fetchone()
            return res[0] if res and res[0] else ""

    def save_daily_k_df(self, df: pd.DataFrame):
        if df is None or df.empty:
            return
        records = []
        for idx, row in df.iterrows():
            d_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
            records.append((
                d_str,
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                float(row['Volume'])
            ))
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR REPLACE INTO daily_k (date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', records)
            conn.commit()
        sync_db_push(self.pure_code)

    def load_daily_k_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("SELECT * FROM daily_k ORDER BY date ASC", conn)
            if df.empty:
                return pd.DataFrame()
            df['Date'] = pd.to_datetime(df['date'])
            df.set_index('Date', inplace=True)
            df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }, inplace=True)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]

    def get_latest_institutional_date(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT MAX(date) FROM institutional_investors").fetchone()
            return res[0] if res and res[0] else ""

    def get_latest_margin_date(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT MAX(date) FROM margin_short").fetchone()
            return res[0] if res and res[0] else ""

    def get_latest_holding_date(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT MAX(date) FROM shareholding_distribution").fetchone()
            return res[0] if res and res[0] else ""

    def save_institutional_data(self, records: list):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR REPLACE INTO institutional_investors (date, foreign_net, trust_net, dealer_net)
                VALUES (?, ?, ?, ?)
            ''', records)
            conn.commit()
        sync_db_push(self.pure_code)

    def save_margin_data(self, records: list):
        """
        【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
        同時支援 5 欄（個股：date, margin_diff, short_diff, margin_bal, short_bal）
        與 7 欄（大盤/櫃買：含 margin_money_diff, margin_money_bal 億元）寫入格式，維持向後相容。
        """
        if not records:
            return
        norm_records = []
        for r in records:
            if len(r) >= 7:
                norm_records.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
            else:
                norm_records.append((r[0], r[1], r[2], r[3], r[4], 0.0, 0.0))
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR REPLACE INTO margin_short
                (date, margin_diff, short_diff, margin_bal, short_bal, margin_money_diff, margin_money_bal)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', norm_records)
            conn.commit()
        sync_db_push(self.pure_code)

    def save_holding_data(self, records: list):
        """
        【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
        1. 修改目的：向下相容 5 欄 (date, level, holders, shares, percent) 與舊版 3 欄 (date, level, percent) 寫入格式，
           將集保每週公告之真實股數（shares）存入 shareholding_distribution.shares，隨每週更新自動反映增資/減資/庫藏股異動。
        2. 防呆防錯原因：嚴格限定 1 <= level <= 15（排除第 16 差異數與第 17 合計列）；若遇舊資料庫缺欄觸發 OperationalError，
           自動呼叫 self._init_db() 補欄並重試寫入一次。
        """
        if not records:
            return
        norm_records = []
        for r in records:
            if not r or len(r) < 3:
                continue
            lvl = int(r[1])
            if not (1 <= lvl <= 15):
                continue
            if len(r) >= 5:
                holders_v = int(r[2] or 0)
                shares_v = int(r[3] or 0)
                pct_v = float(r[4] or 0.0)
                norm_records.append((str(r[0])[:10], lvl, holders_v, shares_v, pct_v))
            else:
                pct_v = float(r[2] or 0.0)
                norm_records.append((str(r[0])[:10], lvl, 0, 0, pct_v))
        if not norm_records:
            return

        sql_ins = '''
            INSERT OR REPLACE INTO shareholding_distribution (date, level, holders, shares, percent)
            VALUES (?, ?, ?, ?, ?)
        '''
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(sql_ins, norm_records)
                conn.commit()
        except sqlite3.OperationalError:
            self._init_db()
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(sql_ins, norm_records)
                conn.commit()
        sync_db_push(self.pure_code)

    def get_latest_tdcc_total_shares(self) -> float:
        """
        【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
        1. 修改目的：動態加總本地 shareholding_distribution 最新一週（含有效 shares > 0）之 1～15 級真實股數，
           回傳最新總發行股數（單位：股），隨每週集保更新自動同步增資、減資、庫藏股註銷與面額變更，絕不依賴永久死快取。
        2. 防呆防錯原因：僅查詢有 shares > 0 之最新週別並嚴格限制 1 <= level <= 15，若尚無集保股數則回傳 0.0 供上層備援。
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                row_dt = conn.execute(
                    "SELECT MAX(date) FROM shareholding_distribution WHERE level >= 1 AND level <= 15 AND shares > 0"
                ).fetchone()
                if not row_dt or not row_dt[0]:
                    return 0.0
                latest_dt = str(row_dt[0])[:10]
                row_sum = conn.execute(
                    "SELECT SUM(shares) FROM shareholding_distribution WHERE date = ? AND level >= 1 AND level <= 15",
                    (latest_dt,)
                ).fetchone()
                tot = float(row_sum[0] or 0.0) if row_sum else 0.0
                return tot if tot > 0 else 0.0
        except Exception:
            return 0.0

    def load_institutional_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("SELECT * FROM institutional_investors ORDER BY date ASC", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df

    def load_margin_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("SELECT * FROM margin_short ORDER BY date ASC", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                if 'margin_money_diff' not in df.columns:
                    df['margin_money_diff'] = 0.0
                if 'margin_money_bal' not in df.columns:
                    df['margin_money_bal'] = 0.0
            return df

    def load_holding_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT * FROM shareholding_distribution WHERE level >= 1 AND level <= 15 ORDER BY date ASC, level ASC",
                conn
            )
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df
## EOF storage.py
