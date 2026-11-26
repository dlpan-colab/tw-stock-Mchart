"""
ftch_broker.py - 富邦券商分點進出排行、逐日明細與全市場分點批次增補模組
(自 data_fetcher.py 依邏輯職責拆分，維持既有 16:00 更新時機點對齊、最後更新日規則校準與批次增補機制)
版本: 202611262050
"""

import re
import gc
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from storage import (
    StockChipStorage,
    load_stock_history,
    get_stock_chinese_name,
    is_tw_stock_or_etf,
    sync_db_push,
)
from ftch_kline_chip import fetch_stock_daily_k

MODULE_NAME = "ftch_broker"
MODULE_VERSION = "202611262050"

MDJ_BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"
MDJ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{MDJ_BASE_DOMAIN}/"
}

GOV_BROKER_PREFIXES = (
    "合庫", "合作金庫", "土銀", "土地銀行",
    "台銀", "臺銀", "台灣銀行", "臺灣銀行",
    "台企", "臺企", "台灣企銀", "臺灣企銀",
    "彰銀", "彰化銀行", "第一金", "兆豐", "華南永昌"
)


def get_default_broker_backfill_base_date(now_dt: datetime = None) -> datetime.date:
    """
    【修訂說明 2026-11-24】富邦券商分點資料以每日 16:00 以後為更新當日時機點；
    台灣時間 16:00 前預設對齊前一交易日，16:00（含）以後才對齊當日。
    """
    now_tw = now_dt if now_dt is not None else (datetime.utcnow() + timedelta(hours=8))
    base_d = now_tw.date()
    if base_d.weekday() == 5:
        base_d -= timedelta(days=1)
    elif base_d.weekday() == 6:
        base_d -= timedelta(days=2)
    elif now_tw.hour < 16:
        base_d -= timedelta(days=1)
    while base_d.weekday() >= 5:
        base_d -= timedelta(days=1)
    return base_d


def is_broker_daily_data_ready_for_date(target_date_str: str, now_dt: datetime = None) -> bool:
    """判斷指定交易日 `target_date_str` 是否已過分點當日更新時機點（台灣時間 16:00）。"""
    d_str = str(target_date_str or "").strip()[:10]
    if not d_str:
        return False
    now_tw = now_dt if now_dt is not None else (datetime.utcnow() + timedelta(hours=8))
    today_str = now_tw.strftime("%Y-%m-%d")
    if d_str < today_str:
        return True
    if d_str == today_str:
        return now_tw.hour >= 16
    return False


def _normalize_mdj_date(raw_str: str) -> str:
    s = str(raw_str or "").strip()
    m = re.search(r'(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if not m:
        return ""
    y = int(m.group(1))
    if y < 1911:
        y += 1911
    return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _parse_int_sheets(val_str: str) -> int:
    s = str(val_str or "").replace(",", "").replace("，", "").replace("+", "").replace("−", "-").replace("－", "-").strip()
    if not s or s in ("-", "--", "—"):
        return 0
    try:
        return int(round(float(s)))
    except Exception:
        return 0


def _classify_broker_system(broker_name: str) -> str:
    name = str(broker_name or "").strip()
    for prefix in GOV_BROKER_PREFIXES:
        if prefix in name:
            return "八大官股"
    return "一般券商"


def _fetch_mdj_html(url: str, timeout: int = 8) -> str:
    try:
        res = requests.get(url, headers=MDJ_HEADERS, timeout=timeout)
        if res.status_code != 200 or not res.content:
            return ""
        raw = res.content
        for enc in ("cp950", "big5", "utf-8"):
            try:
                txt = raw.decode(enc)
                if "分點" in txt or "買超" in txt or "賣超" in txt or "券商" in txt or "日期" in txt:
                    return txt
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _resolve_mdj_broker_detail_url(href: str, page_url: str, stock_code: str, start_date: str, end_date: str) -> str:
    if not href or href.lower().startswith("javascript:"):
        return ""
    abs_url = urljoin(page_url, href)
    parsed = urlparse(abs_url)
    qs = parse_qs(parsed.query)
    if "a" not in qs and "A" not in qs:
        qs["a"] = [stock_code]
    qs["c"] = [start_date]
    qs["d"] = [end_date]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _parse_fubon_side_block(cells, a_tags, page_url: str, stock_code: str, start_date: str, end_date: str, is_buy_side: bool):
    if len(cells) < 5:
        return None
    b_name = cells[0].strip()
    if not b_name or any(k in b_name for k in ("買超券商", "賣超券商", "券商名稱", "合計", "總計", "名次", "買進", "賣出")):
        return None
    if re.fullmatch(r'[\d,.\-+%]+', b_name):
        return None

    buy_v = abs(_parse_int_sheets(cells[1]))
    sell_v = abs(_parse_int_sheets(cells[2]))
    raw_net = _parse_int_sheets(cells[3])
    abs_net = abs(raw_net) if raw_net != 0 else abs(buy_v - sell_v)
    if abs_net == 0 and buy_v == 0 and sell_v == 0:
        return None

    net_v = abs_net if is_buy_side else -abs_net
    ratio_v = cells[4].strip() if len(cells) >= 5 else "-"

    detail_url = ""
    for a in a_tags:
        if a.get_text(strip=True) == b_name or b_name in a.get_text(strip=True):
            detail_url = _resolve_mdj_broker_detail_url(a.get("href", ""), page_url, stock_code, start_date, end_date)
            if detail_url:
                break
    if not detail_url and a_tags:
        detail_url = _resolve_mdj_broker_detail_url(a_tags[0].get("href", ""), page_url, stock_code, start_date, end_date)

    return {
        "分點名稱": b_name,
        "體系": _classify_broker_system(b_name),
        "買進(張)": buy_v,
        "賣出(張)": sell_v,
        "買賣超(張)": net_v,
        "佔比": ratio_v,
        "明細網址": detail_url
    }


def _extract_fubon_last_update_info(soup: BeautifulSoup, ref_end_date: str) -> tuple:
    """依據富邦個股分點進出最後更新日解讀規則解析最後更新日與無資料提示。"""
    if soup is None:
        return "", False
    full_txt = re.sub(r'\s+', ' ', soup.get_text(" ", strip=True))
    has_no_data_msg = bool(re.search(r'查無.{0,24}券商分點.{0,8}進出明細', full_txt))

    ref_year = datetime.now().year
    ref_month = datetime.now().month
    if ref_end_date and len(ref_end_date) >= 7 and ref_end_date[:4].isdigit():
        ref_year = int(ref_end_date[:4])
        if ref_end_date[5:7].isdigit():
            ref_month = int(ref_end_date[5:7])

    last_update_iso = ""
    m_ymd = re.search(r'最後更新日[：:\s]*(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', full_txt)
    if m_ymd:
        last_update_iso = _normalize_mdj_date(f"{m_ymd.group(1)}/{m_ymd.group(2)}/{m_ymd.group(3)}")
    else:
        m_md = re.search(r'最後更新日[：:\s]*(\d{1,2})[/-](\d{1,2})', full_txt)
        if m_md:
            mo_n = int(m_md.group(1))
            da_n = int(m_md.group(2))
            yr_n = ref_year - 1 if (ref_month == 1 and mo_n == 12) else ref_year
            last_update_iso = f"{yr_n:04d}-{mo_n:02d}-{da_n:02d}"

    return last_update_iso, has_no_data_msg


def fetch_stock_broker_range_ranking(pure_code: str, start_date: str, end_date: str):
    """查詢富邦 `zco.djhtm` 指定區間 `[start_date, end_date]` 之買超與賣超排行前 15 名並校準最後更新日。"""
    code = str(pure_code or "").strip().upper()
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
        return pd.DataFrame(), pd.DataFrame()

    s_norm = _normalize_mdj_date(start_date) or str(start_date).strip()
    e_norm = _normalize_mdj_date(end_date) or str(end_date).strip()

    candidate_urls = [
        f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&e={s_norm}&f={e_norm}",
        f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&c={s_norm}&d={e_norm}",
    ]

    buy_rows, sell_rows = [], []
    for url in candidate_urls:
        html = _fetch_mdj_html(url, timeout=8)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        last_update_iso, has_no_data_msg = _extract_fubon_last_update_info(soup, e_norm)
        if has_no_data_msg or not last_update_iso:
            continue
        if s_norm == e_norm:
            if last_update_iso != e_norm:
                continue
        else:
            if not (s_norm <= last_update_iso <= e_norm):
                continue

        parsed_buy, parsed_sell = [], []
        for tbl in soup.find_all("table"):
            txt = tbl.get_text()
            if "買超" not in txt and "賣超" not in txt:
                continue
            table_mode = None
            for tr in tbl.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                cells = [re.sub(r'\s+', ' ', td.get_text(strip=True)) for td in tds]
                row_str = "".join(cells)

                if len(cells) >= 10:
                    left_tds = tds[:5]
                    right_tds = tds[5:10]
                    left_links = [a for td in left_tds for a in td.find_all("a", href=True)]
                    right_links = [a for td in right_tds for a in td.find_all("a", href=True)]
                    b_rec = _parse_fubon_side_block(cells[:5], left_links, url, code, s_norm, e_norm, is_buy_side=True)
                    s_rec = _parse_fubon_side_block(cells[5:10], right_links, url, code, s_norm, e_norm, is_buy_side=False)
                    if b_rec:
                        parsed_buy.append(b_rec)
                    if s_rec:
                        parsed_sell.append(s_rec)
                    continue

                if "買超券商" in row_str or ("買超" in row_str and "賣超" not in row_str and len(cells) <= 6):
                    table_mode = "BUY"
                    continue
                if "賣超券商" in row_str or ("賣超" in row_str and "買超" not in row_str and len(cells) <= 6):
                    table_mode = "SELL"
                    continue

                if len(cells) >= 5 and table_mode in ("BUY", "SELL"):
                    row_links = tr.find_all("a", href=True)
                    rec = _parse_fubon_side_block(
                        cells[:5], row_links, url, code, s_norm, e_norm, is_buy_side=(table_mode == "BUY")
                    )
                    if rec:
                        if table_mode == "BUY":
                            parsed_buy.append(rec)
                        else:
                            parsed_sell.append(rec)

        if parsed_buy or parsed_sell:
            buy_rows = parsed_buy
            sell_rows = parsed_sell
            break

    def _finalize_df(rows_list):
        if not rows_list:
            return pd.DataFrame(columns=["名次", "分點名稱", "體系", "買進(張)", "賣出(張)", "買賣超(張)", "佔比", "明細網址"])
        df_out = pd.DataFrame(rows_list).drop_duplicates(subset=["分點名稱"]).head(15).copy()
        df_out.insert(0, "名次", range(1, len(df_out) + 1))
        return df_out

    return _finalize_df(buy_rows), _finalize_df(sell_rows)


def fetch_single_broker_daily_series(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    1. 修改目的：富邦單一分點歷史明細（zco0.djhtm）改以自設區間參數 `c=E&d=起始日&e=結束日` 查詢指定日期區間，
       避免舊參數未能正確限定歷史區間之問題。
    2. 防呆防錯原因：固定解析 5 欄結構（日期、買進、賣出、買賣總額、買賣超），第 5 欄（cells[4]）為買賣超張數。
    """
    empty_df = pd.DataFrame(columns=["日期", "買進(張)", "賣出(張)", "買賣超(張)"])
    if not detail_url:
        return empty_df

    s_norm = _normalize_mdj_date(start_date) or str(start_date).strip()
    e_norm = _normalize_mdj_date(end_date) or str(end_date).strip()

    parsed = urlparse(detail_url)
    qs = parse_qs(parsed.query)
    qs["c"] = ["E"]
    qs["d"] = [s_norm]
    qs["e"] = [e_norm]
    target_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(qs, doseq=True), parsed.fragment))

    html = _fetch_mdj_html(target_url, timeout=8)
    if not html:
        return empty_df

    soup = BeautifulSoup(html, "html.parser")
    daily_records = []
    for tr in soup.find_all("tr"):
        cells = [re.sub(r'\s+', ' ', td.get_text(strip=True)) for td in tr.find_all(["td", "th"])]
        if len(cells) != 5:
            continue
        d_iso = _normalize_mdj_date(cells[0])
        if not d_iso:
            continue
        if s_norm and d_iso < s_norm:
            continue
        if e_norm and d_iso > e_norm:
            continue

        buy_v = _parse_int_sheets(cells[1])
        sell_v = _parse_int_sheets(cells[2])
        net_v = _parse_int_sheets(cells[4])
        if net_v == 0 and (buy_v != 0 or sell_v != 0):
            net_v = buy_v - sell_v

        daily_records.append({
            "日期": d_iso,
            "買進(張)": buy_v,
            "賣出(張)": sell_v,
            "買賣超(張)": net_v
        })

    if not daily_records:
        return empty_df

    df_res = pd.DataFrame(daily_records).drop_duplicates(subset=["日期"]).sort_values("日期").reset_index(drop=True)
    return df_res


def _series_reaches_target_date(series_list: list, target_date_str: str) -> bool:
    if not isinstance(series_list, list) or not series_list or not target_date_str:
        return False
    for item in series_list:
        if not isinstance(item, dict):
            continue
        d_arr = item.get("dates") or []
        if d_arr:
            max_d = max(str(x)[:10] for x in d_arr if x)
            if max_d >= target_date_str:
                return True
    return False


def batch_sync_all_stocks_brokers(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 對齊富邦網站限制（分點買賣超交易日況僅限最近交易日之近 20 日），限定僅對 `latest_trade_idx - t_idx < 20` 之近 20 日
         檢查並補抓分點日況；第 21 日（含）以前之歷史交易日僅維護 1/10/20 日分點統計快照。
       - 只要第 21 日以前之歷史交易日已具備完整 `has_rank_snapshot`，重跑時直接跳過（`skipped_days_total += 1`），
         不再無效重複抓取排行、明細或重複上傳 `.db`，大幅縮短長天期（如 60 日）執行時間並避免連線逾時。
    2. 防呆防錯原因：
       - 每檔個股僅在 `pending_bundles` 或 `wrote_focus_series` 實際有新增資料時才呼叫 `sync_db_push(code)` 上傳雲端，
         確保中斷重跑可從斷點無縫接續。
    """
    hist_list = load_stock_history()
    stock_items = []
    seen_codes = set()
    for item in hist_list:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or code in seen_codes:
            continue
        if not is_tw_stock_or_etf(code):
            continue
        seen_codes.add(code)
        c_name = str(item.get("name", "")).strip() or get_stock_chinese_name(code)
        stock_items.append((code, c_name))

    if not stock_items:
        return "目前查詢歷史清單無可增補之上市／上櫃個股或 ETF。"

    tot_n = len(stock_items)
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_mdj_date(base_date_str) or str(base_date_str).strip()[:10]

    def _df_to_rank_recs(df_rank):
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

    updated_stocks = 0
    updated_days_total = 0
    skipped_days_total = 0

    for idx_s, (code, c_name) in enumerate(stock_items, start=1):
        if progress_callback:
            progress_callback(idx_s, tot_n, code, c_name, "檢查交易日序列與既有分點資料...")

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
        latest_trade_idx = len(trade_dates) - 1
        valid_pos = [i for i, d_s in enumerate(trade_dates) if d_s <= b_norm]
        if not valid_pos:
            gc.collect()
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_indices = list(range(anchor_pos, start_pos - 1, -1))
        all_focus_map = storage.load_all_broker_focus_daily_series()

        pending_bundles = []
        wrote_focus_series = False

        for t_idx in target_indices:
            end_d_str = trade_dates[t_idx]
            existing_bundle = storage.load_broker_range_rank(end_d_str)
            has_rank_snapshot = isinstance(existing_bundle, dict) and all(
                isinstance(existing_bundle.get(f"w{w}"), dict) and (existing_bundle[f"w{w}"].get("buy") or existing_bundle[f"w{w}"].get("sell"))
                for w in (1, 10, 20)
            )

            # 富邦分點買賣超交易日況僅限最近交易日之近 20 日（latest_trade_idx - t_idx < 20）
            within_recent_20d = (latest_trade_idx - t_idx) < 20
            if within_recent_20d:
                day_focus_map = all_focus_map.get(end_d_str, {})
                w10_b = day_focus_map.get("w10", {}).get("top5_buy_series") or []
                w10_s = day_focus_map.get("w10", {}).get("top5_sell_series") or []
                w20_b = day_focus_map.get("w20", {}).get("top5_buy_series") or []
                w20_s = day_focus_map.get("w20", {}).get("top5_sell_series") or []
                day_ready = is_broker_daily_data_ready_for_date(end_d_str)

                need_w10 = (not w10_b and not w10_s) or (
                    day_ready and not _series_reaches_target_date(w10_b, end_d_str) and not _series_reaches_target_date(w10_s, end_d_str)
                )
                need_w20 = (not w20_b and not w20_s) or (
                    day_ready and not _series_reaches_target_date(w20_b, end_d_str) and not _series_reaches_target_date(w20_s, end_d_str)
                )
            else:
                need_w10 = False
                need_w20 = False

            if has_rank_snapshot and not need_w10 and not need_w20:
                skipped_days_total += 1
                continue

            if progress_callback:
                progress_callback(idx_s, tot_n, code, c_name, f"擷取 {end_d_str}（1/10/20日分點統計）...")

            win_starts = {
                1: end_d_str,
                10: trade_dates[max(0, t_idx - 10 + 1)],
                20: trade_dates[max(0, t_idx - 20 + 1)],
            }
            rank_dfs = {}
            for w in (1, 10, 20):
                df_b, df_s = fetch_stock_broker_range_ranking(code, win_starts[w], end_d_str)
                if (df_b is None or df_b.empty) and (df_s is None or df_s.empty):
                    time.sleep(0.12)
                    df_b, df_s = fetch_stock_broker_range_ranking(code, win_starts[w], end_d_str)
                rank_dfs[w] = (df_b, df_s)
                time.sleep(0.06)

            day_bundle = dict(existing_bundle) if isinstance(existing_bundle, dict) else {}
            has_any = False
            for w in (1, 10, 20):
                df_b, df_s = rank_dfs.get(w, (None, None))
                b_recs = _df_to_rank_recs(df_b)
                s_recs = _df_to_rank_recs(df_s)
                if b_recs or s_recs:
                    has_any = True
                    lbl = end_d_str if w == 1 else f"{win_starts[w]} ~ {end_d_str}"
                    day_bundle[f"w{w}"] = {
                        "range_label": lbl,
                        "buy": b_recs,
                        "sell": s_recs,
                    }
            if has_any:
                pending_bundles.append((end_d_str, day_bundle))

            win_pairs = []
            if need_w10:
                win_pairs.append((10, win_starts[10]))
            if need_w20:
                win_pairs.append((20, win_starts[20]))

            if win_pairs:
                earliest_w_start = min(s_st for _, s_st in win_pairs)
                broker_df_cache = {}
                for w_num, s_start in win_pairs:
                    df_b, df_s = rank_dfs.get(w_num, (None, None))
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
                                if progress_callback:
                                    progress_callback(idx_s, tot_n, code, c_name, f"補抓 {end_d_str} 分點日況：{b_name}...")
                                df_fresh = fetch_single_broker_daily_series(d_url, earliest_w_start, end_d_str)
                                broker_df_cache[b_name] = df_fresh
                                if df_fresh is not None and not df_fresh.empty:
                                    storage.save_broker_daily_trades(b_name, df_fresh, sync_cloud=False)
                                time.sleep(0.05)
                            df_cached_b = broker_df_cache.get(b_name)
                            if df_cached_b is not None and not df_cached_b.empty:
                                df_win = df_cached_b[
                                    (df_cached_b["日期"] >= s_start) & (df_cached_b["日期"] <= end_d_str)
                                ].copy()
                                if not df_win.empty:
                                    storage.save_broker_focus_daily_series(
                                        focus_date=end_d_str,
                                        window_days=w_num,
                                        side=side_key,
                                        rank_no=rank_idx,
                                        broker_name=b_name,
                                        total_net=tot_net,
                                        df_trades=df_win,
                                        sync_cloud=False
                                    )
                                    wrote_focus_series = True
                broker_df_cache.clear()

        if pending_bundles or wrote_focus_series:
            for end_d_str, day_bundle in pending_bundles:
                storage.save_broker_range_rank(end_d_str, day_bundle, sync_cloud=False)
                updated_days_total += 1
            sync_db_push(code)
            updated_stocks += 1
            time.sleep(0.20)

        del df_k, pending_bundles
        gc.collect()

    summary = (
        f"批次分點增補完成（統計基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"共檢查 {tot_n} 檔個股，實際補齊 {updated_stocks} 檔（新增 {updated_days_total} 筆交易日統計快照），"
        f"略過已存在完整快照 {skipped_days_total} 筆。"
    )
    return summary
## EOF ftch_broker.py
