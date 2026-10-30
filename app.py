"""
大戶持股完整歷史爬取與 60 日數值檢測專用程式 (app.py)
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import sqlite3

class StockChipStorage:
    def __init__(self, pure_code):
        self.pure_code = pure_code
        self.db_path = f"data_{pure_code}.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shareholding_distribution (
                    date TEXT,
                    level INTEGER,
                    percent REAL,
                    PRIMARY KEY (date, level)
                )
            """)
            conn.commit()

    def load_holding_df(self):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT date, level, percent FROM shareholding_distribution ORDER BY date, level", conn)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df

    def save_holding_data(self, records):
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO shareholding_distribution (date, level, percent)
                VALUES (?, ?, ?)
            """, records)
            conn.commit()

def fetch_tdcc_history(pure_code):
    storage = StockChipStorage(pure_code)
    holding_df = storage.load_holding_df()
    existing_weeks = set(holding_df['date'].dt.strftime('%Y%m%d')) if not holding_df.empty else set()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.tdcc.com.tw/portal/zh/smWeb/qryStock',
        'Origin': 'https://www.tdcc.com.tw'
    }
    
    try:
        session_tdcc = requests.Session()
        url_tdcc = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
        r_init = session_tdcc.get(url_tdcc, headers=headers, timeout=10)
        soup_init = BeautifulSoup(r_init.text, 'html.parser')

        base_payload = {}
        for inp in soup_init.find_all('input'):
            n = inp.get('name')
            if n:
                base_payload[n] = inp.get('value', '')

        available_dates = []
        for o in soup_init.find_all('option'):
            v = o.get('value', '').strip()
            if v.isdigit() and len(v) == 8 and v.startswith('20'):
                available_dates.append(v)

        # 解除 15 週限制，抓取所有可取得的歷史週次以確保 10/16 以前有資料
        missing_dates = [d for d in available_dates if d not in existing_weeks]

        for d_str in missing_dates:
            payload = base_payload.copy()
            payload.update({
                'scaDate': d_str,
                'sqlMethod': 'StockNo',
                'stockNo': pure_code,
                'stockName': '',
                'sub': '查詢'
            })
            res_tdcc = session_tdcc.post(url_tdcc, data=payload, headers=headers, timeout=10)
            if res_tdcc.status_code == 200:
                soup_post = BeautifulSoup(res_tdcc.text, 'html.parser')
                tables = soup_post.find_all('table')
                hold_records = []
                for t in tables:
                    if "1,000,001" in t.get_text():
                        date_fmt = pd.to_datetime(d_str).strftime('%Y-%m-%d')
                        for tr in t.find_all('tr'):
                            cols = [td.get_text().strip().replace(',', '') for td in tr.find_all(['td', 'th'])]
                            if cols and cols[0] in [str(i) for i in range(1, 16)]:
                                lvl = int(cols[0])
                                if 1 <= lvl <= 15:
                                    hold_records.append((date_fmt, lvl, float(cols[-1].replace('%', ''))))
                        break
                if hold_records:
                    storage.save_holding_data(hold_records)
    except Exception as e:
        print(f"爬取錯誤: {e}")

HOLDING_LEVEL_MAP = {
    100: [8, 9, 10, 11, 12, 13, 14, 15],
    200: [9, 10, 11, 12, 13, 14, 15],
    400: [11, 12, 13, 14, 15],
    600: [12, 13, 14, 15],
    800: [13, 14, 15],
    1000: [15]
}

st.set_page_config(page_title="大戶持股完整檢測工具", layout="wide")
st.title("大戶持股完整歷史抓取與近 60 日對應檢測")

stock_code = st.text_input("輸入股票代號", value="2330")
major1_thresh = st.selectbox("大戶1門檻 (張)", [1000, 800, 600, 400, 200, 100], index=0)
major2_thresh = st.selectbox("大戶2門檻 (張)", [1000, 800, 600, 400, 200, 100], index=3)

if st.button("同步歷史並執行對應"):
    with st.spinner("正在從 TDCC 完整抓取歷史集保資料中..."):
        fetch_tdcc_history(stock_code)
    
    storage = StockChipStorage(stock_code)
    holding_df = storage.load_holding_df()
    
    if holding_df.empty:
        st.warning(f"[{stock_code}] 資料庫中查無大戶持股資料。")
    else:
        holding_df['date'] = pd.to_datetime(holding_df['date']).dt.normalize()
        
        m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
        m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

        def get_weekly_sum(levels):
            sub = holding_df[holding_df['level'].isin(levels)]
            if sub.empty:
                return pd.DataFrame(columns=['date', 'percent'])
            return sub.groupby('date')['percent'].sum().reset_index().sort_values('date')

        m1_weekly = get_weekly_sum(m1_levels)
        m2_weekly = get_weekly_sum(m2_levels)

        mock_dates = pd.date_range(end=pd.Timestamp.today(), periods=60, freq='B')
        trading_days = pd.DataFrame({'date': pd.to_datetime(mock_dates).normalize()}).sort_values('date')

        # 嚴格確保 direction='backward'：交易日只能對應「小於或等於該交易日」最近已公告的每週集保數據
        if not m1_weekly.empty:
            merged_m1 = pd.merge_asof(trading_days, m1_weekly, on='date', direction='backward')
            merged_m1.rename(columns={'percent': 'Major1_Pct'}, inplace=True)
        else:
            merged_m1 = trading_days.copy()
            merged_m1['Major1_Pct'] = np.nan

        if not m2_weekly.empty:
            merged_m2 = pd.merge_asof(trading_days, m2_weekly, on='date', direction='backward')
            merged_m2.rename(columns={'percent': 'Major2_Pct'}, inplace=True)
        else:
            merged_m2 = trading_days.copy()
            merged_m2['Major2_Pct'] = np.nan

        res_df = pd.merge(merged_m1, merged_m2, on='date', how='left')
        res_df['Date'] = res_df['date'].dt.strftime('%Y-%m-%d')
        res_df = res_df[['Date', 'Major1_Pct', 'Major2_Pct']]

        st.success(f"成功同步並完成 [{stock_code}] 近 60 個交易日大戶持股數值對應！")
        st.dataframe(res_df, use_container_width=True)
