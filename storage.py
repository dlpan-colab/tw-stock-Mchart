"""
storage.py - 本地 SQLite 資料庫與股票歷史紀錄管理器
(支援含英文後綴台股ETF與雲端分點增量累積與批次清除分點與大盤融資金額欄位向後相容與多日歷史分點統計全載入版)
版本: 202611210850
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
MODULE_VERSION = "202611210850"

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
    "^DJI": "道瓊指數", "^IXIC": "那斯達克", "^SOX": "費城半導體", "^GSPC": "標普500",
    "^N225": "日經225", "^KS11": "韓國綜合",
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
                q=q, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc", pageSize=50
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


def clear_all_broker_data() -> str:
    """
    【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
    修改目的：一次性清除本地及雲端 Google Drive 資料夾內所有個股資料庫（data_*.db）之分點區間統計（broker_range_rank）與分點逐日明細（broker_daily_trades）資料表，並同步回寫雲端。
    防呆防錯原因：僅刪除分點資料表並執行 VACUUM 釋放空間，完整保留 daily_k（日線）、institutional_investors（三大法人）、margin_short（資券）與 shareholding_distribution（集保大戶）資料；同步雲端前先 pull 避免覆蓋雲端既有歷史資料。
    """
    codes_set = set()
    for p in glob.glob(os.path.join(STORAGE_DIR, "data_*.db")):
        base = os.path.basename(p)
        pure = base.replace("data_", "").replace(".db", "").strip().upper()
        if pure and not pure.startswith("^"):
            codes_set.add(pure)

    try:
        from cloud_sync import GoogleDriveSync
        sync_client = GoogleDriveSync()
        if sync_client.service and sync_client.folder_id:
            q = f"'{sync_client.folder_id}' in parents and name contains 'data_' and name contains '.db' and trashed = false"
            res = sync_client.service.files().list(
                q=q, fields="files(id, name)", pageSize=200
            ).execute()
            for f in res.get("files", []):
                fname = f.get("name", "")
                pure = fname.replace("data_", "").replace(".db", "").strip().upper()
                if pure and not pure.startswith("^"):
                    codes_set.add(pure)
    except Exception as e:
        print(f"[Storage] 雲端分點資料庫列表掃描警告: {e}")

    if not codes_set:
        return "目前無任何已收集之個股資料庫。"

    cleared_count = 0
    for pure_code in sorted(codes_set):
        db_path = os.path.join(STORAGE_DIR, f"data_{pure_code}.db")
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            _do_sync_db_pull(pure_code)
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM broker_range_rank")
                cur.execute("DELETE FROM broker_daily_trades")
                conn.commit()
            _do_sync_db_push(pure_code)
            cleared_count += 1
        except Exception as e:
            print(f"[Storage] 清除 {pure_code} 分點資料失敗: {e}")

    return f"已成功清除 {cleared_count} 檔個股之分點統計與分點日況明細（日線、法人、資券與集保大戶資料完整保留）。"


class StockChipStorage:
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
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
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
        if not records:
            return
        valid_records = [r for r in records if 1 <= int(r[1]) <= 15]
        if not valid_records:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR REPLACE INTO shareholding_distribution (date, level, holders, shares, percent)
                VALUES (?, ?, ?, ?, ?)
            ''', valid_records)
            conn.commit()
        sync_db_push(self.pure_code)

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

    # =====================================================================
    # 雲端分點資料增量累積與讀取 API
    # =====================================================================
    def save_broker_daily_trades(self, broker_name: str, df_trades: pd.DataFrame, sync_cloud: bool = True):
        """增量寫入單一券商分點逐日買賣超張數明細"""
        b_name = str(broker_name or "").strip()
        if not b_name or df_trades is None or df_trades.empty:
            return
        records = []
        for _, r in df_trades.iterrows():
            d_str = str(r.get("日期", "")).strip()[:10]
            if not d_str:
                continue
            b_val = int(r.get("買進(張)", 0) or 0)
            s_val = int(r.get("賣出(張)", 0) or 0)
            n_val = int(r.get("買賣超(張)", b_val - s_val) or 0)
            records.append((b_name, d_str, b_val, s_val, n_val))
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR REPLACE INTO broker_daily_trades
                (broker_name, trade_date, buy_sheets, sell_sheets, net_sheets)
                VALUES (?, ?, ?, ?, ?)
            ''', records)
            conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_broker_daily_series(self, broker_name: str, start_date: str, end_date: str) -> pd.DataFrame:
        """從本地/雲端資料庫讀取指定分點於起訖日期區間內之逐日買賣超序列"""
        b_name = str(broker_name or "").strip()
        if not b_name:
            return pd.DataFrame(columns=["日期", "買進(張)", "賣出(張)", "買賣超(張)"])
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query('''
                SELECT trade_date AS 日期, buy_sheets AS "買進(張)", sell_sheets AS "賣出(張)", net_sheets AS "買賣超(張)"
                FROM broker_daily_trades
                WHERE broker_name = ? AND trade_date >= ? AND trade_date <= ?
                ORDER BY trade_date ASC
            ''', conn, params=(b_name, start_date, end_date))
        return df

    def save_broker_range_rank(self, range_date: str, bundle_dict: dict, sync_cloud: bool = True):
        """儲存指定基準日之 1/10/20/60 日買賣超前 10 名統計快照"""
        r_date = str(range_date or "").strip()[:10]
        if not r_date or not isinstance(bundle_dict, dict):
            return
        records = []
        for win_days in (1, 10, 20, 60):
            w_obj = bundle_dict.get(f"w{win_days}")
            if not isinstance(w_obj, dict):
                continue
            r_label = str(w_obj.get("range_label", ""))
            for side in ("buy", "sell"):
                rows = w_obj.get(side, [])
                for idx, item in enumerate(rows[:10], start=1):
                    records.append((
                        r_date,
                        int(win_days),
                        side,
                        int(idx),
                        str(item.get("name", "")),
                        str(item.get("sys", "")),
                        int(item.get("buy", 0)),
                        int(item.get("sell", 0)),
                        int(item.get("net", 0)),
                        str(item.get("ratio", "-")),
                        r_label
                    ))
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM broker_range_rank WHERE range_date = ?", (r_date,))
            conn.executemany('''
                INSERT OR REPLACE INTO broker_range_rank
                (range_date, win_days, side, rank, broker_name, broker_sys, buy_sheets, sell_sheets, net_sheets, ratio_str, range_label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', records)
            conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_broker_range_rank(self, range_date: str) -> dict:
        """讀取指定基準日之分點區間統計快照，若無資料回傳 None"""
        r_date = str(range_date or "").strip()[:10]
        if not r_date:
            return None
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute('''
                SELECT win_days, side, rank, broker_name, broker_sys, buy_sheets, sell_sheets, net_sheets, ratio_str, range_label
                FROM broker_range_rank
                WHERE range_date = ?
                ORDER BY win_days ASC, side ASC, rank ASC
            ''', (r_date,)).fetchall()
        if not rows:
            return None
        result = {}
        for win_days, side, rank, b_name, b_sys, b_sh, s_sh, n_sh, r_str, r_lbl in rows:
            w_key = f"w{int(win_days)}"
            if w_key not in result:
                result[w_key] = {"range_label": r_lbl or "", "buy": [], "sell": []}
            if r_lbl and not result[w_key]["range_label"]:
                result[w_key]["range_label"] = r_lbl
            result[w_key][side].append({
                "name": b_name,
                "sys": b_sys,
                "buy": int(b_sh or 0),
                "sell": int(s_sh or 0),
                "net": int(n_sh or 0),
                "ratio": r_str or "-"
            })
        return result

    def load_all_broker_range_ranks(self) -> dict:
        """
        【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
        修改目的：一次性讀取本地已下載 SQLite 資料庫（broker_range_rank）中所有已累積之歷史基準日分點統計快照，
        回傳 {range_date: bundle_dict}，供主圖十字線切換至前一日（如 11/19）時即時呈現，避免隔日基準日推進後看不到前一日紀錄。
        防呆防錯原因：僅查詢本地已存在之 data_{code}.db（耗時 < 3ms，零額外雲端或網站網路請求），不影響既有單日查詢介面。
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute('''
                SELECT range_date, win_days, side, rank, broker_name, broker_sys, buy_sheets, sell_sheets, net_sheets, ratio_str, range_label
                FROM broker_range_rank
                ORDER BY range_date ASC, win_days ASC, side ASC, rank ASC
            ''').fetchall()
        if not rows:
            return {}
        by_date = {}
        for r_date, win_days, side, rank, b_name, b_sys, b_sh, s_sh, n_sh, r_str, r_lbl in rows:
            d_key = str(r_date or "").strip()[:10]
            if not d_key:
                continue
            if d_key not in by_date:
                by_date[d_key] = {}
            w_key = f"w{int(win_days)}"
            if w_key not in by_date[d_key]:
                by_date[d_key][w_key] = {"range_label": r_lbl or "", "buy": [], "sell": []}
            if r_lbl and not by_date[d_key][w_key]["range_label"]:
                by_date[d_key][w_key]["range_label"] = r_lbl
            by_date[d_key][w_key][side].append({
                "name": b_name,
                "sys": b_sys,
                "buy": int(b_sh or 0),
                "sell": int(s_sh or 0),
                "net": int(n_sh or 0),
                "ratio": r_str or "-"
            })
        return by_date
# EOF storage.py
