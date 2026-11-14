"""
storage.py - 本地 SQLite 資料庫與股票歷史紀錄管理器 (支援含英文後綴台股ETF與雲端分點增量累積版)
版本: 202611141210
"""

import os
import io
import re
import json
import glob
import sqlite3
import time
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

MODULE_NAME = "storage"
MODULE_VERSION = "202611141210"

STORAGE_DIR = "."
HISTORY_FILE = os.path.join(STORAGE_DIR, "stock_history.json")
NAMES_CACHE_FILE = os.path.join(STORAGE_DIR, "tw_stock_names.json")


def is_tw_stock_or_etf(code: str) -> bool:
    """【修訂說明 2026-11-14】識別台股個股與含英文後綴之ETF（如 00632R、00664R、00679B、00631L）"""
    c = str(code or "").strip().upper()
    if not c or c.startswith("^"):
        return False
    return bool(re.match(r"^\d{4,6}[A-Z]{0,2}$", c))


COMMON_STOCK_NAMES = {
    # 主要市場指數
    "^TWII": "加權指數", "^TWOII": "櫃買指數",
    "^DJI": "道瓊指數", "^IXIC": "那斯達克", "^SOX": "費城半導體",
    "^GSPC": "標普500", "^N225": "日經225", "^KS11": "韓國綜合",
    "^FTSE": "英國富時100", "^GDAXI": "德國DAX", "^FCHI": "法國CAC40",
    # 常用台股 ETF（含反向與槓桿型）
    "0050": "元大台灣50", "0056": "元大高股息", "00878": "國泰永續高股息",
    "00919": "群益台灣精選高息", "00929": "復華台灣科技優息", "00940": "元大台灣價值高息",
    "006208": "富邦台50", "00631L": "元大台灣50正2", "00632R": "元大台灣50反1",
    "00663L": "國泰臺灣加權正2", "00664R": "國泰臺灣加權反1",
    "00675L": "富邦臺灣加權正2", "00676R": "富邦臺灣加權反1",
    "00685L": "群益臺灣加權正2", "00686R": "群益臺灣加權反1",
    "00691R": "兆豐藍籌30反1", "00679B": "元大美債20年", "00687B": "國泰20年美債",
    # 常用個股
    "1101": "台泥", "1102": "亞泥", "1104": "環泥", "1216": "統一",
    "1301": "台塑", "1303": "南亞", "1312": "國喬", "1326": "台化",
    "1504": "東元", "2002": "中鋼", "2105": "正新", "2303": "聯電",
    "2308": "台達電", "2312": "金寶", "2317": "鴻海", "2324": "仁寶",
    "2327": "國巨", "2330": "台積電", "2374": "佳能", "2382": "廣達",
    "2454": "聯發科", "2478": "大毅", "2492": "華新科", "2609": "陽明",
    "2615": "萬海", "3008": "大立光", "3022": "威強電", "3088": "艾訊",
    "3231": "緯創", "3481": "群創", "3653": "健策", "3661": "世芯-KY",
    "3718": "中光電投控", "4526": "東台", "4991": "環宇-KY", "5439": "高技",
    "6191": "精成科", "6217": "中探針", "6234": "高僑", "6425": "易發",
    "6456": "GIS-KY", "6505": "台塑化", "8111": "立碁", "8131": "福懋科"
}


def _async_run(func, *args, **kwargs):
    """將耗時的網路同步作業丟入背景執行緒，絕不卡死前端主頁面"""
    t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    t.start()


def _do_sync_cloud_pull():
    try:
        from cloud_sync import pull_file
        pull_file("stock_history.json", HISTORY_FILE)
        pull_file("tw_stock_names.json", NAMES_CACHE_FILE)
    except Exception as e:
        print(f"[CloudSync] Pull warning: {e}")


def _sync_cloud_pull():
    if not os.path.exists(HISTORY_FILE) or not os.path.exists(NAMES_CACHE_FILE):
        _do_sync_cloud_pull()


def _do_sync_cloud_push(allow_empty_history: bool = False):
    try:
        from cloud_sync import push_file
        if os.path.exists(HISTORY_FILE):
            can_push = True
            if not allow_empty_history:
                try:
                    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                        chk_data = json.load(f)
                        if not chk_data or len(chk_data) == 0:
                            can_push = False
                except Exception:
                    can_push = False
            if can_push:
                push_file(HISTORY_FILE, "stock_history.json")
        if os.path.exists(NAMES_CACHE_FILE):
            push_file(NAMES_CACHE_FILE, "tw_stock_names.json")
    except Exception as e:
        print(f"[CloudSync] Push warning: {e}")


def _sync_cloud_push(allow_empty_history: bool = False):
    _async_run(_do_sync_cloud_push, allow_empty_history=allow_empty_history)


def _do_sync_db_pull(pure_code: str):
    try:
        from cloud_sync import pull_file
        db_name = f"data_{pure_code}.db"
        local_path = os.path.join(STORAGE_DIR, db_name)
        pull_file(db_name, local_path)
    except Exception as e:
        print(f"[CloudSync] DB pull warning for {pure_code}: {e}")


def sync_db_pull(pure_code: str):
    db_name = f"data_{pure_code}.db"
    local_path = os.path.join(STORAGE_DIR, db_name)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return
    _do_sync_db_pull(pure_code)


def _do_sync_db_push(pure_code: str):
    try:
        from cloud_sync import push_file
        db_name = f"data_{pure_code}.db"
        local_path = os.path.join(STORAGE_DIR, db_name)
        if os.path.exists(local_path):
            push_file(local_path, db_name)
    except Exception as e:
        print(f"[CloudSync] DB push warning for {pure_code}: {e}")


def sync_db_push(pure_code: str):
    _async_run(_do_sync_db_push, pure_code)


def _load_name_cache() -> dict:
    try:
        if os.path.exists(NAMES_CACHE_FILE):
            with open(NAMES_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_name_cache(code: str, name: str):
    code = str(code).strip().upper()
    name = str(name).strip()
    if not code or not name or name == code:
        return
    COMMON_STOCK_NAMES[code] = name
    try:
        cached = _load_name_cache()
        cached[code] = name
        with open(NAMES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)
        _sync_cloud_push()
    except Exception:
        pass


def load_stock_names_dict() -> dict:
    cache = _load_name_cache()
    if not cache:
        return COMMON_STOCK_NAMES
    merged = COMMON_STOCK_NAMES.copy()
    merged.update(cache)
    return merged


def get_stock_chinese_name(pure_code: str) -> str:
    pure_code = str(pure_code).strip().upper()
    if not pure_code:
        return ""
    if pure_code in COMMON_STOCK_NAMES:
        return COMMON_STOCK_NAMES[pure_code]
    cache = _load_name_cache()
    if pure_code in cache and cache[pure_code] and cache[pure_code] != pure_code:
        return cache[pure_code]
    if pure_code.startswith("^"):
        return pure_code

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url_twse = f"https://isin.twse.com.tw/isin/single_main.jsp?owncode={pure_code}&stockname="
    for attempt in range(2):
        try:
            res = requests.get(url_twse, headers=headers, timeout=3)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for r in soup.find_all("tr"):
                    cols = [td.text.replace("\u3000", " ").strip() for td in r.find_all("td")]
                    if len(cols) >= 4 and cols[2].upper() == pure_code:
                        c_name = cols[3].strip()
                        if c_name and c_name != pure_code:
                            _save_name_cache(pure_code, c_name)
                            return c_name
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.2)

    try:
        url_openapi = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
        res_o = requests.get(url_openapi, headers=headers, timeout=3)
        if res_o.status_code == 200:
            data = res_o.json()
            if isinstance(data, list):
                for row in data:
                    c = str(row.get("Code", "")).strip().upper()
                    n = str(row.get("Name", "")).replace("\u3000", " ").strip()
                    if c and n:
                        COMMON_STOCK_NAMES[c] = n
                        if c == pure_code:
                            _save_name_cache(pure_code, n)
                            return n
    except Exception:
        pass

    try:
        url_tpex = f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&stkno={pure_code}"
        res_t = requests.get(url_tpex, headers=headers, timeout=3)
        if res_t.status_code == 200:
            data = res_t.json()
            if "aaData" in data and len(data["aaData"]) > 0:
                c_name = str(data["aaData"][0][1]).replace("\u3000", " ").strip()
                if c_name and c_name != pure_code:
                    _save_name_cache(pure_code, c_name)
                    return c_name
    except Exception:
        pass

    try:
        for suffix in [".TW", ".TWO"]:
            y_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={pure_code}{suffix}"
            y_res = requests.get(y_url, headers=headers, timeout=3)
            if y_res.status_code == 200:
                quotes = y_res.json().get("quotes", [])
                if quotes:
                    shortname = quotes[0].get("shortname") or quotes[0].get("longname")
                    if shortname:
                        c_name = shortname.split()[0].replace("\u3000", " ").strip()
                        if c_name and len(c_name) <= 12:
                            _save_name_cache(pure_code, c_name)
                            return c_name
    except Exception:
        pass

    return pure_code


def _recover_history_from_databases() -> list:
    recovered = []
    seen = set()
    try:
        from cloud_sync import GoogleDriveSync
        sync_client = GoogleDriveSync()
        if sync_client.service and sync_client.folder_id:
            q = f"'{sync_client.folder_id}' in parents and name contains 'data_' and name contains '.db' and trashed = false"
            res = sync_client.service.files().list(
                q=q,
                fields="files(id, name, modifiedTime)",
                orderBy="modifiedTime desc",
                pageSize=50
            ).execute()
            files = res.get("files", [])
            for f in files:
                fname = f.get("name", "")
                pure = fname.replace("data_", "").replace(".db", "").strip().upper()
                if (is_tw_stock_or_etf(pure) or pure.startswith("^")) and pure not in seen:
                    seen.add(pure)
                    recovered.append({"code": pure, "name": get_stock_chinese_name(pure)})
    except Exception as e:
        print(f"[Storage] 雲端資料庫掃描還原失敗: {e}")

    local_files = glob.glob(os.path.join(STORAGE_DIR, "data_*.db"))
    local_files.sort(key=os.path.getmtime, reverse=True)
    for p in local_files:
        base = os.path.basename(p)
        pure = base.replace("data_", "").replace(".db", "").strip().upper()
        if (is_tw_stock_or_etf(pure) or pure.startswith("^")) and pure not in seen:
            seen.add(pure)
            recovered.append({"code": pure, "name": get_stock_chinese_name(pure)})

    if recovered:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(recovered[:30], f, ensure_ascii=False, indent=2)
            _sync_cloud_push(allow_empty_history=False)
        except Exception:
            pass
    return recovered[:30]


def load_stock_history():
    _sync_cloud_pull()
    data = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    if not isinstance(data, list):
        data = []
    if not data:
        data = _recover_history_from_databases()
    for item in data:
        code = str(item.get("code", "")).strip().upper()
        item["code"] = code
        curr_name = str(item.get("name", "")).strip()
        if not curr_name or curr_name == code:
            item["name"] = get_stock_chinese_name(code)
    return data


def save_stock_history(code: str, name: str = None):
    code = str(code).strip().upper()
    if not code:
        return load_stock_history()
    c_name = name.strip() if name and name.strip() != code else get_stock_chinese_name(code)
    history = load_stock_history()
    new_hist = [h for h in history if str(h.get("code")).strip().upper() != code]
    new_hist.insert(0, {"code": code, "name": c_name})
    new_hist = new_hist[:30]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, ensure_ascii=False, indent=2)
        _sync_cloud_push()
    except Exception:
        pass
    return new_hist


def update_stock_name_only(code: str, name: str):
    code = str(code).strip().upper()
    if not code or not name or name.strip() == code:
        return
    history = load_stock_history()
    changed = False
    for item in history:
        if str(item.get("code")).strip().upper() == code:
            if item.get("name") != name:
                item["name"] = name
                changed = True
            break
    if changed:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            _sync_cloud_push()
        except Exception:
            pass


def clear_stock_history():
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        _sync_cloud_push(allow_empty_history=True)
    except Exception:
        pass
    return []


def remove_stocks_from_history(target_codes: list) -> list:
    history = load_stock_history()
    target_set = set(str(c).strip().upper() for c in target_codes)
    new_history = [h for h in history if str(h.get("code")).strip().upper() not in target_set]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_history, f, ensure_ascii=False, indent=2)
        _sync_cloud_push(allow_empty_history=True)
    except Exception:
        pass
    return new_history


def clear_recent_margin_data(pure_code: str, weeks: int = 2) -> str:
    """清除指定週數內之資券紀錄，供重新爬取覆蓋"""
    pure_code = str(pure_code).strip().upper()
    db_name = f"data_{pure_code}.db"
    db_path = os.path.join(STORAGE_DIR, db_name)
    sync_db_pull(pure_code)
    if not os.path.exists(db_path):
        return f"查無代號 {pure_code} 之本地資料庫。"
    cutoff_date = (datetime.now() - timedelta(days=weeks * 7)).strftime('%Y-%m-%d')
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM margin_short WHERE date >= ?", (cutoff_date,))
            conn.commit()
        sync_db_push(pure_code)
        return f"已成功清除 {pure_code} 自 {cutoff_date} 起之資券紀錄。"
    except Exception as e:
        return f"清除資券紀錄失敗: {e}"


def clear_recent_institutional_data(pure_code: str, weeks: int = 6) -> str:
    pure_code = str(pure_code).strip().upper()
    db_name = f"data_{pure_code}.db"
    db_path = os.path.join(STORAGE_DIR, db_name)
    sync_db_pull(pure_code)
    if not os.path.exists(db_path):
        return f"查無代號 {pure_code} 之本地資料庫。"
    cutoff_date = (datetime.now() - timedelta(days=weeks * 7)).strftime('%Y-%m-%d')
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM institutional_investors WHERE date >= ?", (cutoff_date,))
            conn.commit()
        sync_db_push(pure_code)
        return f"已成功清除 {pure_code} 自 {cutoff_date} 起之法人紀錄。"
    except Exception as e:
        return f"清除法人紀錄失敗: {e}"


class StockChipStorage:
    def __init__(self, pure_code: str):
        self.pure_code = str(pure_code).strip().upper()
        self.is_index = self.pure_code.startswith("^")
        self.db_name = f"data_{self.pure_code}.db"
        self.db_path = os.path.join(STORAGE_DIR, self.db_name)
        sync_db_pull(self.pure_code)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_k (
                    date TEXT PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                )
            """)
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_range_rank (
                    base_date TEXT PRIMARY KEY,
                    rank_json TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_daily_trades (
                    broker_name TEXT,
                    date TEXT,
                    buy_vol INTEGER,
                    sell_vol INTEGER,
                    net_vol INTEGER,
                    PRIMARY KEY (broker_name, date)
                )
            """)
            conn.commit()

    def get_latest_daily_k_date(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            if self.is_index:
                cur.execute("SELECT MAX(date) FROM daily_k WHERE open IS NOT NULL")
            else:
                cur.execute("SELECT MAX(date) FROM daily_k WHERE volume > 0")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

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

    def get_latest_holding_date(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM shareholding_distribution")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def save_daily_k_df(self, df: pd.DataFrame):
        if df is None or df.empty:
            return
        records = []
        for d, row in df.iterrows():
            d_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
            vol_val = float(row['Volume']) if not pd.isna(row['Volume']) else 0.0
            if not self.is_index and vol_val <= 0:
                continue
            if pd.isna(row['Open']) or pd.isna(row['Close']):
                continue
            records.append((
                d_str,
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                vol_val
            ))
        if records:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.executemany("""
                    INSERT OR REPLACE INTO daily_k (date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, records)
                conn.commit()
            sync_db_push(self.pure_code)

    def load_daily_k_df(self) -> pd.DataFrame:
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        with sqlite3.connect(self.db_path) as conn:
            if self.is_index:
                df = pd.read_sql_query(
                    "SELECT date, open, high, low, close, volume FROM daily_k WHERE open IS NOT NULL ORDER BY date ASC",
                    conn
                )
            else:
                df = pd.read_sql_query(
                    "SELECT date, open, high, low, close, volume FROM daily_k WHERE volume > 0 ORDER BY date ASC",
                    conn
                )
        if df.empty:
            return pd.DataFrame()
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.index.name = 'Date'
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)
        return df

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
        sync_db_push(self.pure_code)

    def load_institutional_df(self) -> pd.DataFrame:
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT date, foreign_net, trust_net, dealer_net FROM institutional_investors ORDER BY date ASC",
                conn
            )
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
        return df

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
        sync_db_push(self.pure_code)

    def load_margin_df(self) -> pd.DataFrame:
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT date, margin_diff, short_diff, margin_bal, short_bal FROM margin_short ORDER BY date ASC",
                conn
            )
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
        return df

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
        sync_db_push(self.pure_code)

    def load_holding_df(self) -> pd.DataFrame:
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT date, level, percent FROM shareholding_distribution ORDER BY date ASC",
                conn
            )
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
        return df

    def save_broker_range_rank(self, base_date: str, rank_bundle: dict, sync_cloud: bool = True):
        if not base_date or not isinstance(rank_bundle, dict):
            return
        now_str = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        payload_str = json.dumps(rank_bundle, ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO broker_range_rank (base_date, rank_json, updated_at)
                VALUES (?, ?, ?)
            """, (str(base_date)[:10], payload_str, now_str))
            conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_broker_range_rank(self, base_date: str):
        if not base_date or not os.path.exists(self.db_path):
            return None
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT rank_json FROM broker_range_rank WHERE base_date = ?",
                (str(base_date)[:10],)
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        try:
            parsed = json.loads(row[0])
            if isinstance(parsed, dict) and all(k in parsed for k in ("w1", "w10", "w20", "w60")):
                return parsed
        except Exception:
            pass
        return None

    def save_broker_daily_trades(self, broker_name: str, df_daily: pd.DataFrame, sync_cloud: bool = True):
        b_name = str(broker_name or "").strip()
        if not b_name or df_daily is None or df_daily.empty:
            return
        records = []
        for _, r in df_daily.iterrows():
            d_str = str(r.get("日期", "")).strip()[:10]
            if not d_str:
                continue
            buy_v = int(r.get("買進(張)", 0) or 0)
            sell_v = int(r.get("賣出(張)", 0) or 0)
            net_v = int(r.get("買賣超(張)", buy_v - sell_v) or 0)
            records.append((b_name, d_str, buy_v, sell_v, net_v))
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO broker_daily_trades (broker_name, date, buy_vol, sell_vol, net_vol)
                VALUES (?, ?, ?, ?, ?)
            """, records)
            conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_broker_daily_series(self, broker_name: str, start_date: str, end_date: str) -> pd.DataFrame:
        b_name = str(broker_name or "").strip()
        if not b_name or not os.path.exists(self.db_path):
            return pd.DataFrame()
        s_iso = str(start_date)[:10]
        e_iso = str(end_date)[:10]
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("""
                SELECT date AS "日期", buy_vol AS "買進(張)", sell_vol AS "賣出(張)", net_vol AS "買賣超(張)"
                FROM broker_daily_trades
                WHERE broker_name = ? AND date >= ? AND date <= ?
                ORDER BY date ASC
            """, conn, params=(b_name, s_iso, e_iso))
        return df
# EOF storage.py
