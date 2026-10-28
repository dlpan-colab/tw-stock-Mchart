"""
台股技術與籌碼分析系統 - 模組化主程式入口 (app.py)
整合側邊欄參數設定、歷史紀錄快捷選取、前後導航狀態機、
圖表渲染及雙執行環境（Streamlit Cloud / Google Colab）支援。
"""

MODULE_NAME = "app"
MODULE_VERSION = "202610281055"

import re
import datetime
import streamlit as st
import streamlit.components.v1 as components

from storage import (
    load_stock_history,
    save_stock_history,
    clear_stock_history
)
from chart_builder import build_split_figures
from frontend import get_legend_html, get_component_html

DEFAULT_DISPLAY_DAYS = 20
DEFAULT_MAJOR1_THRESH = 1000
DEFAULT_MAJOR2_THRESH = 400


def parse_pure_code(input_str: str) -> str:
    if not input_str:
        return ""
    m = re.search(r'\b(\d{4,6})\b', str(input_str))
    return m.group(1) if m else str(input_str).strip()


def run_app():
    st.set_page_config(
        page_title="台股技術與籌碼分析(模組化)",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 1. 狀態初始化
    if 'history_list' not in st.session_state:
        st.session_state.history_list = load_stock_history()
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0
    if 'ticker_input_field' not in st.session_state:
        init_code = st.session_state.history_list[0]['code'] if st.session_state.history_list else "2330"
        st.session_state.ticker_input_field = init_code

    # 2. 連動回調函式
    def on_hist_change():
        selected = st.session_state.get('hist_select')
        if selected and selected != "(選擇歷史標的)":
            chosen_code = parse_pure_code(selected)
            if chosen_code:
                st.session_state.ticker_input_field = chosen_code
                for i, h in enumerate(st.session_state.history_list):
                    if h.get('code') == chosen_code:
                        st.session_state.current_index = i
                        break

    def on_prev_click():
        hist = st.session_state.history_list
        if not hist:
            return
        st.session_state.current_index = (st.session_state.current_index - 1) % len(hist)
        target_code = hist[st.session_state.current_index]['code']
        st.session_state.ticker_input_field = target_code

    def on_next_click():
        hist = st.session_state.history_list
        if not hist:
            return
        st.session_state.current_index = (st.session_state.current_index + 1) % len(hist)
        target_code = hist[st.session_state.current_index]['code']
        st.session_state.ticker_input_field = target_code

    # 3. 側邊欄參數設定
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

        s_ticker = st.text_input(
            "股票代號 / 名稱",
            key="ticker_input_field"
        ).strip()

        s_days = st.number_input(
            "顯示日數",
            min_value=5,
            max_value=120,
            value=DEFAULT_DISPLAY_DAYS,
            step=5
        )

        s_period = st.selectbox(
            "資料週期",
            options=["6mo", "1y", "2y"],
            index=1
        )

        use_base_date = st.checkbox("指定基準日 (復盤模式)", value=False)
        s_base_date = None
        if use_base_date:
            s_base_date = st.date_input("基準日期", value=datetime.date.today())

        st.subheader("大戶門檻設定")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            s_m1 = st.selectbox("大戶門檻 1 (張)", options=[100, 200, 400, 600, 800, 1000], index=5)
        with col_m2:
            s_m2 = st.selectbox("大戶門檻 2 (張)", options=[100, 200, 400, 600, 800, 1000], index=2)

        is_mobile = st.checkbox("手機緊湊版面優化", value=True)

        col_b1, col_b2 = st.columns([1, 1])
        with col_b1:
            s_btn = st.button("查詢", type="primary", use_container_width=True)
        with col_b2:
            c_btn = st.button("清除歷史", use_container_width=True)

        if c_btn:
            st.session_state.history_list = clear_stock_history()
            st.session_state.current_index = 0
            st.rerun()

    # 4. 頂部看板與頂部導航按鈕
    st.markdown(get_legend_html(version_tag=MODULE_VERSION), unsafe_allow_html=True)

    nav_col1, nav_col2, _ = st.columns([1, 1, 6])
    with nav_col1:
        st.button("⏮ 上一個", on_click=on_prev_click, key="btn_prev_top")
    with nav_col2:
        st.button("⏭ 下一個", on_click=on_next_click, key="btn_next_top")

    status_box = st.empty()

    target_symbol = parse_pure_code(s_ticker)
    if not target_symbol:
        st.info("請輸入台股代號以開始分析。")
        return

    # 5. 執行圖表運算
    try:
        fig_top, fig_btm, df, c_name, end_idx, disp_n = build_split_figures(
            raw_ticker=target_symbol,
            period=s_period,
            display_days=s_days,
            base_date=s_base_date,
            major1_thresh=s_m1,
            major2_thresh=s_m2,
            is_mobile=is_mobile,
            status_placeholder=status_box
        )
        status_box.empty()
    except Exception as e:
        status_box.empty()
        st.error(f"資料擷取或計算失敗：{e}")
        return

    if df is None or df.empty:
        st.warning(f"查無標的 `{target_symbol}` 之交易資料，請確認代號是否正確。")
        return

    # 6. 自動回饋至歷史清單
    saved_hist = save_stock_history(target_symbol, c_name)
    st.session_state.history_list = saved_hist

    # 7. 渲染前端圖表
    component_html = get_component_html(
        fig_top=fig_top,
        fig_btm=fig_btm,
        df=df,
        raw_ticker=target_symbol,
        major1_thresh=s_m1,
        major2_thresh=s_m2,
        initial_end_idx=end_idx,
        initial_disp_days=disp_n,
        is_mobile=is_mobile
    )

    chart_height = 1820 if is_mobile else 1880
    components.html(component_html, height=chart_height, scrolling=False)

    # 8. 底部重複導航按鈕
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    btm_col1, btm_col2, _ = st.columns([1, 1, 6])
    with btm_col1:
        st.button("⏮ 上一個", on_click=on_prev_click, key="btn_prev_bottom")
    with btm_col2:
        st.button("⏭ 下一個", on_click=on_next_click, key="btn_next_bottom")


if __name__ == "__main__":
    run_app()
