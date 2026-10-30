"""
台股技術與籌碼分析系統 - Plotly 圖表繪製模組
"""

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202610300900"

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

def create_stock_chart(df: pd.DataFrame, stock_name: str, stock_code: str) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()

    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.45, 0.15, 0.13, 0.13, 0.14]
    )

    # 1. 主圖：K線與均線、轉折高低點
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name='K線',
        increasing_line_color='#ef5350', increasing_fillcolor='#ef5350',
        decreasing_line_color='#26a69a', decreasing_fillcolor='#26a69a'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], name='MA5', line=dict(color='#ffa726', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name='MA20', line=dict(color='#29b6f6', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], name='MA60', line=dict(color='#ab47bc', width=1.5)), row=1, col=1)

    if 'Is_Head' in df.columns and 'Is_Bottom' in df.columns:
        heads = df[df['Is_Head']]
        bottoms = df[df['Is_Bottom']]
        if not heads.empty:
            fig.add_trace(go.Scatter(
                x=heads.index, y=heads['High'] * 1.01, mode='markers',
                marker=dict(symbol='triangle-down', size=8, color='#ef5350'), name='波段高點'
            ), row=1, col=1)
        if not bottoms.empty:
            fig.add_trace(go.Scatter(
                x=bottoms.index, y=bottoms['Low'] * 0.99, mode='markers',
                marker=dict(symbol='triangle-up', size=8, color='#26a69a'), name='波段低點'
            ), row=1, col=1)

    # 2. 成交量與換手率標示 (10%~20% 藍色正三角 ▲, >=20% 黃色倒三角 ▼)
    colors = ['#ef5350' if c >= o else '#26a69a' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(
        x=df.index, y=df['Volume'], name='成交量', marker_color=colors
    ), row=2, col=1)

    if 'Turnover_Rate' in df.columns:
        t_rate = df['Turnover_Rate']
        t10_20 = df[(t_rate >= 10.0) & (t_rate < 20.0)]
        t20_up = df[t_rate >= 20.0]

        if not t10_20.empty:
            fig.add_trace(go.Scatter(
                x=t10_20.index, y=t10_20['Volume'] * 1.05, mode='markers',
                marker=dict(symbol='triangle-up', size=9, color='#29b6f6'),
                name='換手率 10-20%'
            ), row=2, col=1)

        if not t20_up.empty:
            fig.add_trace(go.Scatter(
                x=t20_up.index, y=t20_up['Volume'] * 1.05, mode='markers',
                marker=dict(symbol='triangle-down', size=9, color='#ffee58'),
                name='換手率 >= 20%'
            ), row=2, col=1)

    # 3. 三大法人買賣超
    if all(col in df.columns for col in ['Foreign_Net', 'Trust_Net', 'Dealer_Net']):
        fig.add_trace(go.Bar(x=df.index, y=df['Foreign_Net'], name='外資買賣超', marker_color='#ab47bc'), row=3, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df['Trust_Net'], name='投信買賣超', marker_color='#ff7043'), row=3, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df['Dealer_Net'], name='自營商買賣超', marker_color='#26a69a'), row=3, col=1)

    # 4. 資券餘額
    if all(col in df.columns for col in ['Margin_Diff', 'Short_Diff']):
        fig.add_trace(go.Bar(x=df.index, y=df['Margin_Diff'], name='融資增減', marker_color='#ef5350'), row=4, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df['Short_Diff'], name='融券增減', marker_color='#26a69a'), row=4, col=1)

    # 5. KD / MACD 或 集保大戶持股
    if 'K' in df.columns and 'D' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], name='K', line=dict(color='#ffa726', width=1)), row=5, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], name='D', line=dict(color='#29b6f6', width=1)), row=5, col=1)

    fig.update_layout(
        title=f"{stock_code} {stock_name} 技術與籌碼分析",
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        height=900,
        margin=dict(l=50, r=30, t=50, b=30)
    )

    return fig
