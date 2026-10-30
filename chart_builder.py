"""
chart_builder.py - Plotly 圖表建構與前端互動渲染模組
"""

import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from data_fetcher import fetch_stock_data, save_stock_history
except ImportError:
    fetch_stock_data, save_stock_history = None, None

try:
    from indicators import calculate_all_indicators
except ImportError:
    calculate_all_indicators = None

LEGEND_HTML = """
<style>
  @keyframes app-spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  .app-loading-ring { display: inline-block; width: 14px; height: 14px; border: 2.5px solid rgba(41, 128, 185, 0.25); border-top: 2.5px solid #2980b9; border-radius: 50%; animation: app-spin 0.8s linear infinite; vertical-align: middle; margin-left: 6px; }
</style>
<div style="font-size: 15px; line-height: 1.6; margin-bottom: 6px; padding: 4px 10px; background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
  <b>主圖：</b><span style="color:#eb4d4b;">■</span> K線 <span style="color:#27ae60;font-weight:bold;">〔頭〕</span> <span style="color:#e74c3c;font-weight:bold;">〔底〕</span> <span style="color:#f1c40f;">MA5</span> <span style="color:#e67e22;">MA20</span> <span style="color:#9b59b6;">MA60</span> |
  <b>技術：</b><span style="color:#eb4d4b;">■</span> 量/OSC <span style="color:#1e3799; font-weight:bold;">━</span> 換手 <span style="color:#e74c3c;">K</span> <span style="color:#3498db;">D</span> <span style="color:#f39c12;">DIF</span> <span style="color:#2980b9;">MACD</span> <span style="color:#16a085;">OBV</span> |
  <b>法人：</b><span style="color:#eb4d4b;">■</span> 外/投/自 <span style="color:#c0392b;">大1</span> <span style="color:#8e44ad;">大2</span> |
  <b>資券：</b><span style="color:#eb4d4b;">■</span>(左)融資 <span style="color:#f1c40f;">■</span>(右)融券 <span style="color:#e67e22;">━</span> 券資比
</div>
"""

def build_split_figures(raw_ticker, period, display_days, base_date=None, major1_thresh=1000, major2_thresh=400, is_mobile=False, status_placeholder=None):
    if fetch_stock_data is None or calculate_all_indicators is None:
        raise ImportError("缺少必要的模組：data_fetcher 或 indicators")

    df_raw, full_ticker, pure_code, market, c_name, shares_outstanding = fetch_stock_data(raw_ticker, period)
    if df_raw is None or df_raw.empty:
        return None, None, None, "", None, 0

    if save_stock_history:
        save_stock_history(pure_code, c_name)

    df = calculate_all_indicators(df_raw, pure_code, major1_thresh, major2_thresh, shares_outstanding, status_placeholder)

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
    sub_df = df.iloc[start_idx:end_idx+1]
    
    # K 線價格 Y 軸範圍（避免從 0 起算）
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

    # OBV 範圍
    sub_obv = sub_df['OBV'].dropna()
    sub_obv_ma = sub_df['OBV_MA20'].dropna()
    obv_min = float(min(sub_obv.min(), sub_obv_ma.min())) if not sub_obv_ma.empty else float(sub_obv.min())
    obv_max = float(max(sub_obv.max(), sub_obv_ma.max())) if not sub_obv_ma.empty else float(sub_obv.max())
    obv_pad = (obv_max - obv_min) * 0.10 if obv_max > obv_min else 5.0

    # MACD 範圍
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
    r_min, r_max = float(ratio_clean.min()) if not ratio_clean.empty else 0, float(ratio_clean.max()) if not ratio_clean.empty else 10
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

    # 轉折頭底標籤
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

    # 成交量柱與加粗換手率
    fig_top.add_trace(go.Bar(x=date_str_list, y=df['Volume_Sheets'], marker_color=vol_colors, name='成交量', hoverinfo='none'), secondary_y=False, row=2, col=1)
    fig_top.add_trace(go.Scatter(x=date_str_list, y=df['Turnover_Rate'], line=dict(color='#1e3799', width=3.9), connectgaps=True, name='換手率', hoverinfo='none'), secondary_y=True, row=2, col=1)

    fig_top.update_layout(
        title=dict(text=f'{c_name or pure_code} ({market}) 多指標+籌碼技術分析圖', font=dict(size=16)),
        font=dict(size=16),
        template='plotly_white', hovermode=False, dragmode='pan', showlegend=False,
        height=top_height,
        margin=dict(l=80, r=15, t=35, b=20, autoexpand=False),
        xaxis_rangeslider_visible=False
    )
    fig_top.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], row=1, col=1)
    fig_top.update_xaxes(type='category', range=[start_idx - 0.5, end_idx + 0.5], domain=[0, 1], showticklabels=True, tickvals=month_ticks_vals, ticktext=month_ticks_text, row=2, col=1)
    
    # 鎖定 Y 軸不上下移動 (fixedrange=True) 並動態緊貼價格
    fig_top.update_yaxes(title_text='價格', range=[p_min - (p_max - p_min) * 0.08, p_max + p_pad], fixedrange=True, row=1, col=1)
    fig_top.update_yaxes(title_text='成交量', range=[0, vol_upper], fixedrange=True, secondary_y=False, row=2, col=1)
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

def get_component_html(fig_top, fig_btm, df, raw_ticker, major1_thresh, major2_thresh, initial_end_idx, initial_disp_days, is_mobile=False):
    chart_id = f"chart_{raw_ticker.replace('.', '_')}"
    top_h_css = "340px" if is_mobile else "380px"
    btm_h_css = "1050px" if is_mobile else "1150px"

    js_template = """
    <style>
      .plot-main-container { position: relative; width: 100%; box-sizing: border-box; overflow-x: auto; padding-bottom: 90px !important; }
      .touch-plot-box { position: relative; touch-action: none !important; user-select: none !important; -webkit-user-select: none !important; width: 100% !important; }
      .pane-info-bar { font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #2c3e50; background: #f8fafc; padding: 4px 8px; border-radius: 4px; border: 1px solid #e2e8f0; white-space: normal; line-height: 1.45; box-shadow: 0 1px 2px rgba(0,0,0,0.03); overflow-x: auto; }
      .val-up { color: #eb4d4b; font-weight: bold; }
      .val-dn { color: #2ecc71; font-weight: bold; }
      .tag-lbl { margin-right: 5px; }
      .middle-inserted-bar { width: 100%; box-sizing: border-box; margin: 4px 0; display: flex; flex-direction: column; gap: 4px; }
      .middle-inserted-bar .pane-info-bar { width: 100%; box-sizing: border-box; }
      .bottom-chip-deck { width: 100%; box-sizing: border-box; margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }
      .bottom-chip-deck .pane-info-bar { width: 100%; box-sizing: border-box; }
      .sync-crosshair-line { position: absolute; top: 0; bottom: 0; width: 1px; border-left: 1px dotted #2c3e50; pointer-events: none; display: none; z-index: 100; }
      .sync-price-line { position: absolute; left: 80px; right: 15px; height: 1px; border-top: 1px dotted rgba(44, 62, 80, 0.75); pointer-events: none; display: none; z-index: 100; }
    </style>
    <div class="plot-main-container">
        <div id="__CHART_ID___info1" class="pane-info-bar" style="margin-bottom: 2px;">正在載入...</div>
        <div id="__CHART_ID___top" class="touch-plot-box" style="height: __TOP_H__;">
            <div id="__CHART_ID___line_top" class="sync-crosshair-line"></div>
            <div id="__CHART_ID___line_price" class="sync-price-line"></div>
        </div>
        <div class="middle-inserted-bar">
            <div id="__CHART_ID___info_tech1" class="pane-info-bar"></div>
            <div id="__CHART_ID___info_tech2" class="pane-info-bar"></div>
        </div>
        <div id="__CHART_ID___btm" class="touch-plot-box" style="height: __BTM_H__;">
            <div id="__CHART_ID___line_btm" class="sync-crosshair-line"></div>
        </div>
        <div class="bottom-chip-deck">
            <div id="__CHART_ID___info_ms" class="pane-info-bar"></div>
            <div id="__CHART_ID___info_chip" class="pane-info-bar"></div>
        </div>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
    (function() {
        var pTop = __PLOT_JSON_TOP__;
        var pBtm = __PLOT_JSON_BTM__;
        var dates = __DATES__;
        var opens = __OPENS__, highs = __HIGHS__, lows = __LOWS__, closes = __CLOSES__, vols = __VOLS__;
        var ma5s = __MA5S__, ma20s = __MA20S__, ma60s = __MA60S__;
        var turnovers = __TURNOVERS__;
        var ks = __KS__, ds = __DS__, difs = __DIFS__, macds = __MACDS__, oscs = __OSCS__;
        var obvs = __OBVS__, obvMas = __OBVMAS__;
        var foreigns = __FOREIGNS__, trusts = __TRUSTS__, dealers = __DEALERS__;
        var mDiffs = __MARGIN_DIFFS__, sDiffs = __SHORT_DIFFS__, rat = __RATIOS__;
        var m1_pcts = __M1_PCTS__, m2_pcts = __M2_PCTS__, m1_thresh = __M1_THRESH__, m2_thresh = __M2_THRESH__;

        var elTop = document.getElementById('__CHART_ID___top'), elBtm = document.getElementById('__CHART_ID___btm');
        var lineTop = document.getElementById('__CHART_ID___line_top'), lineBtm = document.getElementById('__CHART_ID___line_btm'), linePrice = document.getElementById('__CHART_ID___line_price');
        var info1 = document.getElementById('__CHART_ID___info1'), infoTech1 = document.getElementById('__CHART_ID___info_tech1'), infoTech2 = document.getElementById('__CHART_ID___info_tech2');
        var infoMs = document.getElementById('__CHART_ID___info_ms'), infoChip = document.getElementById('__CHART_ID___info_chip');

        var totalPoints = dates.length;
        var isUpdating = false;
        var debounceTimer = null;

        var targetDays = Number(__INITIAL_DISP_DAYS__) || 20;
        var initEnd = __INITIAL_END_IDX__;
        var initStart = Math.max(0, initEnd - targetDays + 1);

        pTop.layout.xaxis.range = [initStart - 0.5, initEnd + 0.5];
        pTop.layout.xaxis2.range = [initStart - 0.5, initEnd + 0.5];
        for (var r = 1; r <= 9; r++) {
            var k = (r === 1) ? 'xaxis' : 'xaxis' + r;
            if (pBtm.layout[k]) {
                pBtm.layout[k].range = [initStart - 0.5, initEnd + 0.5];
            }
        }

        Plotly.newPlot(elTop, pTop.data, pTop.layout, {responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: false});
        Plotly.newPlot(elBtm, pBtm.data, pBtm.layout, {responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: false});

        var spinEl = document.getElementById('app_loading_spinner');
        if (spinEl) { spinEl.style.display = 'none'; }

        if (window.ResizeObserver) {
            var ro = new ResizeObserver(entries => {
                window.requestAnimationFrame(() => {
                    Plotly.Plots.resize(elTop);
                    Plotly.Plots.resize(elBtm);
                });
            });
            ro.observe(elTop);
            ro.observe(elBtm);
        }

        function isValidNum(v) { return v !== null && v !== undefined && !isNaN(v); }
        function fmtNum(v, d) { return !isValidNum(v) ? '-' : Number(v).toFixed(d); }
        function fmtNet(v, dec) {
            if (!isValidNum(v)) return '-';
            var s = Number(v).toFixed(dec);
            return v > 0 ? '<span class="val-up">+' + s + '</span>' : (v < 0 ? '<span class="val-dn">' + s + '</span>' : '<span>' + s + '</span>');
        }
        function fmtNetShort(v, dec) {
            if (!isValidNum(v)) return '-';
            var s = Number(v).toFixed(dec);
            return v > 0 ? '<span style="color:#f1c40f;font-weight:bold;">+' + s + '</span>' : (v < 0 ? '<span style="color:#3498db;font-weight:bold;">' + s + '</span>' : '<span>' + s + '</span>');
        }

        function updateAllPanes(idx) {
            if (idx < 0 || idx >= totalPoints) return;
            var d = dates[idx], c = closes[idx], prevC = idx > 0 ? closes[idx - 1] : opens[idx];
            var chg = (isValidNum(c) && isValidNum(prevC)) ? (c - prevC) : 0;
            var chgPct = (isValidNum(prevC) && prevC > 0) ? (chg / prevC * 100) : 0;
            var cClass = chg > 0 ? 'val-up' : (chg < 0 ? 'val-dn' : ''), sign = chg > 0 ? '+' : '';
            var toStr = isValidNum(turnovers[idx]) ? fmtNum(turnovers[idx], 2) + '%' : '-';

            info1.innerHTML = '<span class="tag-lbl"><b>' + d + '</b></span>開:<span class="' + cClass + '">' + fmtNum(opens[idx], 2) + '</span> 高:<span class="' + cClass + '">' + fmtNum(highs[idx], 2) + '</span> 低:<span class="' + cClass + '">' + fmtNum(lows[idx], 2) + '</span> 收:<span class="' + cClass + '">' + fmtNum(c, 2) + ' (' + sign + fmtNum(chg, 2) + ', ' + sign + fmtNum(chgPct, 2) + '%)</span> 量:<span>' + fmtNum(vols[idx], 0) + '張</span> <span style="color:#1e3799;font-weight:bold;">換手:' + toStr + '</span> <span style="color:#f1c40f;">MA5:' + fmtNum(ma5s[idx], 2) + '</span> <span style="color:#e67e22;">MA20:' + fmtNum(ma20s[idx], 2) + '</span> <span style="color:#9b59b6;">MA60:' + fmtNum(ma60s[idx], 2) + '</span>';

            var oscClass = oscs[idx] > 0 ? 'val-up' : (oscs[idx] < 0 ? 'val-dn' : '');
            infoTech1.innerHTML = '<span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:' + fmtNum(ks[idx], 1) + '</span> <span style="color:#3498db;">D:' + fmtNum(ds[idx], 1) + '</span> | <span class="tag-lbl"><b>MACD(' + d + ')</b></span><span style="color:#f39c12;">DIF:' + fmtNum(difs[idx], 2) + '</span> <span style="color:#2980b9;">MACD:' + fmtNum(macds[idx], 2) + '</span> OSC:<span class="' + oscClass + '">' + fmtNum(oscs[idx], 2) + '</span>';
            infoTech2.innerHTML = '<span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:' + fmtNum(obvs[idx], 0) + '</span> <span style="color:#8e44ad;">MA20:' + fmtNum(obvMas[idx], 0) + '</span>';

            infoMs.innerHTML = '<span class="tag-lbl"><b>資券[千張](' + d + ')</b></span>融資:' + fmtNet(mDiffs[idx], 3) + ' 融券:' + fmtNetShort(sDiffs[idx], 3) + ' <span style="color:#e67e22;font-weight:bold;">券資比:' + (isValidNum(rat[idx]) ? fmtNum(rat[idx], 2) + '%' : '-') + '</span>';
            infoChip.innerHTML = '<span class="tag-lbl"><b>法人集保(' + d + ')</b></span>外資:' + fmtNet(foreigns[idx], 0) + ' 投信:' + fmtNet(trusts[idx], 0) + ' 自營:' + fmtNet(dealers[idx], 0) + ' | <span style="color:#c0392b;">≥' + m1_thresh + '張: ' + (isValidNum(m1_pcts[idx]) ? fmtNum(m1_pcts[idx], 2) + '%' : '-') + '</span> <span style="color:#8e44ad;">≥' + m2_thresh + '張: ' + (isValidNum(m2_pcts[idx]) ? fmtNum(m2_pcts[idx], 2) + '%' : '-') + '</span>';
        }

        function setCrosshair(idx) {
            if (idx < 0 || idx >= totalPoints) return;
            try {
                var xaTop = elTop._fullLayout.xaxis, xPxTop = elTop._fullLayout._size.l + xaTop.c2p(idx);
                lineTop.style.left = xPxTop + 'px'; lineTop.style.display = 'block';
                var xaBtm = elBtm._fullLayout.xaxis, xPxBtm = elBtm._fullLayout._size.l + xaBtm.c2p(idx);
                lineBtm.style.left = xPxBtm + 'px'; lineBtm.style.display = 'block';
                var yaTop = elTop._fullLayout.yaxis, cVal = closes[idx];
                if (isValidNum(cVal) && yaTop) {
                    var yPxTop = elTop._fullLayout._size.t + yaTop.c2p(cVal);
                    linePrice.style.top = yPxTop + 'px'; linePrice.style.display = 'block';
                } else { linePrice.style.display = 'none'; }
                updateAllPanes(idx);
            } catch (err) {}
        }

        setCrosshair(__INITIAL_END_IDX__);

        function recalcVisibleExtremes(x0, x1) {
            try {
                var iStart = Math.max(0, Math.floor(x0)), iEnd = Math.min(totalPoints - 1, Math.ceil(x1));
                if (iEnd <= iStart) return;

                var cMaxP = -Infinity, cMinP = Infinity, cMaxVol = 0, cMaxTo = 0, cMaxMacd = -Infinity, cMinMacd = Infinity, cMaxObv = -Infinity, cMinObv = Infinity;
                var cMaxFn = 0, cMaxTn = 0, cMaxDn = 0, cMaxMs = 0, cMaxRat = -Infinity, cMinRat = Infinity, cMaxM1 = -Infinity, cMinM1 = Infinity, cMaxM2 = -Infinity, cMinM2 = Infinity;

                for (var i = iStart; i <= iEnd; i++) {
                    if (isValidNum(highs[i]) && highs[i] > cMaxP) cMaxP = highs[i];
                    if (isValidNum(lows[i]) && lows[i] < cMinP) cMinP = lows[i];
                    if (isValidNum(vols[i]) && vols[i] > cMaxVol) cMaxVol = vols[i];
                    if (isValidNum(turnovers[i]) && turnovers[i] > cMaxTo) cMaxTo = turnovers[i];
                    [difs[i], macds[i], oscs[i]].forEach(function(v) { if (isValidNum(v)) { if (v > cMaxMacd) cMaxMacd = v; if (v < cMinMacd) cMinMacd = v; } });
                    [obvs[i], obvMas[i]].forEach(function(v) { if (isValidNum(v)) { if (v > cMaxObv) cMaxObv = v; if (v < cMinObv) cMinObv = v; } });
                    if (isValidNum(foreigns[i]) && Math.abs(foreigns[i]) > cMaxFn) cMaxFn = Math.abs(foreigns[i]);
                    if (isValidNum(trusts[i]) && Math.abs(trusts[i]) > cMaxTn) cMaxTn = Math.abs(trusts[i]);
                    if (isValidNum(dealers[i]) && Math.abs(dealers[i]) > cMaxDn) cMaxDn = Math.abs(dealers[i]);
                    if (isValidNum(mDiffs[i]) && Math.abs(mDiffs[i]) > cMaxMs) cMaxMs = Math.abs(mDiffs[i]);
                    if (isValidNum(sDiffs[i]) && Math.abs(sDiffs[i]) > cMaxMs) cMaxMs = Math.abs(sDiffs[i]);
                    if (isValidNum(rat[i])) { if (rat[i] > cMaxRat) cMaxRat = rat[i]; if (rat[i] < cMinRat) cMinRat = rat[i]; }
                    if (isValidNum(m1_pcts[i])) { if (m1_pcts[i] > cMaxM1) cMaxM1 = m1_pcts[i]; if (m1_pcts[i] < cMinM1) cMinM1 = m1_pcts[i]; }
                    if (isValidNum(m2_pcts[i])) { if (m2_pcts[i] > cMaxM2) cMaxM2 = m2_pcts[i]; if (m2_pcts[i] < cMinM2) cMinM2 = m2_pcts[i]; }
                }

                if (isFinite(cMinP) && isFinite(cMaxP)) {
                    var tUpd = {'yaxis.range': [cMinP - (cMaxP - cMinP)*0.08, cMaxP + (cMaxP - cMinP)*0.12], 'yaxis2.range': [0, cMaxVol*1.25]};
                    if (cMaxTo > 0) tUpd['yaxis3.range'] = [0, cMaxTo * 1.35];
                    Plotly.relayout(elTop, tUpd);
                }

                var bUpd = {};
                if (isFinite(cMinMacd)) bUpd['yaxis2.range'] = [cMinMacd - Math.max(0.5, (cMaxMacd - cMinMacd)*0.15), cMaxMacd + Math.max(0.5, (cMaxMacd - cMinMacd)*0.15)];
                if (isFinite(cMinObv)) bUpd['yaxis3.range'] = [cMinObv - Math.max(5, (cMaxObv - cMinObv)*0.10), cMaxObv + Math.max(5, (cMaxObv - cMinObv)*0.10)];
                bUpd['yaxis4.range'] = cMaxFn > 0 ? [-cMaxFn*1.25, cMaxFn*1.25] : [-100, 100];
                bUpd['yaxis5.range'] = cMaxTn > 0 ? [-cMaxTn*1.25, cMaxTn*1.25] : [-50, 50];
                bUpd['yaxis6.range'] = cMaxDn > 0 ? [-cMaxDn*1.25, cMaxDn*1.25] : [-50, 50];
                bUpd['yaxis7.range'] = cMaxMs > 0 ? [-cMaxMs*1.25, cMaxMs*1.25] : [-100, 100];
                if (isFinite(cMinRat)) bUpd['yaxis8.range'] = [Math.max(0, cMinRat - Math.max(0.5, (cMaxRat-cMinRat)*0.15)), cMaxRat + Math.max(0.5, (cMaxRat-cMinRat)*0.15)];
                if (isFinite(cMinM1)) bUpd['yaxis9.range'] = [cMinM1 - Math.max(0.15, (cMaxM1-cMinM1)*0.15), cMaxM1 + Math.max(0.15, (cMaxM1-cMinM1)*0.15)];
                if (isFinite(cMinM2)) bUpd['yaxis10.range'] = [cMinM2 - Math.max(0.15, (cMaxM2-cMinM2)*0.15), cMaxM2 + Math.max(0.15, (cMaxM2-cMinM2)*0.15)];
                if (Object.keys(bUpd).length > 0) Plotly.relayout(elBtm, bUpd);
            } catch (err) {}
        }

        function syncRelayout(src, tgt, ed) {
            if (isUpdating) return;
            var r = ed['xaxis.range'] || (ed['xaxis.range[0]'] !== undefined ? [ed['xaxis.range[0]'], ed['xaxis.range[1]']] : (ed['xaxis.autorange'] ? [0, totalPoints-1] : null));
            if (!r) return;

            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function() {
                var span = Math.max(5, Math.min(totalPoints, r[1] - r[0]));
                var r1 = Math.min(totalPoints - 0.5, Math.max(span - 0.5, r[1]));
                var r0 = Math.max(-0.5, r1 - span);
                r1 = r0 + span;

                isUpdating = true;
                recalcVisibleExtremes(r0, r1);
                updateAllPanes(Math.max(0, Math.min(totalPoints-1, Math.round(r1))));

                var u
