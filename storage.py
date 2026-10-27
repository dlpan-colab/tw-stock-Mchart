"""
台股技術與籌碼分析系統 - 本地與歷史資料管理模組
封裝 SQLite 資料庫操作（三大法人、融券融資、集保持股分級），
並管理歷史個股清單與中文名稱快取。
"""

MODULE_NAME = "storage"
MODULE_VERSION = "202610280100"

import os
import json
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd

from config import (
    DATA_DIR,
    DB_FILE_PATH,
    HISTORY_FILE_PATH,
    STOCK_NAMES_CACHE_PATH,
    IS_COLAB
)

logger = logging.getLogger(__name__)

# ==========================================
# 1. 股票晶片資料庫存取類別 (StockChipStorage)
# ==========================================
class StockChipStorage:
    def __init__(self, pure_code: str):
        self.pure_code = str(pure_code).strip().upper()
        self.db_name = f"data_{self.pure_code}.db"
        self.db_path = str(DATA_DIR / self.db_name)
        
        # 雲端同步支援
        try:
            from cloud_sync import drive_sync
            if not IS_COLAB and drive_sync.enabled and not os.path.exists(self.db_path):
                drive_sync.pull(self.db_name, self.db_path)
        except Exception:
            pass

        self.is_first_time = not os.path.exists(self.db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS institutional_investors (
                    date TEXT PRIMARY KEY,
                    foreign_net REAL,
                    trust_net REAL,
                    dealer_net REAL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shareholding_distribution (
                    date TEXT,
                    level INTEGER,
                    percent REAL,
                    PRIMARY KEY (date, level)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS margin_short (
                    date TEXT PRIMARY KEY,
                    margin_diff REAL,
                    short_diff REAL,
                    margin_bal REAL,
                    short_bal REAL
                )
            """)
            conn.commit()

    def get_latest_inst_date(self) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM institutional_investors")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def get_latest_holding_date(self) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM shareholding_distribution")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def get_latest_margin_date(self) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM margin_short")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def save_institutional_data(self, records: list):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO institutional_investors (date, foreign_net, trust_net, dealer_net)
                VALUES (?, ?, ?, ?)
            """, records)
            conn.commit()
        try:
            from cloud_sync import drive_sync
            if not IS_COLAB and drive_sync.enabled:
                drive_sync.push(self.db_path, self.db_name)
        except Exception:
            pass

    def save_holding_data(self, records: list):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO shareholding_distribution (date, level, percent)
                VALUES (?, ?, ?)
            """, records)
            conn.commit()
        try:
            from cloud_sync import drive_sync
            if not IS_COLAB and drive_sync.enabled:
                drive_sync.push(self.db_path, self.db_name)
        except Exception:
            pass

    def save_margin_data(self, records: list):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO margin_short (date, margin_diff, short_diff, margin_bal, short_bal)
                VALUES (?, ?, ?, ?, ?)
            """, records)
            conn.commit()
        try:
            from cloud_sync import drive_sync
            if not IS_COLAB and drive_sync.enabled:
                drive_sync.push(self.db_path, self.db_name)
        except Exception:
            pass

    def load_institutional_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT date, foreign_net, trust_net, dealer_net FROM institutional_investors ORDER BY date", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.normalize()
            return df

    def load_holding_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT date, level, percent FROM shareholding_distribution ORDER BY date, level", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.normalize()
            return df

    def load_margin_df(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT * FROM margin_short ORDER BY date", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.normalize()
            return df


# ==========================================
# 2. 歷史個股清單管理
# ==========================================
def load_stock_history() -> List[dict]:
    history_file = str(HISTORY_FILE_PATH)
    try:
        from cloud_sync import drive_sync
        if not IS_COLAB and drive_sync.enabled:
            drive_sync.pull("stock_history.json", history_file)
    except Exception:
        pass

    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    # 統一結構為 [{'code': ..., 'name': ...}, ...]
                    formatted = []
                    for item in data:
                        if isinstance(item, dict):
                            formatted.append(item)
                        elif isinstance(item, str):
                            formatted.append({"code": item, "name": item})
                    return formatted
        except Exception:
            pass

    return [
        {"code": "1303", "name": "南亞"},
        {"code": "6217", "name": "中探針"},
        {"code": "2609", "name": "陽明"},
        {"code": "2615", "name": "萬海"},
        {"code": "8111", "name": "立碁"},
        {"code": "4526", "name": "東台"},
        {"code": "2330", "name": "台積電"}
    ]

def save_stock_history(code: str, name: str = "") -> List[dict]:
    code = str(code).strip().upper()
    history = load_stock_history()
    new_hist = [h for h in history if h.get("code") != code]
    new_hist.insert(0, {"code": code, "name": name or code})
    new_hist = new_hist[:30]
    
    history_file = str(HISTORY_FILE_PATH)
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, ensure_ascii=False, indent=2)
        from cloud_sync import drive_sync
        if not IS_COLAB and drive_sync.enabled:
            drive_sync.push(history_file, "stock_history.json")
    except Exception:
        pass
    return new_hist

def clear_stock_history() -> List[dict]:
    history_file = str(HISTORY_FILE_PATH)
    try:
        if os.path.exists(history_file):
            os.remove(history_file)
        from cloud_sync import drive_sync
        if not IS_COLAB and drive_sync.enabled:
            drive_sync.delete("stock_history.json")
    except Exception:
        pass
    return []


# ==========================================
# 3. 中文名稱快取讀寫
# ==========================================
def load_stock_names_cache() -> Dict[str, str]:
    cache_path = str(STOCK_NAMES_CACHE_PATH)
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_stock_names_cache(cache_data: Dict[str, str]):
    cache_path = str(STOCK_NAMES_CACHE_PATH)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
