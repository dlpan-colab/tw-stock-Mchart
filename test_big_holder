"""
大戶持股正確週對齊測試程式 (app.py) - 完整顯示 15 週版
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
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
        st.error(f"爬取錯誤: {e}")

HOLDING_LEVEL_MAP = {
    100: [8, 9, 10, 11, 12, 13, 14, 15],
    200: [9, 10, 11, 12, 13, 14, 15],
    400: [11, 12, 13, 14, 15],
    600: [12, 13, 14, 15],
    800: [13, 14, 15],
    1000: [15]
}

st.set_page_config(page_title="大戶持股週歸屬對齊檢測", layout="wide")
st.title("大戶持股依週精準歸屬檢測（完整 15 週）")

stock_code = st.text_input("輸入股票代號", value="2330")
major1_thresh = st.selectbox("大戶1門檻 (張)", [1000, 800, 600, 400, 200, 100], index=0)
major2_thresh = st.selectbox("大戶2門檻 (張)", [1000, 800, 600, 400, 200, 100], index=3)

if st.button("同步歷史並執行對齊"):
    with st.spinner("正在爬取 TDCC 歷史資料..."):
        fetch_tdcc_history(stock_code)
    
    storage = StockChipStorage(stock_code)
    holding_df = storage.load_holding_df()
    
    if holding_df.empty:
        st.warning(f"[{stock_code}] 資料庫無資料。")
    else:
        holding_df['date'] = pd.to_datetime(holding_df['date']).dt.normalize()
        holding_df['week_key'] = holding_df['date'].dt.strftime('%G-%V')

        m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
        m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

        def calc_weekly_summary(levels):
            sub = holding_df[holding_df['level'].isin(levels)]
            if sub.empty:
                return pd.DataFrame(columns=['week_key', 'percent'])
            sub_sorted = sub.sort_values('date')
            weekly = sub_sorted.groupby(['week_key', 'date'])['percent'].sum().reset_index()
            weekly_last = weekly.groupby('week_key').last().reset_index()[['week_key', 'percent']]
            return weekly_last

        m1_weekly = calc_weekly_summary(m1_levels).rename(columns={'percent': 'Major1_Pct'})
        m2_weekly = calc_weekly_summary(m2_levels).rename(columns={'percent': 'Major2_Pct'})

        # 生成 15 週交易日（15 週 * 5 工作日 = 75 天）
        trading_dates = pd.date_range(end=pd.Timestamp.today(), periods=75, freq='B')
        trading_df = pd.DataFrame({'date': pd.to_datetime(trading_dates).normalize()})
        trading_df['week_key'] = trading_df['date'].dt.strftime('%G-%V')

        merged_df = pd.merge(trading_df, m1_weekly, on='week_key', how='left')
        merged_df = pd.merge(merged_df, m2_weekly, on='week_key', how='left')

        merged_df['Date'] = merged_df['date'].dt.strftime('%Y-%m-%d')
        result_df = merged_df[['Date', 'Major1_Pct', 'Major2_Pct']].sort_values('Date')

        st.success(f"完成 [{stock_code}] 大戶持股完整 15 週對齊檢測（共 {len(result_df)} 筆交易日）")
        st.dataframe(result_df, use_container_width=True, height=800)
