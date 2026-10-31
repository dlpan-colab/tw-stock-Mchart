"""
app.py - 主應用程式介面與生命週期控制
版本: 202610312059
"""
import streamlit as st
import streamlit.components.v1 as components

MODULE_VERSION = "202610312059"

from storage import load_stock_history, save_stock_history, clear_stock_history
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
        padding-top: 1rem;
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

with st.sidebar:
    st.header("參數設定")
    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip() for item in history_records if item.get("code")]
    
    with st.expander("查詢歷史紀錄", expanded=False):
        if history_codes:
            history_display = [f"{h.get('code')} {h.get('name', '')}" for h in history_records]
            selected_history = st.selectbox(
                "點擊展開並勾選標的...",
                [""] + history_display,
                key="history_select"
            )
            if selected_history:
                st.session_state.stock_id = selected_history.split()[0]
        if st.button("清除歷史記錄"):
            clear_stock_history()
            st.rerun()

    input_stock = st.text_input("股票代號 (直接鍵入)", value=st.session_state.stock_id)
    if input_stock.strip() != st.session_state.stock_id:
        st.session_state.stock_id = input_stock.strip()

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
    st.session_state.disp_days = st.number_input("顯示日數", min_value=10, max_value=240, value=default_days, step=5)

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

st.markdown(get_legend_html(), unsafe_allow_html=True)

stock_id = st.session_state.stock_id

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

top_height = 540 if is_mobile else 580
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

total_h = 2150 if is_mobile else 2250
components.html(
    html_content,
    height=total_h,
    scrolling=False
)

hist_records = load_stock_history()
hist_codes = [str(item.get("code")).strip() for item in hist_records if item.get("code")]
if hist_codes and stock_id in hist_codes:
    curr_idx = hist_codes.index(stock_id)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("◀ 上一檔", use_container_width=True):
            prev_idx = (curr_idx - 1) % len(hist_codes)
            st.session_state.stock_id = hist_codes[prev_idx]
            st.rerun()
    with c2:
        if st.button("下一檔 ▶", use_container_width=True):
            next_idx = (curr_idx + 1) % len(hist_codes)
            st.session_state.stock_id = hist_codes[next_idx]
            st.rerun()
