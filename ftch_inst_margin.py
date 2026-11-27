"""
ftch_inst_margin.py - 三大法人與個股/大盤全市場資券籌碼爬蟲模組
(自 ftch_kline_chip.py 依邏輯職責拆分，維持既有證交所 T86、櫃買 3itrade、FinMind 法人與上市/上櫃全市場資券主資料源)
版本: 202611270925
"""

import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

MODULE_NAME = "ftch_inst_margin"
MODULE_VERSION = "202611270925"

FINMIND_TOKEN = ""


def fetch_market_index_institutional_data(
    pure_code: str,
    df_dates: pd.DatetimeIndex,
    explicit_missing_dates: list = None
) -> list:
    """
    【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
    1. 修改目的：擷取上市加權指數（^TWII）與櫃買指數（^TWOII）全市場三大法人每日買賣超金額，
       統一換算為「億元」並回傳 `[(date_str, foreign_yi, trust_yi, dealer_yi), ...]` 寫入 `institutional_investors`。
       - 上市（^TWII）：主資料源為證交所 `BFI82U`（`https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&dayDate=YYYYMMDD`），
         解析自營商（自行買賣＋避險合計，或直接取自營商合計列）、投信、外資及陸資（不含外資自營商＋外資自營商合計，或直接取外資及陸資合計列），單位由元除以 `1e8` 換算為億元。
       - 上櫃（^TWOII）：主資料源為櫃買中心三大法人買賣金額統計 `3itrade_hedge_result.php`（`se=EW&t=D&d=YYY/MM/DD`），
         解析自營商合計、投信、外資及陸資合計買賣差額，單位由元除以 `1e8` 換算為億元；若無則以 FinMind `TaiwanStockTotalInstitutionalInvestors` 備援。
    2. 防呆防錯原因：週末自動跳過；單日連線設短逾時防卡死，避免影響前端載入流暢度。
    """
    code = str(pure_code or "").strip().upper()
    if code not in ("^TWII", "^TWOII"):
        return []

    sample_dates = list(explicit_missing_dates) if explicit_missing_dates is not None else list(df_dates[-5:])
    if not sample_dates:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://www.twse.com.tw/" if code == "^TWII" else "https://www.tpex.org.tw/"
    }

    def _to_yi(val_raw, scale_div: float = 1e8) -> float:
        s = str(val_raw or "").replace(",", "").replace("+", "").replace("−", "-").replace("－", "-").strip()
        if s in ("", "-", "--", "—", "N/A"):
            return 0.0
        try:
            return float(s) / scale_div
        except Exception:
            return 0.0

    records = []
    missing_dates = []

    for dt in sample_dates:
        if dt.weekday() >= 5:
            continue
        date_str = dt.strftime("%Y-%m-%d")
        found = False

        if code == "^TWII":
            d_compact = dt.strftime("%Y%m%d")
            url_twse = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&dayDate={d_compact}"
            try:
                res = requests.get(url_twse, headers=headers, timeout=2.5)
                if res.status_code == 200:
                    js = res.json()
                    if js.get("stat") == "OK" and js.get("data"):
                        f_yi, t_yi, d_yi = 0.0, 0.0, 0.0
                        has_f, has_t, has_d = False, False, False
                        for row in js["data"]:
                            if len(row) < 4:
                                continue
                            item_name = str(row[0]).strip()
                            diff_yi = _to_yi(row[3], 1e8)
                            if "外資及陸資" in item_name:
                                if "不含" in item_name or "自營商" in item_name:
                                    f_yi += diff_yi
                                    has_f = True
                                elif not has_f:
                                    f_yi = diff_yi
                                    has_f = True
                            elif "投信" in item_name:
                                t_yi = diff_yi
                                has_t = True
                            elif "自營商" in item_name and "外資" not in item_name:
                                if "自行" in item_name or "避險" in item_name:
                                    d_yi += diff_yi
                                    has_d = True
                                elif not has_d:
                                    d_yi = diff_yi
                                    has_d = True
                        if has_f or has_t or has_d:
                            records.append((date_str, round(f_yi, 4), round(t_yi, 4), round(d_yi, 4)))
                            found = True
            except Exception:
                pass
        else:
            roc_d = f"{dt.year - 1911}/{dt.strftime('%m/%d')}"
            url_tpex = f"https://www.tpex.org.tw/web/stock/3insti/3insti_summary/3itrdsum_result.php?l=zh-tw&t=D&d={roc_d}"
            try:
                res_t = requests.get(url_tpex, headers=headers, timeout=2.5)
                if res_t.status_code == 200:
                    js_t = res_t.json()
                    rows = js_t.get("aaData") or js_t.get("tables", [{}])[0].get("data", [])
                    if rows:
                        f_yi, t_yi, d_yi = 0.0, 0.0, 0.0
                        has_f, has_t, has_d = False, False, False
                        for row in rows:
                            if len(row) < 4:
                                continue
                            item_name = re.sub(r"<[^>]+>", "", str(row[0])).strip()
                            diff_yi = _to_yi(row[3], 1e8)
                            if "外資及陸資" in item_name and "合計" in item_name:
                                f_yi = diff_yi
                                has_f = True
                            elif "外資及陸資" in item_name and not has_f:
                                f_yi += diff_yi
                                has_f = True
                            elif "投信" in item_name:
                                t_yi = diff_yi
                                has_t = True
                            elif "自營商" in item_name and "外資" not in item_name and "合計" in item_name:
                                d_yi = diff_yi
                                has_d = True
                            elif "自營商" in item_name and "外資" not in item_name and not has_d:
                                d_yi += diff_yi
                                has_d = True
                        if has_f or has_t or has_d:
                            records.append((date_str, round(f_yi, 4), round(t_yi, 4), round(d_yi, 4)))
                            found = True
            except Exception:
                pass

        if not found:
            missing_dates.append(date_str)
        time.sleep(0.02)

    # 備援：僅針對上市加權指數（^TWII）尚缺日期查詢 FinMind TaiwanStockTotalInstitutionalInvestors
    if missing_dates and code == "^TWII":
        try:
            query_start = min(missing_dates)
            url_fm = "https://api.finmindtrade.com/api/v4/data"
            p_fm = {
                "dataset": "TaiwanStockTotalInstitutionalInvestors",
                "start_date": query_start,
                "token": FINMIND_TOKEN
            }
            res_fm = requests.get(url_fm, params=p_fm, headers=headers, timeout=4)
            if res_fm.status_code == 200:
                fm_data = res_fm.json().get("data", [])
                if fm_data:
                    df_fm = pd.DataFrame(fm_data)
                    for d_str, g in df_fm.groupby("date"):
                        if d_str in missing_dates and not any(r[0] == d_str for r in records):
                            f_yi, t_yi, d_yi = 0.0, 0.0, 0.0
                            for _, r in g.iterrows():
                                name = str(r.get("name", ""))
                                diff_yi = (float(r.get("buy", 0) or 0) - float(r.get("sell", 0) or 0)) / 1e8
                                if "Foreign" in name or "外資" in name:
                                    f_yi += diff_yi
                                elif "Investment_Trust" in name or "投信" in name:
                                    t_yi += diff_yi
                                elif "Dealer" in name or "自營" in name:
                                    d_yi += diff_yi
                            records.append((d_str, round(f_yi, 4), round(t_yi, 4), round(d_yi, 4)))
        except Exception:
            pass

    records.sort(key=lambda x: x[0])
    return records


def fetch_institutional_investors(
    pure_code: str,
    df_dates: pd.DatetimeIndex,
    start_date_exclusive: str = None,
    explicit_missing_dates: list = None,
    full_ticker: str = None
) -> list:
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：自 `ftch_kline_chip.py` 拆出三大法人買賣超爬蟲函式至獨立模組 `ftch_inst_margin.py`。
    2. 防呆防錯原因：完整保留證交所 T86（`selectType=ALLBUT0999`）、櫃買中心 `3itrade_hedge_result.php` 與 FinMind 備援邏輯，資料源與欄位索引 100% 不變。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.tpex.org.tw/"
    }
    if explicit_missing_dates is not None:
        sample_dates = list(explicit_missing_dates)
    elif start_date_exclusive:
        sample_dates = [d for d in df_dates if d.strftime('%Y-%m-%d') > start_date_exclusive]
    else:
        sample_dates = list(df_dates[-5:])

    if not sample_dates:
        return []

    records = []
    missing_dates = []

    def clean_val(v):
        try:
            return float(str(v).replace(",", "").strip()) / 1000.0
        except Exception:
            return 0.0

    is_tpex_only = bool(full_ticker and full_ticker.endswith(".TWO"))
    is_twse_only = bool(full_ticker and full_ticker.endswith(".TW"))

    for dt in sample_dates:
        if dt.weekday() >= 5:
            continue
        date_twse = dt.strftime('%Y%m%d')
        date_str = dt.strftime('%Y-%m-%d')
        found = False

        if not is_tpex_only:
            url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_twse}&selectType=ALLBUT0999&response=json"
            try:
                res = requests.get(url_twse, headers=headers, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("stat") == "OK" and "data" in data:
                        for row in data["data"]:
                            if str(row[0]).strip().upper() == pure_code:
                                f_net = clean_val(row[4])
                                t_net = clean_val(row[10])
                                d_net = clean_val(row[11])
                                records.append((date_str, f_net, t_net, d_net))
                                found = True
                                break
                if found:
                    continue
            except Exception:
                pass

        if not found and not is_twse_only:
            try:
                year_tw = dt.year - 1911
                date_tpex = f"{year_tw}/{dt.strftime('%m/%d')}"
                url_tpex = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_tpex}"
                res = requests.get(url_tpex, headers=headers, timeout=1.5)
                if res.status_code == 200:
                    data = res.json()
                    rows = data.get("aaData") or data.get("tables", [{}])[0].get("data", [])
                    if rows:
                        for row in rows:
                            if str(row[0]).strip().upper() == pure_code:
                                num_cols = len(row)
                                f_net = clean_val(row[10]) if num_cols > 10 else clean_val(row[7])
                                t_net = clean_val(row[13]) if num_cols > 13 else clean_val(row[8])
                                if num_cols > 22:
                                    d_net = clean_val(row[22])
                                elif num_cols > 19:
                                    d_net = clean_val(row[16]) + clean_val(row[19])
                                else:
                                    d_net = clean_val(row[9])
                                records.append((date_str, f_net, t_net, d_net))
                                found = True
                                break
            except Exception:
                pass

        if not found:
            missing_dates.append(date_str)
        time.sleep(0.01)

    if missing_dates:
        try:
            query_start = min(missing_dates)
            url_fm = "https://api.finmindtrade.com/api/v4/data"
            p_fm = {
                "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id": pure_code,
                "start_date": query_start,
                "token": FINMIND_TOKEN
            }
            res_fm = requests.get(url_fm, params=p_fm, headers=headers, timeout=2.5)
            if res_fm.status_code == 200:
                fm_data = res_fm.json().get("data", [])
                if fm_data:
                    df_fm = pd.DataFrame(fm_data)
                    grouped = df_fm.groupby("date")
                    for d_str, g in grouped:
                        if d_str in missing_dates and not any(r[0] == d_str for r in records):
                            f_net, t_net, d_net = 0.0, 0.0, 0.0
                            for _, r in g.iterrows():
                                name = str(r.get("name", ""))
                                diff_val = (float(r.get("buy", 0) or 0) - float(r.get("sell", 0) or 0)) / 1000.0
                                if "Foreign_Investor" in name or "外資" in name:
                                    f_net += diff_val
                                elif "Investment_Trust" in name or "投信" in name:
                                    t_net += diff_val
                                elif "Dealer" in name or "自營商" in name:
                                    d_net += diff_val
                            records.append((d_str, f_net, t_net, d_net))
        except Exception:
            pass

    records.sort(key=lambda x: x[0])
    return records


def fetch_twse_total_margin_data(df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    """
    【修訂說明 2026-11-20】擷取上市大盤（^TWII）全市場每日融資/融券增減張數與餘額，以及上市融資金額增減與餘額（換算為億元）。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    if start_date_exclusive:
        query_start = (pd.to_datetime(start_date_exclusive) + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        query_start = (
            (df_dates[0] - timedelta(days=5)).strftime('%Y-%m-%d')
            if len(df_dates) > 0
            else (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        )

    rec_map = {}
    try:
        url_fm = "https://api.finmindtrade.com/api/v4/data"
        p_fm = {
            "dataset": "TaiwanStockTotalMarginPurchaseShortSale",
            "start_date": query_start,
            "token": FINMIND_TOKEN
        }
        res_fm = requests.get(url_fm, params=p_fm, headers=headers, timeout=6)
        if res_fm.status_code == 200:
            data_fm = res_fm.json().get("data", [])
            if data_fm:
                df_raw = pd.DataFrame(data_fm)
                piv_today = df_raw.pivot_table(index="date", columns="name", values="TodayBalance", aggfunc="last")
                piv_yes = df_raw.pivot_table(index="date", columns="name", values="YesBalance", aggfunc="last")
                for d_str in piv_today.index:
                    m_today = float(piv_today.loc[d_str, "MarginPurchase"]) if "MarginPurchase" in piv_today.columns and pd.notna(piv_today.loc[d_str, "MarginPurchase"]) else 0.0
                    m_yes = float(piv_yes.loc[d_str, "MarginPurchase"]) if "MarginPurchase" in piv_yes.columns and pd.notna(piv_yes.loc[d_str, "MarginPurchase"]) else m_today
                    s_today = float(piv_today.loc[d_str, "ShortSale"]) if "ShortSale" in piv_today.columns and pd.notna(piv_today.loc[d_str, "ShortSale"]) else 0.0
                    s_yes = float(piv_yes.loc[d_str, "ShortSale"]) if "ShortSale" in piv_yes.columns and pd.notna(piv_yes.loc[d_str, "ShortSale"]) else s_today
                    mm_today = (float(piv_today.loc[d_str, "MarginPurchaseMoney"]) / 1e8) if "MarginPurchaseMoney" in piv_today.columns and pd.notna(piv_today.loc[d_str, "MarginPurchaseMoney"]) else 0.0
                    mm_yes = (float(piv_yes.loc[d_str, "MarginPurchaseMoney"]) / 1e8) if "MarginPurchaseMoney" in piv_yes.columns and pd.notna(piv_yes.loc[d_str, "MarginPurchaseMoney"]) else mm_today
                    rec_map[str(d_str)] = (
                        str(d_str),
                        m_today - m_yes,
                        s_today - s_yes,
                        m_today,
                        s_today,
                        mm_today - mm_yes,
                        mm_today
                    )
    except Exception:
        pass

    if len(df_dates) > 0:
        latest_d_str = df_dates[-1].strftime('%Y-%m-%d')
        if latest_d_str not in rec_map:
            try:
                d_compact = df_dates[-1].strftime('%Y%m%d')
                url_twse_ms = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d_compact}&selectType=MS&response=json"
                res_t = requests.get(url_twse_ms, headers=headers, timeout=4)
                if res_t.status_code == 200:
                    js_t = res_t.json()
                    if js_t.get("stat") == "OK":
                        m_yes, m_today, s_yes, s_today = 0.0, 0.0, 0.0, 0.0
                        mm_yes_yi, mm_today_yi = 0.0, 0.0
                        for tbl in js_t.get("tables", []):
                            for row in tbl.get("data", []):
                                if len(row) >= 6:
                                    item_name = str(row[0]).strip()
                                    yes_v = float(str(row[4]).replace(",", "").strip() or 0)
                                    tod_v = float(str(row[5]).replace(",", "").strip() or 0)
                                    if "融資(交易單位)" in item_name:
                                        m_yes, m_today = yes_v, tod_v
                                    elif "融券(交易單位)" in item_name:
                                        s_yes, s_today = yes_v, tod_v
                                    elif "融資金額(千元)" in item_name:
                                        mm_yes_yi, mm_today_yi = yes_v / 1e5, tod_v / 1e5
                        if m_today > 0 or s_today > 0:
                            rec_map[latest_d_str] = (
                                latest_d_str,
                                m_today - m_yes,
                                s_today - s_yes,
                                m_today,
                                s_today,
                                mm_today_yi - mm_yes_yi,
                                mm_today_yi
                            )
            except Exception:
                pass

    return [rec_map[k] for k in sorted(rec_map.keys())]


def fetch_tpex_total_margin_data(df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    """
    【修訂說明 2026-11-20】擷取櫃買指數（^TWOII）全市場彙總信用交易統計（主資料源：嗨投資 https://histock.tw/stock/three.aspx?m=mg&no=TWOI）。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://histock.tw/"
    }
    url_otc = "https://histock.tw/stock/three.aspx?m=mg&no=TWOI"

    def parse_num(txt):
        s = str(txt or "").replace(",", "").replace("+", "").strip()
        if s in ("", "-", "--", "—", "N/A"):
            return 0.0
        try:
            return float(s)
        except Exception:
            return 0.0

    md_to_iso = {}
    valid_iso_set = set()
    for d in df_dates:
        iso_s = d.strftime("%Y-%m-%d")
        valid_iso_set.add(iso_s)
        md_to_iso[d.strftime("%m/%d")] = iso_s

    rec_map = {}
    try:
        res = requests.get(url_otc, headers=headers, timeout=8)
        if res.status_code != 200 or not res.text:
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        for tr in soup.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if len(cells) < 5:
                continue
            raw_d = cells[0].strip()
            iso_date = None
            parts = raw_d.replace("-", "/").split("/")
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
                y_num = int(parts[0])
                if y_num < 1911:
                    y_num += 1911
                iso_date = f"{y_num:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            elif len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                md_key = f"{int(parts[0]):02d}/{int(parts[1]):02d}"
                iso_date = md_to_iso.get(md_key)

            if not iso_date or iso_date not in valid_iso_set:
                continue
            if start_date_exclusive and iso_date <= start_date_exclusive:
                continue

            mm_bal_yi = parse_num(cells[1])
            mm_diff_yi = parse_num(cells[2])
            s_bal = parse_num(cells[3])
            s_diff = parse_num(cells[4])
            if mm_bal_yi > 0 or s_bal > 0:
                rec_map[iso_date] = (
                    iso_date,
                    0.0,
                    s_diff,
                    0.0,
                    s_bal,
                    mm_diff_yi,
                    mm_bal_yi
                )
    except Exception:
        pass

    return [rec_map[k] for k in sorted(rec_map.keys())]


def fetch_margin_short_data(pure_code: str, df_dates: pd.DatetimeIndex, start_date_exclusive: str = None) -> list:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if start_date_exclusive:
        query_start = (pd.to_datetime(start_date_exclusive) + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        query_start = (df_dates[0] - timedelta(days=10)).strftime('%Y-%m-%d') if len(df_dates) > 0 else (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')

    try:
        url_fm = "https://api.finmindtrade.com/api/v4/data"
        p_fm = {
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": pure_code,
            "start_date": query_start,
            "token": FINMIND_TOKEN
        }
        res_fm = requests.get(url_fm, params=p_fm, headers=headers, timeout=5)
        if res_fm.status_code == 200:
            data = res_fm.json().get("data", [])
            if data:
                records = []
                for row in data:
                    d_str = row.get("date")
                    m_buy = float(row.get("MarginPurchaseBuy", 0) or 0)
                    m_sell = float(row.get("MarginPurchaseSell", 0) or 0)
                    m_ret = float(row.get("MarginPurchaseCashRepayment", 0) or 0)
                    m_bal = float(row.get("MarginPurchaseTodayBalance", 0) or 0)
                    m_diff = m_buy - m_sell - m_ret

                    s_sell = float(row.get("ShortSaleSell", 0) or 0)
                    s_buy = float(row.get("ShortSaleBuy", 0) or 0)
                    s_ret = float(row.get("ShortSaleCashRepayment", 0) or 0)
                    s_bal = float(row.get("ShortSaleTodayBalance", 0) or 0)
                    s_diff = s_sell - s_buy - s_ret

                    records.append((d_str, m_diff, s_diff, m_bal, s_bal))
                return records
    except Exception:
        pass
    return []
## EOF ftch_inst_margin.py
