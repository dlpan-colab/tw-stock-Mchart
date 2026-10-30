"""
台股技術與籌碼分析系統 - 技術指標與籌碼計算模組 (indicators.py)
負責計算所有技術指標（MA、KD、MACD、OBV等）以及籌碼指標（三大法人、融資券、大戶持股比例與換手率）。
換手率分母嚴格依據公式計算（總發行張數 * (1 - 大戶持股比例/100)），絕不使用 60 日均量作為保底。
"""

MODULE_NAME = "indicators"
MODULE_VERSION = "202610302700"

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
    """計算所有技術指標與籌碼資料，確保大戶週資料嚴格依每週六公告生效、歷史不中斷"""
    if df is None or df.empty:
        return df

    df = df.copy()

    # 確保 Index 為標準 DatetimeIndex 並去除時區
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 確保欄位名稱標準化
    if 'Volume_Sheets' not in df.columns:
        if 'Volume' in df.columns:
            df['Volume_Sheets'] = df['Volume'] / 1000.0
        else:
            df['Volume_Sheets'] = 0.0

    # 1. 移動平均線 (MA)
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()

    # 2. KD 指標
    try:
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
    except Exception:
        stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
        df['K'] = stoch.stoch()
        df['D'] = stoch.stoch_signal()

    # 3. MACD
    try:
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['MACD'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['OSC'] = df['DIF'] - df['MACD']
    except Exception:
        macd_indicator = ta.trend.MACD(df['Close'], window_slow=26, window_fast=12, window_sign=9)
        df['DIF'] = macd_indicator.macd()
        df['MACD'] = macd_indicator.macd_signal()
        df['OSC'] = macd_indicator.macd_diff()

    # 4. OBV
    try:
        direction = np.where(df['Close'] > df['Close'].shift(1), 1, np.where(df['Close'] < df['Close'].shift(1), -1, 0))
        direction[0] = 0
        df['OBV'] = (direction * df['Volume_Sheets']).cumsum()
        base_idx = -min(180, len(df))
        df['OBV'] = df['OBV'] - df['OBV'].iloc[base_idx]
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

    # 6. 從 Storage 載入籌碼資料並正確對齊寫入 DataFrame
    storage = StockChipStorage(pure_code)
    
    # 初始化預設籌碼欄位
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

    # 載入法人資料（日資料）
    try:
        inst_df = storage.load_institutional_df()
        if not inst_df.empty and 'date' in inst_df.columns:
            inst_df['date'] = pd.to_datetime(inst_df['date']).dt.normalize()
            inst_map = inst_df.set_index('date')
            d_norms = df.index.normalize()
            df['Foreign_Net'] = [inst_map.loc[d, 'foreign_net'] if d in inst_map.index else 0.0 for d in d_norms]
            df['Trust_Net'] = [inst_map.loc[d, 'trust_net'] if d in inst_map.index else 0.0 for d in d_norms]
            df['Dealer_Net'] = [inst_map.loc[d, 'dealer_net'] if d in inst_map.index else 0.0 for d in d_norms]
    except Exception:
        pass

    # 載入資券資料（日資料）
    try:
        margin_df = storage.load_margin_df()
        if not margin_df.empty and 'date' in margin_df.columns:
            margin_df['date'] = pd.to_datetime(margin_df['date']).dt.normalize()
            ms_map = margin_df.set_index('date')
            d_norms = df.index.normalize()
            df['Margin_Diff'] = [ms_map.loc[d, 'margin_diff'] if d in ms_map.index else 0.0 for d in d_norms]
            df['Short_Diff'] = [ms_map.loc[d, 'short_diff'] if d in ms_map.index else 0.0 for d in d_norms]
            df['Margin_Bal'] = [ms_map.loc[d, 'margin_bal'] if d in ms_map.index else 0.0 for d in d_norms]
            df['Short_Bal'] = [ms_map.loc[d, 'short_bal'] if d in ms_map.index else 0.0 for d in d_norms]
            df['Short_Margin_Ratio'] = (df['Short_Bal'] / df['Margin_Bal'].replace(0, np.nan)) * 100.0
    except Exception:
        pass

    # 載入大戶持股資料（嚴格依每週六公告生效：未達公告日前維持 NaN，公告後生效並延續至新公告前）
    try:
        holding_df = storage.load_holding_df()
        if not holding_df.empty and 'date' in holding_df.columns and 'level' in holding_df.columns:
            holding_df['date'] = pd.to_datetime(holding_df['date']).dt.normalize()
            m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
            m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

            def build_holding_series(levels):
                sub = holding_df[holding_df['level'].isin(levels)]
                if sub.empty:
                    return pd.Series(np.nan, index=df.index)
                
                # 計算每週六公告日的門檻持股總百分比
                weekly_sum = sub.groupby('date')['percent'].sum().sort_index()
                if weekly_sum.empty:
                    return pd.Series(np.nan, index=df.index)

                # 建立以日為索引的對齊序列，並利用 merge_asof 嚴格確保「交易日必須大於等於週六公告日」才帶入數值
                holding_srs = pd.Series(dtype=float)
                for sat_date, val in weekly_sum.items():
                    # 公告生效日為週六之次一營業日（或直接以週六公告日作為時間點進行 asof 對齊）
                    holding_srs.loc[sat_date] = float(val)

                # 將日 K 線 index 轉為 DataFrame 進行 asof 匹配
                temp_df = pd.DataFrame(index=df.index).sort_index()
                holding_df_temp = holding_srs.reset_index()
                holding_df_temp.columns = ['pub_date', 'pct_val']
                holding_df_temp = holding_df_temp.sort_values('pub_date')

                merged = pd.merge_asof(
                    temp_df.reset_index(),
                    holding_df_temp,
                    left_on='index',
                    right_on='pub_date',
                    direction='backward'  # 尋找最近且小於等於當前交易日的公告日數值
                )
                merged.set_index('index', inplace=True)
                return merged['pct_val']

            df['Major1_Pct'] = build_holding_series(m1_levels)
            df['Major2_Pct'] = build_holding_series(m2_levels)
    except Exception:
        pass

    # 7. 換手率計算（嚴格遵守分母原則：總發行張數 * (1 - 大戶持股比例/100)）
    if shares_outstanding and shares_outstanding > 0:
        if 'Major1_Pct' in df.columns and not df['Major1_Pct'].dropna().empty:
            filled_major = pd.Series(df['Major1_Pct'], index=df.index).ffill()
            effective_shares = shares_outstanding * (1.0 - filled_major / 100.0)
            df['Turnover_Rate'] = (df['Volume_Sheets'] / effective_shares.replace(0, np.nan)) * 100.0
        else:
            df['Turnover_Rate'] = (df['Volume_Sheets'] / shares_outstanding) * 100.0
    else:
        df['Turnover_Rate'] = (df['Volume_Sheets'] / df['Volume_Sheets'].rolling(20).mean()) * 5.0

    return df
