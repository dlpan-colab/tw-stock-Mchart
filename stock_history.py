import os
import json

HISTORY_FILE = "stock_history.json"

def _load_raw() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_raw(data: list):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_history_list() -> list:
    """持久化保存，從雲端/本地儲存讀取完整清單"""
    return _load_raw()

def add_to_history(stock_id: str):
    """加入歷史紀錄，已存在則提至首位"""
    stock_id = str(stock_id).strip()
    if not stock_id:
        return
    lst = _load_raw()
    if stock_id in lst:
        lst.remove(stock_id)
    lst.insert(0, stock_id)
    _save_raw(lst)

def remove_history_items(items_to_remove: list):
    """僅移除被勾選的項目"""
    lst = _load_raw()
    new_lst = [item for item in lst if item not in items_to_remove]
    _save_raw(new_lst)

def clear_all_history():
    """清除全部歷史清單"""
    _save_raw([])
