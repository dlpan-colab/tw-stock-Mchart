"""
data_fetcher.py - 整合技術與籌碼資料擷取模組
(支援含英文後綴台股ETF + TWSE/TPEx官方日K即時補齊 + 雲端增量累積分點引擎 + 集保單檔FinMind與批次分離 + 賣超負值正規化版)
版本: 202611172146
"""
import os
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
MODULE_VERSION = "202611172146"

from storage import (
    StockChipStorage,
    COMMON_STOCK_NAMES,
    load_stock_names_dict,
    load_stock_history,
    get_stock_chinese_name,
    is_tw_stock_or_etf
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
    智慧增量同步三大法人、資券與集保大戶（支援台股個股及含英文後綴之 ETF）。
    """
    pure_code = str(pure_code).strip().upper()
    storage = StockChipStorage(pure_code)
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


def fetch_tdcc_holding_data(pure_code: str) -> list:
    """
    【修訂說明 2026-11-16】【修改目的與防呆防錯原因】：
    1. 修改目的：單一個股查詢時僅透過 FinMind 取得該單一個股最近一週公告之大戶持股分級比例，
       不再每次下載全市場集保 CSV 總表（全市場下載僅限批次作業）。
    2. 防呆防錯原因：僅取最新單一公告日期（max(date)）且嚴格保留 1 <= level <= 15 級距。
    """
    hist_recs = fetch_tdcc_holding_history(pure_code, weeks=2)
    if not hist_recs:
        return []
    max_d = max(r[0] for r in hist_recs)
    return [(d, lvl, pct) for (d, lvl, pct) in hist_recs if d == max_d and 1 <= lvl <= 15]


def batch_fetch_and_save_latest_tdcc_holding(target_codes: list = None) -> dict:
    """
    【修訂說明 2026-11-16】【修改目的與防呆防錯原因】：
    1. 修改目的：提供【上市/上櫃】批次作業，優先嘗試集保官方開放資料網鏡像與主站（id=1-5）；
       若因雲端主機位於海外遭集保官網阻擋逾時，自動切換至 FinMind 備援線路批次取得已收錄個股最近一週
       大戶持股分級比例，寫入各檔個股之 data_{code}.db（shareholding_distribution 資料表）並同步雲端。
    2. 防呆防錯原因：
       - 僅保留 1 <= level <= 15 級距，嚴格排除第 16（其他）、17（合計）列，防止比例計算重複加總。
       - 僅針對系統已建立之台股個股/ETF（排除 ^ 開頭指數）寫入，避免無差別產生數千個無效 .db 檔。
       - FinMind 備援模式僅擷取每檔回傳之最新單一公告日期（max(date)）紀錄寫入並加入 0.08s 節流防呆。
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
        return {"ok": False, "msg": "目前無已收錄之台股個股或 ETF 清單可供批次寫入。"}

    csv_text = ""
    source_used = "集保開放資料總表"
    for u in tdcc_urls:
        try:
            res = requests.get(u, headers=headers, timeout=6)
            if res.status_code == 200 and res.text and "," in res.text[:200]:
                csv_text = res.text
                break
        except Exception:
            continue

    grouped_by_code = {}
    latest_announce_date = ""

    if csv_text:
        for line in csv_text.splitlines():
            parts = line.strip().split(",")
            if len(parts) < 6:
                continue
            code = parts[1].strip().upper()
            if code not in candidate_set:
                continue
            try:
                d_str = datetime.strptime(parts[0].strip(), "%Y%m%d").strftime("%Y-%m-%d")
                level = int(parts[2].strip())
                if level < 1 or level > 15:
                    continue
                percent = float(parts[5].strip())
                grouped_by_code.setdefault(code, []).append((d_str, level, percent))
                if d_str > latest_announce_date:
                    latest_announce_date = d_str
            except Exception:
                continue

    if not grouped_by_code:
        source_used = "FinMind雲端備援線路"
        for code in sorted(candidate_set):
            try:
                hist_recs = fetch_tdcc_holding_history(code, weeks=2)
                if hist_recs:
                    max_d = max(r[0] for r in hist_recs)
                    latest_only = [(d, lvl, pct) for (d, lvl, pct) in hist_recs if d == max_d and 1 <= lvl <= 15]
                    if latest_only:
                        grouped_by_code[code] = latest_only
                        if max_d > latest_announce_date:
                            latest_announce_date = max_d
            except Exception:
                pass
            time.sleep(0.08)

    if not grouped_by_code:
        return {"ok": False, "msg": "集保官網連線逾時且備援線路暫無最新週資料，請稍後再試。"}

    updated_codes = []
    for code, recs in sorted(grouped_by_code.items()):
        try:
            storage = StockChipStorage(code)
            storage.save_holding_data(recs)
            updated_codes.append(code)
        except Exception:
            continue

    return {
        "ok": True,
        "announce_date": latest_announce_date,
        "updated_count": len(updated_codes),
        "total_candidates": len(candidate_set),
        "updated_codes": updated_codes,
        "msg": f"已透過【{source_used}】完成公告日 {latest_announce_date} 批次作業，共寫入 {len(updated_codes)}/{len(candidate_set)} 檔個股資料庫並同步雲端。"
    }


def fetch_tdcc_holding_history(pure_code: str, weeks: int = 6) -> list:
    records = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    start_dt = (datetime.now() - timedelta(days=int(weeks) * 7 + 10)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockHoldingSharesPer",
        "data_id": pure_code,
        "start_date": start_dt,
        "token": FINMIND_TOKEN
    }
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json().get("data", [])
            if data:
                level_text_map = {
                    "1-999": 1, "1,000-5,000": 2, "5,001-10,000": 3, "10,001-15,000": 4,
                    "15,001-20,000": 5, "20,001-30,000": 6, "30,001-40,000": 7, "40,001-50,000": 8,
                    "50,001-100,000": 9, "100,001-200,000": 10, "200,001-400,000": 11,
                    "400,001-600,000": 12, "600,001-800,000": 13, "800,001-1,000,000": 14,
                    "more than 1,000,001": 15
                }
                for row in data:
                    d_str = str(row.get("date", "")).strip()
                    lvl_raw = str(row.get("HoldingSharesLevel", "")).strip()
                    pct = float(row.get("percent", 0) or 0)
                    lvl_num = level_text_map.get(lvl_raw)
                    if not lvl_num:
                        m = re.match(r"^(\d+)", lvl_raw)
                        if m:
                            lvl_num = int(m.group(1))
                    if d_str and lvl_num and 1 <= lvl_num <= 15:
                        records.append((d_str, lvl_num, pct))
    except Exception:
        pass
    return records


# ==============================================================================
# 券商分點進出買賣超資料擷取引擎 (富邦 eBroker / MoneyDJ)
# ==============================================================================

def _parse_int_vol(val_str: str) -> int:
    s = str(val_str or "").replace(",", "").replace("+", "").replace(" ", "").strip()
    if not s or s in ("-", "--", "—"):
        return 0
    try:
        return int(round(float(s)))
    except Exception:
        return 0


def _is_gov_broker(broker_name: str) -> bool:
    b = str(broker_name or "").strip()
    return any(b.startswith(p) for p in GOV_BROKER_PREFIXES)


def _extract_broker_link(td_tag) -> str:
    if td_tag is None:
        return ""
    a_tag = td_tag.find("a", href=True)
    if not a_tag:
        return ""
    href = str(a_tag.get("href", "")).strip()
    if not href or href.lower().startswith("javascript"):
        return ""
    return urljoin(f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm", href)


def fetch_stock_broker_range_ranking(pure_code: str, start_date: str, end_date: str) -> tuple:
    """
    擷取指定個股於 [start_date, end_date] 區間內的券商分點買超前10名與賣超前10名。
    【修訂說明 2026-11-17】【修改目的與防呆防錯原因】：
    買超分點之「買賣超(張)」存為正整數並降冪排序；賣超分點之「買賣超(張)」統一存為負整數（-raw_sell_net）
    並依賣超張數由大到小排序（ascending=True），確保資料庫數值與前端負號綠字顯示一致。
    """
    code = str(pure_code or "").strip().upper()
    empty_cols = ["名次", "分點名稱", "體系", "買進(張)", "賣出(張)", "買賣超(張)", "佔比", "明細網址"]
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
        return (pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols))

    s_str = str(start_date).strip()[:10]
    e_str = str(end_date).strip()[:10]
    if s_str > e_str:
        s_str, e_str = e_str, s_str

    url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm"
    params = {"a": code, "e": s_str, "f": e_str}
    html_text = ""
    for attempt in range(2):
        try:
            res = requests.get(url, params=params, headers=MDJ_HEADERS, timeout=6)
            if res.status_code == 200:
                res.encoding = "big5"
                txt = res.text
                if "買超" in txt or "賣超" in txt or "券商" in txt:
                    html_text = txt
                    break
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.25)

    if not html_text:
        return (pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols))

    soup = BeautifulSoup(html_text, "html.parser")
    buy_rows = []
    sell_rows = []

    skip_words = ("券商", "買超", "賣超", "合計", "總計", "平均", "張數")

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            tds = tr.find_all("td")
        if len(tds) >= 10:
            # 左側買超 Top 15
            b_name = tds[0].get_text(strip=True)
            if b_name and not any(w in b_name for w in skip_words):
                b_buy = _parse_int_vol(tds[1].get_text(strip=True))
                b_sell = _parse_int_vol(tds[2].get_text(strip=True))
                b_net_raw = abs(_parse_int_vol(tds[3].get_text(strip=True)))
                b_net = b_net_raw if b_net_raw > 0 else max(0, b_buy - b_sell)
                b_ratio = tds[4].get_text(strip=True)
                b_link = _extract_broker_link(tds[0])
                if b_net > 0 or b_buy > 0:
                    buy_rows.append({
                        "分點名稱": b_name,
                        "體系": "八大官股" if _is_gov_broker(b_name) else "一般券商",
                        "買進(張)": b_buy,
                        "賣出(張)": b_sell,
                        "買賣超(張)": b_net,
                        "佔比": b_ratio,
                        "明細網址": b_link
                    })

            # 右側賣超 Top 15（統一存為負值 -raw_sell_net）
            s_name = tds[5].get_text(strip=True)
            if s_name and not any(w in s_name for w in skip_words):
                s_buy = _parse_int_vol(tds[6].get_text(strip=True))
                s_sell = _parse_int_vol(tds[7].get_text(strip=True))
                s_net_raw = abs(_parse_int_vol(tds[8].get_text(strip=True)))
                s_net_abs = s_net_raw if s_net_raw > 0 else max(0, s_sell - s_buy)
                s_ratio = tds[9].get_text(strip=True)
                s_link = _extract_broker_link(tds[5])
                if s_net_abs > 0 or s_sell > 0:
                    sell_rows.append({
                        "分點名稱": s_name,
                        "體系": "八大官股" if _is_gov_broker(s_name) else "一般券商",
                        "買進(張)": s_buy,
                        "賣出(張)": s_sell,
                        "買賣超(張)": -s_net_abs,
                        "佔比": s_ratio,
                        "明細網址": s_link
                    })

    def to_top10_df(rows_list, is_buy: bool) -> pd.DataFrame:
        if not rows_list:
            return pd.DataFrame(columns=empty_cols)
        df_tmp = pd.DataFrame(rows_list)
        df_tmp = df_tmp.drop_duplicates(subset=["分點名稱"], keep="first")
        df_tmp = df_tmp.sort_values(by="買賣超(張)", ascending=(not is_buy)).head(10).reset_index(drop=True)
        df_tmp.insert(0, "名次", range(1, len(df_tmp) + 1))
        return df_tmp[empty_cols]

    return (to_top10_df(buy_rows, is_buy=True), to_top10_df(sell_rows, is_buy=False))


def _normalize_roc_date(raw_d: str) -> str:
    s = str(raw_d or "").strip()
    m = re.match(r"^(\d{2,4})[/\-](\d{1,2})[/\-](\d{1,2})$", s)
    if not m:
        return ""
    y = int(m.group(1))
    if y < 1911:
        y += 1911
    mo = int(m.group(2))
    da = int(m.group(3))
    if 1 <= mo <= 12 and 1 <= da <= 31:
        return f"{y:04d}-{mo:02d}-{da:02d}"
    return ""


def fetch_single_broker_daily_series(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    透過分點歷史明細網址擷取單一分點於 [start_date, end_date] 內之每日買進、賣出、買賣超(張)明細。
    """
    empty_df = pd.DataFrame(columns=["日期", "買進(張)", "賣出(張)", "買賣超(張)"])
    if not detail_url:
        return empty_df

    s_str = str(start_date).strip()[:10]
    e_str = str(end_date).strip()[:10]
    if s_str > e_str:
        s_str, e_str = e_str, s_str

    parsed = urlparse(detail_url)
    qs = parse_qs(parsed.query)
    qs["e"] = [s_str]
    qs["f"] = [e_str]
    target_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(qs, doseq=True), parsed.fragment))

    html_text = ""
    for attempt in range(2):
        try:
            res = requests.get(target_url, headers=MDJ_HEADERS, timeout=6)
            if res.status_code == 200:
                res.encoding = "big5"
                html_text = res.text
                break
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.2)

    if not html_text:
        return empty_df

    soup = BeautifulSoup(html_text, "html.parser")
    daily_rows = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        d_iso = _normalize_roc_date(tds[0].get_text(strip=True))
        if not d_iso or d_iso < s_str or d_iso > e_str:
            continue
        b_vol = _parse_int_vol(tds[1].get_text(strip=True))
        s_vol = _parse_int_vol(tds[2].get_text(strip=True))
        n_vol = _parse_int_vol(tds[3].get_text(strip=True))
        if n_vol == 0 and (b_vol > 0 or s_vol > 0):
            n_vol = b_vol - s_vol
        daily_rows.append({
            "日期": d_iso,
            "買進(張)": b_vol,
            "賣出(張)": s_vol,
            "買賣超(張)": n_vol
        })

    if not daily_rows:
        return empty_df

    df_res = pd.DataFrame(daily_rows)
    df_res = df_res.drop_duplicates(subset=["日期"], keep="last").sort_values("日期").reset_index(drop=True)
    return df_res
# EOF data_fetcher.py
