"""
台股技術與籌碼分析系統 - 技術指標與量化運算模組
負責 MA5/20/60、KD(9)、MACD(12,26,9)、180日基準歸零 OBV、
5MA 連續波段頭底轉折點演算法、扣除大戶之自由流通換手率計算與 TDCC 映射。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""
# ==============================================================================
# 模組名稱: indicators
# 模組版本: 202610271630
# 核心職責: MA/KD/MACD/OBV、5MA 波段頭底辨識、換手率與集保股權分級映射
# ==============================================================================

MODULE_NAME = "indicators"
MODULE_VERSION = "202610271630"

import pandas as pd
import numpy as np

def calculate_all_indicators(df, total_shares, chip_df=None, tdcc_df=None, m1_level=1000, m2_level=400):
    """計算所有技術指標、波段轉折點、自由流通換手率與大戶持股對齊"""
    if df is None or df.empty:
        return df

    df = df.copy()

    # 1. 移動平均線 (MA)
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()

    # 2. 5MA 連續波段頭底轉折點演算法
    df['Is_Head'] = False
    df['Is_Bottom'] = False
    if len(df) >= 7:
        ma5 = df['MA5'].values
        highs = df['High'].values
        lows = df['Low'].values
        n = len(df)
        for i in range(2, n - 2):
            # 局部高點 (頭)
            if ma5[i] > ma5[i-1] and ma5[i] > ma5[i-2] and ma5[i] >= ma5[i+1] and ma5[i] > ma5[i+2]:
                df.iloc[i, df.columns.get_loc('Is_Head')] = True
            # 局部低點 (底)
            elif ma5[i] < ma5[i-1] and ma5[i] < ma5[i-2] and ma5[i] <= ma5[i+1] and ma5[i] < ma5[i+2]:
                df.iloc[i, df.columns.get_loc('Is_Bottom')] = True

    # 3. KD 指標 (9, 3, 3)
    low_min9 = df['Low'].rolling(window=9).min()
    high_max9 = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_min9) / (high_max9 - low_min9 + 1e-9) * 100.0
    rsv = rsv.fillna(50.0)

    k_vals, d_vals = [50.0], [50.0]
    for r in rsv.values[1:]:
        k = (2.0 / 3.0) * k_vals[-1] + (1.0 / 3.0) * r
        d = (2.0 / 3.0) * d_vals[-1] + (1.0 / 3.0) * k
        k_vals.append(k)
        d_vals.append(d)
    df['K'] = k_vals
    df['D'] = d_vals

    # 4. MACD 指標 (12, 26, 9)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['MACD'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['OSC'] = (df['DIF'] - df['MACD']) * 2.0

    # 5. OBV 指標 (最近 180 日為基準歸零)
    diff = df['Close'].diff().fillna(0)
    direction = np.where(diff > 0, 1, np.where(diff < 0, -1, 0))
    raw_obv = (direction * (df['Volume'] / 1000.0)).cumsum()
    # 基準歸零調整
    base_idx = max(0, len(df) - 180)
    base_val = raw_obv.iloc[base_idx] if len(raw_obv) > base_idx else 0
    df['OBV'] = raw_obv - base_val
    df['OBV_MA20'] = df['OBV'].rolling(window=20).mean()

    # 6. 集保大戶持股比例映射與自由流通換手率計算
    m1_col = f"major_{m1_level}_pct"
    m2_col = f"major_{m2_level}_pct"
    df[m1_col] = np.nan
    df[m2_col] = np.nan

    top_major_pct = 0.0
    if tdcc_df is not None and not tdcc_df.empty:
        # 依日期分組計算各門檻累計持股比例
        grouped = tdcc_df.groupby(['date', 'level'])['percent'].sum().unstack(fill_value=0)
        
        # 門檻對照 (TDCC 等級: 15=1000張以上, 14=800~999, 13=600~799, 12=400~599, 11=200~399, 10=100~199)
        level_map = {1000: 15, 800: 14, 600: 13, 400: 12, 200: 11, 100: 10}
        
        m1_lvl = level_map.get(m1_level, 15)
        m2_lvl = level_map.get(m2_level, 12)

        p1_series = grouped.loc[:, grouped.columns >= m1_lvl].sum(axis=1)
        p2_series = grouped.loc[:, grouped.columns >= m2_lvl].sum(axis=1)

        # 映射到日 K (依週別 ffill)
        tdcc_map = pd.DataFrame({'p1': p1_series, 'p2': p2_series})
        tdcc_map.index = pd.to_datetime(tdcc_map.index)

        df = df.join(tdcc_map, how='left')
        df[m1_col] = df['p1'].ffill()
        df[m2_col] = df['p2'].ffill()
        df.drop(columns=['p1', 'p2'], inplace=True, errors='ignore')

        # 取得千張大戶持股比例 (等級 15)
        p15_series = grouped.loc[:, grouped.columns >= 15].sum(axis=1)
        if not p15_series.empty:
            top_major_pct = float(p15_series.iloc[-1])

    # 換手率 (Turnover Rate): 分母扣除 >=1000張大戶鎖死籌碼
    if total_shares and total_shares > 0:
        if top_major_pct > 0:
            free_float_factor = max(0.1, (100.0 - top_major_pct) / 100.0)
        else:
            free_float_factor = 0.75  # 無大戶資料時採 0.75 保守常數
        
        free_float_shares = total_shares * free_float_factor
        df['Turnover_Rate'] = (df['Volume'] / free_float_shares) * 100.0
    else:
        df['Turnover_Rate'] = 0.0

    # 7. 合併法人與資券數據 (從 chip_df)
    if chip_df is not None and not chip_df.empty:
        chip_clean = chip_df.copy()
        chip_clean['date'] = pd.to_datetime(chip_clean['date'])
        chip_clean.set_index('date', inplace=True)
        # 挑選必要欄位合併
        cols = ['foreign_buy', 'trust_buy', 'dealer_buy', 'margin_balance', 'margin_change', 'short_balance', 'short_change', 'short_ratio']
        avail_cols = [c for c in cols if c in chip_clean.columns]
        df = df.join(chip_clean[avail_cols], how='left')
        for c in avail_cols:
            df[c] = df[c].fillna(0.0)

    return df
