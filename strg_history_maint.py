"""
strg_history_maint.py - 查詢歷史紀錄管理與全市籌碼/分點維護清除模組
(自 storage.py 依邏輯職責拆分，維持既有歷史清單 CRUD、雲端還原與指定基準日區間精準清除防呆機制)
版本: 202611242144
"""

import os
import json
import glob
import sqlite3
from datetime import datetime, timedelta

from strg_cloud_names import (
    STORAGE_DIR,
    HISTORY_FILE,
    is_tw_stock_or_etf,
    is_tw_index_with_gov_brokers,
    _sync_cloud_pull,
    _sync_cloud_push,
    sync_db_pull,
    sync_db_push,
    _do_sync_db_pull,
    _do_sync_db_push,
    get_stock_chinese_name,
)

MODULE_NAME = "strg_history_maint"
MODULE_VERSION = "202611242144"


def _recover_history_from_databases() -> list:
    recovered = []
    seen = set()
    try:
        from cloud_sync import GoogleDriveSync
        sync_client = GoogleDriveSync()
        if sync_client.service and sync_client.folder_id:
            q = f"'{sync_client.folder_id}' in parents and name contains 'data_' and name contains '.db' and trashed = false"
            res = sync_client.service.files().list(
                q=q, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc", pageSize=50
            ).execute()
            files = res.get("files", [])
            for f in files:
                fname = f.get("name", "")
                pure = fname.replace("data_", "").replace(".db", "").strip().upper()
                if (is_tw_stock_or_etf(pure) or pure.startswith("^")) and pure not in seen:
                    seen.add(pure)
                    recovered.append({"code": pure, "name": get_stock_chinese_name(pure)})
    except Exception as e:
        print(f"[Storage] 雲端資料庫掃描還原失敗: {e}")

    local_files = glob.glob(os.path.join(STORAGE_DIR, "data_*.db"))
    local_files.sort(key=os.path.getmtime, reverse=True)
    for p in local_files:
        base = os.path.basename(p)
        pure = base.replace("data_", "").replace(".db", "").strip().upper()
        if (is_tw_stock_or_etf(pure) or pure.startswith("^")) and pure not in seen:
            seen.add(pure)
            recovered.append({"code": pure, "name": get_stock_chinese_name(pure)})

    if recovered:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(recovered[:30], f, ensure_ascii=False, indent=2)
            _sync_cloud_push(allow_empty_history=False)
        except Exception:
            pass
    return recovered[:30]


def load_stock_history():
    _sync_cloud_pull()
    data = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    if not isinstance(data, list):
        data = []
    if not data:
        data = _recover_history_from_databases()
    for item in data:
        code = str(item.get("code", "")).strip().upper()
        item["code"] = code
        curr_name = str(item.get("name", "")).strip()
        if not curr_name or curr_name == code:
            item["name"] = get_stock_chinese_name(code)
    return data


def save_stock_history(code: str, name: str = None):
    code = str(code).strip().upper()
    if not code:
        return load_stock_history()
    c_name = name.strip() if name and name.strip() != code else get_stock_chinese_name(code)
    history = load_stock_history()
    new_hist = [h for h in history if str(h.get("code")).strip().upper() != code]
    new_hist.insert(0, {"code": code, "name": c_name})
    new_hist = new_hist[:30]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, ensure_ascii=False, indent=2)
        _sync_cloud_push()
    except Exception:
        pass
    return new_hist


def update_stock_name_only(code: str, name: str):
    code = str(code).strip().upper()
    if not code or not name or name.strip() == code:
        return
    history = load_stock_history()
    changed = False
    for item in history:
        if str(item.get("code")).strip().upper() == code:
            if item.get("name") != name:
                item["name"] = name
                changed = True
            break
    if changed:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            _sync_cloud_push()
        except Exception:
            pass


def clear_stock_history():
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        _sync_cloud_push(allow_empty_history=True)
    except Exception:
        pass
    return []


def remove_stocks_from_history(target_codes: list) -> list:
    history = load_stock_history()
    target_set = set(str(c).strip().upper() for c in target_codes)
    new_history = [h for h in history if str(h.get("code")).strip().upper() not in target_set]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_history, f, ensure_ascii=False, indent=2)
        _sync_cloud_push(allow_empty_history=True)
    except Exception:
        pass
    return new_history


def clear_recent_margin_data(pure_code: str, weeks: int = 2) -> str:
    """清除指定週數內之資券紀錄，供重新爬取覆蓋"""
    pure_code = str(pure_code).strip().upper()
    db_name = f"data_{pure_code}.db"
    db_path = os.path.join(STORAGE_DIR, db_name)
    sync_db_pull(pure_code)
    if not os.path.exists(db_path):
        return f"查無代號 {pure_code} 之本地資料庫。"
    cutoff_date = (datetime.now() - timedelta(days=weeks * 7)).strftime('%Y-%m-%d')
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM margin_short WHERE date >= ?", (cutoff_date,))
            conn.commit()
        sync_db_push(pure_code)
        return f"已成功清除 {pure_code} 自 {cutoff_date} 起之資券紀錄。"
    except Exception as e:
        return f"清除資券紀錄失敗: {e}"


def clear_recent_institutional_data(pure_code: str, weeks: int = 6) -> str:
    pure_code = str(pure_code).strip().upper()
    db_name = f"data_{pure_code}.db"
    db_path = os.path.join(STORAGE_DIR, db_name)
    sync_db_pull(pure_code)
    if not os.path.exists(db_path):
        return f"查無代號 {pure_code} 之本地資料庫。"
    cutoff_date = (datetime.now() - timedelta(days=weeks * 7)).strftime('%Y-%m-%d')
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM institutional_investors WHERE date >= ?", (cutoff_date,))
            conn.commit()
        sync_db_push(pure_code)
        return f"已成功清除 {pure_code} 自 {cutoff_date} 起之法人紀錄。"
    except Exception as e:
        return f"清除法人紀錄失敗: {e}"


def _collect_all_stock_codes_local_and_cloud() -> list:
    """彙整查詢歷史清單、本地 data_*.db 與雲端 Google Drive 之所有台股個股/ETF 代號（排除 ^ 開頭指數）"""
    codes_set = set()
    for item in load_stock_history():
        pure = str(item.get("code", "")).strip().upper()
        if pure and not pure.startswith("^") and is_tw_stock_or_etf(pure):
            codes_set.add(pure)

    for p in glob.glob(os.path.join(STORAGE_DIR, "data_*.db")):
        base = os.path.basename(p)
        pure = base.replace("data_", "").replace(".db", "").strip().upper()
        if pure and not pure.startswith("^") and is_tw_stock_or_etf(pure):
            codes_set.add(pure)

    try:
        from cloud_sync import GoogleDriveSync
        sync_client = GoogleDriveSync()
        if sync_client.service and sync_client.folder_id:
            q = f"'{sync_client.folder_id}' in parents and name contains 'data_' and name contains '.db' and trashed = false"
            res = sync_client.service.files().list(
                q=q, fields="files(id, name)", pageSize=200
            ).execute()
            for f in res.get("files", []):
                fname = f.get("name", "")
                pure = fname.replace("data_", "").replace(".db", "").strip().upper()
                if pure and not pure.startswith("^") and is_tw_stock_or_etf(pure):
                    codes_set.add(pure)
    except Exception as e:
        print(f"[Storage] 雲端資料庫列表掃描警告: {e}")

    return sorted(codes_set)


def clear_all_stocks_chip_range(chip_type: str, base_date_str: str, lookback_days: int = 1) -> str:
    """
    【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
    1. 修改目的：供「⚙️ 參數設定 → 全市(含上櫃)籌碼資料庫維護」依指定之「籌碼增補基準日（base_date_str）」
       與「往前增補交易籌碼日數（lookback_days）」，精準清除所有個股（含上市/上櫃與 ETF）在該交易日區間內之指定籌碼資料並同步雲端。
    2. 防呆防錯原因：優先依各個股本地 daily_k 實際交易日序列推算精確起始日，完整保留區間外歷史資料及其他資料表。
    """
    c_type = str(chip_type or "").strip().lower()
    table_map = {
        "margin": ("margin_short", "資券籌碼資料"),
        "institutional": ("institutional_investors", "法人籌碼資料"),
        "holding": ("shareholding_distribution", "大戶籌碼資料"),
    }
    if c_type not in table_map:
        return f"不支援的籌碼類型：{chip_type}"

    table_name, label_zh = table_map[c_type]
    b_norm = str(base_date_str or "").strip()[:10]
    n_days = max(1, int(lookback_days or 1))
    try:
        base_dt = datetime.strptime(b_norm, "%Y-%m-%d")
    except Exception:
        base_dt = datetime.now()
        b_norm = base_dt.strftime("%Y-%m-%d")

    fallback_start_str = (base_dt - timedelta(days=max(n_days * 2, n_days + 4))).strftime("%Y-%m-%d")

    all_codes = _collect_all_stock_codes_local_and_cloud()
    if not all_codes:
        return "目前無任何已收集之上市／上櫃個股資料庫。"

    cleared_stocks = 0
    deleted_rows_total = 0
    for pure_code in all_codes:
        db_path = os.path.join(STORAGE_DIR, f"data_{pure_code}.db")
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            _do_sync_db_pull(pure_code)
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                k_rows = cur.execute(
                    "SELECT date FROM daily_k WHERE date <= ? ORDER BY date DESC LIMIT ?",
                    (b_norm, n_days)
                ).fetchall()
                if k_rows:
                    start_date_str = str(k_rows[-1][0])[:10]
                else:
                    start_date_str = fallback_start_str

                cur.execute(
                    f"DELETE FROM {table_name} WHERE date >= ? AND date <= ?",
                    (start_date_str, b_norm)
                )
                affected = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                conn.commit()
            if affected > 0:
                _do_sync_db_push(pure_code)
                cleared_stocks += 1
                deleted_rows_total += affected
        except Exception as e:
            print(f"[Storage] 清除 {pure_code} {label_zh}失敗: {e}")

    return (
        f"已完成清除基準日 {b_norm} 往前 {n_days} 個交易日區間之{label_zh}："
        f"共更新 {cleared_stocks} 檔個股（刪除 {deleted_rows_total} 筆紀錄，區間外歷史資料及其他籌碼完整保留）。"
    )


def clear_all_stocks_broker_range(base_date_str: str, lookback_days: int = 1) -> str:
    """
    【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
    1. 修改目的：供「⚙️ 參數設定 → 全市場（含上櫃）分點批次增補與維護」之「🧹 清除指定期間分點」按鈕呼叫，
       精準清除所有上市／上櫃個股與 ETF 在指定交易日區間內之分點統計與日況明細，並前景同步至雲端。
    2. 防呆防錯原因：僅刪除 [start_date_str, b_norm] 區間內之分點資料，完全保留區間外歷史分點、八大官股及日線/法人/資券/大戶資料。
    """
    b_norm = str(base_date_str or "").strip()[:10]
    n_days = max(1, int(lookback_days or 1))
    try:
        base_dt = datetime.strptime(b_norm, "%Y-%m-%d")
    except Exception:
        base_dt = datetime.now()
        b_norm = base_dt.strftime("%Y-%m-%d")

    fallback_start_str = (base_dt - timedelta(days=max(n_days * 2, n_days + 4))).strftime("%Y-%m-%d")

    all_codes = _collect_all_stock_codes_local_and_cloud()
    if not all_codes:
        return "目前無任何已收集之上市／上櫃個股資料庫。"

    cleared_stocks = 0
    deleted_rows_total = 0
    for pure_code in all_codes:
        db_path = os.path.join(STORAGE_DIR, f"data_{pure_code}.db")
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            _do_sync_db_pull(pure_code)
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                k_rows = cur.execute(
                    "SELECT date FROM daily_k WHERE date <= ? ORDER BY date DESC LIMIT ?",
                    (b_norm, n_days)
                ).fetchall()
                if k_rows:
                    start_date_str = str(k_rows[-1][0])[:10]
                else:
                    start_date_str = fallback_start_str

                affected_stk = 0
                for sql_del in (
                    "DELETE FROM broker_range_rank WHERE range_date >= ? AND range_date <= ?",
                    "DELETE FROM broker_daily_trades WHERE trade_date >= ? AND trade_date <= ?",
                    "DELETE FROM broker_focus_daily_series WHERE focus_date >= ? AND focus_date <= ?",
                ):
                    try:
                        cur.execute(sql_del, (start_date_str, b_norm))
                        if cur.rowcount and cur.rowcount > 0:
                            affected_stk += cur.rowcount
                    except Exception:
                        pass
                conn.commit()
            if affected_stk > 0:
                _do_sync_db_push(pure_code)
                cleared_stocks += 1
                deleted_rows_total += affected_stk
        except Exception as e:
            print(f"[Storage] 清除 {pure_code} 指定期間分點失敗: {e}")

    return (
        f"已完成清除基準日 {b_norm} 往前 {n_days} 個交易日區間之分點資料："
        f"共更新 {cleared_stocks} 檔個股（刪除 {deleted_rows_total} 筆紀錄，區間外歷史分點及其他籌碼完整保留）。"
    )


def clear_all_broker_data() -> str:
    """一次性清除本地及雲端所有台股個股/ETF 與加權(^TWII)/櫃買(^TWOII)資料庫之分點及八大官股資料表並回寫雲端。"""
    codes_set = set()
    for p in glob.glob(os.path.join(STORAGE_DIR, "data_*.db")):
        base = os.path.basename(p)
        pure = base.replace("data_", "").replace(".db", "").strip().upper()
        if pure and (is_tw_stock_or_etf(pure) or is_tw_index_with_gov_brokers(pure)):
            codes_set.add(pure)

    try:
        from cloud_sync import GoogleDriveSync
        sync_client = GoogleDriveSync()
        if sync_client.service and sync_client.folder_id:
            q = f"'{sync_client.folder_id}' in parents and name contains 'data_' and name contains '.db' and trashed = false"
            res = sync_client.service.files().list(
                q=q, fields="files(id, name)", pageSize=200
            ).execute()
            for f in res.get("files", []):
                fname = f.get("name", "")
                pure = fname.replace("data_", "").replace(".db", "").strip().upper()
                if pure and (is_tw_stock_or_etf(pure) or is_tw_index_with_gov_brokers(pure)):
                    codes_set.add(pure)
    except Exception as e:
        print(f"[Storage] 雲端分點資料庫列表掃描警告: {e}")

    if not codes_set:
        return "目前無任何已收集之個股或大盤/櫃買資料庫。"

    cleared_count = 0
    for pure_code in sorted(codes_set):
        db_path = os.path.join(STORAGE_DIR, f"data_{pure_code}.db")
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            _do_sync_db_pull(pure_code)
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                for tbl in ("broker_range_rank", "broker_daily_trades", "broker_focus_daily_series", "gov_index_stock_daily"):
                    try:
                        cur.execute(f"DELETE FROM {tbl}")
                    except Exception:
                        pass
                conn.commit()
            _do_sync_db_push(pure_code)
            cleared_count += 1
        except Exception as e:
            print(f"[Storage] 清除 {pure_code} 分點資料失敗: {e}")

    return f"已成功清除 {cleared_count} 檔標的（含上市/上櫃個股及加權/櫃買八大官股）之分點統計與分點日況明細（日線、法人、資券與集保大戶資料完整保留）。"


def clear_tw_index_gov_broker_data() -> str:
    """僅清除加權指數（^TWII）與櫃買指數（^TWOII）本地與雲端資料庫中的八大官股交易資料並回寫雲端。"""
    cleared_count = 0
    for idx_code in ("^TWII", "^TWOII"):
        db_path = os.path.join(STORAGE_DIR, f"data_{idx_code}.db")
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            _do_sync_db_pull(idx_code)
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                for tbl in ("gov_index_stock_daily", "broker_range_rank", "broker_daily_trades", "broker_focus_daily_series"):
                    try:
                        cur.execute(f"DELETE FROM {tbl}")
                    except Exception:
                        pass
                conn.commit()
            _do_sync_db_push(idx_code)
            cleared_count += 1
        except Exception as e:
            print(f"[Storage] 清除 {idx_code} 八大官股資料失敗: {e}")

    return f"已成功清除加權指數與櫃買指數八大官股交易資料（共更新 {cleared_count} 檔指數資料庫，日線與資券資料完整保留）。"
## EOF strg_history_maint.py
