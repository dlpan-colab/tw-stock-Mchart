"""
app.py - 主應用程式介面與生命週期控制（三主頁籤路由總入口）
(依邏輯職責拆分為 app_broker_cache.py、app_dashboard.py、app_settings.py、app_stock_view.py 與本主入口，維持三主頁籤架構)
版本: 202611252130
"""

import os
import re
import streamlit as st

MODULE_NAME = "app"
MODULE_VERSION = "202611252130"


# 【防呆防錯備註 2026-11-24】：動態掃描主模組與所有拆分子模組之最大版本號，作為唯一系統版本號
def get_system_version() -> str:
    versions = [MODULE_VERSION]
    module_names = [
        "app_broker_cache",
        "app_dashboard",
        "app_settings",
        "app_stock_view",
        "frontend",
        "frnt_broker",
        "chart_builder",
        "chrt_chip",
        "indicators",
        "data_fetcher",
        "ftch_kline_chip",
        "ftch_tdcc_dash",
        "ftch_gov8",
        "ftch_broker",
        "storage",
        "strg_cloud_names",
        "strg_history_maint",
        "strg_broker_mixin",
        "config",
        "cloud_sync"
    ]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for mod_name in module_names:
        try:
            mod_file = os.path.join(base_dir, f"{mod_name}.py")
            if os.path.exists(mod_file):
                with open(mod_file, "r", encoding="utf-8") as f:
                    content = f.read(2000)
                m = re.search(r'MODULE_VERSION\s*=\s*["\'](\d{12})["\']', content)
                if m:
                    versions.append(m.group(1))
        except Exception:
            pass
    return max(versions)


SYSTEM_VERSION = get_system_version()

from storage import (
    load_stock_history,
    get_stock_chinese_name,
)
from chart_builder import build_split_figures
from app_dashboard import render_dashboard_tab
from app_settings import render_settings_tab
from app_stock_view import render_stock_tab

INDEX_MAP = {
    # 台股
    "TWII": "^TWII", "加權": "^TWII", "大盤": "^TWII", "^TWII": "^TWII",
    "TWOII": "^TWOII", "OTC": "^TWOII", "櫃買": "^TWOII", "^TWOII": "^TWOII",
    # 美股
    "DJI": "^DJI", "道瓊": "^DJI", "^DJI": "^DJI",
    "IXIC": "^IXIC", "COMP": "^IXIC", "那指": "^IXIC", "那斯達克": "^IXIC", "^IXIC": "^IXIC",
    "SOX": "^SOX", "費半": "^SOX", "半導體": "^SOX", "^SOX": "^SOX",
    "GSPC": "^GSPC", "SP500": "^GSPC", "標普500": "^GSPC", "^GSPC": "^GSPC",
    # 亞股
    "N225": "^N225", "NIKKEI": "^N225", "日經225": "^N225", "^N225": "^N225",
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


def _format_code_name_options(history_list: list) -> list:
    """確保下拉選項皆完整呈現 '代號 名稱'（若歷史紀錄缺名稱則自動補齊中文名稱）"""
    opts = []
    seen = set()
    for h in history_list:
        code = str(h.get("code", "")).strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        name = str(h.get("name", "")).strip()
        if not name or name == code:
            name = get_stock_chinese_name(code)
        lbl = f"{code} {name}".strip() if (name and name != code) else code
        opts.append(lbl)
    return opts


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
    initial_sidebar_state="collapsed"
)

# 【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
# 1. 修改目的：微調 `.stock-nav-4col-anchor` 左右切換按鈕寬度為 `64px`，確保手機版四鍵同列時
#    「◀ 上一檔」與「下一檔 ▶」完整顯示不出現 `...` 截斷。
# 2. 防呆防錯原因：維持中間兩欄下拉選單 `flex: 1 1 0` 與 `min-width: 0`，避免窄螢幕溢位換行。
st.markdown("""
<style>
    .block-container {
        padding-top: 2.6rem;
        padding-bottom: 1.5rem;
        padding-left: 0.85rem;
        padding-right: 0.85rem;
    }
    footer {visibility: hidden;}
    [data-testid="stSidebar"] {display: none !important;}
    [data-testid="collapsedControl"] {display: none !important;}

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

    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: space-between !important;
        gap: 6px !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(3) {
        flex: 0 0 64px !important;
        width: 64px !important;
        min-width: 64px !important;
        max-width: 64px !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        flex: 1 1 0 !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stSelectbox"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) div[data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) div[data-baseweb="select"] > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stSelectbox"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-baseweb="select"] > div {
        width: 100% !important;
        min-width: 0 !important;
        max-width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-anchor) [data-testid="stHorizontalBlock"] button {
        width: 100% !important;
        min-width: 60px !important;
        padding: 4px 2px !important;
        font-size: 11.5px !important;
        white-space: nowrap !important;
    }

    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: space-between !important;
        gap: 4px !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(4) {
        flex: 0 0 64px !important;
        width: 64px !important;
        min-width: 64px !important;
        max-width: 64px !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2),
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(3) {
        flex: 1 1 0 !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stSelectbox"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) div[data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) div[data-baseweb="select"] > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) [data-testid="stSelectbox"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) div[data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) div[data-baseweb="select"] > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stSelectbox"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-baseweb="select"] > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(3) > div,
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stSelectbox"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(3) div[data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(3) div[data-baseweb="select"] > div {
        width: 100% !important;
        min-width: 0 !important;
        max-width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.stock-nav-4col-anchor) [data-testid="stHorizontalBlock"] button {
        width: 100% !important;
        min-width: 60px !important;
        padding: 4px 2px !important;
        font-size: 11px !important;
        white-space: nowrap !important;
    }

    div[data-testid="stVerticalBlock"]:has(.settings-btn-row-anchor) [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: stretch !important;
        gap: 6px !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.settings-btn-row-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    div[data-testid="stVerticalBlock"]:has(.settings-btn-row-anchor) [data-testid="stHorizontalBlock"] > div {
        flex: 1 1 0 !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
    }
    div[data-testid="stVerticalBlock"]:has(.settings-btn-row-anchor) [data-testid="stHorizontalBlock"] button {
        width: 100% !important;
        min-width: 0 !important;
        padding: 5px 4px !important;
        font-size: 11.5px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }

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
        font-size: 12.5px !important;
        padding: 6px 4px !important;
        border-radius: 4px !important;
        white-space: nowrap !important;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background-color: #1e293b !important;
        color: #ffffff !important;
    }
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
    st.session_state.disp_days = 30
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
if "confirm_clear_brokers_range" not in st.session_state:
    st.session_state.confirm_clear_brokers_range = False
if "confirm_clear_gov_brokers" not in st.session_state:
    st.session_state.confirm_clear_gov_brokers = False
if "confirm_clear_chip_type" not in st.session_state:
    st.session_state.confirm_clear_chip_type = ""
if "index_select_box" not in st.session_state:
    st.session_state.index_select_box = "主要市場指數..."
if "ms_counter" not in st.session_state:
    st.session_state.ms_counter = 0
if "promote_to_top" not in st.session_state:
    st.session_state.promote_to_top = False
if "broker_60d_requests" not in st.session_state:
    st.session_state.broker_60d_requests = set()


# 【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
# 1. 修改目的：在個股查詢歷史下拉式選單中，無論點選既有標的或輸入新代號，皆設 `promote_to_top = True` 使選中個股自動置頂。
# 2. 防呆防錯原因：僅透過下拉選單主動選取時置頂，按「◀ 上一檔 / 下一檔 ▶」仍維持 `promote_to_top = False` 保持瀏覽順序。
def _apply_stock_selector_choice(widget_key: str):
    raw_sel = str(st.session_state.get(widget_key, "") or "").strip()
    if not raw_sel:
        return
    hist_now = load_stock_history()
    existing_labels = set(_format_code_name_options(hist_now))
    if raw_sel in existing_labels:
        target_code = raw_sel.split()[0].strip().upper()
        if target_code:
            st.session_state.stock_id = target_code
            st.session_state.promote_to_top = True
            st.session_state.confirm_clear_all = False
    else:
        first_token = raw_sel.split()[0].strip()
        resolved = resolve_ticker_code(first_token)
        if resolved:
            st.session_state.stock_id = resolved
            st.session_state.promote_to_top = True
            st.session_state.confirm_clear_all = False


def on_top_stock_selector_change():
    _apply_stock_selector_choice("top_stock_selector")


def on_bottom_stock_selector_change():
    _apply_stock_selector_choice("bottom_stock_selector")


def on_index_select_change():
    sel = st.session_state.index_select_box
    if sel and sel != "主要市場指數...":
        m = re.search(r'\((.*?)\)', sel)
        if m:
            idx_code = m.group(1)
            st.session_state.stock_id = idx_code
            st.session_state.promote_to_top = False
            st.session_state.confirm_clear_all = False
            st.session_state.active_main_tab = "📈 個股"
            st.session_state.index_select_box = "主要市場指數..."


if "pending_main_tab" in st.session_state:
    st.session_state.active_main_tab = st.session_state.pop("pending_main_tab")

selected_main_tab = st.radio(
    "主功能頁籤",
    MAIN_TABS,
    horizontal=True,
    label_visibility="collapsed",
    key="active_main_tab"
)

if selected_main_tab == "📊 操作儀錶板":
    render_dashboard_tab(
        system_version=SYSTEM_VERSION,
        resolve_ticker_fn=resolve_ticker_code,
    )
elif selected_main_tab == "⚙️ 參數設定":
    render_settings_tab(
        system_version=SYSTEM_VERSION,
        clear_figures_cache_fn=get_cached_figures.clear,
    )
else:
    render_stock_tab(
        system_version=SYSTEM_VERSION,
        format_options_fn=_format_code_name_options,
        on_top_selector_change_fn=on_top_stock_selector_change,
        on_bottom_selector_change_fn=on_bottom_stock_selector_change,
        on_index_change_fn=on_index_select_change,
        get_figures_fn=get_cached_figures,
    )
## EOF app.py
