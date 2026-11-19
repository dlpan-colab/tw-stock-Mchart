# -*- coding: utf-8 -*-
"""
獨立分點爬蟲與區間邏輯測試頁面（Streamlit 專用版 - 10欄並排表格解析版）
用途：實測指定基準日、往前計數近 N 日、分點統計（1/10/20/60日）與分點逐日明細之真實回傳資料
"""
import re
import time
import requests
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

MDJ_BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"
MDJ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{MDJ_BASE_DOMAIN}/"
}


def _get_default_base_date() -> str:
    now_tw = datetime.utcnow() + timedelta(hours=8)
    d = now_tw.date()
    if d.weekday() == 5:
        d -= timedelta(days=1)
    elif d.weekday() == 6:
        d -= timedelta(days=2)
    elif now_tw.hour < 15:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


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


def _parse_5_cells(td_slice: list, base_url: str, is_sell: bool) -> dict:
    if len(td_slice) < 4:
        return None
    texts = [td.get_text(" ", strip=True) for td in td_slice]
    if any(k in texts[0] for k in ("買超券商", "賣超券商", "券商名稱", "排行")):
        return None
    b_name = re.sub(r"\s+", " ", texts[0]).strip()
    if not b_name or b_name in ("合計", "總計", "其他"):
        return None
    net_v = _clean_int(texts[3])
    if is_sell:
        net_v = -abs(net_v)
    a_tag = td_slice[0].find("a", href=True)
    d_url = _resolve_detail_url(a_tag["href"], base_url) if a_tag else ""
    return {
        "分點名稱": b_name,
        "買進": _clean_int(texts[1]),
        "賣出": _clean_int(texts[2]),
        "買賣超": net_v,
        "佔比": texts[4].strip() if len(texts) >= 5 and "%" in texts[4] else "-",
        "明細網址": d_url
    }


def _parse_combined_or_side_tables(soup, base_url: str) -> tuple:
    """
    【修訂說明 2026-11-19】
    直接解析富邦 eBroker 同一張 10 欄並排表格（前 5 欄為買超券商、後 5 欄為賣超券商），
    若頁面為左右獨立 5 欄子表格亦自動相容。
    """
    buy_rows, sell_rows = [], []

    for tbl in soup.find_all("table"):
        txt = tbl.get_text(" ", strip=True)
        if "買超券商" in txt and "賣超券商" in txt:
            # 尋找最內層包含買賣超資料列的表格
            has_inner = any(
                ("買超券商" in st.get_text(" ", strip=True) and "賣超券商" in st.get_text(" ", strip=True))
                for st in tbl.find_all("table")
            )
            if has_inner:
                continue

            for tr in tbl.find_all("tr"):
                tds = tr.find_all("td", recursive=False)
                if not tds:
                    tds = tr.find_all("td")
                if len(tds) >= 10:
                    b_item = _parse_5_cells(tds[0:5], base_url, is_sell=False)
                    s_item = _parse_5_cells(tds[5:10], base_url, is_sell=True)
                    if b_item:
                        buy_rows.append(b_item)
                    if s_item:
                        sell_rows.append(s_item)
            if buy_rows or sell_rows:
                break

    return pd.DataFrame(buy_rows), pd.DataFrame(sell_rows)


def test_fetch_broker_ranking(code: str, start_date: str, end_date: str):
    url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={code}&e={start_date}&f={end_date}"

    try:
        res = requests.get(url, headers=MDJ_HEADERS, timeout=8)
        html = res.content.decode("cp950", errors="replace")
        m_dt = re.search(r"(?:最後更新日|資料日期)[：:]\s*(\d{2,4}[-/]\d{1,2}[-/]\d{1,2})", html)
        page_date = _parse_roc_or_iso_date(m_dt.group(1)) if m_dt else "未標示"

        soup = BeautifulSoup(html, "html.parser")
        raw_preview = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:300]
        df_b, df_s = _parse_combined_or_side_tables(soup, url)

        return {
            "url": url,
            "status_code": res.status_code,
            "page_date": page_date,
            "df_buy": df_b,
            "df_sell": df_s,
            "raw_preview": raw_preview,
            "err": ""
        }
    except Exception as e:
        return {
            "url": url,
            "status_code": -1,
            "page_date": "-",
            "df_buy": pd.DataFrame(),
            "df_sell": pd.DataFrame(),
            "raw_preview": "",
            "err": str(e)
        }


def test_fetch_broker_detail(detail_url: str, start_date: str, end_date: str) -> tuple:
    parsed = urlparse(detail_url)
    qs = parse_qs(parsed.query)
    flat_qs = {k: v[0] for k, v in qs.items() if v}
    flat_qs["C"] = "1"
    flat_qs["E"] = start_date
    flat_qs["F"] = end_date
    q_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(flat_qs), ""))

    try:
        res = requests.get(q_url, headers=MDJ_HEADERS, timeout=8)
        html = res.content.decode("cp950", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        raw_preview = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:300]
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
            return pd.DataFrame(), q_url, "", raw_preview
        df_out = pd.DataFrame(recs).drop_duplicates(subset=["日期"]).sort_values("日期").reset_index(drop=True)
        return df_out, q_url, "", raw_preview
    except Exception as e:
        return pd.DataFrame(), q_url, str(e), ""


st.set_page_config(page_title="分點獨立測試工具", layout="wide")
st.subheader("🧪 富邦分點統計與明細獨立測試工具")

col1, col2, col3 = st.columns(3)
with col1:
    stock_code = st.text_input("測試股票代號", value="2317").strip().upper()
with col2:
    base_date = st.text_input("增補分點基準日 (YYYY-MM-DD)", value=_get_default_base_date()).strip()
with col3:
    recent_days = st.number_input("增補分點日數（自基準日起往前計數）", min_value=1, max_value=20, value=2, step=1)

c_btn1, c_btn2 = st.columns(2)
run_rank = c_btn1.button("📊 測試分點統計 (1/10/20/60日)", use_container_width=True)
run_detail = c_btn2.button("📈 測試分點明細 (前3名60日逐日)", use_container_width=True)

if run_rank or run_detail:
    with st.spinner(f"正在取得 {stock_code} 交易日曆..."):
        hist = yf.Ticker(f"{stock_code}.TW").history(period="6mo")
        if hist.empty:
            hist = yf.Ticker(f"{stock_code}.TWO").history(period="6mo")

    if hist.empty:
        st.error(f"無法取得 {stock_code} 交易日資料")
    else:
        trade_dates = [d.strftime("%Y-%m-%d") for d in hist.index]
        eligible = [i for i, d in enumerate(trade_dates) if d <= base_date]
        if not eligible:
            st.error(f"基準日 {base_date} 早於最早交易日 {trade_dates[0]}")
        else:
            anchor_idx = eligible[-1]
            start_pos = max(0, anchor_idx - int(recent_days) + 1)
            st.info(f"實際對應交易日區間：{trade_dates[start_pos]} ~ {trade_dates[anchor_idx]}（共 {anchor_idx - start_pos + 1} 個交易日）")

            for idx in range(start_pos, anchor_idx + 1):
                end_d = trade_dates[idx]
                st.markdown(f"### 📅 基準交易日：`{end_d}`")

                if run_rank:
                    for w in (1, 10, 20, 60):
                        s_d = trade_dates[max(0, idx - w + 1)]
                        out = test_fetch_broker_ranking(stock_code, s_d, end_d)
                        b_cnt = len(out["df_buy"])
                        s_cnt = len(out["df_sell"])
                        st.write(
                            f"**區間 w{w}** (`{s_d}` ~ `{end_d}`) ｜ HTTP: `{out['status_code']}` ｜ 網頁資料日期: `{out['page_date']}` ｜ 買超: `{b_cnt}` 筆 / 賣超: `{s_cnt}` 筆"
                        )
                        st.caption(f"網址: {out['url']}")
                        if out["err"]:
                            st.error(out["err"])
                        if b_cnt == 0 and s_cnt == 0:
                            st.code(out["raw_preview"] or "(回傳內容為空)", language="text")
                        else:
                            ca, cb = st.columns(2)
                            with ca:
                                st.dataframe(out["df_buy"][["分點名稱", "買進", "賣出", "買賣超", "佔比"]].head(5), use_container_width=True)
                            with cb:
                                st.dataframe(out["df_sell"][["分點名稱", "買進", "賣出", "買賣超", "佔比"]].head(5), use_container_width=True)
                        time.sleep(0.15)

                if run_detail:
                    s_10 = trade_dates[max(0, idx - 10 + 1)]
                    s_60 = trade_dates[max(0, idx - 60 + 1)]
                    rank_out = test_fetch_broker_ranking(stock_code, s_10, end_d)
                    if rank_out["df_buy"].empty:
                        st.warning(f"`{end_d}` 近10日買超清單為空，無法測試明細（HTTP={rank_out['status_code']}, 錯誤={rank_out['err']}）")
                        st.code(rank_out["raw_preview"] or "(回傳內容為空)", language="text")
                    else:
                        for _, r in rank_out["df_buy"].head(3).iterrows():
                            b_name = r["分點名稱"]
                            d_url = r["明細網址"]
                            df_d, q_url, d_err, d_prev = test_fetch_broker_detail(d_url, s_60, end_d)
                            st.write(f"分點 **{b_name}** 近60日明細 (`{s_60}` ~ `{end_d}`)：共 `{len(df_d)}` 筆")
                            st.caption(f"明細網址: {q_url}")
                            if d_err:
                                st.error(d_err)
                            elif df_d.empty:
                                st.code(d_prev or "(回傳內容為空)", language="text")
                            else:
                                st.dataframe(df_d.tail(10), use_container_width=True)
                            time.sleep(0.15)
