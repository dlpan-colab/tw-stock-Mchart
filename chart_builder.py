"""
chart_builder.py - Plotly 圖表建構模組
版本: 202610301645
- 換手率 ≥10% 與 ≥20% 標記於當日成交量柱上方
- 主圖 Y 軸中文徹底移除
- 支援 shares_outstanding 正確傳遞計算換手率
"""

VERSION_TAG = "202610301645"

from typing import Tuple, Optional
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
    status_placeholder=None
) -> Tuple[Optional[go.Figure], Optional[go.Figure], Optional[pd.DataFrame], str, int, int]:

    k_res = fetch_stock_daily_k(raw_ticker, period=period, base_date=str(base_date) if base_date else None)
    if k_res is None or k_res[0] is None or k_res[0].empty:
        return None, None, None, "", 0, 0

    df_raw = k_res[0]
    full_ticker = k_res[1]
    shares_outstanding = k_res[2] if len(k_res) >= 3 else None

    c_name = fetch_stock_name(raw_ticker)
    market = "上市" if full_ticker.endswith(".TW") else "上櫃"

    # 指標與籌碼計算（傳入股數）
    df = calculate_all_indicators(
        df=df_raw,
        pure_code=raw_ticker,
        major1_thresh=major1_thresh,
        major2_thresh=major2_thresh,
        shares_outstanding=shares_outstanding,
        status_placeholder=status_placeholder
    )

    date_str_list = [d.strftime('%Y-%m-%d') for d in df.index]
    total_len = len(df)
    disp_n = min(int(display_days), total_len)

    # 基準日定位
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

    # --- 各子圖可視範圍極值 ---
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

    sub_obv = sub_df['OBV'].dropna()
    sub_obv_ma = sub_df['OBV_MA20'].dropna()
    obv_min = float(min(sub_obv.min(), sub_obv_ma.min())) if not sub_obv_ma.empty else float(sub_obv.min())
    obv_max = float(max(sub_obv.max(), sub_obv_ma.max())) if not sub_obv_ma.empty else float(sub_obv.max())
    obv_pad = (obv_max - obv_min) * 0.10 if obv_max > obv_min else 5.0

    sub_macd_vals = pd.concat([sub_df['DIF'], sub_df['MACD'], sub_df['OSC']]).dropna()
    macd_min = float(sub_macd_vals.min()) if not sub_macd_vals.empty else -1.0
    macd_max = float(sub_macd_vals.max()) if not sub_macd_vals.empty else 1.0
    macd_pad = (macd_max - macd_min) * 0.15 if macd_max > macd_min else 0.5

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

    def calc_holding_range(series):
        s_clean = series.dropna()
        if s_clean.empty:
            return [0, 100]
        c_min, c_max = float(s_clean.min()), float(s_clean.max())
        pad = max(0.15, (c_max - c_min) * 0.15) if c_max > c_min else 0.5
        return [c_min - pad, c_max + pad]

    m1_range = calc_holding_range(sub_df['Major1_Pct'])
    m2_range = calc_holding_range(sub_df['Major2_Pct'])

    ratio_clean = sub_df['Short_Margin_Ratio'].dropna()
    r_min = float(ratio_clean.min()) if not ratio_clean.empty else 0
    r_max = float(ratio_clean.max()) if not ratio_clean.empty else 10
    r_pad = max(0.5, (r_max - r_min) * 0.15) if r_max > r_min else 1.0
    ratio_range = [max(0, r_min - r_pad), r_max + r_pad]

    to_clean = sub_df['Turnover_Rate'].dropna()
    to_max = float(to_clean.max()) if not to_clean.empty else 1.0
    to_range = [0, max(1.0, to_max * 1.35)]

    top_height = 340 if is_mobile else 380
    btm_height = 1050 if is_mobile else 1150

    # ===== 上半部主圖 =====
    fig_top = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.035, row_heights=[0.72, 0.28],
        specs=[[{}], [{"secondary_y": True}]]
    )
    fig_top.add_trace(go.Candlestick(
        x=date_str_list, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b',
        decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71',
        name='K線', hoverinfo='none'
    ), row=1, col=1)

    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA5'], line=dict(color='#f1c40f', width=1.2), name='MA5', hoverinfo='none'), row=1, col=1)
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA20'], line=dict(color='#e67e22', width=1.2), name='MA20', hoverinfo='none'), row=1, col=1)
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA60'], line=dict(color='#9b59b6', width=1.2), name='MA60', hoverinfo='none'), row=1, col=1)

    # 頭底標籤
    head_df = df[df['Is_Head']]
    if not head_df.empty:
        fig_top.add_trace(go.Scatter(
            x=[d.strftime('%Y-%m-%d') for d in head_df.index], y=head_df['High'],
            mode='text', text='<b>〔頭〕</b>', textposition='top center',
            textfont=dict(family='Arial Black, sans-serif', size=13, color='#27ae60'), hoverinfo='none'
        ), row=1, col=1)
    bottom_df = df[df['Is_Bottom']]
    if not bottom_df.empty:
        fig_top.add_trace(go.Scatter(
            x=[d.strftime('%Y-%m-%d') for d in bottom_df.index], y=bottom_df['Low'],
            mode='text', text='<b>〔底〕</b>', textposition='bottom center',
            textfont=dict(family='Arial Black, sans-serif', size=13, color='#e74c3c'), hoverinfo='none'
        ), row=1, col=1)

    # 成交量柱狀圖 (主軸)
    fig_top.add_trace(go.Bar(x=date_str_list, y=df['Volume_Sheets'], marker_color=vol_colors, name='成交量', hoverinfo='none'), secondary_y=False, row=2, col=1)
    
    # 換手率加粗折線 (副軸)
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['Turnover_Rate'], line=dict(color='#1e3799', width=3.9), connectgaps=True, name='換手率', hoverinfo='none'), secondary_y=True, row=2, col=1)

    # 換手率 ≥10% 與 ≥20% 標記在成交量柱上方
    to_series = df['Turnover_Rate']
    to_10_mask = (to_series >= 10.0) & (to_series < 20.0)
    to_20_mask = (to_series >= 20.0)

    if to_10_mask.any():
        fig_top.add_trace(go.Scatter(
            x=[date_str_list[i] for i in range(total_len) if to_10_mask.iloc[i]],
            y=df.loc[to_10_mask, 'Volume_Sheets'] * 1.05,
            mode='text',
            text=['<b>10%</b>' for _ in range(to_10_mask.sum())],
            textposition='top center',
            textfont=dict(family='Arial Black, sans-serif', size=11, color='#f39c12'),
            showlegend=False, hoverinfo='none'
        ), secondary_y=False, row=2, col=1)

    if to_20_mask.any():
        fig_top.add_trace(go.Scatter(
            x=[date_str_list[i] for i in range(total_len) if to_20_mask.iloc[i]],
            y=df.loc[to_20_mask, 'Volume_Sheets'] * 1.05,
            mode='text',
            text=['<b>20%</b>' for _ in range(to_20_mask.sum())],
            textposition='top center',
            textfont=dict(family='Arial Black, sans-serif', size=12, color='#e74c3c'),
            showlegend=False, hoverinfo='none'
        ), secondary_y=False, row=2, col=1)

    fig_top.update_layout(
        title=dict(text=f'{c_name or raw_ticker} ({market}) 多指標+籌碼技術分析圖({VERSION_TAG})', font=dict(size=16)),
        font=dict(size=16),
        template='plotly_white', hovermode=False, dragmode='pan', showlegend=False,
        height=top_height,
        margin=dict(l=80, r=15, t=35, b=20, autoexpand=False),
        xaxis_rangeslider_visible=False
    )
    fig_top.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], row=1, col=1)
    fig_top.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text, row=2, col=1)

    # 移除中文標示
    fig_top.update_yaxes(title_text='', range=[p_min - (p_max - p_min) * 0.08, p_max + p_pad], fixedrange=True, row=1, col=1)
    fig_top.update_yaxes(title_text='', range=[0, vol_upper], fixedrange=True, secondary_y=False, row=2, col=1)
    fig_top.update_yaxes(title_text='', range=to_range, fixedrange=True, secondary_y=True, showgrid=False, showticklabels=False, row=2, col=1)

    # ===== 下半部副圖 =====
    fig_btm = make_subplots(
        rows=9, cols=1, shared_xaxes=True, vertical_spacing=0.02,
        row_heights=[0.13, 0.12, 0.11, 0.10, 0.10, 0.10, 0.14, 0.10, 0.10],
        specs=[[{}], [{}], [{}], [{}], [{}], [{}], [{"secondary_y": True}], [{}], [{}]]
    )
    # Row 1: KD
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['K'], line=dict(color='#e74c3c', width=1.2), hoverinfo='none'), row=1, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['D'], line=dict(color='#3498db', width=1.2), hoverinfo='none'), row=1, col=1)
    fig_btm.add_hline(y=80, line_dash='dot', line_color='rgba(150,150,150,0.5)', row=1, col=1)
    fig_btm.add_hline(y=20, line_dash='dot', line_color='rgba(150,150,150,0.5)', row=1, col=1)

    # Row 2: MACD
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['OSC'], marker_color=osc_colors, hoverinfo='none'), row=2, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['DIF'], line=dict(color='#f39c12', width=1.2), hoverinfo='none'), row=2, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['MACD'], line=dict(color='#2980b9', width=1.2), hoverinfo='none'), row=2, col=1)

    # Row 3: OBV
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['OBV'], line=dict(color='#16a085', width=1.2), hoverinfo='none'), row=3, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['OBV_MA20'], line=dict(color='#8e44ad', width=1.1, dash='dash'), hoverinfo='none'), row=3, col=1)

    # Row 4: 外資
    f_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Foreign_Net'].fillna(0)]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Foreign_Net'], marker_color=f_colors, hoverinfo='none'), row=4, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=4, col=1)

    # Row 5: 投信
    t_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Trust_Net'].fillna(0)]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Trust_Net'], marker_color=t_colors, hoverinfo='none'), row=5, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=5, col=1)

    # Row 6: 自營
    d_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Dealer_Net'].fillna(0)]
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Dealer_Net'], marker_color=d_colors, hoverinfo='none'), row=6, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=6, col=1)

    # Row 7: 資券
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Margin_Diff'], marker_color=m_colors, name='融資', width=0.4, offset=-0.4, hoverinfo='none'), secondary_y=False, row=7, col=1)
    fig_btm.add_trace(go.Bar(x=date_str_list, y=df['Short_Diff'], marker_color=s_colors, name='融券', width=0.4, offset=0.0, hoverinfo='none'), secondary_y=False, row=7, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=7, col=1)
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['Short_Margin_Ratio'], line=dict(color='#e67e22', width=1.5), connectgaps=True, name='券資比', hoverinfo='none'), secondary_y=True, row=7, col=1)

    # Row 8: 大戶 1
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['Major1_Pct'], line=dict(color='#c0392b', width=1.5, shape='hv'), connectgaps=True, hoverinfo='none'), row=8, col=1)

    # Row 9: 大戶 2
    fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['Major2_Pct'], line=dict(color='#8e44ad', width=1.5, shape='hv'), connectgaps=True, hoverinfo='none'), row=9, col=1)

    fig_btm.update_layout(
        font=dict(size=16),
        template='plotly_white', hovermode=False, dragmode='pan', showlegend=False,
        height=btm_height,
        margin=dict(l=80, r=15, t=10, b=30, autoexpand=False),
        xaxis_rangeslider_visible=False
    )
    for r in range(1, 10):
        fig_btm.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], row=r, col=1)
    fig_btm.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text, row=9, col=1)

    # 鎖定所有副圖 Y 軸 (fixedrange=True)
    fig_btm.update_yaxes(title_text='KD', range=[0, 100], fixedrange=True, row=1, col=1)
    fig_btm.update_yaxes(title_text='MACD', range=[macd_min - macd_pad, macd_max + macd_pad], fixedrange=True, row=2, col=1)
    fig_btm.update_yaxes(title_text='OBV', range=[obv_min - obv_pad, obv_max + obv_pad], fixedrange=True, row=3, col=1)
    fig_btm.update_yaxes(title_text='外資', range=fn_range, fixedrange=True, row=4, col=1)
    fig_btm.update_yaxes(title_text='投信', range=tn_range, fixedrange=True, row=5, col=1)
    fig_btm.update_yaxes(title_text='自營', range=dn_range, fixedrange=True, row=6, col=1)
    fig_btm.update_yaxes(title_text='資券', range=ms_range, fixedrange=True, secondary_y=False, row=7, col=1)
    fig_btm.update_yaxes(title_text='', range=ratio_range, fixedrange=True, secondary_y=True, showgrid=False, showticklabels=False, row=7, col=1)
    fig_btm.update_yaxes(title_text=f'≥{major1_thresh}', range=m1_range, fixedrange=True, row=8, col=1)
    fig_btm.update_yaxes(title_text=f'≥{major2_thresh}', range=m2_range, fixedrange=True, row=9, col=1)

    return fig_top, fig_btm, df, c_name, end_idx, disp_n
