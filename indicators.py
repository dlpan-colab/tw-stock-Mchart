"""
indicators.py - 技術指標計算模組
版本: ind_202610311200
"""

import pandas as pd
import numpy as np

MODULE_VERSION = "ind_202610311200"

def calc_all_indicators(df: pd.DataFrame, m1: int = 1000, m2: int = 400) -> pd.DataFrame:
    """
    計算均線、KD(9)、MACD(12,26,9)、OBV 等各項技術指標
    確保欄位名稱與圖表繪製模組完全對齊
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 1. 均線計算 (MA5, MA20, MA60)
    if 'Close' in df.columns:
        df['MA5'] = df['Close'].rolling(window=5, min_periods=1).mean()
        df['MA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
        df['MA60'] = df['Close'].rolling(window=60, min_periods=1).mean()

    # 2. 成交量均線 (VMA5, VMA20)
    vol_col = None
    for c in ['Volume', 'volume', '成交量', 'Vol']:
        if c in df.columns:
            vol_col = c
            break

    if vol_col:
        df['VMA5'] = df[vol_col].rolling(window=5, min_periods=1).mean()
        df['VMA20'] = df[vol_col].rolling(window=20, min_periods=1).mean()

    # 3. KD(9) 計算
    if {'High', 'Low', 'Close'}.issubset(df.columns):
        rsv_window = 9
        low_min = df['Low'].rolling(window=rsv_window, min_periods=1).min()
        high_max = df['High'].rolling(window=rsv_window, min_periods=1).max()
        rsv = ((df['Close'] - low_min) / (high_max - low_min).replace(0, np.nan)) * 100
        rsv = rsv.fillna(50)

        k_list = []
        d_list = []
        k = 50.0
        d = 50.0
        for val in rsv:
            k = (2.0 / 3.0) * k + (1.0 / 3.0) * val
            d = (2.0 / 3.0) * d + (1.0 / 3.0) * k
            k_list.append(round(k, 2))
            d_list.append(round(d, 2))

        df['K'] = k_list
        df['D'] = d_list
        df['slowk'] = df['K']
        df['slowd'] = df['D']

    # 4. MACD(12, 26, 9) 計算
    if 'Close' in df.columns:
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['MACD'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['OSC'] = df['DIF'] - df['MACD']
        # 兼容常見欄位名
        df['macd'] = df['DIF']
        df['macd_signal'] = df['MACD']
        df['macd_hist'] = df['OSC']

    # 5. OBV 計算
    if vol_col and 'Close' in df.columns:
        price_diff = df['Close'].diff().fillna(0)
        direction = np.where(price_diff > 0, 1, np.where(price_diff < 0, -1, 0))
        df['OBV'] = (direction * df[vol_col]).cumsum()
        df['obv'] = df['OBV']

    return df

# 相容函式別名
compute_indicators = calc_all_indicators
calculate_all = calc_all_indicators
calculate_indicators = calc_all_indicators
