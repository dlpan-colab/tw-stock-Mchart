"""
台股技術與籌碼分析系統 - 外部資料爬蟲與清洗模組
負責 yfinance 日 K 抓取、休市 0 成交量過濾、盤中補點防護、
TDCC 集保大戶分級增量爬蟲、FinMind 法人與資券同步、ISIN 股票中文名稱快取。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610280040"

import os
import re
import time
import json
import logging
import datetime
from io import StringIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup

from config import (
    COMMON_STOCKS,
    DEFAULT_LOOKBACK_DAYS,
    TDCC_INCREMENTAL_WEEKS_LIMIT,
)
from storage import (
    StockChipStorage,
    load_stock_names_cache,
    save_stock_names_cache,
)

# 靜音 yfinance 的日誌
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

FINMIND_TOKEN = ""

# ==========================================
# 1. 中文名稱解析與快取
# ==========================================
def get_tw_stock_name(stock_id: str) -> str:
    stock_id = str(stock_id).strip().upper()
    cache = load_stock_names_cache()

    if stock_id in cache:
        return cache[stock_id]
    if stock_id in COMMON_STOCKS:
        cache[stock_id] = COMMON_STOCKS[stock_id]
        save_stock_names_cache(cache)
        return cache[stock_id]

    try:
        url = f"https://isin.twse.com.tw/isin/single_main.jsp?owncode={stock_id}&stockname="
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.find_all('tr')
           
            for r in rows:
                cols = r.find_all('td')
                if len(cols) >= 3:
                    text_0 = cols[0].text.strip()
                    parts = text_0.replace('\u3000', ' ').split()
                    if len(parts) >= 2 and parts[0] == stock_id:
                        c_name = parts[1]
                        if c_name:
                            cache[stock_id] = c_name
                            save_stock_names_cache(cache)
                            return c_name
    except Exception:
        pass

    return stock_id

get_stock_chinese_name = get_tw_stock_name


# ==========================================
# 2. yfinance 資料抓取 (完整 6 個回傳值)
# ==========================================
def fetch_stock_data(symbol: str, period: str = "1y"):
    """
    抓取台股日 K 資料並過濾假 K 線與盤中補點
    回傳: (df, full_ticker, pure_code, market, c_name, shares_outstanding)
    """
    import yfinance as yf
    raw_str = str(symbol).strip().upper()
    match = re.search(r'\d+', raw_str)
    pure_code = match.group(0) if match else raw_str.split('.')[0]
    
    ticker_obj = None
    df = pd.DataFrame()
    shares_outstanding = None

    for suffix in ['.TW', '.TWO', '']:
        test_ticker = f"{pure_code}{suffix}" if suffix else pure_code
        try:
            t = yf.Ticker(test_ticker)
            d = t.history(period=period, auto_adjust=False)
            if not d.empty and len(d) >= 5:
                df = d
                ticker_obj = t
                try:
                    shares_outstanding = t.fast_info.shares
                except Exception:
                    shares_outstanding = None
                break
        except Exception:
            continue

    if df.empty or ticker_obj is None:
        return None, None, None, None, "", None

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()

    # 過濾休市日與 0 成交量假 K 線
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df = df[df['Volume'] > 0]

    c_name = get_tw_stock_name(pure_code)

    now_dt = datetime.datetime.now()
    target_dt = now_dt
    
    if now_dt.time() < datetime.time(9, 0):
        target_dt -= datetime.timedelta(days=1)
        
    while target_dt.weekday() > 4:
        target_dt -= datetime.timedelta(days=1)
        
    target_date = target_dt.date()
    latest_date = df.index[-1].date() if not df.empty else target_date

    # 盤中補點防護
    if latest_date < target_date:
        try:
            fast_info = ticker_obj.fast_info
            v_val = fast_info.last_volume
            if v_val is not None and not np.isnan(v_val) and v_val > 0:
                cur_price = fast_info.last_price
                if cur_price is not None and not np.isnan(cur_price) and cur_price > 0:
                    o_val = fast_info.open if fast_info.open and fast_info.open > 0 else cur_price
                    h_val = fast_info.day_high if fast_info.day_high and fast_info.day_high > 0 else cur_price
                    l_val = fast_info.day_low if fast_info.day_low and fast_info.day_low > 0 else cur_price

                    today_row = pd.DataFrame({
                        'Open': [float(o_val)],
                        'High': [float(h_val)],
                        'Low': [float(l_val)],
                        'Close': [float(cur_price)],
                        'Volume': [float(v_val)]
                    }, index=[pd.Timestamp(target_date)])
                    df = pd.concat([df, today_row])
        except Exception:
            pass

    market = "上市" if ".TW" in ticker_obj.ticker else ("上櫃" if ".TWO" in ticker_obj.ticker else "台股")
    return df, ticker_obj.ticker, pure_code, market, c_name, shares_outstanding

# 向下相容
def fetch_kline_data(stock_id: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
    df, _, _, _, _, shares = fetch_stock_data(stock_id, period="1y")
    if df is not None and not df.empty:
        return df.tail(lookback_days), (shares or 0.0)
    return pd.DataFrame(), 0.0


# ==========================================
# 3. 籌碼資料增量同步 (TDCC + FinMind)
# ==========================================
def sync_chip_data(pure_code: str, df_dates, status_placeholder=None):
    storage = StockChipStorage(pure_code)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Referer': 'https://www.tdcc.com.tw/portal/zh/smWeb/qryStock'
    }

    last_inst_date = storage.get_latest_inst_date()
    last_margin_date = storage.get_latest_margin_date()
    
    target_start_date = (df_dates[0] - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
    inst_query_start = (pd.to_datetime(last_inst_date) + datetime.timedelta(days=1)).strftime('%Y-%m-%d') if last_inst_date else target_start_date
    margin_query_start = (pd.to_datetime(last_margin_date) + datetime.timedelta(days=1)).strftime('%Y-%m-%d') if last_margin_date else target_start_date
    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')

    if storage.is_first_time and status_placeholder:
        status_placeholder.info(f"⚡ 首次檢視標的 {pure_code}：正在向資料庫初始化同步歷史籌碼...")

    # 1. FinMind 三大法人
    if not last_inst_date or inst_query_start <= latest_trade_date_str:
        try:
            url_inst = "https://api.finmindtrade.com/api/v4/data"
            p_inst = {
                "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id": pure_code,
                "start_date": inst_query_start,
                "token": FINMIND_TOKEN
            }
            res = requests.get(url_inst, params=p_inst, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json().get('data', [])
                if data:
                    idf = pd.DataFrame(data)
                    idf['net_sheets'] = (idf['buy'] - idf['sell']) / 1000.0
                    f_df = idf[idf['name'].str.contains('Foreign|外資|外陸資', na=False, case=False)]
                    t_df = idf[idf['name'].str.contains('Investment_Trust|投信', na=False, case=False)]
                    d_df = idf[idf['name'].str.contains('Dealer|自營', na=False, case=False)]
                    f_s = f_df.groupby('date')['net_sheets'].sum()
                    t_s = t_df.groupby('date')['net_sheets'].sum()
                    d_s = d_df.groupby('date')['net_sheets'].sum()
                    all_dates = sorted(list(set(idf['date'])))
                    records = []
                    for d in all_dates:
                        records.append((d, float(f_s.get(d, 0.0)), float(t_s.get(d, 0.0)), float(d_s.get(d, 0.0))))
                    storage.save_institutional_data(records)
        except Exception:
            pass

    # 2. FinMind 資券
    if not last_margin_date or margin_query_start <= latest_trade_date_str:
        try:
            url_ms = "https://api.finmindtrade.com/api/v4/data"
            p_ms = {
                "dataset": "TaiwanStockMarginPurchaseShortSale",
                "data_id": pure_code,
                "start_date": margin_query_start,
                "token": FINMIND_TOKEN
            }
            res_ms = requests.get(url_ms, params=p_ms, headers=headers, timeout=12)
            if res_ms.status_code == 200:
                data_ms = res_ms.json().get('data', [])
                if data_ms:
                    ms_df = pd.DataFrame(data_ms)
                    records_ms = []
                    for _, r in ms_df.iterrows():
                        mb = float(r.get('MarginPurchaseBuy', 0) or 0)
                        ms = float(r.get('MarginPurchaseSell', 0) or 0)
                        mr = float(r.get('MarginPurchaseCashRepayment', 0) or 0)
                        m_diff = (mb - ms - mr) / 1000.0
                        
                        sb = float(r.get('ShortSaleBuy', 0) or 0)
                        ss = float(r.get('ShortSaleSell', 0) or 0)
                        sr = float(r.get('ShortSaleCashRepayment', 0) or 0)
                        s_diff = (ss - sb - sr) / 1000.0

                        m_bal = float(r.get('MarginPurchaseTodayBalance', 0) or 0) / 1000.0
                        s_bal = float(r.get('ShortSaleTodayBalance', 0) or 0) / 1000.0
                        records_ms.append((r['date'], m_diff, s_diff, m_bal, s_bal))
                    storage.save_margin_data(records_ms)
        except Exception:
            pass

    # 3. TDCC 集保分級增量
    holding_df = storage.load_holding_df()
    existing_weeks = set(holding_df['date'].dt.strftime('%Y%m%d')) if not holding_df.empty else set()
    try:
        session_tdcc = requests.Session()
        url_home = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
        r_home = session_tdcc.get(url_home, headers=headers, timeout=12)
        if r_home.status_code == 200:
            soup_home = BeautifulSoup(r_home.text, 'html.parser')
            form = soup_home.find('form')
            action = form.get('action', '') if form else ''
            target_url = f"https://www.tdcc.com.tw{action}" if action.startswith('/') else (action if action.startswith('http') else f"https://www.tdcc.com.tw/portal/zh/smWeb/{action}")

            available_dates = [o.get('value').strip() for o in soup_home.find_all('option')
                               if o.get('value') and o.get('value').strip().isdigit() and len(o.get('value').strip()) == 8 and o.get('value').strip().startswith('20')]
            available_dates = sorted(list(set(available_dates)), reverse=True)
            missing_dates = [d for d in available_dates if d not in existing_weeks][:TDCC_INCREMENTAL_WEEKS_LIMIT]

            h_rec = []
            for d_str in missing_dates:
                try:
                    r_page = session_tdcc.get(url_home, headers=headers, timeout=10)
                    sp_page = BeautifulSoup(r_page.text, 'html.parser')
                    cur_form = sp_page.find('form')
                    payload = {inp.get('name'): inp.get('value', '') for inp in cur_form.find_all('input') if inp.get('name')}
                    payload.update({'scaDate': d_str, 'sqlMethod': 'StockNo', 'stockNo': pure_code, 'stockName': '', 'sub': '查詢'})
                    resp = session_tdcc.post(target_url, data=payload, headers=headers, timeout=10)
                    dfs = pd.read_html(StringIO(resp.text))

                    target_tbl = next((d for d in dfs if '1' in d.iloc[:, 0].astype(str).tolist() and '15' in d.iloc[:, 0].astype(str).tolist()), None)
                    if target_tbl is not None:
                        lvl_col, pct_col = target_tbl.columns[0], target_tbl.columns[-1]
                        sub = target_tbl[target_tbl[lvl_col].astype(str).isin([str(i) for i in range(1, 16)])].copy()
                        d_fmt = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"
                        for _, row in sub.iterrows():
                            try:
                                h_rec.append((d_fmt, int(row[lvl_col]), float(str(row[pct_col]).replace('%', '').replace(',', ''))))
                            except ValueError:
                                pass
                    time.sleep(0.2)
                except Exception:
                    continue
            if h_rec:
                storage.save_holding_data(h_rec)
    except Exception:
        pass

    return storage.load_institutional_df(), storage.load_margin_df(), storage.load_holding_df()
