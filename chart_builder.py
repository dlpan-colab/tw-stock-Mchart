"""
chart_builder.py - Plotly 圖表繪製與資訊區跨圖同步對齊模組
版本: cha_202610311450
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

MODULE_VERSION = "cha_202610311450"

def render_master_chart(df: pd.DataFrame, stock_info: dict, m1: int = 1000, m2: int = 400) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()

    df = df.copy()

    # 1. 股票基本標記
    market_raw = stock_info.get("market", "")
    market_str = "市" if "市" in market_raw else "櫃"
    stock_name = stock_info.get("name", "")
    stock_code = stock_info.get("code", "")
    main_title = f"{stock_name}({stock_code})({market_str})"

    # 2. 欄位提取
    def get_c(candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    c_vol = get_c(['Volume', 'volume', '成交量', 'Vol'])
    c_k = get_c(['K', 'k', 'slowk'])
    c_d = get_c(['D', 'd', 'slowd'])
    c_obv = get_c(['OBV', 'obv'])
    c_dif = get_c(['DIF', 'dif', 'macd'])
    c_macd = get_c(['MACD', 'macd_signal', 'signal'])
    c_osc = get_c(['OSC', 'osc', 'macd_hist', 'hist'])

    c_for = get_c(['Foreign_Buy', 'foreign_net'])
    c_tru = get_c(['Trust_Buy', 'trust_net'])
    c_dea = get_c(['Dealer_Buy', 'dealer_net'])

    c_mdiff = get_c(['Margin_Diff', 'margin_diff'])
    c_sdiff = get_c(['Short_Diff', 'short_diff'])
    c_mratio = get_c(['Margin_Short_Ratio', 'margin_short_ratio'])

    c_m1 = get_c([f'Big_{m1}_Ratio', f'big_{m1}_ratio'])
    c_m2 = get_c([f'Big_{m2}_Ratio', f'big_{m2}_ratio'])

    dates_str = df.index.strftime('%Y-%m-%d')

    def to_safe_int(val):
        if pd.isna(val):
            return 0
        try:
            return int(round(float(val)))
        except Exception:
            return 0

    def to_safe_float(val):
        if pd.isna(val):
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    # 3. 準備三大資訊區動態文字列（精確換行，防止右側截斷）
    info1_texts = []
    info2_texts = []
    info3_texts = []

    for i in range(len(df)):
        o = to_safe_float(df['Open'].iloc[i])
        h = to_safe_float(df['High'].iloc[i])
        l = to_safe_float(df['Low'].iloc[i])
        c = to_safe_float(df['Close'].iloc[i])
        t1 = f"<b>{main_title}</b> | <b>{dates_str[i]}</b><br>開:{o:.2f} 高:{h:.2f} 低:{l:.2f} 收:{c:.2f}"
        if 'MA5' in df.columns:
            t1 += f" | MA5:{to_safe_float(df['MA5'].iloc[i]):.2f}"
        if 'MA20' in df.columns:
            t1 += f" MA20:{to_safe_float(df['MA20'].iloc[i]):.2f}"
        if 'MA60' in df.columns:
            t1 += f" MA60:{to_safe_float(df['MA60'].iloc[i]):.2f}"
        info1_texts.append(t1)

        vol = to_safe_int(df[c_vol].iloc[i]) if c_vol else 0
        k_val = to_safe_float(df[c_k].iloc[i]) if c_k else 0.0
        d_val = to_safe_float(df[c_d].iloc[i]) if c_d else 0.0
        obv_val = to_safe_int(df[c_obv].iloc[i]) if c_obv else 0
        dif_val = to_safe_float(df[c_dif].iloc[i]) if c_dif else 0.0
        macd_val = to_safe_float(df[c_macd].iloc[i]) if c_macd else 0.0
        osc_val = to_safe_float(df[c_osc].iloc[i]) if c_osc else 0.0
        t2 = f"成交量:{vol:,} | KD(9) K:{k_val:.1f} D:{d_val:.1f}<br>OBV:{obv_val:,} | DIF:{dif_val:.2f} MACD:{macd_val:.2f} OSC:{osc_val:.2f}"
        info2_texts.append(t2)

        md = to_safe_int(df[c_mdiff].iloc[i]) if c_mdiff else 0
        sd = to_safe_int(df[c_sdiff].iloc[i]) if c_sdiff else 0
        mr = to_safe_float(df[c_mratio].iloc[i]) if c_mratio else 0.0
        fb = to_safe_int(df[c_for].iloc[i]) if c_for else 0
        tb = to_safe_int(df[c_tru].iloc[i]) if c_tru else 0
        db = to_safe_int(df[c_dea].iloc[i]) if c_dea else 0
        m1_r = to_safe_float(df[c_m1].iloc[i]) if c_m1 else 0.0
        m2_r = to_safe_float(df[c_m2].iloc[i]) if c_m2 else 0.0
        t3 = (f"資增減:{md:+} 券增減:{sd:+} 券資比:{mr:.1f}%<br>"
              f"外資:{fb:+} 投信:{tb:+} 自營:{db:+} | 大戶 ≥{m1}張:{m1_r:.2f}% ≥{m2}張:{m2_r:.2f}%")
        info3_texts.append(t3)

    # 4. 配置 5 層子圖結構
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.36, 0.16, 0.16, 0.16, 0.16]
    )

    # ================== Row 1: K線圖 + 均線 ==================
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name="K線",
        increasing_line_color='#e12f2f',
        decreasing_line_color='#2ca02c',
        hoverinfo='skip'
    ), row=1, col=1)

    for ma_name, color in [('MA5', '#f39c12'), ('MA20', '#2980b9'), ('MA60', '#8e44ad')]:
        if ma_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma_name],
                name=ma_name,
                line=dict(color=color, width=1.2),
                hoverinfo='skip'
            ), row=1, col=1)

    # 第一資訊區: 動態錨點
    max_p = df['High'].max() * 1.02 if 'High' in df.columns else 100
    fig.add_trace(go.Scatter(
        x=df.index, y=[max_p] * len(df),
        mode='lines',
        line=dict(width=0),
        name="",
        hovertext=info1_texts,
        hoverinfo='text',
        showlegend=False
    ), row=1, col=1)

    # ================== Row 2: 成交量副圖 ==================
    if c_vol:
        vol_colors = np.where(df['Close'] >= df['Open'], '#e12f2f', '#2ca02c')
        fig.add_trace(go.Bar(
            x=df.index, y=df[c_vol],
            name="成交量",
            marker_color=vol_colors,
            opacity=0.7,
            hoverinfo='skip'
        ), row=2, col=1)

    # 第二資訊區: 動態錨點
    max_v = df[c_vol].max() * 1.05 if c_vol else 1
    fig.add_trace(go.Scatter(
        x=df.index, y=[max_v] * len(df),
        mode='lines',
        line=dict(width=0),
        name="",
        hovertext=info2_texts,
        hoverinfo='text',
        showlegend=False
    ), row=2, col=1)

    # ================== Row 3: 法人買賣超副圖 ==================
    if c_for:
        fig.add_trace(go.Bar(x=df.index, y=df[c_for], name="外資(張)", marker_color='#d63031', hoverinfo='skip'), row=3, col=1)
    if c_tru:
        fig.add_trace(go.Bar(x=df.index, y=df[c_tru], name="投信(張)", marker_color='#0984e3', hoverinfo='skip'), row=3, col=1)
    if c_dea:
        fig.add_trace(go.Bar(x=df.index, y=df[c_dea], name="自營(張)", marker_color='#fdcb6e', hoverinfo='skip'), row=3, col=1)

    # ================== Row 4: 資券增減副圖 ==================
    if c_mdiff:
        fig.add_trace(go.Bar(x=df.index, y=df[c_mdiff], name="融資增減", marker_color='#e17055', hoverinfo='skip'), row=4, col=1)
    if c_sdiff:
        fig.add_trace(go.Bar(x=df.index, y=df[c_sdiff], name="融券增減", marker_color='#00cec9', hoverinfo='skip'), row=4, col=1)

    # 第三資訊區: 動態錨點
    fig.add_trace(go.Scatter(
        x=df.index, y=[0] * len(df),
        mode='lines',
        line=dict(width=0),
        name="",
        hovertext=info3_texts,
        hoverinfo='text',
        showlegend=False
    ), row=4, col=1)

    # ================== Row 5: 大戶持股比例副圖 ==================
    if c_m1:
        fig.add_trace(go.Scatter(x=df.index, y=df[c_m1], name=f"≥{m1}張%", line=dict(color='#d63031', width=1.5), hoverinfo='skip'), row=5, col=1)
    if c_m2:
        fig.add_trace(go.Scatter(x=df.index, y=df[c_m2], name=f"≥{m2}張%", line=dict(color='#0984e3', width=1.5), hoverinfo='skip'), row=5, col=1)

    # 5. 全局配置（拿掉死 annotations，設微透明 hoverlabel 不遮擋）
    fig.update_layout(
        height=960,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=45, r=20, t=30, b=25),
        barmode="group",
        hovermode="x",
        hoverlabel=dict(
            bgcolor="rgba(255, 255, 255, 0.88)",
            bordercolor="rgba(0,0,0,0)",
            font_size=11,
            font_family="monospace",
            align="left"
        )
    )

    # 十字虛線
    fig.update_xaxes(
        type='date',
        tickformat="%Y-%m-%d",
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikethickness=1,
        spikedash='dash',
        spikecolor='#333333'
    )

    fig.update_yaxes(
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikethickness=1,
        spikedash='dash',
        spikecolor='#333333'
    )

    return fig
