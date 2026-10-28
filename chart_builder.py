"""
台股技術與籌碼分析系統 - Plotly 雙圖繪製模組
負責主圖（K 線、5/20/60MA、頭底標籤、成交量柱、換手率正倒三角標記）
與副圖（9 大技術及籌碼子圖）之繪製，計算初始可視範圍與動態月份 X 軸標籤。
完全相容 app.py 的 build_split_figures 呼叫規格與回傳格式。
"""

MODULE_NAME = "chart_builder"
MODULE_VERSION = "202610281018"

from typing import Optional, Tuple
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from data_fetcher import fetch_stock_data
except ImportError:
    fetch_stock_data = None

try:
    from indicators import calculate_all_indicators
except ImportError:
    calculate_all_indicators = None


def render_split_figures_from_df(
    df: pd.DataFrame,
    pure_code: str,
    market: str,
    c_name: str,
    display_days: int = 20,
    base_date: Optional[object] = None,
    major1_thresh: int = 1000,
    major2_thresh: int = 400,
    is_mobile: bool = False
) -> Tuple[go.Figure, go.Figure, int, int]:
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

    # 主圖價格與成交量初始範圍
    p_max, p_min = float(sub_df['High'].max()), float(sub_df['Low'].min())
    p_pad = (p_max - p_min) * 0.12 if p_max > p_min else 2.0
    vol_col = 'Volume_Sheets' if 'Volume_Sheets' in sub_df.columns else 'Volume'
    vol_upper = float(sub_df[vol_col].max()) * 1.30 if not sub_df[vol_col].empty else 1000.0

    # 2. X 軸月份刻度產生
    month_ticks_vals, month_ticks_text = [], []
    cur_m = None
    for i, d in enumerate(df.index):
        m_str = d.strftime('%Y-%m')
        if m_str != cur_m:
            cur_m = m_str
            month_ticks_vals.append(date_str_list[i])
            month_ticks_text.append(d.strftime('%m月'))

    # 上色樣式定義
    vol_colors = ['#eb4d4b' if c >= o else '#2ecc71' for c, o in zip(df['Close'], df['Open'])]
    osc_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df.get('OSC', pd.Series(dtype=float)).fillna(0)]
    m_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df.get('Margin_Diff', pd.Series(dtype=float)).fillna(0)]
    s_colors = ['#f1c40f' if val >= 0 else '#3498db' for val in df.get('Short_Diff', pd.Series(dtype=float)).fillna(0)]

    # 3. 副圖極值與軸邊距計算
    sub_obv = sub_df.get('OBV', pd.Series(dtype=float)).dropna()
    sub_obv_ma = sub_df.get('OBV_MA20', pd.Series(dtype=float)).dropna()
    obv_min = float(min(sub_obv.min(), sub_obv_ma.min())) if not sub_obv_ma.empty else (float(sub_obv.min()) if not sub_obv.empty else 0.0)
    obv_max = float(max(sub_obv.max(), sub_obv_ma.max())) if not sub_obv_ma.empty else (float(sub_obv.max()) if not sub_obv.empty else 100.0)
    obv_pad = (obv_max - obv_min) * 0.10 if obv_max > obv_min else 5.0

    sub_macd_vals = pd.concat([sub_df.get('DIF', pd.Series(dtype=float)), sub_df.get('MACD', pd.Series(dtype=float)), sub_df.get('OSC', pd.Series(dtype=float))]).dropna()
    macd_min = float(sub_macd_vals.min()) if not sub_macd_vals.empty else -1.0
    macd_max = float(sub_macd_vals.max()) if not sub_macd_vals.empty else 1.0
    macd_pad = (macd_max - macd_min) * 0.15 if macd_max > macd_min else 0.5

    def calc_inst_range(series):
        if series is None or series.empty:
            return [-100, 100]
        s_clean = series.dropna()
        if s_clean.empty or (s_clean == 0).all():
            return [-100, 100]
        max_abs = max(abs(float(s_clean.min())), abs(float(s_clean.max())))
        return [-max_abs * 1.25, max_abs * 1.25] if max_abs > 0 else [-100, 100]

    fn_range = calc_inst_range(sub_df.get('Foreign_Net', pd.Series(dtype=float)))
    tn_range = calc_inst_range(sub_df.get('Trust_Net', pd.Series(dtype=float)))
    dn_range = calc_inst_range(sub_df.get('Dealer_Net', pd.Series(dtype=float)))

    ms_vals = pd.concat([sub_df.get('Margin_Diff', pd.Series(dtype=float)), sub_df.get('Short_Diff', pd.Series(dtype=float))]).dropna()
    ms_max_abs = max(abs(float(ms_vals.min())), abs(float(ms_vals.max()))) if not ms_vals.empty else 0
    ms_range = [-ms_max_abs * 1.25, ms_max_abs * 1.25] if ms_max_abs > 0 else [-100, 100]

    def calc_holding_range(series):
        if series is None or series.empty:
            return [0, 100]
        s_clean = series.dropna()
        if s_clean.empty:
            return [0, 100]
        c_min, c_max = float(s_clean.min()), float(s_clean.max())
        pad = max(0.15, (c_max - c_min) * 0.15) if c_max > c_min else 0.5
        return [c_min - pad, c_max + pad]

    m1_range = calc_holding_range(sub_df.get('Major1_Pct', pd.Series(dtype=float)))
    m2_range = calc_holding_range(sub_df.get('Major2_Pct', pd.Series(dtype=float)))

    ratio_clean = sub_df.get('Short_Margin_Ratio', pd.Series(dtype=float)).dropna()
    r_min = float(ratio_clean.min()) if not ratio_clean.empty else 0
    r_max = float(ratio_clean.max()) if not ratio_clean.empty else 10
    r_pad = max(0.5, (r_max - r_min) * 0.15) if r_max > r_min else 1.0
    ratio_range = [max(0, r_min - r_pad), r_max + r_pad]

    top_height = 340 if is_mobile else 380
    btm_height = 1050 if is_mobile else 1150

    # 4. 主圖繪製 (fig_top)
    fig_top = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.035, row_heights=[0.72, 0.28]
    )

    fig_top.add_trace(go.Candlestick(
        x=date_str_list,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b',
        decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71',
        name='K線', hoverinfo='none'
    ), row=1, col=1)

    if 'MA5' in df:
        fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA5'], line=dict(color='#f1c40f', width=1.2), name='MA5', hoverinfo='none'), row=1, col=1)
    if 'MA20' in df:
        fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA20'], line=dict(color='#e67e22', width=1.2), name='MA20', hoverinfo='none'), row=1, col=1)
    if 'MA60' in df:
        fig_top.add_trace(go.Scatter(x=date_str_list, y=df['MA60'], line=dict(color='#9b59b6', width=1.2), name='MA60', hoverinfo='none'), row=1, col=1)

    if 'Is_Head' in df:
        head_df = df[df['Is_Head']]
        if not head_df.empty:
            fig_top.add_trace(go.Scatter(
                x=[d.strftime('%Y-%m-%d') for d in head_df.index],
                y=head_df['High'],
                mode='text',
                text='<b>〔頭〕</b>',
                textposition='top center',
                textfont=dict(family='Arial Black, sans-serif', size=13, color='#27ae60'),
                hoverinfo='none'
            ), row=1, col=1)

    if 'Is_Bottom' in df:
        bottom_df = df[df['Is_Bottom']]
        if not bottom_df.empty:
            fig_top.add_trace(go.Scatter(
                x=[d.strftime('%Y-%m-%d') for d in bottom_df.index],
                y=bottom_df['Low'],
                mode='text',
                text='<b>〔底〕</b>',
                textposition='bottom center',
                textfont=dict(family='Arial Black, sans-serif', size=13, color='#e74c3c'),
                hoverinfo='none'
            ), row=1, col=1)

    v_series = df[vol_col]
    fig_top.add_trace(go.Bar(
        x=date_str_list, y=v_series, marker_color=vol_colors, name='成交量', hoverinfo='none'
    ), row=2, col=1)

    to_col = 'Turnover_Rate' if 'Turnover_Rate' in df.columns else ('Turnover' if 'Turnover' in df.columns else None)
    if to_col:
        t10_df = df[(df[to_col] >= 10.0) & (df[to_col] < 20.0)]
        if not t10_df.empty:
            fig_top.add_trace(go.Scatter(
                x=[d.strftime('%Y-%m-%d') for d in t10_df.index],
                y=t10_df[vol_col],
                mode='text',
                text='▲',
                textposition='top center',
                textfont=dict(family='Arial, sans-serif', size=15, color='#1e3799'),
                hoverinfo='none',
                name='換手≥10%'
            ), row=2, col=1)

        t20_df = df[df[to_col] >= 20.0]
        if not t20_df.empty:
            fig_top.add_trace(go.Scatter(
                x=[d.strftime('%Y-%m-%d') for d in t20_df.index],
                y=t20_df[vol_col],
                mode='text',
                text='▼',
                textposition='top center',
                textfont=dict(family='Arial, sans-serif', size=15, color='#f1c40f'),
                hoverinfo='none',
                name='換手≥20%'
            ), row=2, col=1)

    # 股票名稱(代號) (市場) 台股技術與籌碼分析(模組化)(版本號)
    stock_display = f"{c_name}({pure_code})" if c_name and c_name != pure_code else pure_code
    title_text = f"{stock_display} ({market}) 台股技術與籌碼分析(模組化)({MODULE_VERSION})"

    fig_top.update_layout(
        title=dict(text=title_text, font=dict(size=16)),
        font=dict(size=16),
        template='plotly_white', hovermode=False, dragmode='pan', showlegend=False,
        height=top_height,
        margin=dict(l=80, r=15, t=35, b=20, autoexpand=False),
        xaxis_rangeslider_visible=False
    )
    fig_top.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], row=1, col=1)
    fig_top.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text, row=2, col=1)
    fig_top.update_yaxes(title_text='價格', range=[p_min - (p_max - p_min) * 0.08, p_max + p_pad], fixedrange=True, row=1, col=1)
    fig_top.update_yaxes(title_text='成交量', range=[0, vol_upper], fixedrange=True, row=2, col=1)

    # 5. 副圖繪製 (fig_btm: 9 大子圖)
    fig_btm = make_subplots(
        rows=9, cols=1, shared_xaxes=True, vertical_spacing=0.02,
        row_heights=[0.13, 0.12, 0.11, 0.10, 0.10, 0.10, 0.14, 0.10, 0.10],
        specs=[[{}], [{}], [{}], [{}], [{}], [{}], [{"secondary_y": True}], [{}], [{}]]
    )

    if 'K' in df and 'D' in df:
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['K'], line=dict(color='#e74c3c', width=1.2), hoverinfo='none'), row=1, col=1)
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['D'], line=dict(color='#3498db', width=1.2), hoverinfo='none'), row=1, col=1)
        fig_btm.add_hline(y=80, line_dash='dot', line_color='rgba(150,150,150,0.5)', row=1, col=1)
        fig_btm.add_hline(y=20, line_dash='dot', line_color='rgba(150,150,150,0.5)', row=1, col=1)

    if 'OSC' in df:
        fig_btm.add_trace(go.Bar(x=date_str_list, y=df['OSC'], marker_color=osc_colors, hoverinfo='none'), row=2, col=1)
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df.get('DIF', pd.Series(dtype=float)), line=dict(color='#f39c12', width=1.2), hoverinfo='none'), row=2, col=1)
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df.get('MACD', pd.Series(dtype=float)), line=dict(color='#2980b9', width=1.2), hoverinfo='none'), row=2, col=1)

    if 'OBV' in df:
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['OBV'], line=dict(color='#16a085', width=1.2), hoverinfo='none'), row=3, col=1)
        if 'OBV_MA20' in df:
            fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['OBV_MA20'], line=dict(color='#8e44ad', width=1.1, dash='dash'), hoverinfo='none'), row=3, col=1)

    f_net = df.get('Foreign_Net', pd.Series(dtype=float)).fillna(0)
    fig_btm.add_trace(go.Bar(x=date_str_list, y=f_net, marker_color=['#eb4d4b' if x >= 0 else '#2ecc71' for x in f_net], hoverinfo='none'), row=4, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=4, col=1)

    t_net = df.get('Trust_Net', pd.Series(dtype=float)).fillna(0)
    fig_btm.add_trace(go.Bar(x=date_str_list, y=t_net, marker_color=['#eb4d4b' if x >= 0 else '#2ecc71' for x in t_net], hoverinfo='none'), row=5, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=5, col=1)

    d_net = df.get('Dealer_Net', pd.Series(dtype=float)).fillna(0)
    fig_btm.add_trace(go.Bar(x=date_str_list, y=d_net, marker_color=['#eb4d4b' if x >= 0 else '#2ecc71' for x in d_net], hoverinfo='none'), row=6, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=6, col=1)

    m_diff = df.get('Margin_Diff', pd.Series(dtype=float)).fillna(0)
    s_diff = df.get('Short_Diff', pd.Series(dtype=float)).fillna(0)
    fig_btm.add_trace(go.Bar(x=date_str_list, y=m_diff, marker_color=m_colors, name='融資', width=0.4, offset=-0.4, hoverinfo='none'), secondary_y=False, row=7, col=1)
    fig_btm.add_trace(go.Bar(x=date_str_list, y=s_diff, marker_color=s_colors, name='融券', width=0.4, offset=0.0, hoverinfo='none'), secondary_y=False, row=7, col=1)
    fig_btm.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=7, col=1)

    if 'Short_Margin_Ratio' in df:
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['Short_Margin_Ratio'], line=dict(color='#e67e22', width=1.5), connectgaps=True, name='券資比', hoverinfo='none'), secondary_y=True, row=7, col=1)

    if 'Major1_Pct' in df:
        fig_btm.add_trace(go.Scatter(x=date_str_list, y=df['Major1_Pct'], line=dict(color='#c0392b', width=1.5, shape='hv'), connectgaps=True, hoverinfo='none'), row=8, col=1)
    if 'Major2_Pct' in df:
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

    return fig_top, fig_btm, end_idx, disp_n


def build_split_figures(
    raw_ticker,
    period='1y',
    display_days=20,
    base_date=None,
    major1_thresh=1000,
    major2_thresh=400,
    is_mobile=False,
    status_placeholder=None,
    *args,
    **kwargs
):
    if isinstance(raw_ticker, pd.DataFrame):
        df = raw_ticker
        pure_code = str(period)
        market = str(display_days)
        c_name = str(base_date or pure_code)
        days = int(kwargs.get('display_days', 20))
        b_date = kwargs.get('base_date', None)
        m1 = int(kwargs.get('major1_thresh', 1000))
        m2 = int(kwargs.get('major2_thresh', 400))
        mob = bool(kwargs.get('is_mobile', False))
        f_top, f_btm, e_idx, d_n = render_split_figures_from_df(df, pure_code, market, c_name, days, b_date, m1, m2, mob)
        return f_top, f_btm, df, c_name, e_idx, d_n

    if fetch_stock_data is None or calculate_all_indicators is None:
        raise RuntimeError("無法匯入資料擷取或指標運算函式。")

    df_raw, full_ticker, pure_code, market, c_name, shares_outstanding = fetch_stock_data(raw_ticker, period)
    if df_raw is None or df_raw.empty:
        return None, None, None, "", None, 0

    df = calculate_all_indicators(df_raw, pure_code, major1_thresh, major2_thresh, shares_outstanding, status_placeholder)
    if df is None or df.empty:
        return None, None, None, "", None, 0

    fig_top, fig_btm, end_idx, disp_n = render_split_figures_from_df(
        df=df,
        pure_code=pure_code,
        market=market,
        c_name=c_name,
        display_days=display_days,
        base_date=base_date,
        major1_thresh=major1_thresh,
        major2_thresh=major2_thresh,
        is_mobile=is_mobile
    )

    return fig_top, fig_btm, df, c_name, end_idx, disp_n
