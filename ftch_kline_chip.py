"""
ftch_kline_chip.py - 日K線擷取與全市場籌碼智慧增量同步總入口模組
(依邏輯職責將三大法人與個股/大盤資券爬蟲拆出至 ftch_inst_margin.py，維持 100% 向後相容匯出)
版本: 202611270925
"""

import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from storage import (
    StockChipStorage,
    get_stock_chinese_name,
    is_tw_stock_or_etf,
)
from ftch_tdcc_dash import fetch_tdcc_holding_data
from ftch_inst_margin import (
    FINMIND_TOKEN,
    fetch_market_index_institutional_data,
    fetch_institutional_investors,
    fetch_twse_total_margin_data,
    fetch_tpex_total_margin_data,
    fetch_margin_short_data,
)

MODULE_NAME = "ftch_kline_chip"
MODULE_VERSION = "202611270925"


def fetch_stock_name(pure_code: str) -> str:
    """取得股票中文名稱 (優先查字典/快取，無則爬蟲)"""
    return get_stock_chinese_name(pure_code)


def _fetch_tw_official_month_k(pure_code: str, full_ticker: str = None) -> pd.DataFrame:
    """
    【修訂說明 2026-11-14】向台灣證交所(TWSE STOCK_DAY)或櫃買中心(TPEx)擷取當月完整四價日K線，
    補齊 Yahoo Finance 偶發延遲更新的最新交易日（含開、高、低、收、成交量）。
    """
    code = str(pure_code or "").strip().upper()
    if not is_tw_stock_or_etf(code):
        return pd.DataFrame()

    now_tw = datetime.utcnow() + timedelta(hours=8)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    rows = []

    def parse_float(v):
        s = str(v or "").replace(",", "").strip()
        if s in ("", "-", "--", "—", "X"):
            return None
        try:
            return float(s)
        except Exception:
            return None

    is_tpex_only = bool(full_ticker and full_ticker.endswith(".TWO"))
    is_twse_only = bool(full_ticker and full_ticker.endswith(".TW"))

    # 1. 上市 TWSE STOCK_DAY（含上市個股與 00632R 等上市 ETF）
    if not is_tpex_only:
        date_param = now_tw.strftime("%Y%m01")
        url_twse = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_param}&stockNo={code}"
        try:
            res = requests.get(url_twse, headers=headers, timeout=4)
            if res.status_code == 200:
                js = res.json()
                if js.get("stat") == "OK" and js.get("data"):
                    for r in js["data"]:
                        if len(r) < 7:
                            continue
                        d_parts = str(r[0]).strip().split("/")
                        if len(d_parts) != 3:
                            continue
                        y = int(d_parts[0]) + 1911
                        d_iso = f"{y:04d}-{int(d_parts[1]):02d}-{int(d_parts[2]):02d}"
                        vol_shares = parse_float(r[1])
                        o_p = parse_float(r[3])
                        h_p = parse_float(r[4])
                        l_p = parse_float(r[5])
                        c_p = parse_float(r[6])
                        if None not in (o_p, h_p, l_p, c_p) and vol_shares and vol_shares > 0:
                            rows.append((pd.to_datetime(d_iso), o_p, h_p, l_p, c_p, vol_shares))
        except Exception:
            pass

    # 2. 上櫃 TPEx daily_trading_info（若上市查無且非限定上市）
    if not rows and not is_twse_only:
        roc_ym = f"{now_tw.year - 1911}/{now_tw.month:02d}"
        url_tpex = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d={roc_ym}&stkno={code}"
        try:
            res_t = requests.get(url_tpex, headers=headers, timeout=4)
            if res_t.status_code == 200:
                js_t = res_t.json()
                aa = js_t.get("aaData") or js_t.get("tables", [{}])[0].get("data", [])
                for r in aa:
                    if len(r) < 7:
                        continue
                    d_parts = str(r[0]).strip().split("/")
                    if len(d_parts) != 3:
                        continue
                    y = int(d_parts[0]) + 1911
                    d_iso = f"{y:04d}-{int(d_parts[1]):02d}-{int(d_parts[2]):02d}"
                    vol_k = parse_float(r[1])
                    o_p = parse_float(r[3])
                    h_p = parse_float(r[4])
                    l_p = parse_float(r[5])
                    c_p = parse_float(r[6])
                    if None not in (o_p, h_p, l_p, c_p) and vol_k and vol_k > 0:
                        rows.append((pd.to_datetime(d_iso), o_p, h_p, l_p, c_p, vol_k * 1000.0))
        except Exception:
            pass

    if not rows:
        return pd.DataFrame()
    df_off = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df_off.set_index("Date", inplace=True)
    df_off = df_off[~df_off.index.duplicated(keep="last")].sort_index()
    return df_off


def _resolve_force_refresh_yf_period(target_days: int, anchor_date_str: str = "") -> str:
    """
    依目標交易日數與資料維護基準日（anchor_date_str）計算足以涵蓋至基準日往前 target_days 之 Yahoo Finance period 字串
    """
    n_bars = max(5, int(target_days or 120))
    extra_days = 0
    if anchor_date_str:
        try:
            now_tw = datetime.utcnow() + timedelta(hours=8)
            anc_dt = datetime.strptime(str(anchor_date_str).strip()[:10], "%Y-%m-%d")
            diff_cal = max(0, (now_tw - anc_dt).days)
            extra_days = int(diff_cal * 0.75)
        except Exception:
            extra_days = 0
    total_bars = n_bars + extra_days
    if total_bars <= 20:
        return "1mo"
    elif total_bars <= 62:
        return "3mo"
    elif total_bars <= 125:
        return "6mo"
    elif total_bars <= 250:
        return "1y"
    elif total_bars <= 500:
        return "2y"
    return "5y"


def fetch_stock_daily_k(
    raw_ticker: str,
    period: str = "1y",
    base_date: str = None,
    force_refresh: bool = False,
    display_days: int = 30,
    refresh_cfg: dict = None
):
    """
    自本地 SQLite 或官方 API / Yahoo Finance 擷取歷史日 K 線資料。
    【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
    1. 修改目的：支援透過 `refresh_cfg` 之 `base_date`（資料維護基準日）與 `kline_days` 計算抓取區間，
       當 `force_refresh=True` 且勾選「日 K 線」時重抓日 K 並增量合併覆蓋；未勾選則直接沿用資料庫既有日 K。
    2. 防呆防錯原因：一律以 `keep='last'` 合併去重並保留更早歷史資料。
    """
    raw_str = str(raw_ticker).strip()
    if not raw_str:
        return None
    pure_code = raw_str.upper()

    is_index = pure_code.startswith("^")
    is_tw_etf_or_stk = is_tw_stock_or_etf(pure_code)

    if pure_code == "^TWII":
        target_ticker = "^TWII"
        full_ticker = "^TWII"
    elif pure_code == "^TWOII":
        target_ticker = "006201.TWO"
        full_ticker = "^TWOII"
    elif is_index:
        target_ticker = pure_code
        full_ticker = pure_code
    elif is_tw_etf_or_stk:
        target_ticker = f"{pure_code}.TW"
        full_ticker = f"{pure_code}.TW"
    else:
        target_ticker = pure_code
        full_ticker = pure_code

    storage = StockChipStorage(pure_code)
    db_df = storage.load_daily_k_df()
    last_k_date = storage.get_latest_daily_k_date()

    shares_outstanding = None
    if is_tw_etf_or_stk:
        tdcc_tot = storage.get_latest_tdcc_total_shares()
        if tdcc_tot and tdcc_tot > 0:
            shares_outstanding = tdcc_tot

    cfg = refresh_cfg if isinstance(refresh_cfg, dict) else {}
    kline_force = bool(force_refresh and cfg.get("kline_enabled", True))
    kline_days_val = max(1, int(cfg.get("kline_days", 120) or 120))
    cfg_base_date = str(cfg.get("base_date", "") or "").strip()

    # 若為強制重抓模式且使用者未勾選「日 K 線」，只要本地已有資料就直接返回，完全不動日 K 資料表
    if force_refresh and not kline_force and not db_df.empty:
        return db_df, full_ticker, shares_outstanding

    ticker = yf.Ticker(target_ticker)
    if is_tw_etf_or_stk and not shares_outstanding:
        try:
            shares_outstanding = ticker.info.get("sharesOutstanding")
        except Exception:
            pass

    if db_df.empty or not last_k_date:
        fetch_period = period
    elif kline_force:
        fetch_period = _resolve_force_refresh_yf_period(kline_days_val, cfg_base_date)
    else:
        fetch_period = "5d"

    try:
        df_new = ticker.history(period=fetch_period)
    except Exception:
        df_new = pd.DataFrame()

    if (df_new is None or df_new.empty):
        if target_ticker.endswith(".TWO"):
            alt_ticker = target_ticker.replace(".TWO", ".TW")
            try:
                df_new = yf.Ticker(alt_ticker).history(period=fetch_period)
            except Exception:
                pass
        elif is_tw_etf_or_stk and target_ticker.endswith(".TW"):
            alt_ticker = f"{pure_code}.TWO"
            try:
                t_alt = yf.Ticker(alt_ticker)
                if not shares_outstanding:
                    shares_outstanding = t_alt.info.get("sharesOutstanding")
                df_new = t_alt.history(period=fetch_period)
                if df_new is not None and not df_new.empty:
                    full_ticker = alt_ticker
            except Exception:
                pass

    combined = db_df.copy() if not db_df.empty else pd.DataFrame()
    if df_new is not None and not df_new.empty:
        if df_new.index.tz is not None:
            df_new.index = df_new.index.tz_localize(None)
        valid_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df_new.columns]
        if valid_cols:
            df_new = df_new.dropna(subset=valid_cols)
        if not is_index and 'Volume' in df_new.columns:
            df_new = df_new[df_new['Volume'] > 0]

        if not combined.empty:
            combined = pd.concat([combined, df_new])
            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
        else:
            combined = df_new.sort_index()

    if is_tw_etf_or_stk and not combined.empty:
        now_tw = datetime.utcnow() + timedelta(hours=8)
        expected_latest = now_tw.date()
        if expected_latest.weekday() == 5:
            expected_latest -= timedelta(days=1)
        elif expected_latest.weekday() == 6:
            expected_latest -= timedelta(days=2)
        elif now_tw.hour < 14:
            expected_latest -= timedelta(days=1)
        while expected_latest.weekday() >= 5:
            expected_latest -= timedelta(days=1)

        latest_in_df = combined.index[-1].date()
        if kline_force or latest_in_df < expected_latest:
            df_official = _fetch_tw_official_month_k(pure_code, full_ticker=full_ticker)
            if df_official is not None and not df_official.empty:
                combined = pd.concat([combined, df_official])
                combined = combined[~combined.index.duplicated(keep='last')].sort_index()

    if not combined.empty:
        storage.save_daily_k_df(combined)
        return combined, full_ticker, shares_outstanding
    return None


def sync_chip_data(
    pure_code: str,
    df_dates: pd.DatetimeIndex,
    status_placeholder=None,
    force_refresh: bool = False,
    full_ticker: str = None,
    display_days: int = 30,
    refresh_cfg: dict = None
):
    """
    智慧增量同步三大法人、資券與集保大戶。
    【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
    1. 修改目的：為大盤加權指數（`^TWII`）與櫃買指數（`^TWOII`）補齊全市場三大法人每日買賣超金額（億元）增量同步，
       呼叫 `fetch_market_index_institutional_data` 寫入 `institutional_investors` 並回傳 `storage.load_institutional_df()`。
    2. 防呆防錯原因：台灣時間當日 16:00 前排除尚未公告之當日法人數據；支援 `force_refresh` 依勾選之法人項目與期程覆蓋更新。
    """
    pure_code = str(pure_code).strip().upper()
    storage = StockChipStorage(pure_code)
    n_disp = max(5, int(display_days or 30))
    cfg = refresh_cfg if isinstance(refresh_cfg, dict) else {}

    # 解析資料維護基準日對應於 df_dates 之索引位置 anchor_idx
    anchor_idx = len(df_dates) - 1
    cfg_base_date = str(cfg.get("base_date", "") or "").strip()
    if cfg_base_date and len(df_dates) > 0:
        b_norm = cfg_base_date[:10]
        valid_pos = [i for i, d in enumerate(df_dates) if d.strftime('%Y-%m-%d') <= b_norm]
        if valid_pos:
            anchor_idx = valid_pos[-1]
    anchor_date_str = df_dates[anchor_idx].strftime('%Y-%m-%d') if len(df_dates) > 0 else ""

    if pure_code in ("^TWII", "^TWOII"):
        if len(df_dates) == 0:
            return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        last_margin_date = storage.get_latest_margin_date()
        latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')
        now_tw = datetime.utcnow() + timedelta(hours=8)
        now_tw_date_str = now_tw.strftime('%Y-%m-%d')

        # 1. 大盤/櫃買三大法人買賣超金額（億元）智慧增量同步
        existing_inst_df = storage.load_institutional_df()
        existing_inst_dates = set(existing_inst_df['date'].dt.strftime('%Y-%m-%d')) if not existing_inst_df.empty else set()
        recent_k_dates = [d.strftime('%Y-%m-%d') for d in df_dates[-n_disp:]]
        missing_inst_dates = [d for d in recent_k_dates if d not in existing_inst_dates]
        if now_tw_date_str in missing_inst_dates and now_tw.hour < 16:
            missing_inst_dates.remove(now_tw_date_str)

        f_en = bool(cfg.get("foreign_enabled", True))
        t_en = bool(cfg.get("trust_enabled", True))
        d_en = bool(cfg.get("dealer_enabled", True))
        f_days = max(1, int(cfg.get("foreign_days", 120) or 120))
        t_days = max(1, int(cfg.get("trust_days", 120) or 120))
        d_days = max(1, int(cfg.get("dealer_days", 120) or 120))

        if force_refresh:
            if f_en or t_en or d_en:
                max_inst_days = max(
                    f_days if f_en else 0,
                    t_days if t_en else 0,
                    d_days if d_en else 0,
                )
                inst_start_idx = max(0, anchor_idx - max_inst_days + 1)
                target_dates = list(df_dates[inst_start_idx:anchor_idx + 1]) if max_inst_days > 0 else []
                inst_records = fetch_market_index_institutional_data(
                    pure_code=pure_code,
                    df_dates=df_dates,
                    explicit_missing_dates=target_dates,
                )
                if inst_records:
                    f_cutoff = df_dates[max(0, anchor_idx - f_days + 1)].strftime('%Y-%m-%d') if f_en else "9999-12-31"
                    t_cutoff = df_dates[max(0, anchor_idx - t_days + 1)].strftime('%Y-%m-%d') if t_en else "9999-12-31"
                    d_cutoff = df_dates[max(0, anchor_idx - d_days + 1)].strftime('%Y-%m-%d') if d_en else "9999-12-31"

                    old_map = {}
                    if not existing_inst_df.empty:
                        for _, r in existing_inst_df.iterrows():
                            ds = pd.to_datetime(r['date']).strftime('%Y-%m-%d')
                            old_map[ds] = (
                                float(r.get('foreign_net', 0.0) or 0.0),
                                float(r.get('trust_net', 0.0) or 0.0),
                                float(r.get('dealer_net', 0.0) or 0.0),
                            )

                    merged_inst = []
                    for ds, fn, tn, dn in inst_records:
                        if anchor_date_str and ds > anchor_date_str:
                            continue
                        prev_f, prev_t, prev_d = old_map.get(ds, (0.0, 0.0, 0.0))
                        new_f = fn if (f_en and ds >= f_cutoff) else prev_f
                        new_t = tn if (t_en and ds >= t_cutoff) else prev_t
                        new_d = dn if (d_en and ds >= d_cutoff) else prev_d
                        merged_inst.append((ds, new_f, new_t, new_d))
                    if merged_inst:
                        storage.save_institutional_data(merged_inst)
        elif missing_inst_dates:
            target_dates = [d for d in df_dates if d.strftime('%Y-%m-%d') in missing_inst_dates]
            inst_records = fetch_market_index_institutional_data(
                pure_code=pure_code,
                df_dates=df_dates,
                explicit_missing_dates=target_dates,
            )
            if inst_records:
                storage.save_institutional_data(inst_records)

        # 2. 大盤/櫃買全市場資券增量同步
        existing_ms_df = storage.load_margin_df()
        missing_money_col = (
            existing_ms_df.empty
            or "margin_money_bal" not in existing_ms_df.columns
            or (existing_ms_df["margin_money_bal"].fillna(0) == 0).all()
        )
        margin_force = bool(force_refresh and cfg.get("margin_enabled", True))
        margin_days_val = max(1, int(cfg.get("margin_days", 120) or 120))
        should_fetch_margin = margin_force or missing_money_col
        if not should_fetch_margin and not force_refresh:
            if not last_margin_date:
                should_fetch_margin = True
            elif last_margin_date < latest_trade_date_str:
                if now_tw_date_str == latest_trade_date_str and now_tw.hour < 21:
                    should_fetch_margin = False
                else:
                    should_fetch_margin = True
        if should_fetch_margin:
            if missing_money_col:
                start_filter = None
            elif margin_force:
                idx_start = max(0, anchor_idx - margin_days_val)
                start_filter = df_dates[idx_start].strftime('%Y-%m-%d')
            else:
                start_filter = last_margin_date
            if pure_code == "^TWII":
                margin_records = fetch_twse_total_margin_data(df_dates, start_date_exclusive=start_filter)
            else:
                margin_records = fetch_tpex_total_margin_data(df_dates, start_date_exclusive=start_filter)
            if margin_records:
                if margin_force and anchor_date_str:
                    margin_records = [r for r in margin_records if str(r[0])[:10] <= anchor_date_str]
                if margin_records:
                    storage.save_margin_data(margin_records)
        if status_placeholder:
            status_placeholder.empty()
        return (storage.load_institutional_df(), storage.load_margin_df(), pd.DataFrame())

    if pure_code.startswith("^") or not is_tw_stock_or_etf(pure_code):
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    if len(df_dates) == 0:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    last_margin_date = storage.get_latest_margin_date()
    last_holding_date = storage.get_latest_holding_date()
    latest_trade_date_str = df_dates[-1].strftime('%Y-%m-%d')
    now_tw = datetime.utcnow() + timedelta(hours=8)
    now_tw_date_str = now_tw.strftime('%Y-%m-%d')

    existing_inst_df = storage.load_institutional_df()
    existing_dates = set(existing_inst_df['date'].dt.strftime('%Y-%m-%d')) if not existing_inst_df.empty else set()
    recent_k_dates = [d.strftime('%Y-%m-%d') for d in df_dates[-n_disp:]]
    missing_inst_dates = [d for d in recent_k_dates if d not in existing_dates]
    if now_tw_date_str in missing_inst_dates and now_tw.hour < 16:
        missing_inst_dates.remove(now_tw_date_str)

    # 比照三大法人，檢查近 n_disp 交易日之資券缺漏日（含中間缺日與當日 21:00 後更新）
    existing_ms_df = storage.load_margin_df()
    existing_ms_dates = set(existing_ms_df['date'].dt.strftime('%Y-%m-%d')) if not existing_ms_df.empty else set()
    missing_margin_dates = [d for d in recent_k_dates if d not in existing_ms_dates]
    if now_tw_date_str in missing_margin_dates and now_tw.hour < 21:
        missing_margin_dates.remove(now_tw_date_str)

    f_en = bool(cfg.get("foreign_enabled", True))
    t_en = bool(cfg.get("trust_enabled", True))
    d_en = bool(cfg.get("dealer_enabled", True))
    f_days = max(1, int(cfg.get("foreign_days", 120) or 120))
    t_days = max(1, int(cfg.get("trust_days", 120) or 120))
    d_days = max(1, int(cfg.get("dealer_days", 120) or 120))

    if force_refresh:
        should_fetch_inst = (f_en or t_en or d_en)
    else:
        should_fetch_inst = (len(missing_inst_dates) > 0)

    m_en = bool(cfg.get("margin_enabled", True))
    m_days = max(1, int(cfg.get("margin_days", 120) or 120))
    if force_refresh:
        should_fetch_margin = m_en
    else:
        should_fetch_margin = (len(missing_margin_dates) > 0)
        if not should_fetch_margin:
            if not last_margin_date:
                should_fetch_margin = True
            elif last_margin_date < latest_trade_date_str:
                if not (now_tw_date_str == latest_trade_date_str and now_tw.hour < 21):
                    should_fetch_margin = True

    h_en = bool(cfg.get("holding_enabled", True))
    h_weeks = min(15, max(1, int(cfg.get("holding_weeks", 1) or 1)))
    if force_refresh:
        should_fetch_holding = h_en
    else:
        should_fetch_holding = False
        if not last_holding_date:
            should_fetch_holding = True
        else:
            diff_days = (now_tw - pd.to_datetime(last_holding_date)).days
            is_weekend_publish = (now_tw.weekday() == 4 and now_tw.hour >= 20) or (now_tw.weekday() in [5, 6])
            if diff_days >= 7:
                should_fetch_holding = True
            elif is_weekend_publish and diff_days >= 1:
                should_fetch_holding = True

    if should_fetch_inst:
        if force_refresh:
            max_inst_days = max(
                f_days if f_en else 0,
                t_days if t_en else 0,
                d_days if d_en else 0,
            )
            inst_start_idx = max(0, anchor_idx - max_inst_days + 1)
            target_dates = list(df_dates[inst_start_idx:anchor_idx + 1]) if max_inst_days > 0 else []
            inst_records = fetch_institutional_investors(
                pure_code=pure_code,
                df_dates=df_dates,
                explicit_missing_dates=target_dates,
                full_ticker=full_ticker
            )
            if inst_records:
                f_cutoff = df_dates[max(0, anchor_idx - f_days + 1)].strftime('%Y-%m-%d') if f_en else "9999-12-31"
                t_cutoff = df_dates[max(0, anchor_idx - t_days + 1)].strftime('%Y-%m-%d') if t_en else "9999-12-31"
                d_cutoff = df_dates[max(0, anchor_idx - d_days + 1)].strftime('%Y-%m-%d') if d_en else "9999-12-31"

                old_map = {}
                if not existing_inst_df.empty:
                    for _, r in existing_inst_df.iterrows():
                        ds = pd.to_datetime(r['date']).strftime('%Y-%m-%d')
                        old_map[ds] = (
                            float(r.get('foreign_net', 0.0) or 0.0),
                            float(r.get('trust_net', 0.0) or 0.0),
                            float(r.get('dealer_net', 0.0) or 0.0),
                        )

                merged_inst = []
                for ds, fn, tn, dn in inst_records:
                    if anchor_date_str and ds > anchor_date_str:
                        continue
                    prev_f, prev_t, prev_d = old_map.get(ds, (0.0, 0.0, 0.0))
                    new_f = fn if (f_en and ds >= f_cutoff) else prev_f
                    new_t = tn if (t_en and ds >= t_cutoff) else prev_t
                    new_d = dn if (d_en and ds >= d_cutoff) else prev_d
                    merged_inst.append((ds, new_f, new_t, new_d))
                if merged_inst:
                    storage.save_institutional_data(merged_inst)
        else:
            target_dates = [d for d in df_dates if d.strftime('%Y-%m-%d') in missing_inst_dates]
            inst_records = fetch_institutional_investors(
                pure_code=pure_code,
                df_dates=df_dates,
                explicit_missing_dates=target_dates,
                full_ticker=full_ticker
            )
            if inst_records:
                storage.save_institutional_data(inst_records)

    if should_fetch_margin:
        if force_refresh:
            idx_start = max(0, anchor_idx - m_days)
            start_filter = df_dates[idx_start].strftime('%Y-%m-%d')
        elif missing_margin_dates:
            earliest_missing_ms = min(missing_margin_dates)
            start_filter = (pd.to_datetime(earliest_missing_ms) - timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            start_filter = last_margin_date
        margin_records = fetch_margin_short_data(pure_code, df_dates, start_date_exclusive=start_filter)
        if margin_records:
            if force_refresh and anchor_date_str:
                margin_records = [r for r in margin_records if str(r[0])[:10] <= anchor_date_str]
            if margin_records:
                storage.save_margin_data(margin_records)

    if should_fetch_holding:
        holding_records = fetch_tdcc_holding_data(pure_code)
        if holding_records:
            if force_refresh:
                if anchor_date_str:
                    holding_records = [r for r in holding_records if str(r[0])[:10] <= anchor_date_str]
                distinct_weeks = sorted({str(r[0])[:10] for r in holding_records if r and len(r) >= 3}, reverse=True)
                keep_weeks = set(distinct_weeks[:h_weeks])
                holding_records = [r for r in holding_records if str(r[0])[:10] in keep_weeks]
            if holding_records:
                storage.save_holding_data(holding_records)

    if status_placeholder:
        status_placeholder.empty()

    return (
        storage.load_institutional_df(),
        storage.load_margin_df(),
        storage.load_holding_df()
    )
## EOF ftch_kline_chip.py
