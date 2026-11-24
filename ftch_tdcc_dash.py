"""
ftch_tdcc_dash.py - 集保大戶股權分散表與操作儀錶板報價擷取模組
(自 data_fetcher.py 依邏輯職責拆分，維持既有集保 qryStock 動態 Token 多週查詢與 id=1-5 開放資料批次更新機制)
版本: 202611242207
"""

import os
import io
import glob
import time
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

from storage import (
    StockChipStorage,
    load_stock_history,
    get_stock_chinese_name,
    is_tw_stock_or_etf,
)

MODULE_NAME = "ftch_tdcc_dash"
MODULE_VERSION = "202611242207"


def fetch_tdcc_holding_history(pure_code: str, weeks: int = 15) -> list:
    code = str(pure_code or "").strip().upper()
    if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
        return []

    url_tdcc = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": url_tdcc,
        "Origin": "https://www.tdcc.com.tw",
    }

    def _extract_hidden_inputs(soup_obj: BeautifulSoup) -> dict:
        fields = {}
        for inp in soup_obj.find_all("input"):
            name = inp.get("name")
            if name:
                fields[name] = inp.get("value", "")
        return fields

    existing_weeks_with_shares = set()
    try:
        storage = StockChipStorage(code)
        df_exist = storage.load_holding_df()
        if df_exist is not None and not df_exist.empty and "date" in df_exist.columns:
            if "shares" in df_exist.columns:
                valid_sh = df_exist[pd.to_numeric(df_exist["shares"], errors="coerce").fillna(0) > 0]
                if not valid_sh.empty:
                    existing_weeks_with_shares = set(pd.to_datetime(valid_sh["date"]).dt.strftime("%Y%m%d").tolist())
            else:
                existing_weeks_with_shares = set(pd.to_datetime(df_exist["date"]).dt.strftime("%Y%m%d").tolist())
    except Exception:
        pass

    records_h = []
    try:
        sess = requests.Session()
        res_get = sess.get(url_tdcc, headers=headers, timeout=8)
        if res_get.status_code != 200:
            return []

        soup_get = BeautifulSoup(res_get.text, "html.parser")
        current_payload = _extract_hidden_inputs(soup_get)

        avail_dates = []
        for opt in soup_get.find_all("option"):
            val = str(opt.get("value", "")).strip()
            if val.isdigit() and len(val) == 8:
                avail_dates.append(val)

        if not avail_dates:
            return []

        max_w = max(1, int(weeks or 15))
        target_dates = avail_dates[:max_w]
        missing_dates = [d for d in target_dates if d not in existing_weeks_with_shares]
        if not missing_dates:
            return []

        for d_str in missing_dates:
            if not current_payload.get("SYNCHRONIZER_TOKEN"):
                try:
                    res_reget = sess.get(url_tdcc, headers=headers, timeout=8)
                    if res_reget.status_code == 200:
                        current_payload = _extract_hidden_inputs(BeautifulSoup(res_reget.text, "html.parser"))
                except Exception:
                    current_payload = {}

            payload = current_payload.copy()
            payload.update({
                "scaDate": d_str,
                "sqlMethod": "StockNo",
                "stockNo": code,
                "stockName": "",
                "sub": "查詢"
            })
            try:
                res_post = sess.post(url_tdcc, data=payload, headers=headers, timeout=8)
                if res_post.status_code != 200:
                    current_payload = {}
                    continue

                soup_post = BeautifulSoup(res_post.text, "html.parser")
                next_inputs = _extract_hidden_inputs(soup_post)
                current_payload = next_inputs if next_inputs.get("SYNCHRONIZER_TOKEN") else {}

                iso_d = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                for tbl in soup_post.find_all("table"):
                    if "1,000,001" not in tbl.get_text():
                        continue
                    for tr in tbl.find_all("tr"):
                        cols = [td.get_text(strip=True).replace(",", "") for td in tr.find_all("td")]
                        if len(cols) >= 5 and cols[0].isdigit():
                            lvl = int(cols[0])
                            if 1 <= lvl <= 15:
                                try:
                                    holders_v = int(float(cols[2].strip() or 0))
                                    shares_v = int(float(cols[3].strip() or 0))
                                    pct = float(cols[4].replace("%", "").strip())
                                    records_h.append((iso_d, lvl, holders_v, shares_v, pct))
                                except Exception:
                                    continue
                    break
            except Exception:
                current_payload = {}
            time.sleep(0.25)
    except Exception:
        pass

    return records_h


def fetch_tdcc_holding_data(pure_code: str) -> list:
    hist_recs = fetch_tdcc_holding_history(pure_code, weeks=15)
    if not hist_recs:
        return []
    return [r for r in hist_recs if len(r) >= 5 and 1 <= int(r[1]) <= 15]


def batch_fetch_and_save_latest_tdcc_holding(target_codes: list = None) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    tdcc_urls = [
        "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
        "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5",
    ]

    candidate_set = set()
    if target_codes:
        for c in target_codes:
            cu = str(c or "").strip().upper()
            if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                candidate_set.add(cu)
    else:
        for item in load_stock_history():
            cu = str(item.get("code", "")).strip().upper()
            if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                candidate_set.add(cu)
        for p in glob.glob(os.path.join(".", "data_*.db")):
            cu = os.path.basename(p).replace("data_", "").replace(".db", "").strip().upper()
            if cu and not cu.startswith("^") and is_tw_stock_or_etf(cu):
                candidate_set.add(cu)

    if not candidate_set:
        return {"ok": False, "msg": "目前無已建立之台股個股/ETF 資料庫可更新。"}

    df_od = None
    for u in tdcc_urls:
        try:
            res = requests.get(u, headers=headers, timeout=12)
            if res.status_code == 200 and len(res.content) > 500:
                df_od = pd.read_csv(io.BytesIO(res.content), dtype=str)
                if df_od is not None and not df_od.empty:
                    break
        except Exception:
            continue

    if df_od is None or df_od.empty:
        return {"ok": False, "msg": "集保開放資料網（id=1-5）暫時無回應，請稍後再試。"}

    cols = list(df_od.columns)
    date_col = next((c for c in cols if "日期" in c or "Date" in c), cols[0])
    code_col = next((c for c in cols if "代號" in c or "Code" in c), cols[1])
    lvl_col = next((c for c in cols if "持股分級" in c or "Level" in c), cols[2])
    holders_col = next((c for c in cols if "人數" in c or "Holder" in c), cols[3] if len(cols) > 3 else cols[2])
    shares_col = next((c for c in cols if "股數" in c or "Share" in c), cols[4] if len(cols) > 4 else cols[3])
    pct_col = next((c for c in cols if "占集保庫存數比例" in c or "比例" in c or "Percent" in c), cols[-1])

    df_od[code_col] = df_od[code_col].astype(str).str.strip().str.upper()
    df_sub = df_od[df_od[code_col].isin(candidate_set)].copy()
    if df_sub.empty:
        return {"ok": False, "msg": "集保最新開放資料中未比對到已收錄個股。"}

    grouped_records = {}
    latest_date_str = ""
    for _, row in df_sub.iterrows():
        c_code = str(row[code_col]).strip().upper()
        raw_d = str(row[date_col]).strip().replace("-", "").replace("/", "")
        if len(raw_d) != 8 or not raw_d.isdigit():
            continue
        iso_d = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:8]}"
        if iso_d > latest_date_str:
            latest_date_str = iso_d
        try:
            lvl = int(float(str(row[lvl_col]).strip()))
            if not (1 <= lvl <= 15):
                continue
            holders_v = int(float(str(row[holders_col]).replace(",", "").strip() or 0))
            shares_v = int(float(str(row[shares_col]).replace(",", "").strip() or 0))
            pct = float(str(row[pct_col]).replace(",", "").replace("%", "").strip())
        except Exception:
            continue
        grouped_records.setdefault(c_code, []).append((iso_d, lvl, holders_v, shares_v, pct))

    updated_stocks = 0
    for c_code, recs in grouped_records.items():
        if recs:
            try:
                st_db = StockChipStorage(c_code)
                st_db.save_holding_data(recs)
                updated_stocks += 1
            except Exception:
                continue

    return {
        "ok": updated_stocks > 0,
        "date": latest_date_str,
        "updated_count": updated_stocks,
        "msg": f"已自集保開放資料網補齊 {latest_date_str} 最新週集保分級（共 {updated_stocks} 檔個股/ETF）。"
    }


def fetch_dashboard_watchlist_rows(history_list: list) -> list:
    if not history_list:
        return []

    from ftch_kline_chip import fetch_stock_daily_k

    rows = []
    for item in history_list:
        code = str(item.get("code", "")).strip().upper()
        if not code or code.startswith("^") or not is_tw_stock_or_etf(code):
            continue

        c_name = str(item.get("name", "")).strip()
        if not c_name or c_name == code:
            c_name = get_stock_chinese_name(code)

        storage = StockChipStorage(code)
        df_k = storage.load_daily_k_df()

        market_lbl = "上市"
        live_price = None
        live_vol_sheets = None
        live_date_str = None
        found_yf = False
        for suffix, m_lbl in ((".TW", "上市"), (".TWO", "上櫃")):
            try:
                t_obj = yf.Ticker(f"{code}{suffix}")
                df_1d = t_obj.history(period="5d")
                if df_1d is not None and not df_1d.empty:
                    if df_1d.index.tz is not None:
                        df_1d.index = df_1d.index.tz_localize(None)
                    df_1d = df_1d.dropna(subset=["Close"])
                    if not df_1d.empty:
                        found_yf = True
                        market_lbl = m_lbl
                        last_row = df_1d.iloc[-1]
                        live_price = float(last_row["Close"])
                        live_vol_sheets = float(last_row.get("Volume", 0) or 0) / 1000.0
                        live_date_str = df_1d.index[-1].strftime("%Y-%m-%d")

                        if not df_k.empty:
                            df_k = pd.concat([df_k, df_1d[["Open", "High", "Low", "Close", "Volume"]]])
                            df_k = df_k[~df_k.index.duplicated(keep="last")].sort_index()
                        else:
                            df_k = df_1d[["Open", "High", "Low", "Close", "Volume"]].sort_index()
                        break
            except Exception:
                continue

        if not found_yf and df_k.empty:
            k_res = fetch_stock_daily_k(code, period="3mo", force_refresh=False)
            if k_res and k_res[0] is not None and not k_res[0].empty:
                df_k = k_res[0]
                if str(k_res[1]).endswith(".TWO"):
                    market_lbl = "上櫃"

        if df_k.empty:
            rows.append({
                "code": code,
                "name": c_name,
                "market": market_lbl,
                "price": None,
                "vol_sheets": None,
                "ma5": None,
                "ma20": None,
                "trade_date": "-"
            })
            continue

        closes = df_k["Close"].dropna()
        last_close = live_price if live_price is not None else float(closes.iloc[-1])
        last_vol = live_vol_sheets if live_vol_sheets is not None else (float(df_k["Volume"].iloc[-1]) / 1000.0)
        last_dt = live_date_str if live_date_str else df_k.index[-1].strftime("%Y-%m-%d")
        ma5_val = float(closes.tail(5).mean()) if len(closes) >= 5 else None
        ma20_val = float(closes.tail(20).mean()) if len(closes) >= 20 else None

        rows.append({
            "code": code,
            "name": c_name,
            "market": market_lbl,
            "price": last_close,
            "vol_sheets": last_vol,
            "ma5": ma5_val,
            "ma20": ma20_val,
            "trade_date": last_dt
        })

    return rows
## EOF ftch_tdcc_dash.py
