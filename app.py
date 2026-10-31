"""
app.py - 主應用程式進入點
版本: app_202610311148
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

MODULE_VERSION = "app_202610311148"

# 頁面基本配置
st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 讀取各模組完整版本識別字串
ver_app_full = MODULE_VERSION
ver_cha_full = getattr(cha, "MODULE_VERSION", "cha_202610311145")
ver_dat_full = getattr(dat, "MODULE_VERSION", "dat_202610302000")
ver_fro_full = getattr(fro, "MODULE_VERSION", "fro_202610302000")
ver_ind_full = getattr(ind, "MODULE_VERSION", "ind_202610302000")
ver_sto_full = getattr(sto, "MODULE_VERSION", "sto_202610311112")

# 格式化為版本識別摘要：忽略年份月份，僅保留 DDhhmm
def to_summary(ver_str: str) -> str:
    parts = ver_str.split("_")
    if len(parts) == 2 and len(parts[1]) >= 6:
        return f"{parts[0]}_{parts[1][-6:]}"
    return ver_str

MODULE_VERSIONS = (
    f"{to_summary(ver_app_full)}/"
    f"{to_summary(ver_cha_full)}/"
    f"{to_summary(ver_dat_full)}/"
    f"{to_summary(ver_fro_full)}/"
    f"{to_summary(ver_ind_full)}/"
    f"{to_summary(ver_sto_full)}/"
)

# 1. 第一行：標題（字體大小同側邊欄「參數設定」之 subheader）
st.subheader("台股技術指標與籌碼分析(模組)")

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

# 3. 第三行：[上一檔][下一檔]功能鍵（比例調整避免文字截斷）
c1, c2, _ = st.columns([1, 1, 3])
with c1:
    st.button("◀ 上一檔", key="top_prev", on_click=handle_prev, use_container_width=True)
with c2:
    st.button("下一檔 ▶", key="top_next", on_click=handle_next, use_container_width=True)

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

    # 股票代號輸入（已移除上一檔/下一檔按鈕）
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
df, ticker_full, shares = dat.fetch_stock_daily_k(current_code, period=period)

if df is not None and not df.empty:
    stock_name = dat.fetch_stock_name(current_code)
    market_type = "櫃" if ".TWO" in ticker_full else "市"
    stock_info = {
        "code": current_code,
        "name": stock_name,
        "market": market_type
    }

    # 寫入歷史紀錄
    sto.save_stock_history(current_code, stock_name)

    # 同步籌碼 (法人、資券、大戶持股)
    inst_df, margin_df, holding_df = dat.sync_chip_data(current_code, df.index)

    # 合併法人籌碼
    if not inst_df.empty:
        inst_df = inst_df.rename(columns={
            "foreign_net": "Foreign_Buy",
            "trust_net": "Trust_Buy",
            "dealer_net": "Dealer_Buy"
        }).set_index("date")
        df = df.join(inst_df, how="left")

    # 合併資券
    if not margin_df.empty:
        margin_df = margin_df.rename(columns={
            "margin_diff": "Margin_Diff",
            "short_diff": "Short_Diff",
            "margin_bal": "Margin_Balance",
            "short_bal": "Short_Balance"
        }).set_index("date")
        df = df.join(margin_df, how="left")
        if 'Margin_Balance' in df.columns and 'Short_Balance' in df.columns:
            df['Margin_Short_Ratio'] = (df['Short_Balance'] / df['Margin_Balance'].replace(0, float('nan'))) * 100

    # 合併大戶持股
    if not holding_df.empty:
        holding_pivot = holding_df.pivot(index='date', columns='level', values='percent')
        if 15 in holding_pivot.columns:
            df[f'Big_{m1}_Ratio'] = holding_pivot[15].reindex(df.index).ffill()
        cols_m2 = [c for c in holding_pivot.columns if c >= 11]
        if cols_m2:
            df[f'Big_{m2}_Ratio'] = holding_pivot[cols_m2].sum(axis=1).reindex(df.index).ffill()

    # 指標運算
    if hasattr(ind, "calc_all_indicators"):
        df = ind.calc_all_indicators(df, m1, m2)
    elif hasattr(ind, "calculate_all"):
        df = ind.calculate_all(df)
    elif hasattr(ind, "compute_indicators"):
        df = ind.compute_indicators(df)
    elif hasattr(ind, "calculate_indicators"):
        df = ind.calculate_indicators(df, m1, m2)

    display_df = df.tail(display_days).copy()
    
    # 繪製主圖表
    fig = cha.render_master_chart(display_df, stock_info, m1, m2)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # 第三塊資訊區下方：[◀ 上一檔] [下一檔 ▶] 功能鍵
    b1, b2, _ = st.columns([1, 1, 3])
    with b1:
        st.button("◀ 上一檔", key="bottom_prev", on_click=handle_prev, use_container_width=True)
    with b2:
        st.button("下一檔 ▶", key="bottom_next", on_click=handle_next, use_container_width=True)
else:
    st.error(f"查無標的代碼 {current_code} 之相關資料。")
