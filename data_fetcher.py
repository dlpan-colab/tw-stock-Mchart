"""
台股技術與籌碼分析系統 - 資料擷取模組
支援上市 (TWSE) 與上櫃 (TPEx) 市場精準分流，杜絕 Yahoo 重試延遲。
FinMind 與外部 API 連線逾時全數壓制至 3 秒內。
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610292340"

import io
import re
import ssl
import json
import time
import urllib3
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any, List

import requests
import pandas as pd
import yfinance as yf

from storage import StockChipStorage, load_stock_names_cache, save_stock_names_cache, is_valid_tw_stock_name

logger = logging.getLogger(__name__)

# 關閉不安全連線警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 上櫃代碼特徵前綴或特殊名單判定
TPEX_PREFIXES = ("4", "5", "6", "8")  # 櫃買中心主要代碼分佈


def detect_tw_market(pure_code: str) -> str:
    """
    根據台股代碼規則快速判定市場，避免 Yahoo Finance 盲目撞牆：
    回傳: '.TWO' (上櫃) 或 '.TW' (上市)
    """
    code = pure_code.strip().upper()
    
    # 常用特別名單或明確規則
    # 櫃買主流：4xxx, 5xxx, 8xxx 全數為上櫃；6xxx 大部分為上櫃（少數如 6770、6505 等上市）
    if code.startswith(("4", "5", "8")):
        return ".TWO"
    
    # 6 字頭常見上市名單
    twse_6_list = {
        "6116", "6153", "6168", "6191", "6205", "6213", "6257", "6285", 
        "6409", "6415", "6442", "6456", "6505", "6526", "6669", "6719", 
        "6770", "6781", "6805"
    }
    if code.startswith("6"):
        return ".TW" if code in twse_6_list else ".TWO"
        
    return ".TW"

#############################################################################
def create_fast_session() -> requests.Session:
    """建立自訂 session，加入 User-Agent 偽裝避免 Yahoo 阻擋"""
    s = requests.Session()
    s.verify = False
    # 必須加入 User-Agent，否則 Yahoo 容易直接回傳空值
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    adapter = requests.adapters.HTTPAdapter(max_retries=1) # 給予 1 次重試彈性
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


def fetch_stock_daily_k(
    pure_code: str,
    period: str = "1y",
    base_date: Optional[str] = None
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    抓取台股日 K 線，精準鎖定市場後綴，杜絕卡頓
    """
    code = str(pure_code).strip().upper()
    primary_suffix = detect_tw_market(code)
    secondary_suffix = ".TW" if primary_suffix == ".TWO" else ".TWO"

    session = create_fast_session()
    df = pd.DataFrame()
    success_symbol = ""

    # 先試最佳猜測市場
    symbols_to_try = [f"{code}{primary_suffix}", f"{code}{secondary_suffix}"]
    for sym in symbols_to_try:
        try:
            ticker = yf.Ticker(sym, session=session)
            # K線為主圖核心，把逾時稍微放寬至 8 秒確保能抓到
            fetched = ticker.history(period=period, auto_adjust=False, timeout=8)
            if fetched is not None and not fetched.empty:
                df = fetched
                success_symbol = sym
                break
        except Exception:
            continue

    if df.empty:
        return None, ""

    # 統一整理欄位
    df = df.reset_index()
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
    df.rename(columns={
        'Date': 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    }, inplace=True)

    df['date'] = pd.to_datetime(df['date']).dt.normalize()
    df.sort_values('date', inplace=True)
    df.set_index('date', inplace=True)

    # 基準日截斷（復盤模式）
    if base_date:
        b_dt = pd.to_datetime(base_date).normalize()
        df = df[df['date'] <= b_dt].copy()

    return df, success_symbol
#################################################################################

def fetch_stock_name(pure_code: str) -> str:
    """
    抓取台股中文名稱，附帶快取機制
    """
    code = str(pure_code).strip().upper()
    cache = load_stock_names_cache()
    if code in cache and is_valid_tw_stock_name(cache[code]):
        return cache[code]

    # 向 TWSE / TPEx Open API 取得精簡名稱
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw|otc_{code}.two"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            items = data.get("msgArray", [])
            if items:
                n = items[0].get("n", "")
                if is_valid_tw_stock_name(n):
                    cache[code] = n
                    save_stock_names_cache(cache)
                    return n
    except Exception:
        pass

    return code


def sync_chip_data(pure_code: str, storage: StockChipStorage):
    """
    同步籌碼資料（三大法人、融資券、集保）：
    連線逾時全部壓制在 3 秒內，遇阻塞直接 pass，保證出圖
    """
    code = str(pure_code).strip().upper()
    today_str = datetime.today().strftime('%Y-%m-%d')
    start_date = (datetime.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. FinMind 三大法人 (timeout=3)
    try:
        url_inst = "https://api.finmindtrade.com/api/v4/data"
        p_inst = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": code,
            "start_date": start_date
        }
        res = requests.get(url_inst, params=p_inst, headers=headers, timeout=3)
        if res.status_code == 200:
            raw = res.json().get("data", [])
            if raw:
                df = pd.DataFrame(raw)
                if not df.empty and 'name' in df.columns and 'buy' in df.columns:
                    piv = df.pivot_table(index='date', columns='name', values='buy', fill_value=0) - \
                          df.pivot_table(index='date', columns='name', values='sell', fill_value=0)
                    records = []
                    for d_val, row in piv.iterrows():
                        f_net = (row.get('Foreign_Investor', 0) + row.get('Foreign_Dealer_Self', 0)) / 1000.0
                        t_net = row.get('Investment_Trust', 0) / 1000.0
                        d_net = (row.get('Dealer_Self', 0) + row.get('Dealer_Hedging', 0)) / 1000.0
                        records.append((str(d_val), float(f_net), float(t_net), float(d_net)))
                    if records:
                        storage.save_institutional_data(records)
    except Exception:
        pass

    # 2. FinMind 資券餘額 (timeout=3)
    try:
        url_ms = "https://api.finmindtrade.com/api/v4/data"
        p_ms = {
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": code,
            "start_date": start_date
        }
        res = requests.get(url_ms, params=p_ms, headers=headers, timeout=3)
        if res.status_code == 200:
            raw = res.json().get("data", [])
            if raw:
                df = pd.DataFrame(raw)
                if not df.empty and 'MarginPurchaseTodayBalance' in df.columns:
                    df.sort_values('date', inplace=True)
                    df['m_diff'] = df['MarginPurchaseTodayBalance'].diff().fillna(0)
                    df['s_diff'] = df['ShortSaleTodayBalance'].diff().fillna(0)
                    records = []
                    for _, row in df.iterrows():
                        records.append((
                            str(row['date']),
                            float(row['m_diff']),
                            float(row['s_diff']),
                            float(row['MarginPurchaseTodayBalance']),
                            float(row['ShortSaleTodayBalance'])
                        ))
                    if records:
                        storage.save_margin_data(records)
    except Exception:
        pass

    # 3. 集保大戶資料 (TDCC 逾時 3 秒，遇防火牆立刻中斷)
    try:
        url_tdcc = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
        res = requests.post(url_tdcc, headers=headers, timeout=3)
        if res.status_code == 200:
            # 如有最新資料則解析寫入
            pass
    except Exception:
        pass

def fetch_chip_data_online(*args, **kwargs):
    """相容 app.py 既有匯入介面"""
    return sync_chip_data(*args, **kwargs)

def fetch_stock_data(raw_ticker: str, period: str = "1y", base_date=None) -> Tuple[Optional[pd.DataFrame], str, str, str, str, Optional[int]]:
    """
    相容 chart_builder.py 的舊版呼叫介面。
    整合抓取 K 線、名稱與同步籌碼。
    回傳: (df, full_symbol, pure_code, market_suffix, c_name, shares_outstanding)
    """
    code = str(raw_ticker).strip().upper()
    df, success_symbol = fetch_stock_daily_k(code, period, base_date)
    
    if df is None or df.empty:
        return None, "", code, "", "", None
        
    c_name = fetch_stock_name(code)
    market = ".TWO" if success_symbol.endswith(".TWO") else ".TW"
    
    # 建立本機資料庫連線並同步籌碼
    storage = StockChipStorage(code)
    sync_chip_data(code, storage)
    
    # 這裡的發行股數(shares_outstanding)舊版預設傳回 None，由指標模組自行處裡
    return df, success_symbol, code, market, c_name, None
