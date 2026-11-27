"""
frnt_broker.py - 分點統計排行榜與分點日況（含八大官股8行庫）前端 HTML/JS 渲染模組
(自 frontend.py 依邏輯職責拆分，並將八大官股分點日況8子圖標題改為藍色字體、字體大小同統計區間天數)
版本: 202611271327
"""

import json
import pandas as pd

MODULE_NAME = "frnt_broker"
MODULE_VERSION = "202611271327"

# 【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
# 1. 修改目的：於 `.touch-plot-box` 與圖表內層 SVG 文字（`svg,svg text`）加入 `-webkit-touch-callout:none!important` 與 `user-select:none!important`，
#    防止手機瀏覽器長按圖表時觸發震動選取選單與進入 Plotly 內建 SVG 文字編輯輸入框。
# 2. 防呆防錯原因：維持 `.pane-info-bar` 資訊條可正常顯示與自動折行，不影響既有觸控滑動與拖曳平移操作。
COMMON_CSS = """<style>
html,body{margin:0;padding:0;background:transparent;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.frame-root{position:relative;width:100%;box-sizing:border-box;padding-bottom:4px}
.touch-plot-box{position:relative;touch-action:pan-y!important;user-select:none!important;-webkit-user-select:none!important;-webkit-touch-callout:none!important;width:100%!important;overflow:hidden}
.touch-plot-box svg,.touch-plot-box svg text{user-select:none!important;-webkit-user-select:none!important;-webkit-touch-callout:none!important}
.pane-info-bar{font-size:13px;color:#2c3e50;background:#f8fafc;padding:4px 6px;border-radius:4px;border:1px solid #e2e8f0;white-space:normal;line-height:1.38;overflow-x:auto}
@media(max-width:720px){.pane-info-bar{font-size:11.5px;line-height:1.32;padding:3px 5px}}
.val-up{color:#eb4d4b!important;font-weight:bold}.val-dn{color:#16a085!important;font-weight:bold}.tag-lbl{margin-right:4px}
.sync-crosshair-line{position:absolute;top:0;bottom:0;width:1px;border-left:1px dashed rgba(44,62,80,.85);pointer-events:none;display:none;z-index:999}
.sync-price-line{position:absolute;left:80px;right:15px;height:1px;border-top:1px dashed rgba(44,62,80,.75);pointer-events:none;display:none;z-index:999}
</style>"""

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


def _extract_dates_list(df: pd.DataFrame) -> list:
    s = df['Date'] if 'Date' in df.columns else df.index
    return s.strftime('%Y-%m-%d').tolist() if hasattr(s, 'strftime') else [str(x)[:10] for x in s]


def _detect_gov_index_unit(
    df: pd.DataFrame,
    chart_id: str,
    is_index: bool,
    is_gov_index: bool = None,
    pure_code: str = None
) -> tuple:
    """
    優先採用 app.py 明確傳入之 `is_gov_index` 與 `pure_code` 判定是否為大盤加權（^TWII）或櫃買（^TWOII）八大官股模式，
    回傳 (is_gov_index, unit_label, title_prefix)。上市加權與上櫃櫃買八大官股單位皆為「萬元」。
    """
    if is_index:
        return False, "張", "券商分點"
    code_up = str(pure_code or "").strip().upper()
    if is_gov_index is not None:
        if not bool(is_gov_index):
            return False, "張", "券商分點"
        is_twoii = (code_up == "^TWOII") or (
            ('Margin_Money_Bal' in df.columns and (df['Margin_Money_Bal'].fillna(0) != 0).any())
            and ('Margin_Bal' not in df.columns or (df['Margin_Bal'].fillna(0) == 0).all())
        )
        return (True, "萬元", "上櫃八大官股") if is_twoii else (True, "萬元", "上市八大官股")

    if code_up in ("^TWII", "^TWOII"):
        return (True, "萬元", "上櫃八大官股") if code_up == "^TWOII" else (True, "萬元", "上市八大官股")

    cid_up = str(chart_id or "").upper()
    has_short_maint = ('Short_Maint_Pct' in df.columns and not df['Short_Maint_Pct'].dropna().empty)
    no_inst_flow = (
        ('Foreign_Net' not in df.columns or (df['Foreign_Net'].fillna(0) == 0).all())
        and ('Trust_Net' not in df.columns or (df['Trust_Net'].fillna(0) == 0).all())
        and ('Dealer_Net' not in df.columns or (df['Dealer_Net'].fillna(0) == 0).all())
    )
    has_money_bal = ('Margin_Money_Bal' in df.columns and (df['Margin_Money_Bal'].fillna(0) != 0).any())
    zero_margin_bal = ('Margin_Bal' not in df.columns or (df['Margin_Bal'].fillna(0) == 0).all())
    is_twoii = ("^TWOII" in cid_up) or (has_short_maint and no_inst_flow and has_money_bal and zero_margin_bal)
    is_twii = ("^TWII" in cid_up) or (has_short_maint and no_inst_flow and not is_twoii)
    if is_twoii:
        return True, "萬元", "上櫃八大官股"
    if is_twii:
        return True, "萬元", "上市八大官股"
    return False, "張", "券商分點"


def get_broker_stats_tab_html(
    df: pd.DataFrame,
    broker_payload: dict = None,
    chart_id: str = "mchart_broker_stats",
    end_idx: int = None,
    disp_days: int = 20,
    is_mobile: bool = False,
    initial_end_idx: int = None,
    is_index: bool = None,
    is_gov_index: bool = None,
    pure_code: str = None
) -> str:
    n_pts = len(df)
    resolved_end = end_idx if end_idx is not None else (initial_end_idx if initial_end_idx is not None else (n_pts - 1))
    dates_list = _extract_dates_list(df)
    if is_index is None:
        is_index = len(dates_list) == 0 or (df['Turnover_Rate'].max() == 0 and df['Foreign_Net'].abs().max() == 0)
    safe_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}
    is_gov_idx, unit_lbl, title_prefix = _detect_gov_index_unit(
        df, chart_id, bool(is_index), is_gov_index=is_gov_index, pure_code=pure_code
    )

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
    is_index: bool = None,
    is_gov_index: bool = None,
    pure_code: str = None
) -> str:
    """
    【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    1. 修改目的：依指示將八大官股分點日況 8 子圖標題（renderGov8Banks）改為藍色字體（#1d4ed8），
       字體大小設為 12.5px（與上方「統計區間天數：」標籤完全一致）。
    2. 防呆防錯原因：維持柱狀圖紅買（#eb4d4b）綠賣（#2ecc71）與 staticPlot 鎖死配置不變。
    """
    n_pts = len(df)
    resolved_end = end_idx if end_idx is not None else (initial_end_idx if initial_end_idx is not None else (n_pts - 1))
    dates_list = _extract_dates_list(df)
    if is_index is None:
        is_index = len(dates_list) == 0 or (df['Turnover_Rate'].max() == 0 and df['Foreign_Net'].abs().max() == 0)
    safe_payload = broker_payload if isinstance(broker_payload, dict) else {"by_date": {}}
    is_gov_idx, unit_lbl, title_prefix = _detect_gov_index_unit(
        df, chart_id, bool(is_index), is_gov_index=is_gov_index, pure_code=pure_code
    )

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
            var tr={x:axisDates,y:yVals,type:'bar',marker:{color:cols},hoverinfo:'skip'};
            var lay={
                width:boxW,height:182,autosize:false,
                title:{text:'<b>'+(bIdx+1)+'. '+item.bank+' — '+selStk+' (區間:'+totStr+unitLbl+')</b>',font:{size:12.5,color:'#1d4ed8'},x:0.02,xanchor:'left'},
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
    is_index: bool = None,
    is_gov_index: bool = None,
    pure_code: str = None
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
        is_index=is_index,
        is_gov_index=is_gov_index,
        pure_code=pure_code
    )
## EOF frnt_broker.py
