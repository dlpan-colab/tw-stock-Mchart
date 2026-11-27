"""
app_dashboard.py - 主頁籤 1「📊 操作儀錶板」介面渲染模組
(自 app.py 依邏輯職責拆分，維持既有自選清單同步、盤中均線多空燈號與點擊股名跳轉機制)
版本: 202611272230
"""

import os
import streamlit as st

from storage import (
    load_stock_history,
    save_stock_history,
    remove_stocks_from_history,
    get_stock_chinese_name,
)
from data_fetcher import fetch_dashboard_watchlist_rows

MODULE_NAME = "app_dashboard"
MODULE_VERSION = "202611272230"

_DASH_INDEX_MAP = {
    "TWII": "^TWII", "加權": "^TWII", "大盤": "^TWII", "^TWII": "^TWII",
    "TWOII": "^TWOII", "OTC": "^TWOII", "櫃買": "^TWOII", "^TWOII": "^TWOII",
    "DJI": "^DJI", "道瓊": "^DJI", "^DJI": "^DJI",
    "IXIC": "^IXIC", "COMP": "^IXIC", "那指": "^IXIC", "那斯達克": "^IXIC", "^IXIC": "^IXIC",
    "SOX": "^SOX", "費半": "^SOX", "半導體": "^SOX", "^SOX": "^SOX",
    "GSPC": "^GSPC", "SP500": "^GSPC", "標普500": "^GSPC", "^GSPC": "^GSPC",
    "N225": "^N225", "NIKKEI": "^N225", "日經225": "^N225", "^N225": "^N225",
    "KS11": "^KS11", "KOSPI": "^KS11", "韓綜": "^KS11", "^KS11": "^KS11",
    "FTSE": "^FTSE", "富時": "^FTSE", "英國富時100": "^FTSE", "^FTSE": "^FTSE",
    "GDAXI": "^GDAXI", "DAX": "^GDAXI", "德國DAX": "^GDAXI", "^GDAXI": "^GDAXI",
    "FCHI": "^FCHI", "CAC40": "^FCHI", "法國CAC40": "^FCHI", "^FCHI": "^FCHI",
}


def _default_resolve_ticker(raw_input: str) -> str:
    upper = str(raw_input or "").strip().upper()
    return _DASH_INDEX_MAP.get(upper, upper)


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_dashboard_rows(codes_tuple: tuple) -> list:
    """快取操作儀錶板報價 60 秒，避免頻繁切換主頁籤重複請求"""
    if not codes_tuple:
        return []
    hist_list = load_stock_history()
    return fetch_dashboard_watchlist_rows(hist_list)


def render_dashboard_tab(
    system_version: str,
    main_tabs=None,
    clear_figures_cache_fn=None,
    resolve_ticker_fn=None,
):
    """
    【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 對齊 `app.py` 呼叫參數簽章（新增 `main_tabs` 與 `clear_figures_cache_fn`），消除切換至「📊 操作儀錶板」或點擊「下一檔」時的 `TypeError`。
       - 新增／刪除自選股時同步呼叫 `clear_figures_cache_fn()` 清除圖表快取，並將點擊股名跳轉鍵名同步更新為 `st.session_state.active_main_tab`。
    2. 防呆防錯原因：若呼叫端未傳入 `resolve_ticker_fn`，自動回退使用 `_default_resolve_ticker`，維持完全向後相容。
    """
    resolver = resolve_ticker_fn if callable(resolve_ticker_fn) else _default_resolve_ticker
    target_stock_tab = main_tabs[1] if (main_tabs and len(main_tabs) > 1) else "📈 個股"

    st.markdown(
        f"<div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:6px;'>"
        f"📊 操作儀錶板 <span style='font-size:12px; color:#64748b; font-weight:600;'>v{system_version}（與查詢歷史清單同步）</span></div>",
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
                resolved_c = resolver(raw_c)
                c_name = get_stock_chinese_name(resolved_c)
                save_stock_history(resolved_c, c_name)
                get_cached_dashboard_rows.clear()
                if callable(clear_figures_cache_fn):
                    clear_figures_cache_fn()
                st.rerun()
            else:
                st.warning("請先輸入股票代號。")
    with c_del:
        if st.button("刪除", key="btn_dash_del", use_container_width=True):
            raw_c = str(dash_code_input or "").strip().upper()
            if raw_c:
                resolved_c = resolver(raw_c)
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
                    st.session_state.promote_to_top = False
                get_cached_dashboard_rows.clear()
                if callable(clear_figures_cache_fn):
                    clear_figures_cache_fn()
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
        return

    latest_d_str = next((r["trade_date"] for r in dash_rows if r["trade_date"] != "-"), "-")
    st.caption(
        f"資料基準日：{latest_d_str} ｜ 均線燈號規則：成交價 > 5日/20日均線顯示紅色 ▲；成交價 <= 5日/20日均線顯示綠色 ▼（直接點擊表單內「股票名稱」即可進入個股圖表，維持清單原順序不置頂）"
    )

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
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > div {
            flex: 1 1 0 !important;
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            text-align: center !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1),
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > div:nth-child(1) {
            flex: 1.55 1 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(.dash-grid-anchor) [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(5),
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
                st.session_state.promote_to_top = False
                st.session_state.active_main_tab = target_stock_tab
                st.rerun()
        row_cols[1].markdown(f"<div class='dash-cell'>{r['code']}</div>", unsafe_allow_html=True)
        row_cols[2].markdown(f"<div class='dash-cell'>{r['market']}</div>", unsafe_allow_html=True)
        row_cols[3].markdown(f"<div class='dash-cell'><b>{p_str}</b></div>", unsafe_allow_html=True)
        row_cols[4].markdown(f"<div class='dash-cell'>{v_str}</div>", unsafe_allow_html=True)
        row_cols[5].markdown(f"<div class='dash-cell'>{ma5_html}</div>", unsafe_allow_html=True)
        row_cols[6].markdown(f"<div class='dash-cell'>{ma20_html}</div>", unsafe_allow_html=True)
## EOF app_dashboard.py
