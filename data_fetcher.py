"""
台股技術與籌碼分析系統 - 資料擷取模組
支援上市 (TWSE) 與上櫃 (TPEx) 市場精準分流，完整整合日 K 線、換手率、法人、資券與集保大戶持股
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610300600"

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
    """根據台股代碼規則快速判定市場：回傳 '.TWO' (上櫃) 或 '.TW' (上市)"""
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
    code = str(pure_code).strip().upper()
    primary_suffix = detect_tw_market(code)
    secondary_suffix = ".TW" if primary_suffix == ".TWO" else ".TWO"

    session = create_fast_session()
    df = pd.DataFrame()
    success_symbol = ""
    ticker_obj = None

    symbols_to_try = [f"{code}{primary_suffix}", f"{code}{secondary_suffix}"]
    for sym in symbols_to_try:
        try:
            ticker = yf.Ticker(sym, session=session)
            fetched = ticker.history(period=period, auto_adjust=False, timeout=8)
            if fetched is not None and not fetched.empty:
                df = fetched
                success_symbol = sym
                ticker_obj = ticker
                break
        except Exception:
            continue

    if df.empty:
        return None, ""

    shares_count = None
    try:
        if ticker_obj and hasattr(ticker_obj, 'info'):
            shares_count = ticker_obj.info.get('sharesOutstanding', None)
    except Exception:
        pass

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

    if 'Adj Close' in df.columns:
        df['Close'] = df['Close'].fillna(df['Adj Close'])
    df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].ffill()
    df = df[df['Volume'] > 0].copy()

    df['Volume_Sheets'] = df['Volume'] / 1000.0

    storage = StockChipStorage(code)
    holding_df = storage.load_holding_df()
    
    latest_major_pct = 0.0
    if not holding_df.empty:
        max_level = holding_df['level'].max()
        target_level = 17 if 17 in holding_df['level'].values else max_level
        sub_holding = holding_df[holding_df['level'] == target_level]
        if not sub_holding.empty:
            latest_major_pct = float(sub_holding.iloc[-1]['percent'])

    if shares_count and shares_count > 0:
        free_float_shares = shares_count * (1.0 - (latest_major_pct / 100.0))
        if free_float_shares > 0:
            df['Turnover_Rate'] = (df['Volume'] / free_float_shares) * 100.0
        else:
            df['Turnover_Rate'] = (df['Volume'] / shares_count) * 100.0
    else:
        avg_vol = df['Volume'].rolling(60, min_periods=1).mean()
        df['Turnover_Rate'] = (df['Volume'] / avg_vol) * 10.0

    df['date'] = pd.to_datetime(df['date']).dt.normalize()
    df.sort_values('date', inplace=True)
    df.set_index('date', inplace=True)

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
    
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw|otc_{code}.tw"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            for item in data.get("msgArray", []):
                n = item.get("n", "")
                if is_valid_tw_stock_name(n):
                    cache[code] = n
                    save_stock_names_cache(cache)
                    return n
    except Exception:
        pass

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
    start_date = (datetime.today() - timedelta(days=90)).strftime('%Y-%m-%d')
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. FinMind 三大法人資料
    try:
        url_inst = "https://api.finmindtrade.com/api/v4/data"
        res = requests.get(url_inst, params={
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": code,
            "start_date": start_date
        }, headers=headers, timeout=4)
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
    except Exception as e:
        logger.warning(f"同步三大法人失敗: {e}")

    # 2. FinMind 資券餘額資料
    try:
        url_ms = "https://api.finmindtrade.com/api/v4/data"
        res = requests.get(url_ms, params={
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": code,
            "start_date": start_date
        }, headers=headers, timeout=4)
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
    except Exception as e:
        logger.warning(f"同步資券餘額失敗: {e}")

    # 3. 集保大戶持股資料 (TDCC OpenData ID: 1-5)
    try:
        url_tdcc = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
        res = requests.get(url_tdcc, headers=headers, timeout=5)
        if res.status_code == 200 and res.text:
            tdcc_df = pd.read_csv(io.StringIO(res.text))
            if not tdcc_df.empty:
                col_code = next((c for c in tdcc_df.columns if '代號' in c or 'Stock' in c), tdcc_df.columns[1])
                col_date = next((c for c in tdcc_df.columns if '日期' in c or 'Date' in c), tdcc_df.columns[0])
                col_level = next((c for c in tdcc_df.columns if '級距' in c or 'Level' in c), tdcc_df.columns[2])
                col_pct = next((c for c in tdcc_df.columns if '比例' in c or 'Percent' in c), tdcc_df.columns[-1])

                sub = tdcc_df[tdcc_df[col_code].astype(str).str.strip().str.upper() == code].copy()
                if not sub.empty:
                    holding_records = []
                    for _, row in sub.iterrows():
                        try:
                            d_str = str(row[col_date]).strip()
                            if len(d_str) == 8:
                                d_str = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"
                            lvl = int(row[col_level])
                            pct = float(row[col_pct])
                            holding_records.append((d_str, lvl, pct))
                        except Exception:
                            continue
                    if holding_records:
                        storage.save_holding_data(holding_records)
    except Exception as e:
        logger.warning(f"同步集保大戶資料失敗: {e}")


def fetch_chip_data_online(*args, **kwargs):
    return sync_chip_data(*args, **kwargs)


def fetch_stock_data(raw_ticker: str, period: str = "1y", base_date=None) -> Tuple[Optional[pd.DataFrame], str, str, str, str, Optional[int]]:
    code = str(raw_ticker).strip().upper()
    df, success_symbol = fetch_stock_daily_k(code, period, base_date)
    
    if df is None or df.empty:
        return None, "", code, "", "", None
        
    c_name = fetch_stock_name(code)
    market = ".TWO" if success_symbol.endswith(".TWO") else ".TW"
    
    storage = StockChipStorage(code)
    sync_chip_data(code, storage)
    
    return df, success_symbol, code, market, c_name, None
