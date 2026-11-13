"""
frontend.py - 前端 HTML/CSS 渲染與手勢/游標跨圖同步模組 (三頁籤延遲首次繪圖防塌陷、ResizeObserver自動撐高與分點統計柱狀圖版)
版本: 202611132100
"""

import json
import uuid
import pandas as pd

MODULE_NAME = "frontend"
MODULE_VERSION = "202611132100"


def get_legend_html(version_tag: str = "202611132100") -> str:
    return f"""
    <div style="font-size: 14px; margin-bottom: 4px; padding: 2px 8px; display: inline-flex; align-items: center; background: #f8fafc; border-radius: 4px; border: 1px solid #e2e8f0;">
        <span style="background:#2c3e50; color:#ffffff; padding: 2px 8px; border-radius: 4px; font-weight:bold; font-size:12px;">台股技術與籌碼分析 v{version_tag}</span>
    </div>
    """


js_template = """
<style>
.plot-main-container {
    position: relative;
    width: 100%;
    box-sizing: border-box;
    padding-bottom: 10px !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.touch-plot-box {
    position: relative;
    touch-action: pan-y !important;
    user-select: none !important;
    -webkit-user-select: none !important;
    width: 100% !important;
    overflow: hidden;
}
.pane-info-bar {
    font-size: 13px;
    color: #2c3e50;
    background: #f8fafc;
    padding: 4px 6px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
    white-space: normal;
    line-height: 1.38;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    overflow-x: auto;
}
.val-up { color: #eb4d4b; font-weight: bold; }
.val-dn { color: #2ecc71; font-weight: bold; }
.tag-lbl { margin-right: 4px; }

/* 三頁籤切換導航列 */
.sub-tab-bar {
    display: flex !important;
    flex-direction: row !important;
    align-items: center !important;
    justify-content: space-between !important;
    width: 100% !important;
    min-height: 38px !important;
    margin: 6px 0 6px 0 !important;
    background: #e2e8f0 !important;
    border-radius: 6px !important;
    padding: 4px !important;
    gap: 6px !important;
    box-sizing: border-box !important;
    border: 1px solid #94a3b8 !important;
    position: relative !important;
    z-index: 100 !important;
    pointer-events: auto !important;
}
.sub-tab-btn {
    flex: 1 1 0 !important;
    height: 30px !important;
    line-height: 22px !important;
    text-align: center !important;
    padding: 4px 6px !important;
    font-size: 13.5px !important;
    font-weight: 700 !important;
    color: #334155 !important;
    background: #f8fafc !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 4px !important;
    cursor: pointer !important;
    touch-action: manipulation !important;
    pointer-events: auto !important;
    transition: all 0.12s ease;
}
.sub-tab-btn.active {
    background: #1e293b !important;
    color: #ffffff !important;
    border-color: #1e293b !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2) !important;
}

/* 【修訂說明 2026-11-13】強制面板互斥顯示，避免切換頁籤時原副圖殘留重疊 */
.tab-panel {
    display: none !important;
    width: 100% !important;
    box-sizing: border-box !important;
}
.tab-panel.active {
    display: block !important;
}

/* 分點統計表格與柱狀圖樣式 */
.broker-section-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 6px;
    margin-bottom: 8px;
}
.broker-sec-title {
    font-size: 13px;
    font-weight: bold;
    color: #1e293b;
    background: #f1f5f9;
    padding: 4px 8px;
    border-radius: 4px;
    margin-bottom: 6px;
    border-left: 3px solid #2c3e50;
}
.broker-grid-2col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
}
@media (max-width: 720px) {
    .broker-grid-2col {
        grid-template-columns: 1fr;
    }
    .pane-info-bar {
        font-size: 11.5px;
        line-height: 1.32;
        padding: 3px 5px;
    }
}
.broker-tbl-wrap {
    overflow-x: auto;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
}
.broker-tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: 11.5px;
    text-align: right;
    white-space: nowrap;
}
.broker-tbl th {
    background: #f8fafc;
    color: #334155;
    font-weight: 700;
    padding: 4px 5px;
    border-bottom: 1px solid #cbd5e1;
}
.broker-tbl td {
    padding: 3px 5px;
    border-bottom: 1px solid #f1f5f9;
    color: #1e293b;
}
.broker-tbl th:nth-child(1), .broker-tbl td:nth-child(1),
.broker-tbl th:nth-child(2), .broker-tbl td:nth-child(2) {
    text-align: left;
}
.gov-badge {
    display: inline-block;
    background: #fef3c7;
    color: #92400e;
    font-size: 10px;
    padding: 0px 3px;
    border-radius: 3px;
    margin-left: 3px;
    border: 1px solid #f59e0b;
}
.broker-bar-box {
    width: 100%;
    height: 185px;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    margin-bottom: 6px;
    background: #ffffff;
}
.broker-select-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    flex-wrap: wrap;
}
.broker-select-row select {
    padding: 4px 8px;
    font-size: 13px;
    border-radius: 4px;
    border: 1px solid #94a3b8;
    background: #ffffff;
    color: #1e293b;
    font-weight: bold;
}

.sync-crosshair-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    border-left: 1px dashed rgba(44, 62, 80, 0.85);
    pointer-events: none;
    display: none;
    z-index: 999;
}
.sync-price-line {
    position: absolute;
    left: 80px;
    right: 15px;
    height: 1px;
    border-top: 1px dashed rgba(44, 62, 80, 0.75);
    pointer-events: none;
    display: none;
    z-index: 999;
}
</style>

<div class="plot-main-container" id="__CHART_ID___container">
    <!-- 上半部共用主圖資訊條與K線成交量圖 -->
    <div id="__CHART_ID___info1" class="pane-info-bar" style="margin-bottom: 2px;">正在載入...</div>
    <div id="__CHART_ID___top" class="touch-plot-box" style="height: __TOP_H__;">
        <div id="__CHART_ID___line_top" class="sync-crosshair-line"></div>
        <div id="__CHART_ID___line_price" class="sync-price-line"></div>
    </div>

    <!-- 下半部三頁籤切換導航列 -->
    <div class="sub-tab-bar" id="__CHART_ID___tabbar" role="tablist">
        <button type="button" class="sub-tab-btn active" data-tab="tech">📊 指標</button>
        <button type="button" class="sub-tab-btn" data-tab="chip">💰 籌碼</button>
        <button type="button" class="sub-tab-btn" data-tab="broker">🏦 分點</button>
    </div>

    <!-- 頁籤 1：指標（KD、MACD、OBV、乖離率） -->
    <div id="__CHART_ID___panel_tech" class="tab-panel active">
        <div id="__CHART_ID___info_tech" class="pane-info-bar" style="margin-bottom: 3px;"></div>
        <div id="__CHART_ID___tech" class="touch-plot-box" style="height: __TECH_H__;">
            <div id="__CHART_ID___line_tech" class="sync-crosshair-line"></div>
        </div>
    </div>

    <!-- 頁籤 2：籌碼（三大法人、資券、大戶） -->
    <div id="__CHART_ID___panel_chip" class="tab-panel">
        <div id="__CHART_ID___info_ms" class="pane-info-bar" style="margin-bottom: 3px;"></div>
        <div id="__CHART_ID___info_chip" class="pane-info-bar" style="margin-bottom: 3px;"></div>
        <div id="__CHART_ID___chip" class="touch-plot-box" style="height: __CHIP_H__;">
            <div id="__CHART_ID___line_chip" class="sync-crosshair-line"></div>
        </div>
    </div>

    <!-- 頁籤 3：分點（單日/10/20/60日統計表 + 10/20/60日下拉選單前5名每日柱狀圖） -->
    <div id="__CHART_ID___panel_broker" class="tab-panel">
        <div id="__CHART_ID___broker_header" class="pane-info-bar" style="margin-bottom: 4px;"></div>
        <div id="__CHART_ID___broker_tables"></div>
        <div class="broker-section-card">
            <div class="broker-sec-title">5. 區間買賣超統計各前 5 名分點 — 各日買賣超柱狀圖</div>
            <div class="broker-select-row">
                <label for="__CHART_ID___broker_win_sel" style="font-size:12.5px; font-weight:bold; color:#334155;">統計區間天數：</label>
                <select id="__CHART_ID___broker_win_sel">
                    <option value="10" selected>近 10 日（含關注交易日）</option>
                    <option value="20">近 20 日（含關注交易日）</option>
                    <option value="60">近 60 日（含關注交易日）</option>
                </select>
            </div>
            <div id="__CHART_ID___broker_bars_container"></div>
        </div>
    </div>
</div>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
(function() {
    var pTop = __PLOT_JSON_TOP__;
    var pTech = __PLOT_JSON_TECH__;
    var pChip = __PLOT_JSON_CHIP__;
    var dates = __DATES__;
    var isIndexAsset = __IS_INDEX__;
    var opens = __OPENS__, highs = __HIGHS__, lows = __LOWS__, closes = __CLOSES__, vols = __VOLS__;
    var ma5s = __MA5S__, ma20s = __MA20S__, ma60s = __MA60S__;
    var bias20s = __BIAS20S__, bias120s = __BIAS120S__, bias240s = __BIAS240S__, bias1200s = __BIAS1200S__;
    var turnovers = __TURNOVERS__;
    var ks = __KS__, ds = __DS__, difs = __DIFS__, macds = __MACDS__, oscs = __OSCS__;
    var obvs = __OBVS__, obvMas = __OBVMAS__;
    var foreigns = __FOREIGNS__, trusts = __TRUSTS__, dealers = __DEALERS__;
    var mDiffs = __MARGIN_DIFFS__, sDiffs = __SHORT_DIFFS__, rat = __RATIOS__;
    var m1_pcts = __M1_PCTS__, m2_pcts = __M2_PCTS__, m1_thresh = __M1_THRESH__, m2_thresh = __M2_THRESH__;
    var brokerPayload = __BROKER_PAYLOAD__;

    var container = document.getElementById('__CHART_ID___container');
    var elTop = document.getElementById('__CHART_ID___top');
    var elTech = document.getElementById('__CHART_ID___tech');
    var elChip = document.getElementById('__CHART_ID___chip');

    var lineTop = document.getElementById('__CHART_ID___line_top');
    var lineTech = document.getElementById('__CHART_ID___line_tech');
    var lineChip = document.getElementById('__CHART_ID___line_chip');
    var linePrice = document.getElementById('__CHART_ID___line_price');

    var info1 = document.getElementById('__CHART_ID___info1');
    var infoTech = document.getElementById('__CHART_ID___info_tech');
    var infoMs = document.getElementById('__CHART_ID___info_ms');
    var infoChip = document.getElementById('__CHART_ID___info_chip');

    var brokerHeader = document.getElementById('__CHART_ID___broker_header');
    var brokerTablesBox = document.getElementById('__CHART_ID___broker_tables');
    var brokerWinSel = document.getElementById('__CHART_ID___broker_win_sel');
    var brokerBarsBox = document.getElementById('__CHART_ID___broker_bars_container');

    var totalPoints = dates.length;
    var isUpdating = false;
    var watchdogTimer = null;
    var activeTab = 'tech';
    var currentFocusIdx = __INITIAL_END_IDX__;
    var chipPlotReady = false;
    var chipPlotInitInProgress = false;

    var targetDays = Number(__INITIAL_DISP_DAYS__) || 20;
    var initEnd = __INITIAL_END_IDX__;
    var initStart = Math.max(0, initEnd - targetDays + 1);
    var currentR0 = initStart - 0.5;
    var currentR1 = initEnd + 0.5;
    var cfg = { responsive: true, displayModeBar: false, scrollZoom: false };

    function postFrameHeightNow() {
        if (!container) return;
        var h = Math.ceil(container.getBoundingClientRect().height || container.scrollHeight) + 14;
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                isStreamlitMessage: true,
                type: "streamlit:setFrameHeight",
                height: h
            }, "*");
        }
    }

    function notifyIframeHeight() {
        postFrameHeightNow();
        setTimeout(postFrameHeightNow, 60);
        setTimeout(postFrameHeightNow, 250);
        setTimeout(postFrameHeightNow, 600);
    }

    if (typeof ResizeObserver !== 'undefined' && container) {
        var ro = new ResizeObserver(function() {
            postFrameHeightNow();
        });
        ro.observe(container);
    }

    function calcVisibleBounds(r0, r1) {
        var sIdx = Math.max(0, Math.floor(r0));
        var eIdx = Math.min(totalPoints - 1, Math.ceil(r1));
        var pMin = Infinity, pMax = -Infinity;
        var vMax = 0;
        for (var i = sIdx; i <= eIdx; i++) {
            var h = Number(highs[i]);
            var l = Number(lows[i]);
            if (!isNaN(h) && h > 0) pMax = Math.max(pMax, h);
            if (!isNaN(l) && l > 0) pMin = Math.min(pMin, l);
            var m5 = Number(ma5s[i]);
            if (!isNaN(m5) && m5 > 0) { pMax = Math.max(pMax, m5); pMin = Math.min(pMin, m5); }
            var m20 = Number(ma20s[i]);
            if (!isNaN(m20) && m20 > 0) { pMax = Math.max(pMax, m20); pMin = Math.min(pMin, m20); }
            var m60 = Number(ma60s[i]);
            if (!isNaN(m60) && m60 > 0) { pMax = Math.max(pMax, m60); pMin = Math.min(pMin, m60); }
            var v = Number(vols[i]);
            if (!isNaN(v) && v > 0) { vMax = Math.max(vMax, v); }
        }
        if (pMin === Infinity || pMax === -Infinity) { pMin = 0; pMax = 100; }
        var pPad = (pMax > pMin) ? (pMax - pMin) * 0.10 : 2.0;
        return {
            priceRange: [pMin - pPad, pMax + pPad],
            volRange: [0, (vMax > 0 ? vMax * 1.25 : 1000)]
        };
    }

    var initBounds = calcVisibleBounds(currentR0, currentR1);
    pTop.layout.xaxis.range = [currentR0, currentR1];
    if (pTop.layout.xaxis2) pTop.layout.xaxis2.range = [currentR0, currentR1];
    pTop.layout.yaxis.range = initBounds.priceRange;
    if (pTop.layout.yaxis2) pTop.layout.yaxis2.range = initBounds.volRange;

    for (var r = 1; r <= 4; r++) {
        var kt = (r === 1) ? 'xaxis' : 'xaxis' + r;
        if (pTech.layout && pTech.layout[kt]) pTech.layout[kt].range = [currentR0, currentR1];
    }
    for (var c = 1; c <= 6; c++) {
        var kc = (c === 1) ? 'xaxis' : 'xaxis' + c;
        if (pChip.layout && pChip.layout[kc]) pChip.layout[kc].range = [currentR0, currentR1];
    }

    function fmtNum(val, dec) {
        if (val === null || val === undefined || isNaN(val)) return '-';
        return Number(val).toFixed(dec !== undefined ? dec : 2);
    }

    function fmtBias(val) {
        if (val === null || val === undefined || isNaN(val)) return '-';
        var num = Number(val);
        var s = (num > 0 ? '+' : '') + num.toFixed(2) + '%';
        if (num > 0) return '<span class="val-up">' + s + '</span>';
        if (num < 0) return '<span class="val-dn">' + s + '</span>';
        return s;
    }

    function fmtDiff(val, dec) {
        if (val === null || val === undefined || isNaN(val)) return '-';
        var num = Number(val);
        var s = num.toFixed(dec !== undefined ? dec : 0);
        if (num > 0) return '<span class="val-up">+' + s + '</span>';
        if (num < 0) return '<span class="val-dn">' + s + '</span>';
        return s;
    }

    function buildBrokerRankTableHtml(title, buyList, sellList) {
        function makeSideTable(sideLabel, rows, isBuy) {
            var colorHdr = isBuy ? '#eb4d4b' : '#16a085';
            var html = '<div><div style="font-size:12px; font-weight:bold; color:' + colorHdr + '; margin-bottom:3px;">' + sideLabel + '</div>';
            if (!rows || rows.length === 0) {
                html += '<div style="font-size:11.5px; color:#64748b; padding:6px; border:1px solid #e2e8f0; border-radius:4px;">無資料</div></div>';
                return html;
            }
            html += '<div class="broker-tbl-wrap"><table class="broker-tbl"><thead><tr>' +
                    '<th>#</th><th>分點名稱</th><th>買進</th><th>賣出</th><th>買賣超</th><th>佔比</th>' +
                    '</tr></thead><tbody>';
            for (var i = 0; i < Math.min(10, rows.length); i++) {
                var r = rows[i];
                var badge = (r.sys === '八大官股') ? '<span class="gov-badge">官股</span>' : '';
                var netVal = Number(r.net || 0);
                var netCls = netVal > 0 ? 'val-up' : (netVal < 0 ? 'val-dn' : '');
                var netStr = (netVal > 0 ? '+' : '') + netVal.toLocaleString();
                html += '<tr>' +
                        '<td>' + (i + 1) + '</td>' +
                        '<td>' + (r.name || '') + badge + '</td>' +
                        '<td>' + Number(r.buy || 0).toLocaleString() + '</td>' +
                        '<td>' + Number(r.sell || 0).toLocaleString() + '</td>' +
                        '<td class="' + netCls + '">' + netStr + '</td>' +
                        '<td>' + (r.ratio || '-') + '</td>' +
                        '</tr>';
            }
            html += '</tbody></table></div></div>';
            return html;
        }
        return '<div class="broker-section-card">' +
               '<div class="broker-sec-title">' + title + '</div>' +
               '<div class="broker-grid-2col">' +
               makeSideTable('🔴 買超前 10 名 (張)', buyList, true) +
               makeSideTable('🟢 賣超前 10 名 (張)', sellList, false) +
               '</div></div>';
    }

    function renderBrokerTab(idx) {
        var d = dates[idx];
        if (isIndexAsset) {
            brokerHeader.innerHTML = '<b>' + d + '</b> ｜ 指數標的不適用券商分點統計';
            brokerTablesBox.innerHTML = '';
            brokerBarsBox.innerHTML = '<div style="font-size:12px; color:#64748b; padding:6px;">指數標的無個股券商分點明細。</div>';
            if (activeTab === 'broker') notifyIframeHeight();
            return;
        }

        var dayData = (brokerPayload && brokerPayload.by_date && brokerPayload.by_date[d]) ? brokerPayload.by_date[d] : null;
        if (!dayData) {
            var availDates = (brokerPayload && brokerPayload.by_date) ? Object.keys(brokerPayload.by_date).sort() : [];
            var fallbackDate = availDates.length > 0 ? availDates[availDates.length - 1] : null;
            if (fallbackDate) {
                dayData = brokerPayload.by_date[fallbackDate];
                brokerHeader.innerHTML = '<b>關注交易日：' + d + '</b>（目前顯示已快取基準日 <b>' + fallbackDate + '</b> 之分點統計；若需指定歷史日請於側邊欄設定基準日）';
            } else {
                brokerHeader.innerHTML = '<b>關注交易日：' + d + '</b> ｜ 尚無分點明細資料（請確認網路連線或非盤中時段）';
                brokerTablesBox.innerHTML = '';
                brokerBarsBox.innerHTML = '';
                if (activeTab === 'broker') notifyIframeHeight();
                return;
            }
        } else {
            brokerHeader.innerHTML = '<b>關注交易日：' + d + '</b> ｜ 券商分點買賣超統計與前五大分點逐日明細（單位：張）';
        }

        var r1 = dayData.w1 || { buy: [], sell: [], range_label: d };
        var r10 = dayData.w10 || { buy: [], sell: [], range_label: '' };
        var r20 = dayData.w20 || { buy: [], sell: [], range_label: '' };
        var r60 = dayData.w60 || { buy: [], sell: [], range_label: '' };

        brokerTablesBox.innerHTML =
            buildBrokerRankTableHtml('1. 當日分點統計買賣超各前十名（' + (r1.range_label || d) + '）', r1.buy, r1.sell) +
            buildBrokerRankTableHtml('2. 前 10 日至關注交易日分點統計買賣超各前十名（' + (r10.range_label || '') + '）', r10.buy, r10.sell) +
            buildBrokerRankTableHtml('3. 前 20 日至關注交易日分點統計買賣超各前十名（' + (r20.range_label || '') + '）', r20.buy, r20.sell) +
            buildBrokerRankTableHtml('4. 前 60 日至關注交易日分點統計買賣超各前十名（' + (r60.range_label || '') + '）', r60.buy, r60.sell);

        var winKey = 'w' + (brokerWinSel ? brokerWinSel.value : '10');
        var winObj = dayData[winKey] || r10;
        var top5Buy = (winObj.top5_buy_series || []);
        var top5Sell = (winObj.top5_sell_series || []);

        var barsHtml = '';
        if (top5Buy.length === 0 && top5Sell.length === 0) {
            barsHtml = '<div style="font-size:12px; color:#64748b; padding:6px;">此區間尚無前五大分點逐日柱狀圖資料。</div>';
            brokerBarsBox.innerHTML = barsHtml;
            if (activeTab === 'broker') notifyIframeHeight();
            return;
        }

        barsHtml += '<div style="font-size:12.5px; font-weight:bold; color:#eb4d4b; margin:4px 0;">🔴 區間累計買超前 5 名分點 — 每日買賣超柱狀圖</div>';
        for (var bi = 0; bi < top5Buy.length; bi++) {
            barsHtml += '<div id="__CHART_ID___bbar_buy_' + bi + '" class="broker-bar-box"></div>';
        }
        barsHtml += '<div style="font-size:12.5px; font-weight:bold; color:#16a085; margin:6px 0 4px 0;">🟢 區間累計賣超前 5 名分點 — 每日買賣超柱狀圖</div>';
        for (var si = 0; si < top5Sell.length; si++) {
            barsHtml += '<div id="__CHART_ID___bbar_sell_' + si + '" class="broker-bar-box"></div>';
        }
        brokerBarsBox.innerHTML = barsHtml;

        function drawMiniBar(domId, item, rankLabel) {
            var dom = document.getElementById(domId);
            if (!dom) return;
            var xDates = item.dates || [];
            var yNets = item.nets || [];
            var colors = yNets.map(function(v) { return Number(v) >= 0 ? '#eb4d4b' : '#2ecc71'; });
            var sumNet = yNets.reduce(function(acc, v) { return acc + Number(v || 0); }, 0);
            var trace = {
                x: xDates,
                y: yNets,
                type: 'bar',
                marker: { color: colors },
                hovertemplate: '%{x}<br>買賣超: %{y:,} 張<extra></extra>'
            };
            var layout = {
                title: {
                    text: rankLabel + '：' + item.name + '（主表:' + (item.total_net > 0 ? '+' : '') + Number(item.total_net || 0).toLocaleString() + '張｜逐日加總:' + (sumNet > 0 ? '+' : '') + sumNet.toLocaleString() + '張）',
                    font: { size: 11.5 }
                },
                margin: { l: 48, r: 12, t: 28, b: 36 },
                height: 180,
                template: 'plotly_white',
                xaxis: { type: 'category', tickangle: -35, tickfont: { size: 10 }, fixedrange: true },
                yaxis: { tickfont: { size: 10 }, fixedrange: true, zeroline: true, zerolinecolor: '#94a3b8' },
                showlegend: false
            };
            Plotly.newPlot(dom, [trace], layout, cfg);
        }

        for (var bi2 = 0; bi2 < top5Buy.length; bi2++) {
            drawMiniBar('__CHART_ID___bbar_buy_' + bi2, top5Buy[bi2], '買超 Top ' + (bi2 + 1));
        }
        for (var si2 = 0; si2 < top5Sell.length; si2++) {
            drawMiniBar('__CHART_ID___bbar_sell_' + si2, top5Sell[si2], '賣超 Top ' + (si2 + 1));
        }

        if (activeTab === 'broker') notifyIframeHeight();
    }

    function updateAllPanes(idx) {
        if (idx < 0 || idx >= totalPoints) return;
        currentFocusIdx = idx;
        var d = dates[idx];
        var c = closes[idx], o = opens[idx], h = highs[idx], l = lows[idx];
        var prevC = idx > 0 ? closes[idx - 1] : o;
        var diff = c - prevC;
        var pct = prevC ? (diff / prevC * 100) : 0;
        var cClass = diff > 0 ? 'val-up' : (diff < 0 ? 'val-dn' : '');

        info1.innerHTML =
            '<span class="tag-lbl"><b>' + d + '</b></span>' +
            '開:<span class="' + (o > prevC ? 'val-up' : (o < prevC ? 'val-dn' : '')) + '">' + fmtNum(o, 2) + '</span> ' +
            '高:<span class="' + (h > prevC ? 'val-up' : (h < prevC ? 'val-dn' : '')) + '">' + fmtNum(h, 2) + '</span> ' +
            '低:<span class="' + (l > prevC ? 'val-up' : (l < prevC ? 'val-dn' : '')) + '">' + fmtNum(l, 2) + '</span> ' +
            '收:<span class="' + cClass + '">' + fmtNum(c, 2) + ' (' + (diff > 0 ? '+' : '') + fmtNum(diff, 2) + ', ' + (pct > 0 ? '+' : '') + fmtNum(pct, 2) + '%)</span> ' +
            '量:' + fmtNum(vols[idx], 0) + '張 ' +
            '<span class="tag-lbl"><b>換手:' + fmtNum(turnovers[idx], 2) + '%</b></span> ' +
            'MA5:' + fmtNum(ma5s[idx], 2) + ' MA20:' + fmtNum(ma20s[idx], 2) + ' MA60:' + fmtNum(ma60s[idx], 2);

        // 頁籤 1【指標】資訊條：KD、OBV、MACD 之後呈現關注交易日之 20/120/240/1200 日乖離率
        var oscClass = oscs[idx] > 0 ? 'val-up' : (oscs[idx] < 0 ? 'val-dn' : '');
        infoTech.innerHTML =
            '<div><span class="tag-lbl"><b>' + d + '</b></span> ' +
            '<span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:' + fmtNum(ks[idx], 1) + '</span> <span style="color:#3498db;">D:' + fmtNum(ds[idx], 1) + '</span> | ' +
            '<span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:' + fmtNum(obvs[idx], 0) + '</span> <span style="color:#8e44ad;">MA20:' + fmtNum(obvMas[idx], 0) + '</span></div>' +
            '<div><span class="tag-lbl"><b>MACD(' + d + ')</b></span><span style="color:#f39c12;">DIF:' + fmtNum(difs[idx], 2) + '</span> <span style="color:#2980b9;">MACD:' + fmtNum(macds[idx], 2) + '</span> OSC:<span class="' + oscClass + '">' + fmtNum(oscs[idx], 2) + '</span> | ' +
            '<span class="tag-lbl"><b>乖離率</b></span>' +
            '<span style="color:#e67e22;">20日:</span>' + fmtBias(bias20s[idx]) + ' ' +
            '<span style="color:#2980b9;">120日:</span>' + fmtBias(bias120s[idx]) + ' ' +
            '<span style="color:#8e44ad;">240日:</span>' + fmtBias(bias240s[idx]) + ' ' +
            '<span style="color:#e74c3c;">1200日:</span>' + fmtBias(bias1200s[idx]) + '</div>';

        // 頁籤 2【籌碼】資訊條
        var mDiffThousand = (mDiffs[idx] !== null && mDiffs[idx] !== undefined) ? Number(mDiffs[idx]) / 1000.0 : null;
        var sDiffThousand = (sDiffs[idx] !== null && sDiffs[idx] !== undefined) ? Number(sDiffs[idx]) / 1000.0 : null;
        infoMs.innerHTML =
            '<span class="tag-lbl"><b>資券[千張](' + d + ')</b></span>' +
            '融資:' + fmtDiff(mDiffThousand, 3) + ' 融券:' + fmtDiff(sDiffThousand, 3) + ' ' +
            '<span class="tag-lbl"><b>券資比:' + fmtNum(rat[idx], 2) + '%</b></span>';

        infoChip.innerHTML =
            '<span class="tag-lbl"><b>法人集保(' + d + ')</b></span>' +
            '外資:' + fmtDiff(foreigns[idx], 0) + ' 投信:' + fmtDiff(trusts[idx], 0) + ' 自營:' + fmtDiff(dealers[idx], 0) + ' | ' +
            '≥' + m1_thresh + '張: ' + fmtNum(m1_pcts[idx], 2) + '% ' +
            '≥' + m2_thresh + '張: ' + fmtNum(m2_pcts[idx], 2) + '%';

        // 頁籤 3【分點】同步更新
        renderBrokerTab(idx);
    }

    function applyRangeToAllPlots(r0, r1) {
        var visibleBounds = calcVisibleBounds(r0, r1);
        var topXUpd = { 'xaxis.range': [r0, r1], 'xaxis.autorange': false };
        if (elTop.layout && elTop.layout.xaxis2) {
            topXUpd['xaxis2.range'] = [r0, r1];
            topXUpd['xaxis2.autorange'] = false;
        }
        var techUpd = {};
        for (var i = 1; i <= 4; i++) {
            var ax = (i === 1) ? 'xaxis' : 'xaxis' + i;
            if (elTech.layout && elTech.layout[ax]) {
                techUpd[ax + '.range'] = [r0, r1];
                techUpd[ax + '.autorange'] = false;
            }
        }
        var tasks = [
            Plotly.relayout(elTop, topXUpd),
            Plotly.relayout(elTech, techUpd)
        ];
        if (chipPlotReady && elChip && elChip.layout) {
            var chipUpd = {};
            for (var j = 1; j <= 6; j++) {
                var axc = (j === 1) ? 'xaxis' : 'xaxis' + j;
                if (elChip.layout[axc]) {
                    chipUpd[axc + '.range'] = [r0, r1];
                    chipUpd[axc + '.autorange'] = false;
                }
            }
            tasks.push(Plotly.relayout(elChip, chipUpd));
        }
        Promise.all(tasks).then(function() {
            return requestAnimationFrame(function() {
                Plotly.relayout(elTop, {
                    'yaxis.range': visibleBounds.priceRange,
                    'yaxis.autorange': false,
                    'yaxis2.range': visibleBounds.volRange,
                    'yaxis2.autorange': false
                });
            });
        }).finally(function() {
            setTimeout(function() { isUpdating = false; }, 20);
        });
    }

    function bindSyncXAxis(srcEl, maxAxes) {
        srcEl.on('plotly_relayout', function(ed) {
            if (isUpdating) return;
            var r0 = null, r1 = null;
            for (var k = 1; k <= maxAxes; k++) {
                var prefix = (k === 1) ? 'xaxis' : 'xaxis' + k;
                if (ed[prefix + '.range[0]'] !== undefined) r0 = ed[prefix + '.range[0]'];
                else if (ed[prefix + '.range']) r0 = ed[prefix + '.range'][0];
                if (ed[prefix + '.range[1]'] !== undefined) r1 = ed[prefix + '.range[1]'];
                else if (ed[prefix + '.range']) r1 = ed[prefix + '.range'][1];
            }
            if (r0 === null || r1 === null) return;
            if (Math.abs(r0 - currentR0) < 0.001 && Math.abs(r1 - currentR1) < 0.001) return;

            isUpdating = true;
            if (watchdogTimer) clearTimeout(watchdogTimer);
            watchdogTimer = setTimeout(function() { isUpdating = false; }, 140);

            var span = r1 - r0;
            var maxBound = (totalPoints - 1) + 0.5;
            if (r1 > maxBound) {
                r1 = maxBound;
                r0 = r1 - span;
            }
            currentR0 = r0;
            currentR1 = r1;
            setTimeout(function() { applyRangeToAllPlots(r0, r1); }, 0);
        });
    }

    function ensureChipPlotInitialized() {
        if (chipPlotReady) {
            Plotly.Plots.resize(elChip);
            var chipUpd = {};
            for (var j = 1; j <= 6; j++) {
                var axc = (j === 1) ? 'xaxis' : 'xaxis' + j;
                chipUpd[axc + '.range'] = [currentR0, currentR1];
            }
            Plotly.relayout(elChip, chipUpd);
            notifyIframeHeight();
            return;
        }
        if (chipPlotInitInProgress) return;
        chipPlotInitInProgress = true;
        for (var c = 1; c <= 6; c++) {
            var kc = (c === 1) ? 'xaxis' : 'xaxis' + c;
            if (pChip.layout && pChip.layout[kc]) pChip.layout[kc].range = [currentR0, currentR1];
        }
        Plotly.newPlot(elChip, pChip.data, pChip.layout, cfg).then(function() {
            chipPlotReady = true;
            chipPlotInitInProgress = false;
            bindSyncXAxis(elChip, 6);
            Plotly.Plots.resize(elChip);
            notifyIframeHeight();
        });
    }

    function switchTab(tabName) {
        activeTab = tabName;
        var btns = document.querySelectorAll('#__CHART_ID___tabbar .sub-tab-btn');
        btns.forEach(function(b) {
            if (b.getAttribute('data-tab') === tabName) b.classList.add('active');
            else b.classList.remove('active');
        });
        var panels = ['tech', 'chip', 'broker'];
        panels.forEach(function(p) {
            var panelEl = document.getElementById('__CHART_ID___panel_' + p);
            if (panelEl) {
                if (p === tabName) panelEl.classList.add('active');
                else panelEl.classList.remove('active');
            }
        });

        if (tabName === 'tech' && elTech) {
            Plotly.Plots.resize(elTech);
            var techUpd = {};
            for (var i = 1; i <= 4; i++) {
                var ax = (i === 1) ? 'xaxis' : 'xaxis' + i;
                techUpd[ax + '.range'] = [currentR0, currentR1];
            }
            Plotly.relayout(elTech, techUpd);
            notifyIframeHeight();
        } else if (tabName === 'chip' && elChip) {
            requestAnimationFrame(function() {
                ensureChipPlotInitialized();
            });
        } else if (tabName === 'broker') {
            renderBrokerTab(currentFocusIdx);
            notifyIframeHeight();
        }
    }

    document.querySelectorAll('#__CHART_ID___tabbar .sub-tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            switchTab(this.getAttribute('data-tab'));
        });
    });

    if (brokerWinSel) {
        brokerWinSel.addEventListener('change', function(e) {
            e.stopPropagation();
            renderBrokerTab(currentFocusIdx);
        });
    }

    // 初次只渲染目前可見的 elTop 與 elTech，隱藏分頁 elChip 於首次點擊「籌碼」時再建立，避免寬高塌陷
    Plotly.newPlot(elTop, pTop.data, pTop.layout, cfg).then(function() {
        return Plotly.newPlot(elTech, pTech.data, pTech.layout, cfg);
    }).then(function() {
        updateAllPanes(initEnd);
        notifyIframeHeight();

        bindSyncXAxis(elTop, 2);
        bindSyncXAxis(elTech, 4);

        function processPointer(clientX) {
            var rect = elTop.getBoundingClientRect();
            var relX = clientX - rect.left;
            var xaxis = elTop._fullLayout ? elTop._fullLayout.xaxis : null;
            var yaxis = elTop._fullLayout ? elTop._fullLayout.yaxis : null;
            if (!xaxis || typeof xaxis.p2c !== 'function') return;
            var plotLeft = (xaxis._offset !== undefined) ? xaxis._offset : 80;
            var plotLength = (xaxis._length !== undefined) ? xaxis._length : (rect.width - plotLeft - 15);
            var plotRight = plotLeft + plotLength;
            if (relX < plotLeft || relX > plotRight) return;

            var coord = xaxis.p2c(relX - plotLeft);
            var idx = Math.round(coord);
            if (idx >= 0 && idx < totalPoints) {
                updateAllPanes(idx);
                var snapX = xaxis.c2p(idx) + plotLeft;
                lineTop.style.left = snapX + 'px';
                lineTech.style.left = snapX + 'px';
                lineChip.style.left = snapX + 'px';
                lineTop.style.display = 'block';
                lineTech.style.display = (activeTab === 'tech') ? 'block' : 'none';
                lineChip.style.display = (activeTab === 'chip') ? 'block' : 'none';
                if (yaxis && typeof yaxis.c2p === 'function' && closes[idx] !== null && closes[idx] !== undefined) {
                    var snapY = yaxis.c2p(closes[idx]) + (yaxis._offset || 0);
                    linePrice.style.top = snapY + 'px';
                    linePrice.style.display = 'block';
                }
            }
        }

        function onPointerMove(e) {
            var clientX = e.clientX;
            if (e.touches && e.touches.length > 0) clientX = e.touches[0].clientX;
            if (clientX !== undefined) processPointer(clientX);
        }

        function onPointerLeave() {
            lineTop.style.display = 'none';
            lineTech.style.display = 'none';
            lineChip.style.display = 'none';
            linePrice.style.display = 'none';
        }

        container.addEventListener('mousemove', onPointerMove);
        container.addEventListener('touchmove', onPointerMove, { passive: true });
        container.addEventListener('touchstart', onPointerMove, { passive: true });
        container.addEventListener('mouseleave', onPointerLeave);
    });
})();
</script>
"""


def _series_to_json_nullable(df: pd.DataFrame, col: str, n_pts: int) -> str:
    """保留 NaN 為 JSON null，避免缺值被硬轉成 0.00% 造成乖離率或籌碼失真"""
    if col not in df.columns:
        return json.dumps([None] * n_pts)
    vals = [None if pd.isna(v) else float(v) for v in df[col].tolist()]
    return json.dumps(vals)


def render_interactive_chart_html(
    fig_top,
    fig_btm,
    df,
    m1_thresh=1000,
    m2_thresh=400,
    top_height=270,
    tech_height=540,
    chip_height=760,
    initial_disp_days=20,
    initial_end_idx=None,
    version_tag="202611132100",
    is_index=False,
    chart_id=None,
    broker_payload=None
) -> str:
    if chart_id is None:
        chart_id = "chart_" + uuid.uuid4().hex[:8]
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx

    fig_tech = getattr(fig_btm, "_fig_tech", fig_btm)
    fig_chip = getattr(fig_btm, "_fig_chip", fig_btm)

    p_top_json = fig_top.to_json()
    p_tech_json = fig_tech.to_json()
    p_chip_json = fig_chip.to_json()

    if 'Date' in df.columns:
        date_series = df['Date']
    else:
        date_series = df.index
    dates_list = date_series.strftime('%Y-%m-%d').tolist() if hasattr(date_series, 'strftime') else [str(x)[:10] for x in date_series]

    opens_list = df['Open'].tolist()
    highs_list = df['High'].tolist()
    lows_list = df['Low'].tolist()
    closes_list = df['Close'].tolist()
    vols_list = df['Volume_Sheets'].tolist() if 'Volume_Sheets' in df.columns else (df['Volume'] / 1000.0).tolist()

    ma5_list = df['MA5'].fillna(0).tolist() if 'MA5' in df.columns else [0] * n_pts
    ma20_list = df['MA20'].fillna(0).tolist() if 'MA20' in df.columns else [0] * n_pts
    ma60_list = df['MA60'].fillna(0).tolist() if 'MA60' in df.columns else [0] * n_pts
    turnover_list = (
        df['Turnover_Rate'].fillna(0).tolist() if 'Turnover_Rate' in df.columns
        else (df['TurnoverRate'].fillna(0).tolist() if 'TurnoverRate' in df.columns else [0] * n_pts)
    )

    k_list = df['K'].fillna(0).tolist() if 'K' in df.columns else [0] * n_pts
    d_list = df['D'].fillna(0).tolist() if 'D' in df.columns else [0] * n_pts
    dif_list = df['DIF'].fillna(0).tolist() if 'DIF' in df.columns else [0] * n_pts
    macd_list = df['MACD'].fillna(0).tolist() if 'MACD' in df.columns else [0] * n_pts
    osc_list = df['OSC'].fillna(0).tolist() if 'OSC' in df.columns else [0] * n_pts
    obv_list = df['OBV'].fillna(0).tolist() if 'OBV' in df.columns else [0] * n_pts
    obv_ma_list = df['OBV_MA20'].fillna(0).tolist() if 'OBV_MA20' in df.columns else [0] * n_pts

    foreign_list = df['Foreign_Net'].fillna(0).tolist() if 'Foreign_Net' in df.columns else [0] * n_pts
    trust_list = df['Trust_Net'].fillna(0).tolist() if 'Trust_Net' in df.columns else [0] * n_pts
    dealer_list = df['Dealer_Net'].fillna(0).tolist() if 'Dealer_Net' in df.columns else [0] * n_pts
    m_diff_list = df['Margin_Diff'].fillna(0).tolist() if 'Margin_Diff' in df.columns else [0] * n_pts
    s_diff_list = df['Short_Diff'].fillna(0).tolist() if 'Short_Diff' in df.columns else [0] * n_pts
    ratio_list = df['Short_Margin_Ratio'].fillna(0).tolist() if 'Short_Margin_Ratio' in df.columns else [0] * n_pts
    m1_pct_list = df['Major1_Pct'].fillna(0).tolist() if 'Major1_Pct' in df.columns else [0] * n_pts
    m2_pct_list = df['Major2_Pct'].fillna(0).tolist() if 'Major2_Pct' in df.columns else [0] * n_pts

    safe_broker_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}

    html = js_template
    html = html.replace("__CHART_ID__", chart_id)
    html = html.replace("__TOP_H__", f"{top_height}px")
    html = html.replace("__TECH_H__", f"{tech_height}px")
    html = html.replace("__CHIP_H__", f"{chip_height}px")
    html = html.replace("__PLOT_JSON_TOP__", p_top_json)
    html = html.replace("__PLOT_JSON_TECH__", p_tech_json)
    html = html.replace("__PLOT_JSON_CHIP__", p_chip_json)
    html = html.replace("__DATES__", json.dumps(dates_list))
    html = html.replace("__IS_INDEX__", "true" if is_index else "false")
    html = html.replace("__OPENS__", json.dumps(opens_list))
    html = html.replace("__HIGHS__", json.dumps(highs_list))
    html = html.replace("__LOWS__", json.dumps(lows_list))
    html = html.replace("__CLOSES__", json.dumps(closes_list))
    html = html.replace("__VOLS__", json.dumps(vols_list))
    html = html.replace("__MA5S__", json.dumps(ma5_list))
    html = html.replace("__MA20S__", json.dumps(ma20_list))
    html = html.replace("__MA60S__", json.dumps(ma60_list))
    html = html.replace("__BIAS20S__", _series_to_json_nullable(df, 'BIAS_20', n_pts))
    html = html.replace("__BIAS120S__", _series_to_json_nullable(df, 'BIAS_120', n_pts))
    html = html.replace("__BIAS240S__", _series_to_json_nullable(df, 'BIAS_240', n_pts))
    html = html.replace("__BIAS1200S__", _series_to_json_nullable(df, 'BIAS_1200', n_pts))
    html = html.replace("__TURNOVERS__", json.dumps(turnover_list))
    html = html.replace("__KS__", json.dumps(k_list))
    html = html.replace("__DS__", json.dumps(d_list))
    html = html.replace("__DIFS__", json.dumps(dif_list))
    html = html.replace("__MACDS__", json.dumps(macd_list))
    html = html.replace("__OSCS__", json.dumps(osc_list))
    html = html.replace("__OBVS__", json.dumps(obv_list))
    html = html.replace("__OBVMAS__", json.dumps(obv_ma_list))
    html = html.replace("__FOREIGNS__", json.dumps(foreign_list))
    html = html.replace("__TRUSTS__", json.dumps(trust_list))
    html = html.replace("__DEALERS__", json.dumps(dealer_list))
    html = html.replace("__MARGIN_DIFFS__", json.dumps(m_diff_list))
    html = html.replace("__SHORT_DIFFS__", json.dumps(s_diff_list))
    html = html.replace("__RATIOS__", json.dumps(ratio_list))
    html = html.replace("__M1_PCTS__", json.dumps(m1_pct_list))
    html = html.replace("__M2_PCTS__", json.dumps(m2_pct_list))
    html = html.replace("__M1_THRESH__", str(m1_thresh))
    html = html.replace("__M2_THRESH__", str(m2_thresh))
    html = html.replace("__INITIAL_DISP_DAYS__", str(initial_disp_days))
    html = html.replace("__INITIAL_END_IDX__", str(end_idx))
    html = html.replace("__BROKER_PAYLOAD__", json.dumps(safe_broker_payload, ensure_ascii=False))
    return html


def get_component_html(
    fig_top,
    fig_btm,
    df,
    chart_id: str,
    is_mobile: bool = False,
    initial_disp_days: int = 20,
    initial_end_idx: int = None,
    m1_thresh: int = 1000,
    m2_thresh: int = 400,
    broker_payload: dict = None
) -> str:
    top_h = 270 if is_mobile else 310
    tech_h = 540 if is_mobile else 580
    chip_h = 760 if is_mobile else 800
    is_idx = bool(df is not None and len(df) > 0 and 'Foreign_Net' not in df.columns)
    return render_interactive_chart_html(
        fig_top=fig_top,
        fig_btm=fig_btm,
        df=df,
        m1_thresh=m1_thresh,
        m2_thresh=m2_thresh,
        top_height=top_h,
        tech_height=tech_h,
        chip_height=chip_h,
        initial_disp_days=initial_disp_days,
        initial_end_idx=initial_end_idx,
        version_tag=MODULE_VERSION,
        is_index=is_idx,
        chart_id=chart_id,
        broker_payload=broker_payload
    )
