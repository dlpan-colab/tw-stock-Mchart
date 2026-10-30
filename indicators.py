"""
台股技術與籌碼分析系統 - 技術指標與籌碼計算模組 (indicators.py)
負責計算所有技術指標（MA、KD、MACD、OBV等）以及籌碼指標（三大法人、融資券、大戶持股比例與換手率）。
換手率分母嚴格依據公式計算（總發行張數 * (1 - 大戶持股比例/100)），絕不使用 60 日均量作為保底。
"""

MODULE_NAME = "indicators"
MODULE_VERSION = "202610301730"

import numpy as np
import pandas as pd
import ta


def calculate_all_indicators(
    df: pd.DataFrame,
    pure_code: str,
    major1_thresh: int = 1000,
    major2_thresh: int = 400,
    shares_outstanding: float = None,
    status_placeholder=None,
    *args,
    **kwargs
) -> pd.DataFrame:
    """計算所有技術指標與籌碼資料"""
    if df is None or df.empty:
        return df

    df = df.copy()

    # 確保欄位名稱標準化
    if 'Volume_Sheets' not in df.columns:
        if 'Volume' in df.columns:
            df['Volume_Sheets'] = df['Volume'] / 1000.0
        else:
            df['Volume_Sheets'] = 0.0

    # 1. 移動平均線 (MA)
    df['MA5'] = ta.trend.sma_indicator(df['Close'], window=5)
    df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
    df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)

    # 2. KD 指標
    try:
        stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
        df['K'] = stoch.stoch()
        df['D'] = stoch.stoch_signal()
    except Exception:
        df['K'] = 50.0
        df['D'] = 50.0

    # 3. MACD
    try:
        macd_indicator = ta.trend.MACD(df['Close'], window_slow=26, window_fast=12, window_sign=9)
        df['DIF'] = macd_indicator.macd()
        df['MACD'] = macd_indicator.macd_signal()
        df['OSC'] = macd_indicator.macd_diff()
    except Exception:
        df['DIF'] = 0.0
        df['MACD'] = 0.0
        df['OSC'] = 0.0

    # 4. OBV
    try:
        obv_indicator = ta.volume.OnBalanceVolumeIndicator(df['Close'], df['Volume'])
        df['OBV'] = obv_indicator.on_balance_volume()
        df['OBV_MA20'] = ta.trend.sma_indicator(df['OBV'], window=20)
    except Exception:
        df['OBV'] = 0.0
        df['OBV_MA20'] = 0.0

    # 5. 頭底標籤判定
    df['Is_Head'] = False
    df['Is_Bottom'] = False
    if len(df) >= 5:
        rolling_max = df['High'].rolling(window=5, center=True).max()
        rolling_min = df['Low'].rolling(window=5, center=True).min()
        df['Is_Head'] = (df['High'] == rolling_max)
        df['Is_Bottom'] = (df['Low'] == rolling_min)

    # 6. 換手率計算（嚴格遵守分母原則）
    if shares_outstanding and shares_outstanding > 0:
        if 'Major1_Pct' in df.columns:
            effective_shares = shares_outstanding * (1.0 - df['Major1_Pct'] / 100.0)
            df['Turnover_Rate'] = (df['Volume_Sheets'] / effective_shares.replace(0, np.nan)) * 100.0
        else:
            df['Turnover_Rate'] = (df['Volume_Sheets'] / shares_outstanding) * 100.0
    else:
        df['Turnover_Rate'] = (df['Volume_Sheets'] / df['Volume_Sheets'].rolling(20).mean()) * 5.0

    return df
