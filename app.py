"""
app.py - 主應用程式介面與生命週期控制
版本: 202611081927
"""
import os
import time
import re
import streamlit as st
import streamlit.components.v1 as components
import cloud_sync

MODULE_NAME = "app"
MODULE_VERSION = "202611082105"

# 【防呆防錯備註 2026-11-07】：版本控制權由 app.py 作為唯一權威源，動態掃描所有模組最大版本號，杜絕多頭覆寫與重工
def get_system_version() -> str:
    versions = [MODULE_VERSION]
    module_names = [
        "frontend", "chart_builder", "indicators",
        "data_fetcher", "storage", "config", "cloud_sync"
    ]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for mod_name in module_names:
        try:
            mod_file = os.path.join(base_dir, f"{mod_name}.py")
            if os.path.exists(mod_file):
                with open(mod_file, "r", encoding="utf-8") as f:
                    content = f.read(500)
                    m = re.search(r'MODULE_VERSION\s*=\s*["\'](\d{12})["\']', content)
                    if m:
                        versions.append(m.group(1))
        except Exception:
            pass
    return max(versions)

SYSTEM_VERSION = get_system_version()

from storage import (
    load_stock_history,
    save_stock_history,
    clear_stock_history,
    remove_stocks_from_history,
    update_stock_name_only,
    get_stock_chinese_name,
    clear_recent_margin_data
)
from chart_builder import build_split_figures
from frontend import get_legend_html, get_component_html

INDEX_MAP = {
    # 台股
    "TWII": "^TWII", "加權": "^TWII", "大盤": "^TWII", "^TWII": "^TWII",
    "TWOII": "^TWOII", "OTC": "^TWOII", "櫃買": "^TWOII", "^TWOII": "^TWOII",
    # 美股
    "DJI": "^DJI", "道瓊": "^DJI", "^DJI": "^DJI",
    "IXIC": "^IXIC", "COMP": "^IXIC", "那指": "^IXIC", "那斯達克": "^IXIC", "^IXIC": "^IXIC",
    "SOX": "^SOX", "費半": "^SOX", "半導體": "^SOX", "^SOX": "^SOX",
    "GSPC": "^GSPC", "SP500": "^GSPC", "標普": "^GSPC", "^GSPC": "^GSPC",
    # 亞股
    "N225": "^N225", "NIKKEI": "^N225", "日經": "^N225", "^N225": "^N225",
    "KS11": "^KS11", "KOSPI": "^KS11", "韓綜": "^KS11", "^KS11": "^KS11",
    # 歐股
    "FTSE": "^FTSE", "富時": "^FTSE", "英國": "^FTSE", "^FTSE": "^FTSE",
    "GDAXI": "^GDAXI", "DAX": "^GDAXI", "德國": "^GDAXI", "^GDAXI": "^GDAXI",
    "FCHI": "^FCHI", "CAC": "^FCHI", "法國": "^FCHI", "^FCHI": "^FCHI",
}

def resolve_ticker_code(raw_input: str) -> str:
    cleaned = str(raw_input).strip()
    upper = cleaned.upper()
    if upper in INDEX_MAP:
        return INDEX_MAP[upper]
    return cleaned

# 【防呆防錯備註 2026-11-07】：完整對齊 chart_builder.py 之 build_split_figures 參數簽名，避免 TypeError
@st.cache_data(ttl=180, show_spinner=False)
def get_cached_figures(stock_id, period, disp_days, base_date, m1_thresh, m2_thresh, is_mobile, force_refresh):
    return build_split_figures(
        stock_id,
        period,
        disp_days,
        base_date,
        m1_thresh,
        m2_thresh,
        is_mobile,
        None,
        force_refresh
    )

st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container {padding-top: 3.5rem; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem;}
footer {visibility: hidden;}
[data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    justify-content: center !important;
    align-items: center !important;
    gap: 8px !important;
}
[data-testid="stHorizontalBlock"] > div {
    flex: 0 0 65px !important;
    width: 65px !important;
    min-width: 65px !important;
    max-width: 65px !important;
}
[data-testid="stHorizontalBlock"] button {
    width: 100% !important;
    min-width: 65px !important;
    padding: 2px 4px !important;
    font-size: 12px !important;
    white-space: nowrap !important;
}
</style>
""", unsafe_allow_html=True)

initial_history = load_stock_history()
default_code = "2330"
if initial_history:
    first_code = str(initial_history[0].get("code", "")).strip()
    if first_code:
        default_code = first_code

if "stock_id" not in st.session_state:
    st.session_state.stock_id = default_code
if "period" not in st.session_state:
    st.session_state.period = "1y"
if "disp_days" not in st.session_state:
    st.session_state.disp_days = 20
if "confirm_clear_all" not in st.session_state:
    st.session_state.confirm_clear_all = False
if "index_select_box" not in st.session_state:
    st.session_state.index_select_box = "選擇主要市場指數..."
if "ms_counter" not in st.session_state:
    st.session_state.ms_counter = 0
if "history_multiselect_prev" not in st.session_state:
    st.session_state.history_multiselect_prev = []

def on_stock_input_change():
    val = st.session_state.stock_input_box.strip()
    if val:
        resolved = resolve_ticker_code(val)
        st.session_state.stock_id = resolved
        if not resolved.startswith("^"):
            save_stock_history(resolved)

def on_index_select_change():
    sel = st.session_state.index_select_box
    if sel != "選擇主要市場指數...":
        m = re.search(r'\((.*?)\)', sel)
        if m:
            idx_code = m.group(1)
            st.session_state.stock_id = idx_code
            st.session_state.index_select_box = "選擇主要市場指數..."

with st.sidebar:
    st.header("參數設定")
    INDEX_CHOICES = [
        "選擇主要市場指數...",
        "加權指數 (^TWII)",
        "櫃買指數 (^TWOII)",
        "那斯達克 (^IXIC)",
        "費城半導體 (^SOX)",
        "道瓊工業 (^DJI)",
        "標普500 (^GSPC)",
        "日經225 (^N225)",
        "韓國綜合 (^KS11)",
        "英國富時100 (^FTSE)",
        "德國DAX (^GDAXI)",
        "法國CAC40 (^FCHI)"
    ]
    st.selectbox("主要市場指數", INDEX_CHOICES, key="index_select_box", on_change=on_index_select_change)

    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip() for item in history_records if item.get("code")]
    with st.expander("查詢歷史紀錄", expanded=False):
        if history_codes:
            history_display = [f"{h.get('code')} {h.get('name', '')}".strip() for h in history_records]
            current_ms_key = f"history_multiselect_{st.session_state.ms_counter}"
            selected_history = st.multiselect(
                "點擊展開並勾選標的...",
                options=history_display,
                default=[],
                key=current_ms_key
            )
            
            newly_selected = [item for item in selected_history if item not in st.session_state.history_multiselect_prev]
            if newly_selected:
                latest_clicked_code = newly_selected[-1].split()[0]
                all_codes = [item.split()[0] for item in selected_history]
                other_codes = [c for c in all_codes if c != latest_clicked_code]
                for c in other_codes:
                    save_stock_history(c)
                save_stock_history(latest_clicked_code)
                st.session_state.stock_id = latest_clicked_code
                st.session_state.history_multiselect_prev = []
                st.session_state.ms_counter += 1
                st.rerun()

            st.session_state.history_multiselect_prev = selected_history

            if st.button("清除歷史記錄", use_container_width=True):
                if selected_history:
                    target_codes = [item.split()[0] for item in selected_history]
                    remove_stocks_from_history(target_codes)
                    st.session_state.confirm_clear_all = False
                    st.session_state.history_multiselect_prev = []
                    st.session_state.ms_counter += 1
                    st.rerun()
                else:
                    st.session_state.confirm_clear_all = True
                    st.rerun()
        else:
            st.caption("目前無歷史紀錄")

    if st.session_state.confirm_clear_all:
        st.warning("⚠️ 未勾選任何標的，確定要清除全部歷史紀錄嗎？")
        c_del1, c_del2 = st.columns(2)
        with c_del1:
            if st.button("確認全刪", key="btn_confirm_delete_all", use_container_width=True):
                clear_stock_history()
                st.session_state.stock_id = "2330"
                st.session_state.confirm_clear_all = False
                st.session_state.history_multiselect_prev = []
                st.session_state.ms_counter += 1
                st.rerun()
        with c_del2:
            if st.button("取消", key="btn_cancel_delete_all", use_container_width=True):
                st.session_state.confirm_clear_all = False
                st.rerun()

    if "stock_input_box" not in st.session_state or st.session_state.stock_input_box != st.session_state.stock_id:
        st.session_state.stock_input_box = st.session_state.stock_id
    st.text_input("股票代號 (直接鍵入)", key="stock_input_box", on_change=on_stock_input_change)

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

    # 【防呆防錯備註 2026-11-07】：標題正名，明確包含穿透快取 (Cache) 與重新爬取籌碼功能
    force_refresh = st.checkbox("⚡ 強制更新（穿透快取與重抓籌碼）", value=False, help="勾選後將穿透記憶體快取 (Cache) 與本地資料庫，強制發動網路爬蟲重抓近30日籌碼資料。")
    if force_refresh:
        get_cached_figures.clear()

    if st.button("查詢", use_container_width=True):
        input_code = st.session_state.stock_input_box.strip()
        if input_code:
            resolved = resolve_ticker_code(input_code)
            st.session_state.stock_id = resolved
            if not resolved.startswith("^"):
                save_stock_history(resolved)
        st.rerun()
## 20261108 修訂強制更新資券資料 [開始]
    st.markdown("---")
    st.subheader("資券維護")
    refetch_weeks = st.number_input("重抓週數", min_value=1, max_value=24, value=6, step=1)
    if st.button("🛠️ 清除並重抓近N週資券", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無資券資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_weeks} 週資券紀錄..."):
                # 【防呆防錯備註 2026-11-08】【修訂目的】：
                # 點擊按鈕時直接發動 TWSE/TPEX 爬蟲爬取近 N 週資券，寫入資料庫後再清空快取並刷新，
                # 杜絕「重抓按鈕僅刪除資料庫，但重跑時因未勾選強制更新而未抓取，導致資料全空」之重工缺陷。
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_margin_short_data
                    from storage import StockChipStorage
                    from datetime import datetime, timedelta

                    k_res = fetch_stock_daily_k(cur_code, period="1y", force_refresh=False)
                    if k_res and k_res[0] is not None and not k_res[0].empty:
                        df_k = k_res[0]
                        cutoff_dt = datetime.now() - timedelta(days=int(refetch_weeks) * 7)
                        sub_dates = df_k.index[df_k.index >= cutoff_dt]
                        if len(sub_dates) == 0:
                            sub_dates = df_k.index[-int(refetch_weeks * 5):]

                        margin_records = fetch_margin_short_data(cur_code, sub_dates)
                        if margin_records and len(margin_records) > 0:
                            storage = StockChipStorage(cur_code)
                            storage.save_margin_data(margin_records)
                            st.sidebar.success(f"成功更新 {cur_code} 近 {refetch_weeks} 週共 {len(margin_records)} 筆資券！")
                        else:
                            st.sidebar.warning("爬取完成，但該區間未取得有效資券資料。")
                    else:
                        st.sidebar.error("無法取得該標的之歷史日K線交易日序列。")
                except Exception as e:
                    st.sidebar.error(f"重抓資券發生異常: {e}")

                get_cached_figures.clear()
                time.sleep(1.0)
                st.rerun()
## 20261108 修訂強制更新資券資料 [結束]  
auth_status = cloud_sync.get_auth_status()
if auth_status == 2:
    status_light = "🟡"
elif auth_status == 1:
    status_light = "🔵"
else:
    status_light = "⚪"

# 【防呆防錯備註 2026-11-07】：由 get_system_version() 唯一計算，絕不在模組內硬編碼覆寫
st.markdown(f"## 台股技術與籌碼分析 v{SYSTEM_VERSION} {status_light}")

stock_id = str(st.session_state.stock_id).strip()
if not stock_id:
    stock_id = "2330"
st.session_state.stock_id = stock_id

hist_records = load_stock_history()
hist_codes = [str(item.get("code")).strip() for item in hist_records if item.get("code")]
if stock_id not in hist_codes:
    active_nav_codes = [stock_id] + hist_codes
else:
    active_nav_codes = hist_codes

curr_idx = active_nav_codes.index(stock_id) if stock_id in active_nav_codes else 0

top_c1, top_c2 = st.columns(2)
with top_c1:
    if st.button("◀ 上一檔", key="btn_top_prev"):
        if len(active_nav_codes) > 1:
            prev_idx = (curr_idx - 1) % len(active_nav_codes)
            st.session_state.stock_id = active_nav_codes[prev_idx]
            st.rerun()
with top_c2:
    if st.button("下一檔 ▶", key="btn_top_next"):
        if len(active_nav_codes) > 1:
            next_idx = (curr_idx + 1) % len(active_nav_codes)
            st.session_state.stock_id = active_nav_codes[next_idx]
            st.rerun()

# 【防呆防錯備註 2026-11-07】：位置引數完整傳遞，避免關鍵字名稱衝突
fig_top, fig_btm, df, c_name, end_idx, disp_n = get_cached_figures(
    stock_id,
    st.session_state.period,
    st.session_state.disp_days,
    target_date_val,
    m1_thresh,
    m2_thresh,
    is_mobile,
    force_refresh
)

if fig_top is None or fig_btm is None or df is None or df.empty:
    st.error(f"無法取得代號 {stock_id} 之歷史行情資料，請確認網路連線或稍後點擊查詢重試。")
    st.stop()

if not stock_id.startswith("^") and c_name and c_name != stock_id:
    update_stock_name_only(stock_id, c_name)

top_height = 420 if is_mobile else 460
btm_height = 1180 if is_mobile else 1220
## 20261108 加權數向左平移時無法觸發回彈至右端。[開始]
# 【防呆防錯備註 2026-11-08】【修訂目的】：
# 傳入 is_index 旗標，精確告知前端 JS 是否為指數標的，
# 供 frontend.py 將副圖軸分為兩類同步 (Row 1~3 指數/個股共通，Row 4~9 僅個股)，杜絕空軸中斷平移回彈。
html_content = get_component_html(
    fig_top=fig_top,
    fig_btm=fig_btm,
    df=df,
    m1_thresh=m1_thresh,
    m2_thresh=m2_thresh,
    top_height=top_height,
    btm_height=btm_height,
    initial_disp_days=disp_n,
    initial_end_idx=end_idx,
    version_tag=SYSTEM_VERSION,
    is_index=stock_id.startswith("^")
)
## 20261108 加權數向左平移時無法觸發回彈至右端。[結束]
total_h = 1980 if is_mobile else 1880
components.html(html_content, height=total_h, scrolling=False)

btm_c1, btm_c2 = st.columns(2)
with btm_c1:
    if st.button("◀ 上一檔", key="btn_btm_prev"):
        if len(active_nav_codes) > 1:
            prev_idx = (curr_idx - 1) % len(active_nav_codes)
            st.session_state.stock_id = active_nav_codes[prev_idx]
            st.rerun()
with btm_c2:
    if st.button("下一檔 ▶", key="btn_btm_next"):
        if len(active_nav_codes) > 1:
            next_idx = (curr_idx + 1) % len(active_nav_codes)
            st.session_state.stock_id = active_nav_codes[next_idx]
            st.rerun()
