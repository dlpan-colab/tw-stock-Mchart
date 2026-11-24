"""
data_fetcher.py - 整合技術與籌碼資料擷取模組（對外統一入口）
(依邏輯職責拆分為 ftch_kline_chip.py、ftch_tdcc_dash.py、ftch_gov8.py、ftch_broker.py 與本全市籌碼批次增補總入口，維持 100% 向後相容匯出)
版本: 202611242207
"""

import gc
import time
import pandas as pd
from datetime import datetime, timedelta

MODULE_NAME = "data_fetcher"
MODULE_VERSION = "202611242207"

from storage import (
    StockChipStorage,
    COMMON_STOCK_NAMES,
    load_stock_names_dict,
    load_stock_history,
    get_stock_chinese_name,
    is_tw_stock_or_etf,
    is_tw_index_with_gov_brokers,
    sync_db_push,
    _do_sync_db_push,
)

from ftch_kline_chip import (
    FINMIND_TOKEN,
    fetch_stock_name,
    _fetch_tw_official_month_k,
    fetch_stock_daily_k,
    sync_chip_data,
    fetch_institutional_investors,
    fetch_twse_total_margin_data,
    fetch_tpex_total_margin_data,
    fetch_margin_short_data,
)

from ftch_tdcc_dash import (
    fetch_tdcc_holding_history,
    fetch_tdcc_holding_data,
    batch_fetch_and_save_latest_tdcc_holding,
    fetch_dashboard_watchlist_rows,
)

from ftch_gov8 import (
    EIGHT_GOV_BROKERS,
    _fetch_histock_broker8_single_day,
    batch_sync_tw_index_gov_brokers,
    fetch_tw_index_gov_broker_bundle,
)

from ftch_broker import (
    MDJ_BASE_DOMAIN,
    MDJ_HEADERS,
    GOV_BROKER_PREFIXES,
    get_default_broker_backfill_base_date,
    is_broker_daily_data_ready_for_date,
    _normalize_mdj_date,
    _parse_int_sheets,
    _classify_broker_system,
    _fetch_mdj_html,
    _resolve_mdj_broker_detail_url,
    _parse_fubon_side_block,
    _extract_fubon_last_update_info,
    fetch_stock_broker_range_ranking,
    fetch_single_broker_daily_series,
    _series_reaches_target_date,
    batch_sync_all_stocks_brokers,
)


# =========================================================================
# 【全市(含上櫃)資券 / 法人 / 大戶指定基準日區間批次增補引擎】
# =========================================================================
def get_default_chip_backfill_base_date(now_dt: datetime = None) -> datetime.date:
    now_tw = now_dt if now_dt is not None else (datetime.utcnow() + timedelta(hours=8))
    base_d = now_tw.date()
    if base_d.weekday() == 5:
        base_d -= timedelta(days=1)
    elif base_d.weekday() == 6:
        base_d -= timedelta(days=2)
    elif now_tw.hour < 16 or (now_tw.hour == 16 and now_tw.minute < 30):
        base_d -= timedelta(days=1)
        while base_d.weekday() >= 5:
            base_d -= timedelta(days=1)
    return base_d


def _get_hist_tw_stock_items() -> list:
    hist_list = load_stock_history()
    stock_items = []
    seen_codes = set()
    for item in hist_list:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or not is_tw_stock_or_etf(code) or code in seen_codes:
            continue
        seen_codes.add(code)
        c_name = str(item.get("name", "")).strip() or get_stock_chinese_name(code)
        stock_items.append((code, c_name))
    return stock_items


def batch_sync_all_stocks_margin(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    stock_items = _get_hist_tw_stock_items()
    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]

    updated_stocks = 0
    added_rows_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查資券交易日序列與缺失紀錄...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is None or df_k.empty:
            k_res = fetch_stock_daily_k(code, period="1y", force_refresh=False)
            if k_res and k_res[0] is not None:
                df_k = k_res[0]
        if df_k is None or df_k.empty:
            gc.collect()
            continue

        trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index]
        valid_pos = [i for i, d_s in enumerate(trade_dates) if d_s <= b_norm]
        if not valid_pos:
            gc.collect()
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_dates = trade_dates[start_pos:anchor_pos + 1]
        start_date_str = target_dates[0]

        df_ms_exist = storage.load_margin_df()
        exist_dates = set(df_ms_exist["date"].dt.strftime("%Y-%m-%d")) if (df_ms_exist is not None and not df_ms_exist.empty) else set()
        missing_dates = [d for d in target_dates if d not in exist_dates]
        if not missing_dates:
            del df_k, df_ms_exist
            gc.collect()
            continue

        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, f"補抓資券籌碼 ({start_date_str} ~ {b_norm})...")

        start_excl = (pd.to_datetime(min(missing_dates)) - timedelta(days=1)).strftime("%Y-%m-%d")
        recs_all = fetch_margin_short_data(code, df_k.index, start_date_exclusive=start_excl)
        recs_filtered = [r for r in recs_all if start_date_str <= str(r[0])[:10] <= b_norm]
        if recs_filtered:
            storage.save_margin_data(recs_filtered)
            updated_stocks += 1
            added_rows_total += len(recs_filtered)
            time.sleep(0.25)
        else:
            time.sleep(0.08)

        del df_k, df_ms_exist, recs_all, recs_filtered
        gc.collect()

    return (
        f"批次資券籌碼增補完成（基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（寫入 {added_rows_total} 筆交易日資券紀錄）。"
    )


def batch_sync_all_stocks_institutional(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    stock_items = _get_hist_tw_stock_items()
    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]

    updated_stocks = 0
    added_rows_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查法人交易日序列與缺失紀錄...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is None or df_k.empty:
            k_res = fetch_stock_daily_k(code, period="1y", force_refresh=False)
            if k_res and k_res[0] is not None:
                df_k = k_res[0]
        if df_k is None or df_k.empty:
            gc.collect()
            continue

        trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index]
        valid_pos = [i for i, d_s in enumerate(trade_dates) if d_s <= b_norm]
        if not valid_pos:
            gc.collect()
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_dates_str = set(trade_dates[start_pos:anchor_pos + 1])

        df_inst_exist = storage.load_institutional_df()
        exist_dates = set(df_inst_exist["date"].dt.strftime("%Y-%m-%d")) if (df_inst_exist is not None and not df_inst_exist.empty) else set()
        missing_dt_objs = [d for d in df_k.index if d.strftime("%Y-%m-%d") in target_dates_str and d.strftime("%Y-%m-%d") not in exist_dates]
        if not missing_dt_objs:
            del df_k, df_inst_exist
            gc.collect()
            continue

        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, f"補抓法人籌碼（缺失 {len(missing_dt_objs)} 日）...")

        inst_recs = fetch_institutional_investors(
            pure_code=code,
            df_dates=df_k.index,
            explicit_missing_dates=missing_dt_objs
        )
        if inst_recs:
            storage.save_institutional_data(inst_recs)
            updated_stocks += 1
            added_rows_total += len(inst_recs)
            time.sleep(0.25)
        else:
            time.sleep(0.06)

        del df_k, df_inst_exist, inst_recs
        gc.collect()

    return (
        f"批次法人籌碼增補完成（基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（寫入 {added_rows_total} 筆交易日法人紀錄）。"
    )


def batch_sync_all_stocks_holding(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    stock_items = _get_hist_tw_stock_items()
    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]
    try:
        base_dt = datetime.strptime(b_norm, "%Y-%m-%d")
    except Exception:
        base_dt = datetime.now()
        b_norm = base_dt.strftime("%Y-%m-%d")

    fallback_start_str = (base_dt - timedelta(days=max(n_days * 2, n_days + 4))).strftime("%Y-%m-%d")
    needed_weeks = max(2, min(15, (n_days // 4) + 3))

    updated_stocks = 0
    added_weeks_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查集保大戶週別紀錄...")

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()
        if df_k is not None and not df_k.empty:
            trade_dates = [d.strftime("%Y-%m-%d") for d in df_k.index if d.strftime("%Y-%m-%d") <= b_norm]
            if trade_dates:
                start_date_str = trade_dates[max(0, len(trade_dates) - n_days)]
            else:
                start_date_str = fallback_start_str
        else:
            start_date_str = fallback_start_str

        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, f"補抓大戶籌碼 ({start_date_str} ~ {b_norm})...")

        hist_recs = fetch_tdcc_holding_history(code, weeks=needed_weeks)
        filtered_recs = [
            r for r in hist_recs
            if len(r) >= 5 and start_date_str <= str(r[0])[:10] <= b_norm and 1 <= int(r[1]) <= 15
        ]
        if filtered_recs:
            storage.save_holding_data(filtered_recs)
            weeks_cnt = len({str(r[0])[:10] for r in filtered_recs})
            updated_stocks += 1
            added_weeks_total += weeks_cnt
            time.sleep(0.25)
        else:
            time.sleep(0.08)

        del df_k, hist_recs, filtered_recs
        gc.collect()

    return (
        f"批次大戶籌碼增補完成（基準日 {b_norm} 往前 {n_days} 個交易日區間）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（新增 {added_weeks_total} 週集保分級紀錄）。"
    )
## EOF data_fetcher.py
