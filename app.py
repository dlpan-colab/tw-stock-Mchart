"""
app.py - 主應用程式介面與生命週期控制
版本: 202611012356
"""
import streamlit as st
import streamlit.components.v1 as components

MODULE_VERSION = "202611012356"

from storage import (
    load_stock_history,
    save_stock_history,
    clear_stock_history,
    remove_stocks_from_history,
    update_stock_name_only,
    get_stock_chinese_name
)
from chart_builder import build_split_figures
from frontend import get_legend_html, get_component_html

st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container {
    padding-top: 3.5rem;
    padding-bottom: 0rem;
    padding-left: 1rem;
    padding-right: 1rem;
}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

if "stock_id" not in st.session_state:
    st.session_state.stock_id = "2330"
if "period" not in st.session_state:
    st.session_state.period = "1y"
if "disp_days" not in st.session_state:
    st.session_state.disp_days = 20
if "confirm_clear_all" not in st.session_state:
    st.session_state.confirm_clear_all = False
if "prev_selected_history" not in st.session_state:
    st.session_state.prev_selected_history = []

def on_stock_input_change():
    val = st.session_state.stock_input_box.strip()
    if val:
        st.session_state.stock_id = val
        save_stock_history(val)

with st.sidebar:
    st.header("參數設定")
    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip() for item in history_records if item.get("code")]
    
    with st.expander("查詢歷史紀錄", expanded=False):
        if history_codes:
            history_display = [f"{h.get('code')} {h.get('name', '')}".strip() for h in history_records]
            selected_history = st.multiselect(
                "點擊展開並勾選標的...",
                options=history_display,
                default=[],
                key="history_multiselect"
            )
            
            # 偵測最新勾選的項目：更新股票代號並提至歷史清單最前面
            newly_added = [item for item in selected_history if item not in st.session_state.prev_selected_history]
            if newly_added:
                latest_sel_code = newly_added[-1].split()[0]
                if latest_sel_code != st.session_state.stock_id:
                    st.session_state.stock_id = latest_sel_code
                    save_stock_history(latest_sel_code)
                    st.session_state.prev_selected_history = selected_history
                    st.rerun()
            st.session_state.prev_selected_history = selected_history

            # 清除按鈕邏輯
            if st.button("清除歷史記錄", use_container_width=True):
                if selected_history:
                    target_codes = [item.split()[0] for item in selected_history]
                    remove_stocks_from_history(target_codes)
                    st.session_state.confirm_clear_all = False
                    st.session_state.prev_selected_history = []
                    st.rerun()
                else:
                    st.session_state.confirm_clear_all = True
                    st.rerun()

            # 無勾選項目時的二次確認區塊
            if st.session_state.confirm_clear_all:
                st.warning("⚠️ 未勾選任何標的，確定要清除全部歷史紀錄嗎？")
                c_del1, c_del2 = st.columns(2)
                with c_del1:
                    if st.button("確認全刪", key="btn_confirm_delete_all", use_container_width=True):
                        clear_stock_history()
                        st.session_state.confirm_clear_all = False
                        st.session_state.prev_selected_history = []
                        st.rerun()
                with c_del2:
                    if st.button("取消", key="btn_cancel_delete_all", use_container_width=True):
                        st.session_state.confirm_clear_all = False
                        st.rerun()
        else:
            st.caption("目前無歷史紀錄")

    st.text_input(
        "股票代號 (直接鍵入)",
        value=st.session_state.stock_id,
        key="stock_input_box",
        on_change=on_stock_input_change
    )
    st.session_state.period = st.selectbox(
        "下載區間",
        ["6mo", "1y", "2y", "5y", "max"],
        index=1
    )
    mode_switch = st.selectbox(
        "模式切換",
        ["手機版 (Mobile) - 預設20日", "電腦版 (Desktop) - 預設60日"],
        index=0
    )
    is_mobile = "手機版" in mode_switch
    default_days = 20 if is_mobile else 60
    st.session_state.disp_days = st.number_input(
        "顯示日數",
        min_value=10,
        max_value=240,
        value=default_days,
        step=5
    )
    use_target_date = st.checkbox("指定基準日 (復盤模式)")
    target_date_val = None
    if use_target_date:
        target_date_input = st.text_input("基準日 (YYYY-MM-DD)", value="")
        if target_date_input.strip():
            target_date_val = target_date_input.strip()

    m1_thresh = st.number_input("大戶門檻1 (張)", min_value=100, max_value=2000, value=1000, step=100)
    m2_thresh = st.number_input("大戶門檻2 (張)", min_value=100, max_value=1000, value=400, step=100)

    if st.button("查詢", use_container_width=True):
        save_stock_history(st.session_state.stock_id)
        st.rerun()

st.subheader(f"台股技術與籌碼分析 v{MODULE_VERSION}")

# 頂部：上一檔 / 下一檔 功能列（純切換，不調整歷史順序）
stock_id = str(st.session_state.stock_id).strip()
hist_records = load_stock_history()
hist_codes = [str(item.get("code")).strip() for item in hist_records if item.get("code")]

if hist_codes:
    curr_idx = hist_codes.index(stock_id) if stock_id in hist_codes else 0
    _, top_c1, top_c2, _ = st.columns([1, 2, 2, 1])
    with top_c1:
        if st.button("◀ 上一檔", key="btn_top_prev", use_container_width=True):
            prev_idx = (curr_idx - 1) % len(hist_codes)
            st.session_state.stock_id = hist_codes[prev_idx]
            st.rerun()
    with top_c2:
        if st.button("下一檔 ▶", key="btn_top_next", use_container_width=True):
            next_idx = (curr_idx + 1) % len(hist_codes)
            st.session_state.stock_id = hist_codes[next_idx]
            st.rerun()

fig_top, fig_btm, df, c_name, end_idx, disp_n = build_split_figures(
    raw_ticker=stock_id,
    period=st.session_state.period,
    display_days=st.session_state.disp_days,
    base_date=target_date_val,
    major1_thresh=m1_thresh,
    major2_thresh=m2_thresh,
    is_mobile=is_mobile
)

if fig_top is None or fig_btm is None or df is None or df.empty:
    st.error(f"無法取得股票代號 {stock_id} 之歷史行情資料，請確認網路連線或稍後點擊查詢重試。")
    st.stop()

# 繪圖成功後：若不在清單內才新增入榜；若已存在僅更新名稱，不打亂原有清單順序
if stock_id not in hist_codes:
    save_stock_history(stock_id, c_name)
else:
    update_stock_name_only(stock_id, c_name)

top_height = 420 if is_mobile else 460
btm_height = 1180 if is_mobile else 1220

html_content = get_component_html(
    fig_top=fig_top,
    fig_btm=fig_btm,
    df=df,
    m1_thresh=m1_thresh,
    m2_thresh=m2_thresh,
    top_height=top_height,
    btm_height=btm_height,
    initial_disp_days=disp_n,
    initial_end_idx=end_idx
)

total_h = 1920 if is_mobile else 1880
components.html(
    html_content,
    height=total_h,
    scrolling=False
)

# 底部：上一檔 / 下一檔 功能列（純切換，不調整歷史順序）
if hist_codes:
    curr_idx = hist_codes.index(stock_id) if stock_id in hist_codes else 0
    _, btm_c1, btm_c2, _ = st.columns([1, 2, 2, 1])
    with btm_c1:
        if st.button("◀ 上一檔", key="btn_btm_prev", use_container_width=True):
            prev_idx = (curr_idx - 1) % len(hist_codes)
            st.session_state.stock_id = hist_codes[prev_idx]
            st.rerun()
    with btm_c2:
        if st.button("下一檔 ▶", key="btn_btm_next", use_container_width=True):
            next_idx = (curr_idx + 1) % len(hist_codes)
            st.session_state.stock_id = hist_codes[next_idx]
            st.rerun()
