"""
ftch_kline_chip.py - 日K線、三大法人與個股/大盤全市場資券籌碼擷取模組
(自 data_fetcher.py 依邏輯職責拆分，維持既有官方日K補齊、集保總股數優先與法人資券智慧增量同步機制)
版本: 202611242207
"""

import time
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from storage import (
    StockChipStorage,
    get_stock_chinese_name,
    is_tw_stock_or_etf,
)
from ftch_tdcc_dash import fetch_tdcc_holding_data

MODULE_NAME = "ftch_kline_chip"
MODULE_VERSION = "202611242207"

FINMIND_TOKEN = ""


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

    if is_tw_etf_or_stk:
        tdcc_tot = storage.get_latest_tdcc_total_shares()
        if tdcc_tot and tdcc_tot > 0:
            shares_outstanding = tdcc_tot

    ticker = yf.Ticker(target_ticker)
    if is_tw_etf_or_stk and not shares_outstanding:
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
                if not shares_outstanding:
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
    【修訂說明 2026-11-20】擷取上市大盤（^TWII）全市場每日融資/融券增減張數與餘額，以及上市融資金額增減與餘額（換算為億元）。
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
    【修訂說明 2026-11-20】擷取櫃買指數（^TWOII）全市場彙總信用交易統計（主資料源：嗨投資 https://histock.tw/stock/three.aspx?m=mg&no=TWOI）。
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

            mm_bal_yi = parse_num(cells[1])
            mm_diff_yi = parse_num(cells[2])
            s_bal_sheets = parse_num(cells[3])
            s_diff_sheets = parse_num(cells[4])

            rec_map[iso_date] = (
                iso_date,
                0.0,
                s_diff_sheets,
                0.0,
                s_bal_sheets,
                mm_diff_yi,
                mm_bal_yi
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
## EOF ftch_kline_chip.py
