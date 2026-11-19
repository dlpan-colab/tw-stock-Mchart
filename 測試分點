# -*- coding: utf-8 -*-
"""
獨立分點爬蟲與區間邏輯測試腳本（可直接在 Google Colab 貼上執行）
用途：實測指定基準日、往前計數近 N 日、分點統計（1/10/20/60日）與分點逐日明細之真實回傳資料
"""
import re
import time
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

MDJ_BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"
MDJ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{MDJ_BASE_DOMAIN}/"
}


def _clean_int(val_str: str) -> int:
    s = str(val_str or "").replace(",", "").replace("+", "").replace(" ", "").strip()
    if not s or s in ("-", "--", "—"):
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def _resolve_detail_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    h = href.strip()
    m_js = re.search(r"['\"]([^'\"]*z/zg/zgb/zgb0\.djhtm[^'\"]*)['\"]", h, re.IGNORECASE)
    if m_js:
        h = m_js.group(1)
    if h.lower().startswith("javascript:"):
        return ""
    full = urljoin(base_url, h)
    parsed = urlparse(full)
    qs = parse_qs(parsed.query)
    flat_qs = {k: v[0] for k, v in qs.items() if v}
    if "b" in flat_qs and "B" not in flat_qs:
        flat_qs["B"] = flat_qs.pop("b")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(flat_qs), ""))


def _parse_roc_or_iso_date(date_text: str) -> str:
    s = str(date_text or "").strip()
    m_iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    m_roc = re.match(r"^(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m_roc:
        return f"{int(m_roc.group(1)) + 1911:04d}-{int(m_roc.group(2)):02d}-{int(m_roc.group(3)):02d}"
    return ""


def _parse_side_table(table_soup, base_url: str, is_sell: bool = False) -> pd.DataFrame:
    if table_soup is None:
        return pd.DataFrame()
    rows = []
    for tr in table_soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        texts = [td.get_text(" ", strip=True) for td in tds]
        if any(k in texts[0] for k in ("買超券商", "賣超券商", "券商名稱", "排行")):
            continue
        b_name = re.sub(r"\s+", " ", texts[0]).strip()
        if not b_name or b_name in ("合計", "總計", "其他"):
            continue
        net_v = _clean_int(texts[3])
        if is_sell:
            net_v = -abs(net_v)
        a_tag = tds[0].find("a", href=True)
        d_url = _resolve_detail_url(a_tag["href"], base_url) if a_tag else ""
        rows.append({
            "分點名稱": b_name,
            "買進": _clean_int(texts[1]),
            "賣出": _clean_int(texts[2]),
            "買賣超": net_v,
            "佔比": texts[4].strip() if len(texts) >= 5 and "%" in texts[4] else "-",
            "明細網址": d_url
        })
    return pd.DataFrame(rows)


def test_fetch_broker_ranking(code: str, start_date: str, end_date: str):
    if start_date == end_date:
        url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco_{code}.djhtm"
    else:
        url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&e={start_date}&f={end_date}"

    res = requests.get(url, headers=MDJ_HEADERS, timeout=8)
    html = res.content.decode("cp950", errors="replace")
    m_dt = re.search(r"資料日期[：:]\s*(\d{2,4}[-/]\d{1,2}[-/]\d{1,2})", html)
    page_date = _parse_roc_or_iso_date(m_dt.group(1)) if m_dt else "未標示"

    soup = BeautifulSoup(html, "html.parser")
    buy_tbl, sell_tbl = None, None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text(" ", strip=True)
        if "買超券商" in txt and "賣超券商" in txt:
            for stbl in tbl.find_all("table"):
                stxt = stbl.get_text(" ", strip=True)
                if "買超券商" in stxt and "賣超券商" not in stxt and buy_tbl is None:
                    buy_tbl = stbl
                elif "賣超券商" in stxt and "買超券商" not in stxt and sell_tbl is None:
                    sell_tbl = stbl
            if buy_tbl is not None or sell_tbl is not None:
                break

    df_b = _parse_side_table(buy_tbl, url, is_sell=False)
    df_s = _parse_side_table(sell_tbl, url, is_sell=True)
    return {
        "url": url,
        "status_code": res.status_code,
        "page_date": page_date,
        "df_buy": df_b,
        "df_sell": df_s
    }


def test_fetch_broker_detail(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    parsed = urlparse(detail_url)
    qs = parse_qs(parsed.query)
    flat_qs = {k: v[0] for k, v in qs.items() if v}
    flat_qs["C"] = "1"
    flat_qs["E"] = start_date
    flat_qs["F"] = end_date
    q_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(flat_qs), ""))

    res = requests.get(q_url, headers=MDJ_HEADERS, timeout=8)
    html = res.content.decode("cp950", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    recs = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        texts = [td.get_text(" ", strip=True) for td in tds]
        iso_d = _parse_roc_or_iso_date(texts[0])
        if iso_d and start_date <= iso_d <= end_date:
            recs.append({
                "日期": iso_d,
                "買進": _clean_int(texts[1]),
                "賣出": _clean_int(texts[2]),
                "買賣超": _clean_int(texts[3])
            })
    if not recs:
        return pd.DataFrame()
    return pd.DataFrame(recs).drop_duplicates(subset=["日期"]).sort_values("日期").reset_index(drop=True)


def run_standalone_broker_test(
    stock_code: str = "2317",
    base_date: str = "2026-11-18",
    recent_days: int = 2
):
    print(f"=== 獨立測試開始：標的={stock_code} | 基準日={base_date} | 往前計數={recent_days} 日 ===")
    hist = yf.Ticker(f"{stock_code}.TW").history(period="6mo")
    if hist.empty:
        hist = yf.Ticker(f"{stock_code}.TWO").history(period="6mo")
    trade_dates = [d.strftime("%Y-%m-%d") for d in hist.index]
    eligible = [i for i, d in enumerate(trade_dates) if d <= base_date]
    anchor_idx = eligible[-1]
    start_pos = max(0, anchor_idx - recent_days + 1)

    for idx in range(start_pos, anchor_idx + 1):
        end_d = trade_dates[idx]
        print(f"\n--- [基準交易日: {end_d}] ---")
        for w in (1, 10, 20, 60):
            s_d = trade_dates[max(0, idx - w + 1)]
            out = test_fetch_broker_ranking(stock_code, s_d, end_d)
            b_cnt = len(out["df_buy"])
            s_cnt = len(out["df_sell"])
            print(f"區間 w{w:2d} ({s_d} ~ {end_d}) | HTTP={out['status_code']} | 網頁資料日期={out['page_date']} | 買超筆數={b_cnt}, 賣超筆數={s_cnt}")
            print(f"   URL: {out['url']}")
            if b_cnt > 0:
                print("   買超前3:", out["df_buy"][["分點名稱", "買進", "賣出", "買賣超"]].head(3).to_dict("records"))
            if s_cnt > 0:
                print("   賣超前3:", out["df_sell"][["分點名稱", "買進", "賣出", "買賣超"]].head(3).to_dict("records"))

            if w == 10 and b_cnt > 0:
                top1 = out["df_buy"].iloc[0]
                s_60 = trade_dates[max(0, idx - 60 + 1)]
                df_detail = test_fetch_broker_detail(top1["明細網址"], s_60, end_d)
                print(f"   -> 測試第1名分點【{top1['分點名稱']}】近60日明細 ({s_60} ~ {end_d})：共 {len(df_detail)} 筆")
                if not df_detail.empty:
                    print(df_detail.tail(5).to_string(index=False))
            time.sleep(0.2)


# 直接執行測試（可自行修改代號、基準日、往前日數）
if __name__ == "__main__":
    run_standalone_broker_test(stock_code="2317", base_date="2026-11-18", recent_days=2)
