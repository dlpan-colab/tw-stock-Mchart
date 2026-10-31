"""
app.py - 主應用程式進入點
版本: app_311120
"""

import streamlit as st
import pandas as pd
from datetime import datetime

# 導入既有模組
import chart_builder as cha
import data_fetcher as dat
import frontend as fro
import indicators as ind
import storage as sto

MODULE_VERSION = "app_311120"

# 頁面基本配置
st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 讀取各模組版本識別字串
ver_app = getattr(cha, "MODULE_VERSION", "cha_311115")
ver_dat = getattr(dat, "MODULE_VERSION", "dat_311100")
ver_fro = getattr(fro, "MODULE_VERSION", "fro_311100")
ver_ind = getattr(ind, "MODULE_VERSION", "ind_311100")
ver_sto = getattr(sto, "MODULE_VERSION", "sto_311112")

MODULE_VERSIONS = f"{MODULE_VERSION}/{ver_cha}/{ver_dat}/{ver_fro}/{ver_ind}/{ver_sto}/"

# 1. 第一行：標題
st.markdown("## 台股技術指標與籌碼分析(模組)")

# 2. 第二行：模組前三英文字簡稱_模組版本識別日期摘要
st.caption(MODULE_VERSIONS)

# 初始化 Session State
if "stock_id" not in st.session_state:
    st.session_state.stock_id = "8111"
if "confirm_clear_all" not in st.session_state:
    st.session_state.confirm_clear_all = False

# 讀取持久化歷史清單
history_data = sto.load_stock_history()
history_codes = [str(item.get("code")).strip() for item in history_data]

def handle_prev():
    curr = str(st.session_state.stock_id).strip()
    if curr in history_codes:
        idx = history_codes.index(curr)
        if idx > 0:
            st.session_state.stock_id = history_codes[idx - 1]
    elif len(history_codes) > 0:
        st.session_state.stock_id = history_codes[0]

def handle_next():
    curr = str(st.session_state.stock_id).strip()
    if curr in history_codes:
        idx = history_codes.index(curr)
        if idx < len(history_codes) - 1:
            st.session_state.stock_id = history_codes[idx + 1]
    elif len(history_codes) > 0:
        st.session_state.stock_id = history_codes[0]

# 3. 第三行：[上一檔][下一檔]功能鍵
c1, c2, _ = st.columns([1, 1, 8])
with c1:
    st.button("◀ 上一檔", key="top_prev", on_click=handle_prev)
with c2:
    st.button("下一檔 ▶", key="top_next", on_click=handle_next)

# 側邊欄設定
with st.sidebar:
    st.subheader("參數設定")
    
    # 查詢歷史紀錄清單與勾選管理
    st.markdown("### 查詢歷史紀錄")
    selected_to_remove = []
    if history_data:
        for item in history_data:
            c = item.get("code", "")
            n = item.get("name", "")
            label = f"{n}({c})" if n and n != c else c
            if st.checkbox(label, key=f"hist_chk_{c}"):
                selected_to_remove.append(c)
    else:
        st.caption("尚無歷史紀錄")

    if st.button("清除歷史記錄"):
        if selected_to_remove:
            sto.remove_history_items(selected_to_remove)
            st.rerun()
        else:
            st.session_state.confirm_clear_all = True

    if st.session_state.confirm_clear_all:
        st.warning("未勾選任何項目，是否確認清除所有歷史清單？")
        ca1, ca2 = st.columns(2)
        with ca1:
            if st.button("確定全部清除", key="btn_confirm_all"):
                sto.clear_stock_history()
                st.session_state.confirm_clear_all = False
                st.rerun()
        with ca2:
            if st.button("取消", key="btn_cancel_all"):
                st.session_state.confirm_clear_all = False
                st.rerun()

    # 股票代號輸入（已移除上一檔/下一檔功能鍵）
    input_stock = st.text_input("股票代號 (直接鍵入)", value=st.session_state.stock_id)
    if input_stock != st.session_state.stock_id:
        st.session_state.stock_id = input_stock

    period = st.selectbox("下載區間", ["6mo", "1y", "2y", "5y"], index=1)
    mode = st.selectbox("模式切換", ["手機版 (Mobile) - 預設20日", "完整版 (Full)"], index=0)
    display_days = st.number_input("顯示日數", min_value=10, max_value=240, value=20 if "手機版" in mode else 60)
    
    m1 = st.number_input("大戶門檻1 (張)", min_value=100, max_value=5000, value=1000, step=100)
    m2 = st.number_input("大戶門檻2 (張)", min_value=100, max_value=5000, value=400, step=100)
    
    query_btn = st.button("查詢")

# 資料載入與運算
current_code = str(st.session_state.stock_id).strip()
stock_info, df = dat.load_stock_data(current_code, period)

if df is not None and not df.empty:
    sto.save_stock_history(current_code, stock_info.get("name"))
    df = ind.calculate_indicators(df, m1, m2)
    display_df = df.tail(display_days).copy()
    
    # 繪製主圖表
    fig = cha.render_master_chart(display_df, stock_info, m1, m2)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # 第三塊資訊區下方：[◀ 上一檔] [下一檔 ▶] 功能鍵
    b1, b2, _ = st.columns([1, 1, 8])
    with b1:
        st.button("◀ 上一檔", key="bottom_prev", on_click=handle_prev)
    with b2:
        st.button("下一檔 ▶", key="bottom_next", on_click=handle_next)
else:
    st.error(f"查無標的代碼 {current_code} 之相關資料。")
