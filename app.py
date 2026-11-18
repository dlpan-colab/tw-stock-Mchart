"""
app.py - 主應用程式介面與生命週期控制
(三主頁籤架構：操作儀錶板 / 個股 / 參數設定 + 自選與查詢歷史同步 + 盤中均線多空燈號 + 動態chart_id杜絕跨頁籤殘留 + 批次增補近N日分點統計與明細即時進度版)
版本: 202611190710
"""
import os
import time
import re
import streamlit as st
import streamlit.components.v1 as components
import cloud_sync

MODULE_NAME = "app"
MODULE_VERSION = "202611190710"


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
    StockChipStorage,
    load_stock_history,
    save_stock_history,
    clear_stock_history,
    remove_stocks_from_history,
    update_stock_name_only,
    get_stock_chinese_name,
    clear_recent_margin_data,
    clear_recent_institutional_data,
    clear_all_broker_data,
    is_tw_stock_or_etf
)
from chart_builder import build_split_figures
from frontend import (
    get_legend_html,
    get_top_chart_html,
    get_tech_tab_html,
    get_chip_tab_html,
    get_broker_tab_html
)
from data_fetcher import (
    fetch_stock_broker_range_ranking,
    fetch_single_broker_daily_series,
    fetch_dashboard_watchlist_rows
)

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
    "FTSE": "^FTSE", "富時": "^FTSE", "英國富時100": "^FTSE", "^FTSE": "^FTSE",
    "GDAXI": "^GDAXI", "DAX": "^GDAXI", "德國DAX": "^GDAXI", "^GDAXI": "^GDAXI",
    "FCHI": "^FCHI", "CAC40": "^FCHI", "法國CAC40": "^FCHI", "^FCHI": "^FCHI",
}


def resolve_ticker_code(raw_input: str) -> str:
    cleaned = str(raw_input).strip()
    upper = cleaned.upper()
    if upper in INDEX_MAP:
        return INDEX_MAP[upper]
    return upper


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_dashboard_rows(codes_tuple: tuple) -> list:
    """快取操作儀錶板報價 60 秒，避免頻繁切換主頁籤重複請求"""
    if not codes_tuple:
        return []
    hist_list = load_stock_history()
    return fetch_dashboard_watchlist_rows(hist_list)


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


@st.cache_data(ttl=600, show_spinner=False)
def get_cached_broker_payload(
    stock_id: str,
    trade_dates_tuple: tuple,
    target_end_idx: int,
    force_refresh: bool = False,
    include_60d: bool = False
) -> dict:
    code = str(stock_id).strip().upper()
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code) or not trade_dates_tuple:
        return {"by_date": {}}

    n_dates = len(trade_dates_tuple)
    safe_idx = min(max(0, int(target_end_idx)), n_dates - 1)
    end_date_str = trade_dates_tuple[safe_idx]

    def get_start_date_by_window(win_days: int) -> str:
        s_i = max(0, safe_idx - win_days + 1)
        return trade_dates_tuple[s_i]

    win_starts = {
        1: end_date_str,
        10: get_start_date_by_window(10),
        20: get_start_date_by_window(20),
        60: get_start_date_by_window(60),
    }

    target_windows = (1, 10, 20, 60) if include_60d else (1, 10, 20)
    series_windows = (10, 20, 60) if include_60d else (10, 20)
    earliest_start = win_starts[60] if include_60d else win_starts[20]

    storage = StockChipStorage(code)

    def _has_valid_win(bundle_obj: dict, w_num: int) -> bool:
        if not isinstance(bundle_obj, dict):
            return False
        w_item = bundle_obj.get(f"w{w_num}")
        if not isinstance(w_item, dict):
            return False
        return bool(w_item.get("buy") or w_item.get("sell"))

    def attach_cloud_series_to_bundle(bundle: dict) -> dict:
        for w in (10, 20, 60):
            w_key = f"w{w}"
            s_str = win_starts[w]
            w_obj = bundle.get(w_key)
            if not isinstance(w_obj, dict):
                continue
            for side_rank_key, series_key in (("buy", "top5_buy_series"), ("sell", "top5_sell_series")):
                rank_rows = w_obj.get(side_rank_key, [])[:5]
                out_series = []
                for r in rank_rows:
                    b_name = str(r.get("name", "")).strip()
                    tot_net = int(r.get("net", 0))
                    df_d = storage.load_broker_daily_series(b_name, s_str, end_date_str)
                    if df_d is not None and not df_d.empty:
                        dates_arr = df_d["日期"].tolist()
                        nets_arr = [int(v) for v in df_d["買賣超(張)"].tolist()]
                    else:
                        dates_arr, nets_arr = [], []
                    out_series.append({
                        "name": b_name,
                        "total_net": tot_net,
                        "dates": dates_arr,
                        "nets": nets_arr
                    })
                w_obj[series_key] = out_series
        return bundle

    cached_rank = None if force_refresh else storage.load_broker_range_rank(end_date_str)
    if cached_rank is not None:
        base_ok = all(_has_valid_win(cached_rank, w) for w in (1, 10, 20))
        need_60_missing = include_60d and (not _has_valid_win(cached_rank, 60))
        if base_ok and not need_60_missing:
            hydrated = attach_cloud_series_to_bundle(cached_rank)
            return {"by_date": {end_date_str: hydrated}}

    def df_to_rank_records(df_rank):
        if df_rank is None or df_rank.empty:
            return []
        recs = []
        for _, r in df_rank.head(10).iterrows():
            recs.append({
                "name": str(r.get("分點名稱", "")),
                "sys": str(r.get("體系", "")),
                "buy": int(r.get("買進(張)", 0)),
                "sell": int(r.get("賣出(張)", 0)),
                "net": int(r.get("買賣超(張)", 0)),
                "ratio": str(r.get("佔比", "-")),
            })
        return recs

    if cached_rank is not None and not force_refresh:
        fetch_windows = [w for w in target_windows if not _has_valid_win(cached_rank, w)]
        if not fetch_windows:
            fetch_windows = list(target_windows)
    else:
        fetch_windows = list(target_windows)

    rank_dfs = {}
    for idx_w, w in enumerate(fetch_windows):
        s_str = win_starts[w]
        df_b, df_s = fetch_stock_broker_range_ranking(code, s_str, end_date_str)
        if (df_b is None or df_b.empty) and (df_s is None or df_s.empty):
            time.sleep(0.35)
            df_b, df_s = fetch_stock_broker_range_ranking(code, s_str, end_date_str)
        rank_dfs[w] = (df_b, df_s)
        if idx_w < len(fetch_windows) - 1:
            time.sleep(0.15)

    broker_url_map = {}
    for w in fetch_windows:
        if w not in series_windows:
            continue
        df_b, df_s = rank_dfs.get(w, (None, None))
        for df_side in (df_b, df_s):
            if df_side is not None and not df_side.empty:
                for _, row in df_side.head(5).iterrows():
                    b_name = str(row.get("分點名稱", "")).strip()
                    d_url = str(row.get("明細網址", "")).strip()
                    if b_name and d_url and b_name not in broker_url_map:
                        broker_url_map[b_name] = d_url

    for b_name, d_url in broker_url_map.items():
        df_fresh = fetch_single_broker_daily_series(d_url, earliest_start, end_date_str)
        if df_fresh is not None and not df_fresh.empty:
            storage.save_broker_daily_trades(b_name, df_fresh, sync_cloud=False)
        time.sleep(0.08)

    day_bundle = dict(cached_rank) if (isinstance(cached_rank, dict) and not force_refresh) else {}
    has_any_rank = False
    for w in fetch_windows:
        s_str = win_starts[w]
        df_b, df_s = rank_dfs.get(w, (None, None))
        b_recs = df_to_rank_records(df_b)
        s_recs = df_to_rank_records(df_s)
        if b_recs or s_recs:
            has_any_rank = True
        label = end_date_str if w == 1 else f"{s_str} ~ {end_date_str}"
        day_bundle[f"w{w}"] = {
            "range_label": label,
            "buy": b_recs,
            "sell": s_recs,
        }

    if has_any_rank or day_bundle:
        storage.save_broker_range_rank(end_date_str, day_bundle, sync_cloud=True)
        hydrated_new = attach_cloud_series_to_bundle(day_bundle)
        return {"by_date": {end_date_str: hydrated_new}}

    return {"by_date": {}}


# 【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
# 修改目的：改為三主頁籤架構並預設收合側邊欄，頂部設置受控三主頁籤（📊 操作儀錶板 / 📈 個股 / ⚙️ 參數設定）。
# 防呆防錯原因：使用 st.radio(horizontal=True) 搭配 CSS 樣式呈現主頁籤列，可由程式直接切換至「📈 個股」主頁籤（st.tabs 無法從程式切換頁籤）。
st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .block-container {padding-top: 2.6rem; padding-bottom: 1.5rem; padding-left: 0.85rem; padding-right: 0.85rem;}
    footer {visibility: hidden;}
    [data-testid="stSidebar"] {display: none !important;}
    [data-testid="collapsedControl"] {display: none !important;}

    /* 頂部三主頁籤（st.radio horizontal）擬真分頁外觀 */
    div[data-testid="stRadio"] > div[role="radiogroup"] {
        display: flex !important;
        flex-direction: row !important;
        width: 100% !important;
        gap: 6px !important;
        background: #dbeafe !important;
        padding: 5px 6px 0px 6px !important;
        border-radius: 10px 10px 0 0 !important;
        border-bottom: 2px solid #93c5fd !important;
        margin-bottom: 6px !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label {
        flex: 1 1 0 !important;
        justify-content: center !important;
        text-align: center !important;
        background: #eff6ff !important;
        border: 1px solid #bfdbfe !important;
        border-bottom: none !important;
        border-radius: 8px 8px 0 0 !important;
        padding: 7px 6px !important;
        margin: 0 !important;
        cursor: pointer !important;
        font-weight: 700 !important;
        font-size: 14px !important;
        color: #1e3a8a !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) {
        background: #ffffff !important;
        color: #0f172a !important;
        border-color: #93c5fd !important;
        box-shadow: 0 -2px 5px rgba(15, 23, 42, 0.06) !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }

    /* 上一檔 / 下一檔按鈕列自適應寬度 */
    [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 8px !important;
    }
    [data-testid="stHorizontalBlock"] > div:has(button) {
        flex: 0 0 68px !important;
        width: 68px !important;
        min-width: 68px !important;
        max-width: 68px !important;
    }
    [data-testid="stHorizontalBlock"] > div:not(:has(button)) {
        flex: 1 1 auto !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
    }
    [data-testid="stHorizontalBlock"] button {
        width: 100% !important;
        min-width: 64px !important;
        padding: 3px 4px !important;
        font-size: 12px !important;
        white-space: nowrap !important;
    }

    /* 個股子頁籤（指標 / 籌碼 / 分點） */
    [data-testid="stTabs"] [role="tablist"] {
        display: flex !important;
        width: 100% !important;
        gap: 4px !important;
        background: #eef2f6 !important;
        padding: 3px !important;
        border-radius: 6px !important;
        border: 1px solid #cbd5e1 !important;
    }
    [data-testid="stTabs"] [role="tab"] {
        flex: 1 1 0 !important;
        justify-content: center !important;
        font-weight: 700 !important;
        font-size: 13.5px !important;
        padding: 6px 8px !important;
        border-radius: 4px !important;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background-color: #1e293b !important;
        color: #ffffff !important;
    }

    /* 操作儀錶板表格樣式 */
    .dash-tbl-wrap {
        width: 100%;
        overflow-x: auto;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #ffffff;
        margin-top: 6px;
        margin-bottom: 8px;
    }
    .dash-tbl {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        text-align: center;
        white-space: nowrap;
    }
    .dash-tbl th {
        background: #f1f5f9;
        color: #1e293b;
        font-weight: 700;
        padding: 7px 6px;
        border-bottom: 1.5px solid #94a3b8;
    }
    .dash-tbl td {
        padding: 6px 6px;
        border-bottom: 1px solid #e2e8f0;
        color: #0f172a;
    }
    .dash-up {color: #eb4d4b !important; font-weight: 900 !important; font-size: 15px !important;}
    .dash-dn {color: #16a085 !important; font-weight: 900 !important; font-size: 15px !important;}
</style>
""", unsafe_allow_html=True)

initial_history = load_stock_history()
default_code = "2330"
if initial_history:
    first_code = str(initial_history[0].get("code", "")).strip().upper()
    if first_code:
        default_code = first_code

MAIN_TABS = ["📊 操作儀錶板", "📈 個股", "⚙️ 參數設定"]

if "active_main_tab" not in st.session_state:
    st.session_state.active_main_tab = "📈 個股"
if "stock_id" not in st.session_state:
    st.session_state.stock_id = default_code
if "period" not in st.session_state:
    st.session_state.period = "1y"
if "disp_days" not in st.session_state:
    st.session_state.disp_days = 20
if "is_mobile_mode" not in st.session_state:
    st.session_state.is_mobile_mode = True
if "use_target_date" not in st.session_state:
    st.session_state.use_target_date = False
if "target_date_val" not in st.session_state:
    st.session_state.target_date_val = None
if "m1_thresh" not in st.session_state:
    st.session_state.m1_thresh = 1000
if "m2_thresh" not in st.session_state:
    st.session_state.m2_thresh = 400
if "force_refresh" not in st.session_state:
    st.session_state.force_refresh = False
if "confirm_clear_all" not in st.session_state:
    st.session_state.confirm_clear_all = False
if "confirm_clear_brokers" not in st.session_state:
    st.session_state.confirm_clear_brokers = False
if "index_select_box" not in st.session_state:
    st.session_state.index_select_box = "選擇主要市場指數..."
if "ms_counter" not in st.session_state:
    st.session_state.ms_counter = 0
if "promote_to_top" not in st.session_state:
    st.session_state.promote_to_top = False
if "broker_60d_requests" not in st.session_state:
    st.session_state.broker_60d_requests = set()


def on_stock_input_change():
    val = st.session_state.stock_input_box.strip()
    if val:
        resolved = resolve_ticker_code(val)
        st.session_state.stock_id = resolved
        st.session_state.promote_to_top = True


def on_index_select_change():
    sel = st.session_state.index_select_box
    if sel != "選擇主要市場指數...":
        m = re.search(r'\((.*?)\)', sel)
        if m:
            idx_code = m.group(1)
            st.session_state.stock_id = idx_code
            st.session_state.promote_to_top = False
            st.session_state.active_main_tab = "📈 個股"
        st.session_state.index_select_box = "選擇主要市場指數..."


def on_history_select_change():
    cur_key = f"history_selectbox_{st.session_state.ms_counter}"
    sel = st.session_state.get(cur_key, "選擇歷史紀錄...")
    if sel and sel != "選擇歷史紀錄...":
        target_code = sel.split()[0].strip().upper()
        if target_code:
            st.session_state.stock_id = target_code
            st.session_state.pending_stock_input = target_code
            st.session_state.promote_to_top = True
            st.session_state.confirm_clear_all = False
            st.session_state.active_main_tab = "📈 個股"


# ---------------------------------------------------------------------
# 頂部三主頁籤導覽列
# ---------------------------------------------------------------------
if "pending_main_tab" in st.session_state:
    st.session_state.active_main_tab = st.session_state.pop("pending_main_tab")

selected_main_tab = st.radio(
    "主功能頁籤",
    MAIN_TABS,
    horizontal=True,
    label_visibility="collapsed",
    key="active_main_tab"
)


# =====================================================================
# 主頁籤 1：📊 操作儀錶板（自選清單與查詢歷史同步 + 盤中均線多空燈號）
# =====================================================================
if selected_main_tab == "📊 操作儀錶板":
    st.markdown(
        f"<div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:6px;'>"
        f"📊 操作儀錶板 <span style='font-size:12px; color:#64748b; font-weight:600;'>v{SYSTEM_VERSION}（與查詢歷史清單同步）</span></div>",
        unsafe_allow_html=True
    )

    c_in, c_add, c_del, c_ref = st.columns([3.2, 1.3, 1.3, 1.4])
    with c_in:
        dash_code_input = st.text_input(
            "股票代號",
            placeholder="輸入股票代號 (如 2330、00632R)",
            label_visibility="collapsed",
            key="dash_watchlist_input"
        )
    with c_add:
        if st.button("新增", key="btn_dash_add", use_container_width=True):
            raw_c = str(dash_code_input or "").strip().upper()
            if raw_c:
                resolved_c = resolve_ticker_code(raw_c)
                c_name = get_stock_chinese_name(resolved_c)
                save_stock_history(resolved_c, c_name)
                get_cached_dashboard_rows.clear()
                st.rerun()
            else:
                st.warning("請先輸入股票代號。")
    with c_del:
        if st.button("刪除", key="btn_dash_del", use_container_width=True):
            raw_c = str(dash_code_input or "").strip().upper()
            if raw_c:
                resolved_c = resolve_ticker_code(raw_c)
                remained = remove_stocks_from_history([resolved_c])
                local_db = f"data_{resolved_c}.db"
                if os.path.exists(local_db):
                    try:
                        os.remove(local_db)
                    except Exception:
                        pass
                if str(st.session_state.stock_id).strip().upper() == resolved_c:
                    next_c = remained[0]["code"] if remained else "2330"
                    st.session_state.stock_id = next_c
                    st.session_state.pending_stock_input = next_c
                    st.session_state.promote_to_top = False
                get_cached_dashboard_rows.clear()
                st.rerun()
            else:
                st.warning("請輸入要刪除的股票代號。")
    with c_ref:
        if st.button("🔄 刷新", key="btn_dash_refresh", use_container_width=True):
            get_cached_dashboard_rows.clear()
            st.rerun()

    hist_now = load_stock_history()
    codes_tuple = tuple(str(h.get("code", "")).strip().upper() for h in hist_now if h.get("code"))

    with st.spinner("正在更新操作儀錶板報價與均線燈號..."):
        dash_rows = get_cached_dashboard_rows(codes_tuple)

    if not dash_rows:
        st.info("目前自選／查詢歷史清單尚無台股個股或 ETF，請於上方輸入股票代號並點擊「新增」。")
    else:
        latest_d_str = next((r["trade_date"] for r in dash_rows if r["trade_date"] != "-"), "-")
        st.caption(
            f"資料基準日：{latest_d_str} ｜ 均線燈號規則：成交價 > 5日/20日均線顯示紅色 ▲；成交價 <= 5日/20日均線顯示綠色 ▼（直接點擊表單內「股票名稱」即可進入個股圖表，維持清單原順序不置頂）"
        )
        # 【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
        # 修改目的：將操作儀錶板表格內的「股票名稱」改為原生可點擊按鈕，點擊後直接跳轉「📈 個股」主頁籤並保留清單原順序，同時移除下方重複按鈕列。
        # 防呆防錯原因：加入 dash-grid-row 專用橫向不換行與文字按鈕樣式，防止手機窄螢幕將 7 欄自動折疊成垂直卡片，確保表格閱讀體驗一致。
        st.markdown("""
        <style>
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: center !important;
            gap: 2px !important;
            border-bottom: 1px solid #e2e8f0 !important;
            padding: 3px 0 !important;
            margin: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > div {
            flex: 1 1 0 !important;
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            text-align: center !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(1) {
            flex: 1.55 1 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(5) {
            flex: 1.25 1 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] button {
            background: transparent !important;
            border: 1px solid transparent !important;
            color: #1d4ed8 !important;
            font-weight: 800 !important;
            font-size: 13px !important;
            padding: 2px 4px !important;
            min-height: 28px !important;
            text-decoration: underline !important;
            box-shadow: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] button:hover {
            background: #eff6ff !important;
            border-color: #93c5fd !important;
        }
        .dash-hdr-cell {background:#f1f5f9; color:#1e293b; font-weight:700; font-size:12.5px; padding:6px 2px; text-align:center;}
        .dash-cell {font-size:12.5px; color:#0f172a; text-align:center; padding:4px 2px; white-space:nowrap;}
        </style>
        <div class="dash-grid-anchor"></div>
        """, unsafe_allow_html=True)

        col_ratios = [1.55, 1.0, 0.85, 1.05, 1.25, 0.9, 0.9]
        hdr_cols = st.columns(col_ratios)
        headers_txt = ["股票名稱", "代號", "市/櫃", "成交價", "成交量(張)", "5日均線", "20日均線"]
        for c_obj, h_txt in zip(hdr_cols, headers_txt):
            c_obj.markdown(f"<div class='dash-hdr-cell'>{h_txt}</div>", unsafe_allow_html=True)

        for r in dash_rows:
            p_val = r["price"]
            v_val = r["vol_sheets"]
            ma5_v = r["ma5"]
            ma20_v = r["ma20"]
            p_str = f"{p_val:.2f}" if p_val is not None else "-"
            v_str = f"{int(round(v_val)):,}" if v_val is not None else "-"
            if p_val is not None and ma5_v is not None:
                ma5_html = "<span class='dash-up'>▲</span>" if p_val > ma5_v else "<span class='dash-dn'>▼</span>"
            else:
                ma5_html = "-"
            if p_val is not None and ma20_v is not None:
                ma20_html = "<span class='dash-up'>▲</span>" if p_val > ma20_v else "<span class='dash-dn'>▼</span>"
            else:
                ma20_html = "-"

            row_cols = st.columns(col_ratios)
            with row_cols[0]:
                if st.button(r["name"], key=f"dash_name_jump_{r['code']}", use_container_width=True):
                    st.session_state.stock_id = r["code"]
                    st.session_state.pending_stock_input = r["code"]
                    st.session_state.promote_to_top = False
                    st.session_state.pending_main_tab = "📈 個股"
                    st.rerun()
            row_cols[1].markdown(f"<div class='dash-cell'>{r['code']}</div>", unsafe_allow_html=True)
            row_cols[2].markdown(f"<div class='dash-cell'>{r['market']}</div>", unsafe_allow_html=True)
            row_cols[3].markdown(f"<div class='dash-cell'><b>{p_str}</b></div>", unsafe_allow_html=True)
            row_cols[4].markdown(f"<div class='dash-cell'>{v_str}</div>", unsafe_allow_html=True)
            row_cols[5].markdown(f"<div class='dash-cell'>{ma5_html}</div>", unsafe_allow_html=True)
            row_cols[6].markdown(f"<div class='dash-cell'>{ma20_html}</div>", unsafe_allow_html=True)


# =====================================================================
# 主頁籤 3：⚙️ 參數設定（原左側邊欄所有參數與籌碼維護完整收納）
# =====================================================================
elif selected_main_tab == "⚙️ 參數設定":
    st.markdown(
        f"<div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:6px;'>"
        f"⚙️ 參數設定與資料庫維護 <span style='font-size:12px; color:#64748b; font-weight:600;'>v{SYSTEM_VERSION}</span></div>",
        unsafe_allow_html=True
    )

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
    st.selectbox(
        "主要市場指數",
        INDEX_CHOICES,
        key="index_select_box",
        on_change=on_index_select_change
    )

    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip().upper() for item in history_records if item.get("code")]

    with st.expander("查詢歷史紀錄", expanded=True):
        if history_codes:
            history_options = ["選擇歷史紀錄..."] + [
                f"{h.get('code')} {h.get('name', '')}".strip() for h in history_records
            ]
            current_sb_key = f"history_selectbox_{st.session_state.ms_counter}"
            selected_history = st.selectbox(
                "點擊展開並選擇單一標的（選擇後將置頂並跳轉至個股頁籤）...",
                options=history_options,
                index=0,
                key=current_sb_key,
                on_change=on_history_select_change
            )
            if st.button("清除紀錄", key="btn_clear_hist", use_container_width=True):
                if selected_history and selected_history != "選擇歷史紀錄...":
                    target_code = selected_history.split()[0].strip().upper()
                    remained = remove_stocks_from_history([target_code])
                    local_db = f"data_{target_code}.db"
                    if os.path.exists(local_db):
                        try:
                            os.remove(local_db)
                        except Exception:
                            pass
                    if str(st.session_state.stock_id).strip().upper() == target_code:
                        next_code = remained[0]["code"] if remained else "2330"
                        st.session_state.stock_id = next_code
                        st.session_state.pending_stock_input = next_code
                        st.session_state.promote_to_top = False
                    st.session_state.confirm_clear_all = False
                    st.session_state.ms_counter += 1
                    get_cached_dashboard_rows.clear()
                    st.rerun()
                else:
                    st.session_state.confirm_clear_all = True
                    st.rerun()
        else:
            st.caption("目前無歷史紀錄")

        if st.session_state.confirm_clear_all:
            st.warning("⚠️ 未選取任何標的，確定要清除全部歷史紀錄嗎？")
            c_del1, c_del2 = st.columns(2)
            with c_del1:
                if st.button("確認全刪", key="btn_confirm_delete_all", use_container_width=True):
                    clear_stock_history()
                    st.session_state.stock_id = "2330"
                    st.session_state.pending_stock_input = "2330"
                    st.session_state.promote_to_top = False
                    st.session_state.confirm_clear_all = False
                    st.session_state.ms_counter += 1
                    get_cached_dashboard_rows.clear()
                    st.rerun()
            with c_del2:
                if st.button("取消", key="btn_cancel_delete_all", use_container_width=True):
                    st.session_state.confirm_clear_all = False
                    st.rerun()

    if "pending_stock_input" in st.session_state:
        st.session_state.stock_input_box = st.session_state.pop("pending_stock_input")
    elif "stock_input_box" not in st.session_state:
        st.session_state.stock_input_box = st.session_state.stock_id

    st.text_input("股票代號 (直接鍵入)", key="stock_input_box", on_change=on_stock_input_change)

    period_opts = ["6mo", "1y", "2y", "5y", "max"]
    p_idx = period_opts.index(st.session_state.period) if st.session_state.period in period_opts else 1
    st.session_state.period = st.selectbox("下載區間", period_opts, index=p_idx)

    mode_opts = ["手機版 (Mobile) - 預設20日", "電腦版 (Desktop) - 預設60日"]
    m_idx = 0 if st.session_state.is_mobile_mode else 1
    mode_switch = st.selectbox("模式切換", mode_opts, index=m_idx)
    new_is_mobile = "手機版" in mode_switch
    if new_is_mobile != st.session_state.is_mobile_mode:
        st.session_state.is_mobile_mode = new_is_mobile
        st.session_state.disp_days = 20 if new_is_mobile else 60

    st.session_state.disp_days = st.number_input(
        "顯示日數", min_value=10, max_value=240, value=int(st.session_state.disp_days), step=5
    )

    st.session_state.use_target_date = st.checkbox("指定基準日 (復盤模式)", value=st.session_state.use_target_date)
    if st.session_state.use_target_date:
        t_in = st.text_input("基準日 (YYYY-MM-DD)", value=st.session_state.target_date_val or "")
        st.session_state.target_date_val = t_in.strip() if t_in.strip() else None
    else:
        st.session_state.target_date_val = None

    st.session_state.m1_thresh = st.number_input("大戶門檻1 (張)", min_value=100, max_value=2000, value=int(st.session_state.m1_thresh), step=100)
    st.session_state.m2_thresh = st.number_input("大戶門檻2 (張)", min_value=100, max_value=1000, value=int(st.session_state.m2_thresh), step=100)

    st.session_state.force_refresh = st.checkbox(
        "⚡ 強制更新（穿透快取與重抓籌碼）",
        value=st.session_state.force_refresh,
        help="勾選後將穿透記憶體快取 (Cache) 與本地資料庫，強制發動網路爬蟲重抓籌碼資料。"
    )
    if st.session_state.force_refresh:
        get_cached_figures.clear()
        get_cached_broker_payload.clear()

    if st.button("查詢並返回個股圖表", use_container_width=True):
        input_code = st.session_state.stock_input_box.strip()
        if input_code:
            resolved = resolve_ticker_code(input_code)
            st.session_state.stock_id = resolved
            st.session_state.promote_to_top = True
        st.session_state.pending_main_tab = "📈 個股"
        st.rerun()

    st.markdown("---")
    st.subheader("法人籌碼維護")
    refetch_inst_weeks = st.number_input("重抓法人週數", min_value=1, max_value=24, value=1, step=1)
    if st.button("🛠️ 清除並重抓近N週法人籌碼", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip().upper()
        if cur_code.startswith("^"):
            st.warning("指數標的無三大法人買賣超資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_inst_weeks} 週法人籌碼..."):
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_institutional_investors
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
                                st.success(f"成功重抓並更新 {len(fresh_inst)} 筆法人籌碼紀錄！")
                                get_cached_figures.clear()
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.warning("伺服器未回傳法人資料，請稍後再試。")
                        else:
                            st.warning("找不到對應週數的交易日紀錄。")
                    else:
                        st.error("無法載入該標的日K線資料。")
                except Exception as e:
                    st.error(f"法人重抓失敗: {e}")

    st.markdown("---")
    st.subheader("資券維護")
    refetch_weeks = st.number_input("重抓週數", min_value=1, max_value=24, value=1, step=1)
    if st.button("🛠️ 清除並重抓近N週資券", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip().upper()
        if cur_code.startswith("^"):
            st.warning("指數標的無資券資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_weeks} 週資券紀錄..."):
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_margin_short_data
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
                                st.success(f"成功重抓並更新 {len(fresh_records)} 筆資券資料！")
                                get_cached_figures.clear()
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.warning("未自 FinMind 取得更新資料，請稍後再試。")
                        else:
                            st.warning("找不到對應週數的交易日紀錄。")
                    else:
                        st.error("無法載入該標的日K線資料。")
                except Exception as e:
                    st.error(f"資券重抓失敗: {e}")

    st.markdown("---")
    st.subheader("大戶持股維護[個股/Findmind]")
    st.caption("ℹ️ 集保於當週各交易日不予公告，直到當週最後交易日之次日（週六）公布。")
    refetch_holding_weeks = st.number_input("重抓集保週數", min_value=1, max_value=24, value=6, step=1)
    if st.button("🛠️ 增補近N週集保歷史", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip().upper()
        if cur_code.startswith("^"):
            st.warning("指數標的無集保大戶資料。")
        else:
            with st.spinner(f"正在連線 FinMind 增補 {cur_code} 近 {refetch_holding_weeks} 週歷史分級..."):
                try:
                    from data_fetcher import fetch_tdcc_holding_history
                    fresh_holdings = fetch_tdcc_holding_history(cur_code, weeks=int(refetch_holding_weeks))
                    if fresh_holdings:
                        storage = StockChipStorage(cur_code)
                        storage.save_holding_data(fresh_holdings)
                        unique_dates = len(set(r[0] for r in fresh_holdings))
                        st.success(f"成功增補 {unique_dates} 週 (共 {len(fresh_holdings)} 筆分級) 集保大戶紀錄！")
                        get_cached_figures.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("未自 FinMind 取得集保分級資料，請稍後再試。")
                except Exception as e:
                    st.error(f"集保增補失敗: {e}")

    st.markdown("---")
    st.subheader("[上市/上櫃]批次作業")
    if st.button("📥 擷取最近一週大戶持股比例資料", use_container_width=True):
        with st.spinner("正在連線集保開放資料網 / FinMind 批次擷取最近一週全市場大戶持股分級並寫入資料庫..."):
            try:
                from data_fetcher import batch_fetch_and_save_latest_tdcc_holding
                res_batch = batch_fetch_and_save_latest_tdcc_holding()
                if res_batch.get("ok"):
                    st.success(res_batch.get("msg", "批次寫入完成！"))
                    get_cached_figures.clear()
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.warning(res_batch.get("msg", "未取得集保開放資料，請稍後再試。"))
            except Exception as e:
                st.error(f"集保批次作業失敗: {e}")

    # 【修訂說明 2026-11-19】【修改目的與防呆防錯原因】：
    # 修改目的：新增批次增補所有資料庫個股近 N 日分點統計（1/10/20/60日）與分點逐日明細（前5名60日逐日買賣超）兩個獨立作業按鈕，並附帶即時進度條與狀態文字。
    # 防呆防錯原因：透過 progress_callback 即時刷新畫面進度條與單檔處理狀態，避免長時間批次執行時畫面無回應；完成後清除分點快取。
    backfill_broker_days = st.number_input(
        "增補分點日數 (N)",
        min_value=1,
        max_value=60,
        value=5,
        step=1,
        key="input_backfill_broker_days"
    )
    if st.button("📊 增補近N日分點統計", key="btn_backfill_broker_ranks", use_container_width=True):
        prog_bar = st.progress(0)
        prog_text = st.empty()

        def _on_rank_progress(done_cnt: int, total_cnt: int, msg_line: str):
            ratio = min(1.0, max(0.0, done_cnt / total_cnt)) if total_cnt > 0 else 0.0
            prog_bar.progress(ratio)
            prog_text.info(msg_line)

        try:
            from data_fetcher import batch_backfill_broker_range_ranks
            res_rank = batch_backfill_broker_range_ranks(
                recent_days=int(backfill_broker_days),
                progress_callback=_on_rank_progress
            )
            prog_bar.progress(1.0)
            if res_rank.get("ok"):
                get_cached_broker_payload.clear()
                prog_text.empty()
                st.success(res_rank.get("msg", "分點統計增補完成！"))
            else:
                prog_text.empty()
                st.warning(res_rank.get("msg", "未取得分點統計資料，請稍後再試。"))
        except Exception as e:
            prog_text.empty()
            st.error(f"批次增補分點統計失敗: {e}")

    if st.button("📈 增補近N日分點明細", key="btn_backfill_broker_series", use_container_width=True):
        prog_bar = st.progress(0)
        prog_text = st.empty()

        def _on_series_progress(done_cnt: int, total_cnt: int, msg_line: str):
            ratio = min(1.0, max(0.0, done_cnt / total_cnt)) if total_cnt > 0 else 0.0
            prog_bar.progress(ratio)
            prog_text.info(msg_line)

        try:
            from data_fetcher import batch_backfill_broker_daily_series
            res_ser = batch_backfill_broker_daily_series(
                recent_days=int(backfill_broker_days),
                progress_callback=_on_series_progress
            )
            prog_bar.progress(1.0)
            if res_ser.get("ok"):
                get_cached_broker_payload.clear()
                prog_text.empty()
                st.success(res_ser.get("msg", "分點逐日明細增補完成！"))
            else:
                prog_text.empty()
                st.warning(res_ser.get("msg", "未取得分點逐日明細，請稍後再試。"))
        except Exception as e:
            prog_text.empty()
            st.error(f"批次增補分點明細失敗: {e}")

    if st.button("🗑️ 清除分點", key="btn_clear_all_brokers", use_container_width=True):
        st.session_state.confirm_clear_brokers = True
        st.rerun()

    if st.session_state.confirm_clear_brokers:
        st.warning("⚠️ 確定要清除本地及雲端所有個股的分點統計與逐日明細嗎？（日線、法人、資券與集保大戶資料將完整保留）")
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("確認清除分點", key="btn_confirm_clear_brokers", use_container_width=True):
                with st.spinner("正在清除本地與雲端所有個股分點資料..."):
                    msg_res = clear_all_broker_data()
                    get_cached_broker_payload.clear()
                    st.session_state.broker_60d_requests = set()
                    st.session_state.confirm_clear_brokers = False
                    st.success(msg_res)
                    time.sleep(0.8)
                    st.rerun()
        with cb2:
            if st.button("取消", key="btn_cancel_clear_brokers", use_container_width=True):
                st.session_state.confirm_clear_brokers = False
                st.rerun()


# =====================================================================
# 主頁籤 2：📈 個股（完整單股 K 線、指標、籌碼、分點分析畫面）
# =====================================================================
else:
    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip().upper() for item in history_records if item.get("code")]
    if "pending_stock_input" in st.session_state:
        st.session_state.stock_input_box = st.session_state.pop("pending_stock_input")

    current_stock = str(st.session_state.stock_id).strip().upper()
    if not current_stock:
        current_stock = "2330"

    if st.session_state.promote_to_top:
        save_stock_history(current_stock)
        st.session_state.promote_to_top = False
        history_records = load_stock_history()
        history_codes = [str(item.get("code")).strip().upper() for item in history_records if item.get("code")]

    has_history = len(history_codes) > 0
    if has_history:
        if current_stock in history_codes:
            curr_idx = history_codes.index(current_stock)
            prev_code = history_codes[(curr_idx - 1) % len(history_codes)]
            next_code = history_codes[(curr_idx + 1) % len(history_codes)]
        else:
            prev_code = history_codes[0]
            next_code = history_codes[0]
    else:
        prev_code = current_stock
        next_code = current_stock

    try:
        auth_status = cloud_sync.get_auth_status()
    except Exception:
        auth_status = 0

    if auth_status == 2:
        status_icon = "🟡"
    elif auth_status == 1:
        status_icon = "🔵"
    else:
        status_icon = "⚪"

    top_c1, top_c2, top_c3 = st.columns([6.4, 1.3, 1.3])
    with top_c1:
        st.markdown(
            f"<div style='line-height: 1.25; padding: 2px 0; white-space: nowrap;'>"
            f"<div style='font-size: 16px; font-weight: 800; color: #0f172a;'>台股技術與籌碼分析</div>"
            f"<div style='font-size: 11.5px; color: #64748b; font-weight: 600;'>v{SYSTEM_VERSION} {status_icon}</div>"
            f"</div>",
            unsafe_allow_html=True
        )
    with top_c2:
        if st.button("◀ 上一檔", key="btn_top_prev", disabled=(not has_history), use_container_width=True):
            st.session_state.stock_id = prev_code
            st.session_state.pending_stock_input = prev_code
            st.session_state.promote_to_top = False
            st.rerun()
    with top_c3:
        if st.button("下一檔 ▶", key="btn_top_next", disabled=(not has_history), use_container_width=True):
            st.session_state.stock_id = next_code
            st.session_state.pending_stock_input = next_code
            st.session_state.promote_to_top = False
            st.rerun()

    st.markdown(get_legend_html(), unsafe_allow_html=True)

    with st.spinner(f"正在載入 {current_stock} 技術與籌碼資料..."):
        fig_top, fig_btm, df, c_name, disp_n, end_idx = get_cached_figures(
            stock_id=current_stock,
            period=st.session_state.period,
            disp_days=st.session_state.disp_days,
            base_date=st.session_state.target_date_val,
            m1_thresh=st.session_state.m1_thresh,
            m2_thresh=st.session_state.m2_thresh,
            is_mobile=st.session_state.is_mobile_mode,
            force_refresh=st.session_state.force_refresh
        )

    if fig_top is not None and df is not None and not df.empty:
        if c_name and c_name != current_stock:
            update_stock_name_only(current_stock, c_name)

        # 【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
        # 修改目的：確保未開啟復盤基準日時 safe_end_idx 無條件精準鎖定最新交易日 (len(df) - 1)。
        # 防呆防錯原因：原先僅判斷 safe_end_idx <= 0 才重設，若快取回傳殘留之中間索引（如 19），會導致初始視窗誤停於歷史舊日。
        if not st.session_state.use_target_date:
            safe_end_idx = len(df) - 1
        else:
            safe_end_idx = int(end_idx) if end_idx is not None else (len(df) - 1)
        safe_end_idx = min(max(0, safe_end_idx), len(df) - 1)

        cid_suffix = re.sub(r"[^A-Za-z0-9_]", "_", f"{current_stock}_{safe_end_idx}_{disp_n}")

        top_h = 270 if st.session_state.is_mobile_mode else 310
        tech_h = 540 if st.session_state.is_mobile_mode else 580
        chip_h = 760 if st.session_state.is_mobile_mode else 800

        top_html = get_top_chart_html(
            fig_top=fig_top,
            df=df,
            chart_id=f"mchart_top_{cid_suffix}",
            top_height=top_h,
            initial_disp_days=int(st.session_state.disp_days),
            initial_end_idx=safe_end_idx
        )
        components.html(top_html, height=top_h + 62, scrolling=False)

        tab_tech, tab_chip, tab_broker = st.tabs(["📊 指標", "💰 籌碼", "🏦 分點"])

        with tab_tech:
            tech_html = get_tech_tab_html(
                fig_btm=fig_btm,
                df=df,
                chart_id=f"mchart_tech_{cid_suffix}",
                tech_height=tech_h,
                initial_disp_days=int(st.session_state.disp_days),
                initial_end_idx=safe_end_idx
            )
            components.html(tech_html, height=tech_h + 75, scrolling=False)

        with tab_chip:
            chip_html = get_chip_tab_html(
                fig_btm=fig_btm,
                df=df,
                chart_id=f"mchart_chip_{cid_suffix}",
                chip_height=chip_h,
                initial_disp_days=int(st.session_state.disp_days),
                initial_end_idx=safe_end_idx,
                m1_thresh=st.session_state.m1_thresh,
                m2_thresh=st.session_state.m2_thresh
            )
            components.html(chip_html, height=chip_h + 85, scrolling=False)

        with tab_broker:
            trade_dates_tuple = tuple(d.strftime('%Y-%m-%d') for d in df.index)
            focus_date_str = trade_dates_tuple[safe_end_idx] if trade_dates_tuple else ""
            req_60_key = f"{current_stock}_{focus_date_str}"
            need_60d = req_60_key in st.session_state.broker_60d_requests

            if not current_stock.startswith("^") and is_tw_stock_or_etf(current_stock) and focus_date_str:
                if not need_60d:
                    if st.button(
                        f"📥 載入近 60 日分點統計與明細（基準日 {focus_date_str}）",
                        key=f"btn_load_60d_{req_60_key}",
                        use_container_width=True
                    ):
                        st.session_state.broker_60d_requests.add(req_60_key)
                        st.rerun()
                else:
                    st.caption(f"✅ 已載入近 60 日分點統計與明細（基準日 {focus_date_str}）")

            with st.spinner(
                f"正在載入 {current_stock} {'近 60 日' if need_60d else '近 20 日'}分點統計與明細..."
            ):
                broker_payload = get_cached_broker_payload(
                    stock_id=current_stock,
                    trade_dates_tuple=trade_dates_tuple,
                    target_end_idx=safe_end_idx,
                    force_refresh=st.session_state.force_refresh,
                    include_60d=need_60d
                )
            broker_html = get_broker_tab_html(
                df=df,
                broker_payload=broker_payload,
                chart_id=f"mchart_broker_{cid_suffix}",
                end_idx=safe_end_idx,
                disp_days=disp_n,
                is_mobile=st.session_state.is_mobile_mode
            )
            components.html(broker_html, height=1350, scrolling=False)

        display_name = c_name if c_name else get_stock_chinese_name(current_stock)
        btm_c1, btm_c2, btm_c3 = st.columns([6.4, 1.3, 1.3])
        with btm_c1:
            st.markdown(
                f"<div style='font-size:12.5px; color:#475569; padding-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>"
                f"📌 目前標的：<b>{current_stock} {display_name}</b></div>",
                unsafe_allow_html=True
            )
        with btm_c2:
            if st.button("◀ 上一檔", key="btn_btm_prev", disabled=(not has_history), use_container_width=True):
                st.session_state.stock_id = prev_code
                st.session_state.pending_stock_input = prev_code
                st.session_state.promote_to_top = False
                st.rerun()
        with btm_c3:
            if st.button("下一檔 ▶", key="btn_btm_next", disabled=(not has_history), use_container_width=True):
                st.session_state.stock_id = next_code
                st.session_state.pending_stock_input = next_code
                st.session_state.promote_to_top = False
                st.rerun()
    else:
        st.error(f"❌ 無法載入標的 `{current_stock}` 的日K線資料，請確認股票代號是否正確或稍後再試。")
