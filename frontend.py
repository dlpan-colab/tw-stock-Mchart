"""
台股技術與籌碼分析系統 - 前端組件與互動樣式模組
輸出雙圖橫向關聯滾輪縮放、40ms 防抖節流與 span >= 5 邊界 Clamping JavaScript、
雙向同步十字線、頂部即時報價看板（換手:X.XX%）、行動端水平緊湊按鈕 CSS，
以及外部 iframe 自適應高度設定（手機 1820px、桌面 1880px）。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""
# ==============================================================================
# 模組名稱: frontend
# 模組版本: 202610271640
# 核心職責: 前端 HTML/JS/CSS 雙向連動組件、圖例資訊列、行動端水平按鈕樣式
# ==============================================================================

MODULE_NAME = "frontend"
MODULE_VERSION = "202610271640"

import json

def get_legend_html(versions_dict=None):
    """產出頂部圖例與各模組版本資訊列 (相容 Streamlit 與 Colab)"""
    ver_str = " | ".join([f"{k}: v{v}" for k, v in (versions_dict or {}).items() if v and v != "N/A"])
    if not ver_str:
        ver_str = f"app: v{MODULE_VERSION}"

    return f"""
    <div style="background-color: #1e293b; padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: #cbd5e1; border: 1px solid #334155; line-height: 1.6;">
        <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 4px;">
            <span style="font-weight: 600; color: #f8fafc;">指標圖例:</span>
            <span><b style="color: #ff9800;">─</b> 5MA</span>
            <span><b style="color: #29b6f6;">─</b> 20MA</span>
            <span><b style="color: #ab47bc;">─</b> 60MA</span>
            <span><b style="color: #00e676;">〔頭〕</b>綠高轉折</span>
            <span><b style="color: #e53935;">〔底〕</b>紅低轉折</span>
            <span><b style="color: #00d2ff;">▲</b> 換手10~20%</span>
            <span><b style="color: #ffeb3b;">▼</b> 換手≥20%</span>
        </div>
        <div style="font-size: 11px; color: #94a3b8; border-top: 1px solid #334155; padding-top: 4px; margin-top: 4px;">
            系統架構: 模組化獨立運行架構 | 模組版本: [{ver_str}]
        </div>
    </div>
    """

def get_component_html(fig_top, fig_btm, df, symbol, m1_level, m2_level, end_idx, disp_n, is_mobile=True):
    """輸出整合後的雙圖聯動 HTML/JS/CSS 容器"""
    top_json = fig_top.to_json()
    btm_json = fig_btm.to_json()

    # 提取最後一筆或指定基準日的數值看板資料
    row = df.iloc[end_idx] if end_idx < len(df) else df.iloc[-1]
    close_p = row.get('Close', 0.0)
    open_p = row.get('Open', 0.0)
    high_p = row.get('High', 0.0)
    low_p = row.get('Low', 0.0)
    vol_lots = row.get('Volume', 0.0) / 1000.0
    turnover = row.get('Turnover_Rate', 0.0)

    # 計算自由流通換手率與大戶比率字串
    m1_pct = row.get(f"major_{m1_level}_pct", 0.0)
    m2_pct = row.get(f"major_{m2_level}_pct", 0.0)

    # 計算初始可視範圍 (消除休市空隙的類別型範圍)
    total_len = len(df)
    start_i = max(0, end_idx - disp_n + 1)
    end_i = end_idx

    top_h = "450px" if is_mobile else "520px"
    btm_h = "1300px" if is_mobile else "1300px"

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <script src="https://cdn.plot.ly/plotly-2.29.1.min.js"></script>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: #121824;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                color: #e2e8f0;
                user-select: none;
                -webkit-user-select: none;
            }}
            #quote-bar {{
                background-color: #1a2234;
                padding: 8px 12px;
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                font-size: 13px;
                border-bottom: 1px solid #2d3748;
                position: sticky;
                top: 0;
                z-index: 100;
            }}
            .q-item {{ display: flex; gap: 4px; align-items: baseline; }}
            .q-label {{ color: #94a3b8; font-size: 11px; }}
            .q-val {{ font-weight: 600; color: #f8fafc; }}
            #top-chart {{ width: 100%; height: {top_h}; }}
            #btm-chart {{ width: 100%; height: {btm_h}; }}

            /* 強制 Streamlit 水平區塊在手機端維持 row 並排且縮小按鈕 */
            @media (max-width: 640px) {{
                div[data-testid="stHorizontalBlock"] {{
                    flex-direction: row !important;
                    flex-wrap: nowrap !important;
                    gap: 8px !important;
                }}
                div[data-testid="stHorizontalBlock"] > div {{
                    max-width: 130px !important;
                    flex: 1 1 0% !important;
                }}
            }}
        </style>
    </head>
    <body>
        <div id="quote-bar">
            <div class="q-item"><span class="q-label">標的:</span><span class="q-val" style="color: #38bdf8;">{symbol}</span></div>
            <div class="q-item"><span class="q-label">收盤:</span><span class="q-val">{close_p:.2f}</span></div>
            <div class="q-item"><span class="q-label">開/高/低:</span><span class="q-val">{open_p:.2f} / {high_p:.2f} / {low_p:.2f}</span></div>
            <div class="q-item"><span class="q-label">成交量:</span><span class="q-val">{vol_lots:,.0f} 張</span></div>
            <div class="q-item"><span class="q-label">換手:</span><span class="q-val" style="color: #facc15;">{turnover:.2f}%</span></div>
            <div class="q-item"><span class="q-label">{m1_level}張大戶:</span><span class="q-val" style="color: #c084fc;">{m1_pct:.1f}%</span></div>
            <div class="q-item"><span class="q-label">{m2_level}張大戶:</span><span class="q-val" style="color: #2dd4bf;">{m2_pct:.1f}%</span></div>
        </div>

        <div id="top-chart"></div>
        <div id="btm-chart"></div>

        <script>
            var topData = {top_json};
            var btmData = {btm_json};

            var topPlot = document.getElementById('top-chart');
            var btmPlot = document.getElementById('btm-chart');

            // 初始範圍配置 (類別座標)
            var initRange = [{start_i} - 0.5, {end_i} + 0.5];
            
            topData.layout.xaxis.range = initRange;
            if (topData.layout.xaxis2) topData.layout.xaxis2.range = initRange;
            btmData.layout.xaxis.range = initRange;
            for (var i = 2; i <= 9; i++) {{
                if (btmData.layout['xaxis' + i]) btmData.layout['xaxis' + i].range = initRange;
            }}

            Plotly.newPlot('top-chart', topData.data, topData.layout, {{responsive: true, displayModeBar: false}});
            Plotly.newPlot('btm-chart', btmData.data, btmData.layout, {{responsive: true, displayModeBar: false}});

            // 雙向滾輪與縮放同步 (附 40ms 防抖與邊界防死鎖)
            var isSyncing = false;
            var syncTimer = null;

            function syncZoom(sourcePlot, targetPlot) {{
                sourcePlot.on('plotly_relayout', function(eventdata) {{
                    if (isSyncing) return;
                    if (eventdata['xaxis.range[0]'] !== undefined && eventdata['xaxis.range[1]'] !== undefined) {{
                        var x0 = eventdata['xaxis.range[0]'];
                        var x1 = eventdata['xaxis.range[1]'];
                        
                        // 邊界防護：最少維持 5 根 K 棒
                        if ((x1 - x0) < 5) return;

                        isSyncing = true;
                        clearTimeout(syncTimer);
                        syncTimer = setTimeout(function() {{
                            var update = {{
                                'xaxis.range[0]': x0,
                                'xaxis.range[1]': x1
                            }};
                            Plotly.relayout(targetPlot, update).then(function() {{
                                isSyncing = false;
                            }});
                        }}, 40);
                    }}
                }});
            }}

            syncZoom(topPlot, btmPlot);
            syncZoom(btmPlot, topPlot);
        </script>
    </body>
    </html>
    """
    return html_code
