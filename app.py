"""
app.py - 主應用程式介面與生命週期控制
版本: 202610312037
"""
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime

MODULE_VERSION = "202610312037"

from config import DEFAULT_STOCK_ID, DEFAULT_PERIOD
from storage import get_stock_history, add_stock_history, clear_stock_history
from data_fetcher import fetch_stock_data, get_stock_name
from indicators import calculate_all_indicators
from chart_builder import build_top_chart, build_bottom_chart
from frontend import get_legend_html, get_component_html

st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 隱藏 Streamlit 預設多餘空白
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    header {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# 狀態初始化
if "stock_id" not in st.session_state:
    st.session_state.stock_id = DEFAULT_STOCK_ID
if "period" not in st.session_state:
    st.session_state.period = DEFAULT_PERIOD
if "disp_days" not in st.session_state:
    st.session_state.disp_days = 20
if "target_date" not in st.session_state:
    st.session_state.target_date = ""

# 側邊欄控制項
with st.sidebar:
    st.header("參數設定")
    
    # 歷史紀錄選擇
    history_list = get_stock_history()
    with st.expander("查詢歷史紀錄", expanded=False):
        if history_list:
            selected_history = st.selectbox(
                "點擊展開並勾選標的...",
                [""] + history_list,
                key="history_select"
            )
            if selected_history:
                st.session_state.stock_id = selected_history
        if st.button("清除歷史記錄"):
            clear_stock_history()
            st.rerun()

    input_stock = st.text_input("股票代號 (直接鍵入)", value=st.session_state.stock_id)
    if input_stock != st.session_state.stock_id:
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
    disp_days = st.number_input("顯示日數", min_value=10, max_value=240, value=default_days, step=5)
    st.session_state.disp_days = disp_days

    use_target_date = st.checkbox("指定基準日 (復盤模式)")
    target_date_val = ""
    if use_target_date:
        target_date_input = st.text_input("基準日 (YYYY-MM-DD)", value="")
        target_date_val = target_date_input.strip()

    m1_thresh = st.number_input("大戶門檻1 (張)", min_value=100, max_value=2000, value=1000, step=100)
    m2_thresh = st.number_input("大戶門檻2 (張)", min_value=100, max_value=1000, value=400, step=100)

    if st.button("查詢", use_container_width=True):
        add_stock_history(st.session_state.stock_id)
        st.rerun()

# 主畫面標頭與版本顯示
st.markdown(get_legend_html(), unsafe_allow_html=True)

# 資料獲取與處理
stock_id = st.session_state.stock_id
stock_name = get_stock_name(stock_id)

df = fetch_stock_data(stock_id, period=st.session_state.period)

if df is None or df.empty:
    st.error(f"無法取得股票代號 {stock_id} 之歷史行情資料，請檢查代號或網路連線。")
    st.stop()

df = calculate_all_indicators(df, m1_thresh=m1_thresh, m2_thresh=m2_thresh)

# 基準日定位
initial_end_idx = len(df) - 1
if target_date_val:
    date_strs = df['Date'].dt.strftime('%Y-%m-%d').tolist() if 'Date' in df.columns else [str(x)[:10] for x in df.index]
    if target_date_val in date_strs:
        initial_end_idx = date_strs.index(target_date_val)
    else:
        st.warning(f"指定基準日 {target_date_val} 不在交易資料範圍內，將顯示最新交易日。")

# 圖表尺寸規劃
top_height = 540 if is_mobile else 580
btm_height = 1180 if is_mobile else 1220

fig_top = build_top_chart(df, stock_id, stock_name, is_mobile=is_mobile)
fig_btm = build_bottom_chart(df, is_mobile=is_mobile, m1_thresh=m1_thresh, m2_thresh=m2_thresh)

# 輸出圖表 HTML 容器
html_content = get_component_html(
    fig_top=fig_top,
    fig_btm=fig_btm,
    df=df,
    m1_thresh=m1_thresh,
    m2_thresh=m2_thresh,
    top_height=top_height,
    btm_height=btm_height,
    initial_disp_days=st.session_state.disp_days,
    initial_end_idx=initial_end_idx
)

total_h = 2150 if is_mobile else 2250
components.html(
    html_content,
    height=total_h,
    scrolling=False
)

# 底部導航功能列（上一檔 / 下一檔）
hist = get_stock_history()
if hist and stock_id in hist:
    curr_idx = hist.index(stock_id)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("◀ 上一檔", use_container_width=True):
            prev_idx = (curr_idx - 1) % len(hist)
            st.session_state.stock_id = hist[prev_idx]
            st.rerun()
    with c2:
        if st.button("下一檔 ▶", use_container_width=True):
            next_idx = (curr_idx + 1) % len(hist)
            st.session_state.stock_id = hist[next_idx]
            st.rerun()
