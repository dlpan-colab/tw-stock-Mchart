"""
app_stock_view.py - 主頁籤 2「📈 個股」介面渲染模組
(自 app.py 依邏輯職責拆分，維持上下雙複合選單、共用主圖與四大子頁籤互動機制，並整合四鍵同列與獨立代號輸入框)
版本: 202611281625
"""

import re
import streamlit as st
import streamlit.components.v1 as components

import cloud_sync
from storage import (
    load_stock_history,
    save_stock_history,
    remove_stocks_from_history,
    update_stock_name_only,
    get_stock_chinese_name,
    is_tw_stock_or_etf,
    is_tw_index_with_gov_brokers,
)
from frontend import (
    get_legend_html,
    get_top_chart_html,
    get_tech_tab_html,
    get_chip_tab_html,
    get_broker_stats_tab_html,
    get_broker_daily_tab_html,
)
from app_broker_cache import get_cached_broker_payload
from ftch_broker import ensure_focus_date_broker_daily_series

MODULE_NAME = "app_stock_view"
MODULE_VERSION = "202611281625"


def _on_direct_code_input_change():
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：獨立 `st.text_input` 輸入股票或指數代號按 Enter 送出時，自動轉大寫並透過 `app.resolve_ticker_code` 正規化後切換 `st.session_state.stock_id`，並設定 `clear_direct_code_input = True` 供下一輪渲染前安全清空輸入框。
    2. 防呆防錯原因：嚴禁於 `on_change` 回呼內直接改寫已綁定之 `st.session_state.direct_stock_code_input`，
       避免觸發 `StreamlitWidgetAlreadyInstantiatedError` 導致切換標的失敗。
    """
    raw_txt = str(st.session_state.get("direct_stock_code_input", "") or "").strip()
    if not raw_txt:
        return
    token = raw_txt.split()[0]
    from app import resolve_ticker_code
    new_code = resolve_ticker_code(token)
    if new_code:
        st.session_state.stock_id = new_code
        st.session_state.promote_to_top = True
        st.session_state.confirm_clear_all = False
        st.session_state.clear_direct_code_input = True


def render_stock_tab(
    system_version: str,
    format_options_fn,
    on_top_selector_change_fn,
    on_bottom_selector_change_fn,
    on_index_change_fn,
    get_figures_fn,
):
    """
    【修訂說明 2026-11-28】【修改目的與防呆防錯原因】：
    1. 修改目的：在個股載入分點資料前，若目前關注交易日（如 2026-06-04）尚未具備近 10／20 日分點日況逐日明細，
       自動呼叫 `ensure_focus_date_broker_daily_series` 按需補抓並清除 `get_cached_broker_payload` 快取，
       確保點擊任一歷史交易日切換至「📈 分點日況」時皆能正常顯示柱狀圖（且寫入資料庫後第二次點選免重抓）。
    2. 防呆防錯原因：僅針對個股且缺少該關注日日況明細時執行補抓，保留既有 iframe 高度設定、四鍵同列與雙複合選單邏輯。
    """
    auth_st = cloud_sync.get_auth_status()
    status_icon = "🟡" if auth_st == 2 else ("🔵" if auth_st == 1 else "⚪")
    st.markdown(
        f"<div style='font-size:15px; font-weight:700; color:#1e293b; margin-bottom:2px;'>"
        f"台股技術與籌碼分析 <span style='font-size:12px; color:#64748b;'>v{system_version} {status_icon}</span></div>",
        unsafe_allow_html=True
    )

    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip().upper() for item in history_records if item.get("code")]
    selector_options = format_options_fn(history_records)

    cur_code_upper = str(st.session_state.stock_id).strip().upper()
    cur_name_resolved = get_stock_chinese_name(cur_code_upper)
    cur_display_label = next(
        (opt for opt in selector_options if opt.split()[0] == cur_code_upper),
        f"{cur_code_upper} {cur_name_resolved}".strip() if (cur_name_resolved and cur_name_resolved != cur_code_upper) else cur_code_upper
    )
    if cur_display_label not in selector_options:
        selector_options = [cur_display_label] + selector_options
    cur_sel_idx = selector_options.index(cur_display_label)

    index_options = [
        "主要市場指數...",
        "🇹🇼 台股加權 (^TWII)",
        "🇹🇼 台股櫃買 (^TWOII)",
        "🇺🇸 道瓊工業 (^DJI)",
        "🇺🇸 那斯達克 (^IXIC)",
        "🇺🇸 費城半導體 (^SOX)",
        "🇺🇸 標普500 (^GSPC)",
        "🇯🇵 日經225 (^N225)",
        "🇰🇷 韓國綜合 (^KS11)",
        "🇬🇧 英國富時100 (^FTSE)",
        "🇩🇪 德國DAX (^GDAXI)",
        "🇫🇷 法國CAC40 (^FCHI)",
    ]

    # 第 1 列：四功能同列並排「◀ 上一檔」＋「主要市場指數」＋「個股查詢歷史(純下拉)」＋「下一檔 ▶」
    with st.container():
        st.markdown("<div class='stock-nav-4col-anchor'></div>", unsafe_allow_html=True)
        col_prev, col_idx, col_input, col_next = st.columns([1, 3, 3, 1])
        with col_prev:
            if st.button("◀ 上一檔", key="btn_top_prev", use_container_width=True):
                if history_codes:
                    idx = history_codes.index(cur_code_upper) if cur_code_upper in history_codes else 0
                    prev_code = history_codes[(idx - 1) % len(history_codes)]
                    st.session_state.stock_id = prev_code
                    st.session_state.promote_to_top = False
                    st.session_state.confirm_clear_all = False
                    st.rerun()
        with col_idx:
            st.selectbox(
                "主要市場指數",
                index_options,
                key="index_select_box",
                on_change=on_index_change_fn,
                label_visibility="collapsed"
            )
        with col_input:
            st.selectbox(
                "個股查詢歷史",
                options=selector_options,
                index=cur_sel_idx,
                key="top_stock_selector",
                on_change=on_top_selector_change_fn,
                label_visibility="collapsed"
            )
        with col_next:
            if st.button("下一檔 ▶", key="btn_top_next", use_container_width=True):
                if history_codes:
                    idx = history_codes.index(cur_code_upper) if cur_code_upper in history_codes else 0
                    next_code = history_codes[(idx + 1) % len(history_codes)]
                    st.session_state.stock_id = next_code
                    st.session_state.promote_to_top = False
                    st.session_state.confirm_clear_all = False
                    st.rerun()

    # 第 2 列：左側「獨立代號輸入框（防 Android 鍵盤游標反轉）」＋ 右側「清除查詢個股紀錄」
    if st.session_state.pop("clear_direct_code_input", False):
        st.session_state.direct_stock_code_input = ""
    with st.container():
        st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
        col_code_box, col_clr_hist = st.columns([1, 1])
        with col_code_box:
            st.text_input(
                "輸入代號查詢",
                key="direct_stock_code_input",
                on_change=_on_direct_code_input_change,
                placeholder="輸入代號按Enter (如 2330, 00632R)",
                label_visibility="collapsed"
            )
        with col_clr_hist:
            if st.button("清除查詢個股紀錄", key="btn_clear_stock_history_row", use_container_width=True):
                st.session_state.confirm_clear_all = False
                if cur_code_upper not in history_codes and not cur_code_upper.startswith("^"):
                    # 目前畫面為尚未寫入歷史清單之無效暫存輸入（如誤輸入 1），直接還原回原置頂標的
                    st.session_state.stock_id = history_codes[0] if history_codes else "2330"
                    st.session_state.promote_to_top = False
                    st.rerun()
                elif history_codes:
                    top_code = history_codes[0]
                    rem_hist = remove_stocks_from_history([top_code])
                    from app_dashboard import get_cached_dashboard_rows
                    get_cached_dashboard_rows.clear()
                    if rem_hist:
                        st.session_state.stock_id = str(rem_hist[0].get("code", "2330")).strip().upper()
                    else:
                        st.session_state.stock_id = "2330"
                    st.session_state.promote_to_top = False
                    st.rerun()

    st.markdown(get_legend_html(), unsafe_allow_html=True)

    current_force = bool(st.session_state.force_refresh)
    active_refresh_cfg = None
    broker_force_days = 0
    broker_base_date = ""
    if current_force:
        st.session_state.force_refresh = False
        raw_cfg = st.session_state.get("force_refresh_cfg")
        if isinstance(raw_cfg, dict):
            active_refresh_cfg = dict(raw_cfg)
        else:
            active_refresh_cfg = {
                "base_date": "",
                "kline_enabled": True,
                "kline_days": 120,
                "foreign_enabled": True,
                "foreign_days": 120,
                "trust_enabled": True,
                "trust_days": 120,
                "dealer_enabled": True,
                "dealer_days": 120,
                "margin_enabled": True,
                "margin_days": 120,
                "holding_enabled": True,
                "holding_weeks": 1,
                "broker_enabled": True,
                "broker_days": 120,
            }
        broker_base_date = str(active_refresh_cfg.get("base_date", "") or "").strip()
        if active_refresh_cfg.get("broker_enabled", True):
            broker_force_days = max(1, int(active_refresh_cfg.get("broker_days", 120) or 120))
        else:
            broker_force_days = 0

    with st.spinner(f"正在載入 {st.session_state.stock_id} 技術與籌碼數據..."):
        fig_top, fig_btm, df_res, resolved_name, raw_end_idx, raw_disp_n = get_figures_fn(
            st.session_state.stock_id,
            st.session_state.period,
            st.session_state.disp_days,
            st.session_state.target_date_val,
            st.session_state.m1_thresh,
            st.session_state.m2_thresh,
            st.session_state.is_mobile_mode,
            current_force,
            active_refresh_cfg
        )

    if fig_top is not None and df_res is not None:
        pure_ticker = st.session_state.stock_id.strip().upper()
        if st.session_state.promote_to_top:
            save_stock_history(pure_ticker, resolved_name)
            st.session_state.promote_to_top = False
        elif resolved_name and resolved_name != pure_ticker:
            update_stock_name_only(pure_ticker, resolved_name)

        chart_id = f"mchart_{abs(hash((pure_ticker, str(st.session_state.target_date_val), st.session_state.disp_days, st.session_state.period, st.session_state.m1_thresh, st.session_state.m2_thresh, st.session_state.is_mobile_mode)))}"

        safe_end_idx = len(df_res) - 1
        if st.session_state.target_date_val is not None:
            try:
                t_str = st.session_state.target_date_val.strftime("%Y-%m-%d")
                date_strs_chk = [d.strftime("%Y-%m-%d") for d in df_res.index]
                valid_pos = [i for i, ds in enumerate(date_strs_chk) if ds <= t_str]
                if valid_pos:
                    safe_end_idx = valid_pos[-1]
            except Exception:
                pass

        actual_top_h = int(getattr(getattr(fig_top, "layout", None), "height", None) or (296 if st.session_state.is_mobile_mode else 336))

        # 上半部共用主圖
        top_html = get_top_chart_html(
            fig_top=fig_top,
            df=df_res,
            chart_id=chart_id,
            top_height=actual_top_h,
            initial_disp_days=st.session_state.disp_days,
            initial_end_idx=safe_end_idx
        )
        components.html(top_html, height=actual_top_h + 62, scrolling=False)

        # 下半部四大子頁籤（指標 / 籌碼 / 分點統計 / 分點日況）
        tab_tech, tab_chip, tab_broker_stats, tab_broker_daily = st.tabs([
            "📊 指標",
            "💰 籌碼",
            "📊 分點統計",
            "📈 分點日況"
        ])

        with tab_tech:
            tech_h = 540 if st.session_state.is_mobile_mode else 580
            tech_html = get_tech_tab_html(
                fig_btm=fig_btm,
                df=df_res,
                chart_id=chart_id,
                tech_height=tech_h,
                initial_disp_days=st.session_state.disp_days,
                initial_end_idx=safe_end_idx
            )
            # 【修訂說明 2026-11-27】調高 iframe 預留高度至 tech_h + 175，避免手機折行裁切底部資訊條
            components.html(tech_html, height=tech_h + 175, scrolling=False)

        with tab_chip:
            chip_h = 760 if st.session_state.is_mobile_mode else 800
            chip_html = get_chip_tab_html(
                fig_btm=fig_btm,
                df=df_res,
                chart_id=chart_id,
                chip_height=chip_h,
                initial_disp_days=st.session_state.disp_days,
                initial_end_idx=safe_end_idx,
                m1_thresh=st.session_state.m1_thresh,
                m2_thresh=st.session_state.m2_thresh
            )
            # 【修訂說明 2026-11-27】調高 iframe 預留高度至 chip_h + 235，確保手機折行後兩列資訊條完整呈現不被截斷
            components.html(chip_html, height=chip_h + 235, scrolling=False)

        is_gov_idx = is_tw_index_with_gov_brokers(pure_ticker)
        has_broker_support = (is_tw_stock_or_etf(pure_ticker) and not pure_ticker.startswith("^")) or is_gov_idx
        trade_dates_tuple = tuple(d.strftime("%Y-%m-%d") for d in df_res.index)
        end_date_label = trade_dates_tuple[safe_end_idx] if trade_dates_tuple else ""
        req_key = f"{pure_ticker}_{end_date_label}"
        include_60d = req_key in st.session_state.broker_60d_requests

        if has_broker_support:
            if not is_gov_idx:
                if not include_60d:
                    if st.button(f"📥 載入近 60 日分點統計與明細（基準日 {end_date_label}）", key=f"btn_load_60d_{chart_id}", use_container_width=True):
                        st.session_state.broker_60d_requests.add(req_key)
                        st.rerun()
                else:
                    st.caption(f"✅ 已載入近 1 / 10 / 20 / 60 日分點統計與逐日明細（基準日 {end_date_label}）")

            spinner_txt = (
                "正在載入加權/櫃買八大官股買賣超統計與日況..."
                if is_gov_idx else
                "正在載入雲端與最新券商分點統計與逐日進出序列..."
            )
            with st.spinner(spinner_txt):
                if not is_gov_idx and end_date_label:
                    did_backfill_daily = ensure_focus_date_broker_daily_series(
                        pure_code=pure_ticker,
                        focus_date_str=end_date_label,
                        trade_dates_list=list(trade_dates_tuple),
                        include_60d=include_60d,
                    )
                    if did_backfill_daily:
                        get_cached_broker_payload.clear()

                broker_payload = get_cached_broker_payload(
                    stock_id=pure_ticker,
                    trade_dates_tuple=trade_dates_tuple,
                    target_end_idx=safe_end_idx,
                    force_refresh=current_force,
                    include_60d=include_60d,
                    broker_force_days=broker_force_days,
                    broker_base_date=broker_base_date
                )
        else:
            broker_payload = {"by_date": {}}

        with tab_broker_stats:
            broker_stats_html = get_broker_stats_tab_html(
                df=df_res,
                chart_id=chart_id,
                broker_payload=broker_payload,
                initial_end_idx=safe_end_idx,
                is_index=(not has_broker_support),
                is_gov_index=is_gov_idx,
                pure_code=pure_ticker
            )
            components.html(broker_stats_html, height=580, scrolling=True)

        with tab_broker_daily:
            broker_daily_html = get_broker_daily_tab_html(
                df=df_res,
                chart_id=chart_id,
                broker_payload=broker_payload,
                initial_end_idx=safe_end_idx,
                is_index=(not has_broker_support),
                is_gov_index=is_gov_idx,
                pure_code=pure_ticker
            )
            components.html(broker_daily_html, height=1320, scrolling=True)

        # 底部：「目前關注目標」提示列 ＋「◀ 上一檔」＋「純下拉點選（代號 名稱）」＋「下一檔 ▶」＋ 空白緩衝區避開 [Manage app]
        st.markdown("---")
        latest_hist_list = load_stock_history()
        latest_hist_codes = [str(item.get("code")).strip().upper() for item in latest_hist_list if item.get("code")]
        btm_options = format_options_fn(latest_hist_list)
        btm_name_res = resolved_name if (resolved_name and resolved_name != pure_ticker) else get_stock_chinese_name(pure_ticker)
        btm_cur_label = next(
            (opt for opt in btm_options if opt.split()[0] == pure_ticker),
            f"{pure_ticker} {btm_name_res}".strip() if (btm_name_res and btm_name_res != pure_ticker) else pure_ticker
        )
        if btm_cur_label not in btm_options:
            btm_options = [btm_cur_label] + btm_options
        btm_sel_idx = btm_options.index(btm_cur_label)

        focus_mkt = "指數" if pure_ticker.startswith("^") else "上市"
        try:
            raw_title_txt = str(getattr(getattr(getattr(fig_top, "layout", None), "title", None), "text", "") or "")
            mkt_matches = re.findall(r'\((上市|上櫃|指數|海外)\)', raw_title_txt)
            if mkt_matches:
                focus_mkt = mkt_matches[-1]
        except Exception:
            pass
        focus_name_display = btm_name_res if (btm_name_res and btm_name_res != pure_ticker) else pure_ticker

        st.markdown(
            f"<div style='font-size:13.5px; font-weight:700; color:#1e3a8a; margin-bottom:6px;'>"
            f"目前關注目標：{focus_name_display} {pure_ticker} ({focus_mkt})</div>",
            unsafe_allow_html=True
        )

        with st.container():
            st.markdown("<div class='stock-nav-anchor'></div>", unsafe_allow_html=True)
            btm_prev, btm_sel, btm_next = st.columns([1, 6, 1])
            with btm_prev:
                if st.button("◀ 上一檔", key="btn_btm_prev", use_container_width=True):
                    if latest_hist_codes:
                        idx = latest_hist_codes.index(pure_ticker) if pure_ticker in latest_hist_codes else 0
                        prev_code = latest_hist_codes[(idx - 1) % len(latest_hist_codes)]
                        st.session_state.stock_id = prev_code
                        st.session_state.promote_to_top = False
                        st.session_state.confirm_clear_all = False
                        st.rerun()
            with btm_sel:
                st.selectbox(
                    "關注標的",
                    options=btm_options,
                    index=btm_sel_idx,
                    key="bottom_stock_selector",
                    on_change=on_bottom_selector_change_fn,
                    label_visibility="collapsed"
                )
            with btm_next:
                if st.button("下一檔 ▶", key="btn_btm_next", use_container_width=True):
                    if latest_hist_codes:
                        idx = latest_hist_codes.index(pure_ticker) if pure_ticker in latest_hist_codes else 0
                        next_code = latest_hist_codes[(idx + 1) % len(latest_hist_codes)]
                        st.session_state.stock_id = next_code
                        st.session_state.promote_to_top = False
                        st.session_state.confirm_clear_all = False
                        st.rerun()

        st.markdown("<div style='height: 54px;'></div>", unsafe_allow_html=True)
    else:
        st.error(f"無法取得 {st.session_state.stock_id} 的資料，請確認輸入的代號是否正確。")
## EOF app_stock_view.py
