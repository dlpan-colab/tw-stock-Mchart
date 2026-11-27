""" 
台股技術與籌碼分析系統 - Google Drive 雲端雙向同步模組
支援 Service Account (st.secrets) 與 Google Colab 雙環境。
具備檔名相容比對機制 (相容 data_{code}.db 與 {code}.db)。 
版本: 202611270810
"""

MODULE_NAME = "cloud_sync"
MODULE_VERSION = "202611270810"

import io
import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

try:
    import streamlit as st
except ImportError:
    st = None

# 全域變數用來快取金鑰，解決背景執行緒讀不到 secrets 的問題
_DRIVE_SECRETS = None
_FOLDER_ID = None

def _load_secrets_once():
    """延遲到第一次實際呼叫時才讀取金鑰，確保 Streamlit 已初始化完畢"""
    global _DRIVE_SECRETS, _FOLDER_ID
    if _DRIVE_SECRETS is None:
        try:
            if st and hasattr(st, "secrets"):
                if "gcp_service_account" in st.secrets:
                    _DRIVE_SECRETS = dict(st.secrets["gcp_service_account"])
                if "FOLDER_ID" in st.secrets:
                    _FOLDER_ID = st.secrets["FOLDER_ID"]
        except Exception as e:
            logger.warning(f"載入 secrets 失敗: {e}")

def get_auth_status() -> int:
    """
    回傳金鑰狀態：
    0 = 未取得金鑰 (⚪ 灰燈)
    1 = 已取得金鑰，但尚未驗證或驗證失敗 (🔵 藍燈)
    2 = 金鑰已順利工作/連線成功 (🟡 黃燈)
    """
    _load_secrets_once()
    if not _DRIVE_SECRETS:
        return 0  
    
    # 測試是否能成功建立 service 實例
    sync_client = GoogleDriveSync()
    if sync_client.service:
        return 2  
    else:
        return 1  

class GoogleDriveSync:
    def __init__(self):
        self.service = None
        self.folder_id = None
        self._init_service()

    def _init_service(self):
        # 嘗試載入金鑰 (只在第一次主程式執行成功時寫入全域變數快取)
        _load_secrets_once()
        
        # 1. 取得 Folder ID
        self.folder_id = _FOLDER_ID or os.environ.get("FOLDER_ID", "1lzC9_maXqA1BMBUMBkft8wDaLQIv2GI_")

        # 2. 建立 Google Drive API Service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = None
            if _DRIVE_SECRETS:
                key_dict = _DRIVE_SECRETS.copy()
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                creds = service_account.Credentials.from_service_account_info(
                    key_dict, 
                    scopes=["https://www.googleapis.com/auth/drive"]
                )
            
            if creds:
                # 每次呼叫都建立全新且獨立的 service，確保執行緒安全不當機
                self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
            else:
                logger.warning("未偵測到 gcp_service_account 憑證。")
        except Exception as e:
            logger.error(f"Google Drive 初始化失敗: {e}")
            self.service = None

    def _find_file_id_with_status(self, filename: str) -> tuple:
        """
        【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
        1. 修改目的：明確區分「查詢 API 成功但雲端確實無此檔 (None, True)」與「查詢 API 網路逾時／異常 (None, False)」，
           供上層防覆蓋保護旗標精準判斷是否可安全建立空庫。
        2. 防呆防錯原因：避免查詢失敗時誤判為雲端無檔案，導致本地新空庫反向覆蓋雲端既有完整資料庫。
        """
        if not self.service or not self.folder_id:
            return None, False
        try:
            alt_name = filename.replace("data_", "") if filename.startswith("data_") else f"data_{filename}"
            q = f"(name = '{filename}' or name = '{alt_name}') and '{self.folder_id}' in parents and trashed = false"
            res = self.service.files().list(
                q=q,
                fields="files(id, name)",
                spaces="drive"
            ).execute()
            
            if isinstance(res, str):
                res = json.loads(res)
            
            files = res.get("files", []) if isinstance(res, dict) else []
            if files:
                return files[0]["id"], True
            return None, True
        except Exception as e:
            logger.error(f"查詢雲端檔案 {filename} 失敗: {e}")
            return None, False

    def _find_file_id(self, filename: str) -> Optional[str]:
        fid, _ = self._find_file_id_with_status(filename)
        return fid

    def pull_file_detailed(self, local_path: Path, max_retries: int = 3, status_callback=None) -> tuple:
        """
        【修訂說明 2026-11-27】【修改目的與防呆防錯原因】：
        1. 修改目的：
           - 針對雲端檔案查詢與 `MediaIoBaseDownload` 下載加入最多 `max_retries`（預設 3 次）指數退避重試（0.6s -> 1.2s -> 2.4s），
             並透過 `status_callback(attempt, max_retries, detail_msg)` 即時向前端進度列回報重試狀態。
           - 回傳 `(ok: bool, remote_exists_or_unknown: bool)`：若確認雲端無此檔回傳 `(False, False)`；
             若雲端已有此檔（或查詢本身逾時無法確認不存在）卻 3 次重試皆下載失敗，回傳 `(False, True)` 啟動防覆蓋保護。
        2. 防呆防錯原因：先寫入 `.tmp` 暫存檔並確認大小 > 0 後再原子替換 `local_path`，避免半套損毀檔污染本地 SQLite。
        """
        local_path = Path(local_path)
        filename = local_path.name
        if not self.service:
            return False, True

        retries = max(1, int(max_retries or 3))
        file_id = None
        remote_exists_or_unknown = True

        for attempt in range(1, retries + 1):
            if attempt > 1:
                if status_callback:
                    status_callback(attempt, retries, f"雲端庫查詢重試 ({attempt}/{retries})...")
                time.sleep(0.6 * (2 ** (attempt - 2)))
            fid, query_ok = self._find_file_id_with_status(filename)
            if query_ok:
                if fid:
                    file_id = fid
                    remote_exists_or_unknown = True
                else:
                    # API 明確回應雲端無此檔案，無需無效重試
                    return False, False
                break

        if not file_id:
            return False, True

        from googleapiclient.http import MediaIoBaseDownload
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")

        for attempt in range(1, retries + 1):
            if attempt > 1:
                if status_callback:
                    status_callback(attempt, retries, f"雲端庫下載重試 ({attempt}/{retries})...")
                time.sleep(0.6 * (2 ** (attempt - 2)))
            try:
                request = self.service.files().get_media(fileId=file_id)
                with open(tmp_path, "wb") as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                if tmp_path.exists() and tmp_path.stat().st_size > 0:
                    os.replace(str(tmp_path), str(local_path))
                    logger.info(f"成功自雲端下載: {filename} (第 {attempt} 次)")
                    return True, True
            except Exception as e:
                logger.error(f"自雲端下載 {filename} 失敗 (第 {attempt}/{retries} 次): {e}")
            finally:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass

        return False, True

    def pull_file(self, local_path: Path) -> bool:
        ok, _ = self.pull_file_detailed(local_path, max_retries=3, status_callback=None)
        return ok

    def push_file(self, local_path: Path) -> bool:
        if not self.service or not self.folder_id:
            return False
            
        local_path = Path(local_path)
        if not local_path.exists():
            return False
            
        filename = local_path.name
        file_id = self._find_file_id(filename)
        
        try:
            from googleapiclient.http import MediaFileUpload
            media = MediaFileUpload(str(local_path), resumable=True)
            
            if file_id:
                self.service.files().update(
                    fileId=file_id,
                    media_body=media
                ).execute()
                logger.info(f"成功更新雲端檔案: {filename}")
            else:
                metadata = {
                    "name": filename,
                    "parents": [self.folder_id]
                }
                self.service.files().create(
                    body=metadata,
                    media_body=media,
                    fields="id"
                ).execute()
                logger.info(f"成功上傳新檔至雲端: {filename}")
            return True
        except Exception as e:
            logger.error(f"上傳 {filename} 至雲端失敗: {e}")
            return False

    def delete_remote_file(self, filename: str) -> bool:
        if not self.service:
            return False
        file_id = self._find_file_id(filename)
        if not file_id:
            return False
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except Exception as e:
            logger.error(f"刪除雲端檔案 {filename} 失敗: {e}")
            return False

def pull_file(remote_name: str, local_path: str) -> bool:
    return GoogleDriveSync().pull_file(Path(local_path))

def pull_file_detailed(remote_name: str, local_path: str, max_retries: int = 3, status_callback=None) -> tuple:
    return GoogleDriveSync().pull_file_detailed(Path(local_path), max_retries=max_retries, status_callback=status_callback)

def push_file(local_path: str, remote_name: str = None) -> bool:
    return GoogleDriveSync().push_file(Path(local_path))
## EOF cloud_sync.py
