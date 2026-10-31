"""
chart_builder.py - Plotly 圖表繪製與資訊區跨圖同步對齊模組
版本: cha_202610311230
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

MODULE_VERSION = "cha_202610311230"

def render_master_chart(df: pd.DataFrame, stock_info: dict, m1: int = 1000, m2: int = 400) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()

    df = df.copy()

    # 1. 股票標題資訊
    market_raw = stock_info.get("market", "")
    market_str = "市" if "市" in market_raw else "櫃"
    stock_name = stock_info.get("name", "")
    stock_code = stock_info.get("code", "")
    main_title = f"{stock_name}({stock_code})({market_str})"

    # 2. 欄位安全提取
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

    # 3. 預先組合三大資訊區動態文字列 (隨游標日期即時跳動)
    # --- 資訊區 1: K線開高低收與均線 ---
    info1_texts = []
    for i, idx in enumerate(df.index):
        o = df['Open'].iloc[i]
        h = df['High'].iloc[i]
        l = df['Low'].iloc[i]
        c = df['Close'].iloc[i]
        txt = f"<b>{dates_str[i]}</b> 開:{o:.2f} 高:{h:.2f} 低:{l:.2f} 收:{c:.2f}"
        if 'MA5' in df.columns:
            txt += f" | MA5:{df['MA5'].iloc[i]:.2f}"
        if 'MA20' in df.columns:
            txt += f" MA20:{df['MA20'].iloc[i]:.2f}"
        if 'MA60' in df.columns:
            txt += f" MA60:{df['MA60'].iloc[i]:.2f}"
        info1_texts.append(txt)

    # --- 資訊區 2: 技術指標 (KD / OBV / MACD) ---
    info2_texts = []
    for i, idx in enumerate(df.index):
        k_val = df[c_k].iloc[i] if c_k else 0.0
        d_val = df[c_d].iloc[i] if c_d else 0.0
        obv_val = df[c_obv].iloc[i] if c_obv else 0
        dif_val = df[c_dif].iloc[i] if c_dif else 0.0
        macd_val = df[c_macd].iloc[i] if c_macd else 0.0
        osc_val = df[c_osc].iloc[i] if c_osc else 0.0
        txt = (f"<b>{dates_str[i]}</b> KD(9) K:{k_val:.1f} D:{d_val:.1f} | OBV:{int(obv_val):,} | "
               f"MACD DIF:{dif_val:.2f} MACD:{macd_val:.2f} OSC:{osc_val:.2f}")
        info2_texts.append(txt)

    # --- 資訊區 3: 籌碼 (資券 / 法人 / 大戶持股) ---
    info3_texts = []
    for i, idx in enumerate(df.index):
        md = df[c_mdiff].iloc[i] if c_mdiff else 0
        sd = df[c_sdiff].iloc[i] if c_sdiff else 0
        mr = df[c_mratio].iloc[i] if c_mratio else 0.0
        fb = df[c_for].iloc[i] if c_for else 0
        tb = df[c_tru].iloc[i] if c_tru else 0
        db = df[c_dea].iloc[i] if c_dea else 0
        m1_r = df[c_m1].iloc[i] if c_m1 else 0.0
        m2_r = df[c_m2].iloc[i] if c_m2 else 0.0

        txt = (f"<b>{dates_str[i]}</b> 資增減:{int(md):+} 券增減:{int(sd):+} 券資比:{mr:.1f}%<br>"
               f"外資:{int(fb):+} 投信:{int(tb):+} 自營:{int(db):+} | "
               f"大戶持股 ≥{m1}張:{m1_r:.2f}% ≥{m2}張:{m2_r:.2f}%")
        info3_texts.append(txt)

    # 4. 配置 5 層子圖架構 (預留資訊列空間，各圖絕不重疊遮蔽)
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.38, 0.16, 0.15, 0.15, 0.16]
    )

    # ================== Row 1: K線圖 + 成交量 + 均線 ==================
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name="K線",
        increasing_line_color='#e12f2f',
        decreasing_line_color='#2ca02c',
        hoverinfo='none'
    ), row=1, col=1)

    for ma_name, color in [('MA5', '#f39c12'), ('MA20', '#2980b9'), ('MA60', '#8e44ad')]:
        if ma_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma_name],
                name=ma_name,
                line=dict(color=color, width=1.2),
                hoverinfo='none'
            ), row=1, col=1)

    # 資訊區 1 隱形連動錨點 (懸停時於游標處頂部顯示該日完整 K 線與均線)
    fig.add_trace(go.Scatter(
        x=df.index, y=[df['High'].max()] * len(df),
        mode='markers',
        marker=dict(size=0.1, opacity=0),
        name="資訊區1",
        hovertext=info1_texts,
        hoverinfo='text',
        showlegend=False
    ), row=1, col=1)

    # ================== Row 2: 成交量副圖 + 資訊區 2 ==================
    if c_vol:
        vol_colors = np.where(df['Close'] >= df['Open'], '#e12f2f', '#2ca02c')
        fig.add_trace(go.Bar(
            x=df.index, y=df[c_vol],
            name="成交量",
            marker_color=vol_colors,
            opacity=0.7,
            hoverinfo='none'
        ), row=2, col=1)

    # 資訊區 2 連動錨點 (KD / OBV / MACD 隨游標跳動)
    max_vol = df[c_vol].max() if c_vol else 1
    fig.add_trace(go.Scatter(
        x=df.index, y=[max_vol] * len(df),
        mode='markers',
        marker=dict(size=0.1, opacity=0),
        name="資訊區2",
        hovertext=info2_texts,
        hoverinfo='text',
        showlegend=False
    ), row=2, col=1)

    # ================== Row 3: 法人買賣超副圖 ==================
    if c_for:
        fig.add_trace(go.Bar(x=df.index, y=df[c_for], name="外資(張)", marker_color='#d63031', hoverinfo='none'), row=3, col=1)
    if c_tru:
        fig.add_trace(go.Bar(x=df.index, y=df[c_tru], name="投信(張)", marker_color='#0984e3', hoverinfo='none'), row=3, col=1)
    if c_dea:
        fig.add_trace(go.Bar(x=df.index, y=df[c_dea], name="自營(張)", marker_color='#fdcb6e', hoverinfo='none'), row=3, col=1)

    # ================== Row 4: 資券增減副圖 + 資訊區 3 ==================
    if c_mdiff:
        fig.add_trace(go.Bar(x=df.index, y=df[c_mdiff], name="融資增減", marker_color='#e17055', hoverinfo='none'), row=4, col=1)
    if c_sdiff:
        fig.add_trace(go.Bar(x=df.index, y=df[c_sdiff], name="融券增減", marker_color='#00cec9', hoverinfo='none'), row=4, col=1)

    # 資訊區 3 連動錨點 (資券 / 法人 / 大戶持股比 隨游標跳動)
    fig.add_trace(go.Scatter(
        x=df.index, y=[0] * len(df),
        mode='markers',
        marker=dict(size=0.1, opacity=0),
        name="資訊區3",
        hovertext=info3_texts,
        hoverinfo='text',
        showlegend=False
    ), row=4, col=1)

    # ================== Row 5: 大戶持股比例副圖 ==================
    if c_m1:
        fig.add_trace(go.Scatter(x=df.index, y=df[c_m1], name=f"≥{m1}張%", line=dict(color='#d63031', width=1.5), hoverinfo='none'), row=5, col=1)
    if c_m2:
        fig.add_trace(go.Scatter(x=df.index, y=df[c_m2], name=f"≥{m2}張%", line=dict(color='#0984e3', width=1.5), hoverinfo='none'), row=5, col=1)

    # 預設頂部標籤 (未 hover 時顯示最後一筆基線)
    last_idx = len(df) - 1
    last_date = dates_str[last_idx]
    
    annotations = [
        dict(
            text=f"<b>{main_title}</b> | {info1_texts[last_idx]}",
            xref="paper", yref="paper",
            x=0.0, y=1.03,
            showarrow=False,
            font=dict(size=13, color="#111111"),
            xanchor="left", yanchor="bottom"
        )
    ]

    fig.update_layout(
        height=940,
        annotations=annotations,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=45, r=20, t=45, b=25),
        barmode="group",
        hovermode="x unified",  # 核心：游標懸停同一日期時，全子圖統一浮出各區最新跳動資訊
        hoverlabel=dict(
            bgcolor="rgba(255, 255, 255, 0.95)",
            font_size=12,
            font_family="monospace"
        )
    )

    # 全子圖垂直十字準線強制貫穿同步對齊
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

    return fig
