"""
frontend.py - 前端 HTML/CSS 渲染模組
(恢復 16 日正常版純淨 20 日初始可視視窗 + 分點買賣超紅綠對齊＋柱狀圖 staticPlot 徹底鎖死不可平移縮放版 + 分點統計與分點日況雙頁籤分離版 + 分點日況預設20日自動貼合容器寬度版 + 大盤加權^TWII與櫃買^TWOII緊緻雙列資券千張＋融資金額(億)＋融資/融券維持率消除空白版 + 分點日況嚴格綁定關注交易日無專屬明細整組清空不平移殘影版 + 主圖成交量Y軸tick0=0與動態回報iframe高度完整顯示版 + 個股資券資訊列新增藍色預估融資維持率與綠色季融資維持率顯示版 + 加權^TWII與櫃買^TWOII八大官股個股前50名分點統計與關注個股下拉選單及8家官股行庫每日買賣超萬元紅買綠賣8子圖渲染版)
版本: 202611240725
"""
import json
import pandas as pd

MODULE_NAME = "frontend"
MODULE_VERSION = "202611240725"


# 【修訂說明 2026-11-18】【修改目的與防呆防錯原因】：
# 修改目的：保留主圖上方圖例與互動操作說明列，並兼容未傳入 version_tag 之呼叫方式。
# 防呆防錯原因：app.py 以 get_legend_html() 無參數呼叫，設定預設參數確保不觸發 TypeError。
def get_legend_html(version_tag: str = "202611240725") -> str:
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


def _extract_dates_list(df: pd.DataFrame) -> list:
    s = df['Date'] if 'Date' in df.columns else df.index
    return s.strftime('%Y-%m-%d').tolist() if hasattr(s, 'strftime') else [str(x)[:10] for x in s]


def _detect_gov_index_unit(df: pd.DataFrame, chart_id: str, is_index: bool) -> tuple:
    """
    【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    修改目的：辨識是否為大盤加權（^TWII）或櫃買（^TWOII）八大官股模式，
    回傳 (is_gov_index, unit_label, title_prefix)。上市加權與上櫃櫃買八大官股單位皆為「萬元」。
    防呆防錯原因：當 is_index=False 且 df 具備 Margin_Maint_Pct（大盤/櫃買指標）時判定為八大官股指數；
    以 Margin_Bal 全為 0 且 Margin_Money_Bal 有值區分上櫃八大官股與上市八大官股。
    """
    if is_index:
        return False, "張", "券商分點"
    cid_up = str(chart_id or "").upper()
    has_maint = ('Margin_Maint_Pct' in df.columns and not df['Margin_Maint_Pct'].dropna().empty)
    has_money_bal = ('Margin_Money_Bal' in df.columns and (df['Margin_Money_Bal'].fillna(0) != 0).any())
    zero_margin_bal = ('Margin_Bal' not in df.columns or (df['Margin_Bal'].fillna(0) == 0).all())
    is_twoii = ("^TWOII" in cid_up) or (has_maint and has_money_bal and zero_margin_bal)
    is_twii = ("^TWII" in cid_up) or (has_maint and not is_twoii)
    if is_twoii:
        return True, "萬元", "上櫃八大官股"
    if is_twii:
        return True, "萬元", "上市八大官股"
    return False, "張", "券商分點"


COMMON_CSS = """<style>
html,body{margin:0;padding:0;background:transparent;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.frame-root{position:relative;width:100%;box-sizing:border-box;padding-bottom:4px}
.touch-plot-box{position:relative;touch-action:pan-y!important;user-select:none!important;-webkit-user-select:none!important;width:100%!important;overflow:hidden}
.pane-info-bar{font-size:13px;color:#2c3e50;background:#f8fafc;padding:4px 6px;border-radius:4px;border:1px solid #e2e8f0;white-space:normal;line-height:1.38;overflow-x:auto}
@media(max-width:720px){.pane-info-bar{font-size:11.5px;line-height:1.32;padding:3px 5px}}
.val-up{color:#eb4d4b!important;font-weight:bold}.val-dn{color:#16a085!important;font-weight:bold}.tag-lbl{margin-right:4px}
.sync-crosshair-line{position:absolute;top:0;bottom:0;width:1px;border-left:1px dashed rgba(44,62,80,.85);pointer-events:none;display:none;z-index:999}
.sync-price-line{position:absolute;left:80px;right:15px;height:1px;border-top:1px dashed rgba(44,62,80,.75);pointer-events:none;display:none;z-index:999}
</style>"""

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
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx
    dates_list = _extract_dates_list(df)
    fig_tech = fig_btm["tech"] if isinstance(fig_btm, dict) and "tech" in fig_btm else getattr(fig_btm, "_fig_tech", fig_btm)

    tpl = COMMON_CSS + """
<div class="frame-root" id="__CID___tech_root">
    <div id="__CID___info_tech" class="pane-info-bar" style="margin-bottom:3px;">正在載入指標...</div>
    <div id="__CID___tech" class="touch-plot-box" style="height:__TECH_H__px;"><div id="__CID___line_tech" class="sync-crosshair-line"></div></div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>(function(){__HELPERS__
var pTech=__P_TECH__,dates=__DATES__,ks=__KS__,ds=__DS__,difs=__DIFS__,macds=__MACDS__,oscs=__OSCS__,obvs=__OBVS__,obvMas=__OBVMAS__;
var bias20s=__BIAS20__,bias120s=__BIAS120__,bias240s=__BIAS240__,bias1200s=__BIAS1200__;
var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
var elTech=document.getElementById('__CID___tech'),infoTech=document.getElementById('__CID___info_tech'),lineTech=document.getElementById('__CID___line_tech');

function renderInfo(idx){if(idx<0||idx>=totalPoints)return;
    var d=dates[idx],oscClass=oscs[idx]>0?'val-up':(oscs[idx]<0?'val-dn':'');
    infoTech.innerHTML='<div><span class="tag-lbl"><b>'+d+'</b></span> <span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:'+fmtNum(ks[idx],1)+'</span> <span style="color:#3498db;">D:'+fmtNum(ds[idx],1)+'</span> | <span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:'+fmtNum(obvs[idx],0)+'</span> <span style="color:#8e44ad;">MA20:'+fmtNum(obvMas[idx],0)+'</span></div><div><span class="tag-lbl"><b>MACD('+d+')</b></span><span style="color:#f39c12;">DIF:'+fmtNum(difs[idx])+'</span> <span style="color:#2980b9;">MACD:'+fmtNum(macds[idx])+'</span> OSC:<span class="'+oscClass+'">'+fmtNum(oscs[idx])+'</span> | <span class="tag-lbl"><b>乖離率</b></span><span style="color:#e67e22;">20日:</span>'+fmtBias(bias20s[idx])+' <span style="color:#2980b9;">120日:</span>'+fmtBias(bias120s[idx])+' <span style="color:#8e44ad;">240日:</span>'+fmtBias(bias240s[idx])+' <span style="color:#e74c3c;">1200日:</span>'+fmtBias(bias1200s[idx])+'</div>';
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
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx
    dates_list = _extract_dates_list(df)
    fig_chip = fig_btm["chip"] if isinstance(fig_btm, dict) and "chip" in fig_btm else getattr(fig_btm, "_fig_chip", fig_btm)

    fig_h = getattr(getattr(fig_chip, "layout", None), "height", None)
    resolved_chip_h = int(fig_h) if fig_h else int(chip_height)

    cid_upper = str(chart_id).upper()
    has_maint = ('Margin_Maint_Pct' in df.columns and not df['Margin_Maint_Pct'].dropna().empty)
    has_money_bal = ('Margin_Money_Bal' in df.columns and (df['Margin_Money_Bal'].fillna(0) != 0).any())
    zero_margin_bal = ('Margin_Bal' not in df.columns or (df['Margin_Bal'].fillna(0) == 0).all())
    is_twoii = ("^TWOII" in cid_upper) or (has_maint and has_money_bal and zero_margin_bal)
    is_tw_index = ("^TWII" in cid_upper) or is_twoii or (has_maint and zero_margin_bal)

    tpl = COMMON_CSS + """
<div class="frame-root" id="__CID___chip_root">
    <div id="__CID___info_ms" class="pane-info-bar" style="margin-bottom:3px;">正在載入資券...</div>
    <div id="__CID___info_chip" class="pane-info-bar" style="margin-bottom:3px;">正在載入法人集保...</div>
    <div id="__CID___chip" class="touch-plot-box" style="height:__CHIP_H__px;"><div id="__CID___line_chip" class="sync-crosshair-line"></div></div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>(function(){__HELPERS__
var pChip=__P_CHIP__,dates=__DATES__,foreigns=__FOREIGNS__,trusts=__TRUSTS__,dealers=__DEALERS__,mDiffs=__MDIFFS__,sDiffs=__SDIFFS__,rat=__RATIOS__;
var mMaints=__MMAINTS__,mMaints60d=__MMAINTS60D__,sMaints=__SMAINTS__,mMoneyDiffs=__MMONEY__,isTwIndex=__IS_TW_INDEX__,isTwoii=__IS_TWOII__;
var m1_pcts=__M1PCTS__,m2_pcts=__M2PCTS__,m1_thresh=__M1TH__,m2_thresh=__M2TH__;
var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
var elChip=document.getElementById('__CID___chip'),infoMs=document.getElementById('__CID___info_ms'),infoChip=document.getElementById('__CID___info_chip'),lineChip=document.getElementById('__CID___line_chip');

function renderInfo(idx){if(idx<0||idx>=totalPoints)return;
    var d=dates[idx],mT=mDiffs[idx]!=null?Number(mDiffs[idx])/1000.0:null,sT=sDiffs[idx]!=null?Number(sDiffs[idx])/1000.0:null;
    if(isTwoii){
        infoMs.innerHTML='<span class="tag-lbl"><b>上櫃資券('+d+')</b></span>融券:'+fmtDiff(sT,2)+'千張 ｜ <b>融資金額:</b>'+fmtDiff(mMoneyDiffs[idx],2)+'億 ｜ <span style="color:#e67e22;font-weight:bold;">融資維持率:'+fmtNum(mMaints[idx])+'%</span> <span style="color:#8e44ad;font-weight:bold;">融券維持率:'+fmtNum(sMaints[idx])+'%</span>';
        infoChip.innerHTML='<span class="tag-lbl"><b>櫃買指數('+d+')</b></span>櫃買指數顯示上櫃融券(千張)、上櫃融資金額(億)及融資/融券維持率（八大官股進出請切換至「分點統計／分點日況」頁籤）';
    }else if(isTwIndex){
        infoMs.innerHTML='<span class="tag-lbl"><b>上市資券[千張]('+d+')</b></span>融資:'+fmtDiff(mT,2)+' 融券:'+fmtDiff(sT,2)+' ｜ <b>融資金額:</b>'+fmtDiff(mMoneyDiffs[idx],2)+'億 ｜ <span style="color:#e67e22;font-weight:bold;">融資維持率:'+fmtNum(mMaints[idx])+'%</span> <span style="color:#8e44ad;font-weight:bold;">融券維持率:'+fmtNum(sMaints[idx])+'%</span>';
        infoChip.innerHTML='<span class="tag-lbl"><b>大盤指數('+d+')</b></span>加權指數顯示上市資券(千張)、上市融資金額(億)及融資/融券維持率（八大官股進出請切換至「分點統計／分點日況」頁籤）';
    }else{
        infoMs.innerHTML='<span class="tag-lbl"><b>資券[千張]('+d+')</b></span>融資:'+fmtDiff(mT,3)+' 融券:'+fmtDiff(sT,3)+' <span style="color:#e67e22;font-weight:bold;">券資比:'+fmtNum(rat[idx])+'%</span> <span style="color:#2980b9;font-weight:bold;">預估融資維持率:'+fmtNum(mMaints[idx])+'%</span> <span style="color:#16a085;font-weight:bold;">季融資維持率:'+fmtNum(mMaints60d[idx])+'%</span>';
        infoChip.innerHTML='<span class="tag-lbl"><b>法人集保('+d+')</b></span>外資:'+fmtDiff(foreigns[idx],0)+' 投信:'+fmtDiff(trusts[idx],0)+' 自營:'+fmtDiff(dealers[idx],0)+' | ≥'+m1_thresh+'張: '+fmtNum(m1_pcts[idx])+'% ≥'+m2_thresh+'張: '+fmtNum(m2_pcts[idx])+'%';
    }
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


BROKER_SHARED_CSS = """<style>
.b-card{background:#fff;border:1px solid #e2e8f0;border-radius:6px;padding:6px;margin-bottom:8px;width:100%;box-sizing:border-box}
.b-title{font-size:13px;font-weight:bold;color:#1e293b;background:#f1f5f9;padding:4px 8px;border-radius:4px;margin-bottom:6px;border-left:3px solid #2c3e50}
.b-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;width:100%}@media(max-width:720px){.b-grid{grid-template-columns:1fr}}
.b-grid>div{min-width:0;width:100%}
.b-wrap{overflow-x:auto;border:1px solid #e2e8f0;border-radius:4px;max-height:520px;overflow-y:auto}
.b-tbl{width:100%;border-collapse:collapse;font-size:11.5px;text-align:right;white-space:nowrap}
.b-tbl th{position:sticky;top:0;z-index:2;background:#f8fafc;color:#334155;font-weight:700;padding:4px 5px;border-bottom:1px solid #cbd5e1}
.b-tbl td{padding:3px 5px;border-bottom:1px solid #f1f5f9;color:#1e293b}
.b-tbl td.val-up{color:#eb4d4b!important;font-weight:bold!important}
.b-tbl td.val-dn{color:#16a085!important;font-weight:bold!important}
.b-tbl th:nth-child(1),.b-tbl td:nth-child(1),.b-tbl th:nth-child(2),.b-tbl td:nth-child(2){text-align:left}
.gov-badge{display:inline-block;background:#fef3c7;color:#92400e;font-size:10px;padding:0 3px;border-radius:3px;margin-left:3px;border:1px solid #f59e0b}
.b-bar{width:100%;max-width:100%;box-sizing:border-box;overflow:hidden;height:185px;border:1px solid #e2e8f0;border-radius:4px;margin-bottom:6px;background:#fff;pointer-events:none!important;touch-action:pan-y!important;user-select:none!important;-webkit-user-select:none!important}
</style>"""


def get_broker_stats_tab_html(
    df: pd.DataFrame,
    broker_payload: dict = None,
    chart_id: str = "mchart_broker_stats",
    end_idx: int = None,
    disp_days: int = 20,
    is_mobile: bool = False,
    initial_end_idx: int = None,
    is_index: bool = None
) -> str:
    n_pts = len(df)
    resolved_end = end_idx if end_idx is not None else (initial_end_idx if initial_end_idx is not None else (n_pts - 1))
    dates_list = _extract_dates_list(df)
    if is_index is None:
        is_index = len(dates_list) == 0 or (df['Turnover_Rate'].max() == 0 and df['Foreign_Net'].abs().max() == 0)
    safe_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}
    is_gov_idx, unit_lbl, title_prefix = _detect_gov_index_unit(df, chart_id, bool(is_index))

    tpl = COMMON_CSS + BROKER_SHARED_CSS + """
<div class="frame-root" id="__CID___broker_stats_root">
    <div id="__CID___b_hdr" class="pane-info-bar" style="margin-bottom:6px;"></div>
    <div id="__CID___b_tbls"></div>
</div>
<script>(function(){var dates=__DATES__,isIndex=__IS_IDX__,isGovIdx=__IS_GOV_IDX__,unitLbl=__UNIT_LBL__,titlePrefix=__TITLE_PREFIX__,payload=__BROKER_JSON__,curIdx=__INIT_END__;
var rootEl=document.getElementById('__CID___broker_stats_root'),hdrEl=document.getElementById('__CID___b_hdr'),tblsEl=document.getElementById('__CID___b_tbls');
var MSG_60D_ON_DEMAND='尚未載入近 60 日統計（預設僅載入至 20 日；請點擊上方「📥 載入近 60 日分點統計與明細」按鈕按需抓取）';
function pushH(){if(!rootEl)return;var h=Math.ceil(rootEl.scrollHeight)+16;if(window.parent&&window.parent!==window)window.parent.postMessage({isStreamlitMessage:true,type:"streamlit:setFrameHeight",height:h},"*");}
if(typeof ResizeObserver!=='undefined'&&rootEl){new ResizeObserver(function(){pushH();}).observe(rootEl);}
function fmtI(v){var n=Number(v)||0;return n.toLocaleString('en-US');}
function fmtNet(v,isBuySide){var n=Number(v)||0;if(isBuySide){var a=Math.abs(n);return a>0?'+'+a.toLocaleString('en-US'):'0';}else{var b=Math.abs(n);return b>0?'-'+b.toLocaleString('en-US'):'0';}}
function buildSideTable(title,rows,isBuySide){var h='<div style="border:1px solid #cbd5e1;border-radius:5px;padding:4px;background:#fff;"><div style="font-size:12px;font-weight:bold;margin-bottom:4px;color:'+(isBuySide?'#eb4d4b':'#16a085')+';">'+title+'</div><div class="b-wrap"><table class="b-tbl"><thead><tr><th>名次</th><th>'+(isGovIdx?'股票名稱':'分點名稱')+'</th><th>買進</th><th>賣出</th><th>買賣超</th><th>佔比</th></tr></thead><tbody>';
    if(!rows||rows.length===0){h+='<tr><td colspan="6" style="text-align:center;color:#94a3b8;padding:10px;">查無明細資料</td></tr>';}
    else{for(var i=0;i<rows.length;i++){var r=rows[i],badge=(!isGovIdx&&(r.sys==='官股'||r.sys==='八大官股'))?'<span class="gov-badge">官股</span>':'',cls=isBuySide?'val-up':'val-dn';
        h+='<tr><td>'+(i+1)+'</td><td><b>'+r.name+'</b>'+badge+'</td><td>'+fmtI(r.buy)+'</td><td>'+fmtI(r.sell)+'</td><td class="'+cls+'">'+fmtNet(r.net,isBuySide)+'</td><td>'+(r.ratio||'-')+'</td></tr>';}}
    return h+'</tbody></table></div></div>';
}
function renderStats(idx){if(idx<0||idx>=dates.length)return;curIdx=idx;var dStr=dates[curIdx]||'';
    if(isIndex){hdrEl.innerHTML='<b>📊 券商分點買賣超統計（'+dStr+'）</b> ｜ <span style="color:#64748b;">海外市場指數無單一券商分點明細</span>';tblsEl.innerHTML='';pushH();return;}
    var dayObj=(payload.by_date&&payload.by_date[dStr])?payload.by_date[dStr]:null;
    if(isGovIdx){
        hdrEl.innerHTML='<b>📊 '+titlePrefix+'買賣超個股統計（前50大）</b> ｜ 關注交易日：<b>'+dStr+'</b> <span style="color:#64748b;font-size:11.5px;">（買超紅字＋號、賣超綠字－號；單位：'+unitLbl+'）</span>';
    }else{
        hdrEl.innerHTML='<b>📊 券商分點買賣超統計</b> ｜ 關注交易日：<b>'+dStr+'</b> <span style="color:#64748b;font-size:11.5px;">（買超紅字＋號、賣超綠字－號；15:00前預設對齊前一交易日）</span>';
    }
    if(!dayObj){tblsEl.innerHTML='<div class="b-card" style="color:#64748b;font-size:12.5px;padding:12px;">尚無 <b>'+dStr+'</b> 之'+titlePrefix+'統計資料（可能為非交易日或尚未載入該日資料）。</div>';pushH();return;}
    var secs=[{k:'w1',t:'1. 當日買賣超排行'},{k:'w10',t:'2. 近 10 日買賣超排行'},{k:'w20',t:'3. 近 20 日買賣超排行'},{k:'w60',t:'4. 近 60 日買賣超排行'}];
    var h='';
    for(var s=0;s<secs.length;s++){var obj=dayObj[secs[s].k]||{};var rng=obj.range_label?' <span style="font-weight:normal;color:#475569;font-size:11.5px;">（區間：'+obj.range_label+'）</span>':'';
        h+='<div class="b-card"><div class="b-title">'+secs[s].t+rng+'</div>';
        if(secs[s].k==='w60'&&(!obj.buy||obj.buy.length===0)&&(!obj.sell||obj.sell.length===0)&&!isGovIdx){
            h+='<div style="color:#64748b;font-size:12px;padding:8px 10px;background:#f8fafc;border-radius:4px;border:1px dashed #cbd5e1;">'+MSG_60D_ON_DEMAND+'</div></div>';
        }else{
            h+='<div class="b-grid">'+buildSideTable('🔴 買超排行（'+unitLbl+'）',obj.buy||[],true)+buildSideTable('🟢 賣超排行（'+unitLbl+'）',obj.sell||[],false)+'</div></div>';
        }
    }
    tblsEl.innerHTML=h;setTimeout(pushH,60);
}
window.addEventListener('message',function(ev){var msg=ev.data||{};if(msg.type==='MCHART_SYNC_FOCUS'&&msg.idx>=0)renderStats(msg.idx);});
renderStats(curIdx);
})();</script>"""
    return (tpl.replace("__CID__", chart_id)
            .replace("__DATES__", json.dumps(dates_list))
            .replace("__IS_IDX__", "true" if is_index else "false")
            .replace("__IS_GOV_IDX__", "true" if is_gov_idx else "false")
            .replace("__UNIT_LBL__", json.dumps(unit_lbl, ensure_ascii=False))
            .replace("__TITLE_PREFIX__", json.dumps(title_prefix, ensure_ascii=False))
            .replace("__BROKER_JSON__", json.dumps(safe_payload, ensure_ascii=False))
            .replace("__INIT_END__", str(resolved_end))
            )


def get_broker_daily_tab_html(
    df: pd.DataFrame,
    broker_payload: dict = None,
    chart_id: str = "mchart_broker_daily",
    end_idx: int = None,
    disp_days: int = 20,
    is_mobile: bool = False,
    initial_end_idx: int = None,
    is_index: bool = None
) -> str:
    """
    【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    1. 修改目的：
       - 大盤加權（^TWII）與櫃買指數（^TWOII）模式下（is_gov_idx=True）：
         提供「統計區間天數」（近 10 日 / 近 20 日 / 近 60 日）下拉選單，並動態載入該區間內
         「八大官股買超前 50 大個股」與「賣超前 50 大個股」的「關注個股」下拉式選單；
         選取任一關注個股後，畫面一次呈現該單一個股的 **8 個官股行庫子圖**（合作金庫、土地銀行、臺灣銀行、臺灣企銀、彰化銀行、第一金、兆豐銀、華南永昌），
         每個子圖繪製該官股行庫於該個股每日買賣超（萬元）的紅買綠賣柱狀圖（買超紅柱、賣超綠柱，staticPlot 鎖死不可平移縮放）。
       - 一般台股個股 / ETF 模式下（is_gov_idx=False）：
         完整保留原雙欄買超前 5 名與賣超前 5 名券商分點逐日進出柱狀圖。
    2. 防呆防錯原因：
       - 當切換關注交易日或統計區間天數時，若先前選取的關注個股仍存在於新候選清單中則自動保留該個股，否則自動選取買超第 1 名個股，確保 8 個官股子圖即時重繪不空白。
    """
    n_pts = len(df)
    resolved_end = end_idx if end_idx is not None else (initial_end_idx if initial_end_idx is not None else (n_pts - 1))
    dates_list = _extract_dates_list(df)
    if is_index is None:
        is_index = len(dates_list) == 0 or (df['Turnover_Rate'].max() == 0 and df['Foreign_Net'].abs().max() == 0)
    safe_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}
    is_gov_idx, unit_lbl, title_prefix = _detect_gov_index_unit(df, chart_id, bool(is_index))

    tpl = COMMON_CSS + BROKER_SHARED_CSS + """
<div class="frame-root" id="__CID___broker_daily_root">
    <div id="__CID___d_hdr" class="pane-info-bar" style="margin-bottom:6px;"></div>
    <div class="b-card">
        <div class="b-title" id="__CID___d_card_title">區間買賣超統計各前 5 名分點 — 各日買賣超柱狀圖（分點買賣超交易日況僅限最近20日）</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
            <label for="__CID___b_sel" style="font-size:12.5px;font-weight:bold;color:#334155;">統計區間天數：</label>
            <select id="__CID___b_sel" style="padding:4px 8px;font-size:13px;border-radius:4px;border:1px solid #94a3b8;font-weight:bold;">
                <option value="10">近 10 日（含關注交易日）</option>
                <option value="20" selected>近 20 日（含關注交易日）</option>
                <option value="60">近 60 日（含關注交易日）</option>
            </select>
            <span id="__CID___gov_stk_box" style="display:none;align-items:center;gap:6px;flex-wrap:wrap;">
                <label for="__CID___gov_stk_sel" style="font-size:12.5px;font-weight:bold;color:#1e3a8a;">關注個股（買超前50／賣超前50）：</label>
                <select id="__CID___gov_stk_sel" style="padding:4px 8px;font-size:13px;border-radius:4px;border:1.5px solid #2563eb;font-weight:bold;color:#0f172a;background:#eff6ff;min-width:210px;"></select>
            </span>
        </div>
        <div id="__CID___b_warn" style="font-size:12px;color:#d97706;background:#fffbeb;padding:6px 8px;border-radius:4px;border:1px solid #fde68a;margin-bottom:8px;display:none;"></div>
        <div id="__CID___b_bars"></div>
    </div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>(function(){var dates=__DATES__,isIndex=__IS_IDX__,isGovIdx=__IS_GOV_IDX__,unitLbl=__UNIT_LBL__,titlePrefix=__TITLE_PREFIX__,payload=__BROKER_JSON__,curIdx=__INIT_END__;
var cfg={responsive:true,staticPlot:true,displayModeBar:false,scrollZoom:false,doubleClick:false};
var rootEl=document.getElementById('__CID___broker_daily_root'),hdrEl=document.getElementById('__CID___d_hdr'),cardTitleEl=document.getElementById('__CID___d_card_title');
var selEl=document.getElementById('__CID___b_sel'),govBoxEl=document.getElementById('__CID___gov_stk_box'),govSelEl=document.getElementById('__CID___gov_stk_sel');
var warnEl=document.getElementById('__CID___b_warn'),barsEl=document.getElementById('__CID___b_bars');
var MSG_60D_ON_DEMAND='尚無近 60 日逐日進出明細（單一分點日況僅提供最近 20 個交易日明細）';
var lastRenderedW=0,hasRenderedOnce=false,resizeTimer=null,lastSelectedGovStock='';
if(isGovIdx){
    if(cardTitleEl)cardTitleEl.textContent=titlePrefix+'買賣超前50大個股 — 選定個股 8 家官股行庫每日買賣超柱狀圖（單位：'+unitLbl+'）';
    if(govBoxEl)govBoxEl.style.display='inline-flex';
}
function getVisibleW(){
    if(!rootEl)return 0;
    var w=Math.floor(rootEl.getBoundingClientRect().width||rootEl.offsetWidth||document.documentElement.clientWidth||0);
    return w;
}
function pushH(){if(!rootEl)return;var h=Math.ceil(rootEl.scrollHeight)+16;if(window.parent&&window.parent!==window)window.parent.postMessage({isStreamlitMessage:true,type:"streamlit:setFrameHeight",height:h},"*");}
function fmtNet(v,isBuySide){var n=Number(v)||0;if(isBuySide){var a=Math.abs(n);return a>0?'+'+a.toLocaleString('en-US'):'0';}else{var b=Math.abs(n);return b>0?'-'+b.toLocaleString('en-US'):'0';}}
function fmtSignedNet(v){var n=Number(v)||0;if(n>0)return '+'+n.toLocaleString('en-US');if(n<0)return '-'+Math.abs(n).toLocaleString('en-US');return '0';}
function hasValidSeries(arr){
    if(!Array.isArray(arr)||arr.length===0)return false;
    for(var i=0;i<arr.length;i++){
        if(arr[i]&&Array.isArray(arr[i].dates)&&arr[i].dates.length>0)return true;
    }
    return false;
}
function rebuildGovStockOptions(wObj){
    if(!govSelEl)return '';
    var buyRows=(wObj&&Array.isArray(wObj.buy))?wObj.buy.slice(0,50):[];
    var sellRows=(wObj&&Array.isArray(wObj.sell))?wObj.sell.slice(0,50):[];
    var sMap=(wObj&&wObj.stock_8bank_series)?wObj.stock_8bank_series:{};
    var seen={},opts=[];
    for(var i=0;i<buyRows.length;i++){
        var nm=String(buyRows[i].name||'').trim();
        if(!nm||seen[nm]||!sMap[nm])continue;
        seen[nm]=true;
        opts.push({val:nm,lbl:'[買超#'+(i+1)+'] '+nm+' ('+fmtSignedNet(buyRows[i].net)+'萬)'});
    }
    for(var j=0;j<sellRows.length;j++){
        var nm2=String(sellRows[j].name||'').trim();
        if(!nm2||seen[nm2]||!sMap[nm2])continue;
        seen[nm2]=true;
        opts.push({val:nm2,lbl:'[賣超#'+(j+1)+'] '+nm2+' ('+fmtSignedNet(sellRows[j].net)+'萬)'});
    }
    govSelEl.innerHTML='';
    for(var k=0;k<opts.length;k++){
        var op=document.createElement('option');
        op.value=opts[k].val;
        op.textContent=opts[k].lbl;
        govSelEl.appendChild(op);
    }
    if(opts.length===0)return '';
    var targetVal=opts[0].val;
    if(lastSelectedGovStock&&seen[lastSelectedGovStock]){targetVal=lastSelectedGovStock;}
    govSelEl.value=targetVal;
    lastSelectedGovStock=targetVal;
    return targetVal;
}
function renderGov8Banks(wObj,axisDates,tVals,tTexts,curW){
    var selStk=rebuildGovStockOptions(wObj);
    var sMap=(wObj&&wObj.stock_8bank_series)?wObj.stock_8bank_series:{};
    var bankList=(selStk&&sMap[selStk])?sMap[selStk]:[];
    if(!selStk||!Array.isArray(bankList)||bankList.length===0){
        if(warnEl){warnEl.textContent='尚無此區間八大官股前50大個股之逐日明細，請先於「⚙️ 參數設定 → 加權指數／櫃買指數八大官股維護」點擊「📥 批次增補八大官股交易前30個股」。';warnEl.style.display='block';}
        barsEl.innerHTML='';pushH();return;
    }
    if(warnEl)warnEl.style.display='none';
    var html='<div class="b-grid"><div>';
    for(var i=0;i<4&&i<bankList.length;i++)html+='<div id="__CID___gb_'+i+'" class="b-bar"></div>';
    html+='</div><div>';
    for(var j=4;j<bankList.length;j++)html+='<div id="__CID___gb_'+j+'" class="b-bar"></div>';
    html+='</div></div>';
    barsEl.innerHTML=html;

    for(var idx=0;idx<bankList.length;idx++){
        (function(divId,item,bIdx){
            var el=document.getElementById(divId);if(!el||typeof Plotly==='undefined')return;
            var boxW=Math.floor(el.getBoundingClientRect().width||el.clientWidth||0);
            if(boxW<=0){boxW=curW>720?Math.floor((curW-24)/2):Math.max(260,curW-18);}
            var netMap={};
            var rawD=item.dates||[],rawN=item.nets||[];
            for(var k=0;k<rawD.length;k++){netMap[rawD[k]]=Number(rawN[k])||0;}
            var yVals=axisDates.map(function(dt){return Object.prototype.hasOwnProperty.call(netMap,dt)?netMap[dt]:0;});
            var cols=yVals.map(function(v){return v>=0?'#eb4d4b':'#2ecc71';});
            var totVal=Number(item.total_net)||0;
            var totStr=fmtSignedNet(totVal);
            var titleClr=totVal>0?'#eb4d4b':(totVal<0?'#16a085':'#334155');
            var tr={x:axisDates,y:yVals,type:'bar',marker:{color:cols},hoverinfo:'skip'};
            var lay={
                width:boxW,height:182,autosize:false,
                title:{text:'<b>'+(bIdx+1)+'. '+item.bank+' — '+selStk+' (區間:'+totStr+unitLbl+')</b>',font:{size:11.5,color:titleClr},x:0.02,xanchor:'left'},
                margin:{l:50,r:10,t:28,b:22},template:'plotly_white',showlegend:false,hovermode:false,dragmode:false,
                xaxis:{type:'category',categoryorder:'array',categoryarray:axisDates,range:[-0.5,axisDates.length-0.5],fixedrange:true,showgrid:false,tickmode:'array',tickvals:tVals,ticktext:tTexts,tickfont:{size:10}},
                yaxis:{fixedrange:true,zeroline:true,zerolinecolor:'#94a3b8',zerolinewidth:1,tickfont:{size:10},title:{text:unitLbl,font:{size:10}}}
            };
            Plotly.newPlot(el,[tr],lay,cfg);
        })('__CID___gb_'+idx,bankList[idx],idx);
    }
    setTimeout(pushH,80);
}
function renderBars(forceDraw,keepGovSelection){
    if(!barsEl)return;
    var win=selEl?selEl.value:'20',dStr=dates[curIdx]||'',dayObj=(payload.by_date&&payload.by_date[dStr])?payload.by_date[dStr]:null;
    if(hdrEl){
        if(isIndex){hdrEl.innerHTML='<b>📈 券商分點逐日進出日況（'+dStr+'）</b> ｜ <span style="color:#64748b;">海外市場指數無單一券商分點明細</span>';}
        else if(isGovIdx){hdrEl.innerHTML='<b>📈 '+titlePrefix+'逐日進出日況</b> ｜ 關注交易日：<b>'+dStr+'</b> <span style="color:#64748b;font-size:11.5px;">（下拉選取前50大買超／賣超個股，一次檢視 8 家官股行庫每日買賣超，單位：'+unitLbl+'）</span>';}
        else{hdrEl.innerHTML='<b>📈 券商分點逐日進出日況</b> ｜ 關注交易日：<b>'+dStr+'</b> <span style="color:#64748b;font-size:11.5px;">（買超前 5 名與賣超前 5 名逐日進出柱狀圖）</span>';}
    }
    var curW=getVisibleW();
    if(curW<=0&&!forceDraw){return;}
    lastRenderedW=curW;
    hasRenderedOnce=true;
    if(isIndex){if(warnEl)warnEl.style.display='none';barsEl.innerHTML='<div style="color:#94a3b8;font-size:12px;padding:8px;">海外市場指數無單一券商分點逐日明細資料。</div>';pushH();return;}
    if(!dayObj){
        if(govSelEl)govSelEl.innerHTML='';
        if(warnEl){warnEl.textContent='尚無 '+dStr+' 之近 '+win+' 日'+titlePrefix+'逐日進出明細。';warnEl.style.display='block';}
        barsEl.innerHTML='';pushH();return;
    }
    var wObj=dayObj['w'+win]||null;
    var winNum=parseInt(win,10)||20;
    var sIdx=Math.max(0,curIdx-winNum+1);
    var axisDates=dates.slice(sIdx,curIdx+1);
    var tVals=[],tTexts=[],curM='';
    for(var ti=0;ti<axisDates.length;ti++){
        var ym=axisDates[ti].slice(0,7);
        if(ym!==curM){curM=ym;tVals.push(axisDates[ti]);tTexts.push(parseInt(axisDates[ti].slice(5,7),10)+'月');}
    }

    if(isGovIdx){
        if(keepGovSelection&&govSelEl&&govSelEl.value){lastSelectedGovStock=govSelEl.value;}
        renderGov8Banks(wObj,axisDates,tVals,tTexts,curW);
        return;
    }

    var bList=(wObj&&wObj.top5_buy_series)?wObj.top5_buy_series:[];
    var sList=(wObj&&wObj.top5_sell_series)?wObj.top5_sell_series:[];
    if(!wObj||(!hasValidSeries(bList)&&!hasValidSeries(sList))){
        if(warnEl){warnEl.textContent=(win==='60')?MSG_60D_ON_DEMAND:('尚無 '+dStr+' 之近 '+win+' 日'+titlePrefix+'逐日進出明細（分點買賣超交易日況僅限最近20日）。');warnEl.style.display='block';}
        barsEl.innerHTML='';pushH();return;
    }
    if(warnEl)warnEl.style.display='none';
    var html='<div class="b-grid"><div>';
    for(var i=0;i<bList.length;i++)html+='<div id="__CID___bb_'+i+'" class="b-bar"></div>';
    html+='</div><div>';
    for(var j=0;j<sList.length;j++)html+='<div id="__CID___sb_'+j+'" class="b-bar"></div>';
    html+='</div></div>';barsEl.innerHTML=html;
    function drawOne(divId,item,rankIdx,isBuySide){var el=document.getElementById(divId);if(!el||typeof Plotly==='undefined')return;
        var boxW=Math.floor(el.getBoundingClientRect().width||el.clientWidth||0);
        if(boxW<=0){boxW=curW>720?Math.floor((curW-24)/2):Math.max(260,curW-18);}
        var netMap={};
        var rawD=item.dates||[],rawN=item.nets||[];
        for(var k=0;k<rawD.length;k++){netMap[rawD[k]]=Number(rawN[k])||0;}
        var yVals=axisDates.map(function(dt){return Object.prototype.hasOwnProperty.call(netMap,dt)?netMap[dt]:0;});
        var cols=yVals.map(function(v){return v>=0?'#eb4d4b':'#2ecc71';});
        var totStr=fmtNet(item.total_net,isBuySide);
        var titlePrefixSide=isBuySide?'買超':'賣超';
        var tr={x:axisDates,y:yVals,type:'bar',marker:{color:cols},hoverinfo:'skip'};
        var lay={
            width:boxW,height:182,autosize:false,
            title:{text:'<b>'+titlePrefixSide+'#'+(rankIdx+1)+' '+item.name+' (區間:'+totStr+unitLbl+')</b>',font:{size:11.5,color:isBuySide?'#eb4d4b':'#16a085'},x:0.02,xanchor:'left'},
            margin:{l:46,r:10,t:28,b:22},template:'plotly_white',showlegend:false,hovermode:false,dragmode:false,
            xaxis:{type:'category',categoryorder:'array',categoryarray:axisDates,range:[-0.5,axisDates.length-0.5],fixedrange:true,showgrid:false,tickmode:'array',tickvals:tVals,ticktext:tTexts,tickfont:{size:10}},
            yaxis:{fixedrange:true,zeroline:true,zerolinecolor:'#94a3b8',zerolinewidth:1,tickfont:{size:10},title:{text:unitLbl,font:{size:10}}}
        };
        Plotly.newPlot(el,[tr],lay,cfg);
    }
    for(var i=0;i<bList.length;i++)drawOne('__CID___bb_'+i,bList[i],i,true);
    for(var j=0;j<sList.length;j++)drawOne('__CID___sb_'+j,sList[j],j,false);
    setTimeout(pushH,80);
}
if(typeof ResizeObserver!=='undefined'&&rootEl){
    new ResizeObserver(function(){
        pushH();
        var nowW=getVisibleW();
        if(nowW>0&&(!hasRenderedOnce||Math.abs(nowW-lastRenderedW)>8)){
            clearTimeout(resizeTimer);
            resizeTimer=setTimeout(function(){renderBars(true,true);},60);
        }
    }).observe(rootEl);
}
window.addEventListener('resize',function(){
    var nowW=getVisibleW();
    if(nowW>0&&(!hasRenderedOnce||Math.abs(nowW-lastRenderedW)>8)){
        clearTimeout(resizeTimer);
        resizeTimer=setTimeout(function(){renderBars(true,true);},80);
    }
});
if(selEl)selEl.addEventListener('change',function(){renderBars(true,true);});
if(govSelEl)govSelEl.addEventListener('change',function(){lastSelectedGovStock=govSelEl.value;renderBars(true,true);});
window.addEventListener('message',function(ev){var msg=ev.data||{};if(msg.type==='MCHART_SYNC_FOCUS'&&msg.idx>=0){curIdx=msg.idx;renderBars(false,true);}});
renderBars(false,false);
})();</script>"""
    return (tpl.replace("__CID__", chart_id)
            .replace("__DATES__", json.dumps(dates_list))
            .replace("__IS_IDX__", "true" if is_index else "false")
            .replace("__IS_GOV_IDX__", "true" if is_gov_idx else "false")
            .replace("__UNIT_LBL__", json.dumps(unit_lbl, ensure_ascii=False))
            .replace("__TITLE_PREFIX__", json.dumps(title_prefix, ensure_ascii=False))
            .replace("__BROKER_JSON__", json.dumps(safe_payload, ensure_ascii=False))
            .replace("__INIT_END__", str(resolved_end))
            )


def get_broker_tab_html(
    df: pd.DataFrame,
    broker_payload: dict = None,
    chart_id: str = "mchart_broker",
    end_idx: int = None,
    disp_days: int = 20,
    is_mobile: bool = False,
    initial_end_idx: int = None,
    is_index: bool = None
) -> str:
    """向下相容別名：預設回傳分點統計頁籤 HTML"""
    return get_broker_stats_tab_html(
        df=df,
        broker_payload=broker_payload,
        chart_id=chart_id,
        end_idx=end_idx,
        disp_days=disp_days,
        is_mobile=is_mobile,
        initial_end_idx=initial_end_idx,
        is_index=is_index
    )
## EOF frontend.py
