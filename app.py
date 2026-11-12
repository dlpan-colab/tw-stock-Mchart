"""
app.py - 主應用程式介面與生命週期控制 (修正上一檔/下一檔不改動歷史順序、緊湊留白與底部安全墊高版)
版本: 202611122115
"""

import os
import time
import re
import streamlit as st
import streamlit.components.v1 as components
import cloud_sync

MODULE_NAME = "app"
MODULE_VERSION = "202611122115"

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
    clear_recent_margin_data,
    clear_recent_institutional_data
)
from chart_builder import build_split_figures
from frontend import get_legend_html, get_component_html

INDEX_MAP = {
    # 台股
    "TWII": "^TWII", "加權": "^TWII", "大盤": "^TWII", "^TWII": "^TWII",
    "TWOII": "^TWOII", "OTC": "^TWOII", "櫃買": "^TWII", "^TWOII": "^TWOII",
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

@st.cache_data(ttl=180, show_spinner=False)
def get_cached_figures(stock_id, period, disp_days, base_date, m1_thresh, m2_thresh, is_mobile, force_refresh):
    return build_split_figures(
        raw_ticker=stock_id,
        period=period,
        display_days=disp_days,
        base_date=base_date,
        major1_thresh=m1_thresh,
        major2_thresh=m2_thresh,
        is_mobile=is_mobile,
        status_placeholder=None,
        force_refresh=force_refresh
    )

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

    force_refresh = st.checkbox(
        "⚡ 強制更新（穿透快取與重抓籌碼）",
        value=False,
        help="勾選後將穿透記憶體快取 (Cache) 與本地資料庫，強制發動網路爬蟲重抓籌碼資料。"
    )
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

    # 【防呆防錯備註 2026-11-10】【修訂目的】：
    # 法人籌碼維護重抓預設週數改為 1 週 (value=1)，符合常態維護需求
    st.markdown("---")
    st.subheader("法人籌碼維護")
    refetch_inst_weeks = st.number_input("重抓法人週數", min_value=1, max_value=24, value=1, step=1)
    if st.button("🛠️ 清除並重抓近N週法人籌碼", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無三大法人買賣超資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_inst_weeks} 週法人籌碼..."):
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_institutional_investors
                    from storage import StockChipStorage
                    from datetime import datetime, timedelta
                    k_res = fetch_stock_daily_k(cur_code, period="1y", force_refresh=False)
                    if k_res and k_res[0] is not None and not k_res[0].empty:
                        df_k = k_res[0]
                        full_tkr = k_res[1]
                        cutoff_dt = datetime.now() - timedelta(days=int(refetch_inst_weeks) * 7)
                        sub_dates = [d for d in df_k.index if d >= cutoff_dt]
                        if sub_dates:
                            clear_recent_institutional_data(cur_code, int(refetch_inst_weeks))
                            fresh_inst = fetch_institutional_investors(
                                pure_code=cur_code,
                                df_dates=df_k.index,
                                explicit_missing_dates=sub_dates,
                                full_ticker=full_tkr
                            )
                            if fresh_inst:
                                storage = StockChipStorage(cur_code)
                                storage.save_institutional_data(fresh_inst)
                                st.sidebar.success(f"成功重抓並更新 {len(fresh_inst)} 筆法人籌碼紀錄！")
                                get_cached_figures.clear()
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.sidebar.warning("伺服器未回傳法人資料，請稍後再試。")
                        else:
                            st.sidebar.warning("找不到對應週數的交易日紀錄。")
                    else:
                        st.sidebar.error("無法載入該標的日K線資料。")
                except Exception as e:
                    st.sidebar.error(f"法人重抓失敗: {e}")

    # 【防呆防錯備註 2026-11-10】【修訂目的】：
    # 資券維護重抓預設週數改為 1 週 (value=1)，符合常態維護需求
    st.markdown("---")
    st.subheader("資券維護")
    refetch_weeks = st.number_input("重抓週數", min_value=1, max_value=24, value=1, step=1)
    if st.button("🛠️ 清除並重抓近N週資券", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無資券資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_weeks} 週資券紀錄..."):
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_margin_short_data
                    from storage import StockChipStorage
                    from datetime import datetime, timedelta
                    k_res = fetch_stock_daily_k(cur_code, period="1y", force_refresh=False)
                    if k_res and k_res[0] is not None and not k_res[0].empty:
                        df_k = k_res[0]
                        cutoff_dt = datetime.now() - timedelta(days=int(refetch_weeks) * 7)
                        sub_dates = [d for d in df_k.index if d >= cutoff_dt]
                        if sub_dates:
                            clear_recent_margin_data(cur_code, int(refetch_weeks))
                            fresh_records = fetch_margin_short_data(
                                cur_code,
                                df_k.index,
                                start_date_exclusive=(cutoff_dt - timedelta(days=1)).strftime('%Y-%m-%d')
                            )
                            if fresh_records:
                                storage = StockChipStorage(cur_code)
                                storage.save_margin_data(fresh_records)
                                st.sidebar.success(f"成功重抓並更新 {len(fresh_records)} 筆資券資料！")
                                get_cached_figures.clear()
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.sidebar.warning("未自 FinMind 取得更新資料，請稍後再試。")
                        else:
                            st.sidebar.warning("找不到對應週數的交易日紀錄。")
                    else:
                        st.sidebar.error("無法載入該標的日K線資料。")
                except Exception as e:
                    st.sidebar.error(f"資券重抓失敗: {e}")

    st.markdown("---")
    st.subheader("大戶持股維護")
    st.caption("ℹ️ 集保於當週各交易日不予公告，直到當週最後交易日之次日（週六）公布。")
    refetch_holding_weeks = st.number_input("重抓集保週數", min_value=1, max_value=24, value=6, step=1)
    if st.button("🛠️ 增補近N週集保歷史", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無集保大戶資料。")
        else:
            with st.spinner(f"正在連線集保結算所增補 {cur_code} 近 {refetch_holding_weeks} 週歷史分級..."):
                try:
                    from data_fetcher import fetch_tdcc_holding_history
                    from storage import StockChipStorage
                    fresh_holdings = fetch_tdcc_holding_history(cur_code, weeks=int(refetch_holding_weeks))
                    if fresh_holdings:
                        storage = StockChipStorage(cur_code)
                        storage.save_holding_data(fresh_holdings)
                        unique_dates = len(set(r[0] for r in fresh_holdings))
                        st.sidebar.success(f"成功增補 {unique_dates} 週 (共 {len(fresh_holdings)} 筆分級) 集保大戶紀錄！")
                        get_cached_figures.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.sidebar.warning("集保伺服器未回傳歷史資料，請稍候重試。")
                except Exception as e:
                    st.sidebar.error(f"大戶持股增補失敗: {e}")

auth_status = cloud_sync.get_auth_status()
if auth_status == 2:
    status_icon = "🟡"
elif auth_status == 1:
    status_icon = "🔵"
else:
    status_icon = "⚪"

st.markdown(f"### 台股技術與籌碼分析 v{SYSTEM_VERSION} {status_icon}")

def navigate_stock(direction: int):
    """
    【修訂說明 2026-11-11】：
    修改目的：落實上一檔／下一檔純瀏覽，絕不改動查詢歷史清單排列順序。
    防呆防錯原因：原先在此處呼叫 save_stock_history(target_code) 會將當前股票自動移至歷史第 0 位（置頂），
                  導致歷史清單在每次導航時動態重排，游標陷入前兩檔互換的死循環，無法讀取第三檔以後。
                  修訂後移除 save_stock_history，僅改變 session_state.stock_id 供頁面渲染，
                  清單置頂行為僅保留於「文字框手動輸入」、「點擊查詢」與「歷史清單主動點選」。
    """
    history_records = load_stock_history()
    codes = [str(item.get("code")).strip() for item in history_records if item.get("code")]
    if not codes:
        return
    cur_code = str(st.session_state.stock_id).strip()
    if cur_code in codes:
        idx = codes.index(cur_code)
        next_idx = (idx + direction) % len(codes)
        target_code = codes[next_idx]
    else:
        target_code = codes[0]
    st.session_state.stock_id = target_code
    # 【已移除 save_stock_history(target_code)】避免上一檔／下一檔時清單順序被動態置頂改動

col_nav1, col_nav2 = st.columns(2)
with col_nav1:
    if st.button("◀ 上一檔", key="nav_prev_top"):
        navigate_stock(-1)
        st.rerun()
with col_nav2:
    if st.button("下一檔 ▶", key="nav_next_top"):
        navigate_stock(1)
        st.rerun()

status_box = st.empty()

with st.spinner(f"正在載入 {st.session_state.stock_id} 圖表資料..."):
    fig_top, fig_btm, df, c_name, end_idx, disp_n = get_cached_figures(
        stock_id=st.session_state.stock_id,
        period=st.session_state.period,
        disp_days=st.session_state.disp_days,
        base_date=target_date_val,
        m1_thresh=m1_thresh,
        m2_thresh=m2_thresh,
        is_mobile=is_mobile,
        force_refresh=force_refresh
    )

if fig_top is None or fig_btm is None or df is None or df.empty:
    st.error(f"無法載入標的【{st.session_state.stock_id}】的技術指標資料，請確認代號是否正確。")
else:
    pure_code = str(st.session_state.stock_id).strip().upper()
    real_c_name = c_name or get_stock_chinese_name(pure_code)
    if real_c_name and real_c_name != pure_code:
        update_stock_name_only(pure_code, real_c_name)

    chart_uuid = f"chart_{pure_code.replace('^', '').replace('.', '_')}"
    html_content = get_component_html(
        fig_top=fig_top,
        fig_btm=fig_btm,
        df=df,
        chart_id=chart_uuid,
        is_mobile=is_mobile,
        initial_disp_days=st.session_state.disp_days,
        initial_end_idx=end_idx,
        m1_thresh=m1_thresh,
        m2_thresh=m2_thresh
    )
    
    # 【修訂說明 2026-11-11】：
    # 修改目的：緊縮 components.html 高度，解決底部的上/下一檔與資訊條之間空白過大的問題。
    # 防呆防錯原因：原先 2100px 超出實體圖表與資訊條總高，造成 iframe 底部溢出約 250px 空白；
    #               調整為 1800px / 1780px 緊密包覆內容，且不影響 Plotly 手勢操作。
    total_h = 1800 if is_mobile else 1780
    components.html(html_content, height=total_h, scrolling=False)

col_nav_b1, col_nav_b2 = st.columns(2)
with col_nav_b1:
    if st.button("◀ 上一檔", key="nav_prev_btm"):
        navigate_stock(-1)
        st.rerun()
with col_nav_b2:
    if st.button("下一檔 ▶", key="nav_next_btm"):
        navigate_stock(1)
        st.rerun()

# 【修訂說明 2026-11-12】：
# 修改目的：在「上一檔／下一檔」底部按鈕列下方增加一行空白安全高度，避開右下角官方懸浮的 Manage app 黑條。
# 防呆防錯原因：手機瀏覽時「Manage app」固定於視窗右下角底緣（position: fixed; bottom: 0; right: 0），
#               若無此空白墊高區，滑到底部時「下一檔 ▶」會直接被黑條遮蓋無法點擊。
st.markdown('<div style="height: 48px;"></div>', unsafe_allow_html=True)
