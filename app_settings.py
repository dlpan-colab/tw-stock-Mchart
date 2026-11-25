"""
app_settings.py - 主頁籤 3「⚙️ 參數設定」介面渲染模組
(自 app.py 依邏輯職責拆分，維持既有全市籌碼維護、八大官股維護與全市場分點三鍵並列維護機制，並劃分三項次頁籤)
版本: 202611252305
"""

from datetime import datetime
import streamlit as st
from storage import (
    get_stock_chinese_name,
    clear_all_stocks_chip_range,
    clear_all_stocks_chip_all,
    clear_all_stocks_broker_range,
    clear_all_broker_data,
    clear_tw_index_gov_broker_range,
    clear_tw_index_gov_broker_data,
)
from data_fetcher import (
    get_default_broker_backfill_base_date,
    get_default_chip_backfill_base_date,
)
from app_broker_cache import get_cached_broker_payload

MODULE_NAME = "app_settings"
MODULE_VERSION = "202611252305"


def render_settings_tab(
    system_version: str,
    clear_figures_cache_fn,
):
    """
    【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 於次頁籤 2「個股資料維護」之「🔄 強制重新抓取最新資料」按鈕上方，新增 7 組可彈性勾選與設定期程的欄位：
         日 K 線（預設 120 日）、外資（預設 120 日）、投信（預設 120 日）、自營商（預設 120 日）、
         資券（預設 120 日）、大戶（預設 1 週，備註：最長15週）、分點（預設 120 日，備註：統計不限，日況限最近一日）。
    2. 防呆防錯原因：
       - 將使用者勾選狀態與輸入數值即時存入 `st.session_state.force_refresh_cfg`，
         若全部項目皆未勾選時顯示提示並阻擋無效點擊；未勾選項目於重抓時完全保留資料庫既有資料。
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
        "全市場批次維護"
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

        cfg = st.session_state.get("force_refresh_cfg")
        if not isinstance(cfg, dict):
            cfg = {
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

        # 1. 日 K 線
        c_k1, c_k2 = st.columns([2, 3])
        with c_k1:
            k_en = st.checkbox("日 K 線", value=bool(cfg.get("kline_enabled", True)), key="chk_fr_kline")
        with c_k2:
            k_days = int(st.number_input(
                "日 K 線期程(交易日)",
                min_value=1,
                max_value=1200,
                value=int(cfg.get("kline_days", 120) or 120),
                step=10,
                key="num_fr_kline_days",
                label_visibility="collapsed"
            ))

        # 2. 外資
        c_f1, c_f2 = st.columns([2, 3])
        with c_f1:
            f_en = st.checkbox("外資", value=bool(cfg.get("foreign_enabled", True)), key="chk_fr_foreign")
        with c_f2:
            f_days = int(st.number_input(
                "外資期程(交易日)",
                min_value=1,
                max_value=365,
                value=int(cfg.get("foreign_days", 120) or 120),
                step=10,
                key="num_fr_foreign_days",
                label_visibility="collapsed"
            ))

        # 3. 投信
        c_t1, c_t2 = st.columns([2, 3])
        with c_t1:
            t_en = st.checkbox("投信", value=bool(cfg.get("trust_enabled", True)), key="chk_fr_trust")
        with c_t2:
            t_days = int(st.number_input(
                "投信期程(交易日)",
                min_value=1,
                max_value=365,
                value=int(cfg.get("trust_days", 120) or 120),
                step=10,
                key="num_fr_trust_days",
                label_visibility="collapsed"
            ))

        # 4. 自營商
        c_d1, c_d2 = st.columns([2, 3])
        with c_d1:
            d_en = st.checkbox("自營商", value=bool(cfg.get("dealer_enabled", True)), key="chk_fr_dealer")
        with c_d2:
            d_days = int(st.number_input(
                "自營商期程(交易日)",
                min_value=1,
                max_value=365,
                value=int(cfg.get("dealer_days", 120) or 120),
                step=10,
                key="num_fr_dealer_days",
                label_visibility="collapsed"
            ))

        # 5. 資券
        c_m1, c_m2 = st.columns([2, 3])
        with c_m1:
            m_en = st.checkbox("資券", value=bool(cfg.get("margin_enabled", True)), key="chk_fr_margin")
        with c_m2:
            m_days = int(st.number_input(
                "資券期程(交易日)",
                min_value=1,
                max_value=365,
                value=int(cfg.get("margin_days", 120) or 120),
                step=10,
                key="num_fr_margin_days",
                label_visibility="collapsed"
            ))

        # 6. 大戶（預設1週，備註最長15週）
        c_h1, c_h2 = st.columns([2, 3])
        with c_h1:
            h_en = st.checkbox("大戶（最長15週）", value=bool(cfg.get("holding_enabled", True)), key="chk_fr_holding")
        with c_h2:
            h_weeks = int(st.number_input(
                "大戶期程(週，最長15週)",
                min_value=1,
                max_value=15,
                value=min(15, max(1, int(cfg.get("holding_weeks", 1) or 1))),
                step=1,
                key="num_fr_holding_weeks",
                label_visibility="collapsed"
            ))

        # 7. 分點（預設120日，備註統計不限，日況限最近一日）
        c_b1, c_b2 = st.columns([2, 3])
        with c_b1:
            b_en = st.checkbox("分點（統計不限，日況限最近一日）", value=bool(cfg.get("broker_enabled", True)), key="chk_fr_broker")
        with c_b2:
            b_days = int(st.number_input(
                "分點統計期程(交易日)",
                min_value=1,
                max_value=365,
                value=int(cfg.get("broker_days", 120) or 120),
                step=10,
                key="num_fr_broker_days",
                label_visibility="collapsed"
            ))

        updated_cfg = {
            "kline_enabled": k_en,
            "kline_days": k_days,
            "foreign_enabled": f_en,
            "foreign_days": f_days,
            "trust_enabled": t_en,
            "trust_days": t_days,
            "dealer_enabled": d_en,
            "dealer_days": d_days,
            "margin_enabled": m_en,
            "margin_days": m_days,
            "holding_enabled": h_en,
            "holding_weeks": h_weeks,
            "broker_enabled": b_en,
            "broker_days": b_days,
        }
        st.session_state.force_refresh_cfg = updated_cfg

        if st.button("🔄 強制重新抓取最新資料", use_container_width=True):
            if not any([k_en, f_en, t_en, d_en, m_en, h_en, b_en]):
                st.warning("⚠️ 請至少勾選一項要重新抓取的資料類別。")
            else:
                st.session_state.force_refresh = True
                clear_figures_cache_fn()
                get_cached_broker_payload.clear()
                from app_dashboard import get_cached_dashboard_rows
                get_cached_dashboard_rows.clear()
                st.success("已套用勾選項目與期程，切換回「📈 個股」頁籤即會依設定重新抓取最新資料。")

    # =========================================================================
    # 次頁籤 3：全市場批次維護
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

        # 1. 資券籌碼維護（三鍵並列）
        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>資券籌碼維護</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_ms_add, col_ms_rng_clr, col_ms_all_clr = st.columns(3)
            with col_ms_add:
                run_ms_sync = st.button("📥 批次增補歷史資券籌碼", key="btn_batch_sync_margin", use_container_width=True)
            with col_ms_rng_clr:
                if st.button("🧹 清除指定期間資券", key="btn_batch_clear_margin_range", use_container_width=True):
                    st.session_state.confirm_clear_chip_range_type = "margin"
                    st.session_state.confirm_clear_chip_all_type = ""
                    st.rerun()
            with col_ms_all_clr:
                if st.button("🗑️ 清除所有資券資料", key="btn_batch_clear_margin_all", use_container_width=True):
                    st.session_state.confirm_clear_chip_all_type = "margin"
                    st.session_state.confirm_clear_chip_range_type = ""
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

        # 2. 法人籌碼維護（三鍵並列）
        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>法人籌碼維護</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_in_add, col_in_rng_clr, col_in_all_clr = st.columns(3)
            with col_in_add:
                run_in_sync = st.button("📥 批次增補歷史法人籌碼", key="btn_batch_sync_inst", use_container_width=True)
            with col_in_rng_clr:
                if st.button("🧹 清除指定期間法人", key="btn_batch_clear_inst_range", use_container_width=True):
                    st.session_state.confirm_clear_chip_range_type = "institutional"
                    st.session_state.confirm_clear_chip_all_type = ""
                    st.rerun()
            with col_in_all_clr:
                if st.button("🗑️ 清除所有法人資料", key="btn_batch_clear_inst_all", use_container_width=True):
                    st.session_state.confirm_clear_chip_all_type = "institutional"
                    st.session_state.confirm_clear_chip_range_type = ""
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

        # 3. 大戶籌碼維護（三鍵並列）
        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>大戶籌碼維護（最多15週）</div>",
            unsafe_allow_html=True
        )
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_hd_add, col_hd_rng_clr, col_hd_all_clr = st.columns(3)
            with col_hd_add:
                run_hd_sync = st.button("📥 批次增補歷史大戶籌碼", key="btn_batch_sync_hold", use_container_width=True)
            with col_hd_rng_clr:
                if st.button("🧹 清除指定期間大戶", key="btn_batch_clear_hold_range", use_container_width=True):
                    st.session_state.confirm_clear_chip_range_type = "holding"
                    st.session_state.confirm_clear_chip_all_type = ""
                    st.rerun()
            with col_hd_all_clr:
                if st.button("🗑️ 清除所有大戶資料", key="btn_batch_clear_hold_all", use_container_width=True):
                    st.session_state.confirm_clear_chip_all_type = "holding"
                    st.session_state.confirm_clear_chip_range_type = ""
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

        # 籌碼指定期間清除二次確認
        pending_chip_rng_clr = st.session_state.get("confirm_clear_chip_range_type", "")
        if pending_chip_rng_clr in ("margin", "institutional", "holding"):
            chip_rng_label_map = {
                "margin": "資券籌碼資料",
                "institutional": "法人籌碼資料",
                "holding": "大戶籌碼資料",
            }
            cur_rng_lbl = chip_rng_label_map[pending_chip_rng_clr]
            st.warning(
                f"⚠️ 確定要清除所有上市／上櫃個股於籌碼增補基準日 **{chip_base_str}** 往前 **{chip_days_opt}** 個交易日區間內之「**{cur_rng_lbl}**」嗎？（區間外更早歷史資料與其他資料表將完整保留）"
            )
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cc_yes, cc_no = st.columns(2)
                with cc_yes:
                    if st.button(f"確定清除指定期間{cur_rng_lbl}", key="btn_confirm_clear_chip_rng_yes", use_container_width=True):
                        with st.spinner(f"正在清除基準日 {chip_base_str} 往前 {chip_days_opt} 日之{cur_rng_lbl}..."):
                            res_chip_msg = clear_all_stocks_chip_range(
                                chip_type=pending_chip_rng_clr,
                                base_date_str=chip_base_str,
                                lookback_days=int(chip_days_opt)
                            )
                        st.session_state.confirm_clear_chip_range_type = ""
                        clear_figures_cache_fn()
                        st.success(res_chip_msg)
                with cc_no:
                    if st.button("取消清除", key="btn_confirm_clear_chip_rng_no", use_container_width=True):
                        st.session_state.confirm_clear_chip_range_type = ""
                        st.rerun()

        # 籌碼全部清除二次確認
        pending_chip_all_clr = st.session_state.get("confirm_clear_chip_all_type", "")
        if pending_chip_all_clr in ("margin", "institutional", "holding"):
            chip_all_label_map = {
                "margin": "所有資券資料",
                "institutional": "所有法人資料",
                "holding": "所有大戶資料",
            }
            cur_all_lbl = chip_all_label_map[pending_chip_all_clr]
            st.warning(
                f"⚠️ 確定要清除本地與雲端所有上市／上櫃個股之「**{cur_all_lbl}**」嗎？（日線、分點及其他籌碼資料將完整保留）"
            )
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                ca_yes, ca_no = st.columns(2)
                with ca_yes:
                    if st.button(f"確定清除{cur_all_lbl}", key="btn_confirm_clear_chip_all_yes", use_container_width=True):
                        with st.spinner(f"正在清除本地與雲端之{cur_all_lbl}..."):
                            res_all_chip_msg = clear_all_stocks_chip_all(chip_type=pending_chip_all_clr)
                        st.session_state.confirm_clear_chip_all_type = ""
                        clear_figures_cache_fn()
                        st.success(res_all_chip_msg)
                with ca_no:
                    if st.button("取消清除", key="btn_confirm_clear_chip_all_no", use_container_width=True):
                        st.session_state.confirm_clear_chip_all_type = ""
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
        gov_d_str = gov_base_dt.strftime("%Y-%m-%d")

        # 4. 加權指數／櫃買指數八大官股維護（三鍵並列）
        with st.container():
            st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
            col_gov_add, col_gov_rng_clr, col_gov_all_clr = st.columns(3)
            with col_gov_add:
                run_gov_sync = st.button("📥 批次增補八大官股交易前30個股", key="btn_batch_sync_gov_brokers", use_container_width=True)
            with col_gov_rng_clr:
                if st.button("🧹 清除指定期間八大官股", key="btn_batch_clear_gov_brokers_range", use_container_width=True):
                    st.session_state.confirm_clear_gov_brokers_range = True
                    st.session_state.confirm_clear_gov_brokers = False
                    st.rerun()
            with col_gov_all_clr:
                if st.button("🗑️ 清除所有八大官股資料", key="btn_batch_clear_gov_brokers", use_container_width=True):
                    st.session_state.confirm_clear_gov_brokers = True
                    st.session_state.confirm_clear_gov_brokers_range = False
                    st.rerun()

        if run_gov_sync:
            from data_fetcher import batch_sync_tw_index_gov_brokers
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

        if st.session_state.get("confirm_clear_gov_brokers_range", False):
            st.warning(
                f"⚠️ 確定要清除加權指數（^TWII）與櫃買指數（^TWOII）於八大官股增補基準日 **{gov_d_str}** 往前 **{gov_days_opt}** 個交易日區間內之「**八大官股交易資料**」嗎？（區間外歷史八大官股、指數日線與資券資料將完整保留）"
            )
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cgr_yes, cgr_no = st.columns(2)
                with cgr_yes:
                    if st.button("確定清除指定期間八大官股", key="btn_confirm_clear_gov_rng_yes", use_container_width=True):
                        with st.spinner(f"正在清除基準日 {gov_d_str} 往前 {gov_days_opt} 日之八大官股資料..."):
                            res_gov_rng_msg = clear_tw_index_gov_broker_range(
                                base_date_str=gov_d_str,
                                lookback_days=int(gov_days_opt)
                            )
                        st.session_state.confirm_clear_gov_brokers_range = False
                        get_cached_broker_payload.clear()
                        st.success(res_gov_rng_msg)
                with cgr_no:
                    if st.button("取消清除", key="btn_confirm_clear_gov_rng_no", use_container_width=True):
                        st.session_state.confirm_clear_gov_brokers_range = False
                        st.rerun()

        if st.session_state.get("confirm_clear_gov_brokers", False):
            st.warning("⚠️ 確定要清除加權指數（^TWII）與櫃買指數（^TWOII）本地與雲端之「所有八大官股資料」嗎？（指數日線、資券及其他個股資料將完整保留）")
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                cg_yes, cg_no = st.columns(2)
                with cg_yes:
                    if st.button("確定清除所有八大官股", key="btn_confirm_clear_gov_yes", use_container_width=True):
                        with st.spinner("正在清除加權與櫃買所有八大官股資料..."):
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
            prog_bar = st.progress(0, text="準備檢查歷史紀錄與增補分點統計...")
            status_txt = st.empty()

            def _on_bk_progress(cur_i, tot_n, c_code, c_name, st_msg):
                pct = int(cur_i / max(1, tot_n) * 100)
                prog_bar.progress(min(100, pct), text=f"[{cur_i}/{tot_n}] {c_code} {c_name} - {st_msg}")
                status_txt.caption(f"目前處理：{c_code} {c_name}（基準日 {base_d_str} 往前 {backfill_days_opt} 日）")

            summary_msg = batch_sync_all_stocks_brokers(
                base_date_str=base_d_str,
                lookback_days=int(backfill_days_opt),
                progress_callback=_on_bk_progress
            )
            prog_bar.progress(100, text="批次增補完成！")
            status_txt.empty()
            get_cached_broker_payload.clear()
            st.success(summary_msg)

        if st.session_state.get("confirm_clear_brokers_range", False):
            st.warning(
                f"⚠️ 確定要清除所有上市／上櫃個股於增補基準日 **{base_d_str}** 往前 **{backfill_days_opt}** 個交易日區間內之「**分點資料（含統計排行、個股逐日明細與關注分點日況）**」嗎？（區間外更早歷史分點、日線及籌碼資料將完整保留）"
            )
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                c_rng_yes, c_rng_no = st.columns(2)
                with c_rng_yes:
                    if st.button("確定清除指定期間分點", key="btn_confirm_clear_bk_rng_yes", use_container_width=True):
                        with st.spinner(f"正在清除基準日 {base_d_str} 往前 {backfill_days_opt} 日之分點資料..."):
                            res_rng_msg = clear_all_stocks_broker_range(
                                base_date_str=base_d_str,
                                lookback_days=int(backfill_days_opt)
                            )
                        st.session_state.confirm_clear_brokers_range = False
                        get_cached_broker_payload.clear()
                        st.success(res_rng_msg)
                with c_rng_no:
                    if st.button("取消清除", key="btn_confirm_clear_bk_rng_no", use_container_width=True):
                        st.session_state.confirm_clear_brokers_range = False
                        st.rerun()

        if st.session_state.get("confirm_clear_brokers", False):
            st.warning("⚠️ 確定要清除本地與雲端所有上市／上櫃個股之「所有分點資料（含統計排行、逐日明細與關注分點日況）」嗎？（日線、法人、資券與大戶資料將完整保留）")
            with st.container():
                st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
                c_yes, c_no = st.columns(2)
                with c_yes:
                    if st.button("確定清除所有分點", key="btn_confirm_clear_bk_yes", use_container_width=True):
                        with st.spinner("正在清除本地與雲端所有分點資料..."):
                            res_clr_msg = clear_all_broker_data()
                        st.session_state.confirm_clear_brokers = False
                        get_cached_broker_payload.clear()
                        st.success(res_clr_msg)
                with c_no:
                    if st.button("取消清除", key="btn_confirm_clear_bk_no", use_container_width=True):
                        st.session_state.confirm_clear_brokers = False
                        st.rerun()
## EOF app_settings.py
