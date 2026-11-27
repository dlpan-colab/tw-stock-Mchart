"""
strg_cloud_names.py - 雲端雙向同步、代號格式辨識與中文股名快取模組
(自 storage.py 依邏輯職責拆分，維持既有雲端同步與四層中文股名備援查詢機制)
版本: 202611270810
"""

import os
import re
import json
import time
import threading
import requests
from bs4 import BeautifulSoup

MODULE_NAME = "strg_cloud_names"
MODULE_VERSION = "202611270810"

STORAGE_DIR = "."
HISTORY_FILE = os.path.join(STORAGE_DIR, "stock_history.json")
NAMES_CACHE_FILE = os.path.join(STORAGE_DIR, "tw_stock_names.json")

# 【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
# 記錄「雲端確認已有檔案（或查詢逾時無法確認不存在），但 3 次退避重試皆下載失敗」之股票代號集合。
# 凡在 _CLOUD_PULL_FAILED_CODES 內之標的，嚴禁執行 sync_db_push 反向覆蓋雲端既有完整資料庫。
_CLOUD_PULL_FAILED_CODES = set()


def is_cloud_db_pull_failed(pure_code: str) -> bool:
    """查詢指定股票代號是否處於雲端下載失敗防覆蓋保護狀態"""
    c = str(pure_code or "").strip().upper()
    return c in _CLOUD_PULL_FAILED_CODES


def is_tw_stock_or_etf(code: str) -> bool:
    """【修訂說明 2026-11-14】識別台股個股與含英文後綴之ETF（如 00632R、00664R、00679B、00631L）"""
    c = str(code or "").strip().upper()
    if not c or c.startswith("^"):
        return False
    return bool(re.match(r"^\d{4,6}[A-Z]{0,2}$", c))


def is_tw_index_with_gov_brokers(code: str) -> bool:
    """【修訂說明 2026-11-23】識別具備八大官股買賣超統計與日況之台股大盤指數（^TWII / ^TWOII）"""
    c = str(code or "").strip().upper()
    return c in ("^TWII", "^TWOII")


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


def _do_sync_db_pull(pure_code: str, status_callback=None) -> bool:
    """
    【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
    1. 修改目的：呼叫 `cloud_sync.pull_file_detailed` 執行 3 次退避重試並回傳重試進度提示；
       若雲端確認已有該檔（或無法確認不存在）卻 3 次重試皆失敗，立即將 `pure_code` 加入 `_CLOUD_PULL_FAILED_CODES`。
    2. 防呆防錯原因：一旦下載成功（或確認雲端確實尚無該檔），才允許解除該檔之防覆蓋保護旗標。
    """
    code_u = str(pure_code or "").strip().upper()
    try:
        from cloud_sync import pull_file_detailed
        db_name = f"data_{code_u}.db"
        local_path = os.path.join(STORAGE_DIR, db_name)
        ok, remote_exists_or_unknown = pull_file_detailed(
            db_name,
            local_path,
            max_retries=3,
            status_callback=status_callback
        )
        if ok:
            _CLOUD_PULL_FAILED_CODES.discard(code_u)
            return True
        if remote_exists_or_unknown:
            _CLOUD_PULL_FAILED_CODES.add(code_u)
            print(f"[CloudSync] DB pull failed after retries for {code_u}; anti-overwrite protection enabled.")
            return False
        # 雲端確實尚無此資料庫（首次建立新個股）
        _CLOUD_PULL_FAILED_CODES.discard(code_u)
        return True
    except Exception as e:
        _CLOUD_PULL_FAILED_CODES.add(code_u)
        print(f"[CloudSync] DB pull warning for {code_u}: {e}")
        return False


def sync_db_pull(pure_code: str, status_callback=None) -> bool:
    code_u = str(pure_code or "").strip().upper()
    db_name = f"data_{code_u}.db"
    local_path = os.path.join(STORAGE_DIR, db_name)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        _CLOUD_PULL_FAILED_CODES.discard(code_u)
        return True
    return _do_sync_db_pull(code_u, status_callback=status_callback)


def _do_sync_db_push(pure_code: str):
    code_u = str(pure_code or "").strip().upper()
    if code_u in _CLOUD_PULL_FAILED_CODES:
        print(f"[CloudSync] Blocked push for {code_u} to protect existing cloud DB from partial/empty overwrite.")
        return
    try:
        from cloud_sync import push_file
        db_name = f"data_{code_u}.db"
        local_path = os.path.join(STORAGE_DIR, db_name)
        if os.path.exists(local_path):
            push_file(local_path, db_name)
    except Exception as e:
        print(f"[CloudSync] DB push warning for {code_u}: {e}")


def sync_db_push(pure_code: str):
    code_u = str(pure_code or "").strip().upper()
    if code_u in _CLOUD_PULL_FAILED_CODES:
        return
    _async_run(_do_sync_db_push, code_u)


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
## EOF strg_cloud_names.py
