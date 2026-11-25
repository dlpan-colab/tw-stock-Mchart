"""
app_broker_cache.py - 個股分點與大盤八大官股快取組裝模組
(自 app.py 依邏輯職責拆分，開放歷史關注交易日補抓與顯示近 10/20 日個股分點逐日明細，並支援依指定基準日與交易日數逐日增補分點統計與分點日況)
版本: 202611252320
"""

import time
import streamlit as st
from storage import (
    StockChipStorage,
    is_tw_stock_or_etf,
    is_tw_index_with_gov_brokers,
)
from data_fetcher import (
    fetch_stock_broker_range_ranking,
    fetch_single_broker_daily_series,
    fetch_tw_index_gov_broker_bundle,
    is_broker_daily_data_ready_for_date,
)

MODULE_NAME = "app_broker_cache"
MODULE_VERSION = "202611252320"


@st.cache_data(ttl=600, show_spinner=False)
def get_cached_broker_payload(
    stock_id: str,
    trade_dates_tuple: tuple,
    target_end_idx: int,
    force_refresh: bool = False,
    include_60d: bool = False,
    broker_force_days: int = 0,
    broker_base_date: str = ""
) -> dict:
    """
    【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 新增 `broker_base_date` 參數，當 `force_refresh=True` 且 `broker_force_days > 0` 時，
         以使用者於「個股資料維護」設定之「資料維護基準日（`broker_base_date`）」為錨點，
         往前 `broker_force_days` 個交易日區間內，**逐日**重抓分點統計排行（`w1/w10/w20`）
         與該日前 5 名買賣超分點逐日進出明細（**分點日況逐日增補，不限最近一日**）。
       - 同時針對同一分點跨日共用明細暫存（`broker_df_cache`），避免重複抓取相同網址，提升逐日增補效率。
    2. 防呆防錯原因：
       - 若 `broker_base_date` 落在休市日，自動對齊交易日序列中小於等於該日之最近交易日索引（`anchor_idx`）；
         若 `broker_base_date` 為空則退回 `safe_idx`（目前關注交易日）。
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

    eff_force = bool(force_refresh and int(broker_force_days or 0) > 0)

    # 解析「資料維護基準日」對應之交易日索引 anchor_idx
    anchor_idx = safe_idx
    if broker_base_date:
        b_norm = str(broker_base_date).strip()[:10]
        valid_positions = [i for i, d in enumerate(trade_dates_tuple) if str(d)[:10] <= b_norm]
        if valid_positions:
            anchor_idx = valid_positions[-1]

    # -----------------------------------------------------------------
    # 分支 A：大盤加權（^TWII）與櫃買（^TWOII）八大官股個股統計與8行庫日況
    # -----------------------------------------------------------------
    if is_gov_idx:
        by_date_map = {}
        all_stored_ranks = storage.load_all_broker_range_ranks()
        for hist_date_str, hist_bundle in all_stored_ranks.items():
            if hist_date_str != end_date_str and not eff_force:
                by_date_map[hist_date_str] = dict(hist_bundle)

        lookback_start_idx = max(0, safe_idx - 25)
        lookback_start_str = str(trade_dates_tuple[lookback_start_idx])[:10]
        df_gov_avail = storage.load_gov_index_stock_daily_range(lookback_start_str, end_date_str)
        avail_gov_dates = set()
        if df_gov_avail is not None and not df_gov_avail.empty and "trade_date" in df_gov_avail.columns:
            avail_gov_dates = {str(d)[:10] for d in df_gov_avail["trade_date"].tolist() if d}

        date_to_idx = {str(d)[:10]: i for i, d in enumerate(trade_dates_tuple)}
        for d_avail in sorted(avail_gov_dates):
            if d_avail == end_date_str:
                continue
            if not eff_force and d_avail in by_date_map and isinstance(by_date_map[d_avail], dict) and by_date_map[d_avail].get("w1"):
                continue
            d_idx = date_to_idx.get(d_avail)
            if d_idx is not None:
                hist_gov_bundle, _ = fetch_tw_index_gov_broker_bundle(
                    pure_code=code,
                    trade_dates_tuple=trade_dates_tuple,
                    target_end_idx=d_idx,
                    include_60d=True
                )
                if hist_gov_bundle:
                    by_date_map[d_avail] = hist_gov_bundle
                    storage.save_broker_range_rank(d_avail, hist_gov_bundle, sync_cloud=False)

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
    # 分支 B：台股個股 / ETF 富邦券商分點統計與日況（支援最新日與歷史關注日）
    # -----------------------------------------------------------------
    def _has_valid_win(bundle_obj: dict, w_num: int) -> bool:
        if not isinstance(bundle_obj, dict):
            return False
        w_item = bundle_obj.get(f"w{w_num}")
        if not isinstance(w_item, dict):
            return False
        return bool(w_item.get("buy") or w_item.get("sell"))

    def _series_reaches_target_date(series_list: list, target_dt_str: str) -> bool:
        if not isinstance(series_list, list) or not series_list or not target_dt_str:
            return False
        for item in series_list:
            if not isinstance(item, dict):
                continue
            d_arr = item.get("dates") or []
            if d_arr:
                max_d = max(str(x)[:10] for x in d_arr if x)
                if max_d >= target_dt_str:
                    return True
        return False

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

    def _calc_win_starts(idx_pos: int) -> dict:
        anchor_d = trade_dates_tuple[idx_pos]
        return {
            1: anchor_d,
            10: trade_dates_tuple[max(0, idx_pos - 10 + 1)],
            20: trade_dates_tuple[max(0, idx_pos - 20 + 1)],
            60: trade_dates_tuple[max(0, idx_pos - 60 + 1)],
        }

    all_stored_ranks = storage.load_all_broker_range_ranks()
    by_date_map = {}
    for hist_date_str, hist_bundle in all_stored_ranks.items():
        by_date_map[hist_date_str] = attach_focus_series_to_bundle(dict(hist_bundle), hist_date_str)

    # 若為「強制重抓模式」但使用者未勾選分點（broker_force_days <= 0），直接沿用既有分點資料
    if force_refresh and not eff_force:
        return {"by_date": by_date_map}

    # 若為「強制重抓模式」且有勾選分點：自 anchor_idx 往前 broker_force_days 個交易日，
    # 逐日重抓「分點統計（1/10/20日）」＋「前5名買賣超分點逐日明細（分點日況）」
    if eff_force:
        n_force_days = max(1, int(broker_force_days))
        start_hist_idx = max(0, anchor_idx - n_force_days + 1)
        earliest_global_start = trade_dates_tuple[max(0, start_hist_idx - 20 + 1)]
        anchor_end_str = trade_dates_tuple[anchor_idx]

        # 跨日共用單一分點全區間明細快取，大幅加速多日逐日增補分點日況
        shared_broker_df_cache = {}
        for h_idx in range(start_hist_idx, anchor_idx + 1):
            h_dt_str = trade_dates_tuple[h_idx]
            h_starts = _calc_win_starts(h_idx)
            h_rank_dfs = {}
            for w in (1, 10, 20):
                s_str = h_starts[w]
                df_b, df_s = fetch_stock_broker_range_ranking(code, s_str, h_dt_str)
                if (df_b is None or df_b.empty) and (df_s is None or df_s.empty):
                    time.sleep(0.25)
                    df_b, df_s = fetch_stock_broker_range_ranking(code, s_str, h_dt_str)
                h_rank_dfs[w] = (df_b, df_s)
                time.sleep(0.06)

            # 逐日同步增補近 10 日與近 20 日前 5 名買賣超分點逐日進出序列（分點日況，不限最近一日）
            for w in (10, 20):
                s_str = h_starts[w]
                df_b, df_s = h_rank_dfs.get(w, (None, None))
                for side_key, df_side in (("buy", df_b), ("sell", df_s)):
                    if df_side is None or df_side.empty:
                        continue
                    for rank_idx, (_, row) in enumerate(df_side.head(5).iterrows(), start=1):
                        b_name = str(row.get("分點名稱", "")).strip()
                        d_url = str(row.get("明細網址", "")).strip()
                        tot_net = int(row.get("買賣超(張)", 0) or 0)
                        if not b_name or not d_url:
                            continue
                        if b_name not in shared_broker_df_cache:
                            df_fresh = fetch_single_broker_daily_series(
                                d_url, earliest_global_start, anchor_end_str
                            )
                            shared_broker_df_cache[b_name] = df_fresh
                            if df_fresh is not None and not df_fresh.empty:
                                storage.save_broker_daily_trades(b_name, df_fresh, sync_cloud=False)
                            time.sleep(0.06)
                        df_cached_b = shared_broker_df_cache.get(b_name)
                        if df_cached_b is not None and not df_cached_b.empty:
                            df_win = df_cached_b[
                                (df_cached_b["日期"] >= s_str) & (df_cached_b["日期"] <= h_dt_str)
                            ].copy()
                            if not df_win.empty:
                                storage.save_broker_focus_daily_series(
                                    focus_date=h_dt_str,
                                    window_days=w,
                                    side=side_key,
                                    rank_no=rank_idx,
                                    broker_name=b_name,
                                    total_net=tot_net,
                                    df_trades=df_win,
                                    sync_cloud=False
                                )

            h_bundle = {}
            h_has_any = False
            for w in (1, 10, 20):
                s_str = h_starts[w]
                df_b, df_s = h_rank_dfs.get(w, (None, None))
                b_recs = df_to_rank_records(df_b)
                s_recs = df_to_rank_records(df_s)
                if b_recs or s_recs:
                    h_has_any = True
                lbl = h_dt_str if w == 1 else f"{s_str} ~ {h_dt_str}"
                h_bundle[f"w{w}"] = {
                    "range_label": lbl,
                    "buy": b_recs,
                    "sell": s_recs,
                }
            if h_has_any:
                storage.save_broker_range_rank(
                    h_dt_str, h_bundle, sync_cloud=(h_dt_str == latest_trade_date_str)
                )
                by_date_map[h_dt_str] = h_bundle

        # 重新載入所有關注分點逐日明細並掛載至對應交易日
        all_focus_series = storage.load_all_broker_focus_daily_series()
        for dt_k in list(by_date_map.keys()):
            by_date_map[dt_k] = attach_focus_series_to_bundle(dict(by_date_map[dt_k]), dt_k)

        # 若當前個股畫面關注日（end_date_str）已涵蓋於剛才重抓區間內，直接返回；否則再補齊該關注日
        if end_date_str in by_date_map and _has_valid_win(by_date_map[end_date_str], 1):
            return {"by_date": by_date_map}

    # 一般模式（非強制重抓）或關注日不在剛重抓區間內：檢查 end_date_str 是否已具備完整快取
    cached_rank = by_date_map.get(end_date_str)
    end_w20_b = all_focus_series.get(end_date_str, {}).get("w20", {}).get("top5_buy_series") or []
    end_w20_s = all_focus_series.get(end_date_str, {}).get("w20", {}).get("top5_sell_series") or []
    ready_for_end_date = is_broker_daily_data_ready_for_date(end_date_str)
    has_focus_for_end = bool(end_w20_b or end_w20_s) and (
        not ready_for_end_date
        or _series_reaches_target_date(end_w20_b, end_date_str)
        or _series_reaches_target_date(end_w20_s, end_date_str)
    )
    is_end_latest = (end_date_str == latest_trade_date_str)

    if cached_rank is not None:
        base_ok = all(_has_valid_win(cached_rank, w) for w in (1, 10, 20))
        need_60_missing = include_60d and (not _has_valid_win(cached_rank, 60))
        need_focus = (not has_focus_for_end) and (ready_for_end_date or not is_end_latest)
        if base_ok and not need_60_missing and not need_focus:
            by_date_map[end_date_str] = attach_focus_series_to_bundle(dict(cached_rank), end_date_str)
            return {"by_date": by_date_map}

    win_starts = _calc_win_starts(safe_idx)
    target_windows = (1, 10, 20, 60) if include_60d else (1, 10, 20)
    series_windows = (10, 20, 60) if include_60d else (10, 20)
    earliest_start = win_starts[60] if include_60d else win_starts[20]

    if cached_rank is not None:
        fetch_windows = [w for w in target_windows if not _has_valid_win(cached_rank, w)]
        if not fetch_windows and (not has_focus_for_end):
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

    should_fetch_focus = ready_for_end_date or (not is_end_latest)
    if should_fetch_focus:
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

    day_bundle = dict(cached_rank) if isinstance(cached_rank, dict) else {}
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
        storage.save_broker_range_rank(end_date_str, day_bundle, sync_cloud=is_end_latest)
    by_date_map[end_date_str] = attach_focus_series_to_bundle(day_bundle, end_date_str)
    return {"by_date": by_date_map}
## EOF app_broker_cache.py
