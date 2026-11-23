"""
app.py - 主應用程式介面與生命週期控制
(三主頁籤架構：操作儀錶板 / 個股 / 參數設定 + 自選與查詢歷史同步 + 盤中均線多空燈號 + 動態chart_id杜絕跨頁籤殘留 + 批次增補指定基準日起往前N日分點統計與明細版 + 分點15:00前對齊前一交易日與分點統計/分點日況雙頁籤版 + 上下雙複合選單自由輸入置頂/下拉選取不改順序及初始K線30根 + 全市含上櫃籌碼指定基準日區間標題與雙鍵並列 + 大戶15週與全市場含上櫃標題及底部目前關注目標列版 + 關注交易日專屬分點日況隔離與增補分點標註僅限最近交易日之近20日版 + 修正主圖高度解包錯位並對齊成交量Y軸0刻度完整顯示版 + 手機窄螢幕個股導覽列與參數設定雙功能鍵強制同列並排版 + 加權^TWII與櫃買^TWOII八大官股個股前50名分點統計與單一個股8家官股行庫逐日買賣超日況及獨立增補清除維護版)
版本: 202611240720
"""

import os
import time
import re
from datetime import datetime, timedelta
import streamlit as st
import streamlit.components.v1 as components
import cloud_sync

MODULE_NAME = "app"
MODULE_VERSION = "202611240720"


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
                    content = f.read(2000)
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
    clear_all_stocks_chip_range,
    clear_all_broker_data,
    clear_tw_index_gov_broker_data,
    is_tw_stock_or_etf,
    is_tw_index_with_gov_brokers
)
from chart_builder import build_split_figures
from frontend import (
    get_legend_html,
    get_top_chart_html,
    get_tech_tab_html,
    get_chip_tab_html,
    get_broker_stats_tab_html,
    get_broker_daily_tab_html
)
from data_fetcher import (
    fetch_stock_broker_range_ranking,
    fetch_single_broker_daily_series,
    fetch_tw_index_gov_broker_bundle,
    fetch_dashboard_watchlist_rows,
    get_default_broker_backfill_base_date,
    get_default_chip_backfill_base_date
)

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
    """
    【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 同時支援台股個股/ETF（富邦券商分點）與大盤加權指數（^TWII）、櫃買指數（^TWOII）（HiStock 八大官股個股買賣超）；
       - 針對 ^TWII 與 ^TWOII：呼叫 fetch_tw_index_gov_broker_bundle() 依關注交易日往前計算當日/近10日/近20日/近60日
         買超前 50 大與賣超前 50 大個股統計（單位：萬元），並掛載各候選個股對應 8 家官股行庫（合庫、土銀、台銀、台企銀、彰銀、第一金、兆豐銀、華南永昌）
         的每日買賣超序列，供「📈 分點日況」下拉選單選取關注個股後一次繪製 8 個子圖；
       - 針對個股/ETF：載入所有歷史基準日之 1/10/20/60 日買賣超統計快照，並依關注交易日掛載專屬逐日買賣超序列。
    2. 防呆防錯原因：
       - 美歐亞等海外指數（^DJI、^IXIC 等）仍直接回傳 {"by_date": {}}，不觸發任何無效爬蟲；
       - ^TWII 與 ^TWOII 每次切換關注交易日皆依累積之 gov_index_stock_daily 即時重算區間前 50 名與 8 行庫子圖序列，確保不遺漏批次增補之歷史交易日。
    """
    code = str(stock_id).strip().upper()
    is_gov_idx = is_tw_index_with_gov_brokers(code)
    is_stk = is_tw_stock_or_etf(code)
    if not code or (not is_stk and not is_gov_idx) or not trade_dates_tuple:
        return {"by_date": {}}

    n_dates = len(trade_dates_tuple)
    safe_idx = min(max(0, int(target_end_idx)), n_dates - 1)
    end_date_str = trade_dates_tuple[safe_idx]
    latest_trade_date_str = trade_dates_tuple[-1]

    storage = StockChipStorage(code)

    # -----------------------------------------------------------------
    # 分支 A：大盤加權（^TWII）與櫃買（^TWOII）八大官股個股統計與8行庫日況
    # -----------------------------------------------------------------
    if is_gov_idx:
        by_date_map = {}
        all_stored_ranks = storage.load_all_broker_range_ranks()
        for hist_date_str, hist_bundle in all_stored_ranks.items():
            if hist_date_str != end_date_str:
                by_date_map[hist_date_str] = dict(hist_bundle)

        gov_bundle, _ = fetch_tw_index_gov_broker_bundle(
            pure_code=code,
            trade_dates_tuple=trade_dates_tuple,
            target_end_idx=safe_idx,
            include_60d=True
        )
        if gov_bundle:
            storage.save_broker_range_rank(end_date_str, gov_bundle, sync_cloud=False)
            by_date_map[end_date_str] = gov_bundle
        return {"by_date": by_date_map}

    # -----------------------------------------------------------------
    # 分支 B：台股個股 / ETF 富邦券商分點統計與日況
    # -----------------------------------------------------------------
    def _has_valid_win(bundle_obj: dict, w_num: int) -> bool:
        if not isinstance(bundle_obj, dict):
            return False
        w_item = bundle_obj.get(f"w{w_num}")
        if not isinstance(w_item, dict):
            return False
        return bool(w_item.get("buy") or w_item.get("sell"))

    all_focus_series = storage.load_all_broker_focus_daily_series()

    def attach_focus_series_to_bundle(bundle: dict, target_date_str: str) -> dict:
        focus_day_obj = all_focus_series.get(target_date_str, {})
        for w in (10, 20, 60):
            w_key = f"w{w}"
            w_obj = bundle.get(w_key)
            if not isinstance(w_obj, dict):
                continue
            w_focus = focus_day_obj.get(w_key, {})
            w_obj["top5_buy_series"] = w_focus.get("top5_buy_series", [])
            w_obj["top5_sell_series"] = w_focus.get("top5_sell_series", [])
        return bundle

    all_stored_ranks = storage.load_all_broker_range_ranks()
    by_date_map = {}
    for hist_date_str, hist_bundle in all_stored_ranks.items():
        if hist_date_str == end_date_str and force_refresh:
            continue
        by_date_map[hist_date_str] = attach_focus_series_to_bundle(dict(hist_bundle), hist_date_str)

    cached_rank = None if force_refresh else all_stored_ranks.get(end_date_str)
    has_focus_for_end = bool(
        all_focus_series.get(end_date_str, {}).get("w20", {}).get("top5_buy_series")
        or all_focus_series.get(end_date_str, {}).get("w20", {}).get("top5_sell_series")
    )
    is_end_latest = (end_date_str == latest_trade_date_str)

    if cached_rank is not None:
        base_ok = all(_has_valid_win(cached_rank, w) for w in (1, 10, 20))
        need_60_missing = include_60d and (not _has_valid_win(cached_rank, 60))
        need_latest_focus = is_end_latest and (not has_focus_for_end)
        if base_ok and not need_60_missing and not need_latest_focus:
            by_date_map[end_date_str] = attach_focus_series_to_bundle(dict(cached_rank), end_date_str)
            return {"by_date": by_date_map}

    def _calc_win_starts(anchor_idx: int) -> dict:
        anchor_d = trade_dates_tuple[anchor_idx]
        return {
            1: anchor_d,
            10: trade_dates_tuple[max(0, anchor_idx - 10 + 1)],
            20: trade_dates_tuple[max(0, anchor_idx - 20 + 1)],
            60: trade_dates_tuple[max(0, anchor_idx - 60 + 1)],
        }

    win_starts = _calc_win_starts(safe_idx)
    target_windows = (1, 10, 20, 60) if include_60d else (1, 10, 20)
    series_windows = (10, 20, 60) if include_60d else (10, 20)
    earliest_start = win_starts[60] if include_60d else win_starts[20]

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
        if not fetch_windows and is_end_latest and not has_focus_for_end:
            fetch_windows = [10, 20]
        elif not fetch_windows:
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

    if is_end_latest:
        broker_df_cache = {}
        for w in fetch_windows:
            if w not in series_windows:
                continue
            s_str = win_starts[w]
            df_b, df_s = rank_dfs.get(w, (None, None))
            for side_key, df_side in (("buy", df_b), ("sell", df_s)):
                if df_side is None or df_side.empty:
                    continue
                for rank_idx, (_, row) in enumerate(df_side.head(5).iterrows(), start=1):
                    b_name = str(row.get("分點名稱", "")).strip()
                    d_url = str(row.get("明細網址", "")).strip()
                    tot_net = int(row.get("買賣超(張)", 0) or 0)
                    if not b_name or not d_url:
                        continue
                    if b_name not in broker_df_cache:
                        df_fresh = fetch_single_broker_daily_series(d_url, earliest_start, end_date_str)
                        broker_df_cache[b_name] = df_fresh
                        if df_fresh is not None and not df_fresh.empty:
                            storage.save_broker_daily_trades(b_name, df_fresh, sync_cloud=False)
                        time.sleep(0.08)
                    df_cached_b = broker_df_cache.get(b_name)
                    if df_cached_b is not None and not df_cached_b.empty:
                        df_win = df_cached_b[
                            (df_cached_b["日期"] >= s_str) & (df_cached_b["日期"] <= end_date_str)
                        ].copy()
                        if not df_win.empty:
                            storage.save_broker_focus_daily_series(
                                focus_date=end_date_str,
                                window_days=w,
                                side=side_key,
                                rank_no=rank_idx,
                                broker_name=b_name,
                                total_net=tot_net,
                                df_trades=df_win,
                                sync_cloud=False
                            )
        all_focus_series = storage.load_all_broker_focus_daily_series()

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
        by_date_map[end_date_str] = attach_focus_series_to_bundle(day_bundle, end_date_str)

    return {"by_date": by_date_map}


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
    .block-container {
        padding-top: 2.6rem;
        padding-bottom: 1.5rem;
        padding-left: 0.85rem;
        padding-right: 0.85rem;
    }
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

    /* 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
       1. 修改目的：使用後代選擇器 :has(.stock-nav-anchor) 穿透手機窄螢幕（<640px）Streamlit 垂直堆疊樣式，
          強制個股頁籤上下「◀ 上一檔 / 中間複合選單 / 下一檔 ▶」三元件始終並排於同一列；
       2. 防呆防錯原因：設定中間選單 min-width: 0 與 flex: 1 1 0，避免在 360px 手機螢幕撐爆寬度而折行。 */
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

    /* 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
       修改目的：強制「⚙️ 參數設定」頁籤內所有「批次增補 / 清除」雙按鈕列在手機窄螢幕（<640px）保持同列水平並排；
       防呆防錯原因：以 .settings-btn-row-anchor 錨點限定作用於並排功能鍵列，不影響全寬表單元件。 */
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
        width: 50% !important;
        min-width: 0 !important;
        max-width: 50% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.settings-btn-row-anchor) [data-testid="stHorizontalBlock"] button {
        width: 100% !important;
        min-width: 0 !important;
        padding: 5px 4px !important;
        font-size: 12px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }

    /* 個股子頁籤（指標 / 籌碼 / 分點統計 / 分點日況） */
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
if "confirm_clear_gov_brokers" not in st.session_state:
    st.session_state.confirm_clear_gov_brokers = False
if "confirm_clear_chip_type" not in st.session_state:
    st.session_state.confirm_clear_chip_type = ""
if "index_select_box" not in st.session_state:
    st.session_state.index_select_box = "選擇主要市場指數..."
if "ms_counter" not in st.session_state:
    st.session_state.ms_counter = 0
if "promote_to_top" not in st.session_state:
    st.session_state.promote_to_top = False
if "broker_60d_requests" not in st.session_state:
    st.session_state.broker_60d_requests = set()


def _apply_stock_selector_choice(widget_key: str):
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 處理「📈 個股」頁籤上下兩個可輸入＋下拉複合選單（accept_new_options=True）之變更事件：
         (a) 若為「下拉點選既有查詢歷史項目」（格式為「代號 名稱」且存在於歷史清單），僅切換標的、設定 promote_to_top=False，絕不改變查詢歷史順序；
         (b) 若為「手動輸入代號並按 Enter」，解析代號並設定 promote_to_top=True，將該標的置頂寫入查詢歷史清單。
    2. 防呆防錯原因：相容帶名稱字串（如 "6669 緯穎"）或純輸入代號（如 "2330"、"^TWII"）。
    """
    raw_sel = str(st.session_state.get(widget_key, "") or "").strip()
    if not raw_sel:
        return
    hist_now = load_stock_history()
    existing_labels = set(_format_code_name_options(hist_now))
    if raw_sel in existing_labels:
        target_code = raw_sel.split()[0].strip().upper()
        if target_code:
            st.session_state.stock_id = target_code
            st.session_state.promote_to_top = False
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
        "加權指數 (^TWII)", "櫃買指數 (^TWOII)",
        "那斯達克 (^IXIC)", "費城半導體 (^SOX)", "道瓊工業 (^DJI)", "標普500 (^GSPC)",
        "日經225 (^N225)", "韓國綜合 (^KS11)",
        "英國富時100 (^FTSE)", "德國DAX (^GDAXI)", "法國CAC40 (^FCHI)"
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
            history_options = ["選擇歷史紀錄..."] + _format_code_name_options(history_records)
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
            st.warning("⚠️ 確定要清空所有查詢歷史紀錄嗎？")
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button("確定清空", key="btn_confirm_yes", use_container_width=True):
                    clear_stock_history()
                    st.session_state.confirm_clear_all = False
                    st.session_state.ms_counter += 1
                    get_cached_dashboard_rows.clear()
                    st.rerun()
            with c_no:
                if st.button("取消", key="btn_confirm_no", use_container_width=True):
                    st.session_state.confirm_clear_all = False
                    st.rerun()

    st.session_state.is_mobile_mode = st.toggle(
        "手機版緊湊模式 (自動最佳化字體與高度)",
        value=st.session_state.is_mobile_mode
    )

    period_options = {"1年": "1y", "2年": "2y", "3年": "3y", "5年": "5y", "6個月": "6mo", "3個月": "3mo"}
    current_period_label = [k for k, v in period_options.items() if v == st.session_state.period][0]
    sel_period_label = st.selectbox("K線歷史抓取範圍", list(period_options.keys()), index=list(period_options.keys()).index(current_period_label))
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
    st.session_state.m1_thresh = st.selectbox("大戶線 1 (預設1000張)", major_options, index=major_options.index(st.session_state.m1_thresh))
    st.session_state.m2_thresh = st.selectbox("大戶線 2 (預設400張)", major_options, index=major_options.index(st.session_state.m2_thresh))

    st.markdown("---")
    if st.button("🔄 強制重新抓取最新資料", use_container_width=True):
        st.session_state.force_refresh = True
        get_cached_figures.clear()
        get_cached_broker_payload.clear()
        get_cached_dashboard_rows.clear()
        st.success("快取已清除，切換回「📈 個股」頁籤即會重新抓取最新資料。")

    st.markdown("---")
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

    # ① 第一列：資券籌碼維護；第二列：批次增補 / 清除 並列
    st.markdown("<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>資券籌碼維護</div>", unsafe_allow_html=True)
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
        get_cached_figures.clear()
        st.success(summary_ms)

    # ② 第一列：法人籌碼維護；第二列：批次增補 / 清除 並列
    st.markdown("<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>法人籌碼維護</div>", unsafe_allow_html=True)
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
        get_cached_figures.clear()
        st.success(summary_inst)

    # ③ 第一列：大戶籌碼維護（最多15週）；第二列：批次增補 / 清除 並列
    st.markdown("<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>大戶籌碼維護（最多15週）</div>", unsafe_allow_html=True)
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
        get_cached_figures.clear()
        st.success(summary_hold)

    # 二段式確認清除
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
                    get_cached_figures.clear()
                    st.success(res_chip_msg)
            with cc_no:
                if st.button("取消清除", key="btn_confirm_clear_chip_no", use_container_width=True):
                    st.session_state.confirm_clear_chip_type = ""
                    st.rerun()

    # =====================================================================
    # 【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    # 1. 修改目的：新增「加權指數／櫃買指數八大官股維護」獨立區塊，提供「八大官股增補基準日」與「往前增補交易日數」，
    #    並並列設置「📥 批次增補八大官股交易前30個股」與「🗑️ 清除八大官股交易資料」雙功能按鈕。
    # 2. 防呆防錯原因：二段式確認清除，僅清除 ^TWII 與 ^TWOII 八大官股紀錄並清理快取，完全保留指數日線、資券及其他個股資料。
    # =====================================================================
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
        "八大官股增補基準日（預設15:00前為前一交易日）",
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
        "增補基準日（預設15:00前為前一交易日）",
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

    st.markdown("<div style='font-size:13px; font-weight:700; color:#334155; margin-top:6px; margin-bottom:2px;'>增補分點(分點買賣超交易日況僅限最近交易日之近20日)</div>", unsafe_allow_html=True)
    with st.container():
        st.markdown("<div class='settings-btn-row-anchor'></div>", unsafe_allow_html=True)
        col_bk_add, col_bk_clr = st.columns(2)
        with col_bk_add:
            run_bk_sync = st.button("📥 批次增補歷史分點（統計與明細）", key="btn_batch_sync_brokers", use_container_width=True)
        with col_bk_clr:
            if st.button("🗑️ 清除所有分點資料", key="btn_batch_clear_brokers", use_container_width=True):
                st.session_state.confirm_clear_brokers = True
                st.rerun()

    if run_bk_sync:
        from data_fetcher import batch_sync_all_stocks_brokers
        base_d_str = backfill_base_dt.strftime("%Y-%m-%d")
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


# =====================================================================
# 主頁籤 2：📈 個股（預設顯示，含上下雙複合選單、K線主圖及四大子頁籤）
# =====================================================================
else:
    auth_st = cloud_sync.get_auth_status()
    status_icon = "🟡" if auth_st == 2 else ("🔵" if auth_st == 1 else "⚪")
    st.markdown(
        f"<div style='font-size:15px; font-weight:700; color:#1e293b; margin-bottom:2px;'>"
        f"台股技術與籌碼分析 <span style='font-size:12px; color:#64748b;'>v{SYSTEM_VERSION} {status_icon}</span></div>",
        unsafe_allow_html=True
    )

    history_records = load_stock_history()
    history_codes = [str(item.get("code")).strip().upper() for item in history_records if item.get("code")]
    selector_options = _format_code_name_options(history_records)
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
                on_change=on_top_stock_selector_change,
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
        fig_top, fig_btm, df_res, resolved_name, raw_end_idx, raw_disp_n = get_cached_figures(
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
                is_index=(not has_broker_support)
            )
            components.html(broker_stats_html, height=580, scrolling=True)

        with tab_broker_daily:
            broker_daily_html = get_broker_daily_tab_html(
                df=df_res,
                chart_id=chart_id,
                broker_payload=broker_payload,
                initial_end_idx=safe_end_idx,
                is_index=(not has_broker_support)
            )
            components.html(broker_daily_html, height=1320, scrolling=True)

        # 底部：「目前關注目標」提示列 ＋「◀ 上一檔」＋「可輸入＋下拉點選（代號 名稱）」＋「下一檔 ▶」＋ 空白緩衝區避開 [Manage app]
        st.markdown("---")
        latest_hist_list = load_stock_history()
        latest_hist_codes = [str(item.get("code")).strip().upper() for item in latest_hist_list if item.get("code")]
        btm_options = _format_code_name_options(latest_hist_list)
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
                    on_change=on_bottom_stock_selector_change,
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

        # 底部保留一行空白緩衝區，避開右下角懸浮之 [Manage app] 按鈕
        st.markdown("<div style='height: 54px;'></div>", unsafe_allow_html=True)
    else:
        st.error(f"無法取得 {st.session_state.stock_id} 的資料，請檢查代號是否正確或稍後再試。")
## EOF app.py
