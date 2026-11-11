"""
frontend.py - 前端 HTML/CSS 渲染與手勢/游標跨圖同步模組 (緊湊底部留白與全副圖軸同步版)
版本: 202611112030
"""

MODULE_NAME = "frontend"
MODULE_VERSION = "202611112030"

def get_legend_html(version_tag: str = "202611112030") -> str:
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
        /* 【修訂說明 2026-11-11】：縮減底部內距至 8px，防止資訊條下方產生多餘大段空白 */
        padding-bottom: 8px !important;
    }
    .touch-plot-box {
        position: relative;
        touch-action: pan-y !important;
        user-select: none !important;
        -webkit-user-select: none !important;
        width: 100% !important;
    }
    .pane-info-bar {
        font-size: 13.5px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #2c3e50;
        background: #f8fafc;
        padding: 4px 6px;
        border-radius: 4px;
        border: 1px solid #e2e8f0;
        white-space: normal;
        line-height: 1.4;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        overflow-x: auto;
    }
    .val-up { color: #eb4d4b; font-weight: bold; }
    .val-dn { color: #2ecc71; font-weight: bold; }
    .tag-lbl { margin-right: 4px; }
    .middle-inserted-bar {
        width: 100%;
        box-sizing: border-box;
        margin: 4px 0;
    }
    .bottom-chip-deck {
        width: 100%;
        box-sizing: border-box;
        margin-top: 4px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    @media (max-width: 600px) {
        .pane-info-bar {
            font-size: 12px;
            line-height: 1.35;
            padding: 3px 5px;
        }
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
    <div id="__CHART_ID___info1" class="pane-info-bar" style="margin-bottom: 2px;">正在載入...</div>
    <div id="__CHART_ID___top" class="touch-plot-box" style="height: __TOP_H__;">
        <div id="__CHART_ID___line_top" class="sync-crosshair-line"></div>
        <div id="__CHART_ID___line_price" class="sync-price-line"></div>
    </div>
    <div class="middle-inserted-bar">
        <div id="__CHART_ID___info_tech" class="pane-info-bar"></div>
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
    var isIndexAsset = __IS_INDEX__;
    var opens = __OPENS__, highs = __HIGHS__, lows = __LOWS__, closes = __CLOSES__, vols = __VOLS__;
    var ma5s = __MA5S__, ma20s = __MA20S__, ma60s = __MA60S__;
    var turnovers = __TURNOVERS__;
    var ks = __KS__, ds = __DS__, difs = __DIFS__, macds = __MACDS__, oscs = __OSCS__;
    var obvs = __OBVS__, obvMas = __OBVMAS__;
    var foreigns = __FOREIGNS__, trusts = __TRUSTS__, dealers = __DEALERS__;
    var mDiffs = __MARGIN_DIFFS__, sDiffs = __SHORT_DIFFS__, rat = __RATIOS__;
    var m1_pcts = __M1_PCTS__, m2_pcts = __M2_PCTS__, m1_thresh = __M1_THRESH__, m2_thresh = __M2_THRESH__;

    var container = document.getElementById('__CHART_ID___container');
    var elTop = document.getElementById('__CHART_ID___top');
    var elBtm = document.getElementById('__CHART_ID___btm');
    var lineTop = document.getElementById('__CHART_ID___line_top');
    var lineBtm = document.getElementById('__CHART_ID___line_btm');
    var linePrice = document.getElementById('__CHART_ID___line_price');
    var info1 = document.getElementById('__CHART_ID___info1');
    var infoTech = document.getElementById('__CHART_ID___info_tech');
    var infoMs = document.getElementById('__CHART_ID___info_ms');
    var infoChip = document.getElementById('__CHART_ID___info_chip');

    var totalPoints = dates.length;
    var isUpdating = false;
    var watchdogTimer = null;
    var targetDays = Number(__INITIAL_DISP_DAYS__) || 20;
    var initEnd = __INITIAL_END_IDX__;
    var initStart = Math.max(0, initEnd - targetDays + 1);
    var currentR0 = initStart - 0.5;
    var currentR1 = initEnd + 0.5;

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
            if (!isNaN(v) && v > 0) {
                vMax = Math.max(vMax, v);
            }
        }
        if (pMin === Infinity || pMax === -Infinity) {
            pMin = 0; pMax = 100;
        }
        var pPad = (pMax > pMin) ? (pMax - pMin) * 0.10 : 2.0;
        return {
            priceRange: [pMin - pPad, pMax + pPad],
            volRange: [0, (vMax > 0 ? vMax * 1.25 : 1000)]
        };
    }

    var initBounds = calcVisibleBounds(currentR0, currentR1);
    var currentPriceRange = initBounds.priceRange;
    var currentVolRange = initBounds.volRange;

    pTop.layout.xaxis.range = [currentR0, currentR1];
    if (pTop.layout.xaxis2) pTop.layout.xaxis2.range = [currentR0, currentR1];
    pTop.layout.yaxis.range = currentPriceRange;
    if (pTop.layout.yaxis2) pTop.layout.yaxis2.range = currentVolRange;

    for (var r = 1; r <= 9; r++) {
        var k = (r === 1) ? 'xaxis' : 'xaxis' + r;
        if (pBtm.layout && pBtm.layout[k]) {
            pBtm.layout[k].range = [currentR0, currentR1];
        }
    }

    function fmtNum(val, dec) {
        if (val === null || val === undefined || isNaN(val)) return '-';
        return Number(val).toFixed(dec !== undefined ? dec : 2);
    }

    function fmtDiff(val, dec) {
        if (val === null || val === undefined || isNaN(val)) return '-';
        var num = Number(val);
        var s = num.toFixed(dec !== undefined ? dec : 0);
        if (num > 0) return '<span class="val-up">+' + s + '</span>';
        if (num < 0) return '<span class="val-dn">' + s + '</span>';
        return s;
    }

    function updateAllPanes(idx) {
        if (idx < 0 || idx >= totalPoints) return;
        var d = dates[idx];
        var c = closes[idx], o = opens[idx], h = highs[idx], l = lows[idx];
        var prevC = idx > 0 ? closes[idx - 1] : o;
        var diff = c - prevC;
        var pct = prevC ? (diff / prevC * 100) : 0;
        var cClass = diff > 0 ? 'val-up' : (diff < 0 ? 'val-dn' : '');

        info1.innerHTML = '<span class="tag-lbl"><b>' + d + '</b></span>' +
            '開:<span class="' + (o > prevC ? 'val-up' : (o < prevC ? 'val-dn' : '')) + '">' + fmtNum(o, 2) + '</span> ' +
            '高:<span class="' + (h > prevC ? 'val-up' : (h < prevC ? 'val-dn' : '')) + '">' + fmtNum(h, 2) + '</span> ' +
            '低:<span class="' + (l > prevC ? 'val-up' : (l < prevC ? 'val-dn' : '')) + '">' + fmtNum(l, 2) + '</span> ' +
            '收:<span class="' + cClass + '">' + fmtNum(c, 2) + ' (' + (diff > 0 ? '+' : '') + fmtNum(diff, 2) + ', ' + (pct > 0 ? '+' : '') + fmtNum(pct, 2) + '%)</span> ' +
            '量:' + fmtNum(vols[idx], 0) + '張 ' +
            '<span class="tag-lbl"><b>換手:' + fmtNum(turnovers[idx], 2) + '%</b></span> ' +
            'MA5:' + fmtNum(ma5s[idx], 2) + ' MA20:' + fmtNum(ma20s[idx], 2) + ' MA60:' + fmtNum(ma60s[idx], 2);

        var oscClass = oscs[idx] > 0 ? 'val-up' : (oscs[idx] < 0 ? 'val-dn' : '');
        infoTech.innerHTML = '<div><span class="tag-lbl"><b>' + d + '</b></span> ' +
            '<span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:' + fmtNum(ks[idx], 1) + '</span> <span style="color:#3498db;">D:' + fmtNum(ds[idx], 1) + '</span> | ' +
            '<span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:' + fmtNum(obvs[idx], 0) + '</span> <span style="color:#8e44ad;">MA20:' + fmtNum(obvMas[idx], 0) + '</span></div>' +
            '<div><span class="tag-lbl"><b>MACD(' + d + ')</b></span><span style="color:#f39c12;">DIF:' + fmtNum(difs[idx], 2) + '</span> <span style="color:#2980b9;">MACD:' + fmtNum(macds[idx], 2) + '</span> OSC:<span class="' + oscClass + '">' + fmtNum(oscs[idx], 2) + '</span></div>';

        var mDiffThousand = (mDiffs[idx] !== null && mDiffs[idx] !== undefined) ? Number(mDiffs[idx]) / 1000.0 : null;
        var sDiffThousand = (sDiffs[idx] !== null && sDiffs[idx] !== undefined) ? Number(sDiffs[idx]) / 1000.0 : null;
        infoMs.innerHTML = '<span class="tag-lbl"><b>資券[千張](' + d + ')</b></span>' +
            '融資:' + fmtDiff(mDiffThousand, 3) + ' 融券:' + fmtDiff(sDiffThousand, 3) + ' ' +
            '<span class="tag-lbl"><b>券資比:' + fmtNum(rat[idx], 2) + '%</b></span>';

        infoChip.innerHTML = '<span class="tag-lbl"><b>法人集保(' + d + ')</b></span>' +
            '外資:' + fmtDiff(foreigns[idx], 0) + ' 投信:' + fmtDiff(trusts[idx], 0) + ' 自營:' + fmtDiff(dealers[idx], 0) + ' | ' +
            '≥' + m1_thresh + '張: ' + fmtNum(m1_pcts[idx], 2) + '% ' +
            '≥' + m2_thresh + '張: ' + fmtNum(m2_pcts[idx], 2) + '%';
    }

    var cfg = { responsive: true, displayModeBar: false, scrollZoom: false };

    Plotly.newPlot(elTop, pTop.data, pTop.layout, cfg).then(function() {
        return Plotly.newPlot(elBtm, pBtm.data, pBtm.layout, cfg);
    }).then(function() {
        updateAllPanes(initEnd);

        function syncXAxis(srcEl, destEl) {
            srcEl.on('plotly_relayout', function(ed) {
                if (isUpdating) return;

                var r0 = ed['xaxis.range[0]'] !== undefined ? ed['xaxis.range[0]'] : (ed['xaxis.range'] ? ed['xaxis.range'][0] : (ed['xaxis2.range[0]'] !== undefined ? ed['xaxis2.range[0]'] : (ed['xaxis2.range'] ? ed['xaxis2.range'][0] : null)));
                var r1 = ed['xaxis.range[1]'] !== undefined ? ed['xaxis.range[1]'] : (ed['xaxis.range'] ? ed['xaxis.range'][1] : (ed['xaxis2.range[1]'] !== undefined ? ed['xaxis2.range[1]'] : (ed['xaxis2.range'] ? ed['xaxis2.range'][1] : null)));
                var auto = ed['xaxis.autorange'] || ed['xaxis2.autorange'];

                if (r0 === null && r1 === null && !auto) {
                    return;
                }

                if (r0 !== null && r1 !== null) {
                    if (Math.abs(r0 - currentR0) < 0.001 && Math.abs(r1 - currentR1) < 0.001) {
                        return;
                    }
                    isUpdating = true;
                    if (watchdogTimer) clearTimeout(watchdogTimer);
                    watchdogTimer = setTimeout(function() { isUpdating = false; }, 120);

                    var span = r1 - r0;
                    var maxBound = (totalPoints - 1) + 0.5;
                    if (r1 > maxBound) {
                        r1 = maxBound;
                        r0 = r1 - span;
                    }

                    currentR0 = r0;
                    currentR1 = r1;

                    var visibleBounds = calcVisibleBounds(r0, r1);
                    currentPriceRange = visibleBounds.priceRange;
                    currentVolRange = visibleBounds.volRange;

                    var topXUpd = { 'xaxis.range': [r0, r1], 'xaxis.autorange': false };
                    if (elTop.layout && elTop.layout.xaxis2) {
                        topXUpd['xaxis2.range'] = [r0, r1];
                        topXUpd['xaxis2.autorange'] = false;
                    }

                    var btmUpd = {};
                    if (elBtm && elBtm.layout) {
                        for (var i = 1; i <= 3; i++) {
                            var ax = (i === 1) ? 'xaxis' : 'xaxis' + i;
                            if (elBtm.layout[ax]) {
                                btmUpd[ax + '.range'] = [r0, r1];
                                btmUpd[ax + '.autorange'] = false;
                            }
                        }
                        if (!isIndexAsset) {
                            for (var i = 4; i <= 9; i++) {
                                var ax = 'xaxis' + i;
                                if (elBtm.layout[ax]) {
                                btmUpd[ax + '.range'] = [r0, r1];
                                btmUpd[ax + '.autorange'] = false;
                                }
                            }
                        }
                    }

                    setTimeout(function() {
                        var p1 = Plotly.relayout(elTop, topXUpd);
                        var p2 = (Object.keys(btmUpd).length > 0) ? Plotly.relayout(elBtm, btmUpd) : Promise.resolve();
                        Promise.all([p1, p2]).then(function() {
                            return requestAnimationFrame(function() {
                                Plotly.relayout(elTop, {
                                    'yaxis.range': currentPriceRange,
                                    'yaxis.autorange': false,
                                    'yaxis2.range': currentVolRange,
                                    'yaxis2.autorange': false
                                });
                            });
                        }).catch(function(err) {
                            console.warn("Relayout sync warning:", err);
                        }).finally(function() {
                            setTimeout(function() { isUpdating = false; }, 20);
                        });
                    }, 0);

                } else if (auto) {
                    isUpdating = true;
                    if (watchdogTimer) clearTimeout(watchdogTimer);
                    watchdogTimer = setTimeout(function() { isUpdating = false; }, 120);

                    var updTopAuto = { 'xaxis.autorange': true };
                    var updBtmAuto = {};
                    if (elBtm && elBtm.layout) {
                        for (var j = 1; j <= 3; j++) {
                            var axAuto = (j === 1) ? 'xaxis' : 'xaxis' + j;
                            if (elBtm.layout[axAuto]) updBtmAuto[axAuto + '.autorange'] = true;
                        }
                        if (!isIndexAsset) {
                            for (var j = 4; j <= 9; j++) {
                                var axAuto = 'xaxis' + j;
                                if (elBtm.layout[axAuto]) updBtmAuto[axAuto + '.autorange'] = true;
                            }
                        }
                    }

                    setTimeout(function() {
                        var pa1 = Plotly.relayout(elTop, updTopAuto);
                        var pa2 = (Object.keys(updBtmAuto).length > 0) ? Plotly.relayout(elBtm, updBtmAuto) : Promise.resolve();
                        Promise.all([pa1, pa2]).finally(function() {
                            setTimeout(function() { isUpdating = false; }, 20);
                        });
                    }, 0);
                }
            });
        }

        syncXAxis(elTop, elBtm);
        syncXAxis(elBtm, elTop);

        function processPointer(clientX) {
            var rect = elTop.getBoundingClientRect();
            var relX = clientX - rect.left;
            var xaxis = elTop._fullLayout ? elTop._fullLayout.xaxis : null;
            var yaxis = elTop._fullLayout ? elTop._fullLayout.yaxis : null;

            if (!xaxis || typeof xaxis.p2c !== 'function') return;

            var plotLeft = (xaxis._offset !== undefined) ? xaxis._offset : 80;
            var plotLength = (xaxis._length !== undefined) ? xaxis._length : (rect.width - plotLeft - 15);
            var plotRight = plotLeft + plotLength;

            if (relX < plotLeft || relX > plotRight) {
                return;
            }

            var coord = xaxis.p2c(relX - plotLeft);
            var idx = Math.round(coord);

            if (idx >= 0 && idx < totalPoints) {
                updateAllPanes(idx);

                var snapX = xaxis.c2p(idx) + plotLeft;
                lineTop.style.left = snapX + 'px';
                lineBtm.style.left = snapX + 'px';
                lineTop.style.display = 'block';
                lineBtm.style.display = 'block';

                if (yaxis && typeof yaxis.c2p === 'function' && closes[idx] !== null && closes[idx] !== undefined) {
                    var snapY = yaxis.c2p(closes[idx]) + (yaxis._offset || 0);
                    linePrice.style.top = snapY + 'px';
                    linePrice.style.display = 'block';
                }
            }
        }

        function onPointerMove(e) {
            var clientX = e.clientX;
            if (e.touches && e.touches.length > 0) {
                clientX = e.touches[0].clientX;
            }
            if (clientX !== undefined) {
                processPointer(clientX);
            }
        }

        function onPointerLeave() {
            lineTop.style.display = 'none';
            lineBtm.style.display = 'none';
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

def render_interactive_chart_html(
    fig_top,
    fig_btm,
    df,
    m1_thresh=1000,
    m2_thresh=400,
    top_height=420,
    btm_height=1180,
    initial_disp_days=20,
    initial_end_idx=None,
    version_tag="202611112030",
    is_index=False
) -> str:
    import json
    import uuid

    chart_id = "chart_" + uuid.uuid4().hex[:8]
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx

    p_top_json = fig_top.to_json()
    p_btm_json = fig_btm.to_json()

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
        df['Turnover_Rate'].fillna(0).tolist()
        if 'Turnover_Rate' in df.columns
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

    html = js_template
    html = html.replace("__CHART_ID__", chart_id)
    html = html.replace("__TOP_H__", f"{top_height}px")
    html = html.replace("__BTM_H__", f"{btm_height}px")
    html = html.replace("__PLOT_JSON_TOP__", p_top_json)
    html = html.replace("__PLOT_JSON_BTM__", p_btm_json)

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

    return html

def get_component_html(*args, **kwargs):
    import inspect
    sig = inspect.signature(render_interactive_chart_html)
    valid_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return render_interactive_chart_html(*args, **valid_kwargs)
