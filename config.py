"""
台股技術與籌碼分析系統 - 常數與環境配置模組
負責儲存常用中英文代碼對照表、集保等級映射表、環境判定常數與路徑管理。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

# ==============================================================================
# 模組名稱: config
# 模組版本: 202610271700
# 核心職責: 全域路徑配置、環境偵測旗標、常用股票對照表
# ==============================================================================

MODULE_NAME = "config"
MODULE_VERSION = "202610271700"

import os
import sys

# 1. 執行環境自動判定 (Colab vs 本地/Streamlit)
try:
    import google.colab
    IS_COLAB = True
except ImportError:
    IS_COLAB = False

# 2. 檔案路徑配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE = os.path.join(DATA_DIR, "stock_chips.db")
HISTORY_FILE = os.path.join(DATA_DIR, "stock_history.json")
NAME_CACHE_FILE = os.path.join(DATA_DIR, "stock_names.json")

# 3. 常用權值股中文名稱對照備援表
COMMON_STOCK_MAP = {
    "1301": "台塑",
    "1303": "南亞",
    "1326": "台化",
    "6505": "台塑化",
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2308": "台達電",
    "2382": "廣達",
    "3231": "緯創",
    "2356": "英業達",
    "2603": "長榮",
    "2609": "陽明",
    "2615": "萬海",
    "2881": "富邦金",
    "2882": "國泰金",
    "2891": "中信金",
    "2049": "上銀",
    "3576": "聯合再生",
    "2376": "技嘉",
    "2303": "聯電",
    "3008": "大立光",
    "2412": "中華電"
}
