"""
台股技術與籌碼分析系統 - 常數與環境配置模組
負責儲存常用中英文代碼對照表、集保等級映射表、環境判定常數與路徑管理。
相容 Streamlit Cloud 與 Google Colab 雙執行環境。
"""

MODULE_NAME = "config"
MODULE_VERSION = "202610271400"

import os
import sys
from pathlib import Path

# ==========================================
# 1. 執行環境判斷 (Colab vs Streamlit Cloud / 本地)
# ==========================================
def detect_runtime_environment() -> str:
    """
    判定當前執行環境：'colab' 或 'streamlit' / 'local'
    """
    if "google.colab" in sys.modules:
        return "colab"
    if os.environ.get("STREAMLIT_RUNTIME_ENV") or os.path.exists("/app"):
        return "streamlit"
    return "local"

ENV = detect_runtime_environment()

# ==========================================
# 2. 檔案目錄與路徑常數
# ==========================================
BASE_DIR = Path(__file__).resolve().parent

if ENV == "colab":
    # Google Colab 掛載 Google Drive 之預設路徑
    DRIVE_MOUNT_PATH = Path("/content/drive/MyDrive/tw_stock_analyzer")
    DATA_DIR = DRIVE_MOUNT_PATH / "data"
else:
    # Streamlit Cloud 與一般 Local 環境路徑
    DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# 核心檔案路徑
DB_FILE_PATH = DATA_DIR / "chips_data.db"
HISTORY_FILE_PATH = DATA_DIR / "stock_history.json"
STOCK_NAMES_CACHE_PATH = DATA_DIR / "tw_stock_names.json"
GDRIVE_SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"

# ==========================================
# 3. 集保中心 (TDCC) 分級映射表 (1-15 級)
# ==========================================
# 1: 1-999股 (零股)
# 2-9: 1張至50張
# 10-14: 50張至1000張
# 15: 1000張以上 (特大戶)
TDCC_LEVEL_MAP = {
    1: "1-999股",
    2: "1,000-5,000股",
    3: "5,001-10,000股",
    4: "10,001-15,000股",
    5: "15,001-20,000股",
    6: "20,001-30,000股",
    7: "30,001-40,000股",
    8: "40,001-50,000股",
    9: "50,001-100,000股",
    10: "100,001-200,000股",
    11: "200,001-400,000股",
    12: "400,001-600,000股",
    13: "600,001-800,000股",
    14: "800,001-1,000,000股",
    15: "1,000,001股以上",
}

# 門檻常數定義 (張數對應 TDCC 等級)
TDCC_THRESHOLD_LEVELS = {
    "1000張以上": [15],
    "800張以上": [14, 15],
    "600張以上": [13, 14, 15],
    "400張以上": [12, 13, 14, 15],
    "200張以上": [11, 12, 13, 14, 15],
    "100張以上": [10, 11, 12, 13, 14, 15],
}

# ==========================================
# 4. 常見指標參數與量化閥值
# ==========================================
DEFAULT_STOCK_ID = "2330"
DEFAULT_BENCHMARK_ID = "^TWII"  # 加權指數

DEFAULT_LOOKBACK_DAYS = 365
OBV_BASE_LOOKBACK = 180

# 換手率大戶排除係數（當缺乏集保資料時的保守替代常數）
DEFAULT_FLOAT_RATIO_FALLBACK = 0.75

# 換手率警告門檻
TURNOVER_THRESHOLD_MID = 10.0   # 10% ~ 20%：藍色正三角 ▲
TURNOVER_THRESHOLD_HIGH = 20.0  # >= 20%：黃色倒三角 ▼

# TDCC 爬蟲防護參數
TDCC_INCREMENTAL_WEEKS_LIMIT = 15  # 增量回溯上限週數

# ==========================================
# 5. 常用中英文對照表
# ==========================================
COMMON_STOCKS = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2308": "台達電",
    "2382": "廣達",
    "3231": "緯創",
    "2603": "長榮",
    "2609": "陽明",
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "00878": "國泰永續高股息",
    "00919": "群益台灣精選高息",
    "00929": "復華台灣科技優息",
    "00940": "元大台灣價值高息",
}
