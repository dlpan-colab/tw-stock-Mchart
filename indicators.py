"""
台股技術與籌碼分析系統 - 技術指標與量化運算模組 (indicators.py) - 完整版
負責 MA5/20/60、KD(9)、MACD(12,26,9)、OBV、5MA 頭底轉折點演算法、
法人/資券資料字串精準對齊、集保分級持股比率（嚴格同週對齊）與自由流通換手率計算。
"""

MODULE_NAME = "indicators"
MODULE_VERSION = "202610301630"

import numpy as np
import pandas as pd

# 集保張數門檻等級映射表
HOLDING_LEVEL_MAP = {
    100: [8, 9, 10, 11, 12, 13, 14, 15],
    200: [9, 10, 11, 12, 13, 14, 15],
    400: [11, 12, 13, 14, 15],
    600: [12, 13, 14, 15],
    800: [13, 14, 15],
    1000: [15]
}

def calculate_all_indicators(
    df: pd.DataFrame,
    pure_code: str,
    major1_thresh: int = 1000,
    major2_thresh: int = 400,
    shares_outstanding: float = None,
    status_placeholder=None
) -> pd.DataFrame:
    """
    全量指標計算函式：完全相容 chart_builder.py 呼叫介面
    """
    if df is None or df.empty:
        return df

    # 時區剝除防護
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 1. 均線 MA5, MA20, MA60
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()

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
    direction = np.where(df['Close'] > df['Close'].shift(1), 1, np.where(df['Close'] < df['Close'].shift(1), -1, 0))
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
    try:
        from data_fetcher import sync_chip_data
        inst_df, margin_df, holding_df = sync_chip_data(pure_code, df.index, status_placeholder)
    except Exception:
        inst_df, margin_df, holding_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 統一轉換為 YYYY-MM-DD 純文字格式作為比對鍵值，杜絕型態不匹配
    trade_date_strs = [pd.to_datetime(d).strftime('%Y-%m-%d') for d in df.index]

    # --- 法人買賣超對齊 (精準字串比對) ---
    df['Foreign_Net'] = 0.0
    df['Trust_Net'] = 0.0
    df['Dealer_Net'] = 0.0
    if not inst_df.empty:
        inst_df['str_date'] = pd.to_datetime(inst_df['date']).dt.strftime('%Y-%m-%d')
        inst_map = inst_df.drop_duplicates(subset=['str_date']).set_index('str_date')
        df['Foreign_Net'] = [float(inst_map.loc[d, 'foreign_net']) if d in inst_map.index else 0.0 for d in trade_date_strs]
        df['Trust_Net'] = [float(inst_map.loc[d, 'trust_net']) if d in inst_map.index else 0.0 for d in trade_date_strs]
        df['Dealer_Net'] = [float(inst_map.loc[d, 'dealer_net']) if d in inst_map.index else 0.0 for d in trade_date_strs]

    # --- 資券對齊 (精準字串比對) ---
    df['Margin_Diff'] = 0.0
    df['Short_Diff'] = 0.0
    df['Margin_Bal'] = 0.0
    df['Short_Bal'] = 0.0
    df['Short_Margin_Ratio'] = np.nan
    if not margin_df.empty:
        margin_df['str_date'] = pd.to_datetime(margin_df['date']).dt.strftime('%Y-%m-%d')
        ms_map = margin_df.drop_duplicates(subset=['str_date']).set_index('str_date')
        df['Margin_Diff'] = [float(ms_map.loc[d, 'margin_diff']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Short_Diff'] = [float(ms_map.loc[d, 'short_diff']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Margin_Bal'] = [float(ms_map.loc[d, 'margin_bal']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Short_Bal'] = [float(ms_map.loc[d, 'short_bal']) if d in ms_map.index else 0.0 for d in trade_date_strs]
        df['Short_Margin_Ratio'] = (df['Short_Bal'] / df['Margin_Bal'].replace(0, np.nan)) * 100.0

    # --- 大戶持股門檻（嚴格同週對齊，絕不跨週填充） ---
    if not holding_df.empty:
        holding_df['norm_date'] = pd.to_datetime(holding_df['date']).dt.normalize()
        m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
        m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

        def calc_major_weekly_dict(levels):
            sub = holding_df[holding_df['level'].isin(levels)]
            if sub.empty:
                return {}
            # 每週保留該週最新一次公告值（防假日提前公告）
            sub_sorted = sub.sort_values('norm_date')
            weekly_sum = sub_sorted.groupby('norm_date')['percent'].sum().reset_index()
            weekly_sum['iso_year'] = weekly_sum['norm_date'].dt.isocalendar().year
            weekly_sum['iso_week'] = weekly_sum['norm_date'].dt.isocalendar().week
            
            last_in_week = weekly_sum.groupby(['iso_year', 'iso_week']).last().reset_index()
            return {(row['iso_year'], row['iso_week']): float(row['percent']) for _, row in last_in_week.iterrows()}

        m1_dict = calc_major_weekly_dict(m1_levels)
        m2_dict = calc_major_weekly_dict(m2_levels)

        m1_vals, m2_vals = [], []
        for d in df.index:
            iso_y, iso_w, _ = pd.to_datetime(d).isocalendar()
            # 僅精確同週匹配，當週無公告則為 NaN，絕不向後或向前補值
            m1_vals.append(m1_dict.get((iso_y, iso_w), np.nan))
            m2_vals.append(m2_dict.get((iso_y, iso_w), np.nan))

        df['Major1_Pct'] = pd.Series(m1_vals, index=df.index)
        df['Major2_Pct'] = pd.Series(m2_vals, index=df.index)
    else:
        df['Major1_Pct'] = np.nan
        df['Major2_Pct'] = np.nan

    # 8. 自由流通換手率計算
    if shares_outstanding and shares_outstanding > 0:
        if 'Major1_Pct' in df and not df['Major1_Pct'].dropna().empty:
            filled_major = df['Major1_Pct'].ffill().bfill()
            free_float_ratio = (100.0 - filled_major).clip(lower=10.0, upper=100.0) / 100.0
        elif 'Major2_Pct' in df and not df['Major2_Pct'].dropna().empty:
            filled_major = df['Major2_Pct'].ffill().bfill()
            free_float_ratio = (100.0 - filled_major).clip(lower=10.0, upper=100.0) / 100.0
        else:
            free_float_ratio = 0.75

        free_float_shares = float(shares_outstanding) * free_float_ratio
        df['Turnover_Rate'] = (df['Volume'] / free_float_shares) * 100.0
    else:
        df['Turnover_Rate'] = np.nan

    return df
