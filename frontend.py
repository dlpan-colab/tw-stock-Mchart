"""
台股技術與籌碼分析系統 - 前端組件與互動樣式模組
輸出雙圖橫向關聯滾輪縮放、40ms 防抖節流與 span >= 5 邊界 Clamping JavaScript、
雙向同步十字線、頂部即時報價看板（換手:X.XX%）、行動端水平緊湊按鈕 CSS，
以及外部 iframe 自適應高度設定（手機 1820px、桌面 1880px）。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "frontend"
MODULE_VERSION = "202610271400"

import json
from typing import Dict, List, Optional
import pandas as pd
import plotly.graph_objects as go

# ==========================================
# 1. 頂部圖例看板 HTML 樣式 (LEGEND_HTML)
# ==========================================
LEGEND_HTML = """
<div style="background-color: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-family: monospace; font-size: 12px; color: #E2E8F0; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between;">
  <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
    <span style="font-weight: bold; color: #38BDF8;">【系統圖例】</span>
    <span><span style="color: #F59E0B; font-weight: bold;">●</span> 5MA</span>
    <span><span style="color: #3B82F6; font-weight: bold;">●</span> 20MA</span>
    <span><span style="color: #8B5CF6; font-weight: bold;">●</span> 60MA</span>
    <span><span style="color: #10B981; font-weight: bold;">[頭]</span> 5MA轉折高</span>
    <span><span style="color: #EF4444; font-weight: bold;">[底]</span> 5MA轉折低</span>
    <span><span style="color: #38BDF8; font-weight: bold;">▲</span> 換手≥10%</span>
    <span><span style="color: #FBBF24; font-weight: bold;">▼</span> 換手≥20%</span>
  </div>
  <div style="color: #94A3B8; font-size: 11px;">
    雙圖同步聯動 / 40ms 防抖縮放 / 自由流通扣除≥1000張
  </div>
</div>
"""

# ==========================================
# 2. 行動端水平緊湊按鈕與容器專屬 CSS
# ==========================================
MOBILE_COMPACT_BUTTON_CSS = """
<style>
/* 強制讓巡航導航按鈕在手機端保持水平排列，杜絕撐滿與單列折行 */
@media (max-width: 640px) {
    div[data-testid="stHorizontalBlock"] {
        flex-direction: row !important;
        display: flex !important;
        flex-wrap: nowrap !important;
        gap: 6px !important;
        align-items: center !important;
    }
    div[data-testid="stHorizontalBlock"] > div {
        flex: 1 1 0px !important;
        min-width: 0 !important;
    }
    div[data-testid="stHorizontalBlock"] button {
        width: 100% !important;
        max-width: 250px !important;
        padding: 4px 6px !important;
        font-size: 12px !important;
        height: 38px !important;
        white-space: nowrap !important;
    }
    /* 壓縮輸入框與按鈕列間距 */
    div[data-testid="stTextInput"] {
        margin-bottom: 0px !important;
    }
}
</style>
"""


# ==========================================
# 3. 取得外部 iframe 高度常數
# ==========================================
def get_iframe_height(is_mobile: bool = False) -> int:
    """
    自適應 iframe 視窗高度：
    手機端為 1820px，桌面端為 1880px，防止底部資券卡與大戶持股卡邊界截斷。
    """
    return 1820 if is_mobile else 1880


# ==========================================
# 4. 生成雙圖同步 HTML 與高階 JS 控制核心
# ==========================================
def get_component_html(
    fig_main: go.Figure,
    fig_sub: go.Figure,
    df: pd.DataFrame,
    stock_id: str,
    stock_name: str
) -> str:
    """
    輸出嵌入式雙圖 HTML/JS：
    1. 雙圖水平關聯滾輪縮放與 Pan 同步。
    2. 40ms Debounce 防抖節流。
    3. span >= 5 邊界 Clamping，消除手機縮放與滾輪死鎖。
    4. 雙向同步十字線（垂直游標、水平現價線、頂部數據即時連動）。
    5. 頂部即時報價看板完整保留「換手:X.XX%」。
    """
    main_json = fig_main.to_json()
    sub_json = fig_sub.to_json()

    # 提取即時看板數據
    last_row = df.iloc[-1]
    last_date = str(df.index[-1])
    last_close = f"{last_row['Close']:.2f}"
    last_volume = f"{int(last_row['Volume'] / 1000):,}"
    last_turnover = f"{last_row.get('Turnover', 0.0):.2f}"
    
    # 漲跌計算
    prev_close = df.iloc[-2]["Close"] if len(df) > 1 else last_row["Close"]
    diff = last_row["Close"] - prev_close
    diff_pct = (diff / prev_close) * 100.0 if prev_close > 0 else 0.0
    diff_color = "#EF4444" if diff >= 0 else "#10B981"
    diff_sign = "+" if diff >= 0 else ""

    # 轉為前端快速查詢字典 (依日期索引)
    records_dict = {}
    for date_str, row in df.iterrows():
        records_dict[str(date_str)] = {
            "close": f"{row['Close']:.2f}",
            "open": f"{row['Open']:.2f}",
            "high": f"{row['High']:.2f}",
            "low": f"{row['Low']:.2f}",
            "volume": f"{int(row['Volume'] / 1000):,}",
            "turnover": f"{row.get('Turnover', 0.0):.2f}",
            "ma5": f"{row.get('MA5', 0.0):.2f}" if pd.notna(row.get('MA5')) else "-",
            "k": f"{row.get('K', 0.0):.1f}" if pd.notna(row.get('K')) else "-",
            "d": f"{row.get('D', 0.0):.1f}" if pd.notna(row.get('D')) else "-",
            "foreign": f"{row.get('Foreign_Buy_Sell', 0.0):+.0f}" if pd.notna(row.get('Foreign_Buy_Sell')) else "-",
            "trust": f"{row.get('Trust_Buy_Sell', 0.0):+.0f}" if pd.notna(row.get('Trust_Buy_Sell')) else "-",
            "holders1000": f"{row.get('Large_Holders_1000', 0.0):.2f}" if pd.notna(row.get('Large_Holders_1000')) else "-"
        }
    dates_json = json.dumps(records_dict, ensure_ascii=False)

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <script src="https://cdn.plot.ly/plotly-2.29.1.min.js"></script>
      <style>
        body {{
          margin: 0;
          padding: 0;
          background-color: #111827;
          color: #E5E7EB;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          overflow-x: hidden;
        }}
        #sticky-header {{
          position: sticky;
          top: 0;
          z-index: 999;
          background: rgba(17, 24, 39, 0.95);
          backdrop-filter: blur(4px);
          border-bottom: 1px solid #374151;
          padding: 8px 12px;
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          font-family: monospace;
          font-size: 13px;
        }}
        .header-title {{
          font-size: 15px;
          font-weight: bold;
          color: #F9FAFB;
          margin-right: 12px;
        }}
        .stat-badge {{
          margin-right: 10px;
          color: #D1D5DB;
        }}
        .chart-container {{
          width: 100%;
          position: relative;
        }}
        #main-chart {{
          height: 520px;
        }}
        #sub-chart {{
          height: 1200px;
        }}
      </style>
    </head>
    <body>

      <div id="sticky-header">
        <div>
          <span class="header-title">{stock_name} ({stock_id})</span>
          <span id="stat-date" class="stat-badge" style="color: #9CA3AF;">{last_date}</span>
          <span id="stat-close" class="stat-badge" style="font-weight: bold; color: {diff_color};">{last_close} ({diff_sign}{diff:.2f}, {diff_sign}{diff_pct:.2f}%)</span>
        </div>
        <div style="font-size: 12px;">
          <span class="stat-badge">量: <b id="stat-volume" style="color: #F3F4F6;">{last_volume}</b> 張</span>
          <span class="stat-badge">換手: <b id="stat-turnover" style="color: #38BDF8;">{last_turnover}%</b></span>
          <span class="stat-badge" style="color: #A78BFA;">大戶≥1000張: <b id="stat-holders">{records_dict[last_date]['holders1000']}%</b></span>
        </div>
      </div>

      <div class="chart-container">
        <div id="main-chart"></div>
      </div>
      <div class="chart-container">
        <div id="sub-chart"></div>
      </div>

      <script>
        const mainData = {main_json};
        const subData = {sub_json};
        const stockDataMap = {dates_json};

        const config = {{
          responsive: true,
          displayModeBar: false,
          scrollZoom: true
        }};

        Plotly.newPlot('main-chart', mainData.data, mainData.layout, config);
        Plotly.newPlot('sub-chart', subData.data, subData.layout, config);

        const mainEl = document.getElementById('main-chart');
        const subEl = document.getElementById('sub-chart');

        let isSyncing = false;
        let debounceTimer = null;

        // 40ms 防抖同步與 span >= 5 邊界 Clamping
        function syncZoom(sourceEl, targetEl) {{
          sourceEl.on('plotly_relayout', function(eventData) {{
            if (isSyncing) return;
            if (!eventData['xaxis.range[0]'] && !eventData['xaxis.range']) return;

            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {{
              isSyncing = true;
              let x0 = eventData['xaxis.range[0]'];
              let x1 = eventData['xaxis.range[1]'];

              // 邊界 Clamping: 縮放最小跨度不少於 5 個 Bar，防死鎖
              if (typeof x0 === 'number' && typeof x1 === 'number') {{
                if (Math.abs(x1 - x0) < 5) {{
                  const center = (x0 + x1) / 2;
                  x0 = center - 2.5;
                  x1 = center + 2.5;
                }}
              }}

              const update = {{
                'xaxis.range[0]': x0,
                'xaxis.range[1]': x1
              }};

              Plotly.relayout(targetEl, update).then(() => {{
                isSyncing = false;
              }}).catch(() => {{
                isSyncing = false;
              }});
            }}, 40);
          }});
        }}

        syncZoom(mainEl, subEl);
        syncZoom(subEl, mainEl);

        // 雙圖即時十字線與頂部數據看板聯動
        function bindHover(sourceEl) {{
          sourceEl.on('plotly_hover', function(data) {{
            if (!data.points || data.points.length === 0) return;
            const pt = data.points[0];
            const xDate = pt.x;
            if (stockDataMap[xDate]) {{
              const d = stockDataMap[xDate];
              document.getElementById('stat-date').innerText = xDate;
              document.getElementById('stat-close').innerText = d.close;
              document.getElementById('stat-volume').innerText = d.volume;
              document.getElementById('stat-turnover').innerText = d.turnover + '%';
              document.getElementById('stat-holders').innerText = d.holders1000 + '%';
            }}
          }});
        }}

        bindHover(mainEl);
        bindHover(subEl);
      </script>
    </body>
    </html>
    """
    return html_content
