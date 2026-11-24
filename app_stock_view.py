"""
app_stock_view.py - 主頁籤 2「📈 個股」介面渲染模組
(自 app.py 依邏輯職責拆分，維持既有上下雙複合選單、共用主圖與四大子頁籤互動機制)
版本: 202611242246
"""

import re
import streamlit as st
import streamlit.components.v1 as components
import cloud_sync

from storage import (
    load_stock_history,
    save_stock_history,
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

MODULE_NAME = "app_stock_view"
MODULE_VERSION = "202611242246"


def render_stock_tab(
    system_version: str,
    format_options_fn,
    on_top_selector_change_fn,
    on_bottom_selector_change_fn,
    get_figures_fn,
):
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

    # 頂部：「◀ 上一檔」＋「可輸入＋下拉點選（代號 名稱）」＋「下一檔 ▶」
    with st.container():
        st.markdown("<div class='stock-nav-anchor'></div>", unsafe_allow_html=True)
        col_prev, col_input, col_next = st.columns([1, 6, 1])
        with col_prev:
            if st.button("◀ 上一檔", key="btn_top_prev", use_container_width=True):
                if history_codes:
                    idx = history_codes.index(cur_code_upper) if cur_code_upper in history_codes else 0
                    prev_code = history_codes[(idx - 1) % len(history_codes)]
                    st.session_state.stock_id = prev_code
                    st.session_state.promote_to_top = False
                    st.rerun()
        with col_input:
            st.selectbox(
                "股票代號或名稱",
                options=selector_options,
                index=cur_sel_idx,
                accept_new_options=True,
                key="top_stock_selector",
                on_change=on_top_selector_change_fn,
                placeholder="輸入代號或下拉選擇標的 (如 2330, 00632R, ^TWII)",
                label_visibility="collapsed"
            )
        with col_next:
            if st.button("下一檔 ▶", key="btn_top_next", use_container_width=True):
                if history_codes:
                    idx = history_codes.index(cur_code_upper) if cur_code_upper in history_codes else 0
                    next_code = history_codes[(idx + 1) % len(history_codes)]
                    st.session_state.stock_id = next_code
                    st.session_state.promote_to_top = False
                    st.rerun()

    st.markdown(get_legend_html(), unsafe_allow_html=True)

    current_force = st.session_state.force_refresh
    if current_force:
        st.session_state.force_refresh = False

    with st.spinner(f"正在載入 {st.session_state.stock_id} 技術與籌碼數據..."):
        fig_top, fig_btm, df_res, resolved_name, raw_end_idx, raw_disp_n = get_figures_fn(
            st.session_state.stock_id,
            st.session_state.period,
            st.session_state.disp_days,
            st.session_state.target_date_val,
            st.session_state.m1_thresh,
            st.session_state.m2_thresh,
            st.session_state.is_mobile_mode,
            current_force
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
            "📊 指標", "💰 籌碼", "📊 分點統計", "📈 分點日況"
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
            components.html(tech_html, height=tech_h + 72, scrolling=False)

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
            components.html(chip_html, height=chip_h + 85, scrolling=False)

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
                broker_payload = get_cached_broker_payload(
                    stock_id=pure_ticker,
                    trade_dates_tuple=trade_dates_tuple,
                    target_end_idx=safe_end_idx,
                    force_refresh=current_force,
                    include_60d=include_60d
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

        # 底部：「目前關注目標」提示列 ＋「◀ 上一檔」＋「可輸入＋下拉點選（代號 名稱）」＋「下一檔 ▶」＋ 空白緩衝區避開 [Manage app]
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
                        st.rerun()
            with btm_sel:
                st.selectbox(
                    "關注標的",
                    options=btm_options,
                    index=btm_sel_idx,
                    accept_new_options=True,
                    key="bottom_stock_selector",
                    on_change=on_bottom_selector_change_fn,
                    placeholder="輸入代號或下拉選擇標的 (如 2330, 00632R, ^TWII)",
                    label_visibility="collapsed"
                )
            with btm_next:
                if st.button("下一檔 ▶", key="btn_btm_next", use_container_width=True):
                    if latest_hist_codes:
                        idx = latest_hist_codes.index(pure_ticker) if pure_ticker in latest_hist_codes else 0
                        next_code = latest_hist_codes[(idx + 1) % len(latest_hist_codes)]
                        st.session_state.stock_id = next_code
                        st.session_state.promote_to_top = False
                        st.rerun()

        st.markdown("<div style='height: 54px;'></div>", unsafe_allow_html=True)
    else:
        st.error(f"無法取得 {st.session_state.stock_id} 的資料，請檢查代號是否正確或稍後再試。")
## EOF app_stock_view.py
