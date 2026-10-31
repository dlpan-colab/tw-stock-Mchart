"""
app.py - 主應用程式介面與生命週期控制
版本: 202610312052
"""
import streamlit as st
import streamlit.components.v1 as components

MODULE_VERSION = "202610312052"

from storage import load_stock_history, save_stock_history, clear_stock_history, get_stock_chinese_name
from indicators import calculate_all_indicators
from chart_builder import plot_stock_charts
from frontend import get_legend_html

try:
    from data_fetcher import fetch_stock_data
except ImportError:
    import yfinance as yf
    def fetch_stock_data(stock_id: str, period: str = "1y"):
        code = f"{stock_id}.TW" if not (stock_id.endswith(".TW") or stock_id.endswith(".TWO")) else stock_id
        df = yf.download(code, period=period, progress=False)
        if df.empty and not stock_id.endswith(".TWO"):
            df = yf.download(f"{stock_id}.TWO", period=period, progress=False)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        return df

st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="collapsed"
)

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
    target_date_val = ""
    if use_target_date:
        target_date_input = st.text_input("基準日 (YYYY-MM-DD)", value="")
        target_date_val = target_date_input.strip()

    m1_thresh = st.number_input("大戶門檻1 (張)", min_value=100, max_value=2000, value=1000, step=100)
    m2_thresh = st.number_input("大戶門檻2 (張)", min_value=100, max_value=1000, value=400, step=100)

    if st.button("查詢", use_container_width=True):
        save_stock_history(st.session_state.stock_id)
        st.rerun()

st.markdown(get_legend_html(), unsafe_allow_html=True)

stock_id = st.session_state.stock_id
stock_name = get_stock_chinese_name(stock_id)

df = fetch_stock_data(stock_id, period=st.session_state.period)

if df is None or df.empty:
    st.error(f"無法取得股票代號 {stock_id} 之歷史行情資料，請檢查代號或網路連線。")
    st.stop()

df = calculate_all_indicators(df, m1_thresh=m1_thresh, m2_thresh=m2_thresh)

initial_end_idx = len(df) - 1
if target_date_val:
    date_strs = df['Date'].dt.strftime('%Y-%m-%d').tolist() if 'Date' in df.columns else [str(x)[:10] for x in df.index]
    if target_date_val in date_strs:
        initial_end_idx = date_strs.index(target_date_val)
    else:
        st.warning(f"指定基準日 {target_date_val} 不在交易資料範圍內，將顯示最新交易日。")

html_content = plot_stock_charts(
    df=df,
    stock_id=stock_id,
    stock_name=stock_name,
    is_mobile=is_mobile,
    m1_thresh=m1_thresh,
    m2_thresh=m2_thresh,
    initial_disp_days=st.session_state.disp_days,
    initial_end_idx=initial_end_idx
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
