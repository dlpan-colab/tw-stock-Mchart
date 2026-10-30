"""
台股技術與籌碼分析系統 - Plotly 圖表繪製模組
"""

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202610301100"

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

def create_stock_chart(df: pd.DataFrame, stock_name: str, stock_code: str) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()

    fig = make_subplots(
        rows=8, cols=1, shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.38, 0.11, 0.09, 0.09, 0.09, 0.09, 0.08, 0.07],
        subplot_titles=(
            f"{stock_code} {stock_name} 技術與籌碼分析",
            "成交量", "外資", "投信", "自營", "資券", "KD / MACD", ">=1000大戶"
        )
    )

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
                x=heads.index, y=heads['High'] * 1.01, mode='text', text=['{頭}']*len(heads),
                textfont=dict(color='#26a69a', size=12), name='波段高點'
            ), row=1, col=1)
        if not bottoms.empty:
            fig.add_trace(go.Scatter(
                x=bottoms.index, y=bottoms['Low'] * 0.99, mode='text', text=['{底}']*len(bottoms),
                textfont=dict(color='#ef5350', size=12), name='波段低點'
            ), row=1, col=1)

    colors = ['#ef5350' if c >= o else '#26a69a' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(
        x=df.index, y=df['Volume_Sheets'], name='成交量', marker_color=colors
    ), row=2, col=1)

    if 'Turnover_Rate' in df.columns:
        t_rate = df['Turnover_Rate']
        t10_20 = df[(t_rate >= 10.0) & (t_rate < 20.0)]
        t20_up = df[t_rate >= 20.0]

        if not t10_20.empty:
            fig.add_trace(go.Scatter(
                x=t10_20.index, y=t10_20['Volume_Sheets'] * 1.05, mode='markers',
                marker=dict(symbol='triangle-up', size=9, color='#29b6f6'),
                name='換手率 10-20%'
            ), row=2, col=1)

        if not t20_up.empty:
            fig.add_trace(go.Scatter(
                x=t20_up.index, y=t20_up['Volume_Sheets'] * 1.05, mode='markers',
                marker=dict(symbol='triangle-down', size=9, color='#ffee58'),
                name='換手率 >= 20%'
            ), row=2, col=1)

    if 'Foreign_Net' in df.columns:
        f_colors = ['#ef5350' if val >= 0 else '#26a69a' for val in df['Foreign_Net']]
        fig.add_trace(go.Bar(x=df.index, y=df['Foreign_Net'], name='外資', marker_color=f_colors), row=3, col=1)

    if 'Trust_Net' in df.columns:
        t_colors = ['#ef5350' if val >= 0 else '#26a69a' for val in df['Trust_Net']]
        fig.add_trace(go.Bar(x=df.index, y=df['Trust_Net'], name='投信', marker_color=t_colors), row=4, col=1)

    if 'Dealer_Net' in df.columns:
        d_colors = ['#ef5350' if val >= 0 else '#26a69a' for val in df['Dealer_Net']]
        fig.add_trace(go.Bar(x=df.index, y=df['Dealer_Net'], name='自營', marker_color=d_colors), row=5, col=1)

    if 'Margin_Diff' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Margin_Diff'], name='融資增減', marker_color='#ef5350'), row=6, col=1)
    if 'Short_Diff' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Short_Diff'], name='融券增減', marker_color='#26a69a'), row=6, col=1)

    if 'K' in df.columns and 'D' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], name='K', line=dict(color='#ffa726', width=1)), row=7, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], name='D', line=dict(color='#29b6f6', width=1)), row=7, col=1)

    if 'Major1_Pct' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['Major1_Pct'], name='大戶比例', line=dict(color='#ab47bc', width=1.5)), row=8, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        height=1100,
        margin=dict(l=40, r=20, t=30, b=20),
        showlegend=False
    )

    return fig
