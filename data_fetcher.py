"""
data_fetcher.py - 整合技術與籌碼資料擷取模組
(支援含英文後綴台股ETF + TWSE/TPEx官方日K即時補齊 + 雲端增量累積分點引擎 + 集保單檔FinMind與批次分離 + 賣超負值正規化 + 操作儀錶板盤中報價版 + 批次增補近N日分點統計與明細穩定版)
版本: 202611190730
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
MODULE_VERSION = "202611190730"

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
            if len(df_dates) > 0 else (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
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
                        r['date'], m_diff, s_diff, m_bal, s_bal
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
                    latest_recs = [(d, lvl, pct) for (d, lvl, pct) in hist_recs if d == max_d and 1 <= lvl <= 15]
                    if latest_recs:
                        grouped_by_code[code] = latest_recs
                        if max_d > latest_announce_date:
                            latest_announce_date = max_d
            except Exception:
                pass
            time.sleep(0.08)

    if not grouped_by_code:
        return {"ok": False, "msg": "集保開放資料網與 FinMind 備援線路皆未能取得最新一週分級紀錄，請稍後再試。"}

    saved_stocks = 0
    saved_rows = 0
    for code, recs in grouped_by_code.items():
        try:
            storage = StockChipStorage(code)
            storage.save_holding_data(recs)
            saved_stocks += 1
            saved_rows += len(recs)
        except Exception:
            continue

    return {
        "ok": True,
        "source": source_used,
        "announce_date": latest_announce_date,
        "stocks_count": saved_stocks,
        "rows_count": saved_rows,
        "msg": f"已透過【{source_used}】完成 {saved_stocks} 檔個股（共 {saved_rows} 筆分級，最新公告日 {latest_announce_date}）大戶持股寫入並同步雲端！"
    }


def fetch_tdcc_holding_history(pure_code: str, weeks: int = 8) -> list:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    start_dt = (datetime.now() - timedelta(days=weeks * 7 + 14)).strftime('%Y-%m-%d')
    records_h = []
    try:
        url_h = "https://api.finmindtrade.com/api/v4/data"
        p_h = {
            "dataset": "TaiwanStockHoldingSharesPer",
            "data_id": pure_code,
            "start_date": start_dt,
            "token": FINMIND_TOKEN
        }
        res_h = requests.get(url_h, params=p_h, headers=headers, timeout=5)
        if res_h.status_code == 200:
            data_h = res_h.json().get('data', [])
            if data_h:
                h_df = pd.DataFrame(data_h)
                level_map = {
                    "1-999": 1, "1,000-5,000": 2, "5,001-10,000": 3, "10,001-15,000": 4,
                    "15,001-20,000": 5, "20,001-30,000": 6, "30,001-40,000": 7, "40,001-50,000": 8,
                    "50,001-100,000": 9, "100,001-200,000": 10, "200,001-400,000": 11,
                    "400,001-600,000": 12, "600,001-800,000": 13, "800,001-1,000,000": 14,
                    "more than 1,000,001": 15
                }
                for _, r in h_df.iterrows():
                    lvl_str = str(r.get('HoldingSharesLevel', '')).strip()
                    lvl_int = level_map.get(lvl_str)
                    if lvl_int and 1 <= lvl_int <= 15:
                        records_h.append((r['date'], lvl_int, float(r.get('percent', 0) or 0)))
    except Exception:
        pass
    return records_h


# =====================================================================
# 券商分點進出排行與逐日明細爬蟲引擎 (富邦 e點通 fubon-ebrokerdj)
# =====================================================================

def _clean_broker_int(val_str: str) -> int:
    s = str(val_str or "").replace(",", "").replace("+", "").replace(" ", "").strip()
    if not s or s in ("-", "--", "—"):
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def _clean_broker_name(raw_name: str) -> tuple:
    name = re.sub(r"\s+", " ", str(raw_name or "")).strip()
    sys_tag = "官股" if name.startswith(GOV_BROKER_PREFIXES) else ""
    return name, sys_tag


def _resolve_mdj_broker_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    h = href.strip()
    m_js = re.search(r"['\"]([^'\"]*z/zg/zgb/zgb0\.djhtm[^'\"]*)['\"]", h, re.IGNORECASE)
    if m_js:
        h = m_js.group(1)
    if h.lower().startswith("javascript:"):
        return ""
    full = urljoin(base_url, h)
    parsed = urlparse(full)
    qs = parse_qs(parsed.query)
    flat_qs = {k: v[0] for k, v in qs.items() if v}
    if "b" in flat_qs and "B" not in flat_qs:
        flat_qs["B"] = flat_qs.pop("b")
    new_query = urlencode(flat_qs)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))


def _parse_roc_or_iso_date(date_text: str) -> str:
    s = str(date_text or "").strip()
    if not s:
        return ""
    m_iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    m_roc = re.match(r"^(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m_roc:
        y = int(m_roc.group(1)) + 1911
        return f"{y:04d}-{int(m_roc.group(2)):02d}-{int(m_roc.group(3)):02d}"
    return ""


def _parse_broker_side_table(table_soup, base_url: str, is_sell_side: bool = False) -> pd.DataFrame:
    """
    【修訂說明 2026-11-17】
    賣超方（右側欄位）之「買賣超(張)」強制轉為負值（-abs(net_val)），
    確保前端賣超列表一律呈現綠字與負號，區間柱狀圖亦精準朝下顯示賣超張數。
    """
    rows_out = []
    if table_soup is None:
        return pd.DataFrame()
    for tr in table_soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        texts = [td.get_text(" ", strip=True) for td in tds]
        if any(k in texts[0] for k in ("買超券商", "賣超券商", "券商名稱", "排行")):
            continue
        b_name, sys_tag = _clean_broker_name(texts[0])
        if not b_name or b_name in ("合計", "總計", "其他"):
            continue
        buy_val = _clean_broker_int(texts[1])
        sell_val = _clean_broker_int(texts[2])
        net_val = _clean_broker_int(texts[3])
        if is_sell_side:
            net_val = -abs(net_val)
        ratio_str = texts[4].strip() if len(texts) >= 5 and "%" in texts[4] else "-"
        detail_url = ""
        a_tag = tds[0].find("a", href=True)
        if a_tag:
            detail_url = _resolve_mdj_broker_url(a_tag["href"], base_url)
        rows_out.append({
            "分點名稱": b_name,
            "體系": sys_tag,
            "買進(張)": buy_val,
            "賣出(張)": sell_val,
            "買賣超(張)": net_val,
            "佔比": ratio_str,
            "明細網址": detail_url
        })
    return pd.DataFrame(rows_out)


def fetch_stock_broker_range_ranking(pure_code: str, start_date: str, end_date: str):
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    100% 還原原本已驗證成功之富邦 eBroker 網址規則：
    - 當 start_date == end_date（最新當日）使用 zco_{code}.djhtm。
    - 區間查詢使用標準 YYYY-MM-DD 格式之 zco.djhtm?a={code}&e={s_str}&f={e_str}，不試其他錯誤日期格式。
    """
    code = str(pure_code or "").strip().upper()
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
        return pd.DataFrame(), pd.DataFrame()

    s_str = str(start_date).strip()[:10]
    e_str = str(end_date).strip()[:10]
    if s_str == e_str:
        target_url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco_{code}.djhtm"
    else:
        target_url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&e={s_str}&f={e_str}"

    try:
        res = requests.get(target_url, headers=MDJ_HEADERS, timeout=5)
        if res.status_code != 200:
            return pd.DataFrame(), pd.DataFrame()
        try:
            html_text = res.content.decode("cp950", errors="replace")
        except Exception:
            html_text = res.text

        soup = BeautifulSoup(html_text, "html.parser")
        buy_tbl = None
        sell_tbl = None

        for tbl in soup.find_all("table"):
            txt = tbl.get_text(" ", strip=True)
            if "買超券商" in txt and "賣超券商" in txt:
                sub_tables = tbl.find_all("table")
                for stbl in sub_tables:
                    stxt = stbl.get_text(" ", strip=True)
                    if "買超券商" in stxt and "賣超券商" not in stxt and buy_tbl is None:
                        buy_tbl = stbl
                    elif "賣超券商" in stxt and "買超券商" not in stxt and sell_tbl is None:
                        sell_tbl = stbl
                if buy_tbl is not None or sell_tbl is not None:
                    break

        if buy_tbl is None and sell_tbl is None:
            for tbl in soup.find_all("table"):
                txt = tbl.get_text(" ", strip=True)
                if "買超券商" in txt and "賣超券商" not in txt and len(tbl.find_all("tr")) >= 3:
                    buy_tbl = tbl
                elif "賣超券商" in txt and "買超券商" not in txt and len(tbl.find_all("tr")) >= 3:
                    sell_tbl = tbl

        df_buy = _parse_broker_side_table(buy_tbl, target_url, is_sell_side=False)
        df_sell = _parse_broker_side_table(sell_tbl, target_url, is_sell_side=True)
        return df_buy, df_sell
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def fetch_single_broker_daily_series(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    if not detail_url:
        return pd.DataFrame()

    s_str = str(start_date).strip()[:10]
    e_str = str(end_date).strip()[:10]

    parsed = urlparse(detail_url)
    qs = parse_qs(parsed.query)
    flat_qs = {k: v[0] for k, v in qs.items() if v}
    flat_qs["C"] = "1"
    flat_qs["E"] = s_str
    flat_qs["F"] = e_str
    query_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(flat_qs), ""))

    try:
        res = requests.get(query_url, headers=MDJ_HEADERS, timeout=5)
        if res.status_code != 200:
            return pd.DataFrame()
        try:
            html_text = res.content.decode("cp950", errors="replace")
        except Exception:
            html_text = res.text

        soup = BeautifulSoup(html_text, "html.parser")
        records = []
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            texts = [td.get_text(" ", strip=True) for td in tds]
            iso_d = _parse_roc_or_iso_date(texts[0])
            if not iso_d:
                continue
            if iso_d < s_str or iso_d > e_str:
                continue
            b_vol = _clean_broker_int(texts[1])
            s_vol = _clean_broker_int(texts[2])
            n_vol = _clean_broker_int(texts[3]) if len(texts) >= 4 else (b_vol - s_vol)
            records.append({
                "日期": iso_d,
                "買進(張)": b_vol,
                "賣出(張)": s_vol,
                "買賣超(張)": n_vol
            })

        if not records:
            return pd.DataFrame()

        df_out = pd.DataFrame(records)
        df_out = df_out.drop_duplicates(subset=["日期"], keep="last").sort_values("日期").reset_index(drop=True)
        return df_out
    except Exception:
        return pd.DataFrame()


# =====================================================================
# 操作儀錶板：自選清單盤中即時報價與 5日/20日均線計算引擎
# =====================================================================

def fetch_dashboard_watchlist_rows(history_records: list) -> list:
    """
    【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
    1. 修改目的：為「📊 操作儀錶板」批量計算清單內所有台股個股/ETF之最新盤中成交價、成交量(張)、
       動態 5日均線與 20日均線（含最新成交價）。
    2. 防呆防錯原因：
       - 僅處理台股個股與含英文後綴之 ETF（自動略過 ^ 開頭大盤指數），並維持與查詢歷史清單完全一致之排序。
       - 優先結合本地 SQLite 歷史收盤價與 yfinance 近 5 日含盤中即時報價計算動態 5MA/20MA，避免逐檔下載 1 年全期資料造成延遲。
    """
    rows = []
    if not history_records:
        return rows

    for item in history_records:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
            continue

        c_name = str(item.get("name", "")).strip()
        if not c_name or c_name == code:
            c_name = get_stock_chinese_name(code)

        storage = StockChipStorage(code)
        db_df = storage.load_daily_k_df()

        market_label = "市"
        df_recent = pd.DataFrame()
        for suffix, m_lbl in ((".TW", "市"), (".TWO", "櫃")):
            try:
                hist = yf.Ticker(f"{code}{suffix}").history(period="5d")
                if hist is not None and not hist.empty:
                    if hist.index.tz is not None:
                        hist.index = hist.index.tz_localize(None)
                    hist = hist.dropna(subset=["Close"])
                    if "Volume" in hist.columns:
                        hist = hist[hist["Volume"] > 0]
                    if not hist.empty:
                        df_recent = hist
                        market_label = m_lbl
                        break
            except Exception:
                continue

        if not db_df.empty and not df_recent.empty:
            merged = pd.concat([db_df[["Open", "High", "Low", "Close", "Volume"]], df_recent[["Open", "High", "Low", "Close", "Volume"]]])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        elif not df_recent.empty:
            merged = df_recent.sort_index()
        elif not db_df.empty:
            merged = db_df.sort_index()
        else:
            merged = pd.DataFrame()

        if len(merged) < 20:
            # 若歷史不足 20 日以計算完整 20MA，補抓 3mo
            try:
                alt_suffix = ".TWO" if market_label == "櫃" else ".TW"
                h3m = yf.Ticker(f"{code}{alt_suffix}").history(period="3mo")
                if h3m is not None and not h3m.empty:
                    if h3m.index.tz is not None:
                        h3m.index = h3m.index.tz_localize(None)
                    h3m = h3m.dropna(subset=["Close"])
                    if not merged.empty:
                        merged = pd.concat([h3m[["Open", "High", "Low", "Close", "Volume"]], merged])
                        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                    else:
                        merged = h3m.sort_index()
            except Exception:
                pass

        if merged.empty:
            rows.append({
                "code": code,
                "name": c_name,
                "market": "-",
                "price": None,
                "vol_sheets": None,
                "ma5": None,
                "ma20": None,
                "trade_date": "-"
            })
            continue

        last_row = merged.iloc[-1]
        price_val = float(last_row["Close"])
        vol_sheets = float(last_row["Volume"]) / 1000.0 if "Volume" in merged.columns else 0.0
        ma5_val = float(merged["Close"].tail(5).mean()) if len(merged) >= 5 else None
        ma20_val = float(merged["Close"].tail(20).mean()) if len(merged) >= 20 else None
        t_date = merged.index[-1].strftime("%Y-%m-%d")

        rows.append({
            "code": code,
            "name": c_name,
            "market": market_label,
            "price": price_val,
            "vol_sheets": vol_sheets,
            "ma5": ma5_val,
            "ma20": ma20_val,
            "trade_date": t_date
        })

    return rows


# =====================================================================
# 【上市/上櫃】批次作業：增補近 N 日分點統計與分點逐日明細
# =====================================================================

def _collect_all_stock_db_codes() -> list:
    """
    【修訂說明 2026-11-19】
    掃描本地目錄與 Google Drive 雲端資料夾內所有已建立之台股個股/ETF資料庫（data_*.db），
    自動排除 ^ 開頭大盤指數，並將一般個股（4碼）排在前面優先處理。
    """
    codes_set = set()
    for p in glob.glob(os.path.join(".", "data_*.db")):
        cu = os.path.basename(p).replace("data_", "").replace(".db", "").strip().upper()
        if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
            codes_set.add(cu)

    try:
        from cloud_sync import GoogleDriveSync
        sync_client = GoogleDriveSync()
        if sync_client.service and sync_client.folder_id:
            q = f"'{sync_client.folder_id}' in parents and name contains 'data_' and name contains '.db' and trashed = false"
            res = sync_client.service.files().list(
                q=q, fields="files(id, name)", pageSize=250
            ).execute()
            for f in res.get("files", []):
                fname = f.get("name", "")
                cu = fname.replace("data_", "").replace(".db", "").strip().upper()
                if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                    codes_set.add(cu)
    except Exception:
        pass

    return sorted(codes_set, key=lambda c: (0 if len(c) == 4 and c.isdigit() else 1, c))


def _get_stock_trade_dates_for_backfill(pure_code: str) -> list:
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    1. 修改目的：優先直接從 Google Drive 同步拉取該股既有資料庫取得交易日清單，避免每檔重複向 Yahoo 抓 1 年日線造成卡頓。
    2. 防呆防錯原因：僅在本地與雲端皆無日線資料時才抓 6mo 日線；若仍無交易日則快速略過不卡死整批作業。
    """
    from storage import _do_sync_db_pull
    db_path = os.path.join(".", f"data_{pure_code}.db")
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        _do_sync_db_pull(pure_code)

    storage = StockChipStorage(pure_code)
    df_k = storage.load_daily_k_df()
    if df_k is None or df_k.empty:
        k_res = fetch_stock_daily_k(pure_code, period="6mo", force_refresh=False)
        if k_res and k_res[0] is not None and not k_res[0].empty:
            df_k = k_res[0]
    if df_k is None or df_k.empty:
        return []
    return [d.strftime("%Y-%m-%d") for d in df_k.index]


def batch_backfill_broker_range_ranks(recent_days: int = 5, progress_callback=None) -> dict:
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    1. 修改目的：僅使用已驗證成功之富邦標準 YYYY-MM-DD 網址邏輯：
       - 最新交易日（target_idx == total_len - 1）抓取 1、10、20、60 日四區間統計；
       - 往前推之歷史交易日（target_idx < total_len - 1）抓取 10、20、60 日區間統計（富邦不支援歷史單日參數）；
       - 同時保留各分點明細網址（url）供後續「增補近N日分點明細」直接讀取。
    2. 防呆防錯原因：拿掉所有錯誤日期格式猜測與無效重試，單檔有新寫入即同步上傳 Google 雲端硬碟。
    """
    from storage import _do_sync_db_push
    n_days = max(1, min(60, int(recent_days or 5)))
    codes = _collect_all_stock_db_codes()
    total_codes = len(codes)
    if total_codes == 0:
        return {"ok": False, "msg": "目前本地與雲端無任何已建立之台股個股資料庫。"}

    def _has_valid_win(bundle_obj: dict, w_num: int) -> bool:
        if not isinstance(bundle_obj, dict):
            return False
        w_item = bundle_obj.get(f"w{w_num}")
        if not isinstance(w_item, dict):
            return False
        return bool(w_item.get("buy") or w_item.get("sell"))

    def _df_to_rank_recs(df_rank) -> list:
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
                "url": str(r.get("明細網址", "")),
            })
        return recs

    updated_stocks = 0
    updated_days = 0
    skipped_days = 0

    for idx_c, code in enumerate(codes, start=1):
        c_name = get_stock_chinese_name(code)
        if progress_callback:
            progress_callback(idx_c - 1, total_codes, f"[{idx_c}/{total_codes}] 正在檢查 {code} {c_name}...")

        trade_dates = _get_stock_trade_dates_for_backfill(code)
        if not trade_dates:
            if progress_callback:
                progress_callback(idx_c, total_codes, f"[{idx_c}/{total_codes}] {code} {c_name} 無交易日資料，已略過")
            continue

        storage = StockChipStorage(code)
        total_len = len(trade_dates)
        latest_idx = total_len - 1
        start_pos = max(0, total_len - n_days)
        stock_changed = False
        stock_added_days = 0

        for target_idx in range(start_pos, total_len):
            end_date_str = trade_dates[target_idx]
            req_windows = (1, 10, 20, 60) if target_idx == latest_idx else (10, 20, 60)

            existing_bundle = storage.load_broker_range_rank(end_date_str)
            if existing_bundle is not None and all(_has_valid_win(existing_bundle, w) for w in req_windows):
                skipped_days += 1
                continue

            day_bundle = dict(existing_bundle) if isinstance(existing_bundle, dict) else {}
            missing_wins = [w for w in req_windows if not _has_valid_win(day_bundle, w)]
            has_new_valid = False

            for idx_w, w in enumerate(missing_wins):
                s_i = max(0, target_idx - w + 1)
                s_str = trade_dates[s_i]
                df_b, df_s = fetch_stock_broker_range_ranking(code, s_str, end_date_str)

                b_recs = _df_to_rank_recs(df_b)
                s_recs = _df_to_rank_recs(df_s)
                if b_recs or s_recs:
                    has_new_valid = True
                    label = end_date_str if w == 1 else f"{s_str} ~ {end_date_str}"
                    day_bundle[f"w{w}"] = {
                        "range_label": label,
                        "buy": b_recs,
                        "sell": s_recs,
                    }

                if idx_w < len(missing_wins) - 1:
                    time.sleep(0.05)

            if has_new_valid and day_bundle:
                storage.save_broker_range_rank(end_date_str, day_bundle, sync_cloud=False)
                updated_days += 1
                stock_added_days += 1
                stock_changed = True

            time.sleep(0.03)

        if stock_changed:
            _do_sync_db_push(code)
            updated_stocks += 1
            if progress_callback:
                progress_callback(
                    idx_c, total_codes,
                    f"[{idx_c}/{total_codes}] ✅ {code} {c_name} 新增 {stock_added_days} 日統計並已同步雲端（累計 {updated_stocks} 檔）"
                )
        else:
            if progress_callback:
                progress_callback(
                    idx_c, total_codes,
                    f"[{idx_c}/{total_codes}] ⏭️ {code} {c_name} 已有完整資料或無新資料"
                )

    return {
        "ok": True,
        "stocks_count": updated_stocks,
        "updated_days": updated_days,
        "skipped_days": skipped_days,
        "msg": (
            f"分點統計增補完成（近 {n_days} 日）：共掃描 {total_codes} 檔個股，"
            f"新寫入並同步雲端 {updated_stocks} 檔（{updated_days} 個交易日統計），"
            f"略過已有完整資料 {skipped_days} 日。"
        )
    }


def batch_backfill_broker_daily_series(recent_days: int = 5, progress_callback=None) -> dict:
    """
    【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    1. 修改目的：優先直接從資料庫已寫入的統計紀錄（broker_range_rank）讀取近 10/20/60 日前 5 名分點與明細網址，
       僅當資料庫尚無該日統計或缺少網址時才補查排行榜，大幅加速「增補近N日分點明細」執行速度。
    2. 防呆防錯原因：
       - 若該分點於 [60日起始日 ~ 基準日] 區間內資料庫已有逐日明細紀錄，則自動跳過不重複請求。
       - 單檔個股只要有任何新明細寫入即同步上傳 Google 雲端硬碟（_do_sync_db_push）。
    """
    from storage import _do_sync_db_push
    n_days = max(1, min(60, int(recent_days or 5)))
    codes = _collect_all_stock_db_codes()
    total_codes = len(codes)
    if total_codes == 0:
        return {"ok": False, "msg": "目前本地與雲端無任何已建立之台股個股資料庫。"}

    updated_stocks = 0
    saved_series_count = 0
    skipped_series_count = 0

    for idx_c, code in enumerate(codes, start=1):
        c_name = get_stock_chinese_name(code)
        if progress_callback:
            progress_callback(idx_c - 1, total_codes, f"[{idx_c}/{total_codes}] 正在檢查 {code} {c_name} 分點明細...")

        trade_dates = _get_stock_trade_dates_for_backfill(code)
        if not trade_dates:
            if progress_callback:
                progress_callback(idx_c, total_codes, f"[{idx_c}/{total_codes}] {code} {c_name} 無交易日資料，已略過")
            continue

        storage = StockChipStorage(code)
        total_len = len(trade_dates)
        start_pos = max(0, total_len - n_days)
        stock_changed = False
        stock_added_series = 0

        for target_idx in range(start_pos, total_len):
            end_date_str = trade_dates[target_idx]
            s_60_idx = max(0, target_idx - 60 + 1)
            earliest_start = trade_dates[s_60_idx]

            broker_url_map = {}
            cached_bundle = storage.load_broker_range_rank(end_date_str)
            if isinstance(cached_bundle, dict):
                for w in (10, 20, 60):
                    w_obj = cached_bundle.get(f"w{w}")
                    if isinstance(w_obj, dict):
                        for side_k in ("buy", "sell"):
                            for r in w_obj.get(side_k, [])[:5]:
                                b_name = str(r.get("name", "")).strip()
                                d_url = str(r.get("url", "")).strip()
                                if b_name and d_url and b_name not in broker_url_map:
                                    broker_url_map[b_name] = d_url

            if not broker_url_map:
                for idx_w, w in enumerate((10, 20, 60)):
                    s_i = max(0, target_idx - w + 1)
                    s_str = trade_dates[s_i]
                    df_b, df_s = fetch_stock_broker_range_ranking(code, s_str, end_date_str)

                    for df_side in (df_b, df_s):
                        if df_side is not None and not df_side.empty:
                            for _, row in df_side.head(5).iterrows():
                                b_name = str(row.get("分點名稱", "")).strip()
                                d_url = str(row.get("明細網址", "")).strip()
                                if b_name and d_url and b_name not in broker_url_map:
                                    broker_url_map[b_name] = d_url

                    if idx_w < 2:
                        time.sleep(0.05)

            for b_name, d_url in broker_url_map.items():
                existing_df = storage.load_broker_daily_series(b_name, earliest_start, end_date_str)
                if existing_df is not None and not existing_df.empty:
                    max_exist_d = str(existing_df["日期"].max())
                    if max_exist_d >= end_date_str:
                        skipped_series_count += 1
                        continue

                df_fresh = fetch_single_broker_daily_series(d_url, earliest_start, end_date_str)
                if df_fresh is not None and not df_fresh.empty:
                    storage.save_broker_daily_trades(b_name, df_fresh, sync_cloud=False)
                    saved_series_count += 1
                    stock_added_series += 1
                    stock_changed = True
                time.sleep(0.03)

        if stock_changed:
            _do_sync_db_push(code)
            updated_stocks += 1
            if progress_callback:
                progress_callback(
                    idx_c, total_codes,
                    f"[{idx_c}/{total_codes}] ✅ {code} {c_name} 抓到 {stock_added_series} 筆明細並已同步雲端（累計 {updated_stocks} 檔）"
                )
        else:
            if progress_callback:
                progress_callback(
                    idx_c, total_codes,
                    f"[{idx_c}/{total_codes}] ⏭️ {code} {c_name} 明細無需更新"
                )

    return {
        "ok": True,
        "stocks_count": updated_stocks,
        "saved_series": saved_series_count,
        "skipped_series": skipped_series_count,
        "msg": (
            f"分點逐日明細增補完成（近 {n_days} 日）：共掃描 {total_codes} 檔個股，"
            f"更新並同步雲端 {updated_stocks} 檔（新增 {saved_series_count} 筆分點 60 日逐日明細，"
            f"略過已有明細 {skipped_series_count} 筆）。"
        )
    }
