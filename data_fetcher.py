"""
台股技術與籌碼分析系統 - 外部資料爬蟲與清洗模組
負責 yfinance 日 K 抓取、休市 0 成交量過濾、盤中補點防護、
TDCC 集保大戶分級增量爬蟲、FinMind 法人與資券同步、ISIN 股票中文名稱快取。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

# ==============================================================================
# 模組名稱: data_fetcher
# 模組版本: 202610271510
# 核心職責: 外部資料擷取、ISIN中文名稱爬蟲、yfinance清洗、FinMind與TDCC爬蟲
# ==============================================================================

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610271510"

import os
import re
import json
import logging
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import yfinance as yf

import config
from storage import (
    load_chip_from_db,
    save_chip_to_db,
    load_tdcc_from_db,
    save_tdcc_to_db
)

# 靜音 yfinance 內部 404 探測日誌
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# ------------------------------------------------------------------------------
# 1. ISIN 中文名稱爬蟲與本地快取
# ------------------------------------------------------------------------------
def get_stock_chinese_name(symbol):
    """自本地快取或 TWSE ISIN 系統取得股票標準中文名稱"""
    pure_code = re.search(r'\d+', str(symbol))
    code = pure_code.group(0) if pure_code else str(symbol).strip()
    
    # 讀取本地快取
    cache = {}
    if os.path.exists(config.NAME_CACHE_FILE):
        try:
            with open(config.NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                if code in cache:
                    return cache[code]
        except Exception:
            pass

    # 查表備援
    if code in config.COMMON_STOCK_MAP:
        return config.COMMON_STOCK_MAP[code]

    # 爬取臺灣證券交易所 ISIN
    url = f"https://isin.twse.com.tw/isin/single_main.jsp?owncode={code}&stockname="
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            resp.encoding = 'big5'
            soup = BeautifulSoup(resp.text, 'html.parser')
            table = soup.find('table', class_='h4')
            if table:
                rows = table.find_all('tr')
                if len(rows) > 1:
                    cols = rows[1].find_all('td')
                    if len(cols) >= 3:
                        c_name = cols[2].text.strip()
                        if c_name:
                            cache[code] = c_name
                            try:
                                with open(config.NAME_CACHE_FILE, 'w', encoding='utf-8') as f:
                                    json.dump(cache, f, ensure_ascii=False, indent=2)
                            except Exception:
                                pass
                            return c_name
    except Exception:
        pass

    return code

# ------------------------------------------------------------------------------
# 2. yfinance 日 K 線清洗與盤中補點防護
# ------------------------------------------------------------------------------
def fetch_stock_data(symbol, period='1y'):
    """下載日 K 線並執行嚴格清洗（剔除國定休市 0 成交量假 K 線）"""
    pure_code = re.search(r'\d+', str(symbol))
    code = pure_code.group(0) if pure_code else str(symbol).strip()

    df = None
    suffix_list = ['.TW', '.TWO', '']
    ticker_obj = None

    for sfx in suffix_list:
        try:
            tk = yf.Ticker(f"{code}{sfx}")
            temp_df = tk.history(period=period)
            if temp_df is not None and not temp_df.empty:
                df = temp_df
                ticker_obj = tk
                break
        except Exception:
            continue

    if df is None or df.empty:
        return None, 0

    # 嚴格全域清洗：必須刪除空值與 0 成交量的休市假資料
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df = df[df['Volume'] > 0]
    if df.empty:
        return None, 0

    # 取得在外流通股數
    shares = 0
    try:
        shares = ticker_obj.fast_info.shares
    except Exception:
        try:
            shares = ticker_obj.info.get('sharesOutstanding', 0)
        except Exception:
            shares = 0

    # 盤中即時補點防護（必須 09:00 後且有實質成交量）
    now_dt = datetime.now()
    if now_dt.time() >= datetime.strptime("09:00", "%H:%M").time():
        try:
            fi = ticker_obj.fast_info
            last_vol = getattr(fi, 'last_volume', 0)
            last_price = getattr(fi, 'last_price', 0)
            if last_vol and last_vol > 0 and last_price and last_price > 0:
                last_dt = df.index[-1].date()
                if last_dt < now_dt.date():
                    # 追加今日盤中臨時 Bar
                    new_row = pd.DataFrame({
                        'Open': [fi.open if hasattr(fi, 'open') else last_price],
                        'High': [fi.day_high if hasattr(fi, 'day_high') else last_price],
                        'Low': [fi.day_low if hasattr(fi, 'day_low') else last_price],
                        'Close': [last_price],
                        'Volume': [last_vol]
                    }, index=[pd.Timestamp(now_dt.date())])
                    df = pd.concat([df, new_row])
        except Exception:
            pass

    return df, shares

# ------------------------------------------------------------------------------
# 3. FinMind 三大法人與資券爬蟲（換算為「張」）
# ------------------------------------------------------------------------------
def fetch_chip_data(symbol, start_date):
    """自本地 SQLite 優先讀取，缺漏則呼叫 FinMind 補齊並換算為張"""
    pure_code = re.search(r'\d+', str(symbol))
    code = pure_code.group(0) if pure_code else str(symbol).strip()

    # 優先讀取 DB
    db_df = load_chip_from_db(code, start_date)
    
    # 簡易判斷若已有近期資料則直接回傳
    if db_df is not None and not db_df.empty:
        last_date_str = db_df['date'].max()
        if (datetime.now() - datetime.strptime(last_date_str, "%Y-%m-%d")).days <= 3:
            return db_df

    # 向 FinMind 請求法人資料
    try:
        url_inst = "https://api.finmindtrade.com/api/v4/data"
        p_inst = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": code,
            "start_date": start_date
        }
        res_inst = requests.get(url_inst, params=p_inst, timeout=10).json()
        raw_inst = res_inst.get('data', [])

        inst_dict = {}
        for r in raw_inst:
            d = r['date']
            if d not in inst_dict:
                inst_dict[d] = {'foreign_buy': 0.0, 'trust_buy': 0.0, 'dealer_buy': 0.0}
            name = r.get('name', '')
            net_shares = r.get('buy', 0) - r.get('sell', 0)
            net_lots = net_shares / 1000.0  # 股換算為張
            if any(k in name for k in ['Foreign', '外資', '外陸資']):
                inst_dict[d]['foreign_buy'] += net_lots
            elif any(k in name for k in ['Investment_Trust', '投信']):
                inst_dict[d]['trust_buy'] += net_lots
            elif any(k in name for k in ['Dealer', '自營']):
                inst_dict[d]['dealer_buy'] += net_lots

        # 資券資料
        p_margin = {
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": code,
            "start_date": start_date
        }
        res_margin = requests.get(url_inst, params=p_margin, timeout=10).json()
        raw_margin = res_margin.get('data', [])

        margin_dict = {}
        for r in raw_margin:
            d = r['date']
            # 增減計算
            m_buy = r.get('MarginPurchaseBuy', 0)
            m_sell = r.get('MarginPurchaseSell', 0)
            m_repay = r.get('MarginPurchaseCashRepayment', 0)
            m_change = (m_buy - m_sell - m_repay) / 1000.0
            m_bal = r.get('MarginPurchaseTodayBalance', 0) / 1000.0

            s_sell = r.get('ShortSaleSell', 0)
            s_buy = r.get('ShortSaleBuy', 0)
            s_repay = r.get('ShortSaleCashRepayment', 0)
            s_change = (s_sell - s_buy - s_repay) / 1000.0
            s_bal = r.get('ShortSaleTodayBalance', 0) / 1000.0

            s_ratio = (s_bal / m_bal * 100.0) if m_bal > 0 else 0.0
            margin_dict[d] = {
                'margin_balance': m_bal, 'margin_change': m_change,
                'short_balance': s_bal, 'short_change': s_change,
                'short_ratio': s_ratio
            }

        # 彙整寫入
        all_dates = sorted(list(set(list(inst_dict.keys()) + list(margin_dict.keys()))))
        rows = []
        for d in all_dates:
            i_info = inst_dict.get(d, {'foreign_buy': 0.0, 'trust_buy': 0.0, 'dealer_buy': 0.0})
            m_info = margin_dict.get(d, {'margin_balance': 0.0, 'margin_change': 0.0, 'short_balance': 0.0, 'short_change': 0.0, 'short_ratio': 0.0})
            rows.append({
                'date': d, 'symbol': code,
                'foreign_buy': i_info['foreign_buy'], 'trust_buy': i_info['trust_buy'], 'dealer_buy': i_info['dealer_buy'],
                'margin_balance': m_info['margin_balance'], 'margin_change': m_info['margin_change'],
                'short_balance': m_info['short_balance'], 'short_change': m_info['short_change'],
                'short_ratio': m_info['short_ratio']
            })

        if rows:
            res_df = pd.DataFrame(rows)
            save_chip_to_db(res_df)
            return res_df
    except Exception:
        pass

    return db_df if db_df is not None else pd.DataFrame()

# ------------------------------------------------------------------------------
# 4. 集保大戶持股比例（TDCC）增量爬蟲
# ------------------------------------------------------------------------------
def fetch_tdcc_data(symbol):
    """自本地讀取集保歷史，僅針對缺失週別增量爬取 TDCC"""
    pure_code = re.search(r'\d+', str(symbol))
    code = pure_code.group(0) if pure_code else str(symbol).strip()

    db_tdcc = load_tdcc_from_db(code)
    existing_dates = set(db_tdcc['date'].unique()) if (db_tdcc is not None and not db_tdcc.empty) else set()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    })

    url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    try:
        r = session.get(url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        form = soup.find('form')
        if not form:
            return db_tdcc

        action = form.get('action', '')
        post_url = action if action.startswith('http') else "https://www.tdcc.com.tw" + action
        
        # 爬取可用日期選單
        select = soup.find('select', {'id': 'SCA_DATE'}) or soup.find('select', {'name': 'scaDates'})
        if not select:
            return db_tdcc

        avail_dates = [opt.get('value', '').strip() for opt in select.find_all('option') if opt.get('value', '').strip()]
        needed_dates = [d for d in avail_dates if d not in existing_dates][:15]

        new_records = []
        for dt_str in needed_dates:
            p_data = {"scaDates": dt_str, "scaDate": dt_str, "StockNo": code}
            pr = session.post(post_url, data=p_data, timeout=10)
            if pr.status_code == 200:
                tables = pd.read_html(pr.text)
                for tbl in tables:
                    # 鎖定含 1 與 15 級別的表格
                    col0 = tbl.iloc[:, 0].astype(str)
                    if col0.str.contains('1').any() and col0.str.contains('15').any():
                        for _, row in tbl.iterrows():
                            lvl_str = str(row.iloc[0]).strip()
                            if lvl_str.isdigit() and 1 <= int(lvl_str) <= 15:
                                new_records.append({
                                    'date': dt_str,
                                    'symbol': code,
                                    'level': int(lvl_str),
                                    'holders': int(str(row.iloc[2]).replace(',', '')),
                                    'shares': float(str(row.iloc[3]).replace(',', '')),
                                    'percent': float(str(row.iloc[4]).replace('%', ''))
                                })
                        break

        if new_records:
            new_df = pd.DataFrame(new_records)
            save_tdcc_to_db(new_df)
            db_tdcc = load_tdcc_from_db(code)
    except Exception:
        pass

    return db_tdcc
