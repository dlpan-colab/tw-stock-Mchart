"""
app_market_batch_maint.py - 主頁籤 3「⚙️ 參數設定 → 全市場批次維護」次頁籤渲染模組
(自 app_settings.py 依邏輯職責拆分，維持既有全市籌碼維護、加權/櫃買八大官股維護與全市場分點三鍵並列維護及二次確認機制)
版本: 202611262010
"""

from datetime import datetime
import streamlit as st
from storage import (
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

MODULE_NAME = "app_market_batch_maint"
MODULE_VERSION = "202611262010"


def render_market_batch_maint_tab(clear_figures_cache_fn):
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：自 `app_settings.py` 拆出次頁籤 3「全市場批次維護」獨立模組，降低單檔行數並維持職責單一。
    2. 防呆防錯原因：完整保留所有按鈕 `key`、`session_state` 確認旗標名稱、三鍵並列錨點與清除／增補邏輯，確保功能與操作體驗 100% 一致。
    """
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
## EOF app_market_batch_maint.py
