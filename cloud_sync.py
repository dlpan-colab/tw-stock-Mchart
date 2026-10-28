"""
台股技術與籌碼分析系統 - Google Drive 雲端雙向同步模組
支援 Service Account (st.secrets) 與 Google Colab 雙環境。
具備檔名相容比對機制 (相容 data_{code}.db 與 {code}.db)。
"""

MODULE_NAME = "cloud_sync"
MODULE_VERSION = "202610281100"

import io
import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

try:
    import streamlit as st
except ImportError:
    st = None


class GoogleDriveSync:
    def __init__(self):
        self.service = None
        self.folder_id = None
        self._init_service()

    def _init_service(self):
        # 1. 取得 Folder ID
        if st and hasattr(st, "secrets") and "FOLDER_ID" in st.secrets:
            self.folder_id = st.secrets["FOLDER_ID"]
        else:
            self.folder_id = os.environ.get("FOLDER_ID", "1lzC9_maXqA1BMBUMBkft8wDaLQIv2GI_")

        # 2. 建立 Google Drive API Service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = None
            if st and hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
                key_dict = dict(st.secrets["gcp_service_account"])
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                creds = service_account.Credentials.from_service_account_info(
                    key_dict,
                    scopes=["https://www.googleapis.com/auth/drive"]
                )

            if creds:
                self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
                logger.info("Google Drive 服務帳號驗證成功。")
            else:
                logger.warning("未偵測到 gcp_service_account 憑證。")
        except Exception as e:
            logger.error(f"Google Drive 初始化失敗: {e}")
            self.service = None

    def _find_file_id(self, filename: str) -> Optional[str]:
        if not self.service or not self.folder_id:
            return None
        try:
            # 檔名相容：例如 data_1303.db 或 1303.db 皆能命中
            alt_name = filename.replace("data_", "") if filename.startswith("data_") else f"data_{filename}"
            q = f"(name = '{filename}' or name = '{alt_name}') and '{self.folder_id}' in parents and trashed = false"
            res = self.service.files().list(q=q, fields="files(id, name)", spaces="drive").execute()
            files = res.get("files", [])
            if files:
                return files[0]["id"]
            return None
        except Exception as e:
            logger.error(f"查詢雲端檔案 {filename} 失敗: {e}")
            return None

    def pull_file(self, local_path: Path) -> bool:
        """從 Google Drive 下載檔案覆蓋至 local_path"""
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
        """將本地檔案上傳/覆蓋至 Google Drive"""
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


# 全域實例
cloud_sync_manager = GoogleDriveSync()
drive_sync = cloud_sync_manager
