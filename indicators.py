"""
台股技術與籌碼分析系統 - 技術指標與量化運算模組 (indicators.py)
負責 MA5/20/60、KD(9)、MACD(12,26,9)、OBV、5MA 頭底轉折點演算法、
集保分級持股比率（嚴格同週對齊）與自由流通換手率計算。
"""

MODULE_NAME = "indicators"
MODULE_VERSION = "202610300900"

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

    # 4. 成交量換算
    df['Volume_Sheets'] = df['Volume'] / 1000.0

    # 5. OBV (180 日基準歸零)
    direction = np.where(df['Close'] > df['Close'].shift(1), 1, np.where(df['Close'] < df['Close'].shift(1), -1, 0))
    direction[0] = 0
    df['OBV'] = (direction * df['Volume_Sheets']).cumsum()
    base_idx = -min(180, len(df))
    df['OBV'] = df['OBV'] - df['OBV'].iloc[base_idx]
    df['OBV_MA20'] = df['OBV'].rolling(window=20).mean()

    # 6. 5MA 頭底轉折點
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

    # 7. 籌碼同步 (自 data_fetcher 抓取並解耦)
    try:
        from data_fetcher import sync_chip_data
        inst_df, margin_df, holding_df = sync_chip_data(pure_code, df.index, status_placeholder)
    except Exception:
        inst_df, margin_df, holding_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    d_strs = df.index.strftime('%Y-%m-%d')

    # 法人買賣超
    df['Foreign_Net'], df['Trust_Net'], df['Dealer_Net'] = 0.0, 0.0, 0.0
    if not inst_df.empty:
        inst_map = inst_df.copy().assign(d_str=inst_df['date'].dt.strftime('%Y-%m-%d')).set_index('d_str')
        df['Foreign_Net'] = [inst_map.loc[d, 'foreign_net'] if d in inst_map.index else 0.0 for d in d_strs]
        df['Trust_Net'] = [inst_map.loc[d, 'trust_net'] if d in inst_map.index else 0.0 for d in d_strs]
        df['Dealer_Net'] = [inst_map.loc[d, 'dealer_net'] if d in inst_map.index else 0.0 for d in d_strs]

    # 資券
    df['Margin_Diff'], df['Short_Diff'], df['Margin_Bal'], df['Short_Bal'], df['Short_Margin_Ratio'] = 0.0, 0.0, 0.0, 0.0, np.nan
    if not margin_df.empty:
        ms_map = margin_df.copy().assign(d_str=margin_df['date'].dt.strftime('%Y-%m-%d')).set_index('d_str')
        df['Margin_Diff'] = [ms_map.loc[d, 'margin_diff'] if d in ms_map.index else 0.0 for d in d_strs]
        df['Short_Diff'] = [ms_map.loc[d, 'short_diff'] if d in ms_map.index else 0.0 for d in d_strs]
        df['Margin_Bal'] = [ms_map.loc[d, 'margin_bal'] if d in ms_map.index else 0.0 for d in d_strs]
        df['Short_Bal'] = [ms_map.loc[d, 'short_bal'] if d in ms_map.index else 0.0 for d in d_strs]
        df['Short_Margin_Ratio'] = (df['Short_Bal'] / df['Margin_Bal'].replace(0, np.nan)) * 100

    # 大戶持股門檻 (嚴格同週對齊，不跨週填充)
    if not holding_df.empty:
        m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
        m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

        def calc_major_pct(levels):
            sub = holding_df[holding_df['level'].isin(levels)]
            if sub.empty:
                return {}
            res = {}
            for d, val in sub.groupby('date')['percent'].sum().items():
                iso_year, iso_week, _ = d.isocalendar()
                res[(iso_year, iso_week)] = float(val)
            return res

        m1_dict, m2_dict = calc_major_pct(m1_levels), calc_major_pct(m2_levels)
        m1_vals, m2_vals = [], []
        for d in df.index:
            y, w, _ = d.isocalendar()
            m1_vals.append(m1_dict.get((y, w), np.nan))
            m2_vals.append(m2_dict.get((y, w), np.nan))

        df['Major1_Pct'] = pd.Series(m1_vals, index=df.index)
        df['Major2_Pct'] = pd.Series(m2_vals, index=df.index)
    else:
        df['Major1_Pct'], df['Major2_Pct'] = np.nan, np.nan

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
