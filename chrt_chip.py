融券維持率區分長期與季別(3)
"""
chrt_chip.py - Plotly 籌碼頁籤副圖建置模組
(自 chart_builder.py 依邏輯職責拆分，維持既有大盤/櫃買6列三大法人及八大官股/資券/融資金額副圖與個股6列法人資券大戶副圖機制，副圖長標題改雙行顯示杜絕裁切、字體與資訊條同為12px且文字顏色與折線圖顏色一致)
版本: 202611272215
"""

from typing import Optional, List
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MODULE_NAME = "chrt_chip"
MODULE_VERSION = "202611272215"


def build_chip_figure(
    df: pd.DataFrame,
    sub_df: pd.DataFrame,
    date_str_list: List[str],
    start_idx: int,
    end_idx: int,
    month_ticks_vals: List[str],
    month_ticks_text: List[str],
    raw_ticker: str,
    major1_thresh: int,
    major2_thresh: int,
    shares_outstanding: Optional[float],
    is_mobile: bool,
) -> go.Figure:
    """
    【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 將過長之單行副圖標題（個股第 4 列、指數第 5 列）改為 `<br>` 雙行標題並靠右對齊（`x=0.994, xanchor='right'`），維持 `size=12` 與折線同色標示，徹底解決手機直向視窗右側文字被砍斷之問題。
       - 針對長期（全期間）與季（近 60 日）維持率數值完全重合時視覺上互相遮蔽之情況，將「長期」維持率改為加粗半透明底線（`width=3.2`），「季」維持率改為高對比點線（`width=2.0, dash='dot'`），重合時呈現雙色交錯線條，5 條折線清晰可辨。
    2. 防呆防錯原因：維持既有雙次軸結構（`y`～`y9`）與上下界自適應範圍計算，空序列自動回退安全預設值避免縮放異常。
    """
    m_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df['Margin_Diff'].fillna(0)]
    s_colors = ['#f1c40f' if val >= 0 else '#3498db' for val in df['Short_Diff'].fillna(0)]
    mm_colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df['Margin_Money_Diff'].fillna(0)]

    def calc_inst_range(series, default_bound: float = 100.0):
        s_clean = series.dropna()
        if s_clean.empty or (s_clean == 0).all():
            return [-default_bound, default_bound]
        max_abs = max(abs(float(s_clean.min())), abs(float(s_clean.max())))
        return [-max_abs * 1.25, max_abs * 1.25] if max_abs > 0 else [-default_bound, default_bound]

    raw_upper = str(raw_ticker).strip().upper()
    is_tw_index = raw_upper in ("^TWII", "^TWOII")
    mkt_prefix = "上櫃" if raw_upper == "^TWOII" else "上市"
    inst_default_b = 10.0 if is_tw_index else 100.0

    fn_range = calc_inst_range(sub_df['Foreign_Net'], inst_default_b)
    tn_range = calc_inst_range(sub_df['Trust_Net'], inst_default_b)
    dn_range = calc_inst_range(sub_df['Dealer_Net'], inst_default_b)
    gov8_series = sub_df['Gov8_Net'] if 'Gov8_Net' in sub_df.columns else pd.Series([0.0] * len(sub_df))
    g8_range = calc_inst_range(gov8_series, 10.0)

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

    if is_tw_index:
        maint_parts_r5 = [
            sub_df['Margin_Maint_Pct'].dropna() if 'Margin_Maint_Pct' in sub_df.columns else pd.Series(dtype=float),
            sub_df['Short_Maint_Pct'].dropna() if 'Short_Maint_Pct' in sub_df.columns else pd.Series(dtype=float),
            sub_df['Short_Maint_60D_Pct'].dropna() if 'Short_Maint_60D_Pct' in sub_df.columns else pd.Series(dtype=float),
        ]
        maint_vals = pd.concat(maint_parts_r5)
        r_min = float(maint_vals.min()) if not maint_vals.empty else 120.0
        r_max = float(maint_vals.max()) if not maint_vals.empty else 230.0
        r_pad = max(2.0, (r_max - r_min) * 0.15) if r_max > r_min else 5.0
        ratio_range = [max(0, r_min - r_pad), r_max + r_pad]

        mmaint_parts = []
        if 'Margin_Maint_Pct' in sub_df.columns and not sub_df['Margin_Maint_Pct'].dropna().empty:
            mmaint_parts.append(sub_df['Margin_Maint_Pct'].dropna())
        if 'Margin_Maint_60D_Pct' in sub_df.columns and not sub_df['Margin_Maint_60D_Pct'].dropna().empty:
            mmaint_parts.append(sub_df['Margin_Maint_60D_Pct'].dropna())
        mmaint_clean = pd.concat(mmaint_parts) if mmaint_parts else pd.Series(dtype=float)
        mm_r_min = float(mmaint_clean.min()) if not mmaint_clean.empty else 130.0
        mm_r_max = float(mmaint_clean.max()) if not mmaint_clean.empty else 180.0
        mm_r_pad = max(1.5, (mm_r_max - mm_r_min) * 0.15) if mm_r_max > mm_r_min else 3.0
        mmaint_range = [max(0, mm_r_min - mm_r_pad), mm_r_max + mm_r_pad]
    else:
        ratio_clean = sub_df['Short_Margin_Ratio'].dropna() if 'Short_Margin_Ratio' in sub_df.columns else pd.Series(dtype=float)
        r_min = float(ratio_clean.min()) if not ratio_clean.empty else 0.0
        r_max = float(ratio_clean.max()) if not ratio_clean.empty else 10.0
        r_pad = max(0.5, (r_max - r_min) * 0.18) if r_max > r_min else 1.0
        ratio_range = [max(0.0, r_min - r_pad), r_max + r_pad]

        mmaint_parts = []
        if 'Margin_Maint_Pct' in sub_df.columns and not sub_df['Margin_Maint_Pct'].dropna().empty:
            mmaint_parts.append(sub_df['Margin_Maint_Pct'].dropna())
        if 'Margin_Maint_60D_Pct' in sub_df.columns and not sub_df['Margin_Maint_60D_Pct'].dropna().empty:
            mmaint_parts.append(sub_df['Margin_Maint_60D_Pct'].dropna())
        if 'Short_Maint_Pct' in sub_df.columns and not sub_df['Short_Maint_Pct'].dropna().empty:
            mmaint_parts.append(sub_df['Short_Maint_Pct'].dropna())
        if 'Short_Maint_60D_Pct' in sub_df.columns and not sub_df['Short_Maint_60D_Pct'].dropna().empty:
            mmaint_parts.append(sub_df['Short_Maint_60D_Pct'].dropna())
        mmaint_clean = pd.concat(mmaint_parts) if mmaint_parts else pd.Series(dtype=float)
        mm_r_min = float(mmaint_clean.min()) if not mmaint_clean.empty else 120.0
        mm_r_max = float(mmaint_clean.max()) if not mmaint_clean.empty else 180.0
        mm_r_pad = max(2.0, (mm_r_max - mm_r_min) * 0.18) if mm_r_max > mm_r_min else 5.0
        mmaint_range = [max(0.0, mm_r_min - mm_r_pad), mm_r_max + mm_r_pad]

    chip_height = (760 if is_mobile else 800) if is_tw_index else (760 if is_mobile else 800)
    is_index = str(raw_ticker).startswith("^")

    if is_tw_index:
        fig_chip = make_subplots(
            rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.032,
            row_heights=[0.15, 0.15, 0.15, 0.15, 0.21, 0.19],
            specs=[[{}], [{}], [{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}]]
        )

        # 第 1 列：外資每日買賣超（億）
        f_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Foreign_Net'].fillna(0)]
        fig_chip.add_trace(go.Bar(x=date_str_list, y=df['Foreign_Net'], marker_color=f_colors, name='外資(億)', hoverinfo='none'), row=1, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=1, col=1)

        # 第 2 列：投信每日買賣超（億）
        t_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Trust_Net'].fillna(0)]
        fig_chip.add_trace(go.Bar(x=date_str_list, y=df['Trust_Net'], marker_color=t_colors, name='投信(億)', hoverinfo='none'), row=2, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=2, col=1)

        # 第 3 列：自營商每日買賣超（億）
        d_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in df['Dealer_Net'].fillna(0)]
        fig_chip.add_trace(go.Bar(x=date_str_list, y=df['Dealer_Net'], marker_color=d_colors, name='自營(億)', hoverinfo='none'), row=3, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=3, col=1)

        # 第 4 列：八大官股每日買賣超（億）
        gov8_vals = df['Gov8_Net'].fillna(0) if 'Gov8_Net' in df.columns else pd.Series([0.0] * len(df))
        g8_colors = ['#eb4d4b' if x >= 0 else '#2ecc71' for x in gov8_vals]
        fig_chip.add_trace(go.Bar(x=date_str_list, y=gov8_vals, marker_color=g8_colors, name='八大官股(億)', hoverinfo='none'), row=4, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, row=4, col=1)

        # 第 5 列：上市/上櫃資券（千張）增減柱狀＋長期估算融資維持率(橘黃)/長期估算融券維持率(紫粗實線)/季融券維持率(洋紅點線)
        fig_chip.add_trace(go.Bar(
            x=date_str_list, y=df['Margin_Diff'], marker_color=m_colors,
            name=f'{mkt_prefix}融資', width=0.4, offset=-0.4, hoverinfo='none'
        ), secondary_y=False, row=5, col=1)
        fig_chip.add_trace(go.Bar(
            x=date_str_list, y=df['Short_Diff'], marker_color=s_colors,
            name=f'{mkt_prefix}融券', width=0.4, offset=0.0, hoverinfo='none'
        ), secondary_y=False, row=5, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=5, col=1)

        fig_chip.add_trace(go.Scatter(
            x=date_str_list, y=df['Margin_Maint_Pct'], line=dict(color='#e67e22', width=2.4),
            connectgaps=True, hoverinfo='none', name='長期估算融資維持率%'
        ), secondary_y=True, row=5, col=1)
        fig_chip.add_trace(go.Scatter(
            x=date_str_list, y=df['Short_Maint_Pct'], line=dict(color='rgba(142,68,173,0.75)', width=3.2),
            connectgaps=True, hoverinfo='none', name='長期估算融券維持率%'
        ), secondary_y=True, row=5, col=1)
        if 'Short_Maint_60D_Pct' in df.columns:
            fig_chip.add_trace(go.Scatter(
                x=date_str_list, y=df['Short_Maint_60D_Pct'], line=dict(color='#c0392b', width=2.0, dash='dot'),
                connectgaps=True, hoverinfo='none', name='季融券維持率%'
            ), secondary_y=True, row=5, col=1)

        # 第 6 列：上市/上櫃融資金額增減（億）單一柱狀圖＋長期估算融資維持率(橘黃粗實線)/季融資維持率(綠點線)雙折線
        fig_chip.add_trace(go.Bar(
            x=date_str_list, y=df['Margin_Money_Diff'], marker_color=mm_colors,
            name=f'{mkt_prefix}融資金額增減(億)', hoverinfo='none'
        ), secondary_y=False, row=6, col=1)
        fig_chip.add_hline(y=0, line_color='rgba(150,150,150,0.7)', line_width=1, secondary_y=False, row=6, col=1)
        fig_chip.add_trace(go.Scatter(
            x=date_str_list, y=df['Margin_Maint_Pct'], line=dict(color='rgba(230,126,34,0.75)', width=3.2),
            connectgaps=True, hoverinfo='none', name='長期估算融資維持率%'
        ), secondary_y=True, row=6, col=1)
        if 'Margin_Maint_60D_Pct' in df.columns:
            fig_chip.add_trace(go.Scatter(
                x=date_str_list, y=df['Margin_Maint_60D_Pct'], line=dict(color='#16a085', width=2.0, dash='dot'),
                connectgaps=True, hoverinfo='none', name='季融資維持率%'
            ), secondary_y=True, row=6, col=1)

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
        fig_chip.update_yaxes(title_text='', range=g8_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), row=4, col=1)
        fig_chip.update_yaxes(title_text='', range=ms_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=False, row=5, col=1)
        fig_chip.update_yaxes(title_text='', range=ratio_range, showgrid=False, showticklabels=False, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=True, row=5, col=1)
        fig_chip.update_yaxes(title_text='', range=mm_range, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=False, row=6, col=1)
        fig_chip.update_yaxes(title_text='', range=mmaint_range, showgrid=False, showticklabels=False, fixedrange=True, showspikes=False, tickfont=dict(size=11), secondary_y=True, row=6, col=1)

        row5_colored_title = (
            f'{mkt_prefix}資券(千張)/'
            f'<span style="color:#e67e22;">長期估算融資維持率(實)</span><br>'
            f'<span style="color:#8e44ad;">長期估算融券維持率(實)</span>/'
            f'<span style="color:#c0392b;">季融券維持率(點)</span>'
        )
        row6_colored_title = (
            f'{mkt_prefix}融資金額(億)/'
            f'<span style="color:#e67e22;">長期估算融資維持率(實)</span>/'
            f'<span style="color:#16a085;">季融資維持率(點)</span>'
        )
        chip_pane_labels = [
            ('y domain', '外資(億)'),
            ('y2 domain', '投信(億)'),
            ('y3 domain', '自營(億)'),
            ('y4 domain', '八大官股(億)'),
            ('y5 domain', row5_colored_title),
            ('y7 domain', row6_colored_title),
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
                x=date_str_list, y=df['Short_Margin_Ratio'], line=dict(color='#e67e22', width=1.8),
                connectgaps=True, hoverinfo='none', name='券資比%'
            ), secondary_y=True, row=4, col=1)

            if 'Margin_Maint_Pct' in df.columns:
                fig_chip.add_trace(go.Scatter(
                    x=date_str_list, y=df['Margin_Maint_Pct'], line=dict(color='rgba(41,128,185,0.75)', width=3.2),
                    connectgaps=True, hoverinfo='none', name='長期估算融資維持率%',
                    xaxis='x4', yaxis='y9'
                ))
            if 'Margin_Maint_60D_Pct' in df.columns:
                fig_chip.add_trace(go.Scatter(
                    x=date_str_list, y=df['Margin_Maint_60D_Pct'], line=dict(color='#16a085', width=2.0, dash='dot'),
                    connectgaps=True, hoverinfo='none', name='季融資維持率%',
                    xaxis='x4', yaxis='y9'
                ))
            if 'Short_Maint_Pct' in df.columns:
                fig_chip.add_trace(go.Scatter(
                    x=date_str_list, y=df['Short_Maint_Pct'], line=dict(color='rgba(142,68,173,0.75)', width=3.2),
                    connectgaps=True, hoverinfo='none', name='長期估算融券維持率%',
                    xaxis='x4', yaxis='y9'
                ))
            if 'Short_Maint_60D_Pct' in df.columns:
                fig_chip.add_trace(go.Scatter(
                    x=date_str_list, y=df['Short_Maint_60D_Pct'], line=dict(color='#c0392b', width=2.0, dash='dot'),
                    connectgaps=True, hoverinfo='none', name='季融券維持率%',
                    xaxis='x4', yaxis='y9'
                ))

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
            xaxis_rangeslider_visible=False,
            yaxis9=dict(
                overlaying='y4',
                side='right',
                range=mmaint_range,
                showgrid=False,
                showticklabels=False,
                zeroline=False,
                fixedrange=True,
                showspikes=False
            )
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

        stock_row4_colored_title = (
            '資券(千張)/'
            '<span style="color:#2980b9;">長期估算融資維持率(實)</span>/'
            '<span style="color:#16a085;">季融資維持率(點)</span><br>'
            '<span style="color:#8e44ad;">長期估算融券維持率(實)</span>/'
            '<span style="color:#c0392b;">季融券維持率(點)</span>/'
            '<span style="color:#e67e22;">券資比</span>'
        )
        chip_pane_labels = [
            ('y domain', '外資'),
            ('y2 domain', '投信'),
            ('y3 domain', '自營'),
            ('y4 domain', stock_row4_colored_title),
            ('y6 domain', m1_pane_label),
            ('y8 domain', f'≥{major2_thresh}'),
        ]

    for y_ref_str, lbl_c in chip_pane_labels:
        fig_chip.add_annotation(
            x=0.994, y=0.98, xref='paper', yref=y_ref_str,
            xanchor='right', yanchor='top',
            align='right',
            text=f'<b>{lbl_c}</b>',
            font=dict(size=12, color='#1e293b'),
            bgcolor='rgba(255,255,255,0.82)',
            borderpad=2,
            showarrow=False
        )

    return fig_chip
## EOF chrt_chip.py
