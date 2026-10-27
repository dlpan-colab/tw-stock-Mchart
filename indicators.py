"""
台股技術與籌碼分析系統 - 技術指標與量化運算模組
負責 MA5/20/60、KD(9)、MACD(12,26,9)、180日基準歸零 OBV、
5MA 連續波段頭底轉折點演算法、扣除大戶之自由流通換手率計算與 TDCC 映射。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "indicators"
MODULE_VERSION = "202610271400"

import datetime
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    DEFAULT_FLOAT_RATIO_FALLBACK,
    OBV_BASE_LOOKBACK,
    TURNOVER_THRESHOLD_HIGH,
    TURNOVER_THRESHOLD_MID,
)
from storage import db_manager


# ==========================================
# 1. 技術指標運算 (MA, KD, MACD, OBV)
# ==========================================
def calculate_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """計算 MA5, MA20, MA60"""
    df["MA5"] = df["Close"].rolling(window=5, min_periods=1).mean()
    df["MA20"] = df["Close"].rolling(window=20, min_periods=1).mean()
    df["MA60"] = df["Close"].rolling(window=60, min_periods=1).mean()
    return df


def calculate_kd(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """計算 KD(9)，RSV 平滑衰減計算"""
    low_n = df["Low"].rolling(window=n, min_periods=1).min()
    high_n = df["High"].rolling(window=n, min_periods=1).max()
    denom = high_n - low_n
    rsv = np.where(denom == 0, 50.0, (df["Close"] - low_n) / denom * 100.0)

    k_vals = []
    d_vals = []
    current_k = 50.0
    current_d = 50.0

    for r in rsv:
        current_k = (2.0 / 3.0) * current_k + (1.0 / 3.0) * r
        current_d = (2.0 / 3.0) * current_d + (1.0 / 3.0) * current_k
        k_vals.append(current_k)
        d_vals.append(current_d)

    df["K"] = k_vals
    df["D"] = d_vals
    return df


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """計算 MACD(12, 26, 9) 與 OSC 柱狀體"""
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = ema_fast - ema_slow
    df["MACD9"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["OSC"] = df["DIF"] - df["MACD9"]
    return df


def calculate_obv(df: pd.DataFrame, base_days: int = OBV_BASE_LOOKBACK) -> pd.DataFrame:
    """
    計算 OBV：
    以最近 180 個交易日為基準歸零，附 20MA 趨勢線。
    """
    direction = np.sign(df["Close"].diff().fillna(0))
    raw_obv = (direction * df["Volume"]).cumsum()

    # 以最近 180 日的起點歸零
    if len(raw_obv) >= base_days:
        base_val = raw_obv.iloc[-base_days]
    else:
        base_val = raw_obv.iloc[0]

    df["OBV"] = raw_obv - base_val
    df["OBV_MA20"] = df["OBV"].rolling(window=20, min_periods=1).mean()
    return df


# ==========================================
# 2. 5MA 連續波段頭底識別演算法
# ==========================================
def calculate_head_bottom_turning_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    依收盤價相對於 5MA 的連續穿越狀態進行波段切片：
    - 站上 5MA 區間 (Close >= MA5)：取該區間之最高點標記綠色〔頭〕(Is_Head = True)
    - 跌破 5MA 區間 (Close < MA5)：取該區間之最低點標記紅色〔底〕(Is_Bottom = True)
    """
    df["Is_Head"] = False
    df["Is_Bottom"] = False
    df["Head_Price"] = np.nan
    df["Bottom_Price"] = np.nan

    if "MA5" not in df.columns or len(df) < 5:
        return df

    # 1 表示站上 5MA，-1 表示跌破 5MA
    trend = np.where(df["Close"] >= df["MA5"], 1, -1)
    df["_trend"] = trend

    # 標記區間變動分組
    segment_ids = (df["_trend"] != df["_trend"].shift(1)).cumsum()
    df["_segment"] = segment_ids

    for _, group in df.groupby("_segment"):
        if group.empty:
            continue
        seg_trend = group["_trend"].iloc[0]
        if seg_trend == 1:
            # 站上區間：標記波段最高點
            max_idx = group["High"].idxmax()
            df.loc[max_idx, "Is_Head"] = True
            df.loc[max_idx, "Head_Price"] = df.loc[max_idx, "High"]
        else:
            # 跌破區間：標記波段最低點
            min_idx = group["Low"].idxmin()
            df.loc[min_idx, "Is_Bottom"] = True
            df.loc[min_idx, "Bottom_Price"] = df.loc[min_idx, "Low"]

    df.drop(columns=["_trend", "_segment"], inplace=True)
    return df


# ==========================================
# 3. 集保對齊與自由流通換手率計算
# ==========================================
def calculate_turnover_and_chips_features(
    df: pd.DataFrame,
    stock_id: str,
    shares_outstanding: float
) -> pd.DataFrame:
    """
    計算籌碼對齊與自由流通換手率：
    1. 透過 d.isocalendar() 將 TDCC 週資料對齊日 K 並向後 ffill()。
    2. 分母基準：發行股數扣除 >= 1000 張大戶持股比例 (等級 15) 作為自由流通股數；
       無資料時以 0.75 保守常數替代。
    3. 門檻標記：
       - 換手率 10% ~ 20%：標記藍色正三角 ▲ (Turnover_Flag = 1)
       - 換手率 >= 20%：標記黃色倒三角 ▼ (Turnover_Flag = 2)
    4. 關聯外資、投信、自營商及融資融券歷史數據。
    """
    # 關聯集保大戶資料 (等級 15 與等級 12-15)
    tdcc_df = db_manager.get_tdcc_data(stock_id)
    df["Large_Holders_1000"] = np.nan
    df["Large_Holders_400"] = np.nan

    if not tdcc_df.empty:
        # 整理每週等級 15 (1000張以上) 與 12-15 (400張以上)
        weekly_stats = []
        for (date_str, yw), grp in tdcc_df.groupby(["date", "year_week"]):
            lvl15_ratio = grp[grp["level"] == 15]["ratio"].sum()
            lvl400_ratio = grp[grp["level"] >= 12]["ratio"].sum()
            weekly_stats.append({
                "date": date_str,
                "year_week": yw,
                "ratio_1000": lvl15_ratio,
                "ratio_400": lvl400_ratio
            })
        w_df = pd.DataFrame(weekly_stats)
        w_df["dt"] = pd.to_datetime(w_df["date"], errors="coerce")
        w_df = w_df.dropna(subset=["dt"]).sort_values("dt")

        # 透過日 K 日期比對映射
        df_dates = pd.to_datetime(df.index)
        for i, dt in enumerate(df_dates):
            # 取小於等於該交易日最近一期週集保
            valid = w_df[w_df["dt"] <= dt]
            if not valid.empty:
                last_row = valid.iloc[-1]
                df.iloc[i, df.columns.get_loc("Large_Holders_1000")] = last_row["ratio_1000"]
                df.iloc[i, df.columns.get_loc("Large_Holders_400")] = last_row["ratio_400"]

    # 向後填補集保缺失值
    df["Large_Holders_1000"] = df["Large_Holders_1000"].ffill().bfill()
    df["Large_Holders_400"] = df["Large_Holders_400"].ffill().bfill()

    # 計算自由流通換手率
    turnover_list = []
    turnover_flag_list = []

    for idx, row in df.iterrows():
        vol = float(row.get("Volume", 0))
        holder_1000_ratio = row.get("Large_Holders_1000", np.nan)

        if pd.notna(holder_1000_ratio) and holder_1000_ratio > 0:
            free_float_factor = max(0.05, 1.0 - (holder_1000_ratio / 100.0))
        else:
            free_float_factor = DEFAULT_FLOAT_RATIO_FALLBACK

        if shares_outstanding > 0:
            effective_shares = shares_outstanding * free_float_factor
            turnover_pct = (vol / effective_shares) * 100.0
        else:
            turnover_pct = 0.0

        turnover_list.append(round(turnover_pct, 2))

        # 門檻標記判定
        if turnover_pct >= TURNOVER_THRESHOLD_HIGH:
            turnover_flag_list.append(2)  # 黃色倒三角 ▼
        elif turnover_pct >= TURNOVER_THRESHOLD_MID:
            turnover_flag_list.append(1)  # 藍色正三角 ▲
        else:
            turnover_flag_list.append(0)

    df["Turnover"] = turnover_list
    df["Turnover_Flag"] = turnover_flag_list

    # 關聯三大法人與資券資料庫
    inst_df = db_manager.get_institutional_data(stock_id)
    margin_df = db_manager.get_margin_data(stock_id)

    if not inst_df.empty:
        inst_df = inst_df.set_index("date")
        df["Foreign_Buy_Sell"] = inst_df["foreign_buy_sell"].reindex(df.index).fillna(0)
        df["Trust_Buy_Sell"] = inst_df["trust_buy_sell"].reindex(df.index).fillna(0)
        df["Dealer_Buy_Sell"] = inst_df["dealer_buy_sell"].reindex(df.index).fillna(0)
    else:
        df["Foreign_Buy_Sell"] = 0.0
        df["Trust_Buy_Sell"] = 0.0
        df["Dealer_Buy_Sell"] = 0.0

    if not margin_df.empty:
        margin_df = margin_df.set_index("date")
        df["Margin_Balance"] = margin_df["margin_balance"].reindex(df.index).fillna(0)
        df["Margin_Diff"] = df["Margin_Balance"].diff().fillna(0)
        df["Short_Balance"] = margin_df["short_balance"].reindex(df.index).fillna(0)
        df["Short_Diff"] = df["Short_Balance"].diff().fillna(0)
        df["Margin_Short_Ratio"] = margin_df["margin_short_ratio"].reindex(df.index).fillna(0)
    else:
        df["Margin_Balance"] = 0.0
        df["Margin_Diff"] = 0.0
        df["Short_Balance"] = 0.0
        df["Short_Diff"] = 0.0
        df["Margin_Short_Ratio"] = 0.0

    return df


# ==========================================
# 4. 全量指標主排程函式
# ==========================================
def process_all_indicators(df: pd.DataFrame, stock_id: str, shares_outstanding: float) -> pd.DataFrame:
    """執行全套技術指標與籌碼特徵運算管線"""
    if df.empty:
        return df

    df = calculate_moving_averages(df)
    df = calculate_kd(df)
    df = calculate_macd(df)
    df = calculate_obv(df)
    df = calculate_head_bottom_turning_points(df)
    df = calculate_turnover_and_chips_features(df, stock_id, shares_outstanding)

    return df
