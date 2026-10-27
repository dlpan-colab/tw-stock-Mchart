"""
台股技術與籌碼分析系統 - 主程式進入點模組
負責彙整所有 7 個獨立模組之版本、管理 Streamlit / Google Colab 狀態機、
巡航導航（上一個/下一個）防洗牌與回呼防崩潰機制，以及響應式容器渲染。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "app"
MODULE_VERSION = "202610271400"

import os
import sys
import logging
from typing import Dict, List, Optional

# 設定日誌級別
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ==========================================
# 1. 導入系統全部獨立模組
# ==========================================
import config
import cloud_sync
import storage
import data_fetcher
import indicators
import chart_builder
import frontend

# ==========================================
# 2. 全域模組版本收集
# ==========================================
def collect_all_module_versions() -> Dict[str, str]:
    """彙整所有模組的獨立版本識別碼"""
    return {
        getattr(config, "MODULE_NAME", "config"): getattr(config, "MODULE_VERSION", "N/A"),
        getattr(cloud_sync, "MODULE_NAME", "cloud_sync"): getattr(cloud_sync, "MODULE_VERSION", "N/A"),
        getattr(storage, "MODULE_NAME", "storage"): getattr(storage, "MODULE_VERSION", "N/A"),
        getattr(data_fetcher, "MODULE_NAME", "data_fetcher"): getattr(data_fetcher, "MODULE_VERSION", "N/A"),
        getattr(indicators, "MODULE_NAME", "indicators"): getattr(indicators, "MODULE_VERSION", "N/A"),
        getattr(chart_builder, "MODULE_NAME", "chart_builder"): getattr(chart_builder, "MODULE_VERSION", "N/A"),
        getattr(frontend, "MODULE_NAME", "frontend"): getattr(frontend, "MODULE_VERSION", "N/A"),
        MODULE_NAME: MODULE_VERSION,
    }


def render_version_legend_html() -> str:
    """生成包含全部模組版本的頂部圖例欄位"""
    versions = collect_all_module_versions()
    ver_badges = "".join(
        f"<span style='background:#334155; padding:2px 6px; border-radius:4px; margin-right:4px;'>{k}:{v[-8:]}</span>"
        for k, v in versions.items()
    )
    legend_html = f"""
    {frontend.LEGEND_HTML}
    <div style="background-color: #0F172A; border: 1px solid #1E293B; border-radius: 6px; padding: 6px 12px; margin-bottom: 8px; font-family: monospace; font-size: 11px; color: #94A3B8;">
      <span style="color: #38BDF8; font-weight: bold;">模組版本：</span> {ver_badges}
    </div>
    """
    return legend_html


# ==========================================
# 3. 核心數據處理流程 (雙環境通用)
# ==========================================
def run_analysis_pipeline(stock_id: str, lookback_days: int) -> Optional[str]:
    """
    執行分析運算並生成 HTML 視圖：
    1. 爬取與快取中文名稱
    2. yfinance 日 K 抓取、Volume > 0 過濾、盤中即時補點
    3. TDCC 集保分級增量爬蟲同步
    4. FinMind 法人與資券資料庫同步
    5. 技術指標與大戶自由流通換手率計算
    6. Plotly 主副雙圖建構與互動 HTML 生成
    """
    stock_id = str(stock_id).strip().upper()
    stock_name = data_fetcher.get_tw_stock_name(stock_id)

    # 1. 取得日 K 與發行股數
    df, shares_outstanding = data_fetcher.fetch_kline_data(stock_id, lookback_days=lookback_days)
    if df.empty or len(df) < 5:
        logger.warning(f"標的 {stock_id} 查無足夠之交易資料。")
        return None

    # 2. 增量同步籌碼 (TDCC 與 FinMind)
    try:
        data_fetcher.sync_tdcc_distribution(stock_id)
        data_fetcher.sync_finmind_chip_data(stock_id, lookback_days=lookback_days)
    except Exception as e:
        logger.warning(f"同步第三方籌碼資料庫時發生輕微異常: {e}")

    # 3. 計算全量技術與籌碼特徵指標
    df = indicators.process_all_indicators(df, stock_id, shares_outstanding)

    # 4. 繪製圖表
    fig_main = chart_builder.build_main_chart(df, stock_name, stock_id)
    fig_sub = chart_builder.build_sub_chart(df)

    # 5. 輸出整合互動式 HTML
    html_str = frontend.get_component_html(fig_main, fig_sub, df, stock_id, stock_name)
    return html_str


# ==========================================
# 4. Google Colab 執行分流實作
# ==========================================
def run_in_colab():
    """Google Colab 環境進入點：掛載雲端硬碟、ipywidgets 控制列與 HTML 渲染"""
    try:
        from google.colab import drive
        drive.mount('/content/drive', force_remount=False)
    except Exception as e:
        logger.warning(f"Colab Drive 掛載跳過或失敗: {e}")

    cloud_sync.cloud_sync_manager.sync_all_from_cloud()

    import ipywidgets as widgets
    from IPython.display import HTML, display, clear_output

    history = storage.history_manager.load_history()
    current_stock = history[0] if history else "2330"

    out = widgets.Output()

    txt_ticker = widgets.Text(value=current_stock, description="代碼:", layout=widgets.Layout(width="180px"))
    dd_history = widgets.Dropdown(options=history, value=current_stock if current_stock in history else None, description="歷史:", layout=widgets.Layout(width="200px"))
    slider_days = widgets.IntSlider(value=180, min=60, max=500, step=10, description="日數:", layout=widgets.Layout(width="280px"))

    btn_query = widgets.Button(description="查詢標的", button_style="primary", layout=widgets.Layout(width="100px"))
    btn_prev = widgets.Button(description="⏮ 上一個", button_style="info", layout=widgets.Layout(width="90px"))
    btn_next = widgets.Button(description="⏭ 下一個", button_style="info", layout=widgets.Layout(width="90px"))
    btn_clear = widgets.Button(description="清除歷史", button_style="warning", layout=widgets.Layout(width="90px"))

    def render_chart(ticker: str, days: int):
        with out:
            clear_output(wait=True)
            display(HTML(render_version_legend_html()))
            display(HTML(f"<div style='color:#38BDF8; font-family:monospace;'>正在運算分析標的：{ticker} ...</div>"))
            html_content = run_analysis_pipeline(ticker, days)
            clear_output(wait=True)
            display(HTML(render_version_legend_html()))
            if html_content:
                display(HTML(f"<iframe srcdoc='{html_content.replace(\"'\", \"'\")}' style='width:100%; height:1880px; border:none;'></iframe>"))
            else:
                display(HTML("<div style='color:#EF4444;'>查無此標的之有效 K 線資料。</div>"))

    def on_query_clicked(_):
        ticker = txt_ticker.value.strip().upper()
        if ticker:
            # 手動查詢：置頂儲存
            updated_h = storage.history_manager.save_manual_query(ticker)
            dd_history.options = updated_h
            dd_history.value = ticker
            cloud_sync.cloud_sync_manager.push_file(config.HISTORY_FILE_PATH)
            render_chart(ticker, slider_days.value)

    def on_history_selected(change):
        if change.get("new"):
            t = change["new"]
            txt_ticker.value = t
            # 歷史切換不洗牌置頂
            render_chart(t, slider_days.value)

    def on_prev_clicked(_):
        nxt = storage.history_manager.get_adjacent_ticker(txt_ticker.value, "prev")
        txt_ticker.value = nxt
        dd_history.value = nxt
        render_chart(nxt, slider_days.value)

    def on_next_clicked(_):
        nxt = storage.history_manager.get_adjacent_ticker(txt_ticker.value, "next")
        txt_ticker.value = nxt
        dd_history.value = nxt
        render_chart(nxt, slider_days.value)

    def on_clear_clicked(_):
        if config.HISTORY_FILE_PATH.exists():
            config.HISTORY_FILE_PATH.unlink()
        cloud_sync.cloud_sync_manager.delete_remote_file("stock_history.json")
        dd_history.options = ["2330"]
        txt_ticker.value = "2330"
        with out:
            clear_output()
            print("歷史紀錄已清空。")

    btn_query.on_click(on_query_clicked)
    btn_prev.on_click(on_prev_clicked)
    btn_next.on_click(on_next_clicked)
    btn_clear.on_click(on_clear_clicked)
    dd_history.observe(on_history_selected, names="value")

    ui_box = widgets.VBox([
        widgets.HBox([txt_ticker, dd_history, slider_days]),
        widgets.HBox([btn_query, btn_prev, btn_next, btn_clear]),
        out
    ])
    display(ui_box)
    render_chart(txt_ticker.value, slider_days.value)


# ==========================================
# 5. Streamlit 執行分流實作
# ==========================================
def run_in_streamlit():
    """
    Streamlit Cloud / Local 環境進入點：
    嚴格防護 StreamlitWidgetAlreadyInstantiatedError，
    以 on_click 回呼機制更新 session_state，杜絕巡航洗牌死循環。
    """
    import streamlit as st
    import streamlit.components.v1 as components

    # 頁面寬版配置
    st.set_page_config(
        page_title="台股技術與籌碼分析系統",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 注入行動端專屬水平緊湊按鈕 CSS
    st.markdown(frontend.MOBILE_COMPACT_BUTTON_CSS, unsafe_allow_html=True)

    # 啟動時雲端同步
    if "cloud_synced" not in st.session_state:
        cloud_sync.cloud_sync_manager.sync_all_from_cloud()
        st.session_state["cloud_synced"] = True

    # 載入歷史清單（保證不洗牌）
    history_list = storage.history_manager.load_history()

    # 初始化 session_state
    if "ticker_input" not in st.session_state:
        st.session_state["ticker_input"] = history_list[0] if history_list else "2330"

    # ==========================================
    # 【關鍵防護】按鈕 on_click 回呼函式
    # 必須在腳本最初期結算，嚴禁在 widget 生成後覆寫 state
    # ==========================================
    def on_prev_click():
        cur = st.session_state.get("ticker_input", "2330")
        target = storage.history_manager.get_adjacent_ticker(cur, "prev")
        st.session_state["ticker_input"] = target

    def on_next_click():
        cur = st.session_state.get("ticker_input", "2330")
        target = storage.history_manager.get_adjacent_ticker(cur, "next")
        st.session_state["ticker_input"] = target

    # ---------------- 側邊欄配置 (Sidebar) ----------------
    with st.sidebar:
        st.markdown("### 🔍 標的與參數控制")

        # 歷史紀錄快速選取 (選取時不洗牌)
        selected_hist = st.selectbox(
            "歷史查詢清單",
            options=history_list,
            index=history_list.index(st.session_state["ticker_input"]) if st.session_state["ticker_input"] in history_list else 0
        )
        if selected_hist != st.session_state["ticker_input"]:
            st.session_state["ticker_input"] = selected_hist

        # 股票代碼輸入框 (雙向綁定 key="ticker_input")
        ticker = st.text_input("股票代碼", key="ticker_input")

        lookback_days = st.slider("顯示日數", min_value=60, max_value=400, value=180, step=10)

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            s_btn = st.button("查詢標的", type="primary", use_container_width=True)
        with col_s2:
            clear_btn = st.button("清除歷史", use_container_width=True)

        if clear_btn:
            if config.HISTORY_FILE_PATH.exists():
                config.HISTORY_FILE_PATH.unlink()
            cloud_sync.cloud_sync_manager.delete_remote_file("stock_history.json")
            st.session_state["ticker_input"] = "2330"
            st.rerun()

        # 僅在點擊「查詢」時才執行置頂存檔，巡航時絕不洗牌
        if s_btn and ticker:
            storage.history_manager.save_manual_query(ticker)
            cloud_sync.cloud_sync_manager.push_file(config.HISTORY_FILE_PATH)

    # ---------------- 主內容區域 (Main Content) ----------------
    # 頂部圖例看板與模組版本卡片
    st.markdown(render_version_legend_html(), unsafe_allow_html=True)

    # 手繪圈選處：圖例下方、圖表上方的行動端水平緊湊導航列
    nav_col1, nav_col2, _ = st.columns([1, 1, 4])
    with nav_col1:
        st.button("⏮ 上一個", on_click=on_prev_click, use_container_width=True)
    with nav_col2:
        st.button("⏭ 下一個", on_click=on_next_click, use_container_width=True)

    active_ticker = st.session_state["ticker_input"].strip().upper()

    # 執行全量管線運算與圖表渲染
    with st.spinner(f"正在計算 {active_ticker} 均線、頭底轉折與籌碼特徵..."):
        html_view = run_analysis_pipeline(active_ticker, lookback_days)

    if html_view:
        # iframe 高度控制（手機版 1820px、桌面版 1880px，防止底部資券卡與大戶持股卡截斷）
        total_h = frontend.get_iframe_height(is_mobile=False)
        components.html(html_view, height=total_h, scrolling=False)
    else:
        st.error(f"無法取得標的代碼 {active_ticker} 之有效交易資料，請確認代碼是否正確或該標的是否已下市。")


# ==========================================
# 6. 模組主執行進入點
# ==========================================
if __name__ == "__main__":
    if config.ENV == "colab":
        run_in_colab()
    else:
        run_in_streamlit()
