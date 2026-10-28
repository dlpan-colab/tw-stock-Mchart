"""
台股技術與籌碼分析系統 - 本地與歷史資料管理模組
以 Google Drive 為單一來源：查詢前優先 pull_file，儲存後即刻 push_file。
"""

MODULE_NAME = "storage"
MODULE_VERSION = "202610281045"

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

# 確保本地資料夾存在
os.makedirs(str(DATA_DIR), exist_ok=True)


def _get_cloud_sync():
    try:
        import cloud_sync
        if hasattr(cloud_sync, "cloud_sync_manager"):
            return cloud_sync.cloud_sync_manager
        if hasattr(cloud_sync, "drive_sync"):
            return cloud_sync.drive_sync
    except Exception:
        pass
    return None


# ==========================================
# 1. 股票晶片資料庫存取類別 (StockChipStorage)
# ==========================================
class StockChipStorage:
    def __init__(self, pure_code: str):
        self.pure_code = str(pure_code).strip().upper()
        self.db_name = f"data_{self.pure_code}.db"
        self.db_path = str(DATA_DIR / self.db_name)
        
        # 關鍵優先步驟：連線 SQLite 前，強制向 Google Drive 拉取雲端既有的 .db
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            try:
                sync.pull_file(Path(self.db_path))
            except Exception as e:
                logger.warning(f"從雲端拉取 {self.db_name} 失敗: {e}")

        # 初始化資料庫結構
        self._init_db()

        # 嚴格依資料庫內容判定是否初次初始化：若三大法人已有資料，則絕非首次！
        latest_date = self.get_latest_inst_date()
        self.is_first_time = (latest_date is None)

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
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            try:
                sync.push_file(Path(self.db_path))
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
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            try:
                sync.push_file(Path(self.db_path))
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
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            try:
                sync.push_file(Path(self.db_path))
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
    history_file = Path(HISTORY_FILE_PATH)
    sync = _get_cloud_sync()
    if not IS_COLAB and sync:
        try:
            sync.pull_file(history_file)
        except Exception:
            pass

    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
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
    
    history_file = Path(HISTORY_FILE_PATH)
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, ensure_ascii=False, indent=2)
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            sync.push_file(history_file)
    except Exception:
        pass
    return new_hist

def clear_stock_history() -> List[dict]:
    history_file = Path(HISTORY_FILE_PATH)
    try:
        if history_file.exists():
            os.remove(str(history_file))
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            sync.delete_remote_file("stock_history.json")
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
