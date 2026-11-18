"""
frontend.py - 前端圖表 HTML / JavaScript 互動渲染模組 (支援三頁籤完全解耦：主圖 + 指標頁籤 + 籌碼頁籤 + 分點頁籤預設20日與60日按需載入＋真實買超紅柱/賣超綠柱與月份X軸版)
版本: 202611180831
"""
import json
import pandas as pd

MODULE_NAME = "frontend"
MODULE_VERSION = "202611180831"

COMMON_CSS = """
html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #ffffff; overflow-x: hidden; }
.frame-root { position: relative; width: 100%; box-sizing: border-box; padding-bottom: 4px; }
.pane-info-bar {
    font-size: 12px; font-weight: 500; color: #1e293b; background: #f8fafc;
    border: 1px solid #e2e8f0; border-radius: 5px; padding: 4px 6px; margin: 2px 0;
    line-height: 1.4; word-break: break-all;
}
.val-up { color: #eb4d4b; font-weight: bold; }
.val-dn { color: #16a085; font-weight: bold; }
.val-flat { color: #333333; font-weight: bold; }
.touch-plot-box { position: relative; width: 100%; touch-action: pan-y; user-select: none; -webkit-user-select: none; overflow: hidden; }
.v-crosshair { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(41, 128, 185, 0.85); pointer-events: none; z-index: 40; display: none; }
.nav-overlay {
    position: fixed; top: 50%; transform: translateY(-50%); z-index: 9999;
    background: rgba(15, 23, 42, 0.45); color: #fff; border: none; border-radius: 50%;
    width: 32px; height: 32px; font-size: 15px; cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.nav-overlay:hover { background: rgba(15, 23, 42, 0.78); }
.nav-prev { left: 4px; }
.nav-next { right: 4px; }
"""


def get_legend_html() -> str:
    return """
    <div style="font-size:12px; color:#334155; background:#f1f5f9; padding:5px 8px; border-radius:5px; margin-bottom:4px; line-height:1.5;">
        <b>📌 圖例與互動操作說明：</b>
        <span style="color:#eb4d4b; font-weight:bold;">■ 紅K/買超/資增</span> ｜
        <span style="color:#2ecc71; font-weight:bold;">■ 綠K/賣超/資減</span> ｜
        <span style="color:#f1c40f; font-weight:bold;">— MA5</span> ｜
        <span style="color:#e67e22; font-weight:bold;">— MA20/券資比</span> ｜
        <span style="color:#9b59b6; font-weight:bold;">— MA60</span> ｜
        <span style="color:#27ae60; font-weight:bold;">〔頭〕</span><span style="color:#e74c3c; font-weight:bold;">〔底〕</span> 5MA轉折 ｜
        <span style="color:#1e3799; font-weight:bold;">▲</span> 周轉≥10% ｜
        <span style="color:#d4ac0d; font-weight:bold;">▼</span> 周轉≥20%<br/>
        <span style="color:#475569;">💡 點擊或滑動任一圖表可同步更新數值與跨頁籤關注交易日；左右拖曳平移 K 線、滾輪或雙指縮放日數。</span>
    </div>
    """


def _build_base_records_json(df: pd.DataFrame, is_index: bool) -> str:
    records = []
    for i in range(len(df)):
        row = df.iloc[i]
        d_str = df.index[i].strftime('%Y-%m-%d')
        o = float(row['Open'])
        h = float(row['High'])
        l = float(row['Low'])
        c = float(row['Close'])
        prev_c = float(df['Close'].iloc[i - 1]) if i > 0 else o
        chg = c - prev_c
        pct = (chg / prev_c * 100.0) if prev_c != 0 else 0.0
        vol_sh = float(row['Volume_Sheets']) if not pd.isna(row['Volume_Sheets']) else 0.0
        to_rate = float(row['Turnover_Rate']) if ('Turnover_Rate' in df.columns and not pd.isna(row['Turnover_Rate'])) else 0.0

        def safe_f(col, default=None):
            if col not in df.columns or pd.isna(row[col]):
                return default
            return float(row[col])

        records.append({
            "d": d_str,
            "o": round(o, 2),
            "h": round(h, 2),
            "l": round(l, 2),
            "c": round(c, 2),
            "chg": round(chg, 2),
            "pct": round(pct, 2),
            "vol": int(round(vol_sh)),
            "to": round(to_rate, 2),
            "ma5": round(safe_f('MA5', 0.0), 2),
            "ma20": round(safe_f('MA20', 0.0), 2),
            "ma60": round(safe_f('MA60', 0.0), 2),
            "b20": round(safe_f('BIAS_20'), 2) if safe_f('BIAS_20') is not None else None,
            "b120": round(safe_f('BIAS_120'), 2) if safe_f('BIAS_120') is not None else None,
            "b240": round(safe_f('BIAS_240'), 2) if safe_f('BIAS_240') is not None else None,
            "b1200": round(safe_f('BIAS_1200'), 2) if safe_f('BIAS_1200') is not None else None,
            "k": round(safe_f('K', 50.0), 1),
            "d_val": round(safe_f('D', 50.0), 1),
            "dif": round(safe_f('DIF', 0.0), 2),
            "macd": round(safe_f('MACD', 0.0), 2),
            "osc": round(safe_f('OSC', 0.0), 2),
            "obv": int(round(safe_f('OBV', 0.0))),
            "obv_ma": int(round(safe_f('OBV_MA20', 0.0))),
            "fn": int(round(safe_f('Foreign_Net', 0.0))),
            "tn": int(round(safe_f('Trust_Net', 0.0))),
            "dn": int(round(safe_f('Dealer_Net', 0.0))),
            "md": int(round(safe_f('Margin_Diff', 0.0))),
            "mb": int(round(safe_f('Margin_Bal', 0.0))),
            "sd": int(round(safe_f('Short_Diff', 0.0))),
            "sb": int(round(safe_f('Short_Bal', 0.0))),
            "smr": round(safe_f('Short_Margin_Ratio'), 2) if safe_f('Short_Margin_Ratio') is not None else None,
            "m1": round(safe_f('Major1_Pct'), 2) if safe_f('Major1_Pct') is not None else None,
            "m2": round(safe_f('Major2_Pct'), 2) if safe_f('Major2_Pct') is not None else None,
        })
    return json.dumps(records, ensure_ascii=False)


def _shared_sync_js() -> str:
    return """
    function broadcastFocus(cid, idx, dispDays, endIdx) {
        try {
            var msg = { type: 'MCHART_SYNC_FOCUS', cid: cid, idx: idx, dispDays: dispDays, endIdx: endIdx };
            if (window.parent && window.parent.frames) {
                for (var i = 0; i < window.parent.frames.length; i++) {
                    try { window.parent.frames[i].postMessage(msg, '*'); } catch (e) {}
                }
            }
        } catch (e) {}
    }
    function fmtSign(v, dec) {
        if (v === null || v === undefined || isNaN(v)) return '-';
        var s = dec > 0 ? Number(v).toFixed(dec) : Math.round(Number(v)).toString();
        return (v > 0 ? '+' : '') + s;
    }
    function clsVal(v) {
        if (v === null || v === undefined || isNaN(v) || v === 0) return 'val-flat';
        return v > 0 ? 'val-up' : 'val-dn';
    }
    function idxFromClientX(gd, clientX) {
        if (!gd || !gd._fullLayout || !gd._fullLayout.xaxis) return -1;
        var xa = gd._fullLayout.xaxis;
        var rect = gd.getBoundingClientRect();
        var relX = clientX - rect.left - xa._offset;
        var dataX = xa.p2d(relX);
        var idx = Math.round(dataX);
        return idx;
    }
    function placeCrosshair(gd, lineEl, idx) {
        if (!gd || !lineEl || !gd._fullLayout || !gd._fullLayout.xaxis) return;
        var xa = gd._fullLayout.xaxis;
        var px = xa.d2p(idx) + xa._offset;
        if (px >= xa._offset && px <= xa._offset + xa._length) {
            lineEl.style.left = px + 'px';
            lineEl.style.display = 'block';
        } else {
            lineEl.style.display = 'none';
        }
    }
    function bindPaneTouch(boxEl, gd, state, onFocusIdx, onRangeChange) {
        var dragging = false, startX = 0, startRange = null, lastPinchDist = 0;
        boxEl.addEventListener('touchstart', function(ev) {
            if (ev.touches.length === 1) {
                dragging = true;
                startX = ev.touches[0].clientX;
                startRange = gd._fullLayout.xaxis.range.slice();
                var idx = idxFromClientX(gd, ev.touches[0].clientX);
                if (idx >= 0 && idx < state.total) onFocusIdx(idx, true);
            } else if (ev.touches.length === 2) {
                dragging = false;
                lastPinchDist = Math.abs(ev.touches[0].clientX - ev.touches[1].clientX);
            }
        }, { passive: true });
        boxEl.addEventListener('touchmove', function(ev) {
            if (ev.touches.length === 1 && dragging && startRange) {
                var dx = ev.touches[0].clientX - startX;
                var xa = gd._fullLayout.xaxis;
                var span = startRange[1] - startRange[0];
                var shift = -(dx / Math.max(1, xa._length)) * span;
                var n0 = startRange[0] + shift, n1 = startRange[1] + shift;
                if (n0 < -0.5) { n1 += (-0.5 - n0); n0 = -0.5; }
                if (n1 > state.total - 0.5) { n0 -= (n1 - (state.total - 0.5)); n1 = state.total - 0.5; }
                Plotly.relayout(gd, { 'xaxis.range': [n0, n1] });
                if (onRangeChange) onRangeChange(n0, n1);
            } else if (ev.touches.length === 2) {
                var dist = Math.abs(ev.touches[0].clientX - ev.touches[1].clientX);
                if (lastPinchDist > 10 && Math.abs(dist - lastPinchDist) > 6) {
                    var r = gd._fullLayout.xaxis.range;
                    var mid = (r[0] + r[1]) / 2;
                    var half = ((r[1] - r[0]) / 2) * (lastPinchDist / Math.max(1, dist));
                    half = Math.max(5, Math.min(state.total / 2, half));
                    var z0 = Math.max(-0.5, mid - half), z1 = Math.min(state.total - 0.5, mid + half);
                    Plotly.relayout(gd, { 'xaxis.range': [z0, z1] });
                    if (onRangeChange) onRangeChange(z0, z1);
                    lastPinchDist = dist;
                }
            }
        }, { passive: true });
        boxEl.addEventListener('touchend', function() { dragging = false; lastPinchDist = 0; }, { passive: true });
        boxEl.addEventListener('mousemove', function(ev) {
            var idx = idxFromClientX(gd, ev.clientX);
            if (idx >= 0 && idx < state.total) onFocusIdx(idx, false);
        });
        boxEl.addEventListener('click', function(ev) {
            var idx = idxFromClientX(gd, ev.clientX);
            if (idx >= 0 && idx < state.total) onFocusIdx(idx, true);
        });
    }
    """


def get_top_chart_html(fig_top, df: pd.DataFrame, chart_id: str, top_height: int, initial_disp_days: int, initial_end_idx: int) -> str:
    is_index = str(df.index.name) == "INDEX" or (df['Turnover_Rate'].max() == 0 and df['Foreign_Net'].abs().max() == 0)
    rec_json = _build_base_records_json(df, is_index)
    fig_json = fig_top.to_json()
    tpl = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>__CSS__</style></head><body>
<div class="frame-root" id="__CID___root">
  <div id="__CID___info1" class="pane-info-bar">載入主圖資訊中...</div>
  <div id="__CID___top" class="touch-plot-box" style="height:__TOP_H__px;">
    <div id="__CID___vline" class="v-crosshair"></div>
  </div>
  <button class="nav-overlay nav-prev" id="__CID___prev" title="往左移動K線">◀</button>
  <button class="nav-overlay nav-next" id="__CID___next" title="往右移動K線">▶</button>
</div>
<script>
(function(){
  __SYNC_JS__
  var RECS = __RECS__;
  var FIG = __FIG__;
  var state = { total: RECS.length, focusIdx: __INIT_END__, dispDays: __INIT_DISP__, endIdx: __INIT_END__ };
  var gd = document.getElementById('__CID___top');
  var infoEl = document.getElementById('__CID___info1');
  var vline = document.getElementById('__CID___vline');

  function updateInfo(idx) {
    if (idx < 0 || idx >= RECS.length) return;
    state.focusIdx = idx;
    var r = RECS[idx];
    var cCls = clsVal(r.chg);
    var toTxt = r.to > 0 ? (' 換手:<span class="' + (r.to >= 10 ? 'val-up' : 'val-flat') + '">' + r.to.toFixed(2) + '%</span>') : '';
    infoEl.innerHTML = '<b>' + r.d + '</b> 開:' + r.o.toFixed(2) + ' 高:<span class="val-up">' + r.h.toFixed(2) + '</span>' +
      ' 低:<span class="val-dn">' + r.l.toFixed(2) + '</span>' +
      ' 收:<span class="' + cCls + '">' + r.c.toFixed(2) + ' (' + fmtSign(r.chg, 2) + ', ' + fmtSign(r.pct, 2) + '%)</span>' +
      ' 量:' + r.vol.toLocaleString() + '張' + toTxt +
      ' <span style="color:#d4ac0d;font-weight:bold;">MA5:' + r.ma5.toFixed(2) + '</span>' +
      ' <span style="color:#e67e22;font-weight:bold;">MA20:' + r.ma20.toFixed(2) + '</span>' +
      ' <span style="color:#9b59b6;font-weight:bold;">MA60:' + r.ma60.toFixed(2) + '</span>';
    placeCrosshair(gd, vline, idx);
  }

  function onFocus(idx, doBroadcast) {
    updateInfo(idx);
    if (doBroadcast) broadcastFocus('__CID__', idx, state.dispDays, state.endIdx);
  }

  Plotly.newPlot(gd, FIG.data, FIG.layout, { displayModeBar: false, responsive: true }).then(function() {
    updateInfo(state.focusIdx);
    bindPaneTouch(gd, gd, state, onFocus, function(n0, n1) {
      state.dispDays = Math.max(5, Math.round(n1 - n0));
      state.endIdx = Math.min(state.total - 1, Math.max(0, Math.round(n1 - 0.5)));
      updateInfo(state.endIdx);
      broadcastFocus('__CID__', state.endIdx, state.dispDays, state.endIdx);
    });
    gd.on('plotly_relayout', function(ed) {
      if (ed && ed['xaxis.range[0]'] !== undefined && ed['xaxis.range[1]'] !== undefined) {
        var n0 = ed['xaxis.range[0]'], n1 = ed['xaxis.range[1]'];
        state.dispDays = Math.max(5, Math.round(n1 - n0));
        state.endIdx = Math.min(state.total - 1, Math.max(0, Math.round(n1 - 0.5)));
        updateInfo(state.endIdx);
        broadcastFocus('__CID__', state.endIdx, state.dispDays, state.endIdx);
      }
    });
  });

  function shiftWindow(step) {
    var r = gd._fullLayout.xaxis.range;
    var span = r[1] - r[0];
    var n0 = Math.max(-0.5, Math.min(state.total - 0.5 - span, r[0] + step));
    var n1 = n0 + span;
    Plotly.relayout(gd, { 'xaxis.range': [n0, n1] });
  }
  document.getElementById('__CID___prev').addEventListener('click', function(){ shiftWindow(-Math.max(1, Math.round(state.dispDays * 0.4))); });
  document.getElementById('__CID___next').addEventListener('click', function(){ shiftWindow(Math.max(1, Math.round(state.dispDays * 0.4))); });

  window.addEventListener('message', function(ev) {
    var msg = ev.data || {};
    if (msg.type === 'MCHART_SYNC_FOCUS' && msg.idx >= 0 && msg.idx < state.total) {
      updateInfo(msg.idx);
    }
  });
})();
</script></body></html>"""
    return (tpl.replace("__CSS__", COMMON_CSS)
               .replace("__SYNC_JS__", _shared_sync_js())
               .replace("__CID__", chart_id)
               .replace("__TOP_H__", str(top_height))
               .replace("__RECS__", rec_json)
               .replace("__FIG__", fig_json)
               .replace("__INIT_DISP__", str(initial_disp_days))
               .replace("__INIT_END__", str(initial_end_idx)))


def get_tech_tab_html(fig_btm: dict, df: pd.DataFrame, chart_id: str, tech_height: int, initial_disp_days: int, initial_end_idx: int) -> str:
    rec_json = _build_base_records_json(df, False)
    fig_json = fig_btm["tech"].to_json()
    tpl = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>__CSS__</style></head><body>
<div class="frame-root" id="__CID___tech_root">
  <div id="__CID___tech_info" class="pane-info-bar">載入技術指標中...</div>
  <div id="__CID___tech_plot" class="touch-plot-box" style="height:__TECH_H__px;">
    <div id="__CID___tech_vline" class="v-crosshair"></div>
  </div>
</div>
<script>
(function(){
  __SYNC_JS__
  var RECS = __RECS__;
  var FIG = __FIG__;
  var state = { total: RECS.length, focusIdx: __INIT_END__, dispDays: __INIT_DISP__, endIdx: __INIT_END__ };
  var gd = document.getElementById('__CID___tech_plot');
  var infoEl = document.getElementById('__CID___tech_info');
  var vline = document.getElementById('__CID___tech_vline');

  function fmtBias(v) {
    if (v === null || v === undefined || isNaN(v)) return '-';
    return '<span class="' + clsVal(v) + '">' + fmtSign(v, 2) + '%</span>';
  }

  function updateInfo(idx) {
    if (idx < 0 || idx >= RECS.length) return;
    state.focusIdx = idx;
    var r = RECS[idx];
    infoEl.innerHTML = '<b>' + r.d + '</b> ｜ <b>KD(9)</b> K:<span class="val-up">' + r.k.toFixed(1) + '</span> D:<span class="val-dn">' + r.d_val.toFixed(1) + '</span>' +
      ' ｜ <b>MACD</b> DIF:' + r.dif.toFixed(2) + ' MACD:' + r.macd.toFixed(2) + ' OSC:<span class="' + clsVal(r.osc) + '">' + fmtSign(r.osc, 2) + '</span>' +
      ' ｜ <b>OBV</b> ' + r.obv.toLocaleString() + ' (MA20:' + r.obv_ma.toLocaleString() + ')' +
      ' ｜ <b>乖離</b> 20日:' + fmtBias(r.b20) + ' 120日:' + fmtBias(r.b120) + ' 240日:' + fmtBias(r.b240) + ' 1200日:' + fmtBias(r.b1200);
    placeCrosshair(gd, vline, idx);
  }

  function onFocus(idx, doBroadcast) {
    updateInfo(idx);
    if (doBroadcast) broadcastFocus('__CID__', idx, state.dispDays, state.endIdx);
  }

  Plotly.newPlot(gd, FIG.data, FIG.layout, { displayModeBar: false, responsive: true }).then(function() {
    updateInfo(state.focusIdx);
    bindPaneTouch(gd, gd, state, onFocus, null);
  });

  window.addEventListener('message', function(ev) {
    var msg = ev.data || {};
    if (msg.type === 'MCHART_SYNC_FOCUS') {
      if (msg.dispDays && msg.endIdx >= 0) {
        var s0 = Math.max(-0.5, msg.endIdx - msg.dispDays + 0.5);
        var s1 = Math.min(state.total - 0.5, msg.endIdx + 0.5);
        Plotly.relayout(gd, { 'xaxis.range': [s0, s1] });
      }
      if (msg.idx >= 0 && msg.idx < state.total) updateInfo(msg.idx);
    }
  });
})();
</script></body></html>"""
    return (tpl.replace("__CSS__", COMMON_CSS)
               .replace("__SYNC_JS__", _shared_sync_js())
               .replace("__CID__", chart_id)
               .replace("__TECH_H__", str(tech_height))
               .replace("__RECS__", rec_json)
               .replace("__FIG__", fig_json)
               .replace("__INIT_DISP__", str(initial_disp_days))
               .replace("__INIT_END__", str(initial_end_idx)))


def get_chip_tab_html(fig_btm: dict, df: pd.DataFrame, chart_id: str, chip_height: int, initial_disp_days: int, initial_end_idx: int, m1_thresh: int = 1000, m2_thresh: int = 400) -> str:
    rec_json = _build_base_records_json(df, False)
    fig_json = fig_btm["chip"].to_json()
    tpl = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>__CSS__</style></head><body>
<div class="frame-root" id="__CID___chip_root">
  <div id="__CID___chip_info" class="pane-info-bar">載入籌碼數據中...</div>
  <div id="__CID___chip_plot" class="touch-plot-box" style="height:__CHIP_H__px;">
    <div id="__CID___chip_vline" class="v-crosshair"></div>
  </div>
</div>
<script>
(function(){
  __SYNC_JS__
  var RECS = __RECS__;
  var FIG = __FIG__;
  var state = { total: RECS.length, focusIdx: __INIT_END__, dispDays: __INIT_DISP__, endIdx: __INIT_END__ };
  var gd = document.getElementById('__CID___chip_plot');
  var infoEl = document.getElementById('__CID___chip_info');
  var vline = document.getElementById('__CID___chip_vline');

  function updateInfo(idx) {
    if (idx < 0 || idx >= RECS.length) return;
    state.focusIdx = idx;
    var r = RECS[idx];
    var m1Txt = (r.m1 !== null && r.m1 !== undefined) ? (r.m1.toFixed(2) + '%') : '-';
    var m2Txt = (r.m2 !== null && r.m2 !== undefined) ? (r.m2.toFixed(2) + '%') : '-';
    var smrTxt = (r.smr !== null && r.smr !== undefined) ? (r.smr.toFixed(2) + '%') : '-';
    infoEl.innerHTML = '<b>' + r.d + '</b> ｜ 外資:<span class="' + clsVal(r.fn) + '">' + fmtSign(r.fn, 0) + '</span>' +
      ' 投信:<span class="' + clsVal(r.tn) + '">' + fmtSign(r.tn, 0) + '</span>' +
      ' 自營:<span class="' + clsVal(r.dn) + '">' + fmtSign(r.dn, 0) + '</span>' +
      ' ｜ 融資:<span class="' + clsVal(r.md) + '">' + fmtSign(r.md, 0) + '</span>(餘' + r.mb.toLocaleString() + ')' +
      ' 融券:<span class="' + clsVal(r.sd) + '">' + fmtSign(r.sd, 0) + '</span>(餘' + r.sb.toLocaleString() + ', 券資比' + smrTxt + ')' +
      ' ｜ ≥__M1__張:<b>' + m1Txt + '</b> ≥__M2__張:<b>' + m2Txt + '</b>';
    placeCrosshair(gd, vline, idx);
  }

  function onFocus(idx, doBroadcast) {
    updateInfo(idx);
    if (doBroadcast) broadcastFocus('__CID__', idx, state.dispDays, state.endIdx);
  }

  Plotly.newPlot(gd, FIG.data, FIG.layout, { displayModeBar: false, responsive: true }).then(function() {
    updateInfo(state.focusIdx);
    bindPaneTouch(gd, gd, state, onFocus, null);
  });

  window.addEventListener('message', function(ev) {
    var msg = ev.data || {};
    if (msg.type === 'MCHART_SYNC_FOCUS') {
      if (msg.dispDays && msg.endIdx >= 0) {
        var s0 = Math.max(-0.5, msg.endIdx - msg.dispDays + 0.5);
        var s1 = Math.min(state.total - 0.5, msg.endIdx + 0.5);
        Plotly.relayout(gd, { 'xaxis.range': [s0, s1] });
      }
      if (msg.idx >= 0 && msg.idx < state.total) updateInfo(msg.idx);
    }
  });
})();
</script></body></html>"""
    return (tpl.replace("__CSS__", COMMON_CSS)
               .replace("__SYNC_JS__", _shared_sync_js())
               .replace("__CID__", chart_id)
               .replace("__CHIP_H__", str(chip_height))
               .replace("__RECS__", rec_json)
               .replace("__FIG__", fig_json)
               .replace("__INIT_DISP__", str(initial_disp_days))
               .replace("__INIT_END__", str(initial_end_idx))
               .replace("__M1__", str(m1_thresh))
               .replace("__M2__", str(m2_thresh)))


def get_broker_tab_html(df: pd.DataFrame, broker_payload: dict, chart_id: str, end_idx: int, disp_days: int = 20, is_mobile: bool = False) -> str:
    dates_list = [d.strftime('%Y-%m-%d') for d in df.index]
    is_index = len(dates_list) == 0 or (df['Turnover_Rate'].max() == 0 and df['Foreign_Net'].abs().max() == 0)
    safe_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}
    tpl = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
__CSS__
.b-wrap { padding: 2px 2px 10px 2px; }
.b-hdr { font-size: 12.5px; color: #1e293b; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 5px; padding: 5px 8px; margin-bottom: 6px; }
.b-sec-title { font-size: 13px; font-weight: 700; color: #0f172a; margin: 10px 0 4px 0; padding-left: 6px; border-left: 3px solid #2563eb; }
.b-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.b-col { flex: 1 1 320px; min-width: 280px; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden; background: #fff; }
.b-col-head { font-size: 12px; font-weight: 700; padding: 5px 8px; background: #f1f5f9; border-bottom: 1px solid #e2e8f0; }
table.b-tbl { width: 100%; border-collapse: collapse; font-size: 11.5px; }
table.b-tbl th { background: #f8fafc; color: #475569; font-weight: 600; padding: 4px 5px; border-bottom: 1px solid #e2e8f0; text-align: right; }
table.b-tbl th:nth-child(1), table.b-tbl td:nth-child(1) { text-align: center; width: 24px; }
table.b-tbl th:nth-child(2), table.b-tbl td:nth-child(2) { text-align: left; }
table.b-tbl td { padding: 4px 5px; border-bottom: 1px solid #f1f5f9; text-align: right; color: #1e293b; }
/* 【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
   修改目的：提高表格內買超紅字 (.val-up) 與賣超綠字 (.val-dn) 的 CSS 選擇器權重並加上 !important。
   防呆防錯原因：先前 table.b-tbl td { color: #1e293b; } 權重高於單純類別 .val-up / .val-dn，導致買賣超欄位全部被覆蓋成黑字。 */
table.b-tbl td.val-up { color: #eb4d4b !important; font-weight: 700 !important; }
table.b-tbl td.val-dn { color: #16a085 !important; font-weight: 700 !important; }
.gov-tag { display: inline-block; font-size: 10px; background: #fef3c7; color: #92400e; border: 1px solid #f59e0b; border-radius: 3px; padding: 0 3px; margin-left: 3px; }
.b-ctrl { display: flex; align-items: center; gap: 8px; background: #f1f5f9; padding: 6px 8px; border-radius: 5px; margin: 10px 0 6px 0; font-size: 12.5px; }
.b-bar { width: 100%; height: 155px; border: 1px solid #e2e8f0; border-radius: 5px; margin-bottom: 6px; }
</style></head><body>
<div class="b-wrap" id="__CID___broker_root">
  <div class="b-hdr" id="__CID___b_hdr">載入分點統計中...</div>
  <div id="__CID___b_tbls"></div>
  <div class="b-ctrl">
    <b>5. 前五大分點每日買賣超柱狀圖區間：</b>
    <select id="__CID___win_sel" style="padding:3px 6px;border-radius:4px;border:1px solid #94a3b8;font-size:12px;">
      <option value="10" selected>前 10 日至關注交易日</option>
      <option value="20">前 20 日至關注交易日</option>
      <option value="60">前 60 日至關注交易日（按需載入）</option>
    </select>
  </div>
  <div id="__CID___b_warn" style="display:none;font-size:12px;color:#b45309;background:#fffbeb;border:1px solid #fcd34d;padding:5px 8px;border-radius:4px;margin-bottom:6px;"></div>
  <div id="__CID___b_bars"></div>
</div>
<script>
(function(){
  var DATES = __DATES__;
  var IS_IDX = __IS_IDX__;
  var PAYLOAD = __BROKER_JSON__;
  var curIdx = __INIT_END__;
  var hdrEl = document.getElementById('__CID___b_hdr');
  var tblsEl = document.getElementById('__CID___b_tbls');
  var selEl = document.getElementById('__CID___win_sel');
  var warnEl = document.getElementById('__CID___b_warn');
  var barsEl = document.getElementById('__CID___b_bars');
  var cfg = { displayModeBar: false, responsive: true };
  var MSG_60D_ON_DEMAND = '近 60 日分點統計採按需載入，請點擊上方「📥 載入近 60 日分點統計與明細」按鈕擷取。';

  function pushH() {
    try {
      var h = document.getElementById('__CID___broker_root').scrollHeight + 16;
      window.parent.postMessage({ isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: Math.max(420, h) }, '*');
    } catch (e) {}
  }

  // 【修訂說明 2026-11-17】【修改目的與防呆防錯原因】：
  // 買超前10名強制顯示紅字與正號(+)，賣超前10名強制顯示綠字與負號(-)，並即時矯正既有雲端快取正負值。
  function makeTbl(title, buyList, sellList, emptyHint) {
    function side(subTitle, rows, isBuySide) {
      var h = '<div class="b-col"><div class="b-col-head" style="color:' + (isBuySide ? '#eb4d4b' : '#16a085') + ';">' + subTitle + '</div>';
      if (!rows || !rows.length) {
        return h + '<div style="padding:10px;font-size:12px;color:#64748b;">' + (emptyHint || '無資料') + '</div></div>';
      }
      h += '<table class="b-tbl"><thead><tr><th>#</th><th>分點名稱</th><th>買進</th><th>賣出</th><th>買賣超</th><th>佔比</th></tr></thead><tbody>';
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var rawNet = Math.abs(Number(r.net || 0));
        var net = isBuySide ? rawNet : -rawNet;
        var cls = isBuySide ? 'val-up' : 'val-dn';
        var netStr = (isBuySide ? '+' : '-') + rawNet.toLocaleString();
        var gov = (r.sys === '八大官股') ? '<span class="gov-tag">官股</span>' : '';
        h += '<tr><td>' + (i + 1) + '</td><td>' + (r.name || '') + gov + '</td>' +
             '<td>' + Number(r.buy || 0).toLocaleString() + '</td>' +
             '<td>' + Number(r.sell || 0).toLocaleString() + '</td>' +
             '<td class="' + cls + '">' + netStr + '</td>' +
             '<td>' + (r.ratio || '-') + '</td></tr>';
      }
      h += '</tbody></table></div>';
      return h;
    }
    return '<div class="b-sec-title">' + title + '</div><div class="b-grid">' +
           side('🔴 買超前 10 名 (張)', buyList, true) +
           side('🟢 賣超前 10 名 (張)', sellList, false) + '</div>';
  }

  function render(idx) {
    if (IS_IDX || !DATES.length) {
      hdrEl.innerHTML = 'ℹ️ 大盤與市場指數無個別券商分點進出資料。';
      tblsEl.innerHTML = '';
      barsEl.innerHTML = '';
      pushH();
      return;
    }
    var safeI = Math.max(0, Math.min(DATES.length - 1, idx));
    curIdx = safeI;
    var dStr = DATES[safeI];
    hdrEl.innerHTML = '<b>關注交易日：' + dStr + '</b> ｜ 券商分點買賣超統計與雲端累積逐日明細（單位：張）';

    var byDate = (PAYLOAD && PAYLOAD.by_date) ? PAYLOAD.by_date : {};
    var dayObj = byDate[dStr];
    if (!dayObj) {
      var keys = Object.keys(byDate).sort();
      if (keys.length) dayObj = byDate[keys[keys.length - 1]];
    }
    if (!dayObj) {
      tblsEl.innerHTML = '<div style="padding:12px;color:#64748b;font-size:12.5px;">尚無該交易日分點統計資料，可勾選側邊欄「強制更新」重新擷取。</div>';
      barsEl.innerHTML = '';
      pushH();
      return;
    }

    var w1 = dayObj.w1 || {}, w10 = dayObj.w10 || {}, w20 = dayObj.w20 || {}, w60 = dayObj.w60 || {};
    var has60 = Boolean((w60.buy && w60.buy.length) || (w60.sell && w60.sell.length));
    tblsEl.innerHTML =
      makeTbl('1. 當日分點統計買賣超各前十名（' + (w1.range_label || dStr) + '）', w1.buy, w1.sell) +
      makeTbl('2. 前 10 日至關注交易日分點統計買賣超各前十名（' + (w10.range_label || '') + '）', w10.buy, w10.sell) +
      makeTbl('3. 前 20 日至關注交易日分點統計買賣超各前十名（' + (w20.range_label || '') + '）', w20.buy, w20.sell) +
      makeTbl('4. 前 60 日至關注交易日分點統計買賣超各前十名（' + (has60 ? (w60.range_label || '') : '按需載入') + '）', w60.buy, w60.sell, MSG_60D_ON_DEMAND);

    renderBars(dayObj);
    pushH();
  }

  // 【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
  // 1. 修改目的：
  //    (a) data_fetcher.py 與 storage.py 已統一以「買進 - 賣出」儲存真實淨買賣超，前端直接依真實正負值繪製（買超 >= 0 紅柱 #eb4d4b 向上、賣超 < 0 綠柱 #16a085 向下）。
  //    (b) X 軸刻度比照主圖規則，僅在每月第一個交易日顯示月份（如「10月」、「11月」），移除冗餘年份與日期，避免 X 軸文字擁擠重疊。
  // 2. 防呆防錯原因：移除先前針對賣超分點強制乘以 -1 的權宜反轉，避免真實買超日遭誤反轉成綠柱；使用 monthTicksVals / monthTicksText 精準對應 category 型態之 xArr 日期字串。
  function renderBars(dayObj) {
    var wKey = 'w' + (selEl.value || '10');
    var wObj = dayObj[wKey] || {};
    var buyS = wObj.top5_buy_series || [];
    var sellS = wObj.top5_sell_series || [];
    if (!buyS.length && !sellS.length) {
      warnEl.style.display = 'block';
      warnEl.textContent = (wKey === 'w60') ? MSG_60D_ON_DEMAND : '⚠️ 此區間尚無累積逐日明細可繪製柱狀圖，請點擊「查詢」或勾選「強制更新」以累積雲端分點逐日明細。';
      barsEl.innerHTML = '';
      return;
    }
    warnEl.style.display = 'none';
    var html = '<div class="b-grid"><div class="b-col"><div class="b-col-head" style="color:#eb4d4b;">🔴 買超前五大分點每日買賣超</div><div id="__CID___bar_buy"></div></div>' +
               '<div class="b-col"><div class="b-col-head" style="color:#16a085;">🟢 賣超前五大分點每日買賣超</div><div id="__CID___bar_sell"></div></div></div>';
    barsEl.innerHTML = html;

    function plotSide(containerId, list, isBuyGroup) {
      var host = document.getElementById(containerId);
      if (!host) return;
      host.innerHTML = '';
      for (var i = 0; i < list.length; i++) {
        var item = list[i];
        var div = document.createElement('div');
        div.className = 'b-bar';
        host.appendChild(div);
        var xArr = item.dates || [];
        var rawYArr = item.nets || [];
        var yArr = rawYArr.map(function(v) { return Number(v || 0); });
        var barColors = yArr.map(function(v) { return v >= 0 ? '#eb4d4b' : '#16a085'; });

        // 僅於每月第一個交易日顯示月份（例如：10月、11月），不需要年份與日
        var monthTicksVals = [];
        var monthTicksText = [];
        var lastYm = '';
        for (var k = 0; k < xArr.length; k++) {
          var dStr = String(xArr[k] || '');
          if (dStr.length >= 7) {
            var ym = dStr.slice(0, 7);
            if (ym !== lastYm) {
              lastYm = ym;
              var mNum = parseInt(dStr.slice(5, 7), 10);
              monthTicksVals.push(dStr);
              monthTicksText.push((isNaN(mNum) ? dStr.slice(5, 7) : String(mNum)) + '月');
            }
          }
        }

        var rawTot = Math.abs(Number(item.total_net || 0));
        var signedTot = isBuyGroup ? rawTot : -rawTot;
        var titleColor = signedTot >= 0 ? '#eb4d4b' : '#16a085';
        var signPrefix = signedTot > 0 ? '+' : (signedTot < 0 ? '-' : '');
        var titleTxt = (i + 1) + '. ' + item.name + ' (區間合計: ' + signPrefix + rawTot.toLocaleString() + '張)';
        Plotly.newPlot(div, [{
          x: xArr,
          y: yArr,
          type: 'bar',
          marker: { color: barColors },
          hovertemplate: '%{x}<br>買賣超: %{y:+,} 張<extra></extra>'
        }], {
          title: { text: titleTxt, font: { size: 11.5, color: titleColor }, x: 0.02 },
          margin: { l: 42, r: 10, t: 26, b: 22 },
          height: 150,
          template: 'plotly_white',
          xaxis: {
            type: 'category',
            tickmode: 'array',
            tickvals: monthTicksVals,
            ticktext: monthTicksText,
            tickangle: 0,
            tickfont: { size: 10 }
          },
          yaxis: { tickfont: { size: 10 }, zeroline: true, zerolinecolor: '#94a3b8' }
        }, cfg);
      }
    }
    plotSide('__CID___bar_buy', buyS, true);
    plotSide('__CID___bar_sell', sellS, false);
  }

  selEl.addEventListener('change', function() { render(curIdx); });
  render(curIdx);

  window.addEventListener('message', function(ev) {
    var msg = ev.data || {};
    if (msg.type === 'MCHART_SYNC_FOCUS' && typeof msg.idx === 'number') {
      render(msg.idx);
    }
  });
})();
</script></body></html>"""
    return (tpl.replace("__CSS__", COMMON_CSS)
               .replace("__CID__", chart_id)
               .replace("__DATES__", json.dumps(dates_list))
               .replace("__IS_IDX__", "true" if is_index else "false")
               .replace("__BROKER_JSON__", json.dumps(safe_payload, ensure_ascii=False))
               .replace("__INIT_END__", str(end_idx)))
# EOF frontend.py
