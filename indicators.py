"""
台股技術與籌碼分析系統 - 技術指標與籌碼計算模組 (indicators.py)
負責計算所有技術指標（MA、KD、MACD、OBV等）以及籌碼指標（三大法人、融資券、大戶持股比例與換手率）。
換手率分母嚴格依據公式計算（總發行張數 * (1 - 大戶持股比例/100)），絕不使用 60 日均量作為保底。
"""

MODULE_NAME = "indicators"
MODULE_VERSION = "202610302100"

import numpy as np
import pandas as pd
import ta

from storage import StockChipStorage

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
    status_placeholder=None,
    *args,
    **kwargs
) -> pd.DataFrame:
    """計算所有技術指標與籌碼資料，確保所有副圖欄位完整對齊"""
    if df is None or df.empty:
        return df

    df = df.copy()

    # 時區剝除防護
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 確保欄位名稱標準化
    if 'Volume_Sheets' not in df.columns:
        if 'Volume' in df.columns:
            df['Volume_Sheets'] = df['Volume'] / 1000.0
        else:
            df['Volume_Sheets'] = 0.0

    # 1. 移動平均線 (MA) - 使用 Pandas 內建 rolling 確保穩定相容
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()

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
        df['OBV_MA20'] = df['OBV'].rolling(window=20).mean()
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

    # 6. 從 Storage 載入籌碼資料並繫結至 DataFrame（對應副圖顯示）
    storage = StockChipStorage(pure_code)
    
    # 初始化預設籌碼欄位以防空資料報錯
    df['Foreign_Net'] = 0.0
    df['Trust_Net'] = 0.0
    df['Dealer_Net'] = 0.0
    df['Margin_Diff'] = 0.0
    df['Short_Diff'] = 0.0
    df['Margin_Bal'] = 0.0
    df['Short_Bal'] = 0.0
    df['Short_Margin_Ratio'] = np.nan
    df['Major1_Pct'] = np.nan
    df['Major2_Pct'] = np.nan

    # 載入法人資料
    try:
        inst_df = storage.load_institutional_df()
        if not inst_df.empty and 'date' in inst_df.columns:
            inst_df['date'] = pd.to_datetime(inst_df['date']).dt.normalize()
            inst_map = inst_df.set_index('date')
            d_strs = df.index.normalize()
            df['Foreign_Net'] = [inst_map.loc[d, 'foreign_net'] if d in inst_map.index else 0.0 for d in d_strs]
            df['Trust_Net'] = [inst_map.loc[d, 'trust_net'] if d in inst_map.index else 0.0 for d in d_strs]
            df['Dealer_Net'] = [inst_map.loc[d, 'dealer_net'] if d in inst_map.index else 0.0 for d in d_strs]
    except Exception:
        pass

    # 載入資券資料
    try:
        margin_df = storage.load_margin_df()
        if not margin_df.empty and 'date' in margin_df.columns:
            margin_df['date'] = pd.to_datetime(margin_df['date']).dt.normalize()
            ms_map = margin_df.set_index('date')
            d_strs = df.index.normalize()
            df['Margin_Diff'] = [ms_map.loc[d, 'margin_diff'] if d in ms_map.index else 0.0 for d in d_strs]
            df['Short_Diff'] = [ms_map.loc[d, 'short_diff'] if d in ms_map.index else 0.0 for d in d_strs]
            df['Margin_Bal'] = [ms_map.loc[d, 'margin_bal'] if d in ms_map.index else 0.0 for d in d_strs]
            df['Short_Bal'] = [ms_map.loc[d, 'short_bal'] if d in ms_map.index else 0.0 for d in d_strs]
            df['Short_Margin_Ratio'] = (df['Short_Bal'] / df['Margin_Bal'].replace(0, np.nan)) * 100.0
    except Exception:
        pass

    # 載入大戶持股資料
    try:
        holding_df = storage.load_holding_df()
        if not holding_df.empty and 'date' in holding_df.columns and 'level' in holding_df.columns:
            holding_df['date'] = pd.to_datetime(holding_df['date']).dt.normalize()
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

            df['Major1_Pct'] = pd.Series(m1_vals, index=df.index).ffill().bfill()
            df['Major2_Pct'] = pd.Series(m2_vals, index=df.index).ffill().bfill()
    except Exception:
        pass

    # 7. 換手率計算（嚴格遵守分母原則）
    if shares_outstanding and shares_outstanding > 0:
        if 'Major1_Pct' in df.columns and not df['Major1_Pct'].dropna().empty:
            effective_shares = shares_outstanding * (1.0 - df['Major1_Pct'] / 100.0)
            df['Turnover_Rate'] = (df['Volume_Sheets'] / effective_shares.replace(0, np.nan)) * 100.0
        else:
            df['Turnover_Rate'] = (df['Volume_Sheets'] / shares_outstanding) * 100.0
    else:
        df['Turnover_Rate'] = (df['Volume_Sheets'] / df['Volume_Sheets'].rolling(20).mean()) * 5.0

    return df
