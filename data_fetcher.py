"""
data_fetcher.py - 整合技術與籌碼資料擷取模組 (支援含英文後綴台股ETF + 台灣時區校正 + 雲端增量累積分點引擎版)
版本: 202611141215
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
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202611141215"

from storage import (
    StockChipStorage,
    COMMON_STOCK_NAMES,
    load_stock_names_dict,
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


def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: str = None, force_refresh: bool = False):
    """
    自本地 SQLite 或官方 API / Yahoo Finance 擷取歷史日 K 線資料。
    支援台股個股及含英文後綴之 ETF（如 00632R、00664R、00676R、00631L）。
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
                if len(parts) >= 6 and parts[1].strip().upper() == pure_code:
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
                    if lvl_num is None:
                        if "1,000,001" in lvl_raw or "1000001" in lvl_raw:
                            lvl_num = 15
                        elif "800,001" in lvl_raw:
                            lvl_num = 14
                        elif "600,001" in lvl_raw:
                            lvl_num = 13
                        elif "400,001" in lvl_raw:
                            lvl_num = 12
                        elif "200,001" in lvl_raw:
                            lvl_num = 11
                        elif "100,001" in lvl_raw:
                            lvl_num = 10
                        elif "50,001" in lvl_raw:
                            lvl_num = 9
                        elif "40,001" in lvl_raw:
                            lvl_num = 8
                    if d_str and lvl_num is not None:
                        records.append((d_str, int(lvl_num), pct))
    except Exception:
        pass
    return records


# =====================================================================
# 個股與ETF券商分點進出排行與單次查詢+雲端增量累積引擎
# =====================================================================
def is_gov_broker_branch(broker_name: str) -> bool:
    clean_name = str(broker_name).strip()
    return any(clean_name.startswith(prefix) for prefix in GOV_BROKER_PREFIXES)


def _clean_broker_int(val_str: str) -> int:
    cleaned = re.sub(r"[,\s\xa0張]", "", str(val_str or ""))
    if cleaned in ("", "-", "--", "—"):
        return 0
    try:
        return int(float(cleaned))
    except Exception:
        return 0


def _normalize_tw_date(date_str: str) -> str:
    s = str(date_str).strip()
    m = re.match(r"^(\d{2,4})[/\-](\d{1,2})[/\-](\d{1,2})$", s)
    if not m:
        return s
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1911:
        y += 1911
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _build_detail_url_with_range(raw_href: str, s_mdj: str, e_mdj: str) -> str:
    full_url = urljoin(MDJ_BASE_DOMAIN, raw_href)
    parsed = urlparse(full_url)
    qs = parse_qs(parsed.query)
    qs["e"] = [s_mdj]
    qs["f"] = [e_mdj]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def fetch_stock_broker_range_ranking(stock_id: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    code_str = str(stock_id).strip().upper()
    if not code_str or code_str.startswith("^") or not is_tw_stock_or_etf(code_str):
        return pd.DataFrame(), pd.DataFrame()

    try:
        s_dt = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
        e_dt = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        s_mdj = f"{s_dt.year}-{s_dt.month}-{s_dt.day}"
        e_mdj = f"{e_dt.year}-{e_dt.month}-{e_dt.day}"
        main_url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code_str}&e={s_mdj}&f={e_mdj}"

        resp = requests.get(main_url, headers=MDJ_HEADERS, timeout=12)
        resp.encoding = "big5"
        if resp.status_code != 200:
            return pd.DataFrame(), pd.DataFrame()

        soup = BeautifulSoup(resp.text, "html.parser")
        buy_list = []
        sell_list = []

        for tbl in soup.find_all("table"):
            for tr in tbl.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                texts = [c.get_text(strip=True) for c in cells]
                if len(texts) in (8, 10):
                    half = len(texts) // 2
                    left_txt = texts[:half]
                    right_txt = texts[half:]
                    left_cells = cells[:half]
                    right_cells = cells[half:]

                    if left_txt[0] and left_txt[0] not in ("買超券商", "券商名稱", "分點") and any(c.isdigit() for c in left_txt[-1]):
                        a_tag = left_cells[0].find("a", href=True)
                        detail_url = _build_detail_url_with_range(a_tag["href"], s_mdj, e_mdj) if a_tag else ""
                        b_name = left_txt[0]
                        buy_list.append({
                            "分點名稱": b_name,
                            "體系": "八大官股" if is_gov_broker_branch(b_name) else "一般券商",
                            "買進(張)": _clean_broker_int(left_txt[1]),
                            "賣出(張)": _clean_broker_int(left_txt[2]),
                            "買賣超(張)": _clean_broker_int(left_txt[3]),
                            "佔比": left_txt[4] if len(left_txt) > 4 else "",
                            "明細網址": detail_url
                        })

                    if right_txt[0] and right_txt[0] not in ("賣超券商", "券商名稱", "分點") and any(c.isdigit() for c in right_txt[-1]):
                        a_tag = right_cells[0].find("a", href=True)
                        detail_url = _build_detail_url_with_range(a_tag["href"], s_mdj, e_mdj) if a_tag else ""
                        s_name = right_txt[0]
                        sell_list.append({
                            "分點名稱": s_name,
                            "體系": "八大官股" if is_gov_broker_branch(s_name) else "一般券商",
                            "買進(張)": _clean_broker_int(right_txt[1]),
                            "賣出(張)": _clean_broker_int(right_txt[2]),
                            "買賣超(張)": _clean_broker_int(right_txt[3]),
                            "佔比": right_txt[4] if len(right_txt) > 4 else "",
                            "明細網址": detail_url
                        })

        df_buy = pd.DataFrame(buy_list).drop_duplicates(subset=["分點名稱"]).reset_index(drop=True) if buy_list else pd.DataFrame()
        df_sell = pd.DataFrame(sell_list).drop_duplicates(subset=["分點名稱"]).reset_index(drop=True) if sell_list else pd.DataFrame()
        return df_buy, df_sell
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def fetch_single_broker_daily_series(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    if not detail_url:
        return pd.DataFrame()

    s_iso = str(start_date)[:10]
    e_iso = str(end_date)[:10]
    try:
        s_dt = datetime.strptime(s_iso, "%Y-%m-%d").date()
        e_dt = datetime.strptime(e_iso, "%Y-%m-%d").date()
        s_mdj = f"{s_dt.year}-{s_dt.month}-{s_dt.day}"
        e_mdj = f"{e_dt.year}-{e_dt.month}-{e_dt.day}"
        target_url = _build_detail_url_with_range(detail_url, s_mdj, e_mdj)

        resp = requests.get(target_url, headers=MDJ_HEADERS, timeout=12)
        resp.encoding = "big5"
        if resp.status_code != 200:
            return pd.DataFrame()

        soup = BeautifulSoup(resp.text, "html.parser")
        rows_out = []
        for tbl in soup.find_all("table"):
            for tr in tbl.find_all("tr"):
                tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(tds) >= 4 and re.match(r"^\d{2,4}[/\-]\d{1,2}[/\-]\d{1,2}$", tds[0]):
                    norm_date = _normalize_tw_date(tds[0])
                    if not (s_iso <= norm_date <= e_iso):
                        continue
                    buy_vol = _clean_broker_int(tds[1])
                    sell_vol = _clean_broker_int(tds[2])
                    net_vol = buy_vol - sell_vol
                    rows_out.append({
                        "日期": norm_date,
                        "買進(張)": buy_vol,
                        "賣出(張)": sell_vol,
                        "買賣超(張)": net_vol
                    })

        if not rows_out:
            return pd.DataFrame()

        return (
            pd.DataFrame(rows_out)
            .drop_duplicates(subset=["日期"], keep="last")
            .sort_values("日期", ascending=True)
            .reset_index(drop=True)
        )
    except Exception:
        return pd.DataFrame()


def fetch_and_sync_broker_daily_series(
    stock_id: str,
    broker_name: str,
    detail_url: str,
    start_date: str,
    end_date: str,
    sync_cloud: bool = True
) -> pd.DataFrame:
    storage = StockChipStorage(stock_id)
    df_fresh = fetch_single_broker_daily_series(detail_url, start_date, end_date)
    if df_fresh is not None and not df_fresh.empty:
        storage.save_broker_daily_trades(broker_name, df_fresh, sync_cloud=sync_cloud)
    df_merged = storage.load_broker_daily_series(broker_name, start_date, end_date)
    return df_merged if not df_merged.empty else df_fresh
# EOF data_fetcher.py
