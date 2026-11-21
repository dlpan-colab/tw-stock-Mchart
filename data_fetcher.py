"""
data_fetcher.py - 整合技術與籌碼資料擷取模組
(支援含英文後綴台股ETF + TWSE/TPEx官方日K即時補齊 + 大盤加權^TWII與櫃買^TWOII資券與融資金額(億)擷取 + 雲端增量累積分點引擎 + 集保官網qryStock動態Token多週歷史查詢與id=1-5批次分離 + 賣超負值正規化 + 操作儀錶板盤中報價版 + 富邦10欄並排表格與精準單日分點統計/明細5欄修正版 + 全市場歷史分點跨日去重加速批次增補引擎 + 全市含上櫃資券/法人/大戶指定基準日區間批次增補引擎版)
版本: 202611220045
"""
import os
import io
import re
import glob
import json
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202611220045"

from storage import (
    StockChipStorage, COMMON_STOCK_NAMES, load_stock_names_dict,
    load_stock_history, get_stock_chinese_name, is_tw_stock_or_etf,
    sync_db_push
)

FINMIND_TOKEN = ""

MDJ_BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"
MDJ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{MDJ_BASE_DOMAIN}/"
}

GOV_BROKER_PREFIXES = (
    "合庫", "合作金庫", "土銀", "土地銀行", "台銀", "臺銀", "台灣銀行", "臺灣銀行",
    "台企", "臺企", "台灣企銀", "臺灣企銀", "彰銀", "彰化銀行", "第一金", "兆豐", "華南永昌"
)


def fetch_stock_name(pure_code: str) -> str:
    """取得股票中文名稱 (優先查字典/快取，無則爬蟲)"""
    return get_stock_chinese_name(pure_code)


def _fetch_tw_official_month_k(pure_code: str, full_ticker: str = None) -> pd.DataFrame:
    """
    【修訂說明 2026-11-14】向台灣證交所(TWSE STOCK_DAY)或櫃買中心(TPEx)擷取當月完整四價日K線，
    補齊 Yahoo Finance 偶發延遲更新的最新交易日（含開、高、低、收、成交量）。
    """
    code = str(pure_code or "").strip().upper()
    if not is_tw_stock_or_etf(code):
        return pd.DataFrame()

    now_tw = datetime.utcnow() + timedelta(hours=8)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    rows = []

    def parse_float(v):
        s = str(v or "").replace(",", "").strip()
        if s in ("", "-", "--", "—", "X"):
            return None
        try:
            return float(s)
        except Exception:
            return None

    is_tpex_only = bool(full_ticker and full_ticker.endswith(".TWO"))
    is_twse_only = bool(full_ticker and full_ticker.endswith(".TW"))

    # 1. 上市 TWSE STOCK_DAY（含上市個股與 00632R 等上市 ETF）
    if not is_tpex_only:
        date_param = now_tw.strftime("%Y%m01")
        url_twse = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_param}&stockNo={code}"
        try:
            res = requests.get(url_twse, headers=headers, timeout=4)
            if res.status_code == 200:
                js = res.json()
                if js.get("stat") == "OK" and js.get("data"):
                    for r in js["data"]:
                        if len(r) < 7:
                            continue
                        d_parts = str(r[0]).strip().split("/")
                        if len(d_parts) != 3:
                            continue
                        y = int(d_parts[0]) + 1911
                        d_iso = f"{y:04d}-{int(d_parts[1]):02d}-{int(d_parts[2]):02d}"
                        vol_shares = parse_float(r[1])
                        o_p = parse_float(r[3])
                        h_p = parse_float(r[4])
                        l_p = parse_float(r[5])
                        c_p = parse_float(r[6])
                        if None not in (o_p, h_p, l_p, c_p) and vol_shares and vol_shares > 0:
                            rows.append((pd.to_datetime(d_iso), o_p, h_p, l_p, c_p, vol_shares))
        except Exception:
            pass

    # 2. 上櫃 TPEx daily_trading_info（若上市查無且非限定上市）
    if not rows and not is_twse_only:
        roc_ym = f"{now_tw.year - 1911}/{now_tw.month:02d}"
        url_tpex = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d={roc_ym}&stkno={code}"
        try:
            res_t = requests.get(url_tpex, headers=headers, timeout=4)
            if res_t.status_code == 200:
                js_t = res_t.json()
                aa = js_t.get("aaData") or js_t.get("tables", [{}])[0].get("data", [])
                for r in aa:
                    if len(r) < 7:
                        continue
                    d_parts = str(r[0]).strip().split("/")
                    if len(d_parts) != 3:
                        continue
                    y = int(d_parts[0]) + 1911
                    d_iso = f"{y:04d}-{int(d_parts[1]):02d}-{int(d_parts[2]):02d}"
                    vol_k = parse_float(r[1])
                    o_p = parse_float(r[3])
                    h_p = parse_float(r[4])
                    l_p = parse_float(r[5])
                    c_p = parse_float(r[6])
                    if None not in (o_p, h_p, l_p, c_p) and vol_k and vol_k > 0:
                        rows.append((pd.to_datetime(d_iso), o_p, h_p, l_p, c_p, vol_k * 1000.0))
        except Exception:
            pass

    if not rows:
        return pd.DataFrame()
    df_off = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df_off.set_index("Date", inplace=True)
    df_off = df_off[~df_off.index.duplicated(keep="last")].sort_index()
    return df_off


def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: str = None, force_refresh: bool = False):
    """
    自本地 SQLite 或官方 API / Yahoo Finance 擷取歷史日 K 線資料。
    支援台股個股及含英文後綴之 ETF（如 00632R、00664R、00676R、00631L），並以證交所/櫃買官方日K補齊延遲資料。
    """
    raw_str = str(raw_ticker).strip()
    if not raw_str:
        return None
    pure_code = raw_str.upper()
    is_index = pure_code.startswith("^")
    is_tw_etf_or_stk = is_tw_stock_or_etf(pure_code)

    if pure_code == "^TWII":
        target_ticker = "^TWII"
        full_ticker = "^TWII"
    elif pure_code == "^TWOII":
        target_ticker = "006201.TWO"
        full_ticker = "^TWOII"
    elif is_index:
        target_ticker = pure_code
        full_ticker = pure_code
    elif is_tw_etf_or_stk:
        target_ticker = f"{pure_code}.TW"
        full_ticker = f"{pure_code}.TW"
    else:
        target_ticker = pure_code
        full_ticker = pure_code

    storage = StockChipStorage(pure_code)
    db_df = storage.load_daily_k_df()
    last_k_date = storage.get_latest_daily_k_date()
    shares_outstanding = None

    ticker = yf.Ticker(target_ticker)
    if is_tw_etf_or_stk:
        try:
            shares_outstanding = ticker.info.get("sharesOutstanding")
        except Exception:
            pass

    fetch_period = period if db_df.empty or not last_k_date else "5d"
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
        elif is_tw_etf_or_stk and target_ticker.endswith(".TW"):
            alt_ticker = f"{pure_code}.TWO"
            try:
                t_alt = yf.Ticker(alt_ticker)
                shares_outstanding = t_alt.info.get("sharesOutstanding")
                df_new = t_alt.history(period=fetch_period)
                if df_new is not None and not df_new.empty:
                    full_ticker = alt_ticker
            except Exception:
                pass

    combined = db_df.copy() if not db_df.empty else pd.DataFrame()
    if df_new is not None and not df_new.empty:
        if df_new.index.tz is not None:
            df_new.index = df_new.index.tz_localize(None)
        valid_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df_new.columns]
        if valid_cols:
            df_new = df_new.dropna(subset=valid_cols)
        if not is_index and 'Volume' in df_new.columns:
            df_new = df_new[df_new['Volume'] > 0]

        if not combined.empty and not force_refresh:
            combined = pd.concat([combined, df_new])
            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
        else:
            combined = df_new.sort_index()

    # 若為台股個股/ETF，檢查最新交易日是否落後於台灣最近平日收盤日，若落後則向證交所/櫃買補齊當月完整日K
    if is_tw_etf_or_stk and not combined.empty:
        now_tw = datetime.utcnow() + timedelta(hours=8)
        expected_latest = now_tw.date()
        if expected_latest.weekday() == 5:
            expected_latest -= timedelta(days=1)
        elif expected_latest.weekday() == 6:
            expected_latest -= timedelta(days=2)
        elif now_tw.hour < 14:
            expected_latest -= timedelta(days=1)
        while expected_latest.weekday() >= 5:
            expected_latest -= timedelta(days=1)

        latest_in_df = combined.index[-1].date()
        if force_refresh or latest_in_df < expected_latest:
            df_official = _fetch_tw_official_month_k(pure_code, full_ticker=full_ticker)
            if df_official is not None and not df_official.empty:
                combined = pd.concat([combined, df_official])
                combined = combined[~combined.index.duplicated(keep='last')].sort_index()

    if not combined.empty:
        storage.save_daily_k_df(combined)
        return combined, full_ticker, shares_outstanding
    return None


def sync_chip_data(
    pure_code: str,
    df_dates: pd.DatetimeIndex,
    status_placeholder=None,
    force_refresh: bool = False,
    full_ticker: str = None
):
    """
    智慧增量同步三大法人、資券與集保大戶（支援台股個股、含英文後綴之 ETF，以及大盤加權指數 ^TWII 與櫃買指數 ^TWOII 資券與融資金額）。
    """
    pure_code = str(pure_code).strip().upper()
    storage = StockChipStorage(pure_code)

    # 【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
    # 修改目的：開放大盤加權指數 ^TWII（上市）與櫃買指數 ^TWOII（上櫃）同步全市場每日資券與融資金額（億元）。
    # 防呆防錯原因：若舊版資料庫尚無 margin_money_bal 數值（全為 0），自動重抓補齊融資金額歷史。
    if pure_code in ("^TWII", "^TWOII"):
        if len(df_dates) == 0:
            return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        last_margin_date = storage.get_latest_margin_date()
        latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')
        now_tw = datetime.utcnow() + timedelta(hours=8)
        now_tw_date_str = now_tw.strftime('%Y-%m-%d')

        existing_ms_df = storage.load_margin_df()
        missing_money_col = (
            existing_ms_df.empty
            or "margin_money_bal" not in existing_ms_df.columns
            or (existing_ms_df["margin_money_bal"].fillna(0) == 0).all()
        )
        should_fetch_margin = force_refresh or missing_money_col
        if not should_fetch_margin:
            if not last_margin_date:
                should_fetch_margin = True
            elif last_margin_date < latest_trade_date_str:
                if now_tw_date_str == latest_trade_date_str and now_tw.hour < 21:
                    should_fetch_margin = False
                else:
                    should_fetch_margin = True

        if should_fetch_margin:
            start_filter = None if (force_refresh or missing_money_col) else last_margin_date
            if pure_code == "^TWII":
                margin_records = fetch_twse_total_margin_data(df_dates, start_date_exclusive=start_filter)
            else:
                margin_records = fetch_tpex_total_margin_data(df_dates, start_date_exclusive=start_filter)
            if margin_records:
                storage.save_margin_data(margin_records)

        if status_placeholder:
            status_placeholder.empty()
        return (pd.DataFrame(), storage.load_margin_df(), pd.DataFrame())

    if pure_code.startswith("^") or not is_tw_stock_or_etf(pure_code):
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    if len(df_dates) == 0:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    last_margin_date = storage.get_latest_margin_date()
    last_holding_date = storage.get_latest_holding_date()
    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')
    now_tw = datetime.utcnow() + timedelta(hours=8)
    now_tw_date_str = now_tw.strftime('%Y-%m-%d')

    existing_inst_df = storage.load_institutional_df()
    existing_dates = set(existing_inst_df['date'].dt.strftime('%Y-%m-%d')) if not existing_inst_df.empty else set()
    recent_k_dates = [d.strftime('%Y-%m-%d') for d in df_dates[-30:]]
    missing_inst_dates = [d for d in recent_k_dates if d not in existing_dates]
    if now_tw_date_str in missing_inst_dates and now_tw.hour < 16:
        missing_inst_dates.remove(now_tw_date_str)

    should_fetch_inst = force_refresh or (len(missing_inst_dates) > 0)

    should_fetch_margin = force_refresh
    if not should_fetch_margin:
        if not last_margin_date:
            should_fetch_margin = True
        elif last_margin_date < latest_trade_date_str:
            if now_tw_date_str == latest_trade_date_str and now_tw.hour < 21:
                should_fetch_margin = False
            else:
                should_fetch_margin = True

    should_fetch_holding = force_refresh
    if not should_fetch_holding:
        if not last_holding_date:
            should_fetch_holding = True
        else:
            diff_days = (now_tw - pd.to_datetime(last_holding_date)).days
            is_weekend_publish = (now_tw.weekday() == 4 and now_tw.hour >= 20) or (now_tw.weekday() in [5, 6])
            if diff_days >= 7:
                should_fetch_holding = True
            elif is_weekend_publish and diff_days >= 1:
                should_fetch_holding = True

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

    is_tpex_only = bool(full_ticker and full_ticker.endswith(".TWO"))
    is_twse_only = bool(full_ticker and full_ticker.endswith(".TW"))

    for dt in sample_dates:
        if dt.weekday() >= 5:
            continue
        date_twse = dt.strftime('%Y%m%d')
        date_str = dt.strftime('%Y-%m-%d')
        found = False

        if not is_tpex_only:
            url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_twse}&selectType=ALLBUT0999&response=json"
            try:
                res = requests.get(url_twse, headers=headers, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("stat") == "OK" and "data" in data:
                        for row in data["data"]:
                            if str(row[0]).strip().upper() == pure_code:
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

        if not found and not is_twse_only:
            try:
                year_tw = dt.year - 1911
                date_tpex = f"{year_tw}/{dt.strftime('%m/%d')}"
                url_tpex = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_tpex}"
                res = requests.get(url_tpex, headers=headers, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    rows = data.get("aaData") or data.get("tables", [{}])[0].get("data", [])
                    if rows:
                        for row in rows:
                            if str(row[0]).strip().upper() == pure_code:
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


def fetch_twse_total_margin_data(df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    """
    【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
    1. 修改目的：擷取上市大盤（^TWII）全市場每日融資/融券增減張數與餘額，以及上市融資金額增減與餘額（換算為億元）
       （主資料源：FinMind TaiwanStockTotalMarginPurchaseShortSale；備援補齊最新交易日：證交所 MI_MARGN）。
    2. 防呆防錯原因：FinMind MarginPurchaseMoney 單位為「元」（除以 1e8 轉為億元），證交所 MI_MARGN 融資金額(千元)單位為「千元」（除以 1e5 轉為億元），統一以「億元」存入 margin_short 資料表。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    if start_date_exclusive:
        query_start = (pd.to_datetime(start_date_exclusive) + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        query_start = (
            (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d')
            if len(df_dates) > 0
            else (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        )

    rec_map = {}
    try:
        url_fm = "https://api.finmindtrade.com/api/v4/data"
        p_fm = {
            "dataset": "TaiwanStockTotalMarginPurchaseShortSale",
            "start_date": query_start,
            "token": FINMIND_TOKEN
        }
        res_fm = requests.get(url_fm, params=p_fm, headers=headers, timeout=6)
        if res_fm.status_code == 200:
            data_fm = res_fm.json().get("data", [])
            if data_fm:
                df_raw = pd.DataFrame(data_fm)
                piv_today = df_raw.pivot_table(index="date", columns="name", values="TodayBalance", aggfunc="last")
                piv_yes = df_raw.pivot_table(index="date", columns="name", values="YesBalance", aggfunc="last")
                for d_str in piv_today.index:
                    m_today = float(piv_today.loc[d_str, "MarginPurchase"]) if "MarginPurchase" in piv_today.columns and pd.notna(piv_today.loc[d_str, "MarginPurchase"]) else 0.0
                    m_yes = float(piv_yes.loc[d_str, "MarginPurchase"]) if "MarginPurchase" in piv_yes.columns and pd.notna(piv_yes.loc[d_str, "MarginPurchase"]) else m_today
                    s_today = float(piv_today.loc[d_str, "ShortSale"]) if "ShortSale" in piv_today.columns and pd.notna(piv_today.loc[d_str, "ShortSale"]) else 0.0
                    s_yes = float(piv_yes.loc[d_str, "ShortSale"]) if "ShortSale" in piv_yes.columns and pd.notna(piv_yes.loc[d_str, "ShortSale"]) else s_today
                    mm_today = (float(piv_today.loc[d_str, "MarginPurchaseMoney"]) / 1e8) if "MarginPurchaseMoney" in piv_today.columns and pd.notna(piv_today.loc[d_str, "MarginPurchaseMoney"]) else 0.0
                    mm_yes = (float(piv_yes.loc[d_str, "MarginPurchaseMoney"]) / 1e8) if "MarginPurchaseMoney" in piv_yes.columns and pd.notna(piv_yes.loc[d_str, "MarginPurchaseMoney"]) else mm_today
                    rec_map[str(d_str)] = (
                        str(d_str),
                        m_today - m_yes,
                        s_today - s_yes,
                        m_today,
                        s_today,
                        mm_today - mm_yes,
                        mm_today
                    )
    except Exception:
        pass

    # 若最新交易日尚未出現在 FinMind，向證交所 MI_MARGN 補齊單日全市場信用交易統計
    if len(df_dates) > 0:
        latest_d_str = df_dates[-1].strftime('%Y-%m-%d')
        if latest_d_str not in rec_map:
            try:
                d_compact = df_dates[-1].strftime('%Y%m%d')
                url_twse_ms = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d_compact}&selectType=MS&response=json"
                res_t = requests.get(url_twse_ms, headers=headers, timeout=4)
                if res_t.status_code == 200:
                    js_t = res_t.json()
                    if js_t.get("stat") == "OK":
                        m_yes, m_today, s_yes, s_today = 0.0, 0.0, 0.0, 0.0
                        mm_yes_yi, mm_today_yi = 0.0, 0.0
                        for tbl in js_t.get("tables", []):
                            for row in tbl.get("data", []):
                                if len(row) >= 6:
                                    item_name = str(row[0]).strip()
                                    yes_v = float(str(row[4]).replace(",", "").strip() or 0)
                                    tod_v = float(str(row[5]).replace(",", "").strip() or 0)
                                    if "融資(交易單位)" in item_name:
                                        m_yes, m_today = yes_v, tod_v
                                    elif "融券(交易單位)" in item_name:
                                        s_yes, s_today = yes_v, tod_v
                                    elif "融資金額(千元)" in item_name:
                                        mm_yes_yi, mm_today_yi = yes_v / 1e5, tod_v / 1e5
                        if m_today > 0 or s_today > 0:
                            rec_map[latest_d_str] = (
                                latest_d_str,
                                m_today - m_yes,
                                s_today - s_yes,
                                m_today,
                                s_today,
                                mm_today_yi - mm_yes_yi,
                                mm_today_yi
                            )
            except Exception:
                pass

    return [rec_map[k] for k in sorted(rec_map.keys())]


def fetch_tpex_total_margin_data(df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    """
    【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
    1. 修改目的：擷取櫃買指數（^TWOII）全市場彙總信用交易統計（主資料源：嗨投資 https://histock.tw/stock/three.aspx?m=mg&no=TWOI），
       直接取得彙總表欄位：日期、融資餘額(億)、融資增加(億)、融券餘額(張)、融券增加(張)。
    2. 防呆防錯原因：
       - 嚴格區分「張數」與「金額」：上櫃全市場彙總僅提供融券張數（存入 short_diff / short_bal，單位：張）與融資金額（存入 margin_money_diff / margin_money_bal，單位：億元），
         上櫃全市場無融資總張數，故 margin_diff / margin_bal 明確設為 0.0，絕不將金額誤充當張數。
       - 兼容 HiStock 日期格式（YYYY/MM/DD、MM/DD 搭配年份推斷、或民國年 YYY/MM/DD）。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://histock.tw/"
    }
    url_otc = "https://histock.tw/stock/three.aspx?m=mg&no=TWOI"

    def parse_num(txt):
        s = str(txt or "").replace(",", "").replace("+", "").strip()
        if s in ("", "-", "--", "—", "N/A"):
            return 0.0
        try:
            return float(s)
        except Exception:
            return 0.0

    # 建立 df_dates 之「月-日」到完整 YYYY-MM-DD 的對照，兼容表格只顯示 MM/DD 的情況
    md_to_iso = {}
    valid_iso_set = set()
    for d in df_dates:
        iso_s = d.strftime("%Y-%m-%d")
        valid_iso_set.add(iso_s)
        md_to_iso[d.strftime("%m/%d")] = iso_s

    rec_map = {}
    try:
        res = requests.get(url_otc, headers=headers, timeout=8)
        if res.status_code != 200 or not res.text:
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        for tr in soup.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if len(cells) < 5:
                continue
            raw_d = cells[0].strip()
            iso_date = None
            parts = raw_d.replace("-", "/").split("/")
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
                y_num = int(parts[0])
                if y_num < 1911:
                    y_num += 1911
                iso_date = f"{y_num:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            elif len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                md_key = f"{int(parts[0]):02d}/{int(parts[1]):02d}"
                iso_date = md_to_iso.get(md_key)

            if not iso_date:
                continue
            if valid_iso_set and iso_date not in valid_iso_set:
                continue
            if start_date_exclusive and iso_date <= start_date_exclusive:
                continue

            # 欄位順序：日期 | 融資餘額(億) | 融資增加(億) | 融券餘額(張) | 融券增加(張) | 價格 | 比例 | 成交量(億)
            mm_bal_yi = parse_num(cells[1])
            mm_diff_yi = parse_num(cells[2])
            s_bal_sheets = parse_num(cells[3])
            s_diff_sheets = parse_num(cells[4])

            rec_map[iso_date] = (
                iso_date,
                0.0,            # margin_diff（上櫃全市場彙總無融資張數）
                s_diff_sheets,  # short_diff（融券增減，張）
                0.0,            # margin_bal（上櫃全市場彙總無融資張數）
                s_bal_sheets,   # short_bal（融券餘額，張）
                mm_diff_yi,     # margin_money_diff（融資金額增減，億元）
                mm_bal_yi       # margin_money_bal（融資金額餘額，億元）
            )
    except Exception:
        pass

    return [rec_map[k] for k in sorted(rec_map.keys())]


def fetch_margin_short_data(pure_code: str, df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if start_date_exclusive:
        margin_query_start = (pd.to_datetime(start_date_exclusive) + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        margin_query_start = (
            (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d')
            if len(df_dates) > 0
            else (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        )

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


def fetch_tdcc_holding_history(pure_code: str, weeks: int = 15) -> list:
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 捨棄免費版無授權之 FinMind TaiwanStockHoldingSharesPer，改採集保官網歷史查詢介面
         （https://www.tdcc.com.tw/portal/zh/smWeb/qryStock），一次比對本地資料庫缺失週別並補齊約 15 週
         （官方下拉選單提供之所有可用公告週別）1～15 級股權分散表歷史資料。
       - 因應集保官網 Struts SYNCHRONIZER_TOKEN 單次防重送驗證機制，每次 POST 回應後立即從回應頁面
         重新擷取最新核發之表單隱藏欄位（SYNCHRONIZER_TOKEN）供下一週查詢使用，解決第 2 週起被擋下之問題。
    2. 防呆防錯原因：
       - 若任一週 POST 回應未包含有效之 SYNCHRONIZER_TOKEN 或連線異常，下一輪自動執行 GET 重新取得最新權杖，
         確保連續多週歷史查詢不中斷。
       - 嚴格限定表格首欄為純數字 1 <= level <= 15（排除第 16 差異數與第 17 合計列）。
    """
    code = str(pure_code or "").strip().upper()
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
        return []

    url_tdcc = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": url_tdcc,
        "Origin": "https://www.tdcc.com.tw",
    }

    def _extract_hidden_inputs(soup_obj: BeautifulSoup) -> dict:
        fields = {}
        for inp in soup_obj.find_all("input"):
            name = inp.get("name")
            if name:
                fields[name] = inp.get("value", "")
        return fields

    existing_weeks = set()
    try:
        storage = StockChipStorage(code)
        df_exist = storage.load_holding_df()
        if df_exist is not None and not df_exist.empty and "date" in df_exist.columns:
            existing_weeks = set(pd.to_datetime(df_exist["date"]).dt.strftime("%Y%m%d").tolist())
    except Exception:
        pass

    records_h = []
    try:
        sess = requests.Session()
        res_get = sess.get(url_tdcc, headers=headers, timeout=8)
        if res_get.status_code != 200:
            return []

        soup_get = BeautifulSoup(res_get.text, "html.parser")
        current_payload = _extract_hidden_inputs(soup_get)

        avail_dates = []
        for opt in soup_get.find_all("option"):
            val = str(opt.get("value", "")).strip()
            if val.isdigit() and len(val) == 8:
                avail_dates.append(val)

        if not avail_dates:
            return []

        max_w = max(1, int(weeks or 15))
        target_dates = avail_dates[:max_w]
        missing_dates = [d for d in target_dates if d not in existing_weeks]
        if not missing_dates:
            return []

        for d_str in missing_dates:
            # 【防呆防錯】若上一輪未取得有效權杖，重新 GET 補齊最新 SYNCHRONIZER_TOKEN
            if not current_payload.get("SYNCHRONIZER_TOKEN"):
                try:
                    res_reget = sess.get(url_tdcc, headers=headers, timeout=8)
                    if res_reget.status_code == 200:
                        current_payload = _extract_hidden_inputs(BeautifulSoup(res_reget.text, "html.parser"))
                except Exception:
                    current_payload = {}

            payload = current_payload.copy()
            payload.update({
                "scaDate": d_str,
                "sqlMethod": "StockNo",
                "stockNo": code,
                "stockName": "",
                "sub": "查詢"
            })
            try:
                res_post = sess.post(url_tdcc, data=payload, headers=headers, timeout=8)
                if res_post.status_code != 200:
                    current_payload = {}
                    continue

                soup_post = BeautifulSoup(res_post.text, "html.parser")
                # 【修訂重點】立即更新下一輪要帶入的隱藏欄位（最新核發之 SYNCHRONIZER_TOKEN）
                next_inputs = _extract_hidden_inputs(soup_post)
                current_payload = next_inputs if next_inputs.get("SYNCHRONIZER_TOKEN") else {}

                iso_d = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                for tbl in soup_post.find_all("table"):
                    if "1,000,001" not in tbl.get_text():
                        continue
                    for tr in tbl.find_all("tr"):
                        cols = [td.get_text(strip=True).replace(",", "") for td in tr.find_all("td")]
                        if len(cols) >= 5 and cols[0].isdigit():
                            lvl = int(cols[0])
                            if 1 <= lvl <= 15:
                                try:
                                    pct = float(cols[4].replace("%", "").strip())
                                    records_h.append((iso_d, lvl, pct))
                                except Exception:
                                    continue
                    break
            except Exception:
                current_payload = {}
            time.sleep(0.25)
    except Exception:
        pass

    return records_h


def fetch_tdcc_holding_data(pure_code: str) -> list:
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    1. 修改目的：單一個股查詢時直接呼叫集保官網歷史查詢（fetch_tdcc_holding_history），
       一次補齊該個股所有缺失之歷史週別（約 15 週）1～15 級股權分散表比例。
    2. 防呆防錯原因：嚴格過濾 1 <= level <= 15，排除第 16（差異數）與第 17（合計）列，防止比例重複加總。
    """
    hist_recs = fetch_tdcc_holding_history(pure_code, weeks=15)
    if not hist_recs:
        return []
    return [(d, lvl, pct) for (d, lvl, pct) in hist_recs if 1 <= lvl <= 15]


def batch_fetch_and_save_latest_tdcc_holding(target_codes: list = None) -> dict:
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    1. 修改目的：提供【上市/上櫃】批次作業，下載集保官方開放資料網最新單週全市場總表（id=1-5），
       寫入已收錄個股之 data_{code}.db（shareholding_distribution 資料表）並同步雲端。
    2. 防呆防錯原因：
       - 移除無效之 FinMind 免費版集保備援迴圈，避免連線失敗時逐檔空轉等待。
       - 僅保留 1 <= level <= 15 級距，嚴格排除第 16（其他）、17（合計）列。
       - 僅針對系統已建立之台股個股/ETF（排除 ^ 開頭指數）寫入，避免無差別產生數千個無效 .db 檔。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    tdcc_urls = [
        "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
        "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5",
    ]

    candidate_set = set()
    if target_codes:
        for c in target_codes:
            cu = str(c or "").strip().upper()
            if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                candidate_set.add(cu)
    else:
        for item in load_stock_history():
            cu = str(item.get("code", "")).strip().upper()
            if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                candidate_set.add(cu)
        for p in glob.glob(os.path.join(".", "data_*.db")):
            cu = os.path.basename(p).replace("data_", "").replace(".db", "").strip().upper()
            if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                candidate_set.add(cu)

    if not candidate_set:
        return {"ok": False, "msg": "目前無已建立之台股個股/ETF 資料庫可更新。"}

    df_od = None
    for u in tdcc_urls:
        try:
            res = requests.get(u, headers=headers, timeout=12)
            if res.status_code == 200 and len(res.content) > 500:
                df_od = pd.read_csv(io.BytesIO(res.content), dtype=str)
                if df_od is not None and not df_od.empty:
                    break
        except Exception:
            continue

    if df_od is None or df_od.empty:
        return {"ok": False, "msg": "集保開放資料網（id=1-5）暫時無回應，請稍後再試。"}

    cols = list(df_od.columns)
    date_col = next((c for c in cols if "日期" in c or "Date" in c), cols[0])
    code_col = next((c for c in cols if "代號" in c or "Code" in c), cols[1])
    lvl_col = next((c for c in cols if "持股分級" in c or "Level" in c), cols[2])
    pct_col = next((c for c in cols if "占集保庫存數比例" in c or "比例" in c or "Percent" in c), cols[-1])

    df_od[code_col] = df_od[code_col].astype(str).str.strip().str.upper()
    df_sub = df_od[df_od[code_col].isin(candidate_set)].copy()
    if df_sub.empty:
        return {"ok": False, "msg": "集保最新開放資料中未比對到已收錄個股。"}

    grouped_records = {}
    latest_date_str = ""
    for _, row in df_sub.iterrows():
        c_code = str(row[code_col]).strip().upper()
        raw_d = str(row[date_col]).strip().replace("-", "").replace("/", "")
        if len(raw_d) != 8 or not raw_d.isdigit():
            continue
        iso_d = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:8]}"
        if iso_d > latest_date_str:
            latest_date_str = iso_d
        try:
            lvl = int(float(str(row[lvl_col]).strip()))
            if not (1 <= lvl <= 15):
                continue
            pct = float(str(row[pct_col]).replace(",", "").replace("%", "").strip())
        except Exception:
            continue
        grouped_records.setdefault(c_code, []).append((iso_d, lvl, pct))

    updated_stocks = 0
    for c_code, recs in grouped_records.items():
        if recs:
            try:
                st_db = StockChipStorage(c_code)
                st_db.save_holding_data(recs)
                updated_stocks += 1
            except Exception:
                continue

    return {
        "ok": updated_stocks > 0,
        "date": latest_date_str,
        "updated_count": updated_stocks,
        "msg": f"已自集保開放資料網補齊 {latest_date_str} 最新週集保分級（共 {updated_stocks} 檔個股/ETF）。"
    }


def fetch_dashboard_watchlist_rows(history_list: list) -> list:
    """
    【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
    1. 修改目的：為「📊 操作儀錶板」擷取自選／查詢歷史清單之最新成交價、成交量(張)、5日均線、20日均線與市場別。
    2. 防呆防錯原因：
       - 過濾排除 ^ 開頭指數，僅顯示台股個股與含英文後綴之 ETF（如 00632R）；
       - 優先結合本地 SQLite 歷史收盤序列與 Yahoo Finance 盤中即時報價（fast_info / 1d history），確保盤中與盤後均能精準計算 MA5 / MA20 多空燈號，且絕不更動原清單排序。
    """
    if not history_list:
        return []

    rows = []
    for item in history_list:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
            continue

        c_name = str(item.get("name", "")).strip()
        if not c_name or c_name == code:
            c_name = get_stock_chinese_name(code)

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()

        market_lbl = "上市"
        yf_symbol = f"{code}.TW"
        if not df_k.empty:
            pass

        # 嘗試以 Yahoo Finance 取得最新即時/當日價格與確認市場別 (.TW / .TWO)
        live_price = None
        live_vol_sheets = None
        live_date_str = None
        found_yf = False
        for suffix, m_lbl in ((".TW", "上市"), (".TWO", "上櫃")):
            try:
                t_obj = yf.Ticker(f"{code}{suffix}")
                df_1d = t_obj.history(period="5d")
                if df_1d is not None and not df_1d.empty:
                    if df_1d.index.tz is not None:
                        df_1d.index = df_1d.index.tz_localize(None)
                    df_1d = df_1d.dropna(subset=["Close"])
                    if not df_1d.empty:
                        found_yf = True
                        market_lbl = m_lbl
                        yf_symbol = f"{code}{suffix}"
                        last_row = df_1d.iloc[-1]
                        live_price = float(last_row["Close"])
                        live_vol_sheets = float(last_row.get("Volume", 0) or 0) / 1000.0
                        live_date_str = df_1d.index[-1].strftime("%Y-%m-%d")

                        if not df_k.empty:
                            df_k = pd.concat([df_k, df_1d[["Open", "High", "Low", "Close", "Volume"]]])
                            df_k = df_k[~df_k.index.duplicated(keep="last")].sort_index()
                        else:
                            df_k = df_1d[["Open", "High", "Low", "Close", "Volume"]].sort_index()
                        break
            except Exception:
                continue

        if not found_yf and df_k.empty:
            k_res = fetch_stock_daily_k(code, period="3mo", force_refresh=False)
            if k_res and k_res[0] is not None and not k_res[0].empty:
                df_k = k_res[0]
                if str(k_res[1]).endswith(".TWO"):
                    market_lbl = "上櫃"

        if df_k.empty:
            rows.append({
                "code": code,
                "name": c_name,
                "market": market_lbl,
                "price": None,
                "vol_sheets": None,
                "ma5": None,
                "ma20": None,
                "trade_date": "-"
            })
            continue

        closes = df_k["Close"].dropna()
        last_close = live_price if live_price is not None else float(closes.iloc[-1])
        last_vol = live_vol_sheets if live_vol_sheets is not None else (float(df_k["Volume"].iloc[-1]) / 1000.0)
        last_dt = live_date_str if live_date_str else df_k.index[-1].strftime("%Y-%m-%d")
        ma5_val = float(closes.tail(5).mean()) if len(closes) >= 5 else None
        ma20_val = float(closes.tail(20).mean()) if len(closes) >= 20 else None

        rows.append({
            "code": code,
            "name": c_name,
            "market": market_lbl,
            "price": last_close,
            "vol_sheets": last_vol,
            "ma5": ma5_val,
            "ma20": ma20_val,
            "trade_date": last_dt
        })

    return rows


# =========================================================================
# 【券商分點進出排行與逐日明細引擎】- 富邦 e點通 (fubon-ebrokerdj.fbs.com.tw)
# =========================================================================
def get_default_broker_backfill_base_date(now_dt: datetime = None) -> datetime.date:
    """
    【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
    1. 修改目的：富邦券商分點於每個交易日 15:00 後才會更新當日分點資料；
       若查詢時間在 15:00（含）之前，預設基準日自動對齊「前一交易日」（跳過週六日），15:00 之後才對齊當日。
    2. 防呆防錯原因：避免盤中或收盤後 15:00 前查詢當日分點時，抓到空資料並誤寫入快取。
    """
    now_tw = now_dt if now_dt is not None else (datetime.utcnow() + timedelta(hours=8))
    base_d = now_tw.date()
    if base_d.weekday() == 5:
        base_d -= timedelta(days=1)
    elif base_d.weekday() == 6:
        base_d -= timedelta(days=2)
    elif now_tw.hour < 15:
        base_d -= timedelta(days=1)
        while base_d.weekday() >= 5:
            base_d -= timedelta(days=1)
    return base_d


def _normalize_mdj_date(raw_str: str) -> str:
    """將富邦網頁日期格式（2026/11/13、115/11/13、2026-11-13）統一正規化為 YYYY-MM-DD"""
    s = str(raw_str or "").strip()
    m = re.search(r'(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if not m:
        return ""
    y = int(m.group(1))
    if y < 1911:
        y += 1911
    return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _parse_int_sheets(val_str: str) -> int:
    """解析張數欄位（去除逗號、空白、+號、全形負號）"""
    s = str(val_str or "").replace(",", "").replace("，", "").replace("+", "").replace("−", "-").replace("－", "-").strip()
    if not s or s in ("-", "--", "—"):
        return 0
    try:
        return int(round(float(s)))
    except Exception:
        return 0


def _classify_broker_system(broker_name: str) -> str:
    """自動標記八大官股體系分點，供前端徽章辨識"""
    name = str(broker_name or "").strip()
    for prefix in GOV_BROKER_PREFIXES:
        if prefix in name:
            return "八大官股"
    return "一般券商"


def _fetch_mdj_html(url: str, timeout: int = 8) -> str:
    """擷取富邦 DJ 網頁並自動處理 Big5 / CP950 / UTF-8 編碼"""
    try:
        res = requests.get(url, headers=MDJ_HEADERS, timeout=timeout)
        if res.status_code != 200 or not res.content:
            return ""
        raw = res.content
        for enc in ("cp950", "big5", "utf-8"):
            try:
                txt = raw.decode(enc)
                if "分點" in txt or "買超" in txt or "賣超" in txt or "券商" in txt or "日期" in txt:
                    return txt
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _resolve_mdj_broker_detail_url(href: str, page_url: str, stock_code: str, start_date: str, end_date: str) -> str:
    """將分點名稱超連結解析為完整且帶有區間起訖日參數的單一分點逐日明細網址"""
    if not href or href.lower().startswith("javascript:"):
        return ""
    abs_url = urljoin(page_url, href)
    parsed = urlparse(abs_url)
    qs = parse_qs(parsed.query)
    if "a" not in qs and "A" not in qs:
        qs["a"] = [stock_code]
    qs["c"] = [start_date]
    qs["d"] = [end_date]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _parse_fubon_side_block(cells, a_tags, page_url: str, stock_code: str, start_date: str, end_date: str, is_buy_side: bool):
    """
    【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
    1. 修改目的：解析富邦買賣超 5 欄區塊（[券商分點, 買進, 賣出, 買賣超, 佔比]），嚴格保留數值正負符號：
       買超側（is_buy_side=True）買賣超為正值（+N），賣超側（is_buy_side=False）買賣超正規化為負值（-N）。
    2. 防呆防錯原因：修正先前賣超張數存入正值、導致前後端紅綠與負號不一致之缺陷。
    """
    if len(cells) < 5:
        return None
    b_name = cells[0].strip()
    if not b_name or any(k in b_name for k in ("買超券商", "賣超券商", "券商名稱", "合計", "總計", "名次", "買進", "賣出")):
        return None
    if re.fullmatch(r'[\d,.\-+%]+', b_name):
        return None

    buy_v = abs(_parse_int_sheets(cells[1]))
    sell_v = abs(_parse_int_sheets(cells[2]))
    raw_net = _parse_int_sheets(cells[3])
    abs_net = abs(raw_net) if raw_net != 0 else abs(buy_v - sell_v)
    if abs_net == 0 and buy_v == 0 and sell_v == 0:
        return None

    # 買超為正值、賣超為負值
    net_v = abs_net if is_buy_side else -abs_net
    ratio_v = cells[4].strip() if len(cells) >= 5 else "-"

    detail_url = ""
    for a in a_tags:
        if a.get_text(strip=True) == b_name or b_name in a.get_text(strip=True):
            detail_url = _resolve_mdj_broker_detail_url(a.get("href", ""), page_url, stock_code, start_date, end_date)
            if detail_url:
                break
    if not detail_url and a_tags:
        detail_url = _resolve_mdj_broker_detail_url(a_tags[0].get("href", ""), page_url, stock_code, start_date, end_date)

    return {
        "分點名稱": b_name,
        "體系": _classify_broker_system(b_name),
        "買進(張)": buy_v,
        "賣出(張)": sell_v,
        "買賣超(張)": net_v,
        "佔比": ratio_v,
        "明細網址": detail_url
    }


def fetch_stock_broker_range_ranking(pure_code: str, start_date: str, end_date: str):
    """
    擷取指定個股於 [start_date, end_date] 區間之買超前 15 名與賣超前 15 名券商分點統計。
    支援富邦「左買超 5 欄＋右賣超 5 欄（共 10 欄並排）」與上下雙表兩種版面。
    回傳: (df_buy_top15, df_sell_top15)
    """
    code = str(pure_code or "").strip().upper()
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
        return pd.DataFrame(), pd.DataFrame()

    s_norm = _normalize_mdj_date(start_date) or str(start_date).strip()
    e_norm = _normalize_mdj_date(end_date) or str(end_date).strip()

    candidate_urls = [
        f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&e={s_norm}&f={e_norm}",
        f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&c={s_norm}&d={e_norm}",
        f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco_{code}.djhtm",
    ]

    buy_rows, sell_rows = [], []

    for url in candidate_urls:
        html = _fetch_mdj_html(url, timeout=8)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        parsed_buy, parsed_sell = [], []

        for tbl in soup.find_all("table"):
            txt = tbl.get_text()
            if "買超" not in txt and "賣超" not in txt:
                continue

            table_mode = None
            for tr in tbl.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                cells = [re.sub(r'\s+', ' ', td.get_text(strip=True)) for td in tds]
                row_str = "".join(cells)

                # 1. 優先偵測 10 欄並排（左 5 欄買超 + 右 5 欄賣超）
                if len(cells) >= 10:
                    left_tds = tds[:5]
                    right_tds = tds[5:10]
                    left_links = [a for td in left_tds for a in td.find_all("a", href=True)]
                    right_links = [a for td in right_tds for a in td.find_all("a", href=True)]

                    b_rec = _parse_fubon_side_block(cells[:5], left_links, url, code, s_norm, e_norm, is_buy_side=True)
                    s_rec = _parse_fubon_side_block(cells[5:10], right_links, url, code, s_norm, e_norm, is_buy_side=False)
                    if b_rec:
                        parsed_buy.append(b_rec)
                    if s_rec:
                        parsed_sell.append(s_rec)
                    continue

                # 2. 相容上下分表模式（單側 5 欄）
                if "買超券商" in row_str or ("買超" in row_str and "賣超" not in row_str and len(cells) <= 6):
                    table_mode = "BUY"
                    continue
                if "賣超券商" in row_str or ("賣超" in row_str and "買超" not in row_str and len(cells) <= 6):
                    table_mode = "SELL"
                    continue

                if len(cells) >= 5 and table_mode in ("BUY", "SELL"):
                    row_links = tr.find_all("a", href=True)
                    rec = _parse_fubon_side_block(
                        cells[:5], row_links, url, code, s_norm, e_norm,
                        is_buy_side=(table_mode == "BUY")
                    )
                    if rec:
                        if table_mode == "BUY":
                            parsed_buy.append(rec)
                        else:
                            parsed_sell.append(rec)

        if parsed_buy or parsed_sell:
            buy_rows = parsed_buy
            sell_rows = parsed_sell
            break

    def _finalize_df(rows_list):
        if not rows_list:
            return pd.DataFrame(columns=["名次", "分點名稱", "體系", "買進(張)", "賣出(張)", "買賣超(張)", "佔比", "明細網址"])
        df_out = pd.DataFrame(rows_list).drop_duplicates(subset=["分點名稱"]).head(15).copy()
        df_out.insert(0, "名次", range(1, len(df_out) + 1))
        return df_out

    return _finalize_df(buy_rows), _finalize_df(sell_rows)


def fetch_single_broker_daily_series(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
    1. 修改目的：依富邦單一分點歷史明細網頁（zco0.djhtm）實測固定 5 欄結構
       ['日期', '買進(張)', '賣出(張)', '買賣總額(張)', '買賣超(張)']（索引 0 至 4），
       修正為讀取第 5 欄（cells[4]）作為「買賣超(張)」，通案解決所有個股與日期之分點逐日明細正負號與數值解析。
    2. 防呆防錯原因：嚴格限定 len(cells) >= 5 且首欄為有效日期才解析，排除合併多欄之外層容器列（如 106 欄）與底部「期間累計買賣超張數」單欄合計列，避免將第 4 欄恆正之「買賣總額(張)」誤當成買賣超。
    """
    empty_df = pd.DataFrame(columns=["日期", "買進(張)", "賣出(張)", "買賣超(張)"])
    if not detail_url:
        return empty_df

    s_norm = _normalize_mdj_date(start_date) or str(start_date).strip()
    e_norm = _normalize_mdj_date(end_date) or str(end_date).strip()

    parsed = urlparse(detail_url)
    qs = parse_qs(parsed.query)
    qs["c"] = [s_norm]
    qs["d"] = [e_norm]
    target_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(qs, doseq=True), parsed.fragment))

    html = _fetch_mdj_html(target_url, timeout=8)
    if not html:
        return empty_df

    soup = BeautifulSoup(html, "html.parser")
    daily_records = []

    for tr in soup.find_all("tr"):
        cells = [re.sub(r'\s+', ' ', td.get_text(strip=True)) for td in tr.find_all(["td", "th"])]
        if len(cells) != 5:
            continue
        d_iso = _normalize_mdj_date(cells[0])
        if not d_iso:
            continue
        if s_norm and d_iso < s_norm:
            continue
        if e_norm and d_iso > e_norm:
            continue

        buy_v = _parse_int_sheets(cells[1])
        sell_v = _parse_int_sheets(cells[2])
        # cells[3] 為「買賣總額(張)」，cells[4] 為「買賣超(張)」
        net_v = _parse_int_sheets(cells[4])
        if net_v == 0 and (buy_v != 0 or sell_v != 0):
            net_v = buy_v - sell_v

        daily_records.append({
            "日期": d_iso,
            "買進(張)": buy_v,
            "賣出(張)": sell_v,
            "買賣超(張)": net_v
        })

    if not daily_records:
        return empty_df

    df_res = pd.DataFrame(daily_records).drop_duplicates(subset=["日期"]).sort_values("日期").reset_index(drop=True)
    return df_res


def batch_sync_all_stocks_brokers(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 供「⚙️ 參數設定」執行全市場查詢歷史清單之歷史分點批次增補，從指定基準日（base_date_str）往前追溯 lookback_days 個交易日，
         補齊 1 / 10 / 20 日買賣超前 10 名統計（broker_range_rank）與各區間前 5 名分點逐日進出明細（broker_daily_trades）。
       - 跨日分點去重加速：同一檔個股先蒐集所有缺漏交易日「近 10 日前 5 名」與「近 20 日前 5 名」買賣超分點聯集，
         每家分點僅針對整段最長涵蓋區間抓取一次逐日明細，大幅減少重複 HTTP 請求並輸出 Console Log。
    2. 防呆防錯原因：
       - 自動過濾排除 ^ 開頭指數；已具備完整 w1/w10/w20 快照之交易日直接跳過；
       - 每檔個股完成所有交易日寫入後僅執行一次 sync_db_push(code)，降低 Google Drive API 寫入次數。
    """
    hist_list = load_stock_history()
    stock_items = []
    seen_codes = set()
    for item in hist_list:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or not is_tw_stock_or_etf(code) or code in seen_codes:
            continue
        seen_codes.add(code)
        c_name = str(item.get("name", "")).strip() or get_stock_chinese_name(code)
        stock_items.append((code, c_name))

    if not stock_items:
        return "目前查詢歷史清單無可增補之台股個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]
    print(f"[BrokerBackfill] 啟動批次分點增補：基準日={b_norm}，往前={n_days}日，共={tot_n}檔")

    def _df_to_rank_recs(df_rank):
        if df_rank is None or df_rank.empty:
            return []
        recs = []
        for _, r in df_rank.head(10).iterrows():
            recs.append({
                "name": str(r.get("分點名稱", "")),
                "sys": str(r.get("體系", "")),
                "buy": int(r.get("買進(張)", 0)),
                "sell": int(r.get("賣出(張)", 0)),
                "net": int(r.get("買賣超(張)", 0)),
                "ratio": str(r.get("佔比", "-")),
            })
        return recs

    updated_stocks = 0
    updated_days_total = 0
    skipped_days_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查交易日序列與既有分點資料...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is None or df_k.empty:
            k_res = fetch_stock_daily_k(code, period="1y", force_refresh=False)
            if k_res and k_res[0] is not None:
                df_k = k_res[0]

        if df_k is None or df_k.empty:
            print(f"[BrokerBackfill] [{idx_s}/{tot_n}] {code} {c_name}: 無日K資料，略過")
            continue

        trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index]
        valid_pos = [i for i, d_s in enumerate(trade_dates) if d_s <= b_norm]
        if not valid_pos:
            print(f"[BrokerBackfill] [{idx_s}/{tot_n}] {code} {c_name}: 無 <= {b_norm} 交易日，略過")
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_indices = list(range(anchor_pos, start_pos - 1, -1))

        # 1. 篩選出尚未有完整 w1/w10/w20 的缺漏交易日，並蒐集各日統計榜單與所有需補抓逐日明細的分點聯集
        pending_bundles = []
        union_broker_urls = {}
        earliest_all_s = None
        latest_all_e = None

        for t_idx in target_indices:
            end_d_str = trade_dates[t_idx]
            existing_bundle = storage.load_broker_range_rank(end_d_str)
            if isinstance(existing_bundle, dict) and all(
                isinstance(existing_bundle.get(f"w{w}"), dict)
                and (existing_bundle[f"w{w}"].get("buy") or existing_bundle[f"w{w}"].get("sell"))
                for w in (1, 10, 20)
            ):
                skipped_days_total += 1
                continue

            if progress_callback:
                progress_callback(idx_s, tot_n, code, c_name, f"擷取 {end_d_str}（1/10/20日分點統計）...")

            win_starts = {
                1: end_d_str,
                10: trade_dates[max(0, t_idx - 10 + 1)],
                20: trade_dates[max(0, t_idx - 20 + 1)],
            }
            if earliest_all_s is None or win_starts[20] < earliest_all_s:
                earliest_all_s = win_starts[20]
            if latest_all_e is None or end_d_str > latest_all_e:
                latest_all_e = end_d_str

            rank_dfs = {}
            for w in (1, 10, 20):
                df_b, df_s = fetch_stock_broker_range_ranking(code, win_starts[w], end_d_str)
                if (df_b is None or df_b.empty) and (df_s is None or df_s.empty):
                    time.sleep(0.25)
                    df_b, df_s = fetch_stock_broker_range_ranking(code, win_starts[w], end_d_str)
                rank_dfs[w] = (df_b, df_s)
                time.sleep(0.08)

            # 蒐集該交易日「近 10 日前 5 名」與「近 20 日前 5 名」買賣超分點（聯集不遺漏）
            for w in (10, 20):
                df_b, df_s = rank_dfs.get(w, (None, None))
                for df_side in (df_b, df_s):
                    if df_side is not None and not df_side.empty:
                        for _, row in df_side.head(5).iterrows():
                            b_name = str(row.get("分點名稱", "")).strip()
                            d_url = str(row.get("明細網址", "")).strip()
                            if b_name and d_url and b_name not in union_broker_urls:
                                union_broker_urls[b_name] = d_url

            day_bundle = dict(existing_bundle) if isinstance(existing_bundle, dict) else {}
            has_any = False
            for w in (1, 10, 20):
                df_b, df_s = rank_dfs.get(w, (None, None))
                b_recs = _df_to_rank_recs(df_b)
                s_recs = _df_to_rank_recs(df_s)
                if b_recs or s_recs:
                    has_any = True
                    lbl = end_d_str if w == 1 else f"{win_starts[w]} ~ {end_d_str}"
                    day_bundle[f"w{w}"] = {
                        "range_label": lbl,
                        "buy": b_recs,
                        "sell": s_recs,
                    }
            if has_any:
                pending_bundles.append((end_d_str, day_bundle))

        # 2. 針對聯集分點一次性抓取 [earliest_all_s, latest_all_e] 逐日明細，杜絕跨日重複查詢
        if union_broker_urls and earliest_all_s and latest_all_e:
            tot_b = len(union_broker_urls)
            for b_i, (b_name, d_url) in enumerate(union_broker_urls.items(), start=1):
                if progress_callback:
                    progress_callback(idx_s, tot_n, code, c_name, f"補抓分點逐日明細 ({b_i}/{tot_b})：{b_name}...")
                df_fresh = fetch_single_broker_daily_series(d_url, earliest_all_s, latest_all_e)
                if df_fresh is not None and not df_fresh.empty:
                    storage.save_broker_daily_trades(b_name, df_fresh, sync_cloud=False)
                time.sleep(0.06)

        # 3. 寫入該檔個股所有缺漏日統計快照並同步上傳雲端一次
        if pending_bundles:
            for end_d_str, day_bundle in pending_bundles:
                storage.save_broker_range_rank(end_d_str, day_bundle, sync_cloud=False)
                updated_days_total += 1
            sync_db_push(code)
            updated_stocks += 1
            print(f"[BrokerBackfill] [{idx_s}/{tot_n}] {code} {c_name}: 補齊 {len(pending_bundles)} 日快照、{len(union_broker_urls)} 家分點明細並同步雲端")
        else:
            print(f"[BrokerBackfill] [{idx_s}/{tot_n}] {code} {c_name}: 目標區間已完整，略過")

    summary = (
        f"批次分點增補完成（基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（新增 {updated_days_total} 筆交易日快照），"
        f"略過已存在完整快照 {skipped_days_total} 筆。"
    )
    print(f"[BrokerBackfill] {summary}")
    return summary


# =========================================================================
# 【全市(含上櫃)資券 / 法人 / 大戶籌碼指定基準日區間批次增補引擎】
# =========================================================================
def get_default_chip_backfill_base_date(now_dt: datetime = None) -> datetime.date:
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：三大法人與信用交易於每個交易日 16:30 後完備；16:30（含）前預設對齊前一交易日（跳過週六日），16:30 後對齊當日。
    2. 防呆防錯原因：避免盤中或盤後尚未公告時誤以當日作為預設基準日。
    """
    now_tw = now_dt if now_dt is not None else (datetime.utcnow() + timedelta(hours=8))
    base_d = now_tw.date()
    if base_d.weekday() == 5:
        base_d -= timedelta(days=1)
    elif base_d.weekday() == 6:
        base_d -= timedelta(days=2)
    elif now_tw.hour < 16 or (now_tw.hour == 16 and now_tw.minute < 30):
        base_d -= timedelta(days=1)
        while base_d.weekday() >= 5:
            base_d -= timedelta(days=1)
    return base_d


def _get_hist_tw_stock_items() -> list:
    """取得查詢歷史清單內所有台股個股與 ETF（排除 ^ 開頭指數）"""
    hist_list = load_stock_history()
    stock_items = []
    seen_codes = set()
    for item in hist_list:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or not is_tw_stock_or_etf(code) or code in seen_codes:
            continue
        seen_codes.add(code)
        c_name = str(item.get("name", "")).strip() or get_stock_chinese_name(code)
        stock_items.append((code, c_name))
    return stock_items


def batch_sync_all_stocks_margin(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：依據「籌碼增補基準日（base_date_str）」與「往前增補交易籌碼日數（lookback_days）」，
       針對所有上市／上櫃個股（含 ETF）補齊 [start_date, base_date_str] 區間內缺失之資券籌碼資料（margin_short）並同步雲端。
    2. 防呆防錯原因：沿用已驗證資料源 FinMind TaiwanStockMarginPurchaseShortSale；已具備該區間完整交易日紀錄者自動跳過。
    """
    stock_items = _get_hist_tw_stock_items()
    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]

    updated_stocks = 0
    added_rows_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查資券交易日序列與缺失紀錄...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is None or df_k.empty:
            k_res = fetch_stock_daily_k(code, period="1y", force_refresh=False)
            if k_res and k_res[0] is not None:
                df_k = k_res[0]
        if df_k is None or df_k.empty:
            continue

        trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index]
        valid_pos = [i for i, d_s in enumerate(trade_dates) if d_s <= b_norm]
        if not valid_pos:
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_dates = trade_dates[start_pos:anchor_pos + 1]
        start_date_str = target_dates[0]

        df_ms_exist = storage.load_margin_df()
        exist_dates = set(df_ms_exist["date"].dt.strftime("%Y-%m-%d")) if (df_ms_exist is not None and not df_ms_exist.empty) else set()
        missing_dates = [d for d in target_dates if d not in exist_dates]
        if not missing_dates:
            continue

        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, f"補抓資券籌碼 ({start_date_str} ~ {b_norm})...")

        start_excl = (pd.to_datetime(min(missing_dates)) - timedelta(days=1)).strftime("%Y-%m-%d")
        recs_all = fetch_margin_short_data(code, df_k.index, start_date_exclusive=start_excl)
        recs_filtered = [r for r in recs_all if start_date_str <= str(r[0])[:10] <= b_norm]
        if recs_filtered:
            storage.save_margin_data(recs_filtered)
            updated_stocks += 1
            added_rows_total += len(recs_filtered)
        time.sleep(0.08)

    return (
        f"批次資券籌碼增補完成（基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（寫入 {added_rows_total} 筆交易日資券紀錄）。"
    )


def batch_sync_all_stocks_institutional(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：依據「籌碼增補基準日（base_date_str）」與「往前增補交易籌碼日數（lookback_days）」，
       針對所有上市／上櫃個股（含 ETF）補齊 [start_date, base_date_str] 區間內缺失之三大法人籌碼資料（institutional_investors）並同步雲端。
    2. 防呆防錯原因：沿用已驗證資料源（證交所 T86 / 櫃買 3itrade / FinMind 備援），僅針對區間內缺失交易日發起請求。
    """
    stock_items = _get_hist_tw_stock_items()
    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]

    updated_stocks = 0
    added_rows_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查法人交易日序列與缺失紀錄...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is None or df_k.empty:
            k_res = fetch_stock_daily_k(code, period="1y", force_refresh=False)
            if k_res and k_res[0] is not None:
                df_k = k_res[0]
        if df_k is None or df_k.empty:
            continue

        trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index]
        valid_pos = [i for i, d_s in enumerate(trade_dates) if d_s <= b_norm]
        if not valid_pos:
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_dates_str = set(trade_dates[start_pos:anchor_pos + 1])

        df_inst_exist = storage.load_institutional_df()
        exist_dates = set(df_inst_exist["date"].dt.strftime("%Y-%m-%d")) if (df_inst_exist is not None and not df_inst_exist.empty) else set()
        missing_dt_objs = [d for d in df_k.index if d.strftime("%Y-%m-%d") in target_dates_str and d.strftime("%Y-%m-%d") not in exist_dates]
        if not missing_dt_objs:
            continue

        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, f"補抓法人籌碼（缺失 {len(missing_dt_objs)} 日）...")

        inst_recs = fetch_institutional_investors(
            pure_code=code,
            df_dates=df_k.index,
            explicit_missing_dates=missing_dt_objs
        )
        if inst_recs:
            storage.save_institutional_data(inst_recs)
            updated_stocks += 1
            added_rows_total += len(inst_recs)
        time.sleep(0.06)

    return (
        f"批次法人籌碼增補完成（基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（寫入 {added_rows_total} 筆交易日法人紀錄）。"
    )


def batch_sync_all_stocks_holding(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：依據「籌碼增補基準日（base_date_str）」與「往前增補交易籌碼日數（lookback_days）」所涵蓋之區間 [start_date, base_date_str]，
       針對所有上市／上櫃個股（含 ETF）補齊落於該區間內之集保大戶股權分散表（1～15 級）並同步雲端。
    2. 防呆防錯原因：沿用已驗證資料源（集保官網 qryStock 動態 Token 多週歷史查詢），僅寫入區間內週別並嚴格限制 1 <= level <= 15。
    """
    stock_items = _get_hist_tw_stock_items()
    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]
    try:
        base_dt = datetime.strptime(b_norm, "%Y-%m-%d")
    except Exception:
        base_dt = datetime.now()
        b_norm = base_dt.strftime("%Y-%m-%d")

    fallback_start_str = (base_dt - timedelta(days=max(n_days * 2, n_days + 4))).strftime("%Y-%m-%d")
    needed_weeks = max(2, min(15, (n_days // 4) + 3))

    updated_stocks = 0
    added_weeks_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查集保大戶週別紀錄...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is not None and not df_k.empty:
            trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index if d.strftime("%Y-%m-%d") <= b_norm]
            if trade_dates:
                start_date_str = trade_dates[max(0, len(trade_dates) - n_days)]
            else:
                start_date_str = fallback_start_str
        else:
            start_date_str = fallback_start_str

        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, f"補抓大戶籌碼 ({start_date_str} ~ {b_norm})...")

        hist_recs = fetch_tdcc_holding_history(code, weeks=needed_weeks)
        filtered_recs = [
            (d, lvl, pct) for (d, lvl, pct) in hist_recs
            if start_date_str <= str(d)[:10] <= b_norm and 1 <= int(lvl) <= 15
        ]
        if filtered_recs:
            storage.save_holding_data(filtered_recs)
            weeks_cnt = len({str(r[0])[:10] for r in filtered_recs})
            updated_stocks += 1
            added_weeks_total += weeks_cnt
        time.sleep(0.08)

    return (
        f"批次大戶籌碼增補完成（基準日 {b_norm} 往前 {n_days} 個交易日區間）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（新增 {added_weeks_total} 週集保分級紀錄）。"
    )
# EOF data_fetcher.py
