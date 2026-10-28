"""
台股技術與籌碼分析系統 - 前端組件與樣式模組
輸出五大即時看板（Quote Bar、技術1、技術2、資券、法人集保）、
雙向同步十字線、防抖節流滾輪縮放、動態極值重算，
以及行動端緊湊按鈕 CSS 與圖例函式 get_legend_html。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "frontend"
MODULE_VERSION = "202610280310"

import json
from typing import Dict, Optional
import pandas as pd
import plotly.graph_objects as go


def get_legend_html(version_tag: str = MODULE_VERSION, module_versions: Optional[Dict[str, str]] = None) -> str:
    """
    生成頂部圖例看板 HTML
    """
    display_ver = version_tag if isinstance(version_tag, str) else MODULE_VERSION
    if isinstance(module_versions, dict) and "app" in module_versions:
        display_ver = module_versions["app"]

    return f"""
    <style>
      @keyframes app-spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
      .app-loading-ring {{ display: inline-block; width: 14px; height: 14px; border: 2.5px solid rgba(41, 128, 185, 0.25); border-top: 2.5px solid #2980b9; border-radius: 50%; animation: app-spin 0.8s linear infinite; vertical-align: middle; margin-left: 6px; }}
      
      div[data-testid="stHorizontalBlock"]:has(button) {{
          flex-direction: row !important;
          display: flex !important;
          flex-wrap: nowrap !important;
          gap: 10px !important;
          width: auto !important;
          max-width: 250px !important;
          margin: 4px 0 !important;
      }}
      div[data-testid="stHorizontalBlock"]:has(button) > div {{
          flex: 1 1 0px !important;
          min-width: 80px !important;
          max-width: 120px !important;
      }}
      div[data-testid="stHorizontalBlock"] button {{
          height: 32px !important;
          min-height: 32px !important;
          padding: 0 8px !important;
          font-size: 13px !important;
          line-height: 30px !important;
      }}
    </style>
    <div style="font-size: 14px; line-height: 1.6; margin-bottom: 6px; padding: 4px 10px; background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
      <span style="background:#2c3e50; color:#ffffff; padding: 1px 6px; border-radius: 4px; font-weight:bold; margin-right: 6px;">v{display_ver}</span>
      <span id="app_loading_spinner" class="app-loading-ring" style="display:none;" title="系統運作中..."></span>
      <b>主圖：</b><span style="color:#eb4d4b;">■</span> K線 <span style="color:#27ae60;font-weight:bold;">〔頭〕</span> <span style="color:#e74c3c;font-weight:bold;">〔底〕</span> <span style="color:#f1c40f;">MA5</span> <span style="color:#e67e22;">MA20</span> <span style="color:#9b59b6;">MA60</span> | 
      <b>技術：</b><span style="color:#eb4d4b;">■</span> 量/OSC <span style="color:#1e3799; font-weight:bold;">▲</span>≥10% <span style="color:#f1c40f; font-weight:bold;">▼</span>≥20% <span style="color:#e74c3c;">K</span> <span style="color:#3498db;">D</span> <span style="color:#f39c12;">DIF</span> <span style="color:#2980b9;">MACD</span> <span style="color:#16a085;">OBV</span> | 
      <b>法人：</b><span style="color:#eb4d4b;">■</span> 外/投/自 <span style="color:#c0392b;">大1</span> <span style="color:#8e44ad;">大2</span> | 
      <b>資券：</b><span style="color:#eb4d4b;">■</span>(左)融資 <span style="color:#f1c40f;">■</span>(右)融券 <span style="color:#e67e22;">━</span> 券資比
    </div>
    """


def get_component_html(
    fig_top: go.Figure,
    fig_btm: go.Figure,
    df: pd.DataFrame,
    raw_ticker: str,
    major1_thresh: int,
    major2_thresh: int,
    initial_end_idx: int,
    initial_disp_days: int,
    is_mobile: bool = False
) -> str:
    """
    輸出嵌入式雙圖 HTML/JS：
    包含 5 大資訊面板、十字雙向連動、動態極值縮放與防抖更新
    """
    chart_id = f"chart_{str(raw_ticker).replace('.', '_')}"
    top_h_css = "340px" if is_mobile else "380px"
    btm_h_css = "1050px" if is_mobile else "1150px"

    js_template = """
    <style>
      .plot-main-container { position: relative; width: 100%; box-sizing: border-box; overflow-x: auto; padding-bottom: 120px !important; }
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

                var cMaxP = -Infinity, cMinP = Infinity, cMaxVol = 0, cMaxMacd = -Infinity, cMinMacd = Infinity, cMaxObv = -Infinity, cMinObv = Infinity;
                var cMaxFn = 0, cMaxTn = 0, cMaxDn = 0, cMaxMs = 0, cMaxRat = -Infinity, cMinRat = Infinity, cMaxM1 = -Infinity, cMinM1 = Infinity, cMaxM2 = -Infinity, cMinM2 = Infinity;

                for (var i = iStart; i <= iEnd; i++) {
                    if (isValidNum(highs[i]) && highs[i] > cMaxP) cMaxP = highs[i];
                    if (isValidNum(lows[i]) && lows[i] < cMinP) cMinP = lows[i];
                    if (isValidNum(vols[i]) && vols[i] > cMaxVol) cMaxVol = vols[i];
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
                    var tUpd = {'yaxis.range': [cMinP - (cMaxP - cMinP)*0.08, cMaxP + (cMaxP - cMinP)*0.12], 'yaxis2.range': [0, cMaxVol*1.30]};
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

                var uSrc = {'xaxis.range': [r0, r1], 'xaxis.autorange': false};
                var uTgt = {};
                for (var i = 1; i <= (tgt === elBtm ? 9 : 2); i++) {
                    uTgt[(i === 1 ? 'xaxis' : 'xaxis' + i) + '.range'] = [r0, r1];
                    uTgt[(i === 1 ? 'xaxis' : 'xaxis' + i) + '.autorange'] = false;
                }

                Promise.all([Plotly.relayout(src, uSrc), Plotly.relayout(tgt, uTgt)])
                    .then(function() { isUpdating = false; })
                    .catch(function() { isUpdating = false; });
            }, 40);
        }

        elTop.on('plotly_relayout', function(ed) { syncRelayout(elTop, elBtm, ed); });
        elBtm.on('plotly_relayout', function(ed) { syncRelayout(elBtm, elTop, ed); });

        function getHoverIndex(el, cx) {
            try {
                var xa = el._fullLayout.xaxis;
                var val = xa.p2c(cx - el.getBoundingClientRect().left - el._fullLayout._size.l);
                return Math.max(0, Math.min(totalPoints-1, isNaN(Math.round(val)) ? Math.round(xa.range[1]) : Math.round(val)));
            } catch(e) {
                return totalPoints-1;
            }
        }

        function bindHover(el) {
            el.addEventListener('pointermove', function(e) { setCrosshair(getHoverIndex(el, e.clientX)); }, {passive: true});
            el.addEventListener('pointerdown', function(e) { setCrosshair(getHoverIndex(el, e.clientX)); }, {passive: true});
        }
        bindHover(elTop);
        bindHover(elBtm);
    })();
    </script>
    """

    def clean_floats(s):
        return [None if pd.isna(x) else round(float(x), 4) for x in s]

    html_out = (
        js_template
        .replace('__CHART_ID__', chart_id)
        .replace('__TOP_H__', top_h_css)
        .replace('__BTM_H__', btm_h_css)
        .replace('__INITIAL_END_IDX__', str(initial_end_idx))
        .replace('__INITIAL_DISP_DAYS__', str(initial_disp_days))
        .replace('__PLOT_JSON_TOP__', fig_top.to_json())
        .replace('__PLOT_JSON_BTM__', fig_btm.to_json())
        .replace('__DATES__', json.dumps([d.strftime('%Y-%m-%d') for d in df.index]))
        .replace('__OPENS__', json.dumps(clean_floats(df['Open'])))
        .replace('__HIGHS__', json.dumps(clean_floats(df['High'])))
        .replace('__LOWS__', json.dumps(clean_floats(df['Low'])))
        .replace('__CLOSES__', json.dumps(clean_floats(df['Close'])))
        .replace('__VOLS__', json.dumps(clean_floats(df['Volume_Sheets'])))
        .replace('__TURNOVERS__', json.dumps(clean_floats(df['Turnover_Rate'])))
        .replace('__MA5S__', json.dumps(clean_floats(df['MA5'])))
        .replace('__MA20S__', json.dumps(clean_floats(df['MA20'])))
        .replace('__MA60S__', json.dumps(clean_floats(df['MA60'])))
        .replace('__KS__', json.dumps(clean_floats(df['K'])))
        .replace('__DS__', json.dumps(clean_floats(df['D'])))
        .replace('__DIFS__', json.dumps(clean_floats(df['DIF'])))
        .replace('__MACDS__', json.dumps(clean_floats(df['MACD'])))
        .replace('__OSCS__', json.dumps(clean_floats(df['OSC'])))
        .replace('__OBVS__', json.dumps(clean_floats(df['OBV'])))
        .replace('__OBVMAS__', json.dumps(clean_floats(df['OBV_MA20'])))
        .replace('__FOREIGNS__', json.dumps(clean_floats(df['Foreign_Net'])))
        .replace('__TRUSTS__', json.dumps(clean_floats(df['Trust_Net'])))
        .replace('__DEALERS__', json.dumps(clean_floats(df['Dealer_Net'])))
        .replace('__MARGIN_DIFFS__', json.dumps(clean_floats(df['Margin_Diff'])))
        .replace('__SHORT_DIFFS__', json.dumps(clean_floats(df['Short_Diff'])))
        .replace('__RATIOS__', json.dumps(clean_floats(df['Short_Margin_Ratio'])))
        .replace('__M1_PCTS__', json.dumps(clean_floats(df['Major1_Pct'])))
        .replace('__M2_PCTS__', json.dumps(clean_floats(df['Major2_Pct'])))
        .replace('__M1_THRESH__', str(major1_thresh))
        .replace('__M2_THRESH__', str(major2_thresh))
    )

    return html_out
