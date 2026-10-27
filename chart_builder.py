"""
台股技術與籌碼分析系統 - Plotly 雙圖繪製模組
負責主圖（K 線、5/20/60MA、綠色〔頭〕/紅色〔底〕、成交量柱、換手率正倒三角標記）
與副圖（9 大技術及籌碼子圖）之繪製，計算動態極值軸距，徹底移除成交量副軸換手率折線。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202610271400"

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ==========================================
# 1. 軸距動態極值邊距計算
# ==========================================
def calculate_dynamic_range(
    series_list: List[pd.Series],
    padding_ratio: float = 0.08,
    zero_symmetric: bool = False,
    min_span: float = 1.0
) -> List[float]:
    """
    動態計算子圖 Y 軸可視邊界，避免極值切邊：
    - series_list: 納入計算的序列清單
    - padding_ratio: 上下安全緩衝比例
    - zero_symmetric: 是否強制零軸對稱（適用於買賣超、OSC柱）
    - min_span: 最小軸跨度（防除以 0 或數據單一常數）
    """
    valid_data = []
    for s in series_list:
        if s is not None and not s.empty:
            s_clean = s.replace([np.inf, -np.inf], np.nan).dropna()
            if not s_clean.empty:
                valid_data.append(s_clean.values)

    if not valid_data:
        return [-1.0, 1.0]

    all_vals = np.concatenate(valid_data)
    min_val = float(np.min(all_vals))
    max_val = float(np.max(all_vals))

    if zero_symmetric:
        abs_max = max(abs(min_val), abs(max_val))
        if abs_max == 0:
            return [-min_span, min_span]
        span = abs_max * (1.0 + padding_ratio)
        return [-span, span]

    span = max_val - min_val
    if span <= 1e-6:
        return [min_val - min_span, max_val + min_span]

    return [
        min_val - span * padding_ratio,
        max_val + span * padding_ratio
    ]


# ==========================================
# 2. 建構主圖（K線、MA、頭底轉折、成交量柱、換手標記）
# ==========================================
def build_main_chart(df: pd.DataFrame, stock_name: str, stock_id: str) -> go.Figure:
    """
    建構主圖 (Row 1: K 線與均線；Row 2: 成交量柱)：
    - 徹底移除成交量副軸與換手率折線。
    - 換手率 10%~20%：成交量柱頂部標記藍色正三角（▲）。
    - 換手率 >= 20%：成交量柱頂部標記黃色倒三角（▼）。
    - 5MA 連續波段最高/最低點：分別標記綠色〔頭〕與紅色〔底〕。
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28]
    )

    dates = list(df.index)

    # 1. K 線 (紅漲綠跌，符合台股規範)
    candlestick = go.Candlestick(
        x=dates,
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        name="K線",
        increasing_line_color="#EF4444",
        increasing_fillcolor="#EF4444",
        decreasing_line_color="#10B981",
        decreasing_fillcolor="#10B981",
        showlegend=False
    )
    fig.add_trace(candlestick, row=1, col=1)

    # 2. 移動平均線 (5MA / 20MA / 60MA)
    ma_specs = [
        ("MA5", "#F59E0B", 1.2),   # 琥珀黃
        ("MA20", "#3B82F6", 1.4),  # 科技藍
        ("MA60", "#8B5CF6", 1.6),  # 尊貴紫
    ]
    for col_name, color, width in ma_specs:
        if col_name in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=df[col_name],
                    mode="lines",
                    name=col_name,
                    line=dict(color=color, width=width),
                    hoverinfo="skip",
                    showlegend=False
                ),
                row=1,
                col=1
            )

    # 3. 5MA 波段頭底標記
    # 站上 5MA 之區間最高點標記綠色〔頭〕
    head_mask = df["Is_Head"] == True
    if head_mask.any():
        head_df = df[head_mask]
        fig.add_trace(
            go.Scatter(
                x=list(head_df.index),
                y=head_df["High"] * 1.012,
                mode="text",
                name="波段頭",
                text=["頭"] * len(head_df),
                textposition="top center",
                textfont=dict(color="#10B981", size=13, family="monospace"),
                hoverinfo="skip",
                showlegend=False
            ),
            row=1,
            col=1
        )

    # 跌破 5MA 之區間最低點標記紅色〔底〕
    bottom_mask = df["Is_Bottom"] == True
    if bottom_mask.any():
        bottom_df = df[bottom_mask]
        fig.add_trace(
            go.Scatter(
                x=list(bottom_df.index),
                y=bottom_df["Low"] * 0.988,
                mode="text",
                name="波段底",
                text=["底"] * len(bottom_df),
                textposition="bottom center",
                textfont=dict(color="#EF4444", size=13, family="monospace"),
                hoverinfo="skip",
                showlegend=False
            ),
            row=1,
            col=1
        )

    # 4. 成交量柱 (隨漲跌紅綠上色)
    vol_colors = np.where(df["Close"] >= df["Open"], "#EF4444", "#10B981")
    volume_bars = go.Bar(
        x=dates,
        y=df["Volume"] / 1000.0,  # 換算為千股(張)
        name="成交量(張)",
        marker=dict(color=vol_colors, line=dict(width=0)),
        showlegend=False
    )
    fig.add_trace(volume_bars, row=2, col=1)

    # 5. 自由流通換手率門檻標記 (標於成交量柱頂部，無折線、無副軸)
    vol_in_k = df["Volume"] / 1000.0
    # 換手率 10% ~ 20%：藍色正三角 ▲
    mid_turnover_mask = df["Turnover_Flag"] == 1
    if mid_turnover_mask.any():
        mid_df = df[mid_turnover_mask]
        fig.add_trace(
            go.Scatter(
                x=list(mid_df.index),
                y=vol_in_k[mid_turnover_mask] * 1.08,
                mode="markers",
                name="換手≥10%",
                marker=dict(
                    symbol="triangle-up",
                    size=9,
                    color="#38BDF8",  # 天空藍
                    line=dict(color="#0284C7", width=1)
                ),
                hoverinfo="skip",
                showlegend=False
            ),
            row=2,
            col=1
        )

    # 換手率 >= 20%：黃色倒三角 ▼
    high_turnover_mask = df["Turnover_Flag"] == 2
    if high_turnover_mask.any():
        high_df = df[high_turnover_mask]
        fig.add_trace(
            go.Scatter(
                x=list(high_df.index),
                y=vol_in_k[high_turnover_mask] * 1.08,
                mode="markers",
                name="換手≥20%",
                marker=dict(
                    symbol="triangle-down",
                    size=10,
                    color="#FBBF24",  # 明亮金黃
                    line=dict(color="#D97706", width=1)
                ),
                hoverinfo="skip",
                showlegend=False
            ),
            row=2,
            col=1
        )

    # 動態邊距計算
    k_range = calculate_dynamic_range([df["Low"], df["High"]], padding_ratio=0.06)
    vol_range = [0, float(vol_in_k.max()) * 1.25 if not vol_in_k.empty else 1000.0]

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111827",
        plot_bgcolor="#111827",
        margin=dict(l=10, r=40, t=10, b=10),
        xaxis=dict(
            type="category",
            rangeslider=dict(visible=False),
            showgrid=True,
            gridcolor="#1F2937",
            showticklabels=False
        ),
        xaxis2=dict(
            type="category",
            rangeslider=dict(visible=False),
            showgrid=True,
            gridcolor="#1F2937",
            showticklabels=False
        ),
        yaxis=dict(
            side="right",
            range=k_range,
            showgrid=True,
            gridcolor="#1F2937",
            tickfont=dict(color="#9CA3AF", size=10)
        ),
        yaxis2=dict(
            side="right",
            range=vol_range,
            showgrid=True,
            gridcolor="#1F2937",
            tickfont=dict(color="#9CA3AF", size=9)
        ),
        hovermode="x unified",
        dragmode="pan"
    )

    return fig


# ==========================================
# 3. 建構 9 大副圖（技術與籌碼子面板）
# ==========================================
def build_sub_chart(df: pd.DataFrame) -> go.Figure:
    """
    建構 9 大技術與籌碼子圖：
    1. KD(9) (附 20/80 超買超賣虛線)
    2. MACD(12, 26, 9) (DIF, MACD, OSC紅綠柱)
    3. OBV (180日基準歸零, 附 20MA 趨勢虛線)
    4. 外資買賣超 (張)
    5. 投信買賣超 (張)
    6. 自營商買賣超 (張)
    7. 資券增減與券資比 (融資/融券柱 + 券資比折線副軸)
    8. 大戶持股門檻 1 (預設 >= 1000張持股比率)
    9. 大戶持股門檻 2 (預設 >= 400張持股比率)
    """
    fig = make_subplots(
        rows=9,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.015,
        specs=[
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": True}],   # 第 7 圖資券自帶券資比副軸
            [{"secondary_y": False}],
            [{"secondary_y": False}]
        ],
        row_heights=[0.11, 0.11, 0.11, 0.11, 0.11, 0.11, 0.15, 0.10, 0.09]
    )

    dates = list(df.index)

    # ---------------- 1. KD(9) ----------------
    if "K" in df.columns and "D" in df.columns:
        fig.add_trace(go.Scatter(x=dates, y=df["K"], line=dict(color="#F59E0B", width=1.3), name="K", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=df["D"], line=dict(color="#3B82F6", width=1.3), name="D", showlegend=False), row=1, col=1)
        # 80/20 警戒線
        fig.add_hline(y=80, line=dict(color="#EF4444", width=0.8, dash="dot"), row=1, col=1)
        fig.add_hline(y=20, line=dict(color="#10B981", width=0.8, dash="dot"), row=1, col=1)
        fig.update_yaxes(range=[-5, 105], row=1, col=1)

    # ---------------- 2. MACD ----------------
    if "OSC" in df.columns:
        osc_colors = np.where(df["OSC"] >= 0, "#EF4444", "#10B981")
        fig.add_trace(go.Bar(x=dates, y=df["OSC"], marker=dict(color=osc_colors), name="OSC", showlegend=False), row=2, col=1)
        fig.add_trace(go.Scatter(x=dates, y=df["DIF"], line=dict(color="#FBBF24", width=1.2), name="DIF", showlegend=False), row=2, col=1)
        fig.add_trace(go.Scatter(x=dates, y=df["MACD9"], line=dict(color="#60A5FA", width=1.2), name="MACD", showlegend=False), row=2, col=1)
        macd_range = calculate_dynamic_range([df["OSC"], df["DIF"], df["MACD9"]], zero_symmetric=True)
        fig.update_yaxes(range=macd_range, row=2, col=1)

    # ---------------- 3. OBV ----------------
    if "OBV" in df.columns:
        fig.add_trace(go.Scatter(x=dates, y=df["OBV"] / 1000.0, line=dict(color="#38BDF8", width=1.3), name="OBV", showlegend=False), row=3, col=1)
        if "OBV_MA20" in df.columns:
            fig.add_trace(go.Scatter(x=dates, y=df["OBV_MA20"] / 1000.0, line=dict(color="#F59E0B", width=1.1, dash="dash"), name="OBV_MA20", showlegend=False), row=3, col=1)
        obv_range = calculate_dynamic_range([df["OBV"] / 1000.0, df["OBV_MA20"] / 1000.0])
        fig.update_yaxes(range=obv_range, row=3, col=1)

    # ---------------- 4. 外資買賣超 ----------------
    f_colors = np.where(df["Foreign_Buy_Sell"] >= 0, "#EF4444", "#10B981")
    fig.add_trace(go.Bar(x=dates, y=df["Foreign_Buy_Sell"], marker=dict(color=f_colors), name="外資(張)", showlegend=False), row=4, col=1)
    fig.update_yaxes(range=calculate_dynamic_range([df["Foreign_Buy_Sell"]], zero_symmetric=True), row=4, col=1)

    # ---------------- 5. 投信買賣超 ----------------
    t_colors = np.where(df["Trust_Buy_Sell"] >= 0, "#EF4444", "#10B981")
    fig.add_trace(go.Bar(x=dates, y=df["Trust_Buy_Sell"], marker=dict(color=t_colors), name="投信(張)", showlegend=False), row=5, col=1)
    fig.update_yaxes(range=calculate_dynamic_range([df["Trust_Buy_Sell"]], zero_symmetric=True), row=5, col=1)

    # ---------------- 6. 自營商買賣超 ----------------
    d_colors = np.where(df["Dealer_Buy_Sell"] >= 0, "#EF4444", "#10B981")
    fig.add_trace(go.Bar(x=dates, y=df["Dealer_Buy_Sell"], marker=dict(color=d_colors), name="自營商(張)", showlegend=False), row=6, col=1)
    fig.update_yaxes(range=calculate_dynamic_range([df["Dealer_Buy_Sell"]], zero_symmetric=True), row=6, col=1)

    # ---------------- 7. 資券增減與券資比 ----------------
    m_diff_colors = np.where(df["Margin_Diff"] >= 0, "#F87171", "#34D399")
    fig.add_trace(go.Bar(x=dates, y=df["Margin_Diff"], marker=dict(color=m_diff_colors), name="融資增減", showlegend=False), row=7, col=1, secondary_y=False)
    # 券資比以黃色折線繪製於副軸
    fig.add_trace(go.Scatter(x=dates, y=df["Margin_Short_Ratio"], line=dict(color="#FBBF24", width=1.5), name="券資比%", showlegend=False), row=7, col=1, secondary_y=True)
    margin_diff_range = calculate_dynamic_range([df["Margin_Diff"]], zero_symmetric=True)
    ratio_range = [0, max(15.0, float(df["Margin_Short_Ratio"].max() * 1.25))]
    fig.update_yaxes(range=margin_diff_range, row=7, col=1, secondary_y=False)
    fig.update_yaxes(range=ratio_range, row=7, col=1, secondary_y=True)

    # ---------------- 8. 大戶持股門檻 1 (>=1000張) ----------------
    fig.add_trace(go.Scatter(x=dates, y=df["Large_Holders_1000"], line=dict(color="#A78BFA", width=1.8), name="大戶≥1000張%", showlegend=False), row=8, col=1)
    fig.update_yaxes(range=calculate_dynamic_range([df["Large_Holders_1000"]], padding_ratio=0.15), row=8, col=1)

    # ---------------- 9. 大戶持股門檻 2 (>=400張) ----------------
    fig.add_trace(go.Scatter(x=dates, y=df["Large_Holders_400"], line=dict(color="#F472B6", width=1.8), name="大戶≥400張%", showlegend=False), row=9, col=1)
    fig.update_yaxes(range=calculate_dynamic_range([df["Large_Holders_400"]], padding_ratio=0.15), row=9, col=1)

    # 全局副圖樣式
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111827",
        plot_bgcolor="#111827",
        margin=dict(l=10, r=40, t=10, b=15),
        hovermode="x unified",
        dragmode="pan"
    )

    for i in range(1, 10):
        fig.update_xaxes(
            type="category",
            rangeslider=dict(visible=False),
            showgrid=True,
            gridcolor="#1F2937",
            showticklabels=(i == 9),
            tickfont=dict(color="#9CA3AF", size=9),
            row=i,
            col=1
        )
        fig.update_yaxes(
            side="right",
            showgrid=True,
            gridcolor="#1F2937",
            tickfont=dict(color="#9CA3AF", size=9),
            row=i,
            col=1
        )

    return fig
