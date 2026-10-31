"""
chart_builder.py - Plotly 圖表繪製與資訊區排版模組
版本: cha_311115
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

MODULE_VERSION = "cha_311115"

def render_master_chart(df: pd.DataFrame, stock_info: dict, m1: int = 1000, m2: int = 400) -> go.Figure:
    """
    df: 包含量價、技術指標(KD, MACD, OBV)、籌碼資料(法人買賣超、資券、大戶比率)
    stock_info: 字典，包含 'name', 'code', 'market'
    """
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

    # 1. K線圖標題：[中文名](代碼)(市/櫃)  例：立碁(8111)(櫃)
    market_raw = stock_info.get("market", "")
    market_str = "市" if "市" in market_raw else "櫃"
    stock_name = stock_info.get("name", "")
    stock_code = stock_info.get("code", "")
    main_title = f"{stock_name}({stock_code})({market_str})"

    # 2. 第二塊資訊區規格：
    # 第一行：YYYY-MM-DD KD(9) K:... D:... | OBV:...
    # 次行：MACD DIF:... MACD:... OSC:...
    k_val = f"{last_row.get('K', 0):.1f}"
    d_val = f"{last_row.get('D', 0):.1f}"
    obv_val = f"{int(last_row.get('OBV', 0)):,}" if pd.notnull(last_row.get('OBV')) else "0"
    
    dif_val = f"{last_row.get('DIF', 0):.2f}"
    macd_val = f"{last_row.get('MACD', 0):.2f}"
    osc_val = f"{last_row.get('OSC', 0):.2f}"

    info_block_2 = (
        f"{date_str} KD(9) K:{k_val} D:{d_val} | OBV:{obv_val}<br>"
        f"MACD DIF:{dif_val} MACD:{macd_val} OSC:{osc_val}"
    )

    # 3. 第三塊資訊區規格（防遮蔽，拆分為三行）：
    # 第一行：YYYY-MM-DD 資券[千張]資:-XX.XXX 券:-XX.XXX 券資比:XX.XX%
    # 第二行：法人集保[張]外資:-XX 投信:XX 自營:+XX
    # 第三行：大戶持股比(%) ≥1000張: XX.XX% ≥400張: XX.XX%
    margin_diff_k = last_row.get('Margin_Diff', 0) / 1000.0 if pd.notnull(last_row.get('Margin_Diff')) else 0.0
    short_diff_k = last_row.get('Short_Diff', 0) / 1000.0 if pd.notnull(last_row.get('Short_Diff')) else 0.0
    margin_buy_str = f"{margin_diff_k:+.3f}"
    short_sell_str = f"{short_diff_k:+.3f}"
    
    margin_ratio = last_row.get('Margin_Short_Ratio', 0.0)
    ratio_str = f"{margin_ratio:.2f}%" if pd.notnull(margin_ratio) else "0.00%"

    foreign_val = int(last_row.get('Foreign_Buy', 0)) if pd.notnull(last_row.get('Foreign_Buy')) else 0
    trust_val = int(last_row.get('Trust_Buy', 0)) if pd.notnull(last_row.get('Trust_Buy')) else 0
    dealer_val = int(last_row.get('Dealer_Buy', 0)) if pd.notnull(last_row.get('Dealer_Buy')) else 0

    foreign_str = f"{foreign_val:+d}"
    trust_str = f"{trust_val:+d}"
    dealer_str = f"{dealer_val:+d}"

    m1_val = last_row.get(f'Big_{m1}_Ratio', 0.0)
    m2_val = last_row.get(f'Big_{m2}_Ratio', 0.0)
    m1_str = f"{m1_val:.2f}%" if pd.notnull(m1_val) else "0.00%"
    m2_str = f"{m2_val:.2f}%" if pd.notnull(m2_val) else "0.00%"

    info_block_3 = (
        f"{date_str} 資券[千張]資:{margin_buy_str} 券:{short_sell_str} 券資比:{ratio_str}<br>"
        f"法人集保[張]外資:{foreign_str} 投信:{trust_str} 自營:{dealer_str}<br>"
        f"大戶持股比(%) ≥{m1}張: {m1_str} ≥{m2}張: {m2_str}"
    )

    # 建立 5 列子圖版面配置
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.40, 0.15, 0.15, 0.15, 0.15],
        subplot_titles=(main_title, info_block_2, "", "", info_block_3)
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

    ma_configs = [
        ('MA5', '#f39c12', 1.2),
        ('MA20', '#2980b9', 1.4),
        ('MA60', '#8e44ad', 1.2)
    ]
    for ma_col, color, width in ma_configs:
        if ma_col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma_col],
                name=ma_col,
                line=dict(color=color, width=width)
            ), row=1, col=1)

    # Row 2: 第二區 (KD + OBV)
    if 'K' in df.columns and 'D' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['K'],
            name="K",
            line=dict(color='#e74c3c', width=1.2)
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['D'],
            name="D",
            line=dict(color='#3498db', width=1.2)
        ), row=2, col=1)

    # Row 3: 法人買賣超 (外資/投信/自營)
    if 'Foreign_Buy' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df['Foreign_Buy'],
            name="外資",
            marker_color='#d63031'
        ), row=3, col=1)
    if 'Trust_Buy' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df['Trust_Buy'],
            name="投信",
            marker_color='#0984e3'
        ), row=3, col=1)
    if 'Dealer_Buy' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df['Dealer_Buy'],
            name="自營",
            marker_color='#fdcb6e'
        ), row=3, col=1)

    # 法人副圖 Y 軸單位格式化：超過 1000 以 K 呈現 (如 1k, -1k, 20k)
    fig.update_yaxes(
        tickformat=".2s",
        row=3, col=1
    )

    # Row 4: 資券增減副圖
    if 'Margin_Diff' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df['Margin_Diff'],
            name="融資增減",
            marker_color='#e17055'
        ), row=4, col=1)
    if 'Short_Diff' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df['Short_Diff'],
            name="融券增減",
            marker_color='#00cec9'
        ), row=4, col=1)

    # Row 5: 大戶持股比例走勢 (第三區)
    col_m1 = f'Big_{m1}_Ratio'
    col_m2 = f'Big_{m2}_Ratio'
    if col_m1 in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col_m1],
            name=f"≥{m1}張%",
            line=dict(color='#d63031', width=1.5)
        ), row=5, col=1)
    if col_m2 in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col_m2],
            name=f"≥{m2}張%",
            line=dict(color='#0984e3', width=1.5)
        ), row=5, col=1)

    # 整體版面控制
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=40, r=40, t=60, b=40),
        hovermode="x unified",
        barmode="group"
    )

    # 設定全子圖 X 軸日期格式與移除休市空白日
    fig.update_xaxes(
        type='date',
        tickformat="%Y-%m-%d"
    )

    return fig
