# ==============================================================================
# 模組名稱: app
# 模組版本: 202610280020
# 核心職責: 主程式進入點、啟動自動拉取 Drive 資料庫、UI 狀態管理與巡航導航
# ==============================================================================

MODULE_NAME = "app"
MODULE_VERSION = "202610280020"

import re
from datetime import datetime

# 引入系統獨立模組
import config
from storage import load_stock_history, save_stock_history, clear_stock_history
from data_fetcher import get_stock_chinese_name
from chart_builder import build_split_figures
from frontend import get_component_html, get_legend_html

# 嘗試在系統最優先載入時，自 Google Drive 拉回既有的 SQLite 資料庫與歷程清單
try:
    import cloud_sync
    cloud_sync.pull_from_drive(config.DB_FILE)
    cloud_sync.pull_from_drive(config.HISTORY_FILE)
    cloud_sync.pull_from_drive(config.NAME_CACHE_FILE)
except Exception:
    pass

# 收集所有已載入模組之版本號
SYSTEM_VERSIONS = {
    "app": MODULE_VERSION,
    "config": getattr(config, "MODULE_VERSION", "N/A"),
}
try:
    import cloud_sync
    SYSTEM_VERSIONS["cloud_sync"] = getattr(cloud_sync, "MODULE_VERSION", "N/A")
except Exception:
    pass

try:
    import storage
    SYSTEM_VERSIONS["storage"] = getattr(storage, "MODULE_VERSION", "N/A")
except Exception:
    pass

try:
    import data_fetcher
    SYSTEM_VERSIONS["data_fetcher"] = getattr(data_fetcher, "MODULE_VERSION", "N/A")
except Exception:
    pass

try:
    import indicators
    SYSTEM_VERSIONS["indicators"] = getattr(indicators, "MODULE_VERSION", "N/A")
except Exception:
    pass

try:
    import chart_builder
    SYSTEM_VERSIONS["chart_builder"] = getattr(chart_builder, "MODULE_VERSION", "N/A")
except Exception:
    pass

try:
    import frontend
    SYSTEM_VERSIONS["frontend"] = getattr(frontend, "MODULE_VERSION", "N/A")
except Exception:
    pass

# ==============================================================================
# Google Colab 環境邏輯
# ==============================================================================
if config.IS_COLAB:
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    stock_hist = load_stock_history()
    hist_options = [f"{h['code']} ({h['name']})" if h.get('name') else h['code'] for h in stock_hist]

    c_hist_dropdown = widgets.Dropdown(
        options=["(選擇歷史標的)"] + hist_options,
        value="(選擇歷史標的)",
        description='歷史紀錄:',
        layout=widgets.Layout(width='230px')
    )
    c_ticker = widgets.Text(value="1303", description='股票代碼:', layout=widgets.Layout(width='170px'))
    c_btn_prev = widgets.Button(description='⏮ 上一個', button_style='info', layout=widgets.Layout(width='85px'))
    c_btn_next = widgets.Button(description='⏭ 下一個', button_style='info', layout=widgets.Layout(width='85px'))

    def on_dropdown_select(change):
        if change['new'] and change['new'] != "(選擇歷史標的)":
            m = re.search(r'\d+', change['new'])
            if m:
                c_ticker.value = m.group(0)
                c_on_search(None)
    c_hist_dropdown.observe(on_dropdown_select, names='value')

    def navigate_history_colab(direction):
        hist = load_stock_history()
        if not hist: return
        codes = [h['code'] for h in hist]
        cur = c_ticker.value.strip()
        idx = codes.index(cur) if cur in codes else 0
        new_idx = (idx + direction) % len(codes)
        c_ticker.value = codes[new_idx]
        c_on_search(None, record_history=False)

    c_btn_prev.on_click(lambda b: navigate_history_colab(-1))
    c_btn_next.on_click(lambda b: navigate_history_colab(1))

    c_period = widgets.Dropdown(options=['6mo', '1y', '2y', '5y', 'max'], value='1y', description="下載區間:", layout=widgets.Layout(width='160px'))
    c_mode = widgets.Dropdown(options=['手機版 (Mobile) - 預設20日', '筆電版 (Desktop) - 預設60日'], value='手機版 (Mobile) - 預設20日', description="模式切換:", layout=widgets.Layout(width='240px'))
    c_days = widgets.BoundedIntText(value=20, min=5, max=2000, step=5, description="顯示日數:", layout=widgets.Layout(width='150px'))
    c_base_date = widgets.DatePicker(value=datetime.now().date(), description='基準日:', layout=widgets.Layout(width='180px'))

    def on_mode_change(change):
        if '筆電版' in change['new']:
            c_days.value = 60
        else:
            c_days.value = 20
    c_mode.observe(on_mode_change, names='value')

    c_m1 = widgets.Dropdown(options=[100, 200, 400, 600, 800, 1000], value=1000, description='大戶1:')
    c_m2 = widgets.Dropdown(options=[100, 200, 400, 600, 800, 1000], value=400, description='大戶2:')
    c_btn = widgets.Button(description='查詢', button_style='primary')
    c_clear_btn = widgets.Button(description='清除歷程', button_style='danger')
    
    legend_str = get_legend_html(SYSTEM_VERSIONS)
    c_legend = widgets.HTML(value=legend_str)

    def c_on_clear(b):
        clear_stock_history()
        c_hist_dropdown.options, c_hist_dropdown.value, c_ticker.value = ["(選擇歷史標的)"], "(選擇歷史標的)", ""
    c_clear_btn.on_click(c_on_clear)

    c_ui = widgets.VBox([
        widgets.HBox([c_hist_dropdown, c_ticker, c_period, c_mode]),
        widgets.HBox([c_base_date, c_days, c_m1, c_m2, c_btn, c_clear_btn]),
        c_legend,
        widgets.HBox([c_btn_prev, c_btn_next])
    ])
    c_out = widgets.Output()

    is_running = False
    def c_on_search(b, record_history=True):
        global is_running
        if is_running: return
        is_running = True
        try:
            is_mobile = ('手機版' in c_mode.value)
            pure_input = re.search(r'\d+', c_ticker.value)
            target_symbol = pure_input.group(0) if pure_input else c_ticker.value

            fig_top, fig_btm, df, c_name, end_idx, disp_n = build_split_figures(
                target_symbol, c_period.value, c_days.value, c_base_date.value, c_m1.value, c_m2.value, is_mobile=is_mobile
            )
            if fig_top is not None:
                if record_history:
                    save_stock_history(target_symbol, c_name)
                c_hist_dropdown.options = ["(選擇歷史標的)"] + [f"{h['code']} ({h['name']})" if h.get('name') else h['code'] for h in load_stock_history()]
                html_str = get_component_html(fig_top, fig_btm, df, target_symbol, c_m1.value, c_m2.value, end_idx, disp_n, is_mobile=is_mobile)
                with c_out:
                    clear_output(wait=True)
                    display(HTML(html_str))
            else:
                with c_out:
                    clear_output(wait=True)
                    print(f"查無資料: {c_ticker.value}")
        finally:
            is_running = False

    c_btn.on_click(lambda b: c_on_search(b, record_history=True))
    c_ticker.on_submit(lambda b: c_on_search(b, record_history=True))

    display(c_ui, c_out)
    c_on_search(None, record_history=False)

# ==============================================================================
# Streamlit Cloud 環境邏輯
# ==============================================================================
else:
    import streamlit as st
    import streamlit.components.v1 as components

    # 確保首次進網頁時載入歷史清單
    stock_hist = load_stock_history()
    hist_options = [f"{h['code']} ({h['name']})" if h.get('name') else h['code'] for h in stock_hist]

    if "ticker_input" not in st.session_state:
        st.session_state["ticker_input"] = "1303"

    def on_prev_click():
        hist = load_stock_history()
        if hist:
            codes = [h['code'] for h in hist]
            cur = st.session_state.get("ticker_input", "1303").strip()
            idx = codes.index(cur) if cur in codes else 0
            st.session_state["ticker_input"] = codes[(idx - 1) % len(codes)]

    def on_next_click():
        hist = load_stock_history()
        if hist:
            codes = [h['code'] for h in hist]
            cur = st.session_state.get("ticker_input", "1303").strip()
            idx = codes.index(cur) if cur in codes else 0
            st.session_state["ticker_input"] = codes[(idx + 1) % len(codes)]

    st.sidebar.title("參數設定")

    def on_hist_change():
        sel = st.session_state.get("hist_dropdown_key")
        if sel and sel != "(選擇歷史標的)":
            m = re.search(r'\d+', sel)
            if m:
                st.session_state["ticker_input"] = m.group(0)

    st.sidebar.selectbox(
        "歷史紀錄快速選取",
        options=["(選擇歷史標的)"] + hist_options,
        index=0,
        key="hist_dropdown_key",
        on_change=on_hist_change
    )

    s_ticker = st.sidebar.text_input("股票代碼 (直接鍵入)", key="ticker_input")

    if st.sidebar.button("清除歷史記錄", type="secondary"):
        clear_stock_history()
        st.sidebar.success("已清除歷史紀錄並同步！")
        st.rerun()

    s_period = st.sidebar.selectbox("下載區間", options=['6mo', '1y', '2y', '5y', 'max'], index=1)
    s_mode = st.sidebar.selectbox("模式切換", options=['手機版 (Mobile) - 預設20日', '筆電版 (Desktop) - 預設60日'], index=0)
    s_days = st.sidebar.number_input("顯示日數", min_value=5, max_value=2000, value=20 if '手機版' in s_mode else 60, step=5)
    s_base_date = st.sidebar.date_input("基準日 (預設為最新)", value=datetime.now().date())
    s_m1 = st.sidebar.selectbox("大戶1門檻(張)", options=[100, 200, 400, 600, 800, 1000], index=5)
    s_m2 = st.sidebar.selectbox("大戶2門檻(張)", options=[100, 200, 400, 600, 800, 1000], index=2)
    s_btn = st.sidebar.button("查詢", type="primary")

    is_mobile = ('手機版' in s_mode)
    status_box = st.empty()
    
    # 呈現頂部圖例與版本資訊
    legend_str = get_legend_html(SYSTEM_VERSIONS)
    st.markdown(legend_str, unsafe_allow_html=True)

    # 緊湊導航控制列 (強制手機端水平並排且縮小)
    c_btn1, c_btn2, _c_space = st.columns([1, 1, 4])
    with c_btn1:
        st.button("⏮ 上一個", use_container_width=True, on_click=on_prev_click)
    with c_btn2:
        st.button("⏭ 下一個", use_container_width=True, on_click=on_next_click)

    pure_input = re.search(r'\d+', st.session_state["ticker_input"])
    target_symbol = pure_input.group(0) if pure_input else st.session_state["ticker_input"]

    fig_top, fig_btm, df, c_name, end_idx, disp_n = build_split_figures(
        target_symbol, s_period, s_days, s_base_date, s_m1, s_m2, is_mobile=is_mobile, status_placeholder=status_box
    )
    if status_box:
        status_box.empty()

    if fig_top is not None:
        if s_btn:
            save_stock_history(target_symbol, c_name)
        total_h = 1820 if is_mobile else 1880
        components.html(
            get_component_html(fig_top, fig_btm, df, target_symbol, s_m1, s_m2, end_idx, disp_n, is_mobile=is_mobile),
            height=total_h,
            scrolling=False
        )
    else:
        st.error(f"查無資料: {target_symbol}")
