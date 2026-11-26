"""
frontend.py - 前端 HTML/CSS 渲染模組（主圖、指標、籌碼與分點總入口）
(依邏輯職責拆分為 frnt_broker.py 與本主圖/指標/籌碼渲染總入口，維持 100% 向後相容匯出)
版本: 202611262040
"""

import json
import pandas as pd

MODULE_NAME = "frontend"
MODULE_VERSION = "202611262040"

from frnt_broker import (
    COMMON_CSS,
    BROKER_SHARED_CSS,
    _extract_dates_list,
    _detect_gov_index_unit,
    get_broker_stats_tab_html,
    get_broker_daily_tab_html,
    get_broker_tab_html,
)


def get_legend_html(version_tag: str = "202611262040") -> str:
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


def _series_to_json_nullable(df: pd.DataFrame, col: str, n_pts: int) -> str:
    if col not in df.columns:
        return json.dumps([None] * n_pts)
    return json.dumps([None if pd.isna(v) else float(v) for v in df[col].tolist()])


SHARED_JS_HELPERS = """
function broadcastToSiblings(p){try{if(window.parent&&window.parent.frames){for(var i=0;i<window.parent.frames.length;i++){if(window.parent.frames[i]!==window)window.parent.frames[i].postMessage(p,'*');}}}catch(e){}}
function fmtNum(v,d){if(v===null||v===undefined||isNaN(v))return'-';return Number(v).toFixed(d!==undefined?d:2);}
function fmtBias(v){if(v===null||v===undefined||isNaN(v))return'-';var n=Number(v),s=(n>0?'+':'')+n.toFixed(2)+'%';return n>0?'<span class="val-up">'+s+'</span>':(n<0?'<span class="val-dn">'+s+'</span>':s);}
function fmtDiff(v,d){if(v===null||v===undefined||isNaN(v))return'-';var n=Number(v),s=n.toFixed(d!==undefined?d:0);return n>0?'<span class="val-up">+'+s+'</span>':(n<0?'<span class="val-dn">'+s+'</span>':s);}
"""


def get_top_chart_html(fig_top, df: pd.DataFrame, chart_id: str, top_height: int = 270, initial_disp_days: int = 20, initial_end_idx: int = None) -> str:
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx
    dates_list = _extract_dates_list(df)
    vols_list = df['Volume_Sheets'].tolist() if 'Volume_Sheets' in df.columns else (df['Volume'] / 1000.0).tolist()
    to_col = 'Turnover_Rate' if 'Turnover_Rate' in df.columns else ('TurnoverRate' if 'TurnoverRate' in df.columns else None)
    turnover_list = df[to_col].fillna(0).tolist() if to_col else [0] * n_pts

    tpl = COMMON_CSS + """
<div class="frame-root" id="__CID___root">
    <div id="__CID___info1" class="pane-info-bar" style="margin-bottom:2px;">正在載入...</div>
    <div id="__CID___top" class="touch-plot-box" style="height:__TOP_H__px;">
        <div id="__CID___line_x" class="sync-crosshair-line"></div>
        <div id="__CID___line_y" class="sync-price-line"></div>
    </div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>(function(){__HELPERS__
var pTop=__P_TOP__,dates=__DATES__,opens=__OPENS__,highs=__HIGHS__,lows=__LOWS__,closes=__CLOSES__,vols=__VOLS__;
var ma5s=__MA5S__,ma20s=__MA20S__,ma60s=__MA60S__,turnovers=__TURNOVERS__;
var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
var rootEl=document.getElementById('__CID___root'),elTop=document.getElementById('__CID___top'),info1=document.getElementById('__CID___info1');
var lineX=document.getElementById('__CID___line_x'),lineY=document.getElementById('__CID___line_y');

function pushTopH(){
    if(!rootEl)return;
    var h=Math.ceil(rootEl.scrollHeight)+8;
    if(window.parent&&window.parent!==window){
        window.parent.postMessage({isStreamlitMessage:true,type:"streamlit:setFrameHeight",height:h},"*");
    }
}

function calcBounds(r0,r1){var s=Math.max(0,Math.floor(r0)),e=Math.min(totalPoints-1,Math.ceil(r1)),pMin=Infinity,pMax=-Infinity,vMax=0;
    for(var i=s;i<=e;i++){var h=Number(highs[i]),l=Number(lows[i]);
        if(!isNaN(h)&&h>0)pMax=Math.max(pMax,h);if(!isNaN(l)&&l>0)pMin=Math.min(pMin,l);
        [ma5s[i],ma20s[i],ma60s[i]].forEach(function(m){var v=Number(m);if(!isNaN(v)&&v>0){pMax=Math.max(pMax,v);pMin=Math.min(pMin,v);}});
        var vol=Number(vols[i]);if(!isNaN(vol)&&vol>0)vMax=Math.max(vMax,vol);
    }
    if(pMin===Infinity){pMin=0;pMax=100;}
    var pad=(pMax>pMin)?(pMax-pMin)*0.10:2.0;
    var vTop=vMax>0?vMax*1.25:1000;
    var vBot=vMax>0?-vMax*0.06:-50;
    return{p:[pMin-pad,pMax+pad],v:[vBot,vTop]};
}

function renderInfo(idx){if(idx<0||idx>=totalPoints)return;
    var d=dates[idx],c=closes[idx],o=opens[idx],h=highs[idx],l=lows[idx],prev=idx>0?closes[idx-1]:o;
    var diff=c-prev,pct=prev?(diff/prev*100):0,cls=diff>0?'val-up':(diff<0?'val-dn':'');
    info1.innerHTML='<span class="tag-lbl"><b>'+d+'</b></span>開:<span class="'+(o>prev?'val-up':(o<prev?'val-dn':''))+'">'+fmtNum(o)+'</span> 高:<span class="'+(h>prev?'val-up':(h<prev?'val-dn':''))+'">'+fmtNum(h)+'</span> 低:<span class="'+(l>prev?'val-up':(l<prev?'val-dn':''))+'">'+fmtNum(l)+'</span> 收:<span class="'+cls+'">'+fmtNum(c)+' ('+(diff>0?'+':'')+fmtNum(diff)+', '+(pct>0?'+':'')+fmtNum(pct)+'%)</span> 量:'+fmtNum(vols[idx],0)+'張 <span class="tag-lbl"><b>換手:'+fmtNum(turnovers[idx])+'%</b></span> MA5:'+fmtNum(ma5s[idx])+' MA20:'+fmtNum(ma20s[idx])+' MA60:'+fmtNum(ma60s[idx]);
    pushTopH();
}

var b0=calcBounds(currentR0,currentR1);
pTop.layout.height=Number(__TOP_H__)||296;
pTop.layout.xaxis.range=[currentR0,currentR1];if(pTop.layout.xaxis2)pTop.layout.xaxis2.range=[currentR0,currentR1];
pTop.layout.yaxis.range=b0.p;if(pTop.layout.yaxis2){pTop.layout.yaxis2.range=b0.v;pTop.layout.yaxis2.tick0=0;}
Plotly.newPlot(elTop,pTop.data,pTop.layout,{responsive:true,displayModeBar:false,scrollZoom:false}).then(function(){renderInfo(initEnd);pushTopH();
    if(typeof ResizeObserver!=='undefined'&&rootEl){
        var rzTimer=null;
        new ResizeObserver(function(){
            pushTopH();
            clearTimeout(rzTimer);
            rzTimer=setTimeout(function(){if(elTop&&elTop._fullLayout)Plotly.Plots.resize(elTop);},50);
        }).observe(rootEl);
    }
    elTop.on('plotly_relayout',function(ed){if(isUpdating)return;
        var r0=ed['xaxis.range[0]']??ed['xaxis2.range[0]']??(ed['xaxis.range']?ed['xaxis.range'][0]:null);
        var r1=ed['xaxis.range[1]']??ed['xaxis2.range[1]']??(ed['xaxis.range']?ed['xaxis.range'][1]:null);
        if(r0===null||r1===null||(Math.abs(r0-currentR0)<0.001&&Math.abs(r1-currentR1)<0.001))return;
        isUpdating=true;var span=r1-r0,maxB=(totalPoints-1)+0.5;
        if(r1>maxB){r1=maxB;r0=r1-span;}currentR0=r0;currentR1=r1;
        var vb=calcBounds(r0,r1);broadcastToSiblings({type:'MCHART_SYNC_XRANGE',r0:r0,r1:r1});
        Plotly.relayout(elTop,{'xaxis.range':[r0,r1],'xaxis2.range':[r0,r1],'yaxis.range':vb.p,'yaxis2.range':vb.v}).finally(function(){setTimeout(function(){isUpdating=false;},8);});
    });
    window.addEventListener('message',function(ev){var msg=ev.data||{};
        if(msg.type==='MCHART_SYNC_XRANGE'&&!isUpdating){isUpdating=true;currentR0=msg.r0;currentR1=msg.r1;var vb=calcBounds(currentR0,currentR1);
            Plotly.relayout(elTop,{'xaxis.range':[currentR0,currentR1],'xaxis2.range':[currentR0,currentR1],'yaxis.range':vb.p,'yaxis2.range':vb.v}).finally(function(){setTimeout(function(){isUpdating=false;},8);});
        }else if(msg.type==='MCHART_SYNC_FOCUS'&&msg.idx>=0)renderInfo(msg.idx);
    });
    function onMove(e){var cx=(e.touches&&e.touches.length>0)?e.touches[0].clientX:e.clientX;if(cx===undefined)return;
        var rect=elTop.getBoundingClientRect(),relX=cx-rect.left,xa=elTop._fullLayout?elTop._fullLayout.xaxis:null,ya=elTop._fullLayout?elTop._fullLayout.yaxis:null;
        if(!xa||typeof xa.p2c!=='function')return;
        var pL=xa._offset??80,pLen=xa._length??(rect.width-pL-15);if(relX<pL||relX>pL+pLen)return;
        var idx=Math.round(xa.p2c(relX-pL));
        if(idx>=0&&idx<totalPoints){renderInfo(idx);lineX.style.left=(xa.c2p(idx)+pL)+'px';lineX.style.display='block';
            if(ya&&typeof ya.c2p==='function'&&closes[idx]!=null){lineY.style.top=(ya.c2p(closes[idx])+(ya._offset||0))+'px';lineY.style.display='block';}
            broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:idx,showLine:true});
        }
    }
    function onLeave(){lineX.style.display='none';lineY.style.display='none';broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:-1,showLine:false});}
    elTop.addEventListener('mousemove',onMove);elTop.addEventListener('touchmove',onMove,{passive:true});
    elTop.addEventListener('touchstart',onMove,{passive:true});elTop.addEventListener('mouseleave',onLeave);
});
})();</script>"""
    return (tpl.replace("__CID__", chart_id).replace("__HELPERS__", SHARED_JS_HELPERS).replace("__TOP_H__", str(top_height))
            .replace("__P_TOP__", fig_top.to_json()).replace("__DATES__", json.dumps(dates_list))
            .replace("__OPENS__", json.dumps(df['Open'].tolist())).replace("__HIGHS__", json.dumps(df['High'].tolist()))
            .replace("__LOWS__", json.dumps(df['Low'].tolist())).replace("__CLOSES__", json.dumps(df['Close'].tolist()))
            .replace("__VOLS__", json.dumps(vols_list))
            .replace("__MA5S__", json.dumps(df['MA5'].fillna(0).tolist() if 'MA5' in df.columns else [0] * n_pts))
            .replace("__MA20S__", json.dumps(df['MA20'].fillna(0).tolist() if 'MA20' in df.columns else [0] * n_pts))
            .replace("__MA60S__", json.dumps(df['MA60'].fillna(0).tolist() if 'MA60' in df.columns else [0] * n_pts))
            .replace("__TURNOVERS__", json.dumps(turnover_list))
            .replace("__DISP_DAYS__", str(initial_disp_days)).replace("__INIT_END__", str(end_idx))
            )


def get_tech_tab_html(fig_btm, df: pd.DataFrame, chart_id: str, tech_height: int = 540, initial_disp_days: int = 20, initial_end_idx: int = None) -> str:
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：於指標圖表容器（`#__CID___tech`）下方複製渲染一份底部資訊條（`#__CID___info_tech_btm`），
       讓手機直向畫面捲動至最下方指標時仍可直接檢視 KD / OBV / MACD / 乖離率即時數值。
    2. 防呆防錯原因：於 `renderInfo(idx)` 同步寫入頂部與底部資訊條，確保滑動十字準線與跨圖同步時上下完全一致。
    """
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx
    dates_list = _extract_dates_list(df)
    fig_tech = fig_btm["tech"] if isinstance(fig_btm, dict) and "tech" in fig_btm else getattr(fig_btm, "_fig_tech", fig_btm)

    tpl = COMMON_CSS + """
<div class="frame-root" id="__CID___tech_root">
    <div id="__CID___info_tech" class="pane-info-bar" style="margin-bottom:3px;">正在載入指標...</div>
    <div id="__CID___tech" class="touch-plot-box" style="height:__TECH_H__px;"><div id="__CID___line_tech" class="sync-crosshair-line"></div></div>
    <div id="__CID___info_tech_btm" class="pane-info-bar" style="margin-top:3px;">正在載入指標...</div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>(function(){__HELPERS__
var pTech=__P_TECH__,dates=__DATES__,ks=__KS__,ds=__DS__,difs=__DIFS__,macds=__MACDS__,oscs=__OSCS__,obvs=__OBVS__,obvMas=__OBVMAS__;
var bias20s=__BIAS20__,bias120s=__BIAS120__,bias240s=__BIAS240__,bias1200s=__BIAS1200__;
var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
var elTech=document.getElementById('__CID___tech'),infoTech=document.getElementById('__CID___info_tech'),infoTechBtm=document.getElementById('__CID___info_tech_btm'),lineTech=document.getElementById('__CID___line_tech');

function renderInfo(idx){if(idx<0||idx>=totalPoints)return;
    var d=dates[idx],oscClass=oscs[idx]>0?'val-up':(oscs[idx]<0?'val-dn':'');
    var htmlStr='<div><span class="tag-lbl"><b>'+d+'</b></span> <span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:'+fmtNum(ks[idx],1)+'</span> <span style="color:#3498db;">D:'+fmtNum(ds[idx],1)+'</span> | <span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:'+fmtNum(obvs[idx],0)+'</span> <span style="color:#8e44ad;">MA20:'+fmtNum(obvMas[idx],0)+'</span></div><div><span class="tag-lbl"><b>MACD('+d+')</b></span><span style="color:#f39c12;">DIF:'+fmtNum(difs[idx])+'</span> <span style="color:#2980b9;">MACD:'+fmtNum(macds[idx])+'</span> OSC:<span class="'+oscClass+'">'+fmtNum(oscs[idx])+'</span> | <span class="tag-lbl"><b>乖離率</b></span><span style="color:#e67e22;">20日:</span>'+fmtBias(bias20s[idx])+' <span style="color:#2980b9;">120日:</span>'+fmtBias(bias120s[idx])+' <span style="color:#8e44ad;">240日:</span>'+fmtBias(bias240s[idx])+' <span style="color:#e74c3c;">1200日:</span>'+fmtBias(bias1200s[idx])+'</div>';
    if(infoTech)infoTech.innerHTML=htmlStr;
    if(infoTechBtm)infoTechBtm.innerHTML=htmlStr;
}

for(var r=1;r<=4;r++){var kt=r===1?'xaxis':'xaxis'+r;if(pTech.layout&&pTech.layout[kt])pTech.layout[kt].range=[currentR0,currentR1];}
Plotly.newPlot(elTech,pTech.data,pTech.layout,{responsive:true,displayModeBar:false,scrollZoom:false}).then(function(){renderInfo(initEnd);
    elTech.on('plotly_relayout',function(ed){if(isUpdating)return;var r0=null,r1=null;
        for(var k=1;k<=4;k++){var p=k===1?'xaxis':'xaxis'+k;if(ed[p+'.range[0]']!==undefined)r0=ed[p+'.range[0]'];if(ed[p+'.range[1]']!==undefined)r1=ed[p+'.range[1]'];}
        if(r0===null||r1===null||(Math.abs(r0-currentR0)<0.001&&Math.abs(r1-currentR1)<0.001))return;
        isUpdating=true;var span=r1-r0,maxB=(totalPoints-1)+0.5;
        if(r1>maxB){r1=maxB;r0=r1-span;}currentR0=r0;currentR1=r1;
        var upd={};for(var i=1;i<=4;i++)upd[(i===1?'xaxis':'xaxis'+i)+'.range']=[r0,r1];
        broadcastToSiblings({type:'MCHART_SYNC_XRANGE',r0:r0,r1:r1});
        Plotly.relayout(elTech,upd).finally(function(){setTimeout(function(){isUpdating=false;},8);});
    });
    window.addEventListener('message',function(ev){var msg=ev.data||{};
        if(msg.type==='MCHART_SYNC_XRANGE'&&!isUpdating){isUpdating=true;currentR0=msg.r0;currentR1=msg.r1;
            var upd={};for(var i=1;i<=4;i++)upd[(i===1?'xaxis':'xaxis'+i)+'.range']=[currentR0,currentR1];
            Plotly.relayout(elTech,upd).finally(function(){setTimeout(function(){isUpdating=false;},8);});
        }else if(msg.type==='MCHART_SYNC_FOCUS'){if(msg.showLine&&msg.idx>=0){renderInfo(msg.idx);var xa=elTech._fullLayout?elTech._fullLayout.xaxis:null;if(xa&&typeof xa.c2p==='function'){lineTech.style.left=(xa.c2p(msg.idx)+(xa._offset||80))+'px';lineTech.style.display='block';}}
            else lineTech.style.display='none';
        }
    });
    function onMove(e){var cx=(e.touches&&e.touches.length>0)?e.touches[0].clientX:e.clientX;if(cx===undefined)return;
        var rect=elTech.getBoundingClientRect(),relX=cx-rect.left,xa=elTech._fullLayout?elTech._fullLayout.xaxis:null;
        if(!xa||typeof xa.p2c!=='function')return;var pL=xa._offset??80,pLen=xa._length??(rect.width-pL-15);if(relX<pL||relX>pL+pLen)return;
        var idx=Math.round(xa.p2c(relX-pL));
        if(idx>=0&&idx<totalPoints){renderInfo(idx);lineTech.style.left=(xa.c2p(idx)+pL)+'px';lineTech.style.display='block';broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:idx,showLine:true});}
    }
    function onLeave(){lineTech.style.display='none';broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:-1,showLine:false});}
    elTech.addEventListener('mousemove',onMove);elTech.addEventListener('touchmove',onMove,{passive:true});
    elTech.addEventListener('touchstart',onMove,{passive:true});elTech.addEventListener('mouseleave',onLeave);
});
})();</script>"""
    return (tpl.replace("__CID__", chart_id).replace("__HELPERS__", SHARED_JS_HELPERS).replace("__TECH_H__", str(tech_height))
            .replace("__P_TECH__", fig_tech.to_json()).replace("__DATES__", json.dumps(dates_list))
            .replace("__KS__", json.dumps(df['K'].fillna(0).tolist() if 'K' in df.columns else [0] * n_pts))
            .replace("__DS__", json.dumps(df['D'].fillna(0).tolist() if 'D' in df.columns else [0] * n_pts))
            .replace("__DIFS__", json.dumps(df['DIF'].fillna(0).tolist() if 'DIF' in df.columns else [0] * n_pts))
            .replace("__MACDS__", json.dumps(df['MACD'].fillna(0).tolist() if 'MACD' in df.columns else [0] * n_pts))
            .replace("__OSCS__", json.dumps(df['OSC'].fillna(0).tolist() if 'OSC' in df.columns else [0] * n_pts))
            .replace("__OBVS__", json.dumps(df['OBV'].fillna(0).tolist() if 'OBV' in df.columns else [0] * n_pts))
            .replace("__OBVMAS__", json.dumps(df['OBV_MA20'].fillna(0).tolist() if 'OBV_MA20' in df.columns else [0] * n_pts))
            .replace("__BIAS20__", _series_to_json_nullable(df, 'BIAS_20', n_pts))
            .replace("__BIAS120__", _series_to_json_nullable(df, 'BIAS_120', n_pts))
            .replace("__BIAS240__", _series_to_json_nullable(df, 'BIAS_240', n_pts))
            .replace("__BIAS1200__", _series_to_json_nullable(df, 'BIAS_1200', n_pts))
            .replace("__DISP_DAYS__", str(initial_disp_days)).replace("__INIT_END__", str(end_idx))
            )


def get_chip_tab_html(fig_btm, df: pd.DataFrame, chart_id: str, chip_height: int = 780, initial_disp_days: int = 20, initial_end_idx: int = None, m1_thresh: int = 1000, m2_thresh: int = 400) -> str:
    """
    【修訂說明 2026-11-26】【修改目的與防呆防錯原因】：
    1. 修改目的：於籌碼圖表容器（`#__CID___chip`，即 `≥400` 大戶子圖最下方）緊接複製渲染一組底部雙列資訊條
       （`#__CID___info_ms_btm` 資券與 `#__CID___info_chip_btm` 法人集保），解決手機直向畫面捲動至最底部檢視大戶圖表時
       頂部資訊條捲出視窗外無法檢視之問題。
    2. 防呆防錯原因：於 `renderInfo(idx)` 同時更新頂部與底部兩組 DOM 元素，支援個股、加權指數（`^TWII`）與櫃買指數（`^TWOII`）全模式。
    """
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx
    dates_list = _extract_dates_list(df)
    fig_chip = fig_btm["chip"] if isinstance(fig_btm, dict) and "chip" in fig_btm else getattr(fig_btm, "_fig_chip", fig_btm)

    fig_h = getattr(getattr(fig_chip, "layout", None), "height", None)
    resolved_chip_h = int(fig_h) if fig_h else int(chip_height)

    cid_upper = str(chart_id).upper()
    has_short_maint = ('Short_Maint_Pct' in df.columns and not df['Short_Maint_Pct'].dropna().empty)
    no_inst_flow = (
        ('Foreign_Net' not in df.columns or (df['Foreign_Net'].fillna(0) == 0).all())
        and ('Trust_Net' not in df.columns or (df['Trust_Net'].fillna(0) == 0).all())
        and ('Dealer_Net' not in df.columns or (df['Dealer_Net'].fillna(0) == 0).all())
    )
    has_money_bal = ('Margin_Money_Bal' in df.columns and (df['Margin_Money_Bal'].fillna(0) != 0).any())
    zero_margin_bal = ('Margin_Bal' not in df.columns or (df['Margin_Bal'].fillna(0) == 0).all())
    is_twoii = ("^TWOII" in cid_upper) or (has_short_maint and no_inst_flow and has_money_bal and zero_margin_bal)
    is_tw_index = ("^TWII" in cid_upper) or is_twoii or (has_short_maint and no_inst_flow and zero_margin_bal)

    tpl = COMMON_CSS + """
<div class="frame-root" id="__CID___chip_root">
    <div id="__CID___info_ms" class="pane-info-bar" style="margin-bottom:3px;">正在載入資券...</div>
    <div id="__CID___info_chip" class="pane-info-bar" style="margin-bottom:3px;">正在載入法人集保...</div>
    <div id="__CID___chip" class="touch-plot-box" style="height:__CHIP_H__px;"><div id="__CID___line_chip" class="sync-crosshair-line"></div></div>
    <div id="__CID___info_ms_btm" class="pane-info-bar" style="margin-top:3px; margin-bottom:3px;">正在載入資券...</div>
    <div id="__CID___info_chip_btm" class="pane-info-bar" style="margin-bottom:2px;">正在載入法人集保...</div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>(function(){__HELPERS__
var pChip=__P_CHIP__,dates=__DATES__,foreigns=__FOREIGNS__,trusts=__TRUSTS__,dealers=__DEALERS__,mDiffs=__MDIFFS__,sDiffs=__SDIFFS__,rat=__RATIOS__;
var mMaints=__MMAINTS__,mMaints60d=__MMAINTS60D__,sMaints=__SMAINTS__,mMoneyDiffs=__MMONEY__,isTwIndex=__IS_TW_INDEX__,isTwoii=__IS_TWOII__;
var m1_pcts=__M1PCTS__,m2_pcts=__M2PCTS__,m1_thresh=__M1TH__,m2_thresh=__M2TH__;
var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
var elChip=document.getElementById('__CID___chip'),infoMs=document.getElementById('__CID___info_ms'),infoChip=document.getElementById('__CID___info_chip');
var infoMsBtm=document.getElementById('__CID___info_ms_btm'),infoChipBtm=document.getElementById('__CID___info_chip_btm'),lineChip=document.getElementById('__CID___line_chip');

function renderInfo(idx){if(idx<0||idx>=totalPoints)return;
    var d=dates[idx],mT=mDiffs[idx]!=null?Number(mDiffs[idx])/1000.0:null,sT=sDiffs[idx]!=null?Number(sDiffs[idx])/1000.0:null;
    var msHtml='',chipHtml='';
    if(isTwoii){
        msHtml='<span class="tag-lbl"><b>上櫃資券('+d+')</b></span>融券:'+fmtDiff(sT,2)+'千張 ｜ <b>融資金額:</b>'+fmtDiff(mMoneyDiffs[idx],2)+'億 ｜ <span style="color:#e67e22;font-weight:bold;">融資維持率:'+fmtNum(mMaints[idx])+'%</span> <span style="color:#8e44ad;font-weight:bold;">融券維持率:'+fmtNum(sMaints[idx])+'%</span>';
        chipHtml='<span class="tag-lbl"><b>櫃買指數('+d+')</b></span>櫃買指數顯示上櫃融券(千張)、上櫃融資金額(億)及融資/融券維持率（八大官股進出請切換至「分點統計／分點日況」頁籤）';
    }else if(isTwIndex){
        msHtml='<span class="tag-lbl"><b>上市資券[千張]('+d+')</b></span>融資:'+fmtDiff(mT,2)+' 融券:'+fmtDiff(sT,2)+' ｜ <b>融資金額:</b>'+fmtDiff(mMoneyDiffs[idx],2)+'億 ｜ <span style="color:#e67e22;font-weight:bold;">融資維持率:'+fmtNum(mMaints[idx])+'%</span> <span style="color:#8e44ad;font-weight:bold;">融券維持率:'+fmtNum(sMaints[idx])+'%</span>';
        chipHtml='<span class="tag-lbl"><b>大盤指數('+d+')</b></span>加權指數顯示上市資券(千張)、上市融資金額(億)及融資/融券維持率（八大官股進出請切換至「分點統計／分點日況」頁籤）';
    }else{
        msHtml='<span class="tag-lbl"><b>資券[千張]('+d+')</b></span>融資:'+fmtDiff(mT,3)+' 融券:'+fmtDiff(sT,3)+' <span style="color:#e67e22;font-weight:bold;">券資比:'+fmtNum(rat[idx])+'%</span> <span style="color:#2980b9;font-weight:bold;">預估融資維持率:'+fmtNum(mMaints[idx])+'%</span> <span style="color:#16a085;font-weight:bold;">季融資維持率:'+fmtNum(mMaints60d[idx])+'%</span>';
        chipHtml='<span class="tag-lbl"><b>法人集保('+d+')</b></span>外資:'+fmtDiff(foreigns[idx],0)+' 投信:'+fmtDiff(trusts[idx],0)+' 自營:'+fmtDiff(dealers[idx],0)+' | ≥'+m1_thresh+'張: '+fmtNum(m1_pcts[idx])+'% ≥'+m2_thresh+'張: '+fmtNum(m2_pcts[idx])+'%';
    }
    if(infoMs)infoMs.innerHTML=msHtml;
    if(infoChip)infoChip.innerHTML=chipHtml;
    if(infoMsBtm)infoMsBtm.innerHTML=msHtml;
    if(infoChipBtm)infoChipBtm.innerHTML=chipHtml;
}

function getAllXAxisKeys(){
    var keys=[];
    if(elChip&&elChip._fullLayout){
        Object.keys(elChip._fullLayout).forEach(function(k){if(/^xaxis\d*$/.test(k))keys.push(k);});
    }
    if(keys.length===0&&pChip&&pChip.layout){
        Object.keys(pChip.layout).forEach(function(k){if(/^xaxis\d*$/.test(k))keys.push(k);});
    }
    return keys.length>0?keys:['xaxis','xaxis2','xaxis3','xaxis4','xaxis5','xaxis6','xaxis7','xaxis8'];
}

function buildRangeUpdate(r0,r1){
    var upd={},keys=getAllXAxisKeys();
    for(var i=0;i<keys.length;i++){upd[keys[i]+'.range']=[r0,r1];}
    return upd;
}

var initKeys=getAllXAxisKeys();
for(var c=0;c<initKeys.length;c++){if(pChip.layout&&pChip.layout[initKeys[c]])pChip.layout[initKeys[c]].range=[currentR0,currentR1];}
Plotly.newPlot(elChip,pChip.data,pChip.layout,{responsive:true,displayModeBar:false,scrollZoom:false}).then(function(){renderInfo(initEnd);
    elChip.on('plotly_relayout',function(ed){if(isUpdating)return;var r0=null,r1=null,keys=getAllXAxisKeys();
        for(var k=0;k<keys.length;k++){var p=keys[k];
            if(ed[p+'.range[0]']!==undefined)r0=ed[p+'.range[0]'];
            if(ed[p+'.range[1]']!==undefined)r1=ed[p+'.range[1]'];
            if(Array.isArray(ed[p+'.range'])&&ed[p+'.range'].length===2){r0=ed[p+'.range'][0];r1=ed[p+'.range'][1];}
        }
        if(r0===null||r1===null||(Math.abs(r0-currentR0)<0.0005&&Math.abs(r1-currentR1)<0.0005))return;
        isUpdating=true;var span=r1-r0,maxB=(totalPoints-1)+0.5;
        if(r1>maxB){r1=maxB;r0=r1-span;}currentR0=r0;currentR1=r1;
        broadcastToSiblings({type:'MCHART_SYNC_XRANGE',r0:r0,r1:r1});
        Plotly.relayout(elChip,buildRangeUpdate(r0,r1)).finally(function(){setTimeout(function(){isUpdating=false;},5);});
    });
    window.addEventListener('message',function(ev){var msg=ev.data||{};
        if(msg.type==='MCHART_SYNC_XRANGE'&&!isUpdating){
            if(Math.abs(msg.r0-currentR0)<0.0005&&Math.abs(msg.r1-currentR1)<0.0005)return;
            isUpdating=true;currentR0=msg.r0;currentR1=msg.r1;
            Plotly.relayout(elChip,buildRangeUpdate(currentR0,currentR1)).finally(function(){setTimeout(function(){isUpdating=false;},5);});
        }else if(msg.type==='MCHART_SYNC_FOCUS'){if(msg.showLine&&msg.idx>=0){renderInfo(msg.idx);var xa=elChip._fullLayout?elChip._fullLayout.xaxis:null;if(xa&&typeof xa.c2p==='function'){lineChip.style.left=(xa.c2p(msg.idx)+(xa._offset||80))+'px';lineChip.style.display='block';}}
            else lineChip.style.display='none';
        }
    });
    function onMove(e){var cx=(e.touches&&e.touches.length>0)?e.touches[0].clientX:e.clientX;if(cx===undefined)return;
        var rect=elChip.getBoundingClientRect(),relX=cx-rect.left,xa=elChip._fullLayout?elChip._fullLayout.xaxis:null;
        if(!xa||typeof xa.p2c!=='function')return;var pL=xa._offset??80,pLen=xa._length??(rect.width-pL-15);if(relX<pL||relX>pL+pLen)return;
        var idx=Math.round(xa.p2c(relX-pL));
        if(idx>=0&&idx<totalPoints){renderInfo(idx);lineChip.style.left=(xa.c2p(idx)+pL)+'px';lineChip.style.display='block';broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:idx,showLine:true});}
    }
    function onLeave(){lineChip.style.display='none';broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:-1,showLine:false});}
    elChip.addEventListener('mousemove',onMove);elChip.addEventListener('touchmove',onMove,{passive:true});
    elChip.addEventListener('touchstart',onMove,{passive:true});elChip.addEventListener('mouseleave',onLeave);
});
})();</script>"""
    return (tpl.replace("__CID__", chart_id).replace("__HELPERS__", SHARED_JS_HELPERS).replace("__CHIP_H__", str(resolved_chip_h))
            .replace("__P_CHIP__", fig_chip.to_json()).replace("__DATES__", json.dumps(dates_list))
            .replace("__FOREIGNS__", json.dumps(df['Foreign_Net'].fillna(0).tolist() if 'Foreign_Net' in df.columns else [0] * n_pts))
            .replace("__TRUSTS__", json.dumps(df['Trust_Net'].fillna(0).tolist() if 'Trust_Net' in df.columns else [0] * n_pts))
            .replace("__DEALERS__", json.dumps(df['Dealer_Net'].fillna(0).tolist() if 'Dealer_Net' in df.columns else [0] * n_pts))
            .replace("__MDIFFS__", json.dumps(df['Margin_Diff'].fillna(0).tolist() if 'Margin_Diff' in df.columns else [0] * n_pts))
            .replace("__SDIFFS__", json.dumps(df['Short_Diff'].fillna(0).tolist() if 'Short_Diff' in df.columns else [0] * n_pts))
            .replace("__RATIOS__", json.dumps(df['Short_Margin_Ratio'].fillna(0).tolist() if 'Short_Margin_Ratio' in df.columns else [0] * n_pts))
            .replace("__MMAINTS__", _series_to_json_nullable(df, 'Margin_Maint_Pct', n_pts))
            .replace("__MMAINTS60D__", _series_to_json_nullable(df, 'Margin_Maint_60D_Pct', n_pts))
            .replace("__SMAINTS__", _series_to_json_nullable(df, 'Short_Maint_Pct', n_pts))
            .replace("__MMONEY__", _series_to_json_nullable(df, 'Margin_Money_Diff', n_pts))
            .replace("__IS_TW_INDEX__", "true" if is_tw_index else "false")
            .replace("__IS_TWOII__", "true" if is_twoii else "false")
            .replace("__M1PCTS__", json.dumps(df['Major1_Pct'].fillna(0).tolist() if 'Major1_Pct' in df.columns else [0] * n_pts))
            .replace("__M2PCTS__", json.dumps(df['Major2_Pct'].fillna(0).tolist() if 'Major2_Pct' in df.columns else [0] * n_pts))
            .replace("__M1TH__", str(m1_thresh)).replace("__M2TH__", str(m2_thresh))
            .replace("__DISP_DAYS__", str(initial_disp_days)).replace("__INIT_END__", str(end_idx))
            )
## EOF frontend.py
