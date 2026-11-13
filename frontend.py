"""
frontend.py - 前端 HTML/CSS 渲染模組 (共用主圖 Frame + 三頁籤各自獨立 Frame + 分點柱狀圖X軸僅首日標示月份版)
版本: 202611132215
"""

import json
import pandas as pd

MODULE_NAME = "frontend"
MODULE_VERSION = "202611132215"


def get_legend_html(version_tag: str = "202611132215") -> str:
    return f"""
    <div style="font-size: 14px; margin-bottom: 4px; padding: 2px 8px; display: inline-flex; align-items: center; background: #f8fafc; border-radius: 4px; border: 1px solid #e2e8f0;">
        <span style="background:#2c3e50; color:#ffffff; padding: 2px 8px; border-radius: 4px; font-weight:bold; font-size:12px;">台股技術與籌碼分析 v{version_tag}</span>
    </div>
    """


def _series_to_json_nullable(df: pd.DataFrame, col: str, n_pts: int) -> str:
    if col not in df.columns:
        return json.dumps([None] * n_pts)
    return json.dumps([None if pd.isna(v) else float(v) for v in df[col].tolist()])


def _extract_dates_list(df: pd.DataFrame) -> list:
    date_series = df['Date'] if 'Date' in df.columns else df.index
    return date_series.strftime('%Y-%m-%d').tolist() if hasattr(date_series, 'strftime') else [str(x)[:10] for x in date_series]


COMMON_CSS = """
<style>
html, body { margin: 0; padding: 0; background: transparent; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.frame-root { position: relative; width: 100%; box-sizing: border-box; padding-bottom: 4px; }
.touch-plot-box { position: relative; touch-action: pan-y !important; user-select: none !important; -webkit-user-select: none !important; width: 100% !important; overflow: hidden; }
.pane-info-bar { font-size: 13px; color: #2c3e50; background: #f8fafc; padding: 4px 6px; border-radius: 4px; border: 1px solid #e2e8f0; white-space: normal; line-height: 1.38; overflow-x: auto; }
@media (max-width: 720px) { .pane-info-bar { font-size: 11.5px; line-height: 1.32; padding: 3px 5px; } }
.val-up { color: #eb4d4b; font-weight: bold; }
.val-dn { color: #2ecc71; font-weight: bold; }
.tag-lbl { margin-right: 4px; }
.sync-crosshair-line { position: absolute; top: 0; bottom: 0; width: 1px; border-left: 1px dashed rgba(44, 62, 80, 0.85); pointer-events: none; display: none; z-index: 999; }
.sync-price-line { position: absolute; left: 80px; right: 15px; height: 1px; border-top: 1px dashed rgba(44, 62, 80, 0.75); pointer-events: none; display: none; z-index: 999; }
</style>
"""

SHARED_JS_HELPERS = """
function broadcastToSiblings(payload) {
    try {
        if (window.parent && window.parent.frames) {
            for (var i = 0; i < window.parent.frames.length; i++) {
                if (window.parent.frames[i] !== window) window.parent.frames[i].postMessage(payload, '*');
            }
        }
    } catch (e) {}
}
function fmtNum(val, dec) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    return Number(val).toFixed(dec !== undefined ? dec : 2);
}
function fmtBias(val) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    var num = Number(val), s = (num > 0 ? '+' : '') + num.toFixed(2) + '%';
    return num > 0 ? '<span class="val-up">' + s + '</span>' : (num < 0 ? '<span class="val-dn">' + s + '</span>' : s);
}
function fmtDiff(val, dec) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    var num = Number(val), s = num.toFixed(dec !== undefined ? dec : 0);
    return num > 0 ? '<span class="val-up">+' + s + '</span>' : (num < 0 ? '<span class="val-dn">' + s + '</span>' : s);
}
"""


def get_top_chart_html(fig
