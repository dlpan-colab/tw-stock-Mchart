"""
台股技術與籌碼分析系統 - Google Drive 雲端雙向同步模組
支援 Service Account (st.secrets) 與 Google Colab 雙環境。
具備檔名相容比對機制 (相容 data_{code}.db 與 {code}.db)。
"""

MODULE_NAME = "cloud_sync"
MODULE_VERSION = "202611022230"

import io
import os
import json
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

    def _find_file_id(self, filename: str) -> Optional[str]:
        if not self.service or not self.folder_id:
            return None
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
                return files[0]["id"]
            return None
        except Exception as e:
            logger.error(f"查詢雲端檔案 {filename} 失敗: {e}")
            return None

    def pull_file(self, local_path: Path) -> bool:
        if not self.service:
            return False
        
        local_path = Path(local_path)
        filename = local_path.name
        file_id = self._find_file_id(filename)
        
        if not file_id:
            return False
            
        try:
            from googleapiclient.http import MediaIoBaseDownload
            request = self.service.files().get_media(fileId=file_id)
            
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            logger.info(f"成功自雲端下載: {filename}")
            return True
        except Exception as e:
            logger.error(f"自雲端下載 {filename} 失敗: {e}")
            return False

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

def push_file(local_path: str, remote_name: str = None) -> bool:
    return GoogleDriveSync().push_file(Path(local_path))
