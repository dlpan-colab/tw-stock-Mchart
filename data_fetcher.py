"""
data_fetcher.py - 資料獲取與籌碼資料同步模組
版本: dat_202610311200
"""

import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta

MODULE_VERSION = "dat_202610311200"

def fetch_stock_daily_k(stock_code: str, period: str = "1y"):
    """
    獲取台股日 K 線資料，依序嘗試上市代碼 (.TW) 與上櫃代碼 (.TWO)
    """
    stock_code = str(stock_code).strip()
    ticker_tw = f"{stock_code}.TW"
    ticker_two = f"{stock_code}.TWO"

    df = yf.download(ticker_tw, period=period, progress=False)
    ticker_used = ticker_tw

    if df.empty or len(df) < 5:
        df = yf.download(ticker_two, period=period, progress=False)
        ticker_used = ticker_two

    if df.empty:
        return None, "", 0

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df.index = pd.to_datetime(df.index).normalize()
    df.sort_index(inplace=True)

    # 取得發行股數估算 (若無法取得則回傳 0)
    shares = 0
    try:
        t = yf.Ticker(ticker_used)
        shares = t.info.get('sharesOutstanding', 0)
    except Exception:
        shares = 0

    return df, ticker_used, shares

def fetch_stock_name(stock_code: str) -> str:
    """
    查詢台股股票名稱
    """
    stock_code = str(stock_code).strip()
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_code}.tw|otc_{stock_code}.two"
        res = requests.get(url, timeout=5).json()
        msg_array = res.get('msgArray', [])
        if msg_array:
            return msg_array[0].get('n', stock_code)
    except Exception:
        pass
    return stock_code

def sync_chip_data(stock_code: str, target_dates: pd.DatetimeIndex):
    """
    下載並標準化法人、資券與大戶持股資料
    確保 date 索引為 DatetimeIndex 且型態標準，能與 target_dates 完美對齊
    """
    stock_code = str(stock_code).strip()
    start_str = (target_dates.min() - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
    end_str = target_dates.max().strftime('%Y-%m-%d')

    inst_df = pd.DataFrame()
    margin_df = pd.DataFrame()
    holding_df = pd.DataFrame()

    # 1. 三大法人買賣超 (FinMind 免費公開端點)
    try:
        url_inst = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={stock_code}&start_date={start_str}&end_date={end_str}"
        resp_inst = requests.get(url_inst, timeout=6).json()
        if resp_inst.get("msg") == "success" and resp_inst.get("data"):
            raw_inst = pd.DataFrame(resp_inst["data"])
            raw_inst['date'] = pd.to_datetime(raw_inst['date']).dt.normalize()
            # 依身份彙整 (張數單位)
            pivot_inst = raw_inst.pivot_table(index='date', columns='name', values='buy', aggfunc='sum').fillna(0) - \
                         raw_inst.pivot_table(index='date', columns='name', values='sell', aggfunc='sum').fillna(0)
            
            inst_df = pd.DataFrame(index=pivot_inst.index)
            # 轉換股數至張數 (/1000)
            inst_df['foreign_net'] = (pivot_inst.get('Foreign_Investor', 0) / 1000).round(1)
            inst_df['trust_net'] = (pivot_inst.get('Investment_Trust', 0) / 1000).round(1)
            inst_df['dealer_net'] = (pivot_inst.get('Dealer_self', 0) / 1000 + pivot_inst.get('Dealer_Hedging', 0) / 1000).round(1)
            inst_df.reset_index(inplace=True)
    except Exception:
        inst_df = pd.DataFrame()

    # 2. 融資融券增減
    try:
        url_margin = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id={stock_code}&start_date={start_str}&end_date={end_str}"
        resp_margin = requests.get(url_margin, timeout=6).json()
        if resp_margin.get("msg") == "success" and resp_margin.get("data"):
            raw_margin = pd.DataFrame(resp_margin["data"])
            raw_margin['date'] = pd.to_datetime(raw_margin['date']).dt.normalize()
            raw_margin.set_index('date', inplace=True)

            margin_df = pd.DataFrame(index=raw_margin.index)
            # 融資增減、融券增減 (張數單位)
            margin_df['margin_diff'] = raw_margin.get('MarginPurchaseTodayBalance', 0) - raw_margin.get('MarginPurchaseYesterdayBalance', 0)
            margin_df['short_diff'] = raw_margin.get('ShortSaleTodayBalance', 0) - raw_margin.get('ShortSaleYesterdayBalance', 0)
            margin_df['margin_bal'] = raw_margin.get('MarginPurchaseTodayBalance', 0)
            margin_df['short_bal'] = raw_margin.get('ShortSaleTodayBalance', 0)
            margin_df.reset_index(inplace=True)
    except Exception:
        margin_df = pd.DataFrame()

    # 3. 集保大戶股權分散 (週資料)
    try:
        url_holding = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockHoldingSharesPer&data_id={stock_code}&start_date={start_str}&end_date={end_str}"
        resp_holding = requests.get(url_holding, timeout=6).json()
        if resp_holding.get("msg") == "success" and resp_holding.get("data"):
            raw_holding = pd.DataFrame(resp_holding["data"])
            raw_holding['date'] = pd.to_datetime(raw_holding['date']).dt.normalize()
            holding_df = raw_holding[['date', 'level', 'percent']].copy()
    except Exception:
        holding_df = pd.DataFrame()

    return inst_df, margin_df, holding_df
