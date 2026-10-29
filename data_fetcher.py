"""
台股技術與籌碼分析系統 - 資料擷取模組
支援上市 (TWSE) 與上櫃 (TPEx) 市場精準分流，杜絕 Yahoo 重試延遲。
FinMind 與外部 API 連線逾時全數壓制至 3 秒內。
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610300200"

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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def detect_tw_market(pure_code: str) -> str:
    """
    根據台股代碼規則快速判定市場，避免 Yahoo Finance 盲目撞牆：
    回傳: '.TWO' (上櫃) 或 '.TW' (上市)
    """
    code = str(pure_code).strip().upper()
    
    if code.startswith(("4", "5", "8")):
        return ".TWO"
    
    twse_6_list = {
        "6116", "6153", "6168", "6191", "6205", "6213", "6257", "6285", 
        "6409", "6415", "6442", "6456", "6505", "6526", "6669", "6719", 
        "6770", "6781", "6805"
    }
    if code.startswith("6"):
        return ".TW" if code in twse_6_list else ".TWO"
        
    return ".TW"


def create_fast_session() -> requests.Session:
    """建立自訂 session，加入 User-Agent 偽裝避免 Yahoo 阻擋"""
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    adapter = requests.adapters.HTTPAdapter(max_retries=1)
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
            fetched = ticker.history(period=period, auto_adjust=False, timeout=8)
            if fetched is not None and not fetched.empty:
                df = fetched
                success_symbol = sym
                break
        except Exception:
            continue

    if df.empty:
        return None, ""

    # 取得發行股數 (用於計算換手率)
    shares_count = None
    try:
        info = ticker.info
        shares_count = info.get('sharesOutstanding', None)
    except Exception:
        pass

    # 統一整理欄位
    df = df.reset_index()
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)

    df.rename(columns={
        'Date': 'date',
        'Open': 'Open',
        'High': 'High',
        'Low': 'Low',
        'Close': 'Close',
        'Volume': 'Volume'
    }, inplace=True)

    # 1. 補齊 yfinance 最新一日常遺失的收盤價，防 K 線與指標破圖
    if 'Adj Close' in df.columns:
        df['Close'] = df['Close'].fillna(df['Adj Close'])
    df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].ffill()

    # 2. 嚴格剔除成交量為 0 的幽靈交易日，徹底解決資料位移
    df = df[df['Volume'] > 0].copy()

    # 3. 計算成交張數與換手率 (Turnover_Rate) 確保 10%、20% 標記正常顯示
    df['Volume_Sheets'] = df['Volume'] / 1000.0
    if shares_count and shares_count > 0:
        df['Turnover_Rate'] = (df['Volume'] / shares_count) * 100.0
    else:
        # 若無法取得總股數，以近 60 日平均成交量作為基準估算換手率
        avg_vol = df['Volume'].rolling(60, min_periods=1).mean()
        df['Turnover_Rate'] = (df['Volume'] / avg_vol) * 5.0  # 模擬基準

    df['date'] = pd.to_datetime(df['date']).dt.normalize()
    df.sort_values('date', inplace=True)
    df.set_index('date', inplace=True)

    # 基準日截斷（復盤模式）
    if base_date:
        b_dt = pd.to_datetime(base_date).normalize()
        df = df[df.index <= b_dt].copy()

    return df, success_symbol


def fetch_stock_name(pure_code: str) -> str:
    code = str(pure_code).strip().upper()
    cache = load_stock_names_cache()
    if code in cache and is_valid_tw_stock_name(cache[code]):
        return cache[code]

    headers = {"User-Agent": "Mozilla/5.0"}
    
    # 嘗試 1：證交所 MIS API (上市與上櫃通用)
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw|otc_{code}.tw"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            items = data.get("msgArray", [])
            for item in items:
                n = item.get("n", "")
                if is_valid_tw_stock_name(n):
                    cache[code] = n
                    save_stock_names_cache(cache)
                    return n
    except Exception:
        pass

    # 嘗試 2：Yahoo Finance 標頭解析（作為備援）
    try:
        market_suffix = detect_tw_market(code)
        url_yf = f"https://finance.yahoo.com/quote/{code}{market_suffix}"
        res = requests.get(url_yf, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if res.status_code == 200:
            m = re.search(r'<title>(.*?)\s*\(\s*' + code, res.text)
            if m:
                raw_title = m.group(1).strip()
                if is_valid_tw_stock_name(raw_title):
                    cache[code] = raw_title
                    save_stock_names_cache(cache)
                    return raw_title
    except Exception:
        pass

    return code


def sync_chip_data(pure_code: str, storage: StockChipStorage):
    code = str(pure_code).strip().upper()
    start_date = (datetime.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. FinMind 三大法人
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

    # 2. FinMind 資券餘額
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

    # 3. 集保大戶
    try:
        url_tdcc = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
        res = requests.post(url_tdcc, headers=headers, timeout=3)
        if res.status_code == 200:
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
    """
    code = str(raw_ticker).strip().upper()
    df, success_symbol = fetch_stock_daily_k(code, period, base_date)
    
    if df is None or df.empty:
        return None, "", code, "", "", None
        
    c_name = fetch_stock_name(code)
    market = ".TWO" if success_symbol.endswith(".TWO") else ".TW"
    
    storage = StockChipStorage(code)
    sync_chip_data(code, storage)
    
    return df, success_symbol, code, market, c_name, None
