"""
app.py - 主應用程式介面與生命週期控制
(支援含英文後綴台股ETF + 上下檔瀏覽不亂序且不改動輸入框 + 雲端分點預設20日與60日按需載入 + 盤中基準日防呆 + 雲端失敗即時通報版)
版本: 202611172028
"""
import os
import time
import re
from datetime import datetime, timedelta
import streamlit as st
import streamlit.components.v1 as components
import cloud_sync

MODULE_NAME = "app"
MODULE_VERSION = "202611172028"


# 【防呆防錯備註 2026-11-07】：版本控制權由 app.py 作為唯一權威源，動態掃描所有模組最大版本號，杜絕多頭覆寫與重工
def get_system_version() -> str:
    versions = [MODULE_VERSION]
    module_names = [
        "frontend", "chart_builder", "indicators", "data_fetcher", "storage", "config", "cloud_sync"
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
    fetch_single_broker_daily_series
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


def _resolve_broker_end_idx(trade_dates_tuple: tuple, target_end_idx: int) -> int:
    """
    【修訂說明 2026-11-17】【修改目的與防呆防錯原因】：
    1. 修改目的：台灣時間 17:00 前（盤中及盤後分點尚未結算公告），若 K 線最後一日為今日，
       分點查詢基準日自動退回前一個已完成交易日。
    2. 防呆防錯原因：避免盤中拿未結算今日日期去爬券商網頁（既查無快取耗時40秒，又把券商回傳的昨日數據誤標今日）。
    """
    n_dates = len(trade_dates_tuple)
    if n_dates == 0:
        return 0
    safe_idx = min(max(0, int(target_end_idx)), n_dates - 1)
    now_tw = datetime.utcnow() + timedelta(hours=8)
    today_tw_str = now_tw.strftime('%Y-%m-%d')
    if trade_dates_tuple[safe_idx] == today_tw_str and now_tw.hour < 17 and safe_idx > 0:
        return safe_idx - 1
    return safe_idx


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
    """
    【修訂說明 2026-11-16】【修改目的與防呆防錯原因】：
    1. 修改目的：首次查詢預設僅抓取 1、10、20 日排行及前五大分點 20 日逐日明細（include_60d=False）；
       僅當使用者點擊「載入近 60 日分點統計與明細」（include_60d=True）時，才補抓 60 日排行與逐日明細並合併寫回雲端。
    2. 防呆防錯原因：
       - 各區間排行請求加入 0.15s 間隔與空值重試 1 次，解決第 3 次連線（20 日）偶發瞬斷空值問題。
       - 若既有快取存在殘缺（如 w20 為空）或按需請求 include_60d=True 尚無 w60，自動精準補抓並與既有快取合併寫回。
    """
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
        """從雲端 SQLite 讀取各分點已累積之全區間逐日買賣超明細並組裝柱狀圖序列"""
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


st.set_page_config(
    page_title="台股多指標+籌碼技術分析",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container {padding-top: 3.5rem; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem;}
footer {visibility: hidden;}
[data-testid="stHorizontalBlock"] {display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; justify-content: center !important; align-items: center !important; gap: 8px !important;}
[data-testid="stHorizontalBlock"] > div {flex: 0 0 65px !important; width: 65px !important; min-width: 65px !important; max-width: 65px !important;}
[data-testid="stHorizontalBlock"] button {width: 100% !important; min-width: 65px !important; padding: 2px 4px !important; font-size: 12px !important; white-space: nowrap !important;}
[data-testid="stTabs"] [role="tablist"] {display: flex !important; width: 100% !important; gap: 4px !important; background: #eef2f6 !important; padding: 3px !important; border-radius: 6px !important; border: 1px solid #cbd5e1 !important;}
[data-testid="stTabs"] [role="tab"] {flex: 1 1 0 !important; justify-content: center !important; font-weight: 700 !important; font-size: 13.5px !important; padding: 6px 8px !important; border-radius: 4px !important;}
[data-testid="stTabs"] [aria-selected="true"] {background-color: #1e293b !important; color: #ffffff !important;}
</style>
""", unsafe_allow_html=True)

initial_history = load_stock_history()
default_code = "2330"
if initial_history:
    first_code = str(initial_history[0].get("code", "")).strip().upper()
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
if "promote_to_top" not in st.session_state:
    st.session_state.promote_to_top = False
if "broker_60d_requests" not in st.session_state:
    st.session_state.broker_60d_requests = set()
if "pending_input_sync" not in st.session_state:
    st.session_state.pending_input_sync = None


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
        st.session_state.index_select_box = "選擇主要市場指數..."


def on_history_select_change():
    """
    【修訂說明 2026-11-17】【修改目的與防呆防錯原因】：
    選取歷史紀錄下拉選單標的時，同步更新 stock_input_box 與 stock_id 並置頂查詢，
    避免手機觸控未先收合下拉框即按查詢時事件被吞掉（於 callback 階段賦值安全合法）。
    """
    cur_key = f"history_selectbox_{st.session_state.ms_counter}"
    sel = st.session_state.get(cur_key, "選擇歷史紀錄...")
    if sel and sel != "選擇歷史紀錄...":
        target_code = sel.split()[0].strip().upper()
        if target_code:
            st.session_state.stock_input_box = target_code
            st.session_state.stock_id = target_code
            st.session_state.promote_to_top = True
            st.session_state.confirm_clear_all = False


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
    history_codes = [str(item.get("code")).strip().upper() for item in history_records if item.get("code")]

    with st.expander("查詢歷史紀錄", expanded=False):
        if history_codes:
            history_options = ["選擇歷史紀錄..."] + [f"{h.get('code')} {h.get('name', '')}".strip() for h in history_records]
            current_sb_key = f"history_selectbox_{st.session_state.ms_counter}"
            selected_history = st.selectbox(
                "點擊展開並選擇單一標的...",
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
                        st.session_state.pending_input_sync = next_code
                        st.session_state.promote_to_top = False
                    st.session_state.confirm_clear_all = False
                    st.session_state.ms_counter += 1
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
                    st.session_state.pending_input_sync = "2330"
                    st.session_state.promote_to_top = False
                    st.session_state.confirm_clear_all = False
                    st.session_state.ms_counter += 1
                    st.rerun()
            with c_del2:
                if st.button("取消", key="btn_cancel_delete_all", use_container_width=True):
                    st.session_state.confirm_clear_all = False
                    st.rerun()

    # 【防呆防錯備註 2026-11-17】：僅在 st.text_input 實例化前處理清除紀錄之同步賦值，避免 StreamlitWidgetAlreadyInstantiatedError
    if st.session_state.pending_input_sync is not None:
        st.session_state.stock_input_box = st.session_state.pending_input_sync
        st.session_state.pending_input_sync = None
    elif "stock_input_box" not in st.session_state:
        st.session_state.stock_input_box = st.session_state.stock_id
    st.text_input("股票代號 (直接鍵入)", key="stock_input_box", on_change=on_stock_input_change)

    st.session_state.period = st.selectbox(
        "下載區間", ["6mo", "1y", "2y", "5y", "max"], index=1
    )
    mode_switch = st.selectbox(
        "模式切換", ["手機版 (Mobile) - 預設20日", "電腦版 (Desktop) - 預設60日"], index=0
    )
    is_mobile = "手機版" in mode_switch
    default_days = 20 if is_mobile else 60
    st.session_state.disp_days = st.number_input(
        "顯示日數", min_value=10, max_value=240, value=default_days, step=5
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
        get_cached_broker_payload.clear()

    if st.button("查詢", use_container_width=True):
        input_code = st.session_state.stock_input_box.strip()
        if input_code:
            resolved = resolve_ticker_code(input_code)
            st.session_state.stock_id = resolved
            st.session_state.promote_to_top = True
        st.rerun()

    st.markdown("---")
    st.subheader("法人籌碼維護")
    refetch_inst_weeks = st.number_input("重抓法人週數", min_value=1, max_value=24, value=1, step=1)
    if st.button("🛠️ 清除並重抓近N週法人籌碼", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip().upper()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無三大法人買賣超資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_inst_weeks} 週法人籌碼..."):
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_institutional_investors
                    from storage import StockChipStorage
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

    st.markdown("---")
    st.subheader("資券維護")
    refetch_weeks = st.number_input("重抓週數", min_value=1, max_value=24, value=1, step=1)
    if st.button("🛠️ 清除並重抓近N週資券", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip().upper()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無資券資料。")
        else:
            with st.spinner(f"正在重新爬取 {cur_code} 近 {refetch_weeks} 週資券紀錄..."):
                try:
                    from data_fetcher import fetch_stock_daily_k, fetch_margin_short_data
                    from storage import StockChipStorage
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
    st.subheader("大戶持股維護[個股/Findmind]")
    st.caption("ℹ️ 集保於當週各交易日不予公告，直到當週最後交易日之次日（週六）公布。")
    refetch_holding_weeks = st.number_input("重抓集保週數", min_value=1, max_value=24, value=6, step=1)
    if st.button("🛠️ 增補近N週集保歷史", use_container_width=True):
        cur_code = str(st.session_state.stock_id).strip().upper()
        if cur_code.startswith("^"):
            st.sidebar.warning("指數標的無集保大戶資料。")
        else:
            with st.spinner(f"正在連線 FinMind 增補 {cur_code} 近 {refetch_holding_weeks} 週歷史分級..."):
                try:
                    from data_fetcher import fetch_tdcc_holding_history
                    from storage import StockChipStorage
                    fresh_holdings = fetch_tdcc_holding_history(cur_code, weeks=int(refetch_holding_weeks))
                    if fresh_holdings:
                        storage = StockChipStorage(cur_code)
                        storage.save_holding_data(fresh_holdings)
                        unique_dates = len(set(r[0] for r in fresh_holdings))
                        st.sidebar.success(f"成功增補 {unique_dates} 週（共 {len(fresh_holdings)} 筆分級）集保資料！")
                        get_cached_figures.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.sidebar.warning("FinMind 暫無該標的集保歷史分級資料。")
                except Exception as e:
                    st.sidebar.error(f"增補集保歷史失敗: {e}")

    st.markdown("---")
    st.subheader("[上市/上櫃]批次作業")
    if st.button("📥 擷取最近一週大戶持股比例資料", use_container_width=True):
        with st.spinner("正在連線集保開放資料網擷取最新週全市場大戶持股分級..."):
            try:
                from data_fetcher import batch_fetch_and_save_latest_tdcc_holding
                batch_res = batch_fetch_and_save_latest_tdcc_holding()
                if batch_res.get("ok"):
                    st.sidebar.success(batch_res.get("msg", "批次更新完成！"))
                    get_cached_figures.clear()
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.sidebar.warning(batch_res.get("msg", "批次作業未寫入任何資料。"))
            except Exception as e:
                st.sidebar.error(f"批次作業異常: {e}")


# 2. 主畫面頂部：標題列 + 燈號 + 導航按鈕
current_code = str(st.session_state.stock_id).strip().upper()
is_current_index = current_code.startswith("^")

nav_codes = []
if not is_current_index:
    if current_code in history_codes:
        nav_codes = history_codes
    else:
        nav_codes = [current_code] + history_codes

curr_idx = nav_codes.index(current_code) if (not is_current_index and current_code in nav_codes) else -1
has_prev = curr_idx > 0
has_next = (curr_idx >= 0) and (curr_idx < len(nav_codes) - 1)

auth_state = cloud_sync.get_auth_status()
status_dot = "🟡" if auth_state == 2 else ("🔵" if auth_state == 1 else "⚪")
status_title = (
    "雲端已連線並同步就緒"
    if auth_state == 2
    else ("已取得金鑰但尚未驗證/驗證異常" if auth_state == 1 else "未偵測到雲端金鑰")
)

st.markdown(f"""
<div style="text-align: center; font-size: 16px; font-weight: bold; margin-bottom: 6px;">
台股技術與籌碼分析 v{SYSTEM_VERSION} <span title="{status_title}" style="cursor: help;">{status_dot}</span>
</div>
""", unsafe_allow_html=True)

# 【修訂說明 2026-11-17】雲端同步異常即時通報橫幅（絕不靜默吞掉上傳失敗）
sync_err_msg = cloud_sync.get_last_sync_error()
if sync_err_msg:
    st.warning(f"⚠️ 雲端資料庫同步提示：{sync_err_msg}")

# ==============================================================================
# 【設計紀律與防呆備註 2026-11-17 — 嚴禁誤刪或改動引發重工】：
# 1. 點擊「◀ 上一檔 / 下一檔 ▶」屬於依序瀏覽，絕對不可更改查詢歷史紀錄順序（promote_to_top 必須維持 False）。
# 2. 點擊「◀ 上一檔 / 下一檔 ▶」絕對不可修改側邊欄「股票代號 (直接鍵入)」輸入框（stock_input_box），
#    不僅符合操作直覺，亦可避免在 st.text_input 實例化後賦值觸發 StreamlitWidgetAlreadyInstantiatedError 崩潰。
# ==============================================================================
col_prev, col_next = st.columns([1, 1])
with col_prev:
    if st.button("◀ 上一檔", disabled=not has_prev, use_container_width=True, key="btn_prev_stk"):
        prev_code = nav_codes[curr_idx - 1]
        st.session_state.stock_id = prev_code
        st.session_state.promote_to_top = False
        st.rerun()
with col_next:
    if st.button("下一檔 ▶", disabled=not has_next, use_container_width=True, key="btn_next_stk"):
        next_code = nav_codes[curr_idx + 1]
        st.session_state.stock_id = next_code
        st.session_state.promote_to_top = False
        st.rerun()

# 3. 讀取圖表與渲染三頁籤介面
if st.session_state.stock_id:
    status_slot = st.empty()
    res = get_cached_figures(
        stock_id=st.session_state.stock_id,
        period=st.session_state.period,
        disp_days=st.session_state.disp_days,
        base_date=target_date_val,
        m1_thresh=m1_thresh,
        m2_thresh=m2_thresh,
        is_mobile=is_mobile,
        force_refresh=force_refresh
    )
    status_slot.empty()

    if res is None or res[0] is None:
        st.error(f"無法取得代號 `{st.session_state.stock_id}` 的資料，請檢查代號是否正確或稍後再試。")
    else:
        fig_top, fig_btm, df_data, c_name, start_idx, end_idx = res
        curr_code_clean = str(st.session_state.stock_id).strip().upper()
        if not curr_code_clean.startswith("^"):
            if st.session_state.promote_to_top:
                save_stock_history(curr_code_clean, name=c_name)
                st.session_state.promote_to_top = False
            elif curr_code_clean not in history_codes:
                save_stock_history(curr_code_clean, name=c_name)
            elif c_name and c_name != curr_code_clean:
                update_stock_name_only(curr_code_clean, c_name)

        top_h = 270 if is_mobile else 310
        tech_h = 540 if is_mobile else 580
        chip_h = 760 if is_mobile else 800
        chart_uid = f"mc_{curr_code_clean.replace('^', 'IDX_')}_{int(time.time() * 1000)}"

        top_html = get_top_chart_html(
            fig_top=fig_top,
            df=df_data,
            chart_id=chart_uid,
            top_height=top_h,
            initial_disp_days=st.session_state.disp_days,
            initial_end_idx=end_idx
        )
        # 【修訂說明 2026-11-17】手機版上方資訊列折成3行，預留 +62px 防止成交量 0 軸與底部被截斷
        top_iframe_h = (top_h + 62) if is_mobile else (top_h + 44)
        components.html(top_html, height=top_iframe_h, scrolling=False)

        tab_tech, tab_chip, tab_broker = st.tabs(["📊 指標", "💰 籌碼", "🏦 分點"])

        with tab_tech:
            tech_html = get_tech_tab_html(
                fig_btm=fig_btm,
                df=df_data,
                chart_id=chart_uid,
                tech_height=tech_h,
                initial_disp_days=st.session_state.disp_days,
                initial_end_idx=end_idx
            )
            components.html(tech_html, height=tech_h + 46, scrolling=False)

        with tab_chip:
            chip_html = get_chip_tab_html(
                fig_btm=fig_btm,
                df=df_data,
                chart_id=chart_uid,
                chip_height=chip_h,
                initial_disp_days=st.session_state.disp_days,
                initial_end_idx=end_idx,
                m1_thresh=m1_thresh,
                m2_thresh=m2_thresh
            )
            components.html(chip_html, height=chip_h + 68, scrolling=False)

        with tab_broker:
            trade_dates_tuple = tuple(df_data.index.strftime('%Y-%m-%d').tolist())
            # 若未勾選復盤指定基準日，盤中（台灣時間 17:00 前）分點基準日自動退回前一個已結算交易日
            broker_end_idx = end_idx if use_target_date else _resolve_broker_end_idx(trade_dates_tuple, end_idx)
            target_d_str = trade_dates_tuple[broker_end_idx] if trade_dates_tuple else ""
            req_key = f"{curr_code_clean}_{target_d_str}"
            include_60d = req_key in st.session_state.broker_60d_requests

            if not curr_code_clean.startswith("^") and is_tw_stock_or_etf(curr_code_clean) and target_d_str:
                if not include_60d:
                    if st.button(
                        f"📥 載入近 60 日分點統計與明細（基準日 {target_d_str}）",
                        key=f"btn_load_60d_{req_key}",
                        use_container_width=True
                    ):
                        st.session_state.broker_60d_requests.add(req_key)
                        st.rerun()
                else:
                    st.caption(f"✅ 已載入近 60 日分點統計與明細（基準日 {target_d_str}）")

            with st.spinner(
                f"正在載入分點統計與雲端明細（{'含近 60 日' if include_60d else '預設至 20 日'}）..."
            ):
                broker_payload = get_cached_broker_payload(
                    stock_id=curr_code_clean,
                    trade_dates_tuple=trade_dates_tuple,
                    target_end_idx=broker_end_idx,
                    force_refresh=force_refresh,
                    include_60d=include_60d
                )
            broker_html = get_broker_tab_html(
                df=df_data,
                chart_id=chart_uid,
                initial_end_idx=broker_end_idx,
                is_index=curr_code_clean.startswith("^"),
                broker_payload=broker_payload
            )
            components.html(broker_html, height=1380, scrolling=True)
# EOF app.py
