"""
台股技術與籌碼分析系統 - 前端介面與參數設定模組
"""

MODULE_NAME = "frontend"
MODULE_VERSION = "202610301500"

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
    st.sidebar.markdown(f"`{MODULE_VERSION}` 台股技術與籌碼分析")
    
    # 初始化 session state 歷史紀錄與預設值
    if "history_list" not in st.session_state:
        st.session_state.history_list = load_stock_history()

    def on_hist_change():
        selected = st.session_state.get("hist_select")
        if selected and selected != "(選擇歷史標的)":
            # 抽出代號
            code_part = selected.split(" ")[0]
            st.session_state["ticker_input_field"] = code_part

    hist = st.session_state.history_list
    hist_options = ["(選擇歷史標的)"] + [f"{h.get('code')} {h.get('name', '')}".strip() for h in hist]

    st.sidebar.selectbox(
        "歷史紀錄快速選取",
        options=hist_options,
        index=0,
        key="hist_select",
        on_change=on_hist_change
    )

    s_ticker = st.sidebar.text_input(
        "股票代號/ 名稱",
        key="ticker_input_field",
        value="6234"
    ).strip()

    s_days = st.sidebar.number_input(
        "顯示日數",
        min_value=5,
        max_value=120,
        value=240,
        step=5
    )

    s_period = st.sidebar.selectbox(
        "資料週期",
        options=["6mo", "1y", "2y"],
        index=1
    )

    use_base_date = st.sidebar.checkbox("指定基準日(復盤模式)", value=False)
    s_base_date = None
    if use_base_date:
        s_base_date = st.sidebar.date_input("基準日期", value=datetime.today())

    st.sidebar.subheader("大戶門檻設定")
    col_m1, col_m2 = st.sidebar.columns(2)
    with col_m1:
        s_m1 = st.selectbox("大戶門檻1 (張)", options=[100, 200, 400, 600, 800, 1000], index=5)
    with col_m2:
        s_m2 = st.selectbox("大戶門檻2 (張)", options=[100, 200, 400, 600, 800, 1000], index=2)

    is_mobile = st.sidebar.checkbox("手機緊湊版面優化", value=True)

    col_b1, col_b2 = st.sidebar.columns([1, 1])
    with col_b1:
        s_btn = st.button("查詢", type="primary", use_container_width=True)
    with col_b2:
        c_btn = st.button("清除歷史", use_container_width=True)

    if c_btn:
        st.session_state.history_list = clear_stock_history()
        st.rerun()

    # 提取純代號（支援使用者輸入如 "6234 高橋" 或純數字）
    pure_code = s_ticker.split(" ")[0] if s_ticker else "6234"

    return pure_code, s_days, s_period, use_base_date, s_base_date, s_m1, s_m2, is_mobile


def render_main_content(pure_code: str, s_days: int, s_period: str, use_base_date: bool, s_base_date, s_m1: int, s_m2: int, is_mobile: bool):
    if not pure_code:
        st.warning("請輸入有效的股票代號。")
        return

    stock_name = fetch_stock_name(pure_code)
    save_stock_history(pure_code, stock_name)

    storage = StockChipStorage(pure_code)
    
    with st.spinner("正在載入股價與籌碼資料..."):
        import yfinance as yf
        df = yf.download(f"{pure_code}.TW", period=s_period, progress=False)
        if df.empty:
            df = yf.download(f"{pure_code}.TWO", period=s_period, progress=False)
            
        if df.empty:
            st.error(f"無法取得代號 {pure_code} 之股價資料。")
            return

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if use_base_date and s_base_date:
            df = df[df.index.date <= s_base_date]

        if len(df) > s_days:
            df = df.iloc[-s_days:]

        df = calculate_all_indicators(
            df=df,
            pure_code=pure_code,
            major1_thresh=s_m1,
            major2_thresh=s_m2
        )

    fig = create_stock_chart(df, stock_name, pure_code)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("近期籌碼與技術摘要")
    if not df.empty:
        latest = df.iloc[-1]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("收盤價", f"{latest.get('Close', 0):.2f}")
        col2.metric("5日均價", f"{latest.get('MA5', 0):.2f}")
        col3.metric("換手率 (%)", f"{latest.get('Turnover_Rate', 0):.2f}%" if pd.notna(latest.get('Turnover_Rate')) else "N/A")
        col4.metric("外資買賣超", f"{latest.get('Foreign_Net', 0):,.0f} 張")
