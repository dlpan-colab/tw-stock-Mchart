"""
app.py - 主應用程式介面與生命週期控制
負責調用模組、呈現參數側邊欄與圖例看板版本標籤。
"""

VERSION_TAG = "202610301610"

import re
import datetime
import streamlit as st
import streamlit.components.v1 as components

from storage import load_stock_history, clear_stock_history
from chart_builder import build_split_figures
from frontend import get_legend_html, get_component_html

DEFAULT_DISPLAY_DAYS = 20

def parse_pure_code(input_str: str) -> str:
    if not input_str:
        return ""
    m = re.search(r'\b(\d{4,6})\b', str(input_str))
    return m.group(1) if m else str(input_str).strip()

st.set_page_config(page_title="台股多指標+籌碼技術分析", layout="wide")

if 'history_list' not in st.session_state:
    st.session_state.history_list = load_stock_history()
if 'ticker_input_field' not in st.session_state:
    init_code = st.session_state.history_list[0]['code'] if st.session_state.history_list else "2330"
    st.session_state.ticker_input_field = init_code

def on_hist_change():
    selected = st.session_state.get('hist_select')
    if selected and selected != "(選擇歷史標的)":
        chosen_code = parse_pure_code(selected)
        if chosen_code:
            st.session_state.ticker_input_field = chosen_code

# 側邊欄參數設定
with st.sidebar:
    st.header("參數設定")
    hist = st.session_state.history_list
    hist_options = ["(選擇歷史標的)"] + [f"{h.get('code')} ({h.get('name')})" for h in hist]

    st.selectbox(
        "歷史紀錄快速選取",
        options=hist_options,
        index=0,
        key="hist_select",
        on_change=on_hist_change
    )

    s_ticker = st.text_input("股票代號 (直接鍵入)", key="ticker_input_field").strip()

    if st.button("清除歷史記錄", type="secondary"):
        clear_stock_history()
        st.session_state.history_list = []
        st.success("已清除歷史紀錄！")
        st.rerun()

    s_period = st.selectbox("下載區間", options=['6mo', '1y', '2y', '5y', 'max'], index=1)
    s_mode = st.selectbox("模式切換", options=['手機版 (Mobile) - 預設20日', '筆電版 (Desktop) - 預設60日'], index=0)
    s_days = st.number_input("顯示日數", min_value=5, max_value=2000, value=20 if '手機版' in s_mode else 60, step=5)
    
    use_base_date = st.checkbox("指定基準日 (復盤模式)", value=False)
    s_base_date = st.date_input("基準日", value=datetime.date.today()) if use_base_date else None

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        s_m1 = st.selectbox("大戶門檻1 (張)", options=[100, 200, 400, 600, 800, 1000], index=5)
    with col_m2:
        s_m2 = st.selectbox("大戶門檻2 (張)", options=[100, 200, 400, 600, 800, 1000], index=2)

    s_btn = st.button("查詢", type="primary")

is_mobile = ('手機版' in s_mode)
status_box = st.empty()

# 頂部圖例區注入 VERSION_TAG
st.markdown(get_legend_html(VERSION_TAG), unsafe_allow_html=True)

pure_code = parse_pure_code(s_ticker)
fig_top, fig_btm, df, c_name, end_idx, disp_n = build_split_figures(
    pure_code, s_period, s_days, s_base_date, s_m1, s_m2, is_mobile=is_mobile, status_placeholder=status_box
)

if status_box:
    status_box.empty()

if fig_top is not None:
    total_h = 1650 if is_mobile else 1750
    html_content = get_component_html(
        fig_top, fig_btm, df, pure_code, s_m1, s_m2, end_idx, disp_n, is_mobile=is_mobile
    )
    components.html(html_content, height=total_h, scrolling=False)
else:
    st.error(f"查無資料: {s_ticker}")
