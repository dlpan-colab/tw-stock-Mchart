"""
台股技術與籌碼分析系統 - Plotly 雙圖繪製模組 (chart_builder.py)
負責主圖（K 線、5/20/60MA、頭底標籤、成交量柱、換手率標記）
與副圖（9 大技術及籌碼子圖）之繪製，計算初始可視範圍與動態月份 X 軸標籤。
完全相容 app.py 的 build_split_figures 呼叫規格與回傳格式。
"""

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202610300900"

import gc
from typing import Optional, Tuple
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from data_fetcher import fetch_stock_daily_k
except ImportError:
    fetch_stock_daily_k = None

try:
    from indicators import calculate_all_indicators
except ImportError:
    calculate_all_indicators = None

def build_split_figures(
    raw_ticker: str,
    period: str = "1y",
    display_days: int = 20,
    base_date: Optional[object] = None,
    major1_thresh: int = 1000,
    major2_thresh: int = 400,
    is_mobile: bool = False,
    status_placeholder=None
) -> Tuple[Optional[go.Figure], Optional[go.Figure], Optional[pd.DataFrame], str, int, int]:
    
    if fetch_stock_daily_k is None or calculate_all_indicators is None:
        raise ImportError("缺少必要的模組：data_fetcher 或 indicators")

    df, full_ticker = fetch_stock_daily_k(raw_ticker, period=period, base_date=base_date)
    if df is None or df.empty:
        return None, None, None, "", 0, 0

    c_name = raw_ticker
    market = "上市" if full_ticker.endswith(".TW") else "上櫃"

    # 指標與籌碼計算
    df = calculate_all_indicators(
        df=df,
        pure_code=raw_ticker,
        major1_thresh=major1_thresh,
        major2_thresh=major2_thresh,
        status_placeholder=status_placeholder
    )

    date_str_list = [d.strftime('%Y-%m-%d') for d in df.index]
    total_len = len(df)
    disp_n = min(int(display_days), total_len)

    # 1. 基準日定位與可視範圍計算
    end_idx = total_len - 1
    if base_date is not None:
        try:
            target_ts = pd.to_datetime(base_date)
            if target_ts.tz is not None:
                target_ts = target_ts.tz_localize(None)
            valid_idx = np.where(df.index <= target_ts)[0]
            if len(valid_idx) > 0:
                end_idx = valid_idx[-1]
        except Exception:
            pass

    start_idx = max(0, end_idx - disp_n + 1)
    sub_df = df.iloc[start_idx:end_idx + 1]

    # 月份刻度計算
    month_ticks_vals = []
    month_ticks_text = []
    last_m = None
    for i, d in enumerate(df.index):
        cur_m = d.strftime('%Y-%m')
        if cur_m != last_m:
            month_ticks_vals.append(date_str_list[i])
            month_ticks_text.append(d.strftime('%m月'))
            last_m = cur_m

    # ===== 上半部主圖（K線 + 均線 + 成交量） =====
    fig_top = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25]
    )

    # K 線
    fig_top.add_trace(go.Candlestick(
        x=date_str_list,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#eb4d4b', decreasing_line_color='#2ecc71',
        showlegend=False, name="K線"
    ), row=1, col=1)

    # 均線
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA5'], line=dict(color='#f39c12', width=1.2), name="5MA"), row=1, col=1)
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA20'], line=dict(color='#2980b9', width=1.2), name="20MA"), row=1, col=1)
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA60'], line=dict(color='#27ae60', width=1.2), name="60MA"), row=1, col=1)

    # 頭底標籤
    head_mask = df['Is_Head'] == True
    bottom_mask = df['Is_Bottom'] == True
    fig_top.add_trace(go.Scatter(
        x=[date_str_list[i] for i in range(total_len) if head_mask.iloc[i]],
        y=df.loc[head_mask, 'High'] * 1.015,
        mode='text', text=['▼頭' for _ in range(head_mask.sum())],
        textposition='top center', textfont=dict(color='#27ae60', size=11),
        showlegend=False, hoverinfo='none'
    ), row=1, col=1)
    fig_top.add_trace(go.Scatter(
        x=[date_str_list[i] for i in range(total_len) if bottom_mask.iloc[i]],
        y=df.loc[bottom_mask, 'Low'] * 0.985,
        mode='text', text=['▲底' for _ in range(bottom_mask.sum())],
        textposition='bottom center', textfont=dict(color='#eb4d4b', size=11),
        showlegend=False, hoverinfo='none'
    ), row=1, col=1)

    # 成交量
    vol_colors = ['#eb4d4b' if df['Close'].iloc[i] >= df['Open'].iloc[i] else '#2ecc71' for i in range(total_len)]
    fig_top.add_trace(go.Bar(x=date_str_list, y=df['Volume_Sheets'], marker_color=vol_colors, name="成交量(張)"), row=2, col=1)

    fig_top.update_layout(
        height=520,
        margin=dict(l=75, r=15, t=35, b=10),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        template="plotly_white"
    )
    fig_top.update_xaxes(type='category', range=[start_idx, end_idx], row=1, col=1)
    fig_top.update_xaxes(type='category', range=[start_idx, end_idx], showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text, row=2, col=1)

    # ===== 下半部副圖（KD + MACD + OBV + 外資 + 投信 + 自營商 + 資券 + 大戶1 + 大戶2） =====
    fig_btm = make_subplots(
        rows=9, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.13, 0.12, 0.12, 0.11, 0.11, 0.11, 0.10, 0.10, 0.10]
    )

    # Row 1: KD
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['K'], line=dict(color='#f39c12', width=1.2), name="K"), row=1, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['D'], line=dict(color='#2980b9', width=1.2), name="D"), row=1, col=1)

    # Row 2: MACD
    osc_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['OSC']]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['OSC'], marker_color=osc_colors, name="OSC"), row=2, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['DIF'], line=dict(color='#e74c3c', width=1.1), name="DIF"), row=2, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['MACD'], line=dict(color='#3498db', width=1.1), name="MACD"), row=2, col=1)

    # Row 3: OBV
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['OBV'], line=dict(color='#8e44ad', width=1.2), name="OBV"), row=3, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['OBV_MA20'], line=dict(color='#f39c12', width=1.1), name="OBV_MA20"), row=3, col=1)

    # Row 4: 外資買賣超
    f_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Foreign_Net']]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Foreign_Net'], marker_color=f_colors, name="外資"), row=4, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=4, col=1)

    # Row 5: 投信買賣超
    t_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Trust_Net']]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Trust_Net'], marker_color=t_colors, name="投信"), row=5, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=5, col=1)

    # Row 6: 自營商買賣超
    d_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Dealer_Net']]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Dealer_Net'], marker_color=d_colors, name="自營"), row=6, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=6, col=1)

    # Row 7: 資券餘額與增減
    m_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Margin_Diff']]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Margin_Diff'], marker_color=m_colors, name="資增減"), row=7, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['Margin_Bal'], line=dict(color='#e67e22', width=1.2), name="資餘額"), row=7, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=7, col=1)

    # Row 8: 大戶 1 持股比例 (%) - connectgaps=True 杜絕斷線
    fig_btm.add_trace(go.Scatter(
        x=date_str_list,
        y=df['Major1_Pct'],
        line=dict(color='#c0392b', width=1.5),
        name=f'大戶1(≥{major1_thresh}張)',
        connectgaps=True,
        hoverinfo='none'
    ), row=8, col=1)

    # Row 9: 大戶 2 持股比例 (%) - connectgaps=True 杜絕斷線
    fig_btm.add_trace(go.Scatter(
        x=date_str_list,
        y=df['Major2_Pct'],
        line=dict(color='#8e44ad', width=1.5),
        name=f'大戶2(≥{major2_thresh}張)',
        connectgaps=True,
        hoverinfo='none'
    ), row=9, col=1)

    # 軸範圍設置
    m1_s = sub_df['Major1_Pct'].dropna()
    m1_min = float(m1_s.min()) - 0.5 if not m1_s.empty else 0
    m1_max = float(m1_s.max()) + 0.5 if not m1_s.empty else 100

    m2_s = sub_df['Major2_Pct'].dropna()
    m2_min = float(m2_s.min()) - 0.5 if not m2_s.empty else 0
    m2_max = float(m2_s.max()) + 0.5 if not m2_s.empty else 100

    fig_btm.update_layout(
        height=1100 if is_mobile else 1200,
        margin=dict(l=75, r=15, t=10, b=25),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        template="plotly_white"
    )

    for r in range(1, 10):
        fig_btm.update_xaxes(type='category', range=[start_idx, end_idx], row=r, col=1)
    fig_btm.update_xaxes(showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text, row=9, col=1)

    fig_btm.update_yaxes(title_text='KD', row=1, col=1)
    fig_btm.update_yaxes(title_text='MACD', row=2, col=1)
    fig_btm.update_yaxes(title_text='OBV', row=3, col=1)
    fig_btm.update_yaxes(title_text='外資', row=4, col=1)
    fig_btm.update_yaxes(title_text='投信', row=5, col=1)
    fig_btm.update_yaxes(title_text='自營', row=6, col=1)
    fig_btm.update_yaxes(title_text='資券', row=7, col=1)
    fig_btm.update_yaxes(title_text=f'≥{major1_thresh}', range=[m1_min, m1_max], fixedrange=True, row=8, col=1)
    fig_btm.update_yaxes(title_text=f'≥{major2_thresh}', range=[m2_min, m2_max], fixedrange=True, row=9, col=1)

    gc.collect()
    return fig_top, fig_btm, df, c_name, end_idx, disp_n
