# ==============================================================================
# 模組名稱: chart_builder
# 模組版本: 202610271610
# 核心職責: 主圖與副圖繪製、動態 Y 軸範圍計算、換手率門檻三角形標記
# ==============================================================================

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202610271610"

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_fetcher import fetch_stock_data, fetch_chip_data, fetch_tdcc_data, get_stock_chinese_name
from indicators import calculate_all_indicators

def build_split_figures(symbol, period='1y', display_days=20, base_date=None, m1_level=1000, m2_level=400, is_mobile=True, status_placeholder=None):
    """建構分離的主圖與副圖 Figure 物件，輸出給前端雙向聯動組件"""
    if status_placeholder:
        status_placeholder.info(f"正在擷取與計算 {symbol} 相關數據...")

    # 1. 抓取日 K 與股數
    df, shares = fetch_stock_data(symbol, period=period)
    if df is None or df.empty:
        return None, None, None, symbol, 0, 0

    c_name = get_stock_chinese_name(symbol)

    # 2. 籌碼與集保數據
    start_date_str = df.index[0].strftime("%Y-%m-%d")
    chip_df = fetch_chip_data(symbol, start_date_str)
    tdcc_df = fetch_tdcc_data(symbol)

    # 3. 計算所有技術指標與大戶比率
    df = calculate_all_indicators(df, shares, chip_df, tdcc_df, m1_level, m2_level)

    # 4. 基準日與顯示視窗截取
    if base_date:
        base_ts = pd.Timestamp(base_date)
        valid_idx = df.index[df.index <= base_ts]
        end_idx = len(valid_idx) - 1 if len(valid_idx) > 0 else len(df) - 1
    else:
        end_idx = len(df) - 1

    disp_n = int(display_days)
    start_idx = max(0, end_idx - disp_n + 1)
    view_df = df.iloc[start_idx:end_idx + 1]

    # 日期字串序列（供 X 軸類別型座標使用，消除休市空隙）
    date_strs = [d.strftime('%Y-%m-%d') for d in df.index]

    # --------------------------------------------------------------------------
    # 5. 建構主圖（Top Figure: K線 + 均線 + 成交量 + 頭底標籤 + 換手門檻標記）
    # --------------------------------------------------------------------------
    fig_top = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28]
    )

    # K 線
    fig_top.add_trace(go.Candlestick(
        x=date_strs,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K線",
        increasing_line_color='#e53935', increasing_fillcolor='#e53935',
        decreasing_line_color='#00e676', decreasing_fillcolor='#00e676'
    ), row=1, col=1)

    # 均線
    for ma_col, color, name in [('MA5', '#ff9800', '5MA'), ('MA20', '#29b6f6', '20MA'), ('MA60', '#ab47bc', '60MA')]:
        if ma_col in df.columns:
            fig_top.add_trace(go.Scatter(
                x=date_strs, y=df[ma_col], name=name,
                line=dict(color=color, width=1.2), hoverinfo='skip'
            ), row=1, col=1)

    # 頭底波段標記
    if 'Is_Head' in df.columns:
        heads = df[df['Is_Head']]
        if not heads.empty:
            head_dates = [d.strftime('%Y-%m-%d') for d in heads.index]
            fig_top.add_trace(go.Scatter(
                x=head_dates, y=heads['High'] * 1.015,
                mode='text', text=['〔頭〕'] * len(heads),
                textfont=dict(color='#00e676', size=11, family="sans-serif"),
                hoverinfo='skip', showlegend=False
            ), row=1, col=1)

    if 'Is_Bottom' in df.columns:
        bottoms = df[df['Is_Bottom']]
        if not bottoms.empty:
            btm_dates = [d.strftime('%Y-%m-%d') for d in bottoms.index]
            fig_top.add_trace(go.Scatter(
                x=btm_dates, y=bottoms['Low'] * 0.985,
                mode='text', text=['〔底〕'] * len(bottoms),
                textfont=dict(color='#e53935', size=11, family="sans-serif"),
                hoverinfo='skip', showlegend=False
            ), row=1, col=1)

    # 成交量柱（紅綠配色）
    vol_colors = np.where(df['Close'] >= df['Open'], '#e53935', '#00e676')
    fig_top.add_trace(go.Bar(
        x=date_strs, y=df['Volume'] / 1000.0,
        name="成交量(張)",
        marker_color=vol_colors,
        hoverinfo='skip'
    ), row=2, col=1)

    # 換手率門檻三角形標記（▲ 藍色正三角: 10%~20%, ▼ 黃色倒三角: >=20%）
    if 'Turnover_Rate' in df.columns:
        m_t10 = df[(df['Turnover_Rate'] >= 10.0) & (df['Turnover_Rate'] < 20.0)]
        if not m_t10.empty:
            t10_dates = [d.strftime('%Y-%m-%d') for d in m_t10.index]
            fig_top.add_trace(go.Scatter(
                x=t10_dates, y=(m_t10['Volume'] / 1000.0) * 1.08,
                mode='markers',
                marker=dict(symbol='triangle-up', size=8, color='#00d2ff'),
                name="換手 10~20%", hoverinfo='skip'
            ), row=2, col=1)

        m_t20 = df[df['Turnover_Rate'] >= 20.0]
        if not m_t20.empty:
            t20_dates = [d.strftime('%Y-%m-%d') for d in m_t20.index]
            fig_top.add_trace(go.Scatter(
                x=t20_dates, y=(m_t20['Volume'] / 1000.0) * 1.08,
                mode='markers',
                marker=dict(symbol='triangle-down', size=8, color='#ffeb3b'),
                name="換手 >=20%", hoverinfo='skip'
            ), row=2, col=1)

    # 主圖樣式配置
    fig_top.update_layout(
        template="plotly_dark",
        paper_bgcolor="#121824",
        plot_bgcolor="#121824",
        margin=dict(l=8, r=55, t=10, b=10),
        showlegend=False,
        hovermode="x",
        xaxis=dict(rangeslider=dict(visible=False), type='category', showgrid=True, gridcolor='#1e293b'),
        xaxis2=dict(type='category', showgrid=True, gridcolor='#1e293b'),
        yaxis=dict(side="right", showgrid=True, gridcolor='#1e293b'),
        yaxis2=dict(side="right", showgrid=True, gridcolor='#1e293b')
    )

    # --------------------------------------------------------------------------
    # 6. 建構副圖（Bottom Figure: 9 大技術與籌碼子圖）
    # --------------------------------------------------------------------------
    fig_btm = make_subplots(
        rows=9, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.015,
        row_heights=[0.11]*9
    )

    # 1. KD
    if 'K' in df.columns and 'D' in df.columns:
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df['K'], line=dict(color='#ff9800', width=1.2), name="K"), row=1, col=1)
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df['D'], line=dict(color='#29b6f6', width=1.2), name="D"), row=1, col=1)

    # 2. MACD
    if 'OSC' in df.columns:
        osc_colors = np.where(df['OSC'] >= 0, '#e53935', '#00e676')
        fig_btm.add_trace(go.Bar(x=date_strs, y=df['OSC'], marker_color=osc_colors, name="OSC"), row=2, col=1)
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df['DIF'], line=dict(color='#ffa726', width=1.1), name="DIF"), row=2, col=1)
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df['MACD'], line=dict(color='#42a5f5', width=1.1), name="MACD"), row=2, col=1)

    # 3. OBV
    if 'OBV' in df.columns:
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df['OBV'], line=dict(color='#26a69a', width=1.2), name="OBV"), row=3, col=1)
        if 'OBV_MA20' in df.columns:
            fig_btm.add_trace(go.Scatter(x=date_strs, y=df['OBV_MA20'], line=dict(color='#ffb74d', width=1, dash='dot'), name="OBV 20MA"), row=3, col=1)

    # 4. 外資買賣超
    if 'foreign_buy' in df.columns:
        f_colors = np.where(df['foreign_buy'] >= 0, '#e53935', '#00e676')
        fig_btm.add_trace(go.Bar(x=date_strs, y=df['foreign_buy'], marker_color=f_colors, name="外資"), row=4, col=1)

    # 5. 投信買賣超
    if 'trust_buy' in df.columns:
        t_colors = np.where(df['trust_buy'] >= 0, '#e53935', '#00e676')
        fig_btm.add_trace(go.Bar(x=date_strs, y=df['trust_buy'], marker_color=t_colors, name="投信"), row=5, col=1)

    # 6. 自營買賣超
    if 'dealer_buy' in df.columns:
        d_colors = np.where(df['dealer_buy'] >= 0, '#e53935', '#00e676')
        fig_btm.add_trace(go.Bar(x=date_strs, y=df['dealer_buy'], marker_color=d_colors, name="自營"), row=6, col=1)

    # 7. 資券增減與券資比
    if 'margin_change' in df.columns:
        fig_btm.add_trace(go.Bar(x=date_strs, y=df['margin_change'], marker_color='#ff5722', name="資增減"), row=7, col=1)
        fig_btm.add_trace(go.Bar(x=date_strs, y=df.get('short_change', 0), marker_color='#ffeb3b', name="券增減"), row=7, col=1)

    # 8. 大戶門檻 1 持股比例
    col_m1 = f"major_{m1_level}_pct"
    if col_m1 in df.columns:
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df[col_m1], line=dict(color='#ab47bc', width=1.3), name=f"{m1_level}張大戶%"), row=8, col=1)

    # 9. 大戶門檻 2 持股比例
    col_m2 = f"major_{m2_level}_pct"
    if col_m2 in df.columns:
        fig_btm.add_trace(go.Scatter(x=date_strs, y=df[col_m2], line=dict(color='#26c6da', width=1.3), name=f"{m2_level}張大戶%"), row=9, col=1)

    # 副圖樣式配置
    fig_btm.update_layout(
        template="plotly_dark",
        paper_bgcolor="#121824",
        plot_bgcolor="#121824",
        margin=dict(l=8, r=55, t=10, b=10),
        showlegend=False,
        hovermode="x"
    )

    for i in range(1, 10):
        fig_btm.update_xaxes(type='category', showgrid=True, gridcolor='#1e293b', row=i, col=1)
        fig_btm.update_yaxes(side="right", showgrid=True, gridcolor='#1e293b', row=i, col=1)

    return fig_top, fig_btm, df, c_name, end_idx, disp_n
