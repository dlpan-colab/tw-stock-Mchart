"""
台股技術與籌碼分析系統 - 本地與歷史資料管理模組
封裝 SQLite 資料庫操作（三大法人、融券融資、集保持股分級），
並管理歷史個股清單的持久化讀寫。

【防護規則】
點擊巡航導航（上一個/下一個）切換個股時，嚴禁呼叫置頂寫入操作，
避免造成索引洗牌與死循環；僅在手動點擊「查詢」時才執行置頂存檔。
"""

MODULE_NAME = "storage"
MODULE_VERSION = "202610271400"

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from config import DB_FILE_PATH, HISTORY_FILE_PATH, STOCK_NAMES_CACHE_PATH

logger = logging.getLogger(__name__)

class SQLiteManager:
    """SQLite 本地籌碼與技術資料庫管理器"""

    def __init__(self, db_path: Path = DB_FILE_PATH):
        self.db_path = db_path
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))

    def _init_tables(self):
        """初始化資料表綱要 Schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. 三大法人買賣超 (單位: 張)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS institutional_investors (
                    stock_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    foreign_buy_sell REAL DEFAULT 0,
                    trust_buy_sell REAL DEFAULT 0,
                    dealer_buy_sell REAL DEFAULT 0,
                    total_buy_sell REAL DEFAULT 0,
                    PRIMARY KEY (stock_id, date)
                )
            """)

            # 2. 融資融券 (單位: 張)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS margin_trading (
                    stock_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    margin_buy REAL DEFAULT 0,
                    margin_sell REAL DEFAULT 0,
                    margin_balance REAL DEFAULT 0,
                    short_buy REAL DEFAULT 0,
                    short_sell REAL DEFAULT 0,
                    short_balance REAL DEFAULT 0,
                    margin_short_ratio REAL DEFAULT 0,
                    PRIMARY KEY (stock_id, date)
                )
            """)

            # 3. 集保戶股權分級 (TDCC)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tdcc_distribution (
                    stock_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    year_week TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    holders INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0,
                    ratio REAL DEFAULT 0.0,
                    PRIMARY KEY (stock_id, date, level)
                )
            """)

            # 建立索引以加速讀取
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inst_lookup ON institutional_investors (stock_id, date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_margin_lookup ON margin_trading (stock_id, date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tdcc_lookup ON tdcc_distribution (stock_id, date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tdcc_week ON tdcc_distribution (stock_id, year_week);")

            conn.commit()

    # ==========================================
    # 三大法人存取操作
    # ==========================================
    def save_institutional_data(self, stock_id: str, df: pd.DataFrame):
        """儲存法人資料，以 Replace 避免重複寫入"""
        if df.empty:
            return
        records = []
        for _, row in df.iterrows():
            records.append((
                stock_id,
                str(row["date"]),
                float(row.get("foreign_buy_sell", 0)),
                float(row.get("trust_buy_sell", 0)),
                float(row.get("dealer_buy_sell", 0)),
                float(row.get("total_buy_sell", 0))
            ))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO institutional_investors 
                (stock_id, date, foreign_buy_sell, trust_buy_sell, dealer_buy_sell, total_buy_sell)
                VALUES (?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()

    def get_institutional_data(self, stock_id: str, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """讀取法人資料"""
        query = "SELECT date, foreign_buy_sell, trust_buy_sell, dealer_buy_sell, total_buy_sell FROM institutional_investors WHERE stock_id = ?"
        params = [stock_id]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date ASC"

        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        return df

    # ==========================================
    # 融資融券存取操作
    # ==========================================
    def save_margin_data(self, stock_id: str, df: pd.DataFrame):
        """儲存資券資料"""
        if df.empty:
            return
        records = []
        for _, row in df.iterrows():
            records.append((
                stock_id,
                str(row["date"]),
                float(row.get("margin_buy", 0)),
                float(row.get("margin_sell", 0)),
                float(row.get("margin_balance", 0)),
                float(row.get("short_buy", 0)),
                float(row.get("short_sell", 0)),
                float(row.get("short_balance", 0)),
                float(row.get("margin_short_ratio", 0))
            ))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO margin_trading 
                (stock_id, date, margin_buy, margin_sell, margin_balance, short_buy, short_sell, short_balance, margin_short_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()

    def get_margin_data(self, stock_id: str, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """讀取資券資料"""
        query = "SELECT date, margin_buy, margin_sell, margin_balance, short_buy, short_sell, short_balance, margin_short_ratio FROM margin_trading WHERE stock_id = ?"
        params = [stock_id]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date ASC"

        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        return df

    # ==========================================
    # 集保分級存取操作 (TDCC)
    # ==========================================
    def save_tdcc_data(self, stock_id: str, df: pd.DataFrame):
        """儲存集保股權分級資料"""
        if df.empty:
            return
        records = []
        for _, row in df.iterrows():
            records.append((
                stock_id,
                str(row["date"]),
                str(row["year_week"]),
                int(row["level"]),
                int(row.get("holders", 0)),
                int(row.get("shares", 0)),
                float(row.get("ratio", 0.0))
            ))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO tdcc_distribution 
                (stock_id, date, year_week, level, holders, shares, ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()

    def get_existing_tdcc_dates(self, stock_id: str) -> List[str]:
        """取得本地已存之集保日期清單 (8 碼字串: YYYYMMDD 或 YYYY-MM-DD)，供增量比對避坑"""
        query = "SELECT DISTINCT date FROM tdcc_distribution WHERE stock_id = ? ORDER BY date DESC"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (stock_id,))
            rows = cursor.fetchall()
        return [r[0] for r in rows]

    def get_tdcc_data(self, stock_id: str) -> pd.DataFrame:
        """取得該個股的所有集保歷史資料"""
        query = """
            SELECT date, year_week, level, holders, shares, ratio 
            FROM tdcc_distribution 
            WHERE stock_id = ? 
            ORDER BY date ASC, level ASC
        """
        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=[stock_id])
        return df


# ==========================================
# 歷史個股清單管理 (嚴格維護巡航不洗牌順序)
# ==========================================
class StockHistoryManager:
    """管理使用者歷史查詢清單與巡航不洗牌操作"""

    def __init__(self, file_path: Path = HISTORY_FILE_PATH, max_items: int = 50):
        self.file_path = file_path
        self.max_items = max_items

    def load_history(self) -> List[str]:
        """純讀取歷史清單，絕不改變原始清單排序與狀態"""
        if not self.file_path.exists():
            return ["2330", "2317", "2454"]
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return [str(x).strip().upper() for x in data if str(x).strip()]
                return ["2330", "2317", "2454"]
        except Exception as e:
            logger.error(f"讀取歷史紀錄失敗: {e}")
            return ["2330", "2317", "2454"]

    def save_manual_query(self, stock_id: str) -> List[str]:
        """
        僅在手動點擊「查詢」時調用：將標的置頂，若已存在則先抽離再插入頭部。
        """
        stock_id = str(stock_id).strip().upper()
        if not stock_id:
            return self.load_history()

        current_list = self.load_history()
        if stock_id in current_list:
            current_list.remove(stock_id)

        # 置於第 0 位
        updated_list = [stock_id] + current_list
        updated_list = updated_list[:self.max_items]

        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(updated_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"寫入歷史清單失敗: {e}")

        return updated_list

    def get_adjacent_ticker(self, current_ticker: str, direction: str) -> str:
        """
        巡航導航邏輯（不洗牌）：
        依目前個股在歷史清單之索引，循環尋找前一個或後一個標的。
        絕不觸發 save_manual_query()，確保清單次序嚴格穩定，防止 0 與 1 位死循環。
        """
        history = self.load_history()
        current_ticker = str(current_ticker).strip().upper()

        if current_ticker not in history:
            return history[0] if history else "2330"

        idx = history.index(current_ticker)
        if direction == "prev":
            target_idx = (idx - 1) % len(history)
        elif direction == "next":
            target_idx = (idx + 1) % len(history)
        else:
            target_idx = idx

        return history[target_idx]


# ==========================================
# 股票中文名稱持久化快取
# ==========================================
def load_stock_names_cache() -> Dict[str, str]:
    """讀取本地中文名稱對照表"""
    if not STOCK_NAMES_CACHE_PATH.exists():
        return {}
    try:
        with open(STOCK_NAMES_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"讀取中文名稱快取失敗: {e}")
        return {}

def save_stock_names_cache(cache_data: Dict[str, str]):
    """更新本地中文名稱對照表"""
    try:
        STOCK_NAMES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STOCK_NAMES_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"儲存中文名稱快取失敗: {e}")


# 全域實例
db_manager = SQLiteManager()
history_manager = StockHistoryManager()
