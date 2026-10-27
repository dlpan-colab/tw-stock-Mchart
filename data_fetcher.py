"""
台股技術與籌碼分析系統 - 外部資料爬蟲與清洗模組
負責 yfinance 日 K 抓取、休市 0 成交量過濾、盤中補點防護、
TDCC 集保大戶分級增量爬蟲、FinMind 法人與資券同步、ISIN 股票中文名稱快取。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610271400"

import datetime
import io
import logging
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import (
    COMMON_STOCKS,
    DEFAULT_LOOKBACK_DAYS,
    TDCC_INCREMENTAL_WEEKS_LIMIT,
)
from storage import (
    db_manager,
    load_stock_names_cache,
    save_stock_names_cache,
)

# 靜音 yfinance 內部常見的 404 與冗餘日誌
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


# ==========================================
# 1. 股票中文名稱模組 (ISIN 與快取)
# ==========================================
def get_tw_stock_name(stock_id: str) -> str:
    """
    取得台股中文名稱：
    1. 查本地快取 tw_stock_names.json
    2. 查 config.py 內建常用字典
    3. 爬取臺灣證券交易所 ISIN 目錄並自動寫入快取
    """
    stock_id = str(stock_id).strip().upper()
    cache = load_stock_names_cache()

    if stock_id in cache:
        return cache[stock_id]
    if stock_id in COMMON_STOCKS:
        cache[stock_id] = COMMON_STOCKS[stock_id]
        save_stock_names_cache(cache)
        return cache[stock_id]

    # 嘗試從 TWSE ISIN 查詢
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"  # 上市
        resp = requests.get(url, timeout=10)
        resp.encoding = "big5-hkscs"

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"class": "h4"})
        if table:
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) > 1:
                    raw_code_name = tds[0].text.strip()
                    parts = raw_code_name.split("\u3000")
                    if len(parts) == 2:
                        code, name = parts[0].strip(), parts[1].strip()
                        cache[code] = name

        # 若未找到，查上櫃模式
        if stock_id not in cache:
            url_otc = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"  # 上櫃
            resp_otc = requests.get(url_otc, timeout=10)
            resp_otc.encoding = "big5-hkscs"
            soup_otc = BeautifulSoup(resp_otc.text, "html.parser")
            table_otc = soup_otc.find("table", {"class": "h4"})
            if table_otc:
                for tr in table_otc.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) > 1:
                        raw_code_name = tds[0].text.strip()
                        parts = raw_code_name.split("\u3000")
                        if len(parts) == 2:
                            code, name = parts[0].strip(), parts[1].strip()
                            cache[code] = name

        save_stock_names_cache(cache)
        if stock_id in cache:
            return cache[stock_id]
    except Exception as e:
        logger.warning(f"爬取 ISIN 中文名稱失敗: {e}")

    return stock_id


# ==========================================
# 2. yfinance 日 K 抓取與盤中補點防護
# ==========================================
def fetch_kline_data(stock_id: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> Tuple[pd.DataFrame, float]:
    """
    抓取台股日 K 資料並執行嚴格清洗：
    1. 支援上市 (.TW) 與上櫃 (.TWO) 自動嘗試。
    2. 強制全域過濾 df['Volume'] > 0，杜絕休市日假 K 線。
    3. 盤中補點防護：必須於 09:00 後且 fast_info.last_volume > 0 始補點。
    回傳 (清洗後日 K DataFrame, 總發行股數 shares_outstanding)。
    """
    import yfinance as yf

    stock_id = str(stock_id).strip().upper()
    end_dt = datetime.datetime.now()
    start_dt = end_dt - datetime.timedelta(days=int(lookback_days * 1.5))

    ticker_str = f"{stock_id}.TW"
    ticker = yf.Ticker(ticker_str)
    df = ticker.history(start=start_dt.strftime("%Y-%m-%d"), end=(end_dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d"), auto_adjust=False)

    if df.empty or len(df) < 5:
        ticker_str = f"{stock_id}.TWO"
        ticker = yf.Ticker(ticker_str)
        df = ticker.history(start=start_dt.strftime("%Y-%m-%d"), end=(end_dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d"), auto_adjust=False)

    if df.empty:
        return pd.DataFrame(), 0.0

    # 取得發行股數
    shares_outstanding = 0.0
    try:
        if hasattr(ticker, "fast_info") and ticker.fast_info:
            shares_outstanding = float(getattr(ticker.fast_info, "shares", 0.0) or 0.0)
    except Exception:
        shares_outstanding = 0.0

    # 索引時區正規化為 YYYY-MM-DD 字串
    df.index = pd.to_datetime(df.index).tz_localize(None).strftime("%Y-%m-%d")
    df.index.name = "Date"
    df = df.reset_index().drop_duplicates(subset=["Date"], keep="last").set_index("Date")

    # 【避坑規範 1】：強制過濾 Volume > 0，剔除休市日填補昨收的假 K 線
    df = df[df["Volume"] > 0].copy()

    # 【避坑規範 2】：盤中即時資料補點 (fast_info)
    try:
        now_dt = datetime.datetime.now()
        is_weekday = now_dt.weekday() < 5
        is_after_market_open = now_dt.time() >= datetime.time(9, 0)

        if is_weekday and is_after_market_open and hasattr(ticker, "fast_info") and ticker.fast_info:
            fast = ticker.fast_info
            last_vol = float(getattr(fast, "last_volume", 0) or 0)
            last_price = float(getattr(fast, "last_price", 0) or 0)
            today_str = now_dt.strftime("%Y-%m-%d")

            if last_vol > 0 and last_price > 0:
                # 若當日尚未收錄，或最後一筆成交量落後於 fast_info，執行補點
                if (today_str not in df.index) or (today_str == df.index[-1] and last_vol > df.loc[today_str, "Volume"]):
                    open_p = float(getattr(fast, "open", last_price) or last_price)
                    day_h = float(getattr(fast, "day_high", last_price) or last_price)
                    day_l = float(getattr(fast, "day_low", last_price) or last_price)

                    df.loc[today_str, "Open"] = open_p
                    df.loc[today_str, "High"] = max(day_h, last_price)
                    df.loc[today_str, "Low"] = min(day_l, last_price)
                    df.loc[today_str, "Close"] = last_price
                    df.loc[today_str, "Volume"] = last_vol
    except Exception as e:
        logger.warning(f"盤中補點防護檢查異常 (忽略並保留現有日 K): {e}")

    # 確保數值型別完整
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    df = df[df["Volume"] > 0]

    return df.tail(lookback_days), shares_outstanding


# ==========================================
# 3. 集保中心 (TDCC) 股權分級增量爬蟲
# ==========================================
def sync_tdcc_distribution(stock_id: str) -> pd.DataFrame:
    """
    集保大戶持股爬蟲（嚴格避坑規範）：
    1. 使用 requests.Session() 保持 Cookie。
    2. 動態解析首頁 action URL 與 <select> 中實際可用的 8 碼日期（YYYYMMDD）。
    3. 比對本地 SQLite 已有週別，僅增量抓取缺失週別，上限 15 週以防封鎖 IP。
    4. 精確定位首欄含 '1' 與 '15' 的表格，儲存入庫。
    """
    stock_id = str(stock_id).strip().upper()
    existing_dates = set(db_manager.get_existing_tdcc_dates(stock_id))

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    })

    base_url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"

    try:
        resp = session.get(base_url, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 取得動態表單 action URL
        form = soup.find("form", id="form1") or soup.find("form")
        action_url = base_url
        if form and form.get("action"):
            action_url = urllib.parse.urljoin(base_url, form.get("action"))

        # 解析可查詢日期 (8碼數字)
        date_select = soup.find("select", {"id": "scaDates"}) or soup.find("select", {"name": "scaDates"})
        available_dates: List[str] = []
        if date_select:
            for opt in date_select.find_all("option"):
                val = opt.get("value", "").strip()
                if re.match(r"^\d{8}$", val):
                    available_dates.append(val)

        available_dates = sorted(available_dates, reverse=True)
        # 比對本地缺失日期（上限 15 週）
        missing_dates = [d for d in available_dates if d not in existing_dates][:TDCC_INCREMENTAL_WEEKS_LIMIT]

        crawled_dfs = []
        for d_str in missing_dates:
            payload = {
                "scaDates": d_str,
                "scaDate": d_str,
                "StockNo": stock_id,
                "stockNo": stock_id,
                "sub": "查詢",
                "ReqID": ""
            }

            post_resp = session.post(action_url, data=payload, timeout=15)
            post_resp.encoding = "utf-8"
            post_soup = BeautifulSoup(post_resp.text, "html.parser")

            # 鎖定包含等級 1 與 15 的股權分級表格
            target_table = None
            for tbl in post_soup.find_all("table"):
                text = tbl.get_text()
                if "持股分級" in text or ("1" in text and "15" in text and "合計" in text):
                    target_table = tbl
                    break

            if not target_table:
                continue

            # 計算 ISO 週別
            dt_obj = datetime.datetime.strptime(d_str, "%Y%m%d")
            iso_year, iso_week, _ = dt_obj.isocalendar()
            year_week_str = f"{iso_year}-W{iso_week:02d}"

            rows_data = []
            for tr in target_table.find_all("tr"):
                cols = [td.get_text(strip=True).replace(",", "") for td in tr.find_all(["td", "th"])]
                if len(cols) >= 5 and cols[0].isdigit():
                    lvl = int(cols[0])
                    if 1 <= lvl <= 15:
                        holders = int(cols[2]) if cols[2].isdigit() else 0
                        shares = int(cols[3]) if cols[3].isdigit() else 0
                        try:
                            ratio = float(cols[4])
                        except ValueError:
                            ratio = 0.0

                        rows_data.append({
                            "date": d_str,
                            "year_week": year_week_str,
                            "level": lvl,
                            "holders": holders,
                            "shares": shares,
                            "ratio": ratio
                        })

            if len(rows_data) == 15:
                df_week = pd.DataFrame(rows_data)
                db_manager.save_tdcc_data(stock_id, df_week)
                crawled_dfs.append(df_week)

    except Exception as e:
        logger.warning(f"TDCC 增量爬取異常 ({stock_id}): {e}")

    # 回傳該股票完整的集保資料庫紀錄
    return db_manager.get_tdcc_data(stock_id)


# ==========================================
# 4. FinMind API (三大法人與融資融券)
# ==========================================
def sync_finmind_chip_data(stock_id: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
    """
    從 FinMind API 抓取三大法人與融資融券資料：
    1. 三大法人買賣股數必須除以 1000 換算為「張」。
    2. 券資比公式：(融券餘額 / 融資餘額) * 100%。
    3. 清洗後直接存入 SQLite 本地資料庫。
    """
    stock_id = str(stock_id).strip().upper()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=int(lookback_days * 1.5))).strftime("%Y-%m-%d")

    # 1. 抓取三大法人 (TaiwanStockInstitutionalInvestorsBuySell)
    try:
        url_inst = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={stock_id}&start_date={start_date}"
        r_inst = requests.get(url_inst, timeout=12)
        data_inst = r_inst.json().get("data", [])

        if data_inst:
            df_raw = pd.DataFrame(data_inst)
            # 轉換為張數：股數 / 1000
            df_pivot = df_raw.pivot_table(
                index="date",
                columns="name",
                values=["buy", "sell"],
                aggfunc="sum"
            ).fillna(0)

            records = []
            for date_val, row in df_pivot.iterrows():
                f_buy = row.get(("buy", "Foreign_Investor"), 0) / 1000.0
                f_sell = row.get(("sell", "Foreign_Investor"), 0) / 1000.0
                t_buy = row.get(("buy", "Investment_Trust"), 0) / 1000.0
                t_sell = row.get(("sell", "Investment_Trust"), 0) / 1000.0
                d_buy = row.get(("buy", "Dealer_self"), 0) / 1000.0 + row.get(("buy", "Dealer_Hedging"), 0) / 1000.0
                d_sell = row.get(("sell", "Dealer_self"), 0) / 1000.0 + row.get(("sell", "Dealer_Hedging"), 0) / 1000.0

                f_net = f_buy - f_sell
                t_net = t_buy - t_sell
                d_net = d_buy - d_sell

                records.append({
                    "date": str(date_val),
                    "foreign_buy_sell": round(f_net, 2),
                    "trust_buy_sell": round(t_net, 2),
                    "dealer_buy_sell": round(d_net, 2),
                    "total_buy_sell": round(f_net + t_net + d_net, 2),
                })

            if records:
                db_manager.save_institutional_data(stock_id, pd.DataFrame(records))
    except Exception as e:
        logger.warning(f"FinMind 三大法人同步異常: {e}")

    # 2. 抓取融資融券 (TaiwanStockMarginPurchaseShortSale)
    try:
        url_margin = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id={stock_id}&start_date={start_date}"
        r_margin = requests.get(url_margin, timeout=12)
        data_margin = r_margin.json().get("data", [])

        if data_margin:
            df_margin = pd.DataFrame(data_margin)
            records = []
            for _, row in df_margin.iterrows():
                m_buy = float(row.get("MarginPurchaseBuy", 0))
                m_sell = float(row.get("MarginPurchaseSell", 0))
                m_bal = float(row.get("MarginPurchaseTodayBalance", 0))

                s_buy = float(row.get("ShortSaleBuy", 0))
                s_sell = float(row.get("ShortSaleSell", 0))
                s_bal = float(row.get("ShortSaleTodayBalance", 0))

                # 券資比公式計算
                ratio = (s_bal / m_bal * 100.0) if m_bal > 0 else 0.0

                records.append({
                    "date": str(row["date"]),
                    "margin_buy": m_buy,
                    "margin_sell": m_sell,
                    "margin_balance": m_bal,
                    "short_buy": s_buy,
                    "short_sell": s_sell,
                    "short_balance": s_bal,
                    "margin_short_ratio": round(ratio, 2)
                })

            if records:
                db_manager.save_margin_data(stock_id, pd.DataFrame(records))
    except Exception as e:
        logger.warning(f"FinMind 融資融券同步異常: {e}")
