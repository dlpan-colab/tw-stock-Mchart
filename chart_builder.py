"""
chart_builder.py - Plotly 圖表建置模組（主圖、指標頁籤與籌碼總入口）
(依邏輯職責拆分為 chrt_chip.py 與本主圖/指標建置總入口，維持 100% 向後相容回傳結構)
版本: 202611242230
"""

from typing import Tuple, Optional, Dict
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202611242230"

from data_fetcher import fetch_stock_daily_k, fetch_stock_name
from indicators import calculate_all_indicators
from chrt_chip import build_chip_figure


def build_split_figures(
    raw_ticker: str,
    period: str = "1y",
    display_days: int = 20,
    base_date: Optional[object] = None,
    major1_thresh: int = 1000,
    major2_thresh: int = 400,
    is_mobile: bool = False,
    status_placeholder=None,
    force_refresh: bool = False
) -> Tuple[Optional[go.Figure], Optional[Dict[str, go.Figure]], Optional[pd.DataFrame], str, int, int]:
    k_res = fetch_stock_daily_k(
        raw_ticker,
        period=period,
        base_date=str(base_date) if base_date else None,
        force_refresh=force_refresh
    )
    if k_res is None or k_res[0] is None or k_res[0].empty:
        return None, None, None, "", 0, 0

    df_raw = k_res[0]
    full_ticker = k_res[1]
    shares_outstanding = k_res[2] if len(k_res) >= 3 else None

    c_name = fetch_stock_name(raw_ticker)
    if str(raw_ticker).startswith("^"):
        market_label = "指數"
    elif full_ticker.endswith(".TW"):
        market_label = "上市"
    elif full_ticker.endswith(".TWO"):
        market_label = "上櫃"
    else:
        market_label = "海外"

    df = calculate_all_indicators(
        df=df_raw,
        pure_code=raw_ticker,
        major1_thresh=major1_thresh,
        major2_thresh=major2_thresh,
        shares_outstanding=shares_outstanding,
        status_placeholder=status_placeholder,
        force_refresh=force_refresh,
        full_ticker=full_ticker
    )

    date_str_list = [d.strftime('%Y-%m-%d') for d in df.index]
    total_len = len(df)

    disp_n = min(int(display_days), total_len)
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

    p_max, p_min = float(sub_df['High'].max()), float(sub_df['Low'].min())
    p_pad = (p_max - p_min) * 0.12 if p_max > p_min else 2.0
    vol_upper = float(sub_df['Volume_Sheets'].max()) * 1.25 if not sub_df['Volume_Sheets'].empty else 1000.0

    month_ticks_vals, month_ticks_text = [], []
    cur_m = None
    for i, d in enumerate(df.index):
        m_str = d.strftime('%Y-%m')
        if m_str != cur_m:
            cur_m = m_str
            month_ticks_vals.append(date_str_list[i])
            month_ticks_text.append(d.strftime('%m月'))

    vol_colors = ['#eb4d4b' if c >= o else '#2ecc71' for c, o in zip(df['Close'], df['Open'])]
    osc_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df['OSC'].fillna(0)]

    sub_obv = sub_df['OBV'].dropna()
    sub_obv_ma = sub_df['OBV_MA20'].dropna()
    obv_min = float(min(sub_obv.min(), sub_obv_ma.min())) if not sub_obv_ma.empty else float(sub_obv.min())
    obv_max = float(max(sub_obv.max(), sub_obv_ma.max())) if not sub_obv_ma.empty else float(sub_obv.max())
    obv_pad = (obv_max - obv_min) * 0.10 if obv_max > obv_min else 5.0

    sub_macd_vals = pd.concat([sub_df['DIF'], sub_df['MACD'], sub_df['OSC']]).dropna()
    macd_min = float(sub_macd_vals.min()) if not sub_macd_vals.empty else -1.0
    macd_max = float(sub_macd_vals.max()) if not sub_macd_vals.empty else 1.0
    macd_pad = (macd_max - macd_min) * 0.15 if macd_max > macd_min else 0.5

    bias_series_list = [
        sub_df[col].dropna() for col in ['BIAS_20', 'BIAS_120', 'BIAS_240', 'BIAS_1200']
        if col in sub_df.columns and not sub_df[col].dropna().empty
    ]
    if bias_series_list:
        sub_bias_vals = pd.concat(bias_series_list)
        bias_min = min(0.0, float(sub_bias_vals.min()))
        bias_max = max(0.0, float(sub_bias_vals.max()))
    else:
        bias_min, bias_max = -5.0, 5.0
    bias_pad = (bias_max - bias_min) * 0.15 if bias_max > bias_min else 2.0

    top_height = 296 if is_mobile else 336
    tech_height = 540 if is_mobile else 580

    # =====================================================================
    # 1. 上半部共用主圖（K線 + 成交量）
    # =====================================================================
    fig_top = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.70, 0.30]
    )

    fig_top.add_trace(go.Candlestick(
        x=date_str_list, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b',
        decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71',
        hoverinfo='none', name='K線'
    ), row=1, col=1)

    fig_top.add_trace(go.Scatter(
        x=date_str_list, y=df['MA5'], line=dict(color='#f1c40f', width=1.2),
        hoverinfo='none', name='MA5'
    ), row=1, col=1)
    fig_top.add_trace(go.Scatter(
        x=date_str_list, y=df['MA20'], line=dict(color='#e67e22', width=1.2),
        hoverinfo='none', name='MA20'
    ), row=1, col=1)
    fig_top.add_trace(go.Scatter(
        x=date_str_list, y=df['MA60'], line=dict(color='#9b59b6', width=1.2),
        hoverinfo='none', name='MA60'
    ), row=1, col=1)

    head_df = df[df['Is_Head']]
    if not head_df.empty:
        fig_top.add_trace(go.Scatter(
            x=[d.strftime('%Y-%m-%d') for d in head_df.index], y=head_df['High'],
            mode='text', text='<b>〔頭〕</b>', textposition='top center',
            textfont=dict(family='Arial Black, sans-serif', size=12, color='#27ae60'),
            hoverinfo='none'
        ), row=1, col=1)

    bottom_df = df[df['Is_Bottom']]
    if not bottom_df.empty:
        fig_top.add_trace(go.Scatter(
            x=[d.strftime('%Y-%m-%d') for d in bottom_df.index], y=bottom_df['Low'],
            mode='text', text='<b>〔底〕</b>', textposition='bottom center',
            textfont=dict(family='Arial Black, sans-serif', size=12, color='#e74c3c'),
            hoverinfo='none'
        ), row=1, col=1)

    fig_top.add_trace(go.Bar(
        x=date_str_list,
        y=df['Volume_Sheets'],
        marker=dict(color=vol_colors, line=dict(color=vol_colors, width=0.8)),
        hoverinfo='none',
        name='成交量'
    ), row=2, col=1)

    to_series = df['Turnover_Rate']
    to_10_mask = (to_series >= 10.0) & (to_series < 20.0)
    to_20_mask = (to_series >= 20.0)
    if to_10_mask.any():
        fig_top.add_trace(go.Scatter(
            x=[date_str_list[i] for i in range(total_len) if to_10_mask.iloc[i]],
            y=df.loc[to_10_mask, 'Volume_Sheets'] * 1.06,
            mode='text', text=['▲' for _ in range(to_10_mask.sum())],
            textposition='top center',
            textfont=dict(family='Arial Black, sans-serif', size=13, color='#1e3799'),
            showlegend=False, hoverinfo='none'
        ), row=2, col=1)
    if to_20_mask.any():
        fig_top.add_trace(go.Scatter(
            x=[date_str_list[i] for i in range(total_len) if to_20_mask.iloc[i]],
            y=df.loc[to_20_mask, 'Volume_Sheets'] * 1.06,
            mode='text', text=['▼' for _ in range(to_20_mask.sum())],
            textposition='top center',
            textfont=dict(family='Arial Black, sans-serif', size=13, color='#f1c40f'),
            showlegend=False, hoverinfo='none'
        ), row=2, col=1)

    fig_top.update_layout(
        title=dict(
            text=f'<b>{c_name or raw_ticker} ({raw_ticker}) ({market_label})</b>',
            font=dict(size=16, color='#1d4ed8')
        ),
        font=dict(size=12), template='plotly_white', hovermode=False, dragmode='pan',
        showlegend=False, height=top_height,
        margin=dict(l=80, r=15, t=34, b=34, autoexpand=False),
        xaxis_rangeslider_visible=False
    )
    fig_top.update_xaxes(
        type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
        showspikes=False, tickfont=dict(size=11), row=1, col=1
    )
    fig_top.update_xaxes(
        type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
        showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text,
        showspikes=False, tickfont=dict(size=11), row=2, col=1
    )
    fig_top.update_yaxes(
        title_text='', range=[p_min - (p_max - p_min) * 0.08, p_max + p_pad],
        fixedrange=True, showspikes=False, tickfont=dict(size=11), row=1, col=1
    )
    fig_top.update_yaxes(
        title_text='', range=[-vol_upper * 0.08, vol_upper],
        zeroline=True, zerolinecolor='#cbd5e1', zerolinewidth=1,
        fixedrange=True, showspikes=False, tickfont=dict(size=11), row=2, col=1
    )

    # =====================================================================
    # 2. 頁籤 1【指標】副圖：KD、MACD、OBV、乖離率 (20/120/240/1200日)
    # =====================================================================
    fig_tech = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.045,
        row_heights=[0.24, 0.24, 0.24, 0.28]
    )

    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['K'], line=dict(color='#e74c3c', width=1.2), hoverinfo='none'), row=1, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['D'], line=dict(color='#3498db', width=1.2), hoverinfo='none'), row=1, col=1)
    fig_tech.add_hline(y=80, line_dash='dot', line_color='rgba(150,150,150,0.5)', row=1, col=1)
    fig_tech.add_hline(y=20, line_dash='dot', line_color='rgba(150,150,150,0.5)', row=1, col=1)

    fig_tech.add_trace(go.Bar(x=date_str_list, y=df['OSC'], marker_color=osc_colors, hoverinfo='none'), row=2, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['DIF'], line=dict(color='#f39c12', width=1.2), hoverinfo='none'), row=2, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['MACD'], line=dict(color='#2980b9', width=1.2), hoverinfo='none'), row=2, col=1)

    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['OBV'], line=dict(color='#16a085', width=1.2), hoverinfo='none'), row=3, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['OBV_MA20'], line=dict(color='#8e44ad', width=1.1, dash='dash'), hoverinfo='none'), row=3, col=1)

    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['BIAS_20'], line=dict(color='#e67e22', width=1.3), hoverinfo='none', name='20日乖離'), row=4, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['BIAS_120'], line=dict(color='#2980b9', width=1.3), hoverinfo='none', name='120日乖離'), row=4, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['BIAS_240'], line=dict(color='#8e44ad', width=1.3), hoverinfo='none', name='240日乖離'), row=4, col=1)
    fig_tech.add_trace(go.Scatter(x=date_str_list, y=df['BIAS_1200'], line=dict(color='#e74c3c', width=1.4), hoverinfo='none', name='1200日乖離'), row=4, col=1)
    fig_tech.add_hline(y=0, line_dash='dot', line_color='rgba(120,120,120,0.65)', line_width=1, row=4, col=1)

    fig_tech.update_layout(
        font=dict(size=12), template='plotly_white', hovermode=False, dragmode='pan',
        showlegend=False, height=tech_height,
        margin=dict(l=80, r=15, t=8, b=24, autoexpand=False),
        xaxis_rangeslider_visible=False
    )
    for r in range(1, 5):
        fig_tech.update_xaxes(
            type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
            showspikes=False, tickfont=dict(size=11), row=r, col=1
        )
    fig_tech.update_xaxes(
        type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
        showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text,
        tickfont=dict(size=11), row=4, col=1
    )
    fig_tech.update_yaxes(title_text='', range=[0, 100], fixedrange=True, showspikes=False, tickfont=dict(size=11), row=1, col=1)
    fig_tech.update_yaxes(title_text='', range=[macd_min - macd_pad, macd_max + macd_pad], fixedrange=True, showspikes=False, tickfont=dict(size=11), row=2, col=1)
    fig_tech.update_yaxes(title_text='', range=[obv_min - obv_pad, obv_max + obv_pad], fixedrange=True, showspikes=False, tickfont=dict(size=11), row=3, col=1)
    fig_tech.update_yaxes(title_text='', range=[bias_min - bias_pad, bias_max + bias_pad], fixedrange=True, showspikes=False, tickfont=dict(size=11), row=4, col=1)

    for idx_t, lbl_t in enumerate(['KD', 'MACD', 'OBV', '乖離%'], start=1):
        y_ax_name = 'y domain' if idx_t == 1 else f'y{idx_t} domain'
        fig_tech.add_annotation(
            x=0.006, y=0.98, xref='paper', yref=y_ax_name,
            xanchor='left', yanchor='top',
            text=f'<b>{lbl_t}</b>',
            font=dict(size=11, color='#1e293b'),
            bgcolor='rgba(255,255,255,0.82)',
            borderpad=2,
            showarrow=False
        )

    # =====================================================================
    # 3. 頁籤 2【籌碼】副圖（委由 chrt_chip 建置）
    # =====================================================================
    fig_chip = build_chip_figure(
        df=df,
        sub_df=sub_df,
        date_str_list=date_str_list,
        start_idx=start_idx,
        end_idx=end_idx,
        month_ticks_vals=month_ticks_vals,
        month_ticks_text=month_ticks_text,
        raw_ticker=raw_ticker,
        major1_thresh=major1_thresh,
        major2_thresh=major2_thresh,
        shares_outstanding=shares_outstanding,
        is_mobile=is_mobile,
    )

    fig_bundle = {"tech": fig_tech, "chip": fig_chip}
    return fig_top, fig_bundle, df, c_name, end_idx, disp_n
## EOF chart_builder.py
