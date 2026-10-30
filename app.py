"""
台股技術與籌碼分析系統 - 主程式入口 (app.py)
"""

MODULE_NAME = "app"
MODULE_VERSION = "202610301100"

import streamlit as st
from frontend import render_sidebar, render_main_content

st.set_page_config(
    page_title="台股技術與籌碼分析系統",
    page_icon="📈",
    layout="wide"
)

def main():
    code, major1_thresh, major2_thresh, shares_outstanding, nav_action = render_sidebar()
    render_main_content(code, major1_thresh, major2_thresh, shares_outstanding)

if __name__ == "__main__":
    main()
