"""
台股技術與籌碼分析系統 - 前端樣式與元件模組 (frontend.py)
負責頂部看板 HTML 渲染、版本標籤與自訂元件佈局。
完全相容 app.py 的呼叫規格與回傳格式。
"""

MODULE_NAME = "frontend"
MODULE_VERSION = "202610301830"

import streamlit as st


def get_legend_html(version_tag: str = MODULE_VERSION) -> str:
    """產生頂部看板與版本標籤的 HTML"""
    return f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <h3 style="margin: 0; color: #2c3e50;">台股技術與籌碼分析系統</h3>
        <span style="background-color: #e8f8f5; color: #16a085; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-family: monospace;">
            v{version_tag}
        </span>
    </div>
    """


def get_component_html(
    fig_top,
    fig_btm,
    df,
    raw_ticker: str,
    major1_thresh: int,
    major2_thresh: int,
    initial_end_idx: int,
    initial_disp_days: int,
    is_mobile: bool = False
) -> str:
    """組裝雙圖表與前端互動介面的完整 HTML 內容，確保主圖與所有副圖完整顯示"""
    top_html = fig_top.to_html(include_plotlyjs='cdn', full_html=False)
    btm_html = fig_btm.to_html(include_plotlyjs=False, full_html=False)
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background-color: #ffffff;
            }}
            .chart-container {{
                width: 100%;
                margin-bottom: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="chart-container">
            {top_html}
        </div>
        <div class="chart-container">
            {btm_html}
        </div>
    </body>
    </html>
    """
    return html_content
