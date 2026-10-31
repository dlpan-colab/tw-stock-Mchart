"""
frontend.py - 前端 HTML/CSS 渲染與版本彙整模組
版本: 202610312015
"""
import os
import re

MODULE_VERSION = "202610312015"

def get_system_version() -> str:
    """自動萃取各模組版本並回傳系統最大版本號"""
    versions = [MODULE_VERSION]
    module_names = ["chart_builder", "indicators", "data_fetcher", "storage", "config", "cloud_sync"]
    
    # app.py 以讀檔方式取得，避免循環匯入問題
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        app_file = os.path.join(base_dir, "app.py")
        if os.path.exists(app_file):
            with open(app_file, "r", encoding="utf-8") as f:
                content = f.read(500)
                m = re.search(r'MODULE_VERSION\s*=\s*["\'](\d{12})["\']', content)
                if m:
                    versions.append(m.group(1))
    except Exception:
        pass

    for mod_name in module_names:
        try:
            mod = __import__(mod_name)
            v = getattr(mod, "MODULE_VERSION", getattr(mod, "VERSION_TAG", None))
            if v:
                versions.append(str(v).strip())
        except Exception:
            pass
    return max(versions)

SYSTEM_VERSION = get_system_version()

def get_legend_html(version_tag: str = None) -> str:
    """
    台股技術與籌碼分析[頂部版本識別]標籤與運作指示燈
    """
    tag = version_tag if version_tag else SYSTEM_VERSION
    return f"""
    <style>
    @keyframes app-spin {{
        0% {{ transform: rotate(0deg); }}
        100% {{ transform: rotate(360deg); }}
    }}
    .app-loading-ring {{
        display: inline-block;
        width: 13px;
        height: 13px;
        border: 2px solid rgba(41, 128, 185, 0.25);
        border-top: 2px solid #2980b9;
        border-radius: 50%;
        animation: app-spin 0.8s linear infinite;
        vertical-align: middle;
        margin-left: 6px;
    }}
    </style>
    <div style="font-size: 14px; margin-bottom: 4px; padding: 2px 8px; display: inline-flex; align-items: center; background: #f8fafc; border-radius: 4px; border: 1px solid #e2e8f0;">
        <span style="background:#2c3e50; color:#ffffff; padding: 2px 8px; border-radius: 4px; font-weight:bold; font-size:12px;">台股技術與籌碼分析 v{tag}</span>
        <span id="app_loading_spinner" class="app-loading-ring" style="display:none;" title="運作中..."></span>
    </div>
    """

js_template = """
<style>
  .plot-main-container {
    position: relative;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
    padding-bottom: 90px !important;
  }
  .touch-plot-box {
    position: relative;
    touch-action: none !important;
    user-select: none !important;
    -webkit-user-select: none !important;
    width: 100% !important;
  }
  .pane-info-bar {
    font-size: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #2c3e50;
    background: #f8fafc;
    padding: 4px 8px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
    white-space: normal;
    line-height: 1.45;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    overflow-x: auto;
  }
  .val-up { color: #eb4d4b; font-weight: bold; }
  .val-dn { color: #2ecc71; font-weight: bold; }
  .tag-lbl { margin-right: 5px; }
  .middle-inserted-bar {
    width: 100%;
    box-sizing: border-box;
    margin: 4px 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .middle-inserted-bar .pane-info-bar {
    width: 100%;
    box-sizing: border-box;
  }
  .bottom-chip-deck {
    width: 100%;
    box-sizing: border-box;
    margin-top: 6px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .bottom-chip-deck .pane-info-bar {
    width: 100%;
    box-sizing: border-box;
  }
  .sync-crosshair-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    border-left: 1px dotted #2c3e50;
    pointer-events: none;
    display: none;
    z-index: 100;
  }
  .sync-price-line {
    position: absolute;
    left: 80px;
    right: 15px;
    height: 1px;
    border-top: 1px dotted rgba(44, 62, 80, 0.75);
    pointer-events: none;
    display: none;
    z-index: 100;
  }
</style>

<div class="plot-main-container">
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
  var opens = __OPENS__, highs = __HIGHS__, lows = __LOWS__, closes = __CLOSES__, vols = __VOLS__;
  var ma5s = __MA5S__, ma20s = __MA20S__, ma60s = __MA60S__;
  var turnovers = __TURNOVERS__;
  var ks = __KS__, ds = __DS__, difs = __DIFS__, macds = __MACDS__, oscs = __OSCS__;
  var obvs = __OBVS__, obvMas = __OBVMAS__;
  var foreigns = __FOREIGNS__, trusts = __TRUSTS__, dealers = __DEALERS__;
  var mDiffs = __MARGIN_DIFFS__, sDiffs = __SHORT_DIFFS__, rat = __RATIOS__;
  var m1_pcts = __M1_PCTS__, m2_pcts = __M2_PCTS__, m1_thresh = __M1_THRESH__, m2_thresh = __M2_THRESH__;

  var elTop = document.getElementById('__CHART_ID___top'),
      elBtm = document.getElementById('__CHART_ID___btm');
  var lineTop = document.getElementById('__CHART_ID___line_top'),
      lineBtm = document.getElementById('__CHART_ID___line_btm'),
      linePrice = document.getElementById('__CHART_ID___line_price');
  var info1 = document.getElementById('__CHART_ID___info1'),
      infoTech = document.getElementById('__CHART_ID___info_tech');
  var infoMs = document.getElementById('__CHART_ID___info_ms'),
      infoChip = document.getElementById('__CHART_ID___info_chip');

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

    // 主圖資訊
    info1.innerHTML = '<span class="tag-lbl"><b>' + d + '</b></span>' +
      '開:<span class="' + (o > prevC ? 'val-up' : (o < prevC ? 'val-dn' : '')) + '">' + fmtNum(o, 2) + '</span> ' +
      '高:<span class="' + (h > prevC ? 'val-up' : (h < prevC ? 'val-dn' : '')) + '">' + fmtNum(h, 2) + '</span> ' +
      '低:<span class="' + (l > prevC ? 'val-up' : (l < prevC ? 'val-dn' : '')) + '">' + fmtNum(l, 2) + '</span> ' +
      '收:<span class="' + cClass + '">' + fmtNum(c, 2) + ' (' + (diff > 0 ? '+' : '') + fmtNum(diff, 2) + ', ' + (pct > 0 ? '+' : '') + fmtNum(pct, 2) + '%)</span> ' +
      '量:' + fmtNum(vols[idx], 0) + '張 ' +
      '<span class="tag-lbl"><b>換手:' + fmtNum(turnovers[idx], 2) + '%</b></span> ' +
      'MA5:' + fmtNum(ma5s[idx], 2) + ' MA20:' + fmtNum(ma20s[idx], 2) + ' MA60:' + fmtNum(ma60s[idx], 2);

    // 中段技術指標資訊區 (第一行: 日期 KD OBV; 第二行: MACD)
    var oscClass = oscs[idx] > 0 ? 'val-up' : (oscs[idx] < 0 ? 'val-dn' : '');
    infoTech.innerHTML = '<div><span class="tag-lbl"><b>' + d + '</b></span> <span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:' + fmtNum(ks[idx], 1) + '</span> <span style="color:#3498db;">D:' + fmtNum(ds[idx], 1) + '</span> | <span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:' + fmtNum(obvs[idx], 0) + '</span> <span style="color:#8e44ad;">MA20:' + fmtNum(obvMas[idx], 0) + '</span></div>' +
                         '<div><span class="tag-lbl"><b>MACD(' + d + ')</b></span><span style="color:#f39c12;">DIF:' + fmtNum(difs[idx], 2) + '</span> <span style="color:#2980b9;">MACD:' + fmtNum(macds[idx], 2) + '</span> OSC:<span class="' + oscClass + '">' + fmtNum(oscs[idx], 2) + '</span></div>';

    // 底部資券資訊
    infoMs.innerHTML = '<span class="tag-lbl"><b>資券[千張](' + d + ')</b></span>' +
      '融資:' + fmtDiff(mDiffs[idx], 3) + ' 融券:' + fmtDiff(sDiffs[idx], 3) + ' ' +
      '<span class="tag-lbl"><b>券資比:' + fmtNum(rat[idx], 2) + '%</b></span>';

    // 底部法人與集保資訊
    infoChip.innerHTML = '<span class="tag-lbl"><b>法人集保(' + d + ')</b></span>' +
      '外資:' + fmtDiff(foreigns[idx], 0) + ' 投信:' + fmtDiff(trusts[idx], 0) + ' 自營:' + fmtDiff(dealers[idx], 0) + ' | ' +
      '≥' + m1_thresh + '張: ' + fmtNum(m1_pcts[idx], 2) + '% ' +
      '≥' + m2_thresh + '張: ' + fmtNum(m2_pcts[idx], 2) + '%';
  }

  var cfg = {
    responsive: true,
    displayModeBar: false,
    scrollZoom: false
  };

  Plotly.newPlot(elTop, pTop.data, pTop.layout, cfg).then(function() {
    return Plotly.newPlot(elBtm, pBtm.data, pBtm.layout, cfg);
  }).then(function() {
    updateAllPanes(initEnd);

    function syncXAxis(srcEl, destEl) {
      srcEl.on('plotly_relayout', function(ed) {
        if (isUpdating) return;
        var r0 = ed['xaxis.range[0]'] !== undefined ? ed['xaxis.range[0]'] : (ed['xaxis.range'] ? ed['xaxis.range'][0] : null);
        var r1 = ed['xaxis.range[1]'] !== undefined ? ed['xaxis.range[1]'] : (ed['xaxis.range'] ? ed['xaxis.range'][1] : null);
        var auto = ed['xaxis.autorange'];

        if (r0 !== null && r1 !== null) {
          isUpdating = true;
          var upd = {};
          for (var i = 1; i <= 9; i++) {
            var ax = (i === 1) ? 'xaxis' : 'xaxis' + i;
            if (destEl.layout[ax]) {
              upd[ax + '.range'] = [r0, r1];
              upd[ax + '.autorange'] = false;
            }
          }
          Plotly.relayout(destEl, upd).then(function() {
            isUpdating = false;
          }).catch(function() { isUpdating = false; });
        } else if (auto) {
          isUpdating = true;
          var updAuto = {};
          for (var j = 1; j <= 9; j++) {
            var axAuto = (j === 1) ? 'xaxis' : 'xaxis' + j;
            if (destEl.layout[axAuto]) {
              updAuto[axAuto + '.autorange'] = true;
            }
          }
          Plotly.relayout(destEl, updAuto).then(function() {
            isUpdating = false;
          }).catch(function() { isUpdating = false; });
        }
      });
    }

    syncXAxis(elTop, elBtm);
    syncXAxis(elBtm, elTop);

    function handleHover(d) {
      if (!d || !d.points || !d.points.length) return;
      var pt = d.points[0];
      var idx = Math.round(pt.x);
      if (idx >= 0 && idx < totalPoints) {
        updateAllPanes(idx);

        var xPixel = pt.xaxis.d2p(pt.x) + pt.xaxis._offset;
        lineTop.style.left = xPixel + 'px';
        lineBtm.style.left = xPixel + 'px';
        lineTop.style.display = 'block';
        lineBtm.style.display = 'block';

        if (pt.yaxis && pt.y !== undefined) {
          var yPixel = pt.yaxis.d2p(pt.y) + pt.yaxis._offset;
          linePrice.style.top = yPixel + 'px';
          linePrice.style.display = 'block';
        }
      }
    }

    elTop.on('plotly_hover', handleHover);
    elBtm.on('plotly_hover', handleHover);

    function hideLines() {
      lineTop.style.display = 'none';
      lineBtm.style.display = 'none';
      linePrice.style.display = 'none';
    }

    elTop.on('plotly_unhover', hideLines);
    elBtm.on('plotly_unhover', hideLines);
  });
})();
</script>
"""

def render_interactive_chart_html(
    fig_top, fig_btm, df,
    m1_thresh=1000, m2_thresh=400,
    top_height=560, btm_height=1200,
    initial_disp_days=20,
    initial_end_idx=None
) -> str:
    """渲染雙圖連動及懸停十字線的互動 HTML 容器"""
    import json
    import uuid

    chart_id = "chart_" + uuid.uuid4().hex[:8]
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx

    p_top_json = fig_top.to_json()
    p_btm_json = fig_btm.to_json()

    # 序列化各指標陣列以供 JavaScript 懸浮即時讀取
    dates_list = df['Date'].dt.strftime('%Y-%m-%d').tolist() if hasattr(df['Date'], 'dt') else df['Date'].astype(str).tolist()
    opens_list = df['Open'].tolist()
    highs_list = df['High'].tolist()
    lows_list = df['Low'].tolist()
    closes_list = df['Close'].tolist()
    vols_list = df['Volume'].tolist()

    ma5_list = df['MA5'].fillna(0).tolist() if 'MA5' in df.columns else [0] * n_pts
    ma20_list = df['MA20'].fillna(0).tolist() if 'MA20' in df.columns else [0] * n_pts
    ma60_list = df['MA60'].fillna(0).tolist() if 'MA60' in df.columns else [0] * n_pts
    turnover_list = df['TurnoverRate'].fillna(0).tolist() if 'TurnoverRate' in df.columns else [0] * n_pts

    k_list = df['K'].fillna(0).tolist() if 'K' in df.columns else [0] * n_pts
    d_list = df['D'].fillna(0).tolist() if 'D' in df.columns else [0] * n_pts
    dif_list = df['DIF'].fillna(0).tolist() if 'DIF' in df.columns else [0] * n_pts
    macd_list = df['MACD'].fillna(0).tolist() if 'MACD' in df.columns else [0] * n_pts
    osc_list = df['OSC'].fillna(0).tolist() if 'OSC' in df.columns else [0] * n_pts

    obv_list = df['OBV'].fillna(0).tolist() if 'OBV' in df.columns else [0] * n_pts
    obv_ma_list = df['OBV_MA20'].fillna(0).tolist() if 'OBV_MA20' in df.columns else [0] * n_pts

    foreign_list = df['Foreign_Diff'].fillna(0).tolist() if 'Foreign_Diff' in df.columns else [0] * n_pts
    trust_list = df['Trust_Diff'].fillna(0).tolist() if 'Trust_Diff' in df.columns else [0] * n_pts
    dealer_list = df['Dealer_Diff'].fillna(0).tolist() if 'Dealer_Diff' in df.columns else [0] * n_pts

    m_diff_list = df['Margin_Diff'].fillna(0).tolist() if 'Margin_Diff' in df.columns else [0] * n_pts
    s_diff_list = df['Short_Diff'].fillna(0).tolist() if 'Short_Diff' in df.columns else [0] * n_pts
    ratio_list = df['Margin_Short_Ratio'].fillna(0).tolist() if 'Margin_Short_Ratio' in df.columns else [0] * n_pts

    m1_pct_list = df['Major1_Pct'].fillna(0).tolist() if 'Major1_Pct' in df.columns else [0] * n_pts
    m2_pct_list = df['Major2_Pct'].fillna(0).tolist() if 'Major2_Pct' in df.columns else [0] * n_pts

    html = js_template
    html = html.replace("__CHART_ID__", chart_id)
    html = html.replace("__TOP_H__", f"{top_height}px")
    html = html.replace("__BTM_H__", f"{btm_height}px")
    html = html.replace("__PLOT_JSON_TOP__", p_top_json)
    html = html.replace("__PLOT_JSON_BTM__", p_btm_json)
    html = html.replace("__DATES__", json.dumps(dates_list))
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
