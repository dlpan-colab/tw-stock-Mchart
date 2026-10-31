"""
chart_builder.py - Plotly 圖表繪製與資訊區排版模組
版本: cha_202610311200
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

MODULE_VERSION = "cha_202610311200"

def render_master_chart(df: pd.DataFrame, stock_info: dict, m1: int = 1000, m2: int = 400) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()

    # 1. 標題識別
    market_raw = stock_info.get("market", "")
    market_str = "市" if "市" in market_raw else "櫃"
    stock_name = stock_info.get("name", "")
    stock_code = stock_info.get("code", "")
    main_title = f"{stock_name}({stock_code})({market_str})"

    # 2. 欄位安全提取函式
    def find_col(possible_names):
        for name in possible_names:
            if name in df.columns:
                return name
        return None

    col_vol = find_col(['Volume', 'volume', '成交量', 'Vol'])
    col_k = find_col(['K', 'k', 'slowk'])
    col_d = find_col(['D', 'd', 'slowd'])
    col_obv = find_col(['OBV', 'obv'])
    col_dif = find_col(['DIF', 'dif', 'macd'])
    col_macd = find_col(['MACD', 'macd_signal', 'signal'])
    col_osc = find_col(['OSC', 'osc', 'macd_hist', 'hist'])

    col_for = find_col(['Foreign_Buy', 'foreign_net'])
    col_tru = find_col(['Trust_Buy', 'trust_net'])
    col_dea = find_col(['Dealer_Buy', 'dealer_net'])

    col_mdiff = find_col(['Margin_Diff', 'margin_diff'])
    col_sdiff = find_col(['Short_Diff', 'short_diff'])
    col_mratio = find_col(['Margin_Short_Ratio', 'margin_short_ratio'])

    col_m1 = find_col([f'Big_{m1}_Ratio', f'big_{m1}_ratio'])
    col_m2 = find_col([f'Big_{m2}_Ratio', f'big_{m2}_ratio'])

    # 3. 建立 5 個獨立子圖列，拉大間距防止任何重疊
    # Row 1: K線 + 均線
    # Row 2: 成交量 (Volume) + KD/OBV/MACD (隨游標即時跳動顯示)
    # Row 3: 法人買賣超 (外資/投信/自營)
    # Row 4: 資券增減
    # Row 5: 大戶持股比例
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.38, 0.16, 0.15, 0.15, 0.16]
    )

    # ------------------ Row 1: 主圖 (K線 + 均線) ------------------
    # 自訂 hover 顯示格式
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name="K線",
        increasing_line_color='#e12f2f',
        decreasing_line_color='#2ca02c',
        hoverinfo='x+y+text'
    ), row=1, col=1)

    for ma_name, color in [('MA5', '#f39c12'), ('MA20', '#2980b9'), ('MA60', '#8e44ad')]:
        if ma_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma_name],
                name=ma_name,
                line=dict(color=color, width=1.2),
                hoverinfo='name+y'
            ), row=1, col=1)

    # ------------------ Row 2: 成交量 + 技術指標 ------------------
    # 成交量柱狀圖 (依漲跌著色)
    if col_vol:
        vol_colors = np.where(df['Close'] >= df['Open'], '#e12f2f', '#2ca02c')
        fig.add_trace(go.Bar(
            x=df.index, y=df[col_vol],
            name="成交量",
            marker_color=vol_colors,
            opacity=0.6,
            hoverinfo='name+y'
        ), row=2, col=1)

    # KD 指標疊加
    if col_k and col_d:
        fig.add_trace(go.Scatter(x=df.index, y=df[col_k], name="K(9)", line=dict(color='#e74c3c', width=1.1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df[col_d], name="D(9)", line=dict(color='#3498db', width=1.1)), row=2, col=1)

    # ------------------ Row 3: 法人買賣超 ------------------
    if col_for:
        fig.add_trace(go.Bar(x=df.index, y=df[col_for], name="外資(張)", marker_color='#d63031'), row=3, col=1)
    if col_tru:
        fig.add_trace(go.Bar(x=df.index, y=df[col_tru], name="投信(張)", marker_color='#0984e3'), row=3, col=1)
    if col_dea:
        fig.add_trace(go.Bar(x=df.index, y=df[col_dea], name="自營(張)", marker_color='#fdcb6e'), row=3, col=1)

    fig.update_yaxes(tickformat=".2s", row=3, col=1)

    # ------------------ Row 4: 資券增減 ------------------
    if col_mdiff:
        fig.add_trace(go.Bar(x=df.index, y=df[col_mdiff], name="資增減(張)", marker_color='#e17055'), row=4, col=1)
    if col_sdiff:
        fig.add_trace(go.Bar(x=df.index, y=df[col_sdiff], name="券增減(張)", marker_color='#00cec9'), row=4, col=1)

    # ------------------ Row 5: 大戶持股比例 ------------------
    if col_m1:
        fig.add_trace(go.Scatter(x=df.index, y=df[col_m1], name=f"≥{m1}張%", line=dict(color='#d63031', width=1.5)), row=5, col=1)
    if col_m2:
        fig.add_trace(go.Scatter(x=df.index, y=df[col_m2], name=f"≥{m2}張%", line=dict(color='#0984e3', width=1.5)), row=5, col=1)

    # 頂部僅保留股票主標題，其餘資訊由統一 Hover 隨游標即時連動
    annotations = [
        dict(
            text=f"<b>{main_title}</b>",
            xref="paper", yref="paper",
            x=0.01, y=1.02,
            showarrow=False,
            font=dict(size=15, color="#222222"),
            xanchor="left", yanchor="bottom"
        )
    ]

    fig.update_layout(
        height=920,
        annotations=annotations,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=45, r=20, t=35, b=25),
        barmode="group",
        hovermode="x unified"  # 核心：游標懸停時，貫穿所有副圖同步動態顯示各項指標數值
    )

    # 全子圖垂直十字準線同步貫穿
    fig.update_xaxes(
        type='date',
        tickformat="%Y-%m-%d",
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikethickness=1,
        spikedash='dash',
        spikecolor='#555555'
    )

    return fig
