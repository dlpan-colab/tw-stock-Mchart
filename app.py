"""
app.py - 主應用程式介面與生命週期控制
"""

import os
import re
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components

from data_fetcher import load_stock_history, clear_stock_history
from chart_builder import build_split_figures, get_component_html, LEGEND_HTML

st.set_page_config(page_title="台股多指標+籌碼技術分析", layout="wide")

st.sidebar.title("參數設定")
stock_hist = load_stock_history()
hist_options = [f"{h['code']} ({h['name']})" if h.get('name') else h['code'] for h in stock_hist]

if "ticker_input" not in st.session_state:
    st.session_state["ticker_input"] = "2330"

def on_hist_change():
    sel = st.session_state.get("hist_dropdown_key")
    if sel and sel != "(選擇歷史標的)":
        m = re.search(r'\d+', sel)
        if m:
            st.session_state["ticker_input"] = m.group(0)

st.sidebar.selectbox(
    "歷史紀錄快速選取",
    options=["(選擇歷史標的)"] + hist_options,
    index=0,
    key="hist_dropdown_key",
    on_change=on_hist_change
)

s_ticker = st.sidebar.text_input("股票代碼 (直接鍵入)", key="ticker_input")

if st.sidebar.button("清除歷史記錄", type="secondary"):
    clear_stock_history()
    st.sidebar.success("已清除歷史紀錄！")
    st.rerun()

s_period = st.sidebar.selectbox("下載區間", options=['6mo', '1y', '2y', '5y', 'max'], index=1)
s_mode = st.sidebar.selectbox("模式切換", options=['手機版 (Mobile) - 預設20日', '筆電版 (Desktop) - 預設60日'], index=0)
s_days = st.sidebar.number_input("顯示日數", min_value=5, max_value=2000, value=20 if '手機版' in s_mode else 60, step=5)
s_base_date = st.sidebar.date_input("基準日 (預設為最新)", value=datetime.now().date())
s_m1 = st.sidebar.selectbox("大戶1門檻(張)", options=[100, 200, 400, 600, 800, 1000], index=5)
s_m2 = st.sidebar.selectbox("大戶2門檻(張)", options=[100, 200, 400, 600, 800, 1000], index=2)
s_btn = st.sidebar.button("查詢", type="primary")

is_mobile = ('手機版' in s_mode)
status_box = st.empty()
st.markdown(LEGEND_HTML, unsafe_allow_html=True)

pure_input = re.search(r'\d+', s_ticker)
target_symbol = pure_input.group(0) if pure_input else s_ticker

fig_top, fig_btm, df, c_name, end_idx, disp_n = build_split_figures(
    target_symbol, s_period, s_days, s_base_date, s_m1, s_m2, is_mobile=is_mobile, status_placeholder=status_box
)

if status_box:
    status_box.empty()

if fig_top is not None:
    total_h = 1650 if is_mobile else 1750
    html_content = get_component_html(
        fig_top, fig_btm, df, target_symbol, s_m1, s_m2, end_idx, disp_n, is_mobile=is_mobile
    )
    components.html(html_content, height=total_h, scrolling=False)
else:
    st.error(f"查無資料: {s_ticker}")
