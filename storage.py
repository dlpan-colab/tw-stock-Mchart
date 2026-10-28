"""
台股技術與籌碼分析系統 - 本地與歷史資料管理模組
以 Google Drive 雲端資料庫為單一真實來源。
歷史導航清單自動對齊 Google Drive 內已建檔之個股，避免切換時重複初始化。
"""

MODULE_NAME = "storage"
MODULE_VERSION = "202610281145"

import os
import re
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
        
        # 步驟 1：優先從 Google Drive 拉取雲端既有的 .db
        sync = _get_cloud_sync()
        if not IS_COLAB and sync and not os.path.exists(self.db_path):
            try:
                sync.pull_file(Path(self.db_path))
            except Exception as e:
                logger.warning(f"從雲端拉取 {self.db_name} 失敗: {e}")

        # 步驟 2：初始化結構
        self._init_db()

        # 步驟 3：判定是否為初次
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
# 2. 歷史個股清單管理（對齊 Google Drive 現存資料庫）
# ==========================================
def load_stock_history() -> List[dict]:
    """優先抓取 Google Drive 上現有的 .db 檔建立清單，確保每檔皆秒開"""
    history_file = Path(HISTORY_FILE_PATH)
    sync = _get_cloud_sync()
    
    # 嘗試從 Google Drive 讀取現有檔案清單
    drive_codes = []
    if not IS_COLAB and sync and hasattr(sync, "service") and sync.service and sync.folder_id:
        try:
            q = f"'{sync.folder_id}' in parents and trashed = false and name contains '.db'"
            res = sync.service.files().list(q=q, fields="files(name)").execute()
            for item in res.get("files", []):
                m = re.search(r'data_(\w+)\.db', item["name"])
                if m:
                    drive_codes.append(m.group(1))
        except Exception:
            pass

    # 讀取本地/雲端 JSON
    if not IS_COLAB and sync:
        try:
            sync.pull_file(history_file)
        except Exception:
            pass

    existing_history = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "code" in item:
                            existing_history.append(item)
        except Exception:
            pass

    name_map = {item["code"]: item.get("name", item["code"]) for item in existing_history}

    # 若成功取得 Google Drive 雲端資料庫列表，以雲端現有清單為準
    if drive_codes:
        final_list = []
        for code in drive_codes:
            final_list.append({"code": code, "name": name_map.get(code, code)})
        return final_list

    if existing_history:
        return existing_history

    return [
        {"code": "1303", "name": "南亞"},
        {"code": "2330", "name": "台積電"},
        {"code": "2317", "name": "鴻海"},
        {"code": "2609", "name": "陽明"},
        {"code": "2615", "name": "萬海"}
    ]

def save_stock_history(code: str, name: str = "") -> List[dict]:
    code = str(code).strip().upper()
    history = load_stock_history()
    # 保持清單穩定，不強制隨意打亂順序，若新股票則加入最前
    found = False
    for item in history:
        if item.get("code") == code:
            if name:
                item["name"] = name
            found = True
            break
    if not found:
        history.insert(0, {"code": code, "name": name or code})
    
    history_file = Path(HISTORY_FILE_PATH)
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            sync.push_file(history_file)
    except Exception:
        pass
    return history

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
