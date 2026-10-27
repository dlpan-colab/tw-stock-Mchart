"""
台股技術與籌碼分析系統 - 本地與歷史資料管理模組
封裝 SQLite 資料庫操作（三大法人、融券融資、集保持股分級），
並管理歷史個股清單的持久化讀寫。

【防護規則】
點擊巡航導航（上一個/下一個）切換個股時，嚴禁呼叫置頂寫入操作，
避免造成索引洗牌與死循環；僅在手動點擊「查詢」時才執行置頂存檔。
"""
# ==============================================================================
# 模組名稱: storage
# 模組版本: 202610271500
# 核心職責: 本地 SQLite 資料庫讀寫、歷程紀錄持久化（絕不隨意洗牌順序）
# ==============================================================================

MODULE_NAME = "storage"
MODULE_VERSION = "202610271500"

import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import config

# ------------------------------------------------------------------------------
# 1. 歷史紀錄持久化管理
# ------------------------------------------------------------------------------
def load_stock_history():
    """讀取歷史查詢清單 (維持原始儲存順序，不洗牌)"""
    path = config.HISTORY_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []

def save_stock_history(code, name):
    """將查詢成功的標的置頂存入歷史紀錄 (手動查詢時才呼叫)"""
    if not code:
        return
    code = str(code).strip()
    name = str(name).strip() if name else ""
    
    hist = load_stock_history()
    # 移除舊有相同代碼，將最新查詢項目置頂
    hist = [h for h in hist if h.get("code") != code]
    hist.insert(0, {"code": code, "name": name, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
    
    # 保持最多 30 筆
    hist = hist[:30]
    
    try:
        os.makedirs(os.path.dirname(config.HISTORY_FILE), exist_ok=True)
    except Exception:
        pass

    try:
        with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 嘗試背景觸發 Google Drive 同步
    try:
        import cloud_sync
        cloud_sync.push_to_drive(config.HISTORY_FILE)
    except Exception:
        pass

def clear_stock_history():
    """清除歷史紀錄"""
    path = config.HISTORY_FILE
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    try:
        import cloud_sync
        cloud_sync.delete_from_drive(os.path.basename(path))
    except Exception:
        pass

# ------------------------------------------------------------------------------
# 2. SQLite 籌碼資料表管理
# ------------------------------------------------------------------------------
def get_db_connection():
    """取得 SQLite 連線並初始化資料表"""
    try:
        os.makedirs(os.path.dirname(config.DB_FILE), exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(config.DB_FILE)
    init_db(conn)
    return conn

def init_db(conn):
    """建立三大法人、資券與集保分級表格"""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chip_summary (
            date TEXT,
            symbol TEXT,
            foreign_buy REAL,
            trust_buy REAL,
            dealer_buy REAL,
            margin_balance REAL,
            margin_change REAL,
            short_balance REAL,
            short_change REAL,
            short_ratio REAL,
            PRIMARY KEY (date, symbol)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tdcc_distribution (
            date TEXT,
            symbol TEXT,
            level INTEGER,
            holders INTEGER,
            shares REAL,
            percent REAL,
            PRIMARY KEY (date, symbol, level)
        )
    ''')
    conn.commit()

def load_chip_from_db(symbol, start_date):
    """自本地 SQLite 讀取三大法人與資券數據"""
    conn = get_db_connection()
    query = """
        SELECT * FROM chip_summary 
        WHERE symbol = ? AND date >= ?
        ORDER BY date ASC
    """
    try:
        df = pd.read_sql_query(query, conn, params=(symbol, start_date))
        return df
    finally:
        conn.close()

def save_chip_to_db(df):
    """將抓取的法人資券數據批次存入 SQLite"""
    if df is None or df.empty:
        return
    conn = get_db_connection()
    try:
        df.to_sql('chip_summary', conn, if_exists='append', index=False)
    except Exception:
        pass
    finally:
        conn.close()

def load_tdcc_from_db(symbol):
    """自本地 SQLite 讀取集保戶股權分級歷史"""
    conn = get_db_connection()
    query = """
        SELECT * FROM tdcc_distribution 
        WHERE symbol = ?
        ORDER BY date ASC, level ASC
    """
    try:
        df = pd.read_sql_query(query, conn, params=(symbol,))
        return df
    finally:
        conn.close()

def save_tdcc_to_db(df):
    """將集保股權分級資料存入 SQLite"""
    if df is None or df.empty:
        return
    conn = get_db_connection()
    try:
        df.to_sql('tdcc_distribution', conn, if_exists='append', index=False)
    except Exception:
        pass
    finally:
        conn.close()
