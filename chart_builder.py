"""
chart_builder.py - Plotly 圖表建置模組 (主圖1/2緊緻化、指標頁籤乖離率、籌碼分頁標準字典防快取遺失、主標題藍色加大、副圖左上角內嵌標籤與加權^TWII/櫃買^TWOII緊緻雙列資券千張＋融資金額(億)副圖消除空白及大戶線1%約當張數優先採用集保最新週總張數註明版 + 主圖成交量Y軸0刻度抬升完整顯示版)
版本: 202611221630
"""

from typing import Tuple, Optional, Dict
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202611221630"

from data_fetcher import fetch_stock_daily_k, fetch_stock_name
from indicators import calculate_all_indicators


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
    m_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df['Margin_Diff'].fillna(0)]
    s_colors = ['#f1c40f' if val >= 0 else '#3498db' for val in df['Short_Diff'].fillna(0)]
    mm_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df['Margin_Money_Diff'].fillna(0)]

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

    def calc_inst_range(series):
        s_clean = series.dropna()
        if s_clean.empty or (s_clean == 0).all():
            return [-100, 100]
        max_abs = max(abs(float(s_clean.min())), abs(float(s_clean.max())))
        return [-max_abs * 1.25, max_abs * 1.25] if max_abs > 0 else [-100, 100]

    fn_range = calc_inst_range(sub_df['Foreign_Net'])
    tn_range = calc_inst_range(sub_df['Trust_Net'])
    dn_range = calc_inst_range(sub_df['Dealer_Net'])

    ms_vals = pd.concat([sub_df['Margin_Diff'], sub_df['Short_Diff']]).dropna()
    ms_max_abs = max(abs(float(ms_vals.min())), abs(float(ms_vals.max()))) if not ms_vals.empty else 0
    ms_range = [-ms_max_abs * 1.25, ms_max_abs * 1.25] if ms_max_abs > 0 else [-100, 100]

    mm_vals = sub_df['Margin_Money_Diff'].dropna() if 'Margin_Money_Diff' in sub_df.columns else pd.Series(dtype=float)
    mm_max_abs = max(abs(float(mm_vals.min())), abs(float(mm_vals.max()))) if not mm_vals.empty else 0
    mm_range = [-mm_max_abs * 1.25, mm_max_abs * 1.25] if mm_max_abs > 0 else [-10, 10]

    def calc_holding_range(series):
        s_clean = series.dropna()
        if s_clean.empty:
            return [0, 100]
        c_min, c_max = float(s_clean.min()), float(s_clean.max())
        pad = max(0.15, (c_max - c_min) * 0.15) if c_max > c_min else 0.5
        return [c_min - pad, c_max + pad]

    m1_range = calc_holding_range(sub_df['Major1_Pct'])
    m2_range = calc_holding_range(sub_df['Major2_Pct'])

    raw_upper = str(raw_ticker).strip().upper()
    is_tw_index = raw_upper in ("^TWII", "^TWOII")
    mkt_prefix = "上櫃" if raw_upper == "^TWOII" else "上市"

    if is_tw_index:
        maint_vals = pd.concat([
            sub_df['Margin_Maint_Pct'].dropna() if 'Margin_Maint_Pct' in sub_df.columns else pd.Series(dtype=float),
            sub_df['Short_Maint_Pct'].dropna() if 'Short_Maint_Pct' in sub_df.columns else pd.Series(dtype=float)
        ])
        r_min = float(maint_vals.min()) if not maint_vals.empty else 120.0
        r_max = float(maint_vals.max()) if not maint_vals.empty else 230.0
        r_pad = max(2.0, (r_max - r_min) * 0.15) if r_max > r_min else 5.0
        ratio_range = [max(0, r_min - r_pad), r_max + r_pad]

        mmaint_clean = sub_df['Margin_Maint_Pct'].dropna() if 'Margin_Maint_Pct' in sub_df.columns else pd.Series(dtype=float)
        mm_r_min = float(mmaint_clean.min()) if not mmaint_clean.empty else 130.0
        mm_r_max = float(mmaint_clean.max()) if not mmaint_clean.empty else 180.0
        mm_r_pad = max(1.5, (mm_r_max - mm_r_min) * 0.15) if mm_r_max > mm_r_min else 3.0
        mmaint_range = [max(0, mm_r_min - mm_r_pad), mm_r_max + mm_r_pad]
    else:
        ratio_clean = sub_df['Short_Margin_Ratio'].dropna()
        r_min = float(ratio_clean.min()) if not ratio_clean.empty else 0
        r_max = float(ratio_clean.max()) if not ratio_clean.empty else 10
        r_pad = max(0.5, (r_max - r_min) * 0.15) if r_max > r_min else 1.0
        ratio_range = [max(0, r_min - r_pad), r_max + r_pad]
        mmaint_range = [0, 100]

    # 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
    # 修改目的：主圖高度設為 296/336，並於成交量 yaxis2 底部設定負值緩衝（-vol_upper * 0.08），將「0」刻度線向上抬升，
    # 配合底部邊距 b=34，確保成交量 Y 軸「0」刻度文字完整呈現不被 iframe 底緣裁切。
    # 防呆防錯原因：維持 K 線與成交量高度比例（0.70 : 0.30），不影響任何指標與數值計算。
    top_height = 296 if is_mobile else 336
    tech_height = 540 if is_mobile else 580
    chip_height = (380 if is_mobile else 420) if is_tw_index else (760 if is_mobile else 800)

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

    # 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
    # 修改目的：成交量柱狀圖加上同色 0.8px 邊框線（marker_line_width=0.8），確保當可視區間存在極端爆量（如 50 萬張）時，
    # 量縮交易日（數千張）即使柱高不足 1px 仍能清晰顯示紅/綠柱體，不致在圖表上隱形消失。
    # 防呆防錯原因：僅增強視覺最小渲染高度，不更動 Volume_Sheets 原始數據。
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
        title_text='', range=[-vol_upper * 0.08, vol_upper], zeroline=True, zerolinecolor='#cbd5e1', zerolinewidth=1,
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
    # 3. 頁籤 2【籌碼】副圖：
    #    - 大盤加權(^TWII) / 櫃買(^TWOII)：緊緻雙列（資券千張/維持率 + 融資金額億/融資維持率），消除空白
    #    - 個股/ETF：6 列（外資、投信、自營、資券、大戶1、大戶2）
    # =====================================================================
    is_index = str(raw_ticker).startswith("^")
    if is_tw_index:
        fig_chip = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            row_heights=[0.54, 0.46],
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
        )

        # 第 1 列：上市/上櫃資券（千張）增減柱狀＋融資/融券維持率雙折線
        fig_chip.add_trace(go.Bar(
            x=date_str_list, y=df['Margin_Diff'], marker_color=m_colors,
            name=f'{mkt_prefix}融資', width=0.4, offset=-0.4, hoverinfo='none'
        ), secondary_y=False, row=1, col=1)
        fig_chip.add_trace(go.Bar(
            x=date_str_list, y=df['Short_Diff'], marker_color=s_colors,
            name=f'{mkt_prefix}融券', width=0.4, offset=0.0, hoverinfo='none'
        ), secondary_y=False, row=1, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=1, col=1)

        fig_chip.add_trace(go.Scatter(
            x=date_str_list, y=df['Margin_Maint_Pct'], line=dict(color='#e67e22', width=1.6),
            connectgaps=True, hoverinfo='none', name='融資維持率%'
        ), secondary_y=True, row=1, col=1)
        fig_chip.add_trace(go.Scatter(
            x=date_str_list, y=df['Short_Maint_Pct'], line=dict(color='#8e44ad', width=1.6),
            connectgaps=True, hoverinfo='none', name='融券維持率%'
        ), secondary_y=True, row=1, col=1)

        # 第 2 列：上市/上櫃融資金額增減（億）單一柱狀圖＋融資維持率折線
        fig_chip.add_trace(go.Bar(
            x=date_str_list, y=df['Margin_Money_Diff'], marker_color=mm_colors,
            name=f'{mkt_prefix}融資金額增減(億)', hoverinfo='none'
        ), secondary_y=False, row=2, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=2, col=1)
        fig_chip.add_trace(go.Scatter(
            x=date_str_list, y=df['Margin_Maint_Pct'], line=dict(color='#e67e22', width=1.6),
            connectgaps=True, hoverinfo='none', name='融資維持率%'
        ), secondary_y=True, row=2, col=1)

        fig_chip.update_layout(
            font=dict(size=12), template='plotly_white', hovermode=False, dragmode='pan',
            showlegend=False, height=chip_height,
            margin=dict(l=80, r=15, t=6, b=24, autoexpand=False),
            xaxis_rangeslider_visible=False
        )
        fig_chip.update_xaxes(
            type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
            showspikes=False, tickfont=dict(size=11), row=1, col=1
        )
        fig_chip.update_xaxes(
            type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
            showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text,
            tickfont=dict(size=11), row=2, col=1
        )
        fig_chip.update_yaxes(title_text='', range=ms_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=False, row=1, col=1)
        fig_chip.update_yaxes(title_text='', range=ratio_range, showgrid=False, showticklabels=False, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=True, row=1, col=1)
        fig_chip.update_yaxes(title_text='', range=mm_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=False, row=2, col=1)
        fig_chip.update_yaxes(title_text='', range=mmaint_range, showgrid=False, showticklabels=False, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=True, row=2, col=1)

        chip_pane_labels = [
            ('y domain', f'{mkt_prefix}資券(千張)/維持率'),
            ('y3 domain', f'{mkt_prefix}融資金額(億)/融資維持率'),
        ]
    else:
        fig_chip = make_subplots(
            rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.03,
            row_heights=[0.15, 0.15, 0.15, 0.21, 0.17, 0.17],
            specs=[[{}], [{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}], [{}]]
        )

        if not is_index:
            f_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Foreign_Net'].fillna(0)]
            fig_chip.add_trace(go.Bar(x=date_str_list, y=df['Foreign_Net'], marker_color=f_colors, hoverinfo='none'), row=1, col=1)
            fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=1, col=1)

            t_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Trust_Net'].fillna(0)]
            fig_chip.add_trace(go.Bar(x=date_str_list, y=df['Trust_Net'], marker_color=t_colors, hoverinfo='none'), row=2, col=1)
            fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=2, col=1)

            d_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Dealer_Net'].fillna(0)]
            fig_chip.add_trace(go.Bar(x=date_str_list, y=df['Dealer_Net'], marker_color=d_colors, hoverinfo='none'), row=3, col=1)
            fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=3, col=1)

            fig_chip.add_trace(go.Bar(
                x=date_str_list, y=df['Margin_Diff'], marker_color=m_colors,
                name='融資', width=0.4, offset=-0.4, hoverinfo='none'
            ), secondary_y=False, row=4, col=1)
            fig_chip.add_trace(go.Bar(
                x=date_str_list, y=df['Short_Diff'], marker_color=s_colors,
                name='融券', width=0.4, offset=0.0, hoverinfo='none'
            ), secondary_y=False, row=4, col=1)
            fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=4, col=1)

            fig_chip.add_trace(go.Scatter(
                x=date_str_list, y=df['Short_Margin_Ratio'], line=dict(color='#e67e22', width=1.5),
                connectgaps=True, hoverinfo='none', name='券資比%'
            ), secondary_y=True, row=4, col=1)

            fig_chip.add_trace(go.Scatter(
                x=date_str_list, y=df['Major1_Pct'], line=dict(color='#e74c3c', width=1.5),
                connectgaps=True, hoverinfo='none'
            ), secondary_y=False, row=5, col=1)

            fig_chip.add_trace(go.Scatter(
                x=date_str_list, y=df['Major2_Pct'], line=dict(color='#3498db', width=1.5),
                connectgaps=True, hoverinfo='none'
            ), row=6, col=1)

        fig_chip.update_layout(
            font=dict(size=12), template='plotly_white', hovermode=False, dragmode='pan',
            showlegend=False, height=chip_height,
            margin=dict(l=80, r=15, t=8, b=24, autoexpand=False),
            xaxis_rangeslider_visible=False
        )
        for r in range(1, 7):
            fig_chip.update_xaxes(
                type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
                showspikes=False, tickfont=dict(size=11), row=r, col=1
            )
        fig_chip.update_xaxes(
            type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1],
            showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text,
            tickfont=dict(size=11), row=6, col=1
        )
        fig_chip.update_yaxes(title_text='', range=fn_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), row=1, col=1)
        fig_chip.update_yaxes(title_text='', range=tn_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), row=2, col=1)
        fig_chip.update_yaxes(title_text='', range=dn_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), row=3, col=1)
        fig_chip.update_yaxes(title_text='', range=ms_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=False, row=4, col=1)
        fig_chip.update_yaxes(title_text='', range=ratio_range, showgrid=False, showticklabels=False, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=True, row=4, col=1)
        fig_chip.update_yaxes(title_text='', range=m1_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=False, row=5, col=1)
        fig_chip.update_yaxes(title_text='', range=[0, 100], showgrid=False, showticklabels=False, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=True, row=5, col=1)
        fig_chip.update_yaxes(title_text='', range=m2_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), row=6, col=1)

        # 【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
        # 修改目的：在「≥{major1_thresh}」大戶線 1 左上角標籤後方加上 1% 持股對應約當張數註明：(1%約=xxxx張)，
        # 優先採用 indicators.py 依最新週集保真實總股數算出的 df['Total_Shares']（單位：張），再備援 shares_outstanding / 1000.0。
        # 防呆防錯原因：確保新查詢個股在第一次同步抓完集保資料當下即可直接顯示 (1%約=xxxx張)，不必等第二次重整。
        m1_pane_label = f'≥{major1_thresh}'
        resolved_total_sheets = 0.0
        if 'Total_Shares' in df.columns and not df['Total_Shares'].empty:
            ts_val = float(df['Total_Shares'].iloc[-1] or 0.0)
            if ts_val > 0:
                resolved_total_sheets = ts_val
        if resolved_total_sheets <= 0 and shares_outstanding and float(shares_outstanding) > 0:
            resolved_total_sheets = float(shares_outstanding) / 1000.0
        if resolved_total_sheets > 0:
            one_pct_sheets = int(round(resolved_total_sheets * 0.01))
            if one_pct_sheets >= 1:
                m1_pane_label = f'≥{major1_thresh}(1%約={one_pct_sheets:,}張)'

        chip_pane_labels = [
            ('y domain', '外資'),
            ('y2 domain', '投信'),
            ('y3 domain', '自營'),
            ('y4 domain', '資券'),
            ('y6 domain', m1_pane_label),
            ('y8 domain', f'≥{major2_thresh}'),
        ]

    for y_ref_str, lbl_c in chip_pane_labels:
        fig_chip.add_annotation(
            x=0.006, y=0.98, xref='paper', yref=y_ref_str,
            xanchor='left', yanchor='top',
            text=f'<b>{lbl_c}</b>',
            font=dict(size=11, color='#1e293b'),
            bgcolor='rgba(255,255,255,0.82)',
            borderpad=2,
            showarrow=False
        )

    # 【防呆防錯備註 2026-11-13】：
    # 改以標準 Python 字典包裝 fig_tech 與 fig_chip，避免 @st.cache_data 序列化時剝除自訂屬性導致籌碼圖遺失。
    fig_bundle = {"tech": fig_tech, "chip": fig_chip}
    return fig_top, fig_bundle, df, c_name, end_idx, disp_n
# EOF chart_builder.py
