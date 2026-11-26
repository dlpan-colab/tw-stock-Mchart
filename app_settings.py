"""
app_settings.py - 主頁籤 3「⚙️ 參數設定」介面渲染模組
(依邏輯職責將次頁籤 3「全市場批次維護」拆出至 app_market_batch_maint.py，本主入口維持三項次頁籤架構)
版本: 202611262015
"""

from datetime import datetime
import streamlit as st
from storage import get_stock_chinese_name
from data_fetcher import get_default_broker_backfill_base_date
from app_broker_cache import get_cached_broker_payload
from app_market_batch_maint import render_market_batch_maint_tab

MODULE_NAME = "app_settings"
MODULE_VERSION = "202611262015"


def render_settings_tab(
    system_version: str,
    clear_figures_cache_fn,
):
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：將次頁籤 3「全市場批次維護」拆出至 `app_market_batch_maint.py`，降低單檔行數並維持職責單一。
    2. 防呆防錯原因：完整保留次頁籤 1「顯示參數」與次頁籤 2「個股資料維護」（含資料維護基準日與 7 項各自獨立勾選/期程），
       確保所有 `session_state` 鍵名與操作行為 100% 不變。
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

        default_single_date = get_default_broker_backfill_base_date()
        if isinstance(default_single_date, str):
            parsed_single_date = datetime.strptime(default_single_date[:10], "%Y-%m-%d").date()
        elif hasattr(default_single_date, "date"):
            parsed_single_date = default_single_date.date()
        else:
            parsed_single_date = default_single_date

        cfg = st.session_state.get("force_refresh_cfg")
        if not isinstance(cfg, dict):
            cfg = {
                "base_date": parsed_single_date.strftime("%Y-%m-%d"),
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

        saved_b_date = cfg.get("base_date")
        if saved_b_date:
            try:
                init_single_dt = datetime.strptime(str(saved_b_date)[:10], "%Y-%m-%d").date()
            except Exception:
                init_single_dt = parsed_single_date
        else:
            init_single_dt = parsed_single_date

        single_base_dt = st.date_input(
            "資料維護基準日（預設為最近交易日）",
            value=init_single_dt,
            key="single_maint_base_date_input"
        )
        single_base_str = single_base_dt.strftime("%Y-%m-%d")

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

        # 7. 分點（預設120日，統計與日況逐日增補）
        c_b1, c_b2 = st.columns([2, 3])
        with c_b1:
            b_en = st.checkbox("分點（統計與日況逐日增補）", value=bool(cfg.get("broker_enabled", True)), key="chk_fr_broker")
        with c_b2:
            b_days = int(st.number_input(
                "分點期程(交易日)",
                min_value=1,
                max_value=365,
                value=int(cfg.get("broker_days", 120) or 120),
                step=10,
                key="num_fr_broker_days",
                label_visibility="collapsed"
            ))

        updated_cfg = {
            "base_date": single_base_str,
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
                st.success(f"已套用基準日 {single_base_str} 與勾選期程，切換回「📈 個股」頁籤即會依設定重新抓取資料。")

    # =========================================================================
    # 次頁籤 3：全市場批次維護（委派至 app_market_batch_maint.py）
    # =========================================================================
    with tab_market_maint:
        render_market_batch_maint_tab(clear_figures_cache_fn=clear_figures_cache_fn)
## EOF app_settings.py
