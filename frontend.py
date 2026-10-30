"""
台股技術與籌碼分析系統 - 前端介面與互動控制模組
"""

MODULE_NAME = "frontend"
MODULE_VERSION = "202610300900"

import streamlit as st
import pandas as pd
from datetime import datetime

from storage import (
    StockChipStorage,
    load_stock_history,
    save_stock_history,
    clear_stock_history
)
from data_fetcher import fetch_stock_name, sync_chip_data
from indicators import calculate_all_indicators
from chart_builder import create_stock_chart


def render_sidebar():
    st.sidebar.title("台股技術與籌碼分析")
    
    # 輸入股票代號
    code_input = st.sidebar.text_input("輸入股票代號", value="2330").strip().upper()
    
    # 歷史紀錄清單
    st.sidebar.markdown("---")
    st.sidebar.subheader("最近查詢紀錄")
    
    history_list = load_stock_history()
    for item in history_list:
        c = item.get("code")
        n = item.get("name", c)
        if st.sidebar.button(f"{c} {n}", key=f"hist_{c}"):
            code_input = c
            st.rerun()

    if st.sidebar.button("清除歷史紀錄", key="clear_hist"):
        clear_stock_history()
        st.rerun()

    st.sidebar.markdown("---")
    major1_thresh = st.sidebar.selectbox("大戶持股計算級距 1", [1000, 800, 600, 400, 200, 100], index=0)
    major2_thresh = st.sidebar.selectbox("大戶持股計算級距 2", [400, 600, 800, 1000], index=0)
    
    shares_outstanding = st.sidebar.number_input("總發行張數 (預設留空由系統計算)", value=0.0, step=1000.0)

    return code_input, major1_thresh, major2_thresh, shares_outstanding


def render_main_content(code: str, major1_thresh: int, major2_thresh: int, shares_outstanding: float):
    if not code:
        st.warning("請輸入有效的股票代號。")
        return

    # 取得中文名稱
    stock_name = fetch_stock_name(code)
    
    # 儲存至歷史清單
    save_stock_history(code, stock_name)

    st.header(f"{code} {stock_name}")

    # 初始化資料庫與同步
    storage = StockChipStorage(code)
    
    with st.spinner("正在載入股價與籌碼資料..."):
        from data_fetcher import DataLoader
        import yfinance as yf
        
        # 抓取股價歷史
        df = yf.download(f"{code}.TW", period="1y", progress=False)
        if df.empty:
            df = yf.download(f"{code}.TWO", period="1y", progress=False)
            
        if df.empty:
            st.error(f"無法取得代號 {code} 之股價資料。")
            return

        # 處理 MultiIndex 欄位
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # 計算指標與籌碼
        df = calculate_all_indicators(
            df=df,
            pure_code=code,
            major1_thresh=major1_thresh,
            major2_thresh=major2_thresh,
            shares_outstanding=shares_outstanding if shares_outstanding > 0 else None
        )

    # 繪製圖表
    fig = create_stock_chart(df, stock_name, code)
    st.plotly_chart(fig, use_container_width=True)

    # 數值摘要表格
    st.subheader("近期籌碼與技術摘要")
    if not df.empty:
        latest = df.iloc[-1]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("收盤價", f"{latest.get('Close', 0):.2f}")
        col2.metric("5日均價", f"{latest.get('MA5', 0):.2f}")
        col3.metric("換手率 (%)", f"{latest.get('Turnover_Rate', 0):.2f}%" if pd.notna(latest.get('Turnover_Rate')) else "N/A")
        col4.metric("外資買賣超", f"{latest.get('Foreign_Net', 0):,.0f} 張")
