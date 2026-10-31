import streamlit as st
import pandas as pd
from datetime import datetime

# 導入自訂模組
import charts as cha
import data_loader as dat
import frontend_ui as fro
import indicators as ind
import stock_history as sto

# 頁面基本配置
st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 版本識別日期摘要 (DDhhmm)
VER_APP = "app_311056"
VER_CHA = "cha_311056"
VER_DAT = "dat_311056"
VER_FRO = "fro_311056"
VER_IND = "ind_311056"
VER_STO = "sto_311056"

MODULE_VERSIONS = f"{VER_APP}/{VER_CHA}/{VER_DAT}/{VER_FRO}/{VER_IND}/{VER_STO}/"

# 1. 第一行：標題
st.markdown("## 台股技術指標與籌碼分析(模組)")

# 2. 第二行：模組前三英文字簡稱_模組版本識別日期摘要
st.caption(MODULE_VERSIONS)

# 初始化 Session State
if "stock_id" not in st.session_state:
    st.session_state.stock_id = "8111"

# 載入歷史紀錄清單
history_list = sto.get_history_list()

def handle_prev():
    curr = st.session_state.stock_id
    if curr in history_list:
        idx = history_list.index(curr)
        if idx > 0:
            st.session_state.stock_id = history_list[idx - 1]
    elif len(history_list) > 0:
        st.session_state.stock_id = history_list[0]

def handle_next():
    curr = st.session_state.stock_id
    if curr in history_list:
        idx = history_list.index(curr)
        if idx < len(history_list) - 1:
            st.session_state.stock_id = history_list[idx + 1]
    elif len(history_list) > 0:
        st.session_state.stock_id = history_list[0]

# 3. 第三行：[上一檔][下一檔]功能鍵
c1, c2, _ = st.columns([1, 1, 8])
with c1:
    st.button("◀ 上一檔", key="top_prev", on_click=handle_prev)
with c2:
    st.button("下一檔 ▶", key="top_next", on_click=handle_next)

# 側邊欄設定
with st.sidebar:
    st.subheader("參數設定")
    
    # 查詢歷史紀錄管理
    st.markdown("### 查詢歷史紀錄")
    
    selected_to_remove = []
    if history_list:
        for code in history_list:
            chk = st.checkbox(code, key=f"hist_chk_{code}")
            if chk:
                selected_to_remove.append(code)
    else:
        st.caption("尚無歷史紀錄")

    if st.button("清除歷史記錄"):
        if selected_to_remove:
            sto.remove_history_items(selected_to_remove)
            st.rerun()
        else:
            st.session_state.confirm_clear_all = True

    if st.session_state.get("confirm_clear_all", False):
        st.warning("未勾選任何項目，是否確認清除所有歷史清單？")
        ca1, ca2 = st.columns(2)
        with ca1:
            if st.button("確定全部清除", key="btn_confirm_all"):
                sto.clear_all_history()
                st.session_state.confirm_clear_all = False
                st.rerun()
        with ca2:
            if st.button("取消", key="btn_cancel_all"):
                st.session_state.confirm_clear_all = False
                st.rerun()

    # 股票代號輸入
    input_stock = st.text_input("股票代號 (直接鍵入)", value=st.session_state.stock_id)
    if input_stock != st.session_state.stock_id:
        st.session_state.stock_id = input_stock

    period = st.selectbox("下載區間", ["6mo", "1y", "2y", "5y"], index=1)
    mode = st.selectbox("模式切換", ["手機版 (Mobile) - 預設20日", "完整版 (Full)"], index=0)
    display_days = st.number_input("顯示日數", min_value=10, max_value=240, value=20 if "手機版" in mode else 60)
    
    m1 = st.number_input("大戶門檻1 (張)", min_value=100, max_value=5000, value=1000, step=100)
    m2 = st.number_input("大戶門檻2 (張)", min_value=100, max_value=5000, value=400, step=100)
    
    query_btn = st.button("查詢")

# 資料讀取與指標計算
current_code = st.session_state.stock_id
stock_info, df = dat.load_stock_data(current_code, period)

if df is not None and not df.empty:
    sto.add_to_history(current_code)
    df = ind.calculate_indicators(df, m1, m2)
    display_df = df.tail(display_days).copy()
    
    # 繪製圖表 (包含三大資訊區及格式修訂)
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
