"""
台股技術與籌碼分析系統 - 本地與歷史資料管理模組
以 Google Drive 雲端資料庫為單一真實來源。
強化 SSL 連線防護與例外隔離，杜絕啟動時 Segmentation fault 崩潰。
歷史導航清單維持嚴格 LRU（最近查詢置頂）排序。
"""

MODULE_NAME = "storage"
MODULE_VERSION = "202610291945"

import os
import re
import ssl
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


def is_valid_tw_stock_name(name: str) -> bool:
    """
    通用名稱驗證：
    1. 長度在 1 到 10 個字元內（支援一般中文、世芯-KY、GIS-KY、TPK-KY）
    2. 排除 yfinance 常見的長英文全名與公司結尾關鍵字
    """
    if not name or not isinstance(name, str):
        return False
    clean_name = name.strip()
    if len(clean_name) > 10 or len(clean_name) == 0:
        return False
    upper_name = clean_name.upper()
    invalid_keywords = ['INC', 'LTD', 'CORP', 'HOLDING', 'TECH', 'CO.', 'LIMITED']
    if any(kw in upper_name for kw in invalid_keywords):
        return False
    return True


# ==========================================
# 1. 股票晶片資料庫存取類別 (StockChipStorage)
# ==========================================
class StockChipStorage:
    def __init__(self, pure_code: str):
        self.pure_code = str(pure_code).strip().upper()
        self.db_name = f"data_{self.pure_code}.db"
        self.db_path = str(DATA_DIR / self.db_name)
        
        # 步驟 1：優先從 Google Drive 拉取雲端既有的 .db（安全連線包裝）
        sync = _get_cloud_sync()
        if not IS_COLAB and sync and not os.path.exists(self.db_path):
            try:
                sync.pull_file(Path(self.db_path))
            except (ssl.SSLError, OSError, Exception) as e:
                logger.warning(f"從雲端拉取 {self.db_name} 失敗（已安全略過）: {e}")

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
            except (ssl.SSLError, OSError, Exception):
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
            except (ssl.SSLError, OSError, Exception):
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
            except (ssl.SSLError, OSError, Exception):
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
# 2. 歷史個股清單管理（安全防崩潰與 LRU 排序）
# ==========================================
def load_stock_history() -> List[dict]:
    history_file = Path(HISTORY_FILE_PATH)
    sync = _get_cloud_sync()
    
    # 步驟 1：安全從雲端拉取歷史檔，攔截底層 SSL/IO 崩潰
    if not IS_COLAB and sync:
        try:
            sync.pull_file(history_file)
        except (ssl.SSLError, OSError, Exception) as e:
            logger.warning(f"同步 stock_history.json 失敗（已安全轉由本地接手）: {e}")

    existing_history = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "code" in item:
                            # 通用名稱驗證：若名稱不合法（如英文全銜），降級顯示代碼
                            c = str(item["code"])
                            n = str(item.get("name", c))
                            if not is_valid_tw_stock_name(n):
                                n = c
                            existing_history.append({"code": c, "name": n})
        except Exception:
            pass

    # 步驟 2：安全取得 Google Drive 現存的 .db 清單（連線異常時不中斷主程式）
    drive_codes = []
    if not IS_COLAB and sync and hasattr(sync, "service") and sync.service and sync.folder_id:
        try:
            q = f"'{sync.folder_id}' in parents and trashed = false and name contains '.db'"
            res = sync.service.files().list(q=q, fields="files(name)").execute()
            for item in res.get("files", []):
                m = re.search(r'data_(\w+)\.db', item["name"])
                if m:
                    drive_codes.append(m.group(1))
        except (ssl.SSLError, OSError, Exception):
            pass

    # 步驟 3：嚴格保持 LRU 順序
    ordered_list = []
    seen = set()
    for item in existing_history:
        code = item.get("code")
        if code and code not in seen:
            ordered_list.append(item)
            seen.add(code)

    # 步驟 4：若 Google Drive 有尚未列入歷史的 .db，補在末端
    name_cache = load_stock_names_cache()
    if drive_codes:
        for code in drive_codes:
            if code not in seen:
                raw_n = name_cache.get(code, code)
                c_name = raw_n if is_valid_tw_stock_name(raw_n) else code
                ordered_list.append({"code": code, "name": c_name})
                seen.add(code)

    if ordered_list:
        return ordered_list

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

    # 名稱合法性驗證（長度 <= 10 且非 yfinance 英文全名）
    valid_name = name if is_valid_tw_stock_name(name) else ""

    final_name = valid_name
    for item in history:
        if item.get("code") == code:
            if not final_name:
                item_name = item.get("name", code)
                final_name = item_name if is_valid_tw_stock_name(item_name) else code
            break
    if not final_name:
        final_name = code

    # 抽出舊位置並強制插入最上位（第 0 位）
    history = [item for item in history if item.get("code") != code]
    history.insert(0, {"code": code, "name": final_name})

    history_file = Path(HISTORY_FILE_PATH)
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        sync = _get_cloud_sync()
        if not IS_COLAB and sync:
            sync.push_file(history_file)
    except (ssl.SSLError, OSError, Exception):
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
    except (ssl.SSLError, OSError, Exception):
        pass
    return []


# ==========================================
# 3. 中文名稱快取讀寫（通用長度過濾防線）
# ==========================================
def load_stock_names_cache() -> Dict[str, str]:
    cache_path = str(STOCK_NAMES_CACHE_PATH)
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 過濾掉先前意外存入的過長英文全稱
            clean_cache = {}
            for k, v in data.items():
                if is_valid_tw_stock_name(v):
                    clean_cache[k] = v
            return clean_cache
    except Exception:
        return {}

def save_stock_names_cache(cache_data: Dict[str, str]):
    cache_path = str(STOCK_NAMES_CACHE_PATH)
    try:
        clean_cache = {k: v for k, v in cache_data.items() if is_valid_tw_stock_name(v)}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(clean_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
