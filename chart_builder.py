"""
chart_builder.py - Plotly 圖表繪製與資訊區排版模組
版本: cha_202610311145
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

MODULE_VERSION = "cha_202610311145"

def render_master_chart(df: pd.DataFrame, stock_info: dict, m1: int = 1000, m2: int = 400) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()

    last_row = df.iloc[-1]
    
    # 取得日期字串 (YYYY-MM-DD)
    if hasattr(last_row.name, "strftime"):
        date_str = last_row.name.strftime("%Y-%m-%d")
    elif "Date" in df.columns:
        date_str = str(last_row["Date"])[:10]
    else:
        date_str = str(last_row.name)[:10]

    # 1. 主標題：[中文名](代碼)(市/櫃)
    market_raw = stock_info.get("market", "")
    market_str = "市" if "市" in market_raw else "櫃"
    stock_name = stock_info.get("name", "")
    stock_code = stock_info.get("code", "")
    main_title = f"{stock_name}({stock_code})({market_str})"

    # 2. 第二塊資訊區數值提取 (支援大小寫相容)
    def get_val(keys, default=0.0):
        for k in keys:
            if k in last_row and pd.notnull(last_row[k]):
                return last_row[k]
        return default

    k_v = get_val(['K', 'k', 'slowk'])
    d_v = get_val(['D', 'd', 'slowd'])
    obv_v = get_val(['OBV', 'obv'])
    dif_v = get_val(['DIF', 'dif', 'macd'])
    macd_v = get_val(['MACD', 'macd_signal', 'signal'])
    osc_v = get_val(['OSC', 'osc', 'macd_hist', 'hist'])

    obv_str = f"{int(obv_v):,}" if obv_v != 0 else "0"
    info_block_2 = (
        f"<b>{date_str} KD(9) K:{k_v:.1f} D:{d_v:.1f} | OBV:{obv_str}</b><br>"
        f"<b>MACD DIF:{dif_v:.2f} MACD:{macd_v:.2f} OSC:{osc_v:.2f}</b>"
    )

    # 3. 第三塊資訊區數值提取 (三行排版防遮蔽)
    margin_diff = get_val(['Margin_Diff', 'margin_diff'])
    short_diff = get_val(['Short_Diff', 'short_diff'])
    margin_ratio = get_val(['Margin_Short_Ratio', 'margin_short_ratio'])

    foreign_v = int(get_val(['Foreign_Buy', 'foreign_net']))
    trust_v = int(get_val(['Trust_Buy', 'trust_net']))
    dealer_v = int(get_val(['Dealer_Buy', 'dealer_net']))

    m1_v = get_val([f'Big_{m1}_Ratio', f'big_{m1}_ratio'])
    m2_v = get_val([f'Big_{m2}_Ratio', f'big_{m2}_ratio'])

    info_block_3 = (
        f"<b>{date_str} 資券[千張]資:{margin_diff/1000.0:+.3f} 券:{short_diff/1000.0:+.3f} 券資比:{margin_ratio:.2f}%</b><br>"
        f"<b>法人集保[張]外資:{foreign_v:+d} 投信:{trust_v:+d} 自營:{dealer_v:+d}</b><br>"
        f"<b>大戶持股比(%) ≥{m1}張: {m1_v:.2f}% ≥{m2}張: {m2_v:.2f}%</b>"
    )

    # 建立 5 列子圖，設定充足間距
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.38, 0.15, 0.15, 0.15, 0.17]
    )

    # Row 1: 主圖 (K線 + 均線)
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name="K線",
        increasing_line_color='#e12f2f',
        decreasing_line_color='#2ca02c'
    ), row=1, col=1)

    for ma_name, color in [('MA5', '#f39c12'), ('MA20', '#2980b9'), ('MA60', '#8e44ad')]:
        if ma_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma_name],
                name=ma_name,
                line=dict(color=color, width=1.2)
            ), row=1, col=1)

    # Row 2: 第二區走勢 (KD)
    col_k = 'K' if 'K' in df.columns else ('k' if 'k' in df.columns else None)
    col_d = 'D' if 'D' in df.columns else ('d' if 'd' in df.columns else None)
    if col_k and col_d:
        fig.add_trace(go.Scatter(x=df.index, y=df[col_k], name="K", line=dict(color='#e74c3c', width=1.2)), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df[col_d], name="D", line=dict(color='#3498db', width=1.2)), row=2, col=1)

    # Row 3: 法人買賣超 (外資/投信/自營)
    for f_col, col_name, c in [('Foreign_Buy', '外資', '#d63031'), ('Trust_Buy', '投信', '#0984e3'), ('Dealer_Buy', '自營', '#fdcb6e')]:
        if f_col in df.columns:
            fig.add_trace(go.Bar(x=df.index, y=df[f_col], name=col_name, marker_color=c), row=3, col=1)

    # 法人 Y 軸規格：超過 1000 標示為 K
    fig.update_yaxes(tickformat=".2s", row=3, col=1)

    # Row 4: 資券增減
    if 'Margin_Diff' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Margin_Diff'], name="融資增減", marker_color='#e17055'), row=4, col=1)
    if 'Short_Diff' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Short_Diff'], name="融券增減", marker_color='#00cec9'), row=4, col=1)

    # Row 5: 大戶持股比例
    col_m1 = f'Big_{m1}_Ratio'
    col_m2 = f'Big_{m2}_Ratio'
    if col_m1 in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[col_m1], name=f"≥{m1}張%", line=dict(color='#d63031', width=1.5)), row=5, col=1)
    if col_m2 in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[col_m2], name=f"≥{m2}張%", line=dict(color='#0984e3', width=1.5)), row=5, col=1)

    # 使用 Layout Annotations 放置標題與資訊區，避免重疊穿透
    annotations = [
        # 主標題 (置於主圖上方)
        dict(
            text=f"<b>{main_title}</b>",
            xref="paper", yref="paper",
            x=0.01, y=1.02,
            showarrow=False,
            font=dict(size=15, color="#333333"),
            xanchor="left", yanchor="bottom"
        ),
        # 第二塊資訊區 (置於主圖與第二區之間)
        dict(
            text=info_block_2,
            xref="paper", yref="paper",
            x=0.01, y=0.62,
            showarrow=False,
            font=dict(size=12, color="#444444"),
            xanchor="left", yanchor="bottom",
            align="left"
        ),
        # 第三塊資訊區 (置於資券圖與大戶圖之間)
        dict(
            text=info_block_3,
            xref="paper", yref="paper",
            x=0.01, y=0.17,
            showarrow=False,
            font=dict(size=12, color="#444444"),
            xanchor="left", yanchor="bottom",
            align="left"
        )
    ]

    fig.update_layout(
        height=950,
        annotations=annotations,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=45, r=20, t=45, b=30),
        hovermode="x unified",
        barmode="group"
    )

    fig.update_xaxes(
        type='date',
        tickformat="%Y-%m-%d"
    )

    return fig
