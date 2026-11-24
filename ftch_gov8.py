"""
ftch_gov8.py - 大盤加權(^TWII)與櫃買(^TWOII)八大官股個股買賣超統計與8行庫日況模組
(自 data_fetcher.py 依邏輯職責拆分，維持既有 HiStock broker8 解析、前景雲端推送與原生字典彙總機制)
版本: 202611242207
"""

import os
import re
import gc
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from storage import (
    StockChipStorage,
    is_tw_index_with_gov_brokers,
    _do_sync_db_push,
)
from ftch_kline_chip import fetch_stock_daily_k

MODULE_NAME = "ftch_gov8"
MODULE_VERSION = "202611242207"

EIGHT_GOV_BROKERS = [
    ("合作金庫", ("合庫", "合作金庫"), "b_heku"),
    ("土地銀行", ("土銀", "土地銀行"), "b_land"),
    ("臺灣銀行", ("台銀", "臺銀", "台灣銀行", "臺灣銀行"), "b_bot"),
    ("臺灣企銀", ("台企", "臺企", "台灣企銀", "臺灣企銀"), "b_tbb"),
    ("彰化銀行", ("彰銀", "彰化銀行"), "b_ccb"),
    ("第一金", ("第一金", "第一"), "b_first"),
    ("兆豐銀", ("兆豐",), "b_mega"),
    ("華南永昌", ("華南", "華南永昌"), "b_hncb"),
]


def _normalize_date_str(raw_str: str) -> str:
    s = str(raw_str or "").strip()
    m = re.search(r'(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if not m:
        return ""
    y = int(m.group(1))
    if y < 1911:
        y += 1911
    return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _fetch_histock_broker8_single_day(pure_code: str, target_date_str: str) -> tuple:
    """
    向 HiStock 擷取當日八大官股買超與賣超排名個股之 8 家官股行庫買賣超（萬元）與合計（萬元）。
    """
    code = str(pure_code or "").strip().upper()
    if not is_tw_index_with_gov_brokers(code):
        return "", []

    is_otc = (code == "^TWOII")
    d_clean = str(target_date_str or "").strip()[:10]
    if is_otc:
        url = f"https://histock.tw/stock/broker8.aspx?no=TWOI&d={d_clean}" if d_clean else "https://histock.tw/stock/broker8.aspx?no=TWOI"
    else:
        url = f"https://histock.tw/stock/broker8.aspx?d={d_clean}" if d_clean else "https://histock.tw/stock/broker8.aspx"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://histock.tw/stock/broker8.aspx"
    }

    def _match_bank_col(h_txt: str) -> str:
        s = str(h_txt or "").strip()
        for _, aliases, col_key in EIGHT_GOV_BROKERS:
            if any(a in s for a in aliases):
                return col_key
        return ""

    def _parse_num(txt: str):
        s = str(txt or "").replace(",", "").replace("+", "").replace("−", "-").replace("－", "-").strip()
        if s in ("", "-", "--", "—", "N/A"):
            return None
        try:
            return float(s)
        except Exception:
            return None

    def _is_pure_number_or_symbol(txt: str) -> bool:
        s = str(txt or "").strip()
        if not s or s in ("★", "☆", "-", "--", "—"):
            return True
        return bool(re.fullmatch(r'[\d,.\-+%]+', s))

    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200 or not res.text:
            return "", []
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception:
        return "", []

    actual_iso_date = d_clean
    now_tw = datetime.utcnow() + timedelta(hours=8)
    ref_year = int(d_clean[:4]) if (d_clean and len(d_clean) >= 4 and d_clean[:4].isdigit()) else now_tw.year
    for hd in soup.find_all(["h2", "h3", "h4"]):
        htxt = re.sub(r"\s+", " ", hd.get_text(" ", strip=True))
        if "八大官股" in htxt and ("買超排名" in htxt or "賣超排名" in htxt):
            m_ymd = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', htxt)
            if m_ymd:
                actual_iso_date = f"{int(m_ymd.group(1)):04d}-{int(m_ymd.group(2)):02d}-{int(m_ymd.group(3)):02d}"
                break
            m_md = re.search(r'\b(\d{1,2})[/-](\d{1,2})\b', htxt)
            if m_md:
                mo_n, da_n = int(m_md.group(1)), int(m_md.group(2))
                yr_n = ref_year - 1 if (d_clean and int(d_clean[5:7]) == 1 and mo_n == 12) else ref_year
                actual_iso_date = f"{yr_n:04d}-{mo_n:02d}-{da_n:02d}"
                break

    stock_records_map = {}
    table_seq = 0

    for tbl in soup.find_all("table"):
        trs = tbl.find_all("tr")
        if not trs:
            continue
        hdr_cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in trs[0].find_all(["th", "td"])]
        bank_cols_found = [c for c in hdr_cells if _match_bank_col(c)]
        if len(bank_cols_found) < 4:
            continue

        side_label = "buy" if table_seq == 0 else "sell"
        prev_hd = tbl.find_previous(["h2", "h3", "h4"])
        if prev_hd:
            p_txt = prev_hd.get_text(" ", strip=True)
            if "賣超排名" in p_txt:
                side_label = "sell"
            elif "買超排名" in p_txt:
                side_label = "buy"
        table_seq += 1

        def _parse_token_row(tokens: list):
            cleaned = [t.strip() for t in tokens if t and t.strip() not in ("★", "☆")]
            if len(cleaned) < 9:
                return None
            name_idx = None
            for idx_t, tok in enumerate(cleaned):
                if not _is_pure_number_or_symbol(tok) and tok not in ("股票", "合計", "合計(萬)"):
                    name_idx = idx_t
                    break
            if name_idx is None:
                return None
            stk_name = cleaned[name_idx].strip()
            num_tokens = [_parse_num(x) for x in cleaned[name_idx + 1:]]
            num_tokens = [x for x in num_tokens if x is not None]
            if len(num_tokens) < 8:
                return None
            b_eight = num_tokens[:8]
            tot_wan = num_tokens[8] if len(num_tokens) >= 9 else sum(b_eight)
            if side_label == "buy" and tot_wan < 0 and sum(b_eight) > 0:
                tot_wan = sum(b_eight)
            elif side_label == "sell" and tot_wan > 0 and sum(b_eight) < 0:
                tot_wan = sum(b_eight)

            return {
                "stock_name": stk_name,
                "source_side": side_label,
                "b_heku": float(b_eight[0]),
                "b_land": float(b_eight[1]),
                "b_bot": float(b_eight[2]),
                "b_tbb": float(b_eight[3]),
                "b_ccb": float(b_eight[4]),
                "b_first": float(b_eight[5]),
                "b_mega": float(b_eight[6]),
                "b_hncb": float(b_eight[7]),
                "total_wan": float(tot_wan),
            }

        ul_list = tbl.find_next_sibling("ul", class_="stock-list") or tbl.find_next_sibling("ul")
        if ul_list:
            for li in ul_list.find_all("li", recursive=False):
                leaf_vals = [
                    re.sub(r"\s+", " ", el.get_text(strip=True))
                    for el in li.find_all(True, recursive=True)
                    if not el.find(True) and el.get_text(strip=True)
                ]
                rec = _parse_token_row(leaf_vals)
                if rec and rec["stock_name"]:
                    stock_records_map[rec["stock_name"]] = rec

        for tr in trs[1:]:
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            rec = _parse_token_row(cells)
            if rec and rec["stock_name"]:
                stock_records_map[rec["stock_name"]] = rec

    if not stock_records_map:
        return "", []

    return actual_iso_date or d_clean, list(stock_records_map.values())


def batch_sync_tw_index_gov_brokers(
    base_date_str: str,
    lookback_days: int = 1,
    progress_callback=None
) -> str:
    """
    【修訂說明 2026-11-24】批次增補加權指數（^TWII）與櫃買指數（^TWOII）八大官股前30買賣超個股資料完成後，
    改以同步前景函式 `_do_sync_db_push(code)` 立即推送至 Google Drive 雲端資料庫。
    """
    n_days = max(1, int(lookback_days or 1))
    b_norm = _normalize_date_str(base_date_str) or str(base_date_str).strip()[:10]
    targets = [("^TWII", "加權指數"), ("^TWOII", "櫃買指數")]
    tot_targets = len(targets)

    total_added_days = 0
    total_skipped_days = 0
    total_stock_rows = 0

    for idx_t, (code, c_name) in enumerate(targets, start=1):
        if progress_callback:
            progress_callback(idx_t, tot_targets, code, c_name, "讀取交易日序列...")

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
            del df_k
            gc.collect()
            continue

        anchor_pos = valid_pos[-1]
        start_pos = max(0, anchor_pos - n_days + 1)
        target_dates = trade_dates[start_pos:anchor_pos + 1]

        exist_df = storage.load_gov_index_stock_daily_range(target_dates[0], target_dates[-1])
        exist_counts = {}
        if exist_df is not None and not exist_df.empty:
            for d_val in exist_df["trade_date"].tolist():
                dk = str(d_val)[:10]
                exist_counts[dk] = exist_counts.get(dk, 0) + 1

        wrote_any = False
        for d_idx, d_str in enumerate(reversed(target_dates), start=1):
            if exist_counts.get(d_str, 0) >= 50:
                total_skipped_days += 1
                continue
            if progress_callback:
                progress_callback(
                    idx_t, tot_targets, code, c_name,
                    f"擷取 {d_str} 八大官股前30買賣超個股 ({d_idx}/{len(target_dates)})..."
                )
            act_d, stk_rows = _fetch_histock_broker8_single_day(code, d_str)
            if stk_rows:
                save_d = act_d or d_str
                storage.save_gov_index_stock_daily(save_d, stk_rows, sync_cloud=False)
                wrote_any = True
                total_added_days += 1
                total_stock_rows += len(stk_rows)
            time.sleep(0.15)

        if wrote_any:
            if progress_callback:
                progress_callback(idx_t, tot_targets, code, c_name, "正在同步推送八大官股資料庫至雲端...")
            _do_sync_db_push(code)

        del df_k, exist_df
        gc.collect()

    return (
        f"八大官股交易前30個股增補完成（基準日 {b_norm} 往前 {n_days} 個交易日）："
        f"新增 {total_added_days} 個交易日（共 {total_stock_rows} 筆個股八大官股明細），"
        f"略過已完整存在 {total_skipped_days} 個交易日（已同步至雲端）。"
    )


def fetch_tw_index_gov_broker_bundle(
    pure_code: str,
    trade_dates_tuple: tuple,
    target_end_idx: int,
    include_60d: bool = False
) -> tuple:
    code = str(pure_code or "").strip().upper()
    if not is_tw_index_with_gov_brokers(code) or not trade_dates_tuple:
        return {}, {}

    n_dates = len(trade_dates_tuple)
    safe_idx = min(max(0, int(target_end_idx)), n_dates - 1)
    end_date_str = str(trade_dates_tuple[safe_idx])[:10]
    storage = StockChipStorage(code)

    def _query_gov_rows(s_dt: str, e_dt: str) -> list:
        if hasattr(storage, "load_gov_index_stock_daily_range"):
            df_q = storage.load_gov_index_stock_daily_range(s_dt, e_dt)
            if df_q is not None and not df_q.empty:
                return df_q.to_dict(orient="records")
            return []
        import sqlite3
        if not os.path.exists(storage.db_path):
            return []
        try:
            with sqlite3.connect(storage.db_path) as conn:
                cur = conn.execute('''
                    SELECT trade_date, stock_name, source_side,
                           b_heku, b_land, b_bot, b_tbb, b_ccb, b_first, b_mega, b_hncb, total_wan
                    FROM gov_index_stock_daily
                    WHERE trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date ASC, stock_name ASC
                ''', (s_dt, e_dt))
                cols_q = [d[0] for d in cur.description]
                return [dict(zip(cols_q, row)) for row in cur.fetchall()]
        except Exception:
            return []

    chk_today_rows = _query_gov_rows(end_date_str, end_date_str)
    if not chk_today_rows:
        act_d, stk_rows = _fetch_histock_broker8_single_day(code, end_date_str)
        if stk_rows and hasattr(storage, "save_gov_index_stock_daily"):
            storage.save_gov_index_stock_daily(act_d or end_date_str, stk_rows, sync_cloud=True)

    earliest_d = str(trade_dates_tuple[max(0, safe_idx - 60 + 1)])[:10]
    all_rows = _query_gov_rows(earliest_d, end_date_str)
    if not all_rows:
        return {}, {}

    avail_dates = sorted({str(r.get("trade_date", ""))[:10] for r in all_rows if r.get("trade_date")})
    if not avail_dates:
        return {}, {}
    valid_gov_dates = [d for d in avail_dates if d <= end_date_str]
    anchor_gov_date = valid_gov_dates[-1] if valid_gov_dates else avail_dates[-1]

    windows = (1, 10, 20, 60)
    day_bundle = {}

    for w in windows:
        s_idx = max(0, safe_idx - w + 1)
        s_date_str = str(trade_dates_tuple[s_idx])[:10]
        sub_rows = [
            r for r in all_rows
            if s_date_str <= str(r.get("trade_date", ""))[:10] <= anchor_gov_date
        ]
        if not sub_rows and w == 1:
            sub_rows = [
                r for r in all_rows
                if str(r.get("trade_date", ""))[:10] == anchor_gov_date
            ]
        if not sub_rows:
            continue

        agg_map = {}
        daily_by_stock = {}
        min_d_found = "9999-12-31"
        max_d_found = "0000-01-01"

        for r in sub_rows:
            td = str(r.get("trade_date", ""))[:10]
            sn = str(r.get("stock_name", "") or "").strip()
            if not td or not sn:
                continue
            if td < min_d_found:
                min_d_found = td
            if td > max_d_found:
                max_d_found = td

            tot_v = float(r.get("total_wan", 0.0) or 0.0)
            entry = agg_map.get(sn)
            if entry is None:
                entry = {"stock_name": sn, "buy_sum": 0.0, "sell_sum": 0.0, "total_wan": 0.0}
                agg_map[sn] = entry
            entry["total_wan"] += tot_v
            if tot_v > 0:
                entry["buy_sum"] += tot_v
            elif tot_v < 0:
                entry["sell_sum"] += abs(tot_v)

            stk_day_map = daily_by_stock.setdefault(sn, {})
            stk_day_map[td] = {
                "b_heku": float(r.get("b_heku", 0.0) or 0.0),
                "b_land": float(r.get("b_land", 0.0) or 0.0),
                "b_bot": float(r.get("b_bot", 0.0) or 0.0),
                "b_tbb": float(r.get("b_tbb", 0.0) or 0.0),
                "b_ccb": float(r.get("b_ccb", 0.0) or 0.0),
                "b_first": float(r.get("b_first", 0.0) or 0.0),
                "b_mega": float(r.get("b_mega", 0.0) or 0.0),
                "b_hncb": float(r.get("b_hncb", 0.0) or 0.0),
            }

        if not agg_map:
            continue

        tot_abs = sum(abs(v["total_wan"]) for v in agg_map.values()) or 1.0
        buy_items = sorted(
            [v for v in agg_map.values() if v["total_wan"] > 0],
            key=lambda x: x["total_wan"],
            reverse=True
        )[:50]
        sell_items = sorted(
            [v for v in agg_map.values() if v["total_wan"] < 0],
            key=lambda x: x["total_wan"]
        )[:50]

        buy_recs = []
        for item in buy_items:
            nv = int(round(item["total_wan"]))
            b_v = int(round(item["buy_sum"] if item["buy_sum"] > 0 else max(0, nv)))
            s_v = int(round(item["sell_sum"]))
            buy_recs.append({
                "name": item["stock_name"],
                "sys": "八大官股",
                "buy": b_v,
                "sell": s_v,
                "net": nv,
                "ratio": f"{(abs(nv) / tot_abs * 100.0):.1f}%",
            })

        sell_recs = []
        for item in sell_items:
            nv = int(round(item["total_wan"]))
            b_v = int(round(item["buy_sum"]))
            s_v = int(round(item["sell_sum"] if item["sell_sum"] > 0 else abs(nv)))
            sell_recs.append({
                "name": item["stock_name"],
                "sys": "八大官股",
                "buy": b_v,
                "sell": s_v,
                "net": nv,
                "ratio": f"{(abs(nv) / tot_abs * 100.0):.1f}%",
            })

        stock_8bank_map = {}
        if w in (10, 20, 60):
            cand_stocks = []
            seen_stk = set()
            for rec in (buy_recs + sell_recs):
                sn = rec["name"]
                if sn and sn not in seen_stk:
                    seen_stk.add(sn)
                    cand_stocks.append(sn)

            for sn in cand_stocks:
                stk_day_map = daily_by_stock.get(sn)
                if not stk_day_map:
                    continue
                d_list = sorted(stk_day_map.keys())
                banks_list = []
                for b_label, _, col_k in EIGHT_GOV_BROKERS:
                    vals_list = [int(round(stk_day_map[dt].get(col_k, 0.0))) for dt in d_list]
                    banks_list.append({
                        "bank": b_label,
                        "total_net": int(sum(vals_list)),
                        "dates": d_list,
                        "nets": vals_list
                    })
                stock_8bank_map[sn] = banks_list

        lbl = max_d_found if w == 1 else f"{min_d_found} ~ {max_d_found}"
        w_dict = {
            "range_label": lbl,
            "buy": buy_recs,
            "sell": sell_recs,
        }
        if stock_8bank_map:
            w_dict["stock_8bank_series"] = stock_8bank_map
        day_bundle[f"w{w}"] = w_dict

    return day_bundle, {}
## EOF ftch_gov8.py
