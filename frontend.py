"""
frontend.py - 前端 HTML/CSS 渲染模組 (精簡防截斷 + 分點柱狀圖X軸僅首日標示月份版)
版本: 202611132220
"""

import json
import pandas as pd

MODULE_NAME = "frontend"
MODULE_VERSION = "202611132220"


def get_legend_html(version_tag: str = "202611132220") -> str:
    return f"""<div style="font-size:14px;margin-bottom:4px;padding:2px 8px;display:inline-flex;align-items:center;background:#f8fafc;border-radius:4px;border:1px solid #e2e8f0;"><span style="background:#2c3e50;color:#fff;padding:2px 8px;border-radius:4px;font-weight:bold;font-size:12px;">台股技術與籌碼分析 v{version_tag}</span></div>"""


def _series_to_json_nullable(df: pd.DataFrame, col: str, n_pts: int) -> str:
    if col not in df.columns:
        return json.dumps([None] * n_pts)
    return json.dumps([None if pd.isna(v) else float(v) for v in df[col].tolist()])


def _extract_dates_list(df: pd.DataFrame) -> list:
    s = df['Date'] if 'Date' in df.columns else df.index
    return s.strftime('%Y-%m-%d').tolist() if hasattr(s, 'strftime') else [str(x)[:10] for x in s]


COMMON_CSS = """<style>
html,body{margin:0;padding:0;background:transparent;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.frame-root{position:relative;width:100%;box-sizing:border-box;padding-bottom:4px}
.touch-plot-box{position:relative;touch-action:pan-y!important;user-select:none!important;-webkit-user-select:none!important;width:100%!important;overflow:hidden}
.pane-info-bar{font-size:13px;color:#2c3e50;background:#f8fafc;padding:4px 6px;border-radius:4px;border:1px solid #e2e8f0;white-space:normal;line-height:1.38;overflow-x:auto}
@media(max-width:720px){.pane-info-bar{font-size:11.5px;line-height:1.32;padding:3px 5px}}
.val-up{color:#eb4d4b;font-weight:bold}.val-dn{color:#2ecc71;font-weight:bold}.tag-lbl{margin-right:4px}
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
    <script>(function(){
        __HELPERS__
        var pTop=__P_TOP__,dates=__DATES__,opens=__OPENS__,highs=__HIGHS__,lows=__LOWS__,closes=__CLOSES__,vols=__VOLS__;
        var ma5s=__MA5S__,ma20s=__MA20S__,ma60s=__MA60S__,turnovers=__TURNOVERS__;
        var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
        var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
        var elTop=document.getElementById('__CID___top'),info1=document.getElementById('__CID___info1');
        var lineX=document.getElementById('__CID___line_x'),lineY=document.getElementById('__CID___line_y');
        function calcBounds(r0,r1){
            var s=Math.max(0,Math.floor(r0)),e=Math.min(totalPoints-1,Math.ceil(r1)),pMin=Infinity,pMax=-Infinity,vMax=0;
            for(var i=s;i<=e;i++){
                var h=Number(highs[i]),l=Number(lows[i]);
                if(!isNaN(h)&&h>0)pMax=Math.max(pMax,h);if(!isNaN(l)&&l>0)pMin=Math.min(pMin,l);
                [ma5s[i],ma20s[i],ma60s[i]].forEach(function(m){var v=Number(m);if(!isNaN(v)&&v>0){pMax=Math.max(pMax,v);pMin=Math.min(pMin,v);}});
                var vol=Number(vols[i]);if(!isNaN(vol)&&vol>0)vMax=Math.max(vMax,vol);
            }
            if(pMin===Infinity){pMin=0;pMax=100;}
            var pad=(pMax>pMin)?(pMax-pMin)*0.10:2.0;
            return{p:[pMin-pad,pMax+pad],v:[0,vMax>0?vMax*1.25:1000]};
        }
        function renderInfo(idx){
            if(idx<0||idx>=totalPoints)return;
            var d=dates[idx],c=closes[idx],o=opens[idx],h=highs[idx],l=lows[idx],prev=idx>0?closes[idx-1]:o;
            var diff=c-prev,pct=prev?(diff/prev*100):0,cls=diff>0?'val-up':(diff<0?'val-dn':'');
            info1.innerHTML='<span class="tag-lbl"><b>'+d+'</b></span>開:<span class="'+(o>prev?'val-up':(o<prev?'val-dn':''))+'">'+fmtNum(o)+'</span> 高:<span class="'+(h>prev?'val-up':(h<prev?'val-dn':''))+'">'+fmtNum(h)+'</span> 低:<span class="'+(l>prev?'val-up':(l<prev?'val-dn':''))+'">'+fmtNum(l)+'</span> 收:<span class="'+cls+'">'+fmtNum(c)+' ('+(diff>0?'+':'')+fmtNum(diff)+', '+(pct>0?'+':'')+fmtNum(pct)+'%)</span> 量:'+fmtNum(vols[idx],0)+'張 <span class="tag-lbl"><b>換手:'+fmtNum(turnovers[idx])+'%</b></span> MA5:'+fmtNum(ma5s[idx])+' MA20:'+fmtNum(ma20s[idx])+' MA60:'+fmtNum(ma60s[idx]);
        }
        var b0=calcBounds(currentR0,currentR1);
        pTop.layout.xaxis.range=[currentR0,currentR1];if(pTop.layout.xaxis2)pTop.layout.xaxis2.range=[currentR0,currentR1];
        pTop.layout.yaxis.range=b0.p;if(pTop.layout.yaxis2)pTop.layout.yaxis2.range=b0.v;
        Plotly.newPlot(elTop,pTop.data,pTop.layout,{responsive:true,displayModeBar:false,scrollZoom:false}).then(function(){
            renderInfo(initEnd);
            elTop.on('plotly_relayout',function(ed){
                if(isUpdating)return;
                var r0=ed['xaxis.range[0]']??ed['xaxis2.range[0]']??(ed['xaxis.range']?ed['xaxis.range'][0]:null);
                var r1=ed['xaxis.range[1]']??ed['xaxis2.range[1]']??(ed['xaxis.range']?ed['xaxis.range'][1]:null);
                if(r0===null||r1===null||(Math.abs(r0-currentR0)<0.001&&Math.abs(r1-currentR1)<0.001))return;
                isUpdating=true;var span=r1-r0,maxB=(totalPoints-1)+0.5;
                if(r1>maxB){r1=maxB;r0=r1-span;}currentR0=r0;currentR1=r1;
                var vb=calcBounds(r0,r1);broadcastToSiblings({type:'MCHART_SYNC_XRANGE',r0:r0,r1:r1});
                Plotly.relayout(elTop,{'xaxis.range':[r0,r1],'xaxis2.range':[r0,r1],'yaxis.range':vb.p,'yaxis2.range':vb.v}).finally(function(){setTimeout(function(){isUpdating=false;},20);});
            });
            window.addEventListener('message',function(ev){
                var msg=ev.data||{};
                if(msg.type==='MCHART_SYNC_XRANGE'&&!isUpdating){
                    isUpdating=true;currentR0=msg.r0;currentR1=msg.r1;var vb=calcBounds(currentR0,currentR1);
                    Plotly.relayout(elTop,{'xaxis.range':[currentR0,currentR1],'xaxis2.range':[currentR0,currentR1],'yaxis.range':vb.p,'yaxis2.range':vb.v}).finally(function(){setTimeout(function(){isUpdating=false;},20);});
                }else if(msg.type==='MCHART_SYNC_FOCUS'&&msg.idx>=0)renderInfo(msg.idx);
            });
            function onMove(e){
                var cx=(e.touches&&e.touches.length>0)?e.touches[0].clientX:e.clientX;if(cx===undefined)return;
                var rect=elTop.getBoundingClientRect(),relX=cx-rect.left,xa=elTop._fullLayout?elTop._fullLayout.xaxis:null,ya=elTop._fullLayout?elTop._fullLayout.yaxis:null;
                if(!xa||typeof xa.p2c!=='function')return;
                var pL=xa._offset??80,pLen=xa._length??(rect.width-pL-15);if(relX<pL||relX>pL+pLen)return;
                var idx=Math.round(xa.p2c(relX-pL));
                if(idx>=0&&idx<totalPoints){
                    renderInfo(idx);lineX.style.left=(xa.c2p(idx)+pL)+'px';lineX.style.display='block';
                    if(ya&&typeof ya.c2p==='function'&&closes[idx]!=null){lineY.style.top=(ya.c2p(closes[idx])+(ya._offset||0))+'px';lineY.style.display='block';}
                    broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:idx,showLine:true});
                }
            }
            function onLeave(){lineX.style.display='none';lineY.style.display='none';broadcastToSiblings({type:'MCHART_SYNC_FOCUS',idx:-1,showLine:false});}
            elTop.addEventListener('mousemove',onMove);elTop.addEventListener('touchmove',onMove,{passive:true});
            elTop.addEventListener('touchstart',onMove,{passive:true});elTop.addEventListener('mouseleave',onLeave);
        });
    })();</script>"""
    return (
        tpl.replace("__CID__", chart_id).replace("__HELPERS__", SHARED_JS_HELPERS).replace("__TOP_H__", str(top_height))
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
    fig_tech = getattr(fig_btm, "_fig_tech", fig_btm)

    tpl = COMMON_CSS + """
    <div class="frame-root" id="__CID___tech_root">
        <div id="__CID___info_tech" class="pane-info-bar" style="margin-bottom:3px;">正在載入指標...</div>
        <div id="__CID___tech" class="touch-plot-box" style="height:__TECH_H__px;"><div id="__CID___line_tech" class="sync-crosshair-line"></div></div>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>(function(){
        __HELPERS__
        var pTech=__P_TECH__,dates=__DATES__,ks=__KS__,ds=__DS__,difs=__DIFS__,macds=__MACDS__,oscs=__OSCS__,obvs=__OBVS__,obvMas=__OBVMAS__;
        var bias20s=__BIAS20__,bias120s=__BIAS120__,bias240s=__BIAS240__,bias1200s=__BIAS1200__;
        var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
        var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
        var elTech=document.getElementById('__CID___tech'),infoTech=document.getElementById('__CID___info_tech'),lineTech=document.getElementById('__CID___line_tech');
        function renderInfo(idx){
            if(idx<0||idx>=totalPoints)return;
            var d=dates[idx],oscClass=oscs[idx]>0?'val-up':(oscs[idx]<0?'val-dn':'');
            infoTech.innerHTML='<div><span class="tag-lbl"><b>'+d+'</b></span> <span class="tag-lbl"><b>KD(9)</b></span><span style="color:#e74c3c;">K:'+fmtNum(ks[idx],1)+'</span> <span style="color:#3498db;">D:'+fmtNum(ds[idx],1)+'</span> | <span class="tag-lbl"><b>OBV</b></span><span style="color:#16a085;">OBV:'+fmtNum(obvs[idx],0)+'</span> <span style="color:#8e44ad;">MA20:'+fmtNum(obvMas[idx],0)+'</span></div><div><span class="tag-lbl"><b>MACD('+d+')</b></span><span style="color:#f39c12;">DIF:'+fmtNum(difs[idx])+'</span> <span style="color:#2980b9;">MACD:'+fmtNum(macds[idx])+'</span> OSC:<span class="'+oscClass+'">'+fmtNum(oscs[idx])+'</span> | <span class="tag-lbl"><b>乖離率</b></span><span style="color:#e67e22;">20日:</span>'+fmtBias(bias20s[idx])+' <span style="color:#2980b9;">120日:</span>'+fmtBias(bias120s[idx])+' <span style="color:#8e44ad;">240日:</span>'+fmtBias(bias240s[idx])+' <span style="color:#e74c3c;">1200日:</span>'+fmtBias(bias1200s[idx])+'</div>';
        }
        for(var r=1;r<=4;r++){var kt=r===1?'xaxis':'xaxis'+r;if(pTech.layout&&pTech.layout[kt])pTech.layout[kt].range=[currentR0,currentR1];}
        Plotly.newPlot(elTech,pTech.data,pTech.layout,{responsive:true,displayModeBar:false,scrollZoom:false}).then(function(){
            renderInfo(initEnd);
            elTech.on('plotly_relayout',function(ed){
                if(isUpdating)return;var r0=null,r1=null;
                for(var k=1;k<=4;k++){var p=k===1?'xaxis':'xaxis'+k;if(ed[p+'.range[0]']!==undefined)r0=ed[p+'.range[0]'];if(ed[p+'.range[1]']!==undefined)r1=ed[p+'.range[1]'];}
                if(r0===null||r1===null||(Math.abs(r0-currentR0)<0.001&&Math.abs(r1-currentR1)<0.001))return;
                isUpdating=true;var span=r1-r0,maxB=(totalPoints-1)+0.5;
                if(r1>maxB){r1=maxB;r0=r1-span;}currentR0=r0;currentR1=r1;
                var upd={};for(var i=1;i<=4;i++)upd[(i===1?'xaxis':'xaxis'+i)+'.range']=[r0,r1];
                broadcastToSiblings({type:'MCHART_SYNC_XRANGE',r0:r0,r1:r1});
                Plotly.relayout(elTech,upd).finally(function(){setTimeout(function(){isUpdating=false;},20);});
            });
            window.addEventListener('message',function(ev){
                var msg=ev.data||{};
                if(msg.type==='MCHART_SYNC_XRANGE'&&!isUpdating){
                    isUpdating=true;currentR0=msg.r0;currentR1=msg.r1;
                    var upd={};for(var i=1;i<=4;i++)upd[(i===1?'xaxis':'xaxis'+i)+'.range']=[currentR0,currentR1];
                    Plotly.relayout(elTech,upd).finally(function(){setTimeout(function(){isUpdating=false;},20);});
                }else if(msg.type==='MCHART_SYNC_FOCUS'){
                    if(msg.showLine&&msg.idx>=0){renderInfo(msg.idx);var xa=elTech._fullLayout?elTech._fullLayout.xaxis:null;if(xa&&typeof xa.c2p==='function'){lineTech.style.left=(xa.c2p(msg.idx)+(xa._offset||80))+'px';lineTech.style.display='block';}}
                    else lineTech.style.display='none';
                }
            });
            function onMove(e){
                var cx=(e.touches&&e.touches.length>0)?e.touches[0].clientX:e.clientX;if(cx===undefined)return;
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
    return (
        tpl.replace("__CID__", chart_id).replace("__HELPERS__", SHARED_JS_HELPERS).replace("__TECH_H__", str(tech_height))
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
    fig_chip = getattr(fig_btm, "_fig_chip", fig_btm)

    tpl = COMMON_CSS + """
    <div class="frame-root" id="__CID___chip_root">
        <div id="__CID___info_ms" class="pane-info-bar" style="margin-bottom:3px;">正在載入資券...</div>
        <div id="__CID___info_chip" class="pane-info-bar" style="margin-bottom:3px;">正在載入法人集保...</div>
        <div id="__CID___chip" class="touch-plot-box" style="height:__CHIP_H__px;"><div id="__CID___line_chip" class="sync-crosshair-line"></div></div>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>(function(){
        __HELPERS__
        var pChip=__P_CHIP__,dates=__DATES__,foreigns=__FOREIGNS__,trusts=__TRUSTS__,dealers=__DEALERS__,mDiffs=__MDIFFS__,sDiffs=__SDIFFS__,rat=__RATIOS__;
        var m1_pcts=__M1PCTS__,m2_pcts=__M2PCTS__,m1_thresh=__M1TH__,m2_thresh=__M2TH__;
        var totalPoints=dates.length,initEnd=__INIT_END__,targetDays=Number(__DISP_DAYS__)||20;
        var currentR0=Math.max(0,initEnd-targetDays+1)-0.5,currentR1=initEnd+0.5,isUpdating=false;
        var elChip=document.getElementById('__CID___chip'),infoMs=document.getElementById('__CID___info_ms'),infoChip=document.getElementById('__CID___info_chip'),lineChip=document.getElementById('__CID___line_chip');
        function renderInfo(idx){
            if(idx<0||idx>=totalPoints)return;
            var d=dates[idx],mT=mDiffs[idx]!=null?Number(mDiffs[idx])/1000.0:null,sT=sDiffs[idx]!=null?Number(sDiffs[idx])/1000.0:null;
            infoMs.innerHTML='<span class="tag-lbl"><b>資券[千張]('+d+')</b></span>融資:'+fmtDiff(mT,3)+' 融券:'+fmtDiff(sT,3)+' <span class="tag-lbl"><b>券資比:'+fmtNum(rat[idx])+'%</b></span>';
            infoChip.innerHTML='<span class="tag-lbl"><b>法人集保('+d+')</b></span>外資:'+fmtDiff(foreigns[idx],0)+' 投信:'+fmtDiff(trusts[idx],0)+' 自營:'+fmtDiff(dealers[idx],0)+' | ≥'+m1_thresh+'張: '+fmtNum(m1_pcts[idx])+'% ≥'+m2_thresh+'張: '+fmtNum(m2_pcts[idx])+'%';
        }
        for(var c=1;c<=6;c++){var kc=c===1?'xaxis':'xaxis'+c;if(pChip.layout&&pChip.layout[kc])pChip.layout[kc].range=[currentR0,currentR1];}
        Plotly.newPlot(elChip,pChip.data,pChip.layout,{responsive:true,displayModeBar:false,scrollZoom:false}).then(function(){
            renderInfo(initEnd);
            elChip.on('plotly_relayout',function(ed){
                if(isUpdating)return;var r0=null,r1=null;
                for(var k=1;k<=6;k++){var p=k===1?'xaxis':'xaxis'+k;if(ed[p+'.range[0]']!==undefined)r0=ed[p+'.range[0]'];if(ed[p+'.range[1]']!==undefined)r1=ed[p+'.range[1]'];}
                if(r0===null||r1===null||(Math.abs(r0-currentR0)<0.001&&Math.abs(r1-currentR1)<0.001))return;
                isUpdating=true;var span=r1-r0,maxB=(totalPoints-1)+0.5;
                if(r1>maxB){r1=maxB;r0=r1-span;}currentR0=r0;currentR1=r1;
                var upd={};for(var i=1;i<=6;i++)upd[(i===1?'xaxis':'xaxis'+i)+'.range']=[r0,r1];
                broadcastToSiblings({type:'MCHART_SYNC_XRANGE',r0:r0,r1:r1});
                Plotly.relayout(elChip,upd).finally(function(){setTimeout(function(){isUpdating=false;},20);});
            });
            window.addEventListener('message',function(ev){
                var msg=ev.data||{};
                if(msg.type==='MCHART_SYNC_XRANGE'&&!isUpdating){
                    isUpdating=true;currentR0=msg.r0;currentR1=msg.r1;
                    var upd={};for(var i=1;i<=6;i++)upd[(i===1?'xaxis':'xaxis'+i)+'.range']=[currentR0,currentR1];
                    Plotly.relayout(elChip,upd).finally(function(){setTimeout(function(){isUpdating=false;},20);});
                }else if(msg.type==='MCHART_SYNC_FOCUS'){
                    if(msg.showLine&&msg.idx>=0){renderInfo(msg.idx);var xa=elChip._fullLayout?elChip._fullLayout.xaxis:null;if(xa&&typeof xa.c2p==='function'){lineChip.style.left=(xa.c2p(msg.idx)+(xa._offset||80))+'px';lineChip.style.display='block';}}
                    else lineChip.style.display='none';
                }
            });
            function onMove(e){
                var cx=(e.touches&&e.touches.length>0)?e.touches[0].clientX:e.clientX;if(cx===undefined)return;
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
    return (
        tpl.replace("__CID__", chart_id).replace("__HELPERS__", SHARED_JS_HELPERS).replace("__CHIP_H__", str(chip_height))
        .replace("__P_CHIP__", fig_chip.to_json()).replace("__DATES__", json.dumps(dates_list))
        .replace("__FOREIGNS__", json.dumps(df['Foreign_Net'].fillna(0).tolist() if 'Foreign_Net' in df.columns else [0] * n_pts))
        .replace("__TRUSTS__", json.dumps(df['Trust_Net'].fillna(0).tolist() if 'Trust_Net' in df.columns else [0] * n_pts))
        .replace("__DEALERS__", json.dumps(df['Dealer_Net'].fillna(0).tolist() if 'Dealer_Net' in df.columns else [0] * n_pts))
        .replace("__MDIFFS__", json.dumps(df['Margin_Diff'].fillna(0).tolist() if 'Margin_Diff' in df.columns else [0] * n_pts))
        .replace("__SDIFFS__", json.dumps(df['Short_Diff'].fillna(0).tolist() if 'Short_Diff' in df.columns else [0] * n_pts))
        .replace("__RATIOS__", json.dumps(df['Short_Margin_Ratio'].fillna(0).tolist() if 'Short_Margin_Ratio' in df.columns else [0] * n_pts))
        .replace("__M1PCTS__", json.dumps(df['Major1_Pct'].fillna(0).tolist() if 'Major1_Pct' in df.columns else [0] * n_pts))
        .replace("__M2PCTS__", json.dumps(df['Major2_Pct'].fillna(0).tolist() if 'Major2_Pct' in df.columns else [0] * n_pts))
        .replace("__M1TH__", str(m1_thresh)).replace("__M2TH__", str(m2_thresh))
        .replace("__DISP_DAYS__", str(initial_disp_days)).replace("__INIT_END__", str(end_idx))
    )


def get_broker_tab_html(df: pd.DataFrame, chart_id: str, initial_end_idx: int = None, is_index: bool = False, broker_payload: dict = None) -> str:
    n_pts = len(df)
    end_idx = n_pts - 1 if initial_end_idx is None else initial_end_idx
    dates_list = _extract_dates_list(df)
    safe_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}

    tpl = COMMON_CSS + """<style>
    .b-card{background:#fff;border:1px solid #e2e8f0;border-radius:6px;padding:6px;margin-bottom:8px}
    .b-title{font-size:13px;font-weight:bold;color:#1e293b;background:#f1f5f9;padding:4px 8px;border-radius:4px;margin-bottom:6px;border-left:3px solid #2c3e50}
    .b-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}@media(max-width:720px){.b-grid{grid-template-columns:1fr}}
    .b-wrap{overflow-x:auto;border:1px solid #e2e8f0;border-radius:4px}
    .b-tbl{width:100%;border-collapse:collapse;font-size:11.5px;text-align:right;white-space:nowrap}
    .b-tbl th{background:#f8fafc;color:#334155;font-weight:700;padding:4px 5px;border-bottom:1px solid #cbd5e1}
    .b-tbl td{padding:3px 5px;border-bottom:1px solid #f1f5f9;color:#1e293b}
    .b-tbl th:nth-child(1),.b-tbl td:nth-child(1),.b-tbl th:nth-child(2),.b-tbl td:nth-child(2){text-align:left}
    .gov-badge{display:inline-block;background:#fef3c7;color:#92400e;font-size:10px;padding:0 3px;border-radius:3px;margin-left:3px;border:1px solid #f59e0b}
    .b-bar{width:100%;height:185px;border:1px solid #e2e8f0;border-radius:4px;margin-bottom:6px;background:#fff}
    </style>
    <div class="frame-root" id="__CID___broker_root">
        <div id="__CID___b_hdr" class="pane-info-bar" style="margin-bottom:6px;"></div>
        <div id="__CID___b_tbls"></div>
        <div class="b-card">
            <div class="b-title">5. 區間買賣超統計各前 5 名分點 — 各日買賣超柱狀圖</div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
                <label for="__CID___b_sel" style="font-size:12.5px;font-weight:bold;color:#334155;">統計區間天數：</label>
                <select id="__CID___b_sel" style="padding:4px 8px;font-size:13px;border-radius:4px;border:1px solid #94a3b8;font-weight:bold;">
                    <option value="10" selected>近 10 日（含關注交易日）</option>
                    <option value="20">近 20 日（含關注交易日）</option>
                    <option value="60">近 60 日（含關注交易日）</option>
                </select>
            </div>
            <div id="__CID___b_bars"></div>
        </div>
    </div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>(function(){
        var dates=__DATES__,isIndex=__IS_IDX__,payload=__BROKER_JSON__,curIdx=__INIT_END__;
        var cfg={responsive:true,displayModeBar:false,scrollZoom:false};
        var rootEl=document.getElementById('__CID___broker_root'),hdrEl=document.getElementById('__CID___b_hdr');
        var tblsEl=document.getElementById('__CID___b_tbls'),selEl=document.getElementById('__CID___b_sel'),barsEl=document.getElementById('__CID___b_bars');
        function pushH(){if(!rootEl)return;var h=Math.ceil(rootEl.scrollHeight)+16;if(window.parent&&window.parent!==window)window.parent.postMessage({isStreamlitMessage:true,type:"streamlit:setFrameHeight",height:h},"*");}
        if(typeof ResizeObserver!=='undefined'&&rootEl)new ResizeObserver(pushH).observe(rootEl);
        function makeTbl(title,buyList,sellList){
            function side(lbl,rows,isBuy){
                var h='<div><div style="font-size:12px;font-weight:bold;color:'+(isBuy?'#eb4d4b':'#16a085')+';margin-bottom:3px;">'+lbl+'</div>';
                if(!rows||!rows.length)return h+'<div style="font-size:11.5px;color:#64748b;padding:6px;border:1px solid #e2e8f0;border-radius:4px;">無資料</div></div>';
                h+='<div class="b-wrap"><table class="b-tbl"><thead><tr><th>#</th><th>分點名稱</th><th>買進</th><th>賣出</th><th>買賣超</th><th>佔比</th></tr></thead><tbody>';
                for(var i=0;i<Math.min(10,rows.length);i++){
                    var r=rows[i],net=Number(r.net||0),cls=net>0?'val-up':(net<0?'val-dn':'');
                    h+='<tr><td>'+(i+1)+'</td><td>'+(r.name||'')+(r.sys==='八大官股'?'<span class="gov-badge">官股</span>':'')+'</td><td>'+Number(r.buy||0).toLocaleString()+'</td><td>'+Number(r.sell||0).toLocaleString()+'</td><td class="'+cls+'">'+(net>0?'+':'')+net.toLocaleString()+'</td><td>'+(r.ratio||'-')+'</td></tr>';
                }
                return h+'</tbody></table></div></div>';
            }
            return'<div class="b-card"><div class="b-title">'+title+'</div><div class="b-grid">'+side('🔴 買超前 10 名 (張)',buyList,true)+side('🟢 賣超前 10 名 (張)',sellList,false)+'</div></div>';
        }
        function render(idx){
            if(idx<0||idx>=dates.length)return;curIdx=idx;var d=dates[idx];
            if(isIndex){hdrEl.innerHTML='<b>'+d+'</b> ｜ 指數標的不適用券商分點統計';tblsEl.innerHTML='';barsEl.innerHTML='';pushH();return;}
            var byD=(payload&&payload.by_date)?payload.by_date:{},dayData=byD[d];
            if(!dayData){
                var ks=Object.keys(byD).sort(),fb=ks.length?ks[ks.length-1]:null;
                if(fb){dayData=byD[fb];hdrEl.innerHTML='<b>關注交易日：'+d+'</b>（目前顯示已收錄基準日 <b>'+fb+'</b> 之分點統計；若需指定歷史日請於側邊欄設定基準日）';}
                else{hdrEl.innerHTML='<b>關注交易日：'+d+'</b> ｜ 尚無分點明細資料';tblsEl.innerHTML='';barsEl.innerHTML='';pushH();return;}
            }else hdrEl.innerHTML='<b>關注交易日：'+d+'</b> ｜ 券商分點買賣超統計與雲端累積逐日明細（單位：張）';
            var r1=dayData.w1||{},r10=dayData.w10||{},r20=dayData.w20||{},r60=dayData.w60||{};
            tblsEl.innerHTML=makeTbl('1. 當日分點統計買賣超各前十名（'+(r1.range_label||d)+'）',r1.buy,r1.sell)+makeTbl('2. 前 10 日至關注交易日分點統計買賣超各前十名（'+(r10.range_label||'')+'）',r10.buy,r10.sell)+makeTbl('3. 前 20 日至關注交易日分點統計買賣超各前十名（'+(r20.range_label||'')+'）',r20.buy,r20.sell)+makeTbl('4. 前 60 日至關注交易日分點統計買賣超各前十名（'+(r60.range_label||'')+'）',r60.buy,r60.sell);
            var winDays=selEl?selEl.value:'10',winObj=dayData['w'+winDays]||r10;
            var t5b=winObj.top5_buy_series||[],t5s=winObj.top5_sell_series||[];
            if(!t5b.length&&!t5s.length){barsEl.innerHTML='<div style="font-size:12px;color:#64748b;padding:6px;">此區間尚無前五大分點逐日柱狀圖資料。</div>';pushH();return;}
            var bHtml='<div style="font-size:12.5px;font-weight:bold;color:#eb4d4b;margin:4px 0;">🔴 區間累計買超前 5 名分點 — 每日買賣超柱狀圖</div>';
            for(var bi=0;bi<t5b.length;bi++)bHtml+='<div id="__CID___bb_'+bi+'" class="b-bar"></div>';
            bHtml+='<div style="font-size:12.5px;font-weight:bold;color:#16a085;margin:6px 0 4px 0;">🟢 區間累計賣超前 5 名分點 — 每日買賣超柱狀圖</div>';
            for(var si=0;si<t5s.length;si++)bHtml+='<div id="__CID___bs_'+si+'" class="b-bar"></div>';
            barsEl.innerHTML=bHtml;
            function drawBar(domId,item,lbl){
                var dom=document.getElementById(domId);if(!dom)return;
                var xd=item.dates||[],yn=item.nets||[],cols=yn.map(function(v){return Number(v)>=0?'#eb4d4b':'#2ecc71';});
                var monthTickVals=[],monthTickText=[],curYm=null;
                for(var di=0;di<xd.length;di++){var ds=String(xd[di]||'');if(ds.length>=7){var ym=ds.slice(0,7);if(ym!==curYm){curYm=ym;monthTickVals.push(ds);monthTickText.push(ds.slice(5,7)+'月');}}}
                var sum=yn.reduce(function(a,v){return a+Number(v||0);},0);
                var titleStr=lbl+'：'+item.name+'（主表'+winDays+'日累計:'+(item.total_net>0?'+':'')+Number(item.total_net||0).toLocaleString()+'張｜已收錄近'+yn.length+'日逐日加總:'+(sum>0?'+':'')+sum.toLocaleString()+'張）';
                Plotly.newPlot(dom,[{x:xd,y:yn,type:'bar',marker:{color:cols},hovertemplate:'%{x}<br>買賣超: %{y:,} 張<extra></extra>'}],{
                    title:{text:titleStr,font:{size:11}},margin:{l:48,r:12,t:28,b:24},height:180,template:'plotly_white',
                    xaxis:{type:'category',tickvals:monthTickVals,ticktext:monthTickText,tickangle:0,tickfont:{size:11},fixedrange:true},
                    yaxis:{tickfont:{size:10},fixedrange:true,zeroline:true,zerolinecolor:'#94a3b8'},showlegend:false
                },cfg);
            }
            for(var bi2=0;bi2<t5b.length;bi2++)drawBar('__CID___bb_'+bi2,t5b[bi2],'買超 Top '+(bi2+1));
            for(var si2=0;si2<t5s.length;si2++)drawBar('__CID___bs_'+si2,t5s[si2],'賣超 Top '+(si2+1));
            setTimeout(pushH,80);setTimeout(pushH,300);
        }
        if(selEl)selEl.addEventListener('change',function(){render(curIdx);});
        window.addEventListener('message',function(ev){var m=ev.data||{};if(m.type==='MCHART_SYNC_FOCUS'&&m.showLine&&m.idx>=0)render(m.idx);});
        render(initEnd);
    })();</script>"""
    return (
        tpl.replace("__CID__", chart_id).replace("__DATES__", json.dumps(dates_list))
        .replace("__IS_IDX__", "true" if is_index else "false").replace("__BROKER_JSON__", json.dumps(safe_payload, ensure_ascii=False))
        .replace("__INIT_END__", str(end_idx))
    )
# EOF frontend.py
