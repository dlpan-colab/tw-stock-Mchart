"""
storage.py - 本地 SQLite 資料庫與股票歷史紀錄管理器
版本: sto_311110
"""

import os
import io
import json
import sqlite3
import requests
from bs4 import BeautifulSoup
import pandas as pd

MODULE_VERSION = "sto_311110"

STORAGE_DIR = "."
HISTORY_FILE = os.path.join(STORAGE_DIR, "stock_history.json")
NAMES_CACHE_FILE = os.path.join(STORAGE_DIR, "tw_stock_names.json")

# 內建常用名稱對照表
COMMON_STOCK_NAMES = {
    "1101": "台泥", "1102": "亞泥", "1104": "環泥", "1216": "統一",
    "1301": "台塑", "1303": "南亞", "1312": "國喬", "1326": "台化",
    "1504": "東元", "2002": "中鋼", "2105": "正新", "2303": "聯電",
    "2308": "台達電", "2312": "金寶", "2317": "鴻海", "2324": "仁寶",
    "2327": "國巨", "2330": "台積電", "2374": "佳能", "2382": "廣達",
    "2454": "聯發科", "2478": "大毅", "2492": "華新科", "2609": "陽明",
    "2615": "萬海", "3008": "大立光", "3022": "威強電", "3088": "艾訊",
    "3231": "緯創", "3481": "群創", "3653": "健策", "3661": "世芯-KY",
    "4526": "東台", "5439": "高技", "6191": "精成科", "6217": "中探針",
    "6234": "高僑", "6456": "GIS-KY", "6505": "台塑化", "8111": "立碁"
}

def get_stock_chinese_name(pure_code: str) -> str:
    pure_code = str(pure_code).strip()
    if pure_code in COMMON_STOCK_NAMES:
        return COMMON_STOCK_NAMES[pure_code]

    if os.path.exists(NAMES_CACHE_FILE):
        try:
            with open(NAMES_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if pure_code in cached and cached[pure_code]:
                    return cached[pure_code]
        except Exception:
            pass

    # 1. 查 TWSE (上市)
    try:
        url_twse = f"https://isin.twse.com.tw/isin/single_main.jsp?owncode={pure_code}&stockname="
        res = requests.get(url_twse, timeout=4)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for r in soup.find_all('tr'):
                cols = r.find_all('td')
                if len(cols) >= 3 and cols[1].text.strip() == pure_code:
                    c_name = cols[2].text.strip()
                    if c_name:
                        _save_name_cache(pure_code, c_name)
                        return c_name
    except Exception:
        pass

    # 2. 查 TPEx (上櫃)
    try:
        url_tpex = f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&stkno={pure_code}"
        res_t = requests.get(url_tpex, timeout=4)
        if res_t.status_code == 200:
            data = res_t.json()
            if 'aaData' in data and len(data['aaData']) > 0:
                c_name = str(data['aaData'][0][1]).strip()
                if c_name:
                    _save_name_cache(pure_code, c_name)
                    return c_name
    except Exception:
        pass

    return pure_code

def _save_name_cache(code: str, name: str):
    COMMON_STOCK_NAMES[code] = name
    try:
        cached = {}
        if os.path.exists(NAMES_CACHE_FILE):
            with open(NAMES_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
        cached[code] = name
        with open(NAMES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False)
    except Exception:
        pass

def load_stock_history():
    data = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []

    if not isinstance(data, list) or not data:
        data = [
            {"code": "4526", "name": "東台"},
            {"code": "1504", "name": "東元"},
            {"code": "2382", "name": "廣達"},
            {"code": "6456", "name": "GIS-KY"},
            {"code": "2330", "name": "台積電"}
        ]

    for item in data:
        code = str(item.get("code", "")).strip()
        curr_name = str(item.get("name", "")).strip()
        if not curr_name or curr_name == code:
            item["name"] = get_stock_chinese_name(code)
    return data

def save_stock_history(code: str, name: str = None):
    """輸入查詢或選單選取時調用：將該股票提升到清單第 1 筆 (Index 0)"""
    code = str(code).strip()
    if not code:
        return load_stock_history()
    c_name = name.strip() if name and name.strip() != code else get_stock_chinese_name(code)
    history = load_stock_history()
    new_hist = [h for h in history if str(h.get("code")).strip() != code]
    new_hist.insert(0, {"code": code, "name": c_name})
    new_hist = new_hist[:30]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return new_hist

def update_stock_name_only(code: str, name: str):
    """上一檔/下一檔巡覽時調用：僅修正名稱缺漏，絕不變動歷史清單的排列順序"""
    code = str(code).strip()
    if not code or not name or name.strip() == code:
        return
    history = load_stock_history()
    changed = False
    for item in history:
        if str(item.get("code")).strip() == code:
            if item.get("name") != name:
                item["name"] = name
                changed = True
            break
    if changed:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def remove_history_items(codes_to_remove: list):
    """僅移除被勾選項"""
    history = load_stock_history()
    new_hist = [h for h in history if str(h.get("code")).strip() not in codes_to_remove]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return new_hist

def clear_stock_history():
    """清除全部歷史清單"""
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
    except Exception:
        pass
    return []

class StockChipStorage:
    def __init__(self, pure_code: str):
        self.pure_code = str(pure_code).strip()
        self.db_name = f"data_{self.pure_code}.db"
        self.db_path = os.path.join(STORAGE_DIR, self.db_name)
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

    def get_latest_inst_date(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM institutional_investors")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def get_latest_margin_date(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM margin_short")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def save_institutional_data(self, records):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("INSERT OR REPLACE INTO institutional_investors VALUES (?, ?, ?, ?)", records)
            conn.commit()

    def save_margin_data(self, records):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("INSERT OR REPLACE INTO margin_short VALUES (?, ?, ?, ?, ?)", records)
            conn.commit()

    def save_holding_data(self, records):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("INSERT OR REPLACE INTO shareholding_distribution VALUES (?, ?, ?)", records)
            conn.commit()

    def load_institutional_df(self):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT date, foreign_net, trust_net, dealer_net FROM institutional_investors ORDER BY date", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.normalize()
            return df

    def load_margin_df(self):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT * FROM margin_short ORDER BY date", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.normalize()
            return df

    def load_holding_df(self):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT date, level, percent FROM shareholding_distribution ORDER BY date, level", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.normalize()
            return df
