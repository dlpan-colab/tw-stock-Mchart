"""
台股技術與籌碼分析系統 - 資料擷取模組
負責股價歷史資料、三大法人、資券餘額、集保分散表及中文名稱抓取。
"""

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202610300900"

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from FinMind.data import DataLoader

from storage import StockChipStorage, is_valid_tw_stock_name


def fetch_stock_name(pure_code: str) -> str:
    """
    強固型中文名稱抓取：依序透過 TWSE/TPEX 查詢、Yahoo Finance 標題爬蟲與 FinMind 資訊。
    """
    pure_code = str(pure_code).strip().upper()
    
    # 1. 嘗試從 FinMind 取得台灣股票基本資料
    try:
        api_token = os.environ.get("FINMIND_TOKEN", "")
        dl = DataLoader()
        if api_token:
            dl.login_by_token(api_token)
        df_info = dl.taiwan_stock_info()
        if not df_info.empty:
            match = df_info[df_info['stock_id'] == pure_code]
            if not match.empty:
                name = str(match.iloc[0].get('stock_name', '')).strip()
                if is_valid_tw_stock_name(name):
                    return name
    except Exception:
        pass

    # 2. 嘗試從 Yahoo Finance 抓取網頁標題解析
    try:
        url = f"https://finance.yahoo.com/quote/{pure_code}.TW"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title_tag = soup.find('title')
            if title_tag:
                title_text = title_tag.text
                # 範例格式: "台積電 (2330.TW) Stock Price..."
                if '(' in title_text:
                    name = title_text.split('(')[0].strip()
                    if is_valid_tw_stock_name(name):
                        return name
    except Exception:
        pass

    # 3. 嘗試上櫃尾綴 .TWO
    try:
        url = f"https://finance.yahoo.com/quote/{pure_code}.TWO"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title_tag = soup.find('title')
            if title_tag:
                title_text = title_tag.text
                if '(' in title_text:
                    name = title_text.split('(')[0].strip()
                    if is_valid_tw_stock_name(name):
                        return name
    except Exception:
        pass

    return pure_code


def sync_chip_data(pure_code: str, storage: StockChipStorage, status_placeholder=None):
    """
    同步三大法人、資券餘額與集保大戶資料
    """
    api_token = os.environ.get("FINMIND_TOKEN", "")
    dl = DataLoader()
    if api_token:
        dl.login_by_token(api_token)

    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    # 1. 三大法人
    inst_df = pd.DataFrame()
    try:
        df_inst = dl.taiwan_stock_institutional_investors(
            stock_id=pure_code, start_date=start_date
        )
        if not df_inst.empty:
            # 整理三大法人買賣超
            piv = df_inst.pivot_table(index='date', columns='name', values='buy_sell', aggfunc='sum').fillna(0)
            # 對應欄位：外資、投信、自營商
            cols = piv.columns
            f_col = next((c for c in cols if '外資' in c), None)
            t_col = next((c for c in cols if '投信' in c), None)
            d_col = next((c for c in cols if '自營' in c), None)
            
            records = []
            for d, row in piv.iterrows():
                f_val = row[f_col] if f_col else 0.0
                t_val = row[t_col] if t_col else 0.0
                d_val = row[d_col] if d_col else 0.0
                records.append((str(d)[:10], float(f_val), float(t_val), float(d_val)))
            storage.save_institutional_data(records)
            inst_df = storage.load_institutional_df()
    except Exception:
        inst_df = storage.load_institutional_df()

    # 2. 資券餘額
    margin_df = pd.DataFrame()
    try:
        df_margin = dl.taiwan_stock_margin_purchase_short_sale(
            stock_id=pure_code, start_date=start_date
        )
        if not df_margin.empty:
            records = []
            for _, row in df_margin.iterrows():
                d = str(row.get('date', ''))[:10]
                m_diff = float(row.get('margin_purchase_today_balance', 0) - row.get('margin_purchase_yesterday_balance', 0))
                s_diff = float(row.get('short_sale_today_balance', 0) - row.get('short_sale_yesterday_balance', 0))
                m_bal = float(row.get('margin_purchase_today_balance', 0))
                s_bal = float(row.get('short_sale_today_balance', 0))
                records.append((d, m_diff, s_diff, m_bal, s_bal))
            storage.save_margin_data(records)
            margin_df = storage.load_margin_df()
    except Exception:
        margin_df = storage.load_margin_df()

    # 3. 集保戶股權分散表 (TDCC OpenData)
    holding_df = pd.DataFrame()
    try:
        url = f"https://www.tdcc.com.tw/portal/zh/smc/infocode?stockId={pure_code}"
        # 透過 FinMind 或 TDCC OpenData 取得集保資料
        df_holding = dl.taiwan_stock_holding_shares_per(stock_id=pure_code, start_date=start_date)
        if not df_holding.empty:
            records = []
            for _, row in df_holding.iterrows():
                d = str(row.get('date', ''))[:10]
                level = int(row.get('holding_shares_level', 0))
                pct = float(row.get('percent', 0.0))
                records.append((d, level, pct))
            storage.save_holding_data(records)
            holding_df = storage.load_holding_df()
    except Exception:
        holding_df = storage.load_holding_df()

    return inst_df, margin_df, holding_df
