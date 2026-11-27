"""
indicators.py - 技術指標與籌碼計算模組
(新增 20/120/240/1200 日乖離率、大盤加權^TWII與櫃買^TWOII融資金額(億)與融資/融券維持率、八大官股每日買賣超(億)、個股全期間與近60日滾動視窗預估融資維持率計算及以集保最新週真實總股數扣除近15週1000張以上大於0最小持股比例之實際流通張數週轉率與1%約當張數輸出版)
版本: 202611270925
"""

import os
import sqlite3
import numpy as np
import pandas as pd

MODULE_NAME = "indicators"
MODULE_VERSION = "202611270925"

HOLDING_LEVEL_MAP = {
    100: [8, 9, 10, 11, 12, 13, 14, 15],
    200: [9, 10, 11, 12, 13, 14, 15],
    400: [11, 12, 13, 14, 15],
    600: [12, 13, 14, 15],
    800: [13, 14, 15],
    1000: [15]
}


def calculate_all_indicators(
    df,
    pure_code,
    major1_thresh,
    major2_thresh,
    shares_outstanding=None,
    status_placeholder=None,
    force_refresh: bool = False,
    full_ticker: str = None,
    display_days: int = 30,
    refresh_cfg: dict = None
):
    if df is None or df.empty:
        return df

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 1. 均線 MA5, MA20, MA60 及乖離率基準均線 MA120, MA240, MA1200
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['MA120'] = df['Close'].rolling(window=120).mean()
    df['MA240'] = df['Close'].rolling(window=240).mean()
    df['MA1200'] = df['Close'].rolling(window=1200).mean()

    # 【修訂說明 2026-11-13】【修改目的與防呆防錯原因】：
    # 新增相對於 20日、120日、240日、1200日均價的乖離率 (%)，公式：(收盤價 - N日均價) / N日均價 * 100。
    # 將均價為 0 替換為 NaN 防止除以零異常；若歷史資料長度不足（如 1y 區間不足 1200 日），自然保留 NaN 避免誤導。
    df['BIAS_20'] = ((df['Close'] - df['MA20']) / df['MA20'].replace(0, np.nan)) * 100.0
    df['BIAS_120'] = ((df['Close'] - df['MA120']) / df['MA120'].replace(0, np.nan)) * 100.0
    df['BIAS_240'] = ((df['Close'] - df['MA240']) / df['MA240'].replace(0, np.nan)) * 100.0
    df['BIAS_1200'] = ((df['Close'] - df['MA1200']) / df['MA1200'].replace(0, np.nan)) * 100.0

    # 2. KD(9)
    low_min9 = df['Low'].rolling(window=9).min()
    high_max9 = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_min9) / (high_max9 - low_min9 + 1e-9) * 100
    k_list, d_list = [], []
    k_prev, d_prev = 50.0, 50.0
    for r in rsv:
        if pd.isna(r):
            k_list.append(np.nan)
            d_list.append(np.nan)
        else:
            k = (2 / 3) * k_prev + (1 / 3) * r
            d = (2 / 3) * d_prev + (1 / 3) * k
            k_list.append(k)
            d_list.append(d)
            k_prev, d_prev = k, d
    df['K'] = k_list
    df['D'] = d_list

    # 3. MACD(12, 26, 9)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['MACD'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['OSC'] = df['DIF'] - df['MACD']

    # 4. 成交量換算 (張)
    df['Volume_Sheets'] = df['Volume'] / 1000.0

    # 5. OBV (180 日基準歸零)
    direction = np.where(
        df['Close'] > df['Close'].shift(1), 1,
        np.where(df['Close'] < df['Close'].shift(1), -1, 0)
    )
    direction[0] = 0
    df['OBV'] = (direction * df['Volume_Sheets']).cumsum()
    base_idx = -min(180, len(df))
    df['OBV'] = df['OBV'] - df['OBV'].iloc[base_idx]
    df['OBV_MA20'] = df['OBV'].rolling(window=20).mean()

    # 6. 5MA 頭底轉折點演算法
    total_rows = len(df)
    is_head, is_bottom = [False] * total_rows, [False] * total_rows
    valid_idx = [i for i in range(total_rows) if not pd.isna(df['MA5'].iloc[i])]

    if len(valid_idx) >= 2:
        curr_state = bool(df['Close'].iloc[valid_idx[0]] >= df['MA5'].iloc[valid_idx[0]])
        seg_indices = [valid_idx[0]]
        for idx in valid_idx[1:]:
            new_state = bool(df['Close'].iloc[idx] >= df['MA5'].iloc[idx])
            if new_state == curr_state:
                seg_indices.append(idx)
            else:
                seg_indices.append(idx)
                if curr_state:
                    best_head = max(seg_indices, key=lambda si: df['High'].iloc[si])
                    is_head[best_head] = True
                else:
                    best_bottom = min(seg_indices, key=lambda si: df['Low'].iloc[si])
                    is_bottom[best_bottom] = True
                curr_state = new_state
                seg_indices = [idx]

    df['Is_Head'], df['Is_Bottom'] = is_head, is_bottom

    # 7. 籌碼同步與對齊
    # 【防呆防錯備註 2026-11-10】【修訂目的】：
    # 將 Yahoo 日 K 驗證出的 full_ticker (.TW 或 .TWO) 傳遞給 sync_chip_data。
    # 避免籌碼模組因失去市場別，無腦連續輪詢證交所與櫃買中心而造成延遲與誤判。
    # 【修訂說明 2026-11-25】【修改目的與防呆防錯原因】：
    # 轉傳 `refresh_cfg` 給 `sync_chip_data`，使強制重新抓取最新資料時依據使用者勾選項目與期程增量覆蓋更新籌碼。
    inst_df, margin_df, holding_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    try:
        from data_fetcher import sync_chip_data
        chip_res = sync_chip_data(
            pure_code=pure_code,
            df_dates=df.index,
            status_placeholder=status_placeholder,
            force_refresh=force_refresh,
            full_ticker=full_ticker,
            display_days=int(display_days),
            refresh_cfg=refresh_cfg
        )
        if isinstance(chip_res, tuple):
            if len(chip_res) == 3:
                inst_df, margin_df, holding_df = chip_res
            elif len(chip_res) == 2:
                inst_df, holding_df = chip_res
    except Exception:
        pass

    # 若任一 DataFrame 缺失，由本地快取補齊
    if inst_df.empty or margin_df.empty or holding_df.empty:
        try:
            from storage import StockChipStorage
            storage = StockChipStorage(pure_code)
            if inst_df.empty and hasattr(storage, 'load_institutional_df'):
                inst_df = storage.load_institutional_df()
            if margin_df.empty and hasattr(storage, 'load_margin_df'):
                margin_df = storage.load_margin_df()
            if holding_df.empty and hasattr(storage, 'load_holding_df'):
                holding_df = storage.load_holding_df()
        except Exception:
            pass

    trade_date_strs = [pd.to_datetime(d).strftime('%Y-%m-%d') for d in df.index]

    # 法人買賣超對齊 (YYYY-MM-DD 比對；個股為張，^TWII/^TWOII 為億元)
    df['Foreign_Net'] = 0.0
    df['Trust_Net'] = 0.0
    df['Dealer_Net'] = 0.0
    if not inst_df.empty:
        inst_df['str_date'] = pd.to_datetime(inst_df['date']).dt.strftime('%Y-%m-%d')
        inst_map = inst_df.drop_duplicates(subset=['str_date']).set_index('str_date')
        df['Foreign_Net'] = [float(inst_map.loc[d, 'foreign_net']) if d in inst_map.index else 0.0 for d in trade_date_strs]
        df['Trust_Net'] = [float(inst_map.loc[d, 'trust_net']) if d in inst_map.index else 0.0 for d in trade_date_strs]
        df['Dealer_Net'] = [float(inst_map.loc[d, 'dealer_net']) if d in inst_map.index else 0.0 for d in trade_date_strs]

    # 【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
    # 1. 修改目的：為加權指數（^TWII）與櫃買指數（^TWOII）計算每日八大官股買賣超金額（`Gov8_Net`，單位：億元），
    #    自本地 SQLite `gov_index_stock_daily` 依 `trade_date` 加總 `total_wan`（萬元）並除以 `10000.0` 換算為億元。
    # 2. 防呆防錯原因：若資料庫尚無當日八大官股紀錄則平滑回傳 `0.0`，不觸發網路連線以免拖慢主計算流程。
    code_upper = str(pure_code or "").strip().upper()
    df['Gov8_Net'] = 0.0
    if code_upper in ("^TWII", "^TWOII"):
        try:
            from storage import StockChipStorage
            gov_storage = StockChipStorage(code_upper)
            if os.path.exists(gov_storage.db_path):
                with sqlite3.connect(gov_storage.db_path) as conn:
                    rows_g = conn.execute(
                        "SELECT trade_date, SUM(total_wan) FROM gov_index_stock_daily GROUP BY trade_date"
                    ).fetchall()
                gov_day_yi_map = {
                    str(r[0])[:10]: round(float(r[1] or 0.0) / 10000.0, 4)
                    for r in rows_g if r and r[0]
                }
                df['Gov8_Net'] = [gov_day_yi_map.get(d, 0.0) for d in trade_date_strs]
        except Exception:
            pass

    # 資券對齊 (YYYY-MM-DD 比對)
    df['Margin_Diff'] = 0.0
    df['Short_Diff'] = 0.0
    df['Margin_Bal'] = 0.0
    df['Short_Bal'] = 0.0
    df['Margin_Money_Diff'] = 0.0
    df['Margin_Money_Bal'] = 0.0
    df['Short_Margin_Ratio'] = np.nan
    df['Margin_Maint_Pct'] = np.nan
    df['Margin_Maint_60D_Pct'] = np.nan
    df['Short_Maint_Pct'] = np.nan
    if not margin_df.empty:
        margin_df['str_date'] = pd.to_datetime(margin_df['date']).dt.strftime('%Y-%m-%d')
        ms_map = margin_df.drop_duplicates(subset=['str_date']).set_index('str_date')
        df['Margin_Diff'] = [float(ms_map.loc[d, 'margin_diff']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Short_Diff'] = [float(ms_map.loc[d, 'short_diff']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Margin_Bal'] = [float(ms_map.loc[d, 'margin_bal']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Short_Bal'] = [float(ms_map.loc[d, 'short_bal']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        # 【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
        # 同步對齊上市/上櫃融資金額增減（Margin_Money_Diff，億元）與餘額（Margin_Money_Bal，億元）。
        if 'margin_money_diff' in ms_map.columns:
            df['Margin_Money_Diff'] = [
                float(ms_map.loc[d, 'margin_money_diff']) if d in ms_map.index and pd.notna(ms_map.loc[d, 'margin_money_diff']) else 0.0
                for d in trade_date_strs
            ]
        if 'margin_money_bal' in ms_map.columns:
            df['Margin_Money_Bal'] = [
                float(ms_map.loc[d, 'margin_money_bal']) if d in ms_map.index and pd.notna(ms_map.loc[d, 'margin_money_bal']) else 0.0
                for d in trade_date_strs
            ]
        df['Short_Margin_Ratio'] = (df['Short_Bal'] / df['Margin_Bal'].replace(0, np.nan)) * 100.0

    # 【修訂說明 2026-11-20】【修改目的與防呆防錯原因】：
    # 修改目的：大盤加權指數（^TWII）與櫃買指數（^TWOII）同步計算「融資維持率（Margin_Maint_Pct）」與「融券維持率（Short_Maint_Pct）」，
    # 以 20 日滾動成本基準（166.67% / 190.0%）推算整戶維持率折線，供籌碼頁籤資券副圖雙折線繪製。
    if code_upper in ("^TWII", "^TWOII"):
        rolling_cost = df['Close'].rolling(20, min_periods=1).mean().replace(0, np.nan)
        close_safe = df['Close'].replace(0, np.nan)
        df['Margin_Maint_Pct'] = (close_safe / rolling_cost) * 166.67
        df['Short_Maint_Pct'] = (rolling_cost / close_safe) * 190.0
    elif not code_upper.startswith("^"):
        # 【修訂說明 2026-11-23】【修改目的與防呆防錯原因】：
        # 修改目的：
        #   1. 保留全期間「融資淨增減滾動成本法（基準 166.67%）」計算每日預估融資維持率（Margin_Maint_Pct，藍色折線）；
        #   2. 新增「近 60 日滾動視窗估算季融資維持率（Margin_Maint_60D_Pct，綠色折線）」，針對每日往回取最多 60 個交易日區間，
        #      以視窗首日有融資餘額之收盤價為起算成本，依視窗內每日融資淨增減加權滾動成本單價，避免受遠期高點鎖死。
        # 防呆防錯原因：當日無融資餘額（Margin_Bal <= 0）或收盤價無效時輸出 np.nan 並重置平均成本單價，避免除以零。
        maint_vals = []
        avg_cost = np.nan
        prev_bal = 0.0
        closes_arr = [float(x) if pd.notna(x) else 0.0 for x in df['Close']]
        bals_arr = [float(x) if pd.notna(x) else 0.0 for x in df['Margin_Bal']]
        diffs_arr = [float(x) if pd.notna(x) else 0.0 for x in df['Margin_Diff']]
        for c_val, bal_val, diff_val in zip(closes_arr, bals_arr, diffs_arr):
            if bal_val <= 0 or c_val <= 0:
                avg_cost = np.nan
                prev_bal = 0.0
                maint_vals.append(np.nan)
                continue
            if pd.isna(avg_cost) or prev_bal <= 0:
                avg_cost = c_val
            elif diff_val > 0:
                base_bal = max(0.0, bal_val - diff_val)
                avg_cost = ((base_bal * avg_cost) + (diff_val * c_val)) / bal_val
            prev_bal = bal_val
            maint_vals.append((c_val / avg_cost) * 166.67 if avg_cost > 0 else np.nan)
        df['Margin_Maint_Pct'] = maint_vals

        maint_60d_vals = []
        n_bars = len(closes_arr)
        for i in range(n_bars):
            c_end = closes_arr[i]
            bal_end = bals_arr[i]
            if bal_end <= 0 or c_end <= 0:
                maint_60d_vals.append(np.nan)
                continue
            win_start = max(0, i - 60 + 1)
            win_cost = np.nan
            win_prev_bal = 0.0
            for j in range(win_start, i + 1):
                cw = closes_arr[j]
                bw = bals_arr[j]
                dw = diffs_arr[j]
                if bw <= 0 or cw <= 0:
                    win_cost = np.nan
                    win_prev_bal = 0.0
                    continue
                if pd.isna(win_cost) or win_prev_bal <= 0:
                    win_cost = cw
                elif dw > 0:
                    base_b = max(0.0, bw - dw)
                    win_cost = ((base_b * win_cost) + (dw * cw)) / bw
                win_prev_bal = bw
            maint_60d_vals.append((c_end / win_cost) * 166.67 if (not pd.isna(win_cost) and win_cost > 0) else np.nan)
        df['Margin_Maint_60D_Pct'] = maint_60d_vals

    # 大戶持股門檻（嚴格同週對齊，當週全交易日共用該週最新公告值）
    if not holding_df.empty:
        holding_df['norm_date'] = pd.to_datetime(holding_df['date']).dt.normalize()
        m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
        m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

        def calc_major_weekly_dict(levels):
            sub = holding_df[holding_df['level'].isin(levels)]
            if sub.empty:
                return {}
            sub_sorted = sub.sort_values('norm_date')
            weekly_sum = sub_sorted.groupby('norm_date')['percent'].sum().reset_index()
            weekly_sum['iso_year'] = weekly_sum['norm_date'].dt.isocalendar().year
            weekly_sum['iso_week'] = weekly_sum['norm_date'].dt.isocalendar().week
            last_in_week = weekly_sum.groupby(['iso_year', 'iso_week']).last().reset_index()
            return {(int(row['iso_year']), int(row['iso_week'])): float(row['percent']) for _, row in last_in_week.iterrows()}

        m1_dict = calc_major_weekly_dict(m1_levels)
        m2_dict = calc_major_weekly_dict(m2_levels)
        df['Major1_Pct'] = [m1_dict.get((int(d.isocalendar().year), int(d.isocalendar().week)), np.nan) for d in df.index]
        df['Major2_Pct'] = [m2_dict.get((int(d.isocalendar().year), int(d.isocalendar().week)), np.nan) for d in df.index]
    else:
        df['Major1_Pct'] = np.nan
        df['Major2_Pct'] = np.nan

    # 8. 週轉率 (%) 與總發行張數 / 有效流通張數輸出
    # 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
    # 1. 修改目的：優先採用已同步完成之集保最新一週（含有效 shares > 0）1～15 級真實股數加總作為總發行股數（resolved_shares），
    #    隨每週集保更新自動反映增資、減資、庫藏股註銷與面額變更；僅當集保尚無股數紀錄時才備援使用傳入之 shares_outstanding。
    #    同時將 Total_Shares 與 Effective_Float_Shares（張）寫入 df，供 chart_builder.py 於大戶線旁標示「(1%約=xxxx張)」。
    # 2. 防呆防錯原因：先過濾 percent > 0 且非 NaN 之有效週別再取最近 15 週最小值，避免中間缺值週（0 或 NaN）誤當最小持股比例，並設上限 99.0% 防止除以零。
    resolved_shares = 0.0
    if not holding_df.empty and 'shares' in holding_df.columns and 'level' in holding_df.columns:
        sh_series = pd.to_numeric(holding_df['shares'], errors='coerce').fillna(0.0)
        lvl_series = pd.to_numeric(holding_df['level'], errors='coerce').fillna(0).astype(int)
        valid_sh_df = holding_df[(lvl_series >= 1) & (lvl_series <= 15) & (sh_series > 0)].copy()
        if not valid_sh_df.empty:
            valid_sh_df['shares_num'] = pd.to_numeric(valid_sh_df['shares'], errors='coerce').fillna(0.0)
            valid_sh_df['norm_date'] = pd.to_datetime(valid_sh_df['date']).dt.normalize()
            latest_tdcc_dt = valid_sh_df['norm_date'].max()
            tdcc_sum = float(valid_sh_df[valid_sh_df['norm_date'] == latest_tdcc_dt]['shares_num'].sum())
            if tdcc_sum > 0:
                resolved_shares = tdcc_sum

    if resolved_shares <= 0 and shares_outstanding and float(shares_outstanding) > 0:
        resolved_shares = float(shares_outstanding)

    df['Total_Shares'] = 0.0
    df['Effective_Float_Shares'] = 0.0
    if resolved_shares > 0:
        total_sheets = resolved_shares / 1000.0
        min_major1000_pct = 0.0
        if not holding_df.empty and 'level' in holding_df.columns and 'percent' in holding_df.columns:
            pct_series = pd.to_numeric(holding_df['percent'], errors='coerce')
            sub_1000 = holding_df[(holding_df['level'] == 15) & pct_series.notna() & (pct_series > 0)].copy()
            if not sub_1000.empty:
                sub_1000['percent'] = pd.to_numeric(sub_1000['percent'], errors='coerce')
                sub_1000['norm_date'] = pd.to_datetime(sub_1000['date']).dt.normalize()
                weekly_1000 = (
                    sub_1000.sort_values('norm_date')
                    .groupby('norm_date')['percent']
                    .sum()
                )
                valid_1000 = weekly_1000[weekly_1000 > 0].tail(15)
                if not valid_1000.empty:
                    min_major1000_pct = min(99.0, max(0.0, float(valid_1000.min())))

        effective_sheets = total_sheets * (1.0 - min_major1000_pct / 100.0)
        df['Total_Shares'] = total_sheets
        df['Effective_Float_Shares'] = effective_sheets
        if effective_sheets > 0:
            df['Turnover_Rate'] = (df['Volume_Sheets'] / effective_sheets) * 100.0
        else:
            df['Turnover_Rate'] = 0.0
    else:
        df['Turnover_Rate'] = 0.0

    return df
## EOF indicators.py
