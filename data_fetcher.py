"""
data_fetcher.py - 整合技術與籌碼資料擷取模組 (市場別精確分流、防呆備註與零白等版)
版本: 202611102235
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
MODULE_VERSION = "202611102235"

from storage import (
    StockChipStorage,
    COMMON_STOCK_NAMES,
    load_stock_names_dict,
    get_stock_chinese_name
)

FINMIND_TOKEN = ""


def fetch_stock_name(pure_code: str) -> str:
    """取得股票中文名稱 (優先查字典/快取，無則爬蟲)"""
    return get_stock_chinese_name(pure_code)


def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: str = None, force_refresh: bool = False):
    """
    自本地 SQLite 或官方 API / Yahoo Finance 擷取歷史日 K 線資料。
    若本地已存在歷史，則抓取最新資料進行增量合併。
    """
    raw_str = str(raw_ticker).strip()
    if not raw_str:
        return None

    pure_code = raw_str.upper()
    is_index = pure_code.startswith("^")

    if pure_code == "^TWII":
        target_ticker = "^TWII"
        full_ticker = "^TWII"
    elif pure_code == "^TWOII":
        target_ticker = "006201.TWO"
        full_ticker = "^TWOII"
    elif is_index:
        target_ticker = pure_code
        full_ticker = pure_code
    elif pure_code.isdigit():
        target_ticker = f"{pure_code}.TW"
        full_ticker = f"{pure_code}.TW"
    else:
        target_ticker = pure_code
        full_ticker = pure_code

    storage = StockChipStorage(pure_code)
    db_df = storage.load_daily_k_df()
    last_k_date = storage.get_latest_daily_k_date()
    shares_outstanding = None

    if force_refresh:
        db_df = pd.DataFrame()

    ticker = yf.Ticker(target_ticker)
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

    if (df_new is None or df_new.empty):
        if target_ticker.endswith(".TWO"):
            alt_ticker = target_ticker.replace(".TWO", ".TW")
            try:
                df_new = yf.Ticker(alt_ticker).history(period=fetch_period)
            except Exception:
                pass
        elif pure_code.isdigit() and target_ticker.endswith(".TW"):
            alt_ticker = f"{pure_code}.TWO"
            try:
                t_alt = yf.Ticker(alt_ticker)
                shares_outstanding = t_alt.info.get("sharesOutstanding")
                df_new = t_alt.history(period=fetch_period)
                if df_new is not None and not df_new.empty:
                    full_ticker = alt_ticker  # 成功切換為上櫃代碼
            except Exception:
                pass

    if df_new is not None and not df_new.empty:
        if df_new.index.tz is not None:
            df_new.index = df_new.index.tz_localize(None)

        valid_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df_new.columns]
        if valid_cols:
            df_new = df_new.dropna(subset=valid_cols)

        if not is_index and 'Volume' in df_new.columns:
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


def sync_chip_data(
    pure_code: str,
    df_dates: pd.DatetimeIndex,
    status_placeholder=None,
    force_refresh: bool = False,
    full_ticker: str = None
):
    """
    智慧增量同步三大法人、資券與集保大戶。
    以實體資料庫差額精準驅動，嚴禁無腦連續輪詢。
    """
    pure_code = str(pure_code).strip()
    storage = StockChipStorage(pure_code)

    if pure_code.startswith("^") or not pure_code.isdigit():
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    if len(df_dates) == 0:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    last_margin_date = storage.get_latest_margin_date()
    last_holding_date = storage.get_latest_holding_date()

    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')
    now = datetime.now()
    now_date_str = now.strftime('%Y-%m-%d')

    # 1. 三大法人判斷 (差額比對)
    existing_inst_df = storage.load_institutional_df()
    existing_dates = set(existing_inst_df['date'].dt.strftime('%Y-%m-%d')) if not existing_inst_df.empty else set()
    
    recent_k_dates = [d.strftime('%Y-%m-%d') for d in df_dates[-30:]]
    missing_inst_dates = [d for d in recent_k_dates if d not in existing_dates]

    if now_date_str in missing_inst_dates and now.hour < 17:
        missing_inst_dates.remove(now_date_str)

    should_fetch_inst = force_refresh or (len(missing_inst_dates) > 0)

    # 2. 資券判斷
    should_fetch_margin = force_refresh
    if not should_fetch_margin:
        if not last_margin_date:
            should_fetch_margin = True
        elif last_margin_date < latest_trade_date_str:
            if now_date_str == latest_trade_date_str and now.hour < 17:
                should_fetch_margin = False
            else:
                should_fetch_margin = True

    # 3. 集保大戶判斷
    should_fetch_holding = force_refresh
    if not should_fetch_holding:
        if not last_holding_date:
            should_fetch_holding = True
        else:
            diff_days = (now - pd.to_datetime(last_holding_date)).days
            is_weekend_publish = (now.weekday() == 4 and now.hour >= 20) or (now.weekday() in [5, 6])
            if diff_days >= 7:
                should_fetch_holding = True
            elif is_weekend_publish and diff_days >= 1:
                should_fetch_holding = True

    # 執行精準擷取與入庫
    if should_fetch_inst:
        target_dates = [d for d in df_dates if d.strftime('%Y-%m-%d') in missing_inst_dates] if not force_refresh else df_dates
        if force_refresh and not missing_inst_dates:
            target_dates = [d for d in df_dates if d.strftime('%Y-%m-%d') in recent_k_dates[-5:]]

        inst_records = fetch_institutional_investors(
            pure_code=pure_code,
            df_dates=df_dates,
            explicit_missing_dates=target_dates,
            full_ticker=full_ticker
        )
        if inst_records:
            storage.save_institutional_data(inst_records)

    if should_fetch_margin:
        start_filter = None if force_refresh else last_margin_date
        margin_records = fetch_margin_short_data(pure_code, df_dates, start_date_exclusive=start_filter)
        if margin_records:
            storage.save_margin_data(margin_records)

    if should_fetch_holding:
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


def fetch_institutional_investors(
    pure_code: str,
    df_dates: pd.DatetimeIndex,
    start_date_exclusive: str = None,
    explicit_missing_dates: list = None,
    full_ticker: str = None
) -> list:
    """
    【防呆防錯備註 2026-11-10】【修改目的與潛在風險說明】：
    1. 修改目的：依據 full_ticker 後綴 (.TW 或 .TWO) 精確分流證交所與櫃買中心。
       - 上市標的 (.TW，例如 2374)：只爬取 TWSE，絕不向 TPEx 發出無效請求，消除跨市場白等。
       - 上櫃標的 (.TWO，例如 6425)：只爬取 TPEx，絕不向 TWSE 發出無效請求。
    2. 防呆防錯原因（潛在風險註記）：
       - 【重要風險警告】：Yahoo Finance 係透過代號試錯判定 (.TW 失敗才換 .TWO)。
         若因網路逾時或快取殘缺，導致 full_ticker 市場別判定錯誤，此處的單邊分流將直接導致
         「上市被誤當上櫃、或上櫃被誤當上市」，致使官方爬蟲全數槓龜而無法取得法人籌碼！
       - 【保護機制】：一旦官方專屬分流查無資料時，程式自動發動「軌道二：FinMind API」作為備援
         補破網（FinMind 依股票代號自動通吃上市與上櫃），確保即便市場別誤判，依然 100% 順利還原法人籌碼。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.tpex.org.tw/"
    }

    if explicit_missing_dates is not None:
        sample_dates = list(explicit_missing_dates)
    elif start_date_exclusive:
        sample_dates = [d for d in df_dates if d.strftime('%Y-%m-%d') > start_date_exclusive]
    else:
        sample_dates = list(df_dates[-5:])

    if not sample_dates:
        return []

    records = []
    missing_dates = []

    def clean_val(v):
        try:
            return float(str(v).replace(",", "").strip()) / 1000.0
        except Exception:
            return 0.0

    # 判斷市場屬性 (若未傳入則預設先試 TWSE)
    is_tpex_only = bool(full_ticker and full_ticker.endswith(".TWO"))
    is_twse_only = bool(full_ticker and full_ticker.endswith(".TW"))

    # 軌道一：依市場別精確爬取
    for dt in sample_dates:
        if dt.weekday() >= 5:
            continue
        date_twse = dt.strftime('%Y%m%d')
        date_str = dt.strftime('%Y-%m-%d')
        found = False

        # 1. 爬上市 (TWSE) - 僅非上櫃標的執行
        if not is_tpex_only:
            url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_twse}&selectType=ALLBUT0999&response=json"
            try:
                res = requests.get(url_twse, headers=headers, timeout=1.2)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("stat") == "OK" and "data" in data:
                        for row in data["data"]:
                            if str(row[0]).strip() == pure_code:
                                f_net = clean_val(row[4])
                                t_net = clean_val(row[10])
                                d_net = clean_val(row[11])
                                records.append((date_str, f_net, t_net, d_net))
                                found = True
                                break
                        if found:
                            continue
            except Exception:
                pass

        # 2. 爬上櫃 (TPEx) - 僅非上市標的執行
        if not found and not is_twse_only:
            try:
                year_tw = dt.year - 1911
                date_tpex = f"{year_tw}/{dt.strftime('%m/%d')}"
                url_tpex = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_tpex}"
                res = requests.get(url_tpex, headers=headers, timeout=1.2)
                if res.status_code == 200:
                    data = res.json()
                    rows = data.get("aaData") or data.get("tables", [{}])[0].get("data", [])
                    if rows:
                        for row in rows:
                            if str(row[0]).strip() == pure_code:
                                num_cols = len(row)
                                f_net = clean_val(row[10]) if num_cols > 10 else clean_val(row[7])
                                t_net = clean_val(row[13]) if num_cols > 13 else clean_val(row[8])
                                if num_cols > 22:
                                    d_net = clean_val(row[22])
                                elif num_cols > 19:
                                    d_net = clean_val(row[16]) + clean_val(row[19])
                                else:
                                    d_net = clean_val(row[9])
                                
                                records.append((date_str, f_net, t_net, d_net))
                                found = True
                                break
            except Exception:
                pass

        if not found:
            missing_dates.append(date_str)

        time.sleep(0.01)

    # 軌道二：【重要備援機制】若專屬分流因判定錯誤未取到，由 FinMind API 全域精準補齊
    if missing_dates:
        try:
            query_start = min(missing_dates)
            url_fm = "https://api.finmindtrade.com/api/v4/data"
            p_fm = {
                "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id": pure_code,
                "start_date": query_start,
                "token": FINMIND_TOKEN
            }
            res_fm = requests.get(url_fm, params=p_fm, headers=headers, timeout=2.5)
            if res_fm.status_code == 200:
                fm_data = res_fm.json().get("data", [])
                if fm_data:
                    df_fm = pd.DataFrame(fm_data)
                    grouped = df_fm.groupby("date")
                    for d_str, g in grouped:
                        if d_str in missing_dates and not any(r[0] == d_str for r in records):
                            f_net, t_net, d_net = 0.0, 0.0, 0.0
                            for _, r in g.iterrows():
                                name = str(r.get("name", ""))
                                diff_val = (float(r.get("buy", 0) or 0) - float(r.get("sell", 0) or 0)) / 1000.0
                                if "Foreign_Investor" in name or "外資" in name:
                                    f_net += diff_val
                                elif "Investment_Trust" in name or "投信" in name:
                                    t_net += diff_val
                                elif "Dealer" in name or "自營商" in name:
                                    d_net += diff_val
                            records.append((d_str, f_net, t_net, d_net))
        except Exception:
            pass

    records.sort(key=lambda x: x[0])
    return records


def fetch_margin_short_data(pure_code: str, df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    """擷取融資融券買賣超與餘額資料 (FinMind API 架構)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    if start_date_exclusive:
        margin_query_start = (pd.to_datetime(start_date_exclusive) + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        margin_query_start = (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d') if len(df_dates) > 0 else (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

    records_ms = []
    try:
        url_ms = "https://api.finmindtrade.com/api/v4/data"
        p_ms = {
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": pure_code,
            "start_date": margin_query_start,
            "token": FINMIND_TOKEN
        }
        res_ms = requests.get(url_ms, params=p_ms, headers=headers, timeout=4)
        if res_ms.status_code == 200:
            data_ms = res_ms.json().get('data', [])
            if data_ms:
                ms_df = pd.DataFrame(data_ms)
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

                    records_ms.append((
                        r['date'],
                        m_diff,
                        s_diff,
                        m_bal,
                        s_bal
                    ))
    except Exception:
        pass

    return records_ms


def fetch_tdcc_holding_data(pure_code: str) -> list:
    """擷取集保大戶持股分級資料 (集保結算所 TDCC 官方來源 - 最新單週)"""
    records = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, headers=headers, timeout=6)
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


def fetch_tdcc_holding_history(pure_code: str, weeks: int = 6) -> list:
    """擷取集保大戶近 N 週歷史分級 (支援歷史回補)"""
    all_records = []
    latest_recs = fetch_tdcc_holding_data(pure_code)
    if latest_recs:
        all_records.extend(latest_recs)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    }
    try:
        session = requests.Session()
        main_url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
        r_main = session.get(main_url, headers=headers, timeout=5)
        if r_main.status_code == 200:
            soup = BeautifulSoup(r_main.text, "html.parser")
            date_select = soup.find("select", {"id": "scaDates"}) or soup.find("select", {"name": "scaDate"})
            avail_dates = []
            if date_select:
                for opt in date_select.find_all("option"):
                    val = opt.get("value", "").strip()
                    if val and val.isdigit() and len(val) == 8:
                        avail_dates.append(val)

            target_dates = avail_dates[:max(1, int(weeks))]
            for dt_val in target_dates:
                try:
                    target_d_str = datetime.strptime(dt_val, '%Y%m%d').strftime('%Y-%m-%d')
                    if any(r[0] == target_d_str for r in all_records):
                        continue

                    post_url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
                    post_data = {
                        "scaDates": dt_val,
                        "scaDate": dt_val,
                        "StockNo": pure_code,
                        "stockNo": pure_code,
                        "btnSubmit": "查詢"
                    }
                    r_sub = session.post(post_url, data=post_data, headers=headers, timeout=4)
                    if r_sub.status_code == 200:
                        sub_soup = BeautifulSoup(r_sub.text, "html.parser")
                        rows = sub_soup.find_all("tr")
                        for row in rows:
                            cols = [td.text.replace(",", "").strip() for td in row.find_all("td")]
                            if len(cols) >= 5 and cols[0].isdigit():
                                lvl = int(cols[0])
                                if 1 <= lvl <= 15:
                                    pct = float(cols[4].replace("%", ""))
                                    all_records.append((target_d_str, lvl, pct))
                    time.sleep(0.08)
                except Exception:
                    continue
    except Exception:
        pass

    return all_records
