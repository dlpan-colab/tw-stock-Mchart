"""
app_settings.py - 主頁籤 3「⚙️ 參數設定」介面渲染模組
(自 app.py 依邏輯職責拆分，維持既有全市籌碼維護、八大官股維護與全市場分點三鍵並列維護機制，並劃分三項次頁籤)
版本: 202611252150
"""

from datetime import datetime
import streamlit as st

from storage import (
    get_stock_chinese_name,
    clear_all_stocks_chip_range,
    clear_all_stocks_broker_range,
    clear_all_broker_data,
    clear_tw_index_gov_broker_data,
)
from data_fetcher import (
    get_default_broker_backfill_base_date,
    get_default_chip_backfill_base_date,
)
from app_broker_cache import get_cached_broker_payload

MODULE_NAME = "app_settings"
MODULE_VERSION = "202611252150"


def render_settings_tab(
    system_version: str,
    clear_figures_cache_fn,
):
    """
    【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 於「手機版緊湊模式」開關下方建立三個次頁籤：`st.tabs(["顯示參數", "個股資料維護", "全市場個股資料維護"])`。
       - 次頁籤 1「顯示參數」：包含 K線歷史抓取範圍、初始顯示K線根數、指定基準日、大戶持股門檻設定。
       - 次頁籤 2「個股資料維護」：包含當前關注個股標示與「🔄 強制重新抓取最新資料」功能。
       - 次頁籤 3「全市場個股資料維護」：完整包含全市(含上櫃)籌碼資料庫維護、加權指數／櫃買指數八大官股維護、
         全市場（含上櫃）分點批次增補與維護三個既有區塊。
    2. 防呆防錯原因：
       - 僅調整 UI 容器階層歸屬，所有變數鍵值（widget keys）、session_state 狀態與資料庫維護函式呼叫均完整保留未更動。
    """
    st.markdown(
        f"<div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:6px;'>"
        f"⚙️ 參數設定與資料庫維護 <span style='font-size:12px; color:#64748b; font-weight:600;'>v{system_version}</span></div>",
        unsafe_allow_html=True
    )

    st.session_state.is_mobile_mode = st.toggle(
        "手機版緊湊模式 (自動最佳化字體與高度)",
        value=st.session_state.is_mobile_mode
    )

    tab_disp_params, tab_single_maint, tab_market_maint = st.tabs([
        "顯示參數",
        "個股資料維護",
        "全市場個股資料維護"
    ])

    # =========================================================================
    # 次頁籤 1：顯示參數
    # =========================================================================
    with tab_disp_params:
        period_options = {"1年": "1y", "2年": "2y", "3年": "3y", "5年": "5y", "6個月": "6mo", "3個月": "3mo"}
        current_period_label = [k for k, v in period_options.items() if v == st.session_state.period][0]
        sel_period_label = st.selectbox(
            "K線歷史抓取範圍",
            list(period_options.keys()),
            index=list(period_options.keys()).index(current_period_label)
        )
        st.session_state.period = period_options[sel_period_label]

        st.session_state.disp_days = int(st.number_input(
            "初始顯示K線根數",
            min_value=5,
            max_value=240,
            value=int(st.session_state.disp_days),
            step=5,
            key="disp_days_num_input"
        ))

        st.markdown("---")
        st.session_state.use_target_date = st.checkbox("指定基準日", value=st.session_state.use_target_date)
        if st.session_state.use_target_date:
            default_dt = st.session_state.target_date_val if st.session_state.target_date_val else datetime.now().date()
            st.session_state.target_date_val = st.date_input("基準日期", value=default_dt)
        else:
            st.session_state.target_date_val = None

        st.markdown("---")
        st.markdown("**大戶持股門檻設定**")
        major_options = [100, 200, 400, 600, 800, 1000]
        st.session_state.m1_thresh = st.selectbox(
            "大戶線 1 (預設1000張)",
            major_options,
            index=major_options.index(st.session_state.m1_thresh)
        )
        st.session_state.m2_thresh = st.selectbox(
            "大戶線 2 (預設400張)",
            major_options,
            index=major_options.index(st.session_state.m2_thresh)
        )

    # =========================================================================
    # 次頁籤 2：個股資料維護
    # =========================================================================
    with tab_single_maint:
        cur_code_disp = str(st.session_state.get("stock_id", "2330")).strip().upper()
        cur_name_disp = get_stock_chinese_name(cur_code_disp)
        target_label = f"{cur_code_disp} {cur_name_disp}".strip() if (cur_name_disp and cur_name_disp != cur_code_disp) else cur_code_disp
        st.markdown(
            f"<div style='font-size:13.5px; font-weight:700; color:#1e3a8a; margin-bottom:8px;'>"
            f"目前個股頁籤選定標的：{target_label}</div>",
            unsafe_allow_html=True
        )
        if st.button("🔄 強制重新抓取最新資料", use_container_width=True):
            st.session_state.force_refresh = True
            clear_figures_cache_fn()
            get_cached_broker_payload.clear()
            from app_dashboard import get_cached_dashboard_rows
            get_cached_dashboard_rows.clear()
            st.success("快取已清除，切換回「📈 個股」頁籤即會重新抓取最新資料。")

    # =========================================================================
    # 次頁籤 3：全市場個股資料維護
    # =========================================================================
    with tab_market_maint:
        st.markdown("**全市(含上櫃)籌碼資料庫維護**")
        default_chip_date = get_default_chip_backfill_base_date()
        if isinstance(default_chip_date, str):
            parsed_chip_date = datetime.strptime(default_chip_date[:10], "%Y-%m-%d").date()
        elif hasattr(default_chip_date, "date"):
            parsed_chip_date = default_chip_date.date()
        else:
            parsed_chip_date = default_chip_date

        chip_base_dt = st.date_input(
            "籌碼增補基準日（預設16:30前為前一交易日）",
            value=parsed_chip_date,
            key="chip_backfill_base_date_input"
        )
        chip_days_opt = int(st.number_input(
            "往前增補交易籌碼日數",
            min_value=1,
            max_value=365,
            value=1,
            step=1,
            key="chip_backfill_days_input"
        ))
        chip_base_str = chip_base_dt.strftime("%Y-%m-%d")

        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>資券籌碼維護</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_ms_add, col_ms_clr = st.columns(2)
            with col_ms_add:
                run_ms_sync = st.button("📥 批次增補歷史資券籌碼", key="btn_batch_sync_margin", use_container_width=True)
            with col_ms_clr:
                if st.button("🗑️ 清除資券籌碼資料", key="btn_batch_clear_margin", use_container_width=True):
                    st.session_state.confirm_clear_chip_type = "margin"
                    st.rerun()

        if run_ms_sync:
            from data_fetcher import batch_sync_all_stocks_margin
            prog_bar = st.progress(0, text="準備檢查歷史紀錄與增補資券籌碼...")
            status_txt = st.empty()

            def _on_margin_progress(cur_i, tot_n, c_code, c_name, st_msg):
                pct = int(cur_i / max(1, tot_n) * 100)
                prog_bar.progress(min(100, pct), text=f"[{cur_i}/{tot_n}] {c_code} {c_name} - {st_msg}")
                status_txt.caption(f"目前處理：{c_code} {c_name}（基準日 {chip_base_str} 往前 {chip_days_opt} 日）")

            summary_ms = batch_sync_all_stocks_margin(
                base_date_str=chip_base_str,
                lookback_days=int(chip_days_opt),
                progress_callback=_on_margin_progress
            )
            prog_bar.progress(100, text="批次資券籌碼增補完成！")
            status_txt.empty()
            clear_figures_cache_fn()
            st.success(summary_ms)

        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>法人籌碼維護</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_in_add, col_in_clr = st.columns(2)
            with col_in_add:
                run_in_sync = st.button("📥 批次增補歷史法人籌碼", key="btn_batch_sync_inst", use_container_width=True)
            with col_in_clr:
                if st.button("🗑️ 清除法人籌碼資料", key="btn_batch_clear_inst", use_container_width=True):
                    st.session_state.confirm_clear_chip_type = "institutional"
                    st.rerun()

        if run_in_sync:
            from data_fetcher import batch_sync_all_stocks_institutional
            prog_bar = st.progress(0, text="準備檢查歷史紀錄與增補法人籌碼...")
            status_txt = st.empty()

            def _on_inst_progress(cur_i, tot_n, c_code, c_name, st_msg):
                pct = int(cur_i / max(1, tot_n) * 100)
                prog_bar.progress(min(100, pct), text=f"[{cur_i}/{tot_n}] {c_code} {c_name} - {st_msg}")
                status_txt.caption(f"目前處理：{c_code} {c_name}（基準日 {chip_base_str} 往前 {chip_days_opt} 日）")

            summary_inst = batch_sync_all_stocks_institutional(
                base_date_str=chip_base_str,
                lookback_days=int(chip_days_opt),
                progress_callback=_on_inst_progress
            )
            prog_bar.progress(100, text="批次法人籌碼增補完成！")
            status_txt.empty()
            clear_figures_cache_fn()
            st.success(summary_inst)

        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>大戶籌碼維護（最多15週）</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_hd_add, col_hd_clr = st.columns(2)
            with col_hd_add:
                run_hd_sync = st.button("📥 批次增補歷史大戶籌碼", key="btn_batch_sync_hold", use_container_width=True)
            with col_hd_clr:
                if st.button("🗑️ 清除大戶籌碼資料", key="btn_batch_clear_hold", use_container_width=True):
                    st.session_state.confirm_clear_chip_type = "holding"
                    st.rerun()

        if run_hd_sync:
            from data_fetcher import batch_sync_all_stocks_holding
            prog_bar = st.progress(0, text="準備檢查歷史紀錄與增補大戶籌碼...")
            status_txt = st.empty()

            def _on_hold_progress(cur_i, tot_n, c_code, c_name, st_msg):
                pct = int(cur_i / max(1, tot_n) * 100)
                prog_bar.progress(min(100, pct), text=f"[{cur_i}/{tot_n}] {c_code} {c_name} - {st_msg}")
                status_txt.caption(f"目前處理：{c_code} {c_name}（基準日 {chip_base_str} 往前 {chip_days_opt} 日）")

            summary_hold = batch_sync_all_stocks_holding(
                base_date_str=chip_base_str,
                lookback_days=int(chip_days_opt),
                progress_callback=_on_hold_progress
            )
            prog_bar.progress(100, text="批次大戶籌碼增補完成！")
            status_txt.empty()
            clear_figures_cache_fn()
            st.success(summary_hold)

        pending_chip_clr = st.session_state.get("confirm_clear_chip_type", "")
        if pending_chip_clr in ("margin", "institutional", "holding"):
            chip_label_map = {
                "margin": "資券籌碼資料",
                "institutional": "法人籌碼資料",
                "holding": "大戶籌碼資料",
            }
            cur_lbl = chip_label_map[pending_chip_clr]
            st.warning(
                f"⚠️ 確定要清除所有上市／上櫃個股於基準日 **{chip_base_str}** 往前 **{chip_days_opt}** 個交易日區間內之「**{cur_lbl}**」嗎？（區間外更早歷史資料與其他資料表將完整保留）"
            )
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cc_yes, cc_no = st.columns(2)
                with cc_yes:
                    if st.button(f"確定清除{cur_lbl}", key="btn_confirm_clear_chip_yes", use_container_width=True):
                        with st.spinner(f"正在清除基準日 {chip_base_str} 往前 {chip_days_opt} 日之{cur_lbl}..."):
                            res_chip_msg = clear_all_stocks_chip_range(
                                chip_type=pending_chip_clr,
                                base_date_str=chip_base_str,
                                lookback_days=int(chip_days_opt)
                            )
                        st.session_state.confirm_clear_chip_type = ""
                        clear_figures_cache_fn()
                        st.success(res_chip_msg)
                with cc_no:
                    if st.button("取消清除", key="btn_confirm_clear_chip_no", use_container_width=True):
                        st.session_state.confirm_clear_chip_type = ""
                        st.rerun()

        st.markdown("---")
        st.markdown("**加權指數／櫃買指數八大官股維護**")
        default_gov_date = get_default_broker_backfill_base_date()
        if isinstance(default_gov_date, str):
            parsed_gov_date = datetime.strptime(default_gov_date[:10], "%Y-%m-%d").date()
        elif hasattr(default_gov_date, "date"):
            parsed_gov_date = default_gov_date.date()
        else:
            parsed_gov_date = default_gov_date

        gov_base_dt = st.date_input(
            "八大官股增補基準日（預設16:00前為前一交易日）",
            value=parsed_gov_date,
            key="gov_broker_backfill_base_date_input"
        )
        gov_days_opt = int(st.number_input(
            "往前增補交易日數（八大官股）",
            min_value=1,
            max_value=365,
            value=1,
            step=1,
            key="gov_broker_backfill_days_input"
        ))
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_gov_add, col_gov_clr = st.columns(2)
            with col_gov_add:
                run_gov_sync = st.button("📥 批次增補八大官股交易前30個股", key="btn_batch_sync_gov_brokers", use_container_width=True)
            with col_gov_clr:
                if st.button("🗑️ 清除八大官股交易資料", key="btn_batch_clear_gov_brokers", use_container_width=True):
                    st.session_state.confirm_clear_gov_brokers = True
                    st.rerun()

        if run_gov_sync:
            from data_fetcher import batch_sync_tw_index_gov_brokers
            gov_d_str = gov_base_dt.strftime("%Y-%m-%d")
            prog_bar = st.progress(0, text="準備檢查並增補加權／櫃買八大官股交易前30個股...")
            status_txt = st.empty()

            def _on_gov_progress(cur_i, tot_n, c_code, c_name, st_msg):
                pct = int(cur_i / max(1, tot_n) * 100)
                prog_bar.progress(min(100, pct), text=f"[{cur_i}/{tot_n}] {c_code} {c_name} - {st_msg}")
                status_txt.caption(f"目前處理：{c_code} {c_name}（基準日 {gov_d_str} 往前 {gov_days_opt} 日）")

            summary_gov = batch_sync_tw_index_gov_brokers(
                base_date_str=gov_d_str,
                lookback_days=int(gov_days_opt),
                progress_callback=_on_gov_progress
            )
            prog_bar.progress(100, text="八大官股交易前30個股增補完成！")
            status_txt.empty()
            get_cached_broker_payload.clear()
            st.success(summary_gov)

        if st.session_state.confirm_clear_gov_brokers:
            st.warning("⚠️ 確定要清除加權指數（^TWII）與櫃買指數（^TWOII）本地與雲端之「八大官股交易資料」嗎？（指數日線、資券及其他個股資料將完整保留）")
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cg_yes, cg_no = st.columns(2)
                with cg_yes:
                    if st.button("確定清除八大官股", key="btn_confirm_clear_gov_yes", use_container_width=True):
                        with st.spinner("正在清除加權與櫃買八大官股資料..."):
                            res_gov_msg = clear_tw_index_gov_broker_data()
                        st.session_state.confirm_clear_gov_brokers = False
                        get_cached_broker_payload.clear()
                        st.success(res_gov_msg)
                with cg_no:
                    if st.button("取消清除", key="btn_confirm_clear_gov_no", use_container_width=True):
                        st.session_state.confirm_clear_gov_brokers = False
                        st.rerun()

        st.markdown("---")
        st.markdown("**全市場（含上櫃）分點批次增補與維護(分點買賣超交易日況僅限最近交易日之近20日)**")
        default_bf_date = get_default_broker_backfill_base_date()
        if isinstance(default_bf_date, str):
            parsed_bf_date = datetime.strptime(default_bf_date[:10], "%Y-%m-%d").date()
        elif hasattr(default_bf_date, "date"):
            parsed_bf_date = default_bf_date.date()
        else:
            parsed_bf_date = default_bf_date

        backfill_base_dt = st.date_input(
            "增補基準日（預設16:00前為前一交易日）",
            value=parsed_bf_date,
            key="broker_backfill_base_date_input"
        )
        backfill_days_opt = int(st.number_input(
            "往前增補交易日數",
            min_value=1,
            max_value=365,
            value=1,
            step=1,
            key="broker_backfill_days_input"
        ))
        base_d_str = backfill_base_dt.strftime("%Y-%m-%d")

        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>增補分點(分點買賣超交易日況僅限最近交易日之近20日)</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_bk_add, col_bk_rng_clr, col_bk_clr = st.columns(3)
            with col_bk_add:
                run_bk_sync = st.button("📥 批次增補歷史分點（統計與明細）", key="btn_batch_sync_brokers", use_container_width=True)
            with col_bk_rng_clr:
                if st.button("🧹 清除指定期間分點", key="btn_batch_clear_brokers_range", use_container_width=True):
                    st.session_state.confirm_clear_brokers_range = True
                    st.session_state.confirm_clear_brokers = False
                    st.rerun()
            with col_bk_clr:
                if st.button("🗑️ 清除所有分點資料", key="btn_batch_clear_brokers", use_container_width=True):
                    st.session_state.confirm_clear_brokers = True
                    st.session_state.confirm_clear_brokers_range = False
                    st.rerun()

        if run_bk_sync:
            from data_fetcher import batch_sync_all_stocks_brokers
            prog_bar = st.progress(0, text="準備檢查歷史紀錄與增補分點資料...")
            status_txt = st.empty()

            def _on_bf_progress(cur_i, tot_n, c_code, c_name, st_msg):
                pct = int(cur_i / max(1, tot_n) * 100)
                prog_bar.progress(min(100, pct), text=f"[{cur_i}/{tot_n}] {c_code} {c_name} - {st_msg}")
                status_txt.caption(f"目前處理：{c_code} {c_name}（基準日 {base_d_str} 往前 {backfill_days_opt} 日）")

            summary_msg = batch_sync_all_stocks_brokers(
                base_date_str=base_d_str,
                lookback_days=int(backfill_days_opt),
                progress_callback=_on_bf_progress
            )
            prog_bar.progress(100, text="批次增補完成！")
            status_txt.empty()
            get_cached_broker_payload.clear()
            st.success(summary_msg)

        if st.session_state.confirm_clear_brokers_range:
            st.warning(
                f"⚠️ 確定要清除所有上市／上櫃個股於增補基準日 **{base_d_str}** 往前 **{backfill_days_opt}** 個交易日區間內之「**分點統計與分點日況明細**」嗎？（區間外歷史分點、八大官股及日線/法人/資券/大戶資料將完整保留）"
            )
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cbr_yes, cbr_no = st.columns(2)
                with cbr_yes:
                    if st.button("確定清除指定期間分點", key="btn_confirm_clear_brokers_range_yes", use_container_width=True):
                        with st.spinner(f"正在清除基準日 {base_d_str} 往前 {backfill_days_opt} 日之分點資料..."):
                            res_rng_msg = clear_all_stocks_broker_range(
                                base_date_str=base_d_str,
                                lookback_days=int(backfill_days_opt)
                            )
                        st.session_state.confirm_clear_brokers_range = False
                        get_cached_broker_payload.clear()
                        st.success(res_rng_msg)
                with cbr_no:
                    if st.button("取消清除", key="btn_confirm_clear_brokers_range_no", use_container_width=True):
                        st.session_state.confirm_clear_brokers_range = False
                        st.rerun()

        if st.session_state.confirm_clear_brokers:
            st.warning("⚠️ 確定要清除本地與雲端所有標的（含上市/上櫃個股與加權/櫃買八大官股）之「分點統計與分點日況明細」嗎？（日線、法人、資券與集保大戶資料將完整保留）")
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cb_yes, cb_no = st.columns(2)
                with cb_yes:
                    if st.button("確定清除分點", key="btn_confirm_clear_brokers_yes", use_container_width=True):
                        with st.spinner("正在清除本地與雲端分點資料表..."):
                            res_msg = clear_all_broker_data()
                        st.session_state.confirm_clear_brokers = False
                        get_cached_broker_payload.clear()
                        st.success(res_msg)
                with cb_no:
                    if st.button("取消清除", key="btn_confirm_clear_brokers_no", use_container_width=True):
                        st.session_state.confirm_clear_brokers = False
                        st.rerun()
## EOF app_settings.py
