"""
storage.py - 歷史查詢紀錄持久化儲存模組
版本: sto_202610311200
"""

import json
import os
from typing import List, Dict

MODULE_VERSION = "sto_202610311200"

DATA_FILE = "stock_history.json"

def _ensure_file():
    if not os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def load_stock_history() -> List[Dict[str, str]]:
    """
    載入查詢歷史紀錄
    回傳格式: [{"code": "8111", "name": "立碁"}, ...]
    """
    _ensure_file()
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def save_stock_history(code: str, name: str) -> None:
    """
    新增或更新個股至歷史紀錄最前端，自動去重
    """
    code = str(code).strip()
    name = str(name).strip()
    if not code:
        return

    history = load_stock_history()
    # 移除舊有同代碼項目
    history = [item for item in history if str(item.get("code")).strip() != code]
    # 插入至開頭
    history.insert(0, {"code": code, "name": name if name else code})
    # 限制最多保存 30 筆
    history = history[:30]

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def remove_history_items(codes_to_remove: List[str]) -> None:
    """
    依代碼清單批次移除歷史紀錄
    """
    if not codes_to_remove:
        return

    codes_set = set(str(c).strip() for c in codes_to_remove)
    history = load_stock_history()
    history = [item for item in history if str(item.get("code")).strip() not in codes_set]

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def clear_stock_history() -> None:
    """
    清空所有歷史紀錄
    """
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
