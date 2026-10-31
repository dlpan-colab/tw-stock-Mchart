import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

def render_master_chart(df: pd.DataFrame, stock_info: dict, m1: int, m2: int) -> go.Figure:
    """
    df: 已計算各項指標之資料（最末筆對應最新交易日）
    stock_info: 包含 'name', 'code', 'market' (市 或 櫃)
    """
    last_row = df.iloc[-1]
    date_str = last_row.name.strftime("%Y-%m-%d") if hasattr(last_row.name, "strftime") else str(last_row["Date"])[:10]

    # K線圖標題格式：[中文名](代碼)(市/櫃)
    market_str = "市" if "市" in stock_info.get("market", "") else "櫃"
    main_title = f"{stock_info.get('name', '')}({stock_info.get('code', '')})({market_str})"

    # 第二塊資訊區規格修訂：
    # 第一行：YYYY-MM-DD KD(9) K:... D:... | OBV:...
    # 次行：MACD DIF:... MACD:... OSC:...
    k_val = f"{last_row.get('K', 0):.1f}"
    d_val = f"{last_row.get('D', 0):.1f}"
    obv_val = f"{int(last_row.get('OBV', 0))}"
    
    dif_val = f"{last_row.get('DIF', 0):.2f}"
    macd_val = f"{last_row.get('MACD', 0):.2f}"
    osc_val = f"{last_row.get('OSC', 0):.2f}"

    info_block_2 = (
        f"{date_str} KD(9) K:{k_val} D:{d_val} | OBV:{obv_val}<br>"
        f"MACD DIF:{dif_val} MACD:{macd_val} OSC:{osc_val}"
    )

    # 第三塊資訊區規格修訂（防遮蔽，拆分為三行）：
    # 第一行：YYYY-MM-DD 資券[千張]資:-XX.XXX 券:-XX.XXX 券資比:XX.XX%
    # 第二行：法人集保[張]外資:-XX 投信:XX 自營:+XX
    # 第三行：大戶持股比(%) ≥1000張: XX.XX% ≥400張: XX.XX%
    margin_buy = f"{last_row.get('Margin_Balance', 0) / 1000:+.3f}"
    short_sell = f"{last_row.get('Short_Balance', 0) / 1000:+.3f}"
    margin_ratio = f"{last_row.get('Margin_Short_Ratio', 0):.2f}%"

    foreign = f"{int(last_row.get('Foreign_Buy', 0)):+d}"
    trust = f"{int(last_row.get('Trust_Buy', 0)):+d}"
    dealer = f"{int(last_row.get('Dealer_Buy', 0)):+d}"

    ratio_m1 = f"{last_row.get(f'Big_{m1}_Ratio', 0):.2f}%"
    ratio_m2 = f"{last_row.get(f'Big_{m2}_Ratio', 0):.2f}%"

    info_block_3 = (
        f"{date_str} 資券[千張]資:{margin_buy} 券:{short_sell} 券資比:{margin_ratio}<br>"
        f"法人集保[張]外資:{foreign} 投信:{trust} 自營:{dealer}<br>"
        f"大戶持股比(%) ≥{m1}張: {ratio_m1} ≥{m2}張: {ratio_m2}"
    )

    # 建立多子圖（主K+量、KD/MACD/OBV、籌碼法人、資券大戶）
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.42, 0.15, 0.15, 0.14, 0.14],
        subplot_titles=(main_title, info_block_2, "", "", info_block_3)
    )

    # 1. 主圖：K線與均線
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name="K線",
        increasing_line_color='red', decreasing_line_color='green'
    ), row=1, col=1)

    for ma_name, color in [('MA5', '#E6A100'), ('MA20', '#DE6800'), ('MA60', '#A333C8')]:
        if ma_name in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[ma_name], name=ma_name, line=dict(color=color, width=1.2)), row=1, col=1)

    # 2. 第二區：KD / MACD / OBV 走勢
    if 'K' in df.columns and 'D' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], name="K", line=dict(color='#2185D0', width=1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], name="D", line=dict(color='#F2711C', width=1)), row=2, col=1)

    # 3. 法人買賣超（外資 / 投信 / 自營）
    if 'Foreign_Buy' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Foreign_Buy'], name="外資", marker_color='red'), row=3, col=1)
    if 'Trust_Buy' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Trust_Buy'], name="投信", marker_color='#21BA45'), row=3, col=1)
    if 'Dealer_Buy' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Dealer_Buy'], name="自營", marker_color='#A333C8'), row=3, col=1)

    # 4. 資券變化
    if 'Margin_Balance' in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df['Margin_Balance'], name="資券", marker_color='#FBBD08'), row=4, col=1)

    # 5. 大戶持股
    if f'Big_{m1}_Ratio' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[f'Big_{m1}_Ratio'], name=f"≥{m1}張", line=dict(color='#00B5AD', width=1.2)), row=5, col=1)
    if f'Big_{m2}_Ratio' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[f'Big_{m2}_Ratio'], name=f"≥{m2}張", line=dict(color='#6435C9', width=1.2)), row=5, col=1)

    # 法人 Y 軸規格：超過 1000 標示為 K (例如 1k, -1k, 20k)
    fig.update_yaxes(
        tickformat=".2s",
        row=3, col=1
    )

    # 版面設置
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=40, r=40, t=50, b=40),
        hovermode="x unified"
    )

    return fig
