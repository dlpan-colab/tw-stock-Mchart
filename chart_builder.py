"""
chart_builder.py - Plotly 圖表繪製與資訊區跨圖同步對齊模組
版本: cha_202610311330
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

MODULE_VERSION = "cha_202610311330"

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

    # 3. 獨立拆解三大資訊區文字列 (最新一筆作為基準顯示)
    last_i = len(df) - 1

    # --- 第一資訊區: K線開高低收與均線 (對應 Row 1) ---
    o_l = to_safe_float(df['Open'].iloc[last_i])
    h_l = to_safe_float(df['High'].iloc[last_i])
    l_l = to_safe_float(df['Low'].iloc[last_i])
    c_l = to_safe_float(df['Close'].iloc[last_i])
    info1_text = f"<b>{main_title}</b> | <b>{dates_str[last_i]}</b> 開:{o_l:.2f} 高:{h_l:.2f} 低:{l_l:.2f} 收:{c_l:.2f}"
    if 'MA5' in df.columns:
        info1_text += f" | MA5:{to_safe_float(df['MA5'].iloc[last_i]):.2f}"
    if 'MA20' in df.columns:
        info1_text += f" MA20:{to_safe_float(df['MA20'].iloc[last_i]):.2f}"
    if 'MA60' in df.columns:
        info1_text += f" MA60:{to_safe_float(df['MA60'].iloc[last_i]):.2f}"

    # --- 第二資訊區: 成交量與技術指標 (對應 Row 2) ---
    vol_l = to_safe_int(df[c_vol].iloc[last_i]) if c_vol else 0
    k_l = to_safe_float(df[c_k].iloc[last_i]) if c_k else 0.0
    d_l = to_safe_float(df[c_d].iloc[last_i]) if c_d else 0.0
    obv_l = to_safe_int(df[c_obv].iloc[last_i]) if c_obv else 0
    dif_l = to_safe_float(df[c_dif].iloc[last_i]) if c_dif else 0.0
    macd_l = to_safe_float(df[c_macd].iloc[last_i]) if c_macd else 0.0
    osc_l = to_safe_float(df[c_osc].iloc[last_i]) if c_osc else 0.0
    info2_text = f"成交量:{vol_l:,} | KD(9) K:{k_l:.1f} D:{d_l:.1f} | OBV:{obv_l:,} | MACD DIF:{dif_l:.2f} MACD:{macd_l:.2f} OSC:{osc_l:.2f}"

    # --- 第三資訊區: 籌碼動能與大戶持股 (對應 Row 3/4) ---
    md_l = to_safe_int(df[c_mdiff].iloc[last_i]) if c_mdiff else 0
    sd_l = to_safe_int(df[c_sdiff].iloc[last_i]) if c_sdiff else 0
    mr_l = to_safe_float(df[c_mratio].iloc[last_i]) if c_mratio else 0.0
    fb_l = to_safe_int(df[c_for].iloc[last_i]) if c_for else 0
    tb_l = to_safe_int(df[c_tru].iloc[last_i]) if c_tru else 0
    db_l = to_safe_int(df[c_dea].iloc[last_i]) if c_dea else 0
    m1_l = to_safe_float(df[c_m1].iloc[last_i]) if c_m1 else 0.0
    m2_l = to_safe_float(df[c_m2].iloc[last_i]) if c_m2 else 0.0
    info3_text = (f"資增減:{md_l:+} 券增減:{sd_l:+} 券資比:{mr_l:.1f}% | "
                  f"外資:{fb_l:+} 投信:{tb_l:+} 自營:{db_l:+} | "
                  f"大戶 ≥{m1}張:{m1_l:.2f}% ≥{m2}張:{m2_l:.2f}%")

    # 4. 配置 5 層子圖結構
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.38, 0.16, 0.15, 0.15, 0.16]
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

    # ================== Row 5: 大戶持股比例副圖 ==================
    if c_m1:
        fig.add_trace(go.Scatter(x=df.index, y=df[c_m1], name=f"≥{m1}張%", line=dict(color='#d63031', width=1.5), hoverinfo='skip'), row=5, col=1)
    if c_m2:
        fig.add_trace(go.Scatter(x=df.index, y=df[c_m2], name=f"≥{m2}張%", line=dict(color='#0984e3', width=1.5), hoverinfo='skip'), row=5, col=1)

    # 5. 三大獨立固定資訊區標註 (分置於各自子圖上方，絕不疊壓、不產生白框浮條)
    annotations = [
        # 第一資訊區: 主圖上方
        dict(
            text=info1_text,
            xref="paper", yref="paper",
            x=0.0, y=1.03,
            showarrow=False,
            font=dict(size=12, color="#111111"),
            xanchor="left", yanchor="bottom"
        ),
        # 第二資訊區: 成交量與指標圖上方
        dict(
            text=info2_text,
            xref="paper", yref="paper",
            x=0.0, y=0.59,
            showarrow=False,
            font=dict(size=11, color="#2c3e50"),
            xanchor="left", yanchor="bottom"
        ),
        # 第三資訊區: 籌碼副圖上方
        dict(
            text=info3_text,
            xref="paper", yref="paper",
            x=0.0, y=0.39,
            showarrow=False,
            font=dict(size=11, color="#2c3e50"),
            xanchor="left", yanchor="bottom"
        )
    ]

    # 全部 trace 停用 hover（徹底移除遮蔽白框）
    fig.update_traces(hoverinfo='none')

    fig.update_layout(
        height=940,
        annotations=annotations,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=45, r=20, t=45, b=25),
        barmode="group",
        hovermode="x"  # 保持 x 軸連動以啟動十字準線
    )

    # X 軸垂直貫穿虛線
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

    # Y 軸水平十字虛線 (構成完整十字線)
    fig.update_yaxes(
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikethickness=1,
        spikedash='dash',
        spikecolor='#333333'
    )

    return fig
