"""
大戶持股近 60 日數值檢測專用程式 (app.py) - 修正版
"""

import streamlit as st
import pandas as pd
import numpy as np
from storage import StockChipStorage

HOLDING_LEVEL_MAP = {
    100: [8, 9, 10, 11, 12, 13, 14, 15],
    200: [9, 10, 11, 12, 13, 14, 15],
    400: [11, 12, 13, 14, 15],
    600: [12, 13, 14, 15],
    800: [13, 14, 15],
    1000: [15]
}

st.set_page_config(page_title="大戶持股檢測工具", layout="wide")
st.title("大戶持股近 60 日數值對應檢測 (修正版)")

stock_code = st.text_input("輸入股票代號", value="2330")
major1_thresh = st.selectbox("大戶1門檻 (張)", [1000, 800, 600, 400, 200, 100], index=0)
major2_thresh = st.selectbox("大戶2門檻 (張)", [1000, 800, 600, 400, 200, 100], index=3)

if st.button("開始抓取與對應"):
    try:
        storage = StockChipStorage(stock_code)
        holding_df = storage.load_holding_df()
        
        if holding_df.empty:
            st.warning(f"[{stock_code}] 資料庫中查無大戶持股資料。")
        else:
            # 標準化日期格式
            holding_df['date'] = pd.to_datetime(holding_df['date']).dt.normalize()
            
            m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
            m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

            # 彙整各週大戶持股百分比總和
            def get_weekly_sum(levels):
                sub = holding_df[holding_df['level'].isin(levels)]
                if sub.empty:
                    return pd.DataFrame(columns=['date', 'percent'])
                return sub.groupby('date')['percent'].sum().reset_index().sort_values('date')

            m1_weekly = get_weekly_sum(m1_levels)
            m2_weekly = get_weekly_sum(m2_levels)

            # 建立近 60 個交易日序列
            mock_dates = pd.date_range(end=pd.Timestamp.today(), periods=60, freq='B')
            trading_days = pd.DataFrame({'date': pd.to_datetime(mock_dates).normalize()}).sort_values('date')

            # 使用 merge_asof 進行向後對齊 (backward)，確保平日能正確對應到最近已公告的每週集保數據
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

            st.success(f"成功抓取並對應 [{stock_code}] 近 60 個交易日的大戶持股數值！")
            st.dataframe(res_df, use_container_width=True)
            
    except Exception as e:
        st.error(f"執行發生錯誤: {e}")
