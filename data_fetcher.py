"""
data_fetcher.py - 整合技術與籌碼資料擷取模組
版本: 202611071200
"""
import os
import re
import json
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202611071200"

from storage import (
    StockChipStorage, 
    COMMON_STOCK_NAMES, 
    load_stock_names_dict, 
    get_stock_chinese_name
)

def fetch_stock_name(pure_code: str) -> str:
    """取得股票中文名稱 (優先查字典/快取，無則爬蟲)"""
    return get_stock_chinese_name(pure_code)

def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: str = None, force_refresh: bool = False):
    """
    自本地 SQLite 或 Yahoo Finance 擷取歷史日 K 線資料。
    若本地已存在歷史，則抓取最新資料進行增量合併。
    """
    raw_str = str(raw_ticker).strip()
    if not raw_str:
        return None
        
    pure_code = raw_str.upper()
    if pure_code.startswith("^"):
        full_ticker = pure_code
    elif pure_code.isdigit():
        full_ticker = f"{pure_code}.TW"
    else:
        full_ticker = pure_code

    storage = StockChipStorage(pure_code)
    db_df = storage.load_daily_k_df()
    last_k_date = storage.get_latest_daily_k_date()

    shares_outstanding = None
    ticker = yf.Ticker(full_ticker)
    
    # 嘗試取得在外流通股數
    if pure_code.isdigit():
        try:
            shares_outstanding = ticker.info.get("sharesOutstanding")
        except Exception:
            pass

    fetch_period = period if force_refresh or db_df.empty or not last_k_date else "5d"

    try:
        df_new = ticker.history(period=fetch_period)
    except Exception:
        df_new = pd.DataFrame()

    # 若個股查無 .TW，自動切換至 .TWO 嘗試
    if (df_new is None or df_new.empty) and pure_code.isdigit() and full_ticker.endswith(".TW"):
        full_ticker = f"{pure_code}.TWO"
        ticker = yf.Ticker(full_ticker)
        try:
            shares_outstanding = ticker.info.get("sharesOutstanding")
        except Exception:
            pass
        try:
            df_new = ticker.history(period=fetch_period)
        except Exception:
            df_new = pd.DataFrame()

    if df_new is not None and not df_new.empty:
        # 強制移除時區，防止比對錯位
        if df_new.index.tz is not None:
            df_new.index = df_new.index.tz_localize(None)

        # 【防呆防錯備註 2026-11-07】：過濾 Volume <= 0 或四價包含空值的非交易日（避免 10/23 等空量出現在 K 線，並防止盤後缺價過渡資料污染）
        valid_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df_new.columns]
        if valid_cols and 'Volume' in df_new.columns:
            df_new = df_new.dropna(subset=valid_cols)
            df_new = df_new[df_new['Volume'] > 0]

        if not db_df.empty and not force_refresh:
            combined = pd.concat([db_df, df_new])
            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
        else:
            combined = df_new.sort_index()
            
        storage.save_daily_k_df(combined)
        return combined, full_ticker, shares_outstanding
    elif not db_df.empty:
        return db_df, full_ticker, shares_outstanding

    return None

def sync_chip_data(pure_code: str, df_dates: pd.DatetimeIndex, status_placeholder=None, force_refresh: bool = False):
    """
    同步並補齊法人、資券與大戶籌碼資料。
    """
    pure_code = str(pure_code).strip()
    storage = StockChipStorage(pure_code)

    if pure_code.startswith("^") or not pure_code.isdigit():
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    if len(df_dates) == 0:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    last_inst_date = storage.get_latest_inst_date()
    last_margin_date = storage.get_latest_margin_date()
    last_holding_date = storage.get_latest_holding_date()

    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')
    now = datetime.now()
    now_date_str = now.strftime('%Y-%m-%d')

    # 短路判斷 1：三大法人與資券
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

    # 短路判斷 2：集保大戶
    should_fetch_holding = force_refresh
    if not should_fetch_holding:
        if not last_holding_date:
            should_fetch_holding = True
        else:
            last_dt = pd.to_datetime(last_holding_date)
            diff_days = (now - last_dt).days
            if diff_days >= 7:
                should_fetch_holding = True
            elif now.weekday() == 4 and now.hour >= 20 and diff_days >= 1:
                should_fetch_holding = True

    # 執行網路抓取
    if should_fetch_inst:
        if status_placeholder:
            status_placeholder.info(f"正在更新 {pure_code} 三大法人買賣超...")
        inst_records = fetch_institutional_investors(pure_code, df_dates)
        if inst_records:
            storage.save_institutional_data(inst_records)

    if should_fetch_margin:
        if status_placeholder:
            status_placeholder.info(f"正在更新 {pure_code} 融資融券資訊...")
        margin_records = fetch_margin_short_data(pure_code, df_dates)
        if margin_records:
            storage.save_margin_data(margin_records)

    if should_fetch_holding:
        if status_placeholder:
            status_placeholder.info(f"正在更新 {pure_code} 集保大戶股權分散表...")
        holding_records = fetch_tdcc_holding_data(pure_code)
        if holding_records:
            storage.save_holding_data(holding_records)

    if status_placeholder:
        status_placeholder.empty()

    return (
        storage.load_institutional_df(),
        storage.load_margin_df(),
        storage.load_holding_df()
    )

def fetch_institutional_investors(pure_code: str, df_dates: pd.DatetimeIndex) -> list:
    """擷取三大法人買賣超資料 (單位：張)"""
    records = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 擷取近 30 個交易日
    sample_dates = df_dates[-30:]
    for dt in sample_dates:
        date_twse = dt.strftime('%Y%m%d')
        date_str = dt.strftime('%Y-%m-%d')
        
        # 1. 嘗試上市 TWSE
        url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_twse}&selectType=ALLBUT0999&response=json"
        try:
            res = requests.get(url_twse, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("stat") == "OK" and "data" in data:
                    for row in data["data"]:
                        if row[0].strip() == pure_code:
                            def clean_val(v):
                                return float(str(v).replace(",", "").strip()) / 1000.0
                            f_net = clean_val(row[4])
                            t_net = clean_val(row[10])
                            d_net = clean_val(row[11])
                            records.append((date_str, f_net, t_net, d_net))
                            break
                    continue
        except Exception:
            pass

        # 2. 嘗試上櫃 TPEx
        try:
            year_tw = dt.year - 1911
            date_tpex = f"{year_tw}/{dt.strftime('%m/%d')}"
            url_tpex = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_tpex}"
            res = requests.get(url_tpex, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if "aaData" in data:
                    for row in data["aaData"]:
                        if row[0].strip() == pure_code:
                            def clean_val(v):
                                return float(str(v).replace(",", "").strip()) / 1000.0
                            f_net = clean_val(row[7])
                            t_net = clean_val(row[8])
                            d_net = clean_val(row[9])
                            records.append((date_str, f_net, t_net, d_net))
                            break
        except Exception:
            pass

        time.sleep(0.05)

    return records

def fetch_margin_short_data(pure_code: str, df_dates: pd.DatetimeIndex) -> list:
    """擷取融資融券買賣增減與餘額 (單位：張)"""
    records = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    sample_dates = df_dates[-30:]
    for dt in sample_dates:
        date_twse = dt.strftime('%Y%m%d')
        date_str = dt.strftime('%Y-%m-%d')

        # 1. 嘗試上市 TWSE
        url_twse = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={date_twse}&selectType=ALL&response=json"
        try:
            res = requests.get(url_twse, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("stat") == "OK" and "tables" in data:
                    table = data["tables"][0]
                    for row in table.get("data", []):
                        if row[0].strip() == pure_code:
                            def clean_val(v):
                                return float(str(v).replace(",", "").strip())
                            m_diff = clean_val(row[5])
                            m_bal = clean_val(row[6])
                            s_diff = clean_val(row[11])
                            s_bal = clean_val(row[12])
                            records.append((date_str, m_diff, s_diff, m_bal, s_bal))
                            break
                    continue
        except Exception:
            pass

        # 2. 嘗試上櫃 TPEx
        try:
            year_tw = dt.year - 1911
            date_tpex = f"{year_tw}/{dt.strftime('%m/%d')}"
            url_tpex = f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={date_tpex}"
            res = requests.get(url_tpex, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if "aaData" in data:
                    for row in data["aaData"]:
                        if row[0].strip() == pure_code:
                            def clean_val(v):
                                return float(str(v).replace(",", "").strip())
                            m_diff = clean_val(row[4])
                            m_bal = clean_val(row[5])
                            s_diff = clean_val(row[10])
                            s_bal = clean_val(row[11])
                            records.append((date_str, m_diff, s_diff, m_bal, s_bal))
                            break
        except Exception:
            pass

        time.sleep(0.05)

    return records

def fetch_tdcc_holding_data(pure_code: str) -> list:
    """擷取集保大戶持股分級資料 (集保結算所 TDCC 官方來源)"""
    records = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            lines = res.text.splitlines()
            for line in lines:
                parts = line.strip().split(",")
                if len(parts) >= 6 and parts[1].strip() == pure_code:
                    d_raw = parts[0].strip()
                    try:
                        d_str = datetime.strptime(d_raw, '%Y%m%d').strftime('%Y-%m-%d')
                        level = int(parts[2].strip())
                        percent = float(parts[5].strip())
                        records.append((d_str, level, percent))
                    except Exception:
                        pass
    except Exception:
        pass

    return records
