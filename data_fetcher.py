""" 
data_fetcher.py - 資料抓取模組 (支援 Yahoo Finance、TPEx 官方指數備援與 FinMind 籌碼)
版本: 202611060900
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202611060900"

from typing import Tuple, Optional, List
import pandas as pd
import yfinance as yf
import requests
import time
from datetime import datetime, timedelta
from storage import StockChipStorage, get_stock_chinese_name

FINMIND_TOKEN = ""
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"

def fetch_stock_name(raw_ticker: str) -> str:
    return get_stock_chinese_name(raw_ticker)

def _fetch_tpex_index_k() -> pd.DataFrame:
    """自櫃買中心 (TPEx) 官方端點抓取櫃買指數歷史日 K 線"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    today = datetime.now()
    records = []
    
    # 抓取最近 4 個月份之櫃買指數月報
    for i in range(4):
        target_m = today - timedelta(days=i * 28)
        roc_year = target_m.year - 1911
        m_str = f"{target_m.month:02d}"
        url = f"https://www.tpex.org.tw/web/stock/aftertrading/index_info/index_info_result.php?l=zh-tw&d={roc_year}/{m_str}&_="
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                rows = data.get("aaData", [])
                for r in rows:
                    # 格式: [民國日期, 開盤, 最高, 最低, 收盤, 漲跌, 成交量(千股), 成交金額(千元), ...]
                    if len(r) >= 5:
                        date_parts = r[0].strip().split('/')
                        if len(date_parts) == 3:
                            ad_year = int(date_parts[0]) + 1911
                            d_str = f"{ad_year}-{int(date_parts[1]):02d}-{int(date_parts[2]):02d}"
                            
                            def parse_val(v):
                                return float(str(v).replace(',', '').strip())

                            try:
                                close_p = parse_val(r[4])
                                open_p = parse_val(r[1]) if r[1] != '--' else close_p
                                high_p = parse_val(r[2]) if r[2] != '--' else max(open_p, close_p)
                                low_p = parse_val(r[3]) if r[3] != '--' else min(open_p, close_p)
                                vol = parse_val(r[6]) * 1000 if len(r) >= 7 and r[6] != '--' else 0.0
                                records.append({
                                    "date": d_str,
                                    "Open": open_p,
                                    "High": high_p,
                                    "Low": low_p,
                                    "Close": close_p,
                                    "Volume": vol
                                })
                            except Exception:
                                continue
        except Exception:
            pass

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates(subset=['date']).sort_values('date').set_index('date')
    return df

def fetch_stock_daily_k(raw_ticker: str, period: str = "1y", base_date: Optional[str] = None, force_refresh: bool = False):
    pure_code = str(raw_ticker).strip()
    storage = StockChipStorage(pure_code)
    last_k_date = storage.get_latest_daily_k_date()
    db_df = storage.load_daily_k_df()

    # 1. 處理櫃買指數 (^TWOII)
    if pure_code.upper() in ["^TWOII", "TWOII"]:
        full_ticker = "^TWOII"
        shares_outstanding = 0
        if not db_df.empty and not force_refresh and last_k_date:
            latest_db_dt = pd.to_datetime(last_k_date)
            now = datetime.now()
            # 若已有當週或昨日資料且未到強制更新
            if (now - latest_db_dt).days <= 1:
                return db_df, full_ticker, shares_outstanding
        
        tpex_df = _fetch_tpex_index_k()
        if not tpex_df.empty:
            if not db_df.empty:
                combined = pd.concat([db_df, tpex_df])
                combined = combined[~combined.index.duplicated(keep='last')].sort_index()
            else:
                combined = tpex_df
            storage.save_daily_k_df(combined)
            return combined, full_ticker, shares_outstanding
        elif not db_df.empty:
            return db_df, full_ticker, shares_outstanding
        return None

    # 2. 處理加權指數 (^TWII) 與一般個股 / 海外市場指數
    if pure_code.startswith("^"):
        full_ticker = pure_code
    elif pure_code.isdigit():
        full_ticker = f"{pure_code}.TW"
    else:
        full_ticker = pure_code

    ticker = yf.Ticker(full_ticker)
    shares_outstanding = None
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
            days_since_holding = (now - pd.to_datetime(last_holding_date)).days
            if days_since_holding >= 6:
                if now.weekday() == 4 and now.hour < 19:
                    should_fetch_holding = False
                elif now.weekday() < 4:
                    should_fetch_holding = False
                else:
                    should_fetch_holding = True

    target_start_date = (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d')
    inst_query_start = (pd.to_datetime(last_inst_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_inst_date and not force_refresh else target_start_date
    margin_query_start = (pd.to_datetime(last_margin_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_margin_date and not force_refresh else target_start_date

    # 1. 抓取三大法人
    if should_fetch_inst:
        try:
            params = {
                "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id": pure_code,
                "start_date": inst_query_start,
                "token": FINMIND_TOKEN
            }
            res = requests.get(FINMIND_API_URL, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", [])
                if data:
                    inst_dict = {}
                    for item in data:
                        d = item.get("date")
                        name = item.get("name")
                        buy = item.get("buy", 0)
                        sell = item.get("sell", 0)
                        diff_sheets = (buy - sell) / 1000.0
                        if d not in inst_dict:
                            inst_dict[d] = {"Foreign_Net": 0.0, "Trust_Net": 0.0, "Dealer_Net": 0.0}
                        if name in ["Foreign_Investor", "外資及陸資"]:
                            inst_dict[d]["Foreign_Net"] += diff_sheets
                        elif name in ["Investment_Trust", "投信"]:
                            inst_dict[d]["Trust_Net"] += diff_sheets
                        elif name in ["Dealer", "自營商", "Dealer_self", "Dealer_Hedging"]:
                            inst_dict[d]["Dealer_Net"] += diff_sheets
                    
                    records = []
                    for d, vals in inst_dict.items():
                        records.append((d, vals["Foreign_Net"], vals["Trust_Net"], vals["Dealer_Net"]))
                    storage.save_institutional_data(records)
        except Exception:
            pass

    # 2. 抓取資券
    if should_fetch_margin:
        try:
            params = {
                "dataset": "TaiwanStockMarginPurchaseShortSale",
                "data_id": pure_code,
                "start_date": margin_query_start,
                "token": FINMIND_TOKEN
            }
            res = requests.get(FINMIND_API_URL, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", [])
                if data:
                    margin_records = []
                    for item in data:
                        d = item.get("date")
                        mbuy = item.get("MarginPurchaseBuy", 0)
                        msell = item.get("MarginPurchaseSell", 0)
                        mbal = item.get("MarginPurchaseTodayBalance", 0)
                        sbuy = item.get("ShortSaleBuy", 0)
                        ssell = item.get("ShortSaleSell", 0)
                        sbal = item.get("ShortSaleTodayBalance", 0)
                        margin_diff = mbuy - msell
                        short_diff = ssell - sbuy
                        margin_records.append((d, float(margin_diff), float(short_diff), float(mbal), float(sbal)))
                    storage.save_margin_data(margin_records)
        except Exception:
            pass

    # 3. 抓取集保大戶
    if should_fetch_holding:
        try:
            holding_query_start = (pd.to_datetime(last_holding_date) + timedelta(days=1)).strftime('%Y-%m-%d') if last_holding_date and not force_refresh else target_start_date
            params = {
                "dataset": "TaiwanStockHoldingSharesPer",
                "data_id": pure_code,
                "start_date": holding_query_start,
                "token": FINMIND_TOKEN
            }
            res = requests.get(FINMIND_API_URL, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", [])
                if data:
                    holding_records = []
                    for item in data:
                        d = item.get("date")
                        lvl = item.get("HoldingSharesLevel")
                        pct = item.get("percent", 0.0)
                        if lvl is not None:
                            holding_records.append((d, int(lvl), float(pct)))
                    storage.save_holding_data(holding_records)
        except Exception:
            pass

    return (storage.load_institutional_df(), storage.load_margin_df(), storage.load_holding_df())
