"""
台股技術與籌碼分析系統 - 常數與環境配置模組
負責儲存常用中英文代碼對照表、集保等級映射表、環境判定常數與路徑管理。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "config"
MODULE_VERSION = "202610280050"

import os
import sys
from pathlib import Path

# ==========================================
# 1. 執行環境判斷 (Colab vs Streamlit Cloud / 本地)
# ==========================================
IS_COLAB = ('google.colab' in sys.modules) or ('COLAB_GPU' in os.environ) or ('COLAB_JUPYTER_IP' in os.environ)

def detect_runtime_environment() -> str:
    if IS_COLAB:
        return "colab"
    if os.environ.get("STREAMLIT_RUNTIME_ENV") or os.path.exists("/app"):
        return "streamlit"
    return "local"

ENV = detect_runtime_environment()

# ==========================================
# 2. 檔案目錄與路徑常數
# ==========================================
BASE_DIR = Path(__file__).resolve().parent

if IS_COLAB:
    DRIVE_MOUNT_PATH = Path("/content/drive/MyDrive/StockApp")
    DATA_DIR = DRIVE_MOUNT_PATH
else:
    DATA_DIR = BASE_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)

# 核心檔案路徑
DB_FILE_PATH = DATA_DIR / "chips_data.db"
HISTORY_FILE_PATH = DATA_DIR / "stock_history.json"
STOCK_NAMES_CACHE_PATH = DATA_DIR / "tw_stock_names.json"
GDRIVE_SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"

# ==========================================
# 3. 常用參數與爬蟲防護閥值
# ==========================================
DEFAULT_STOCK_ID = "2330"
DEFAULT_LOOKBACK_DAYS = 365
OBV_BASE_LOOKBACK = 180
DEFAULT_FLOAT_RATIO_FALLBACK = 0.75

TURNOVER_THRESHOLD_MID = 10.0   # 10% ~ 20%：藍色正三角 ▲
TURNOVER_THRESHOLD_HIGH = 20.0  # >= 20%：黃色倒三角 ▼

TDCC_INCREMENTAL_WEEKS_LIMIT = 15  # 增量回溯上限週數

# ==========================================
# 4. 常用股票中英文對照表
# ==========================================
COMMON_STOCKS = {
    "1101": "台泥", "1102": "亞泥", "1104": "環泥", "1216": "統一",
    "1301": "台塑", "1303": "南亞", "1312": "國喬", "1326": "台化",
    "1504": "東元", "2002": "中鋼", "2105": "正新", "2303": "聯電",
    "2308": "台達電", "2312": "金寶", "2317": "鴻海", "2324": "仁寶",
    "2327": "國巨", "2330": "台積電", "2331": "精英", "2374": "佳能",
    "2382": "廣達", "2454": "聯發科", "2478": "大毅", "2492": "華新科",
    "2603": "長榮", "2609": "陽明", "2615": "萬海", "3008": "大立光",
    "3022": "威強電", "3088": "艾訊", "3231": "緯創", "3481": "群創",
    "3653": "健策", "3661": "世芯-KY", "4526": "東台", "6191": "精成科",
    "6217": "中探針", "6456": "GIS-KY", "6505": "台塑化", "8111": "立碁",
    "0050": "元大台灣50", "0056": "元大高股息", "00878": "國泰永續高股息",
    "00919": "群益台灣精選高息", "00929": "復華台灣科技優息", "00940": "元大台灣價值高息"
}
