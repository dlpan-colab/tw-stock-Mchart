"""
data_fetcher.py - 外部資料抓取與增量同步模組
版本: 202610301630
"""

import os
import re
import io
import time
import json
import sqlite3
import requests
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from storage import StockChipStorage, get_stock_chinese_name

FINMIND_TOKEN = ""

def fetch_stock_name(pure_code: str) -> str:
    return get_stock_chinese_name(pure_code)

def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: str = None):
    import yfinance as yf
    raw_str = str(raw_ticker).strip().upper()
    match = re.search(r'\d+', raw_str)
    pure_code = match.group(0) if match else raw_str.split('.')[0]

    ticker_obj = None
    df = pd.DataFrame()

    for suffix in ['.TW', '.TWO', '']:
        test_ticker = f"{pure_code}{suffix}" if suffix else pure_code
        try:
            t = yf.Ticker(test_ticker)
            d = t.history(period=period, auto_adjust=False)
            if not d.empty and len(d) >= 5:
                df = d
                ticker_obj = t
                break
        except Exception:
            continue

    if df.empty or ticker_obj is None:
        return None, ""

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

    now_dt = datetime.now()
    target_dt = now_dt
    if now_dt.time() < datetime.strptime("09:00", "%H:%M").time():
        target_dt -= timedelta(days=1)
    while target_dt.weekday() > 4:
        target_dt -= timedelta(days=1)

    target_date = target_dt.date()
    latest_date = df.index[-1].date()

    if latest_date < target_date:
        try:
            fast_info = ticker_obj.fast_info
            cur_price = fast_info.last_price
            if cur_price is not None and not np.isnan(cur_price) and cur_price > 0:
                o_val = fast_info.open if fast_info.open and fast_info.open > 0 else cur_price
                h_val = fast_info.day_high if fast_info.day_high and fast_info.day_high > 0 else cur_price
                l_val = fast_info.day_low if fast_info.day_low and fast_info.day_low > 0 else cur_price
                v_val = fast_info.last_volume if fast_info.last_volume and fast_info.last_volume > 0 else 0

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

    return df, ticker_obj.ticker

def sync_chip_data(pure_code: str, df_dates, status_placeholder=None):
    """
    增量同步法人、資券與集保持股資料
    回傳值明確規範為: inst_df, margin_df, holding_df (共3個)
    """
    storage = StockChipStorage(pure_code)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://www.tdcc.com.tw/portal/zh/smWeb/qryStock'
    }

    last_inst_date = storage.get_latest_inst_date()
    last_margin_date = storage.get_latest_margin_date()

    target_start_date = (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d')
    inst_query_start = (pd.to_datetime(last_inst_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_inst_date else target_start_date
    margin_query_start = (pd.to_datetime(last_margin_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_margin_date else target_start_date
    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')

    # 1. 同步三大法人買賣超
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

    # 2. 同步資券增減
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

    # 3. 同步集保大戶持股 (主動抓足 15 週五歷史)
    holding_df = storage.load_holding_df()
    existing_weeks = set(holding_df['date'].dt.strftime('%Y%m%d')) if not holding_df.empty else set()
    
    today = datetime.today()
    days_ahead = 4 - today.weekday()
    if days_ahead > 0:
        days_ahead -= 7
    last_friday = today + timedelta(days=days_ahead)
    target_fridays = [(last_friday - timedelta(weeks=i)).strftime('%Y%m%d') for i in range(16)]
    missing_dates = [d for d in target_fridays if d not in existing_weeks]

    if missing_dates:
        try:
            session_tdcc = requests.Session()
            url_home = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
            r_home = session_tdcc.get(url_home, headers=headers, timeout=10)
            if r_home.status_code == 200:
                soup_home = BeautifulSoup(r_home.text, 'html.parser')
                form = soup_home.find('form')
                action = form.get('action', '') if form else ''
                target_url = f"https://www.tdcc.com.tw{action}" if action.startswith('/') else (action if action.startswith('http') else f"https://www.tdcc.com.tw/portal/zh/smWeb/{action}")

                h_rec = []
                for d_str in missing_dates:
                    try:
                        r_page = session_tdcc.get(url_home, headers=headers, timeout=8)
                        sp_page = BeautifulSoup(r_page.text, 'html.parser')
                        cur_form = sp_page.find('form')
                        payload = {inp.get('name'): inp.get('value', '') for inp in cur_form.find_all('input') if inp.get('name')}
                        payload.update({'scaDate': d_str, 'sqlMethod': 'StockNo', 'stockNo': pure_code, 'stockName': '', 'sub': '查詢'})
                        resp = session_tdcc.post(target_url, data=payload, headers=headers, timeout=8)
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
                        time.sleep(0.15)
                    except Exception:
                        continue
                if h_rec:
                    storage.save_holding_data(h_rec)
        except Exception:
            pass

    # 嚴格回傳 3 個變數
    return storage.load_institutional_df(), storage.load_margin_df(), storage.load_holding_df()
