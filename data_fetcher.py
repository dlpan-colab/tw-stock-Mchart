"""
data_fetcher.py - 外部資料抓取與增量同步模組
版本: 202611052200
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202611052200"

import os
import re
import io
import time
import json
import requests
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from storage import StockChipStorage, get_stock_chinese_name

FINMIND_TOKEN = ""

INDEX_MAP = {
    # 台股
    "TWII": "^TWII", "加權": "^TWII", "大盤": "^TWII", "^TWII": "^TWII",
    "TWOII": "^TWOII", "OTC": "^TWOII", "櫃買": "^TWOII", "^TWOII": "^TWOII",
    # 美股
    "DJI": "^DJI", "道瓊": "^DJI", "^DJI": "^DJI",
    "IXIC": "^IXIC", "COMP": "^IXIC", "那指": "^IXIC", "那斯達克": "^IXIC", "^IXIC": "^IXIC",
    "SOX": "^SOX", "費半": "^SOX", "半導體": "^SOX", "^SOX": "^SOX",
    "GSPC": "^GSPC", "SP500": "^GSPC", "標普": "^GSPC", "^GSPC": "^GSPC",
    # 亞股
    "N225": "^N225", "NIKKEI": "^N225", "日經": "^N225", "^N225": "^N225",
    "KS11": "^KS11", "KOSPI": "^KS11", "韓綜": "^KS11", "^KS11": "^KS11",
    # 歐股
    "FTSE": "^FTSE", "富時": "^FTSE", "英國": "^FTSE", "^FTSE": "^FTSE",
    "GDAXI": "^GDAXI", "DAX": "^GDAXI", "德國": "^GDAXI", "^GDAXI": "^GDAXI",
    "FCHI": "^FCHI", "CAC": "^FCHI", "法國": "^FCHI", "^FCHI": "^FCHI",
}

def resolve_ticker_code(raw_input: str) -> str:
    cleaned = str(raw_input).strip()
    upper = cleaned.upper()
    if upper in INDEX_MAP:
        return INDEX_MAP[upper]
    return cleaned

def fetch_stock_name(pure_code: str) -> str:
    return get_stock_chinese_name(pure_code)

def _detect_market_suffix(pure_code: str, raw_ticker: str) -> list:
    if str(pure_code).startswith("^") or str(raw_ticker).startswith("^"):
        return [""]

    raw_upper = str(raw_ticker).strip().upper()
    if raw_upper.endswith(".TW"):
        return ['.TW']
    if raw_upper.endswith(".TWO"):
        return ['.TWO']

    try:
        from storage import load_stock_names_dict
        stock_dict = load_stock_names_dict()
        meta = stock_dict.get(pure_code, "")
        if isinstance(meta, dict):
            mkt = meta.get('market', '')
            if '櫃' in mkt or 'TWO' in mkt or 'OTC' in mkt:
                return ['.TWO', '.TW']
            if '市' in mkt or 'TW' in mkt:
                return ['.TW', '.TWO']
        elif isinstance(meta, str):
            if '上櫃' in meta:
                return ['.TWO', '.TW']
            if '上市' in meta:
                return ['.TW', '.TWO']
    except Exception:
        pass

    return ['.TW', '.TWO']

def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: str = None, force_refresh: bool = False):
    import yfinance as yf
    resolved_ticker = resolve_ticker_code(raw_ticker)
    raw_str = resolved_ticker.strip().upper()

    if raw_str.startswith("^"):
        pure_code = raw_str
    else:
        match = re.search(r'\d+', raw_str)
        pure_code = match.group(0) if match else raw_str.split('.')[0]

    storage = StockChipStorage(pure_code)
    cached_df = storage.load_daily_k_df()
    latest_cached_date = storage.get_latest_daily_k_date()

    # 判定下載期間：若本地已有充足歷史，僅下載近 5 天增量更新 (極速)
    fetch_period = period
    if not force_refresh and not cached_df.empty and len(cached_df) >= 40 and latest_cached_date:
        fetch_period = "5d"

    ticker_obj = None
    df_new = pd.DataFrame()
    shares_outstanding = None
    suffixes = _detect_market_suffix(pure_code, raw_str)

    for suffix in suffixes:
        test_ticker = f"{pure_code}{suffix}" if suffix else pure_code
        try:
            t = yf.Ticker(test_ticker)
            d = t.history(period=fetch_period, auto_adjust=False)
            if not d.empty and len(d) >= 1:
                df_new = d
                ticker_obj = t
                try:
                    shares_outstanding = t.fast_info.shares
                except Exception:
                    shares_outstanding = None
                break
        except Exception:
            continue

    if df_new.empty and cached_df.empty:
        return None, "", None

    # 合併本地快取與新下載資料
    if not df_new.empty:
        if df_new.index.tz is not None:
            df_new.index = df_new.index.tz_localize(None)
        df_new.index = df_new.index.normalize()
        df_new = df_new.dropna(subset=['Open', 'High', 'Low', 'Close'])
        if not cached_df.empty and fetch_period == "5d":
            df = pd.concat([cached_df[~cached_df.index.isin(df_new.index)], df_new]).sort_index()
        else:
            df = df_new
        storage.save_daily_k_df(df)
    else:
        df = cached_df

    if ticker_obj is None:
        full_ticker_name = f"{pure_code}.TW" if not pure_code.startswith("^") else pure_code
    else:
        full_ticker_name = ticker_obj.ticker

    if not pure_code.startswith("^"):
        df = df[df['Volume'] > 0]
    return df, full_ticker_name, shares_outstanding

def sync_chip_data(pure_code: str, df_dates, status_placeholder=None, force_refresh: bool = False):
    pure_code = str(pure_code).strip()
    if pure_code.startswith("^"):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    storage = StockChipStorage(pure_code)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://www.tdcc.com.tw/portal/zh/smWeb/qryStock'
    }

    last_inst_date = storage.get_latest_inst_date()
    last_margin_date = storage.get_latest_margin_date()
    last_holding_date = storage.get_latest_holding_date()

    now = datetime.now()
    now_date_str = now.strftime('%Y-%m-%d')
    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')

    # 短路判斷 1：三大法人與資券是否需要抓取？
    # 每天 17:00 前證交所不公布當日數據。若最後紀錄已達最新收盤日，或今日尚未到 17:00 且已有昨日資料，則短路跳過。
    should_fetch_inst = force_refresh
    if not should_fetch_inst:
        if not last_inst_date:
            should_fetch_inst = True
        elif last_inst_date < latest_trade_date_str:
            if now_date_str == latest_trade_date_str and now.hour < 17:
                should_fetch_inst = False
            else:
                should_fetch_inst = True

    should_fetch_margin = force_refresh
    if not should_fetch_margin:
        if not last_margin_date:
            should_fetch_margin = True
        elif last_margin_date < latest_trade_date_str:
            if now_date_str == latest_trade_date_str and now.hour < 17:
                should_fetch_margin = False
            else:
                should_fetch_margin = True

    target_start_date = (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d')
    inst_query_start = (pd.to_datetime(last_inst_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_inst_date else target_start_date
    margin_query_start = (pd.to_datetime(last_margin_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_margin_date else target_start_date

    # 1. 法人買賣超同步
    if should_fetch_inst:
        inst_records = []
        try:
            url_inst = "https://api.finmindtrade.com/api/v4/data"
            p_inst = {
                "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id": pure_code,
                "start_date": inst_query_start,
                "token": FINMIND_TOKEN
            }
            res = requests.get(url_inst, params=p_inst, headers=headers, timeout=6)
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
                    for d in all_dates:
                        inst_records.append((
                            d,
                            float(f_s.get(d, 0.0)),
                            float(t_s.get(d, 0.0)),
                            float(d_s.get(d, 0.0))
                        ))
        except Exception:
            pass

        if inst_records:
            storage.save_institutional_data(inst_records)

    # 2. 資券增減同步
    if should_fetch_margin:
        try:
            url_ms = "https://api.finmindtrade.com/api/v4/data"
            p_ms = {
                "dataset": "TaiwanStockMarginPurchaseShortSale",
                "data_id": pure_code,
                "start_date": margin_query_start,
                "token": FINMIND_TOKEN
            }
            res_ms = requests.get(url_ms, params=p_ms, headers=headers, timeout=6)
            if res_ms.status_code == 200:
                data_ms = res_ms.json().get('data', [])
                if data_ms:
                    ms_df = pd.DataFrame(data_ms)
                    records_ms = []
                    for _, r in ms_df.iterrows():
                        mb = float(r.get('MarginPurchaseBuy', 0) or 0)
                        ms = float(r.get('MarginPurchaseSell', 0) or 0)
                        mr = float(r.get('MarginPurchaseCashRepayment', 0) or 0)
                        m_diff = mb - ms - mr

                        sb = float(r.get('ShortSaleBuy', 0) or 0)
                        ss = float(r.get('ShortSaleSell', 0) or 0)
                        sr = float(r.get('ShortSaleCashRepayment', 0) or 0)
                        s_diff = ss - sb - sr

                        m_raw_bal = r.get('MarginPurchaseTodayBalance') or r.get('MarginPurchaseBalance') or r.get('margin_purchase') or 0
                        s_raw_bal = r.get('ShortSaleTodayBalance') or r.get('ShortSaleBalance') or r.get('short_sale') or 0
                        m_bal = float(m_raw_bal)
                        s_bal = float(s_raw_bal)

                        records_ms.append((r['date'], m_diff, s_diff, m_bal, s_bal))
                    storage.save_margin_data(records_ms)
        except Exception:
            pass

    # 3. 集保大戶持股同步 (短路快取：週六 09:00 前不爬)
    should_fetch_holding = force_refresh
    if not should_fetch_holding:
        if not last_holding_date:
            should_fetch_holding = True
        else:
            # 上次資料日期距今超過 7 天，且今天為週六或週日才允許發動
            days_since = (now.date() - pd.to_datetime(last_holding_date).date()).days
            if days_since >= 7 and (now.weekday() >= 5 or (now.weekday() == 4 and now.hour >= 20)):
                should_fetch_holding = True

    if should_fetch_holding:
        holding_df = storage.load_holding_df()
        existing_weeks = set(holding_df['date'].dt.strftime('%Y%m%d')) if not holding_df.empty else set()
        try:
            session_tdcc = requests.Session()
            url_home = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
            r_home = session_tdcc.get(url_home, headers=headers, timeout=6)
            if r_home.status_code == 200:
                soup_home = BeautifulSoup(r_home.text, 'html.parser')
                form = soup_home.find('form')
                action = form.get('action', '') if form else ''
                target_url = f"https://www.tdcc.com.tw{action}" if action.startswith('/') else (action if action.startswith('http') else f"https://www.tdcc.com.tw/portal/zh/smWeb/{action}")
                available_dates = [
                    o.get('value').strip() for o in soup_home.find_all('option')
                    if o.get('value') and o.get('value').strip().isdigit() and len(o.get('value').strip()) == 8 and o.get('value').strip().startswith('20')
                ]
                missing_dates = [d for d in available_dates if d not in existing_weeks][:10]

                h_rec = []
                for d_str in missing_dates:
                    try:
                        r_page = session_tdcc.get(url_home, headers=headers, timeout=5)
                        sp_page = BeautifulSoup(r_page.text, 'html.parser')
                        cur_form = sp_page.find('form')
                        payload = {inp.get('name'): inp.get('value', '') for inp in cur_form.find_all('input') if inp.get('name')}
                        payload.update({
                            'scaDate': d_str,
                            'sqlMethod': 'StockNo',
                            'stockNo': pure_code,
                            'stockName': '',
                            'sub': '查詢'
                        })
                        resp = session_tdcc.post(target_url, data=payload, headers=headers, timeout=5)
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
                    except Exception:
                        continue
                if h_rec:
                    storage.save_holding_data(h_rec)
        except Exception:
            pass

    return storage.load_institutional_df(), storage.load_margin_df(), storage.load_holding_df()
