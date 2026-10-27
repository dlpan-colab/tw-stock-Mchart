"""
台股技術與籌碼分析系統 - 雲端雙向同步模組
封裝 Google Drive API（支援 Service Account 與 Colab 原生授權），
負責資料庫 (.db) 與歷史紀錄 (.json) 之雲端 push、pull 與 delete 操作。
"""

MODULE_NAME = "cloud_sync"
MODULE_VERSION = "202610271400"

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from config import (
    DB_FILE_PATH,
    DRIVE_MOUNT_PATH,
    ENV,
    GDRIVE_SERVICE_ACCOUNT_FILE,
    HISTORY_FILE_PATH,
    STOCK_NAMES_CACHE_PATH,
)

logger = logging.getLogger(__name__)

class GoogleDriveSyncManager:
    """
    Google Drive 雙向同步管理器。
    在 Colab 環境下優先使用檔案系統直接對應掛載目錄；
    在 Streamlit Cloud / 本地環境下支援 Google Service Account API 認證操作。
    """

    def __init__(self, service_account_json_path: Optional[Path] = None, folder_name: str = "tw_stock_analyzer"):
        self.env = ENV
        self.folder_name = folder_name
        self.service_account_path = service_account_json_path or GDRIVE_SERVICE_ACCOUNT_FILE
        self.service = None

        if self.env != "colab":
            self._init_drive_service()

    def _init_drive_service(self):
        """初始化 Google Drive API Service 客戶端"""
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_data = None
            # 優先讀取 Streamlit Secrets
            try:
                import streamlit as st
                if "gcp_service_account" in st.secrets:
                    creds_data = dict(st.secrets["gcp_service_account"])
            except Exception:
                pass

            # 次之讀取實體檔案
            if creds_data:
                credentials = service_account.Credentials.from_service_account_info(
                    creds_data,
                    scopes=["https://www.googleapis.com/auth/drive"]
                )
            elif self.service_account_path.exists():
                credentials = service_account.Credentials.from_service_account_file(
                    str(self.service_account_path),
                    scopes=["https://www.googleapis.com/auth/drive"]
                )
            else:
                logger.info("未檢測到 Google Service Account 認證，Cloud Sync 將僅運作於本地離線模式。")
                return

            self.service = build("drive", "v3", credentials=credentials)
            logger.info("Google Drive API 客戶端認證成功。")
        except Exception as e:
            logger.warning(f"Google Drive API 初始化失敗: {e}")
            self.service = None

    def _get_or_create_remote_folder_id(self) -> Optional[str]:
        """查詢或建立雲端目標資料夾 ID"""
        if not self.service:
            return None
        try:
            query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{self.folder_name}' and trashed = false"
            results = self.service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
            items = results.get("files", [])
            if items:
                return items[0]["id"]

            folder_metadata = {
                "name": self.folder_name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            folder = self.service.files().create(body=folder_metadata, fields="id").execute()
            return folder.get("id")
        except Exception as e:
            logger.error(f"取得 Google Drive 資料夾失敗: {e}")
            return None

    def pull_file(self, local_path: Path) -> bool:
        """從雲端拉取檔案至本地"""
        if self.env == "colab":
            remote_colab_file = DRIVE_MOUNT_PATH / local_path.name
            if remote_colab_file.exists():
                local_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(remote_colab_file, local_path)
                logger.info(f"[Colab Sync] 成功從 Drive 複製檔案: {local_path.name}")
                return True
            return False

        if not self.service:
            return False

        try:
            from googleapiclient.http import MediaIoBaseDownload
            import io

            folder_id = self._get_or_create_remote_folder_id()
            if not folder_id:
                return False

            query = f"'{folder_id}' in parents and name = '{local_path.name}' and trashed = false"
            results = self.service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
            files = results.get("files", [])
            if not files:
                return False

            file_id = files[0]["id"]
            request = self.service.files().get_media(fileId=file_id)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            with io.FileIO(str(local_path), "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            logger.info(f"[API Sync] 成功下載雲端檔案: {local_path.name}")
            return True
        except Exception as e:
            logger.error(f"[API Sync] 下載檔案失敗 ({local_path.name}): {e}")
            return False

    def push_file(self, local_path: Path) -> bool:
        """推送本地檔案至雲端"""
        if not local_path.exists():
            return False

        if self.env == "colab":
            DRIVE_MOUNT_PATH.mkdir(parents=True, exist_ok=True)
            target_path = DRIVE_MOUNT_PATH / local_path.name
            shutil.copy2(local_path, target_path)
            logger.info(f"[Colab Sync] 成功同步檔案至 Drive: {local_path.name}")
            return True

        if not self.service:
            return False

        try:
            from googleapiclient.http import MediaFileUpload

            folder_id = self._get_or_create_remote_folder_id()
            if not folder_id:
                return False

            query = f"'{folder_id}' in parents and name = '{local_path.name}' and trashed = false"
            results = self.service.files().list(q=query, spaces="drive", fields="files(id)").execute()
            files = results.get("files", [])

            media = MediaFileUpload(str(local_path), resumable=True)

            if files:
                file_id = files[0]["id"]
                self.service.files().update(fileId=file_id, media_body=media).execute()
                logger.info(f"[API Sync] 成功更新雲端檔案: {local_path.name}")
            else:
                file_metadata = {
                    "name": local_path.name,
                    "parents": [folder_id]
                }
                self.service.files().create(body=file_metadata, media_body=media, fields="id").execute()
                logger.info(f"[API Sync] 成功上傳新檔案至雲端: {local_path.name}")
            return True
        except Exception as e:
            logger.error(f"[API Sync] 上傳檔案失敗 ({local_path.name}): {e}")
            return False

    def delete_remote_file(self, filename: str) -> bool:
        """刪除雲端檔案"""
        if self.env == "colab":
            target = DRIVE_MOUNT_PATH / filename
            if target.exists():
                target.unlink()
                return True
            return False

        if not self.service:
            return False

        try:
            folder_id = self._get_or_create_remote_folder_id()
            if not folder_id:
                return False

            query = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
            results = self.service.files().list(q=query, spaces="drive", fields="files(id)").execute()
            files = results.get("files", [])
            for f in files:
                self.service.files().delete(fileId=f["id"]).execute()
            return True
        except Exception as e:
            logger.error(f"[API Sync] 刪除雲端檔案失敗 ({filename}): {e}")
            return False

    def sync_all_from_cloud(self):
        """下載所有核心工作檔案 (啟動時執行)"""
        for path in [DB_FILE_PATH, HISTORY_FILE_PATH, STOCK_NAMES_CACHE_PATH]:
            self.pull_file(path)

    def sync_all_to_cloud(self):
        """上傳所有核心工作檔案 (異動時執行)"""
        for path in [DB_FILE_PATH, HISTORY_FILE_PATH, STOCK_NAMES_CACHE_PATH]:
            if path.exists():
                self.push_file(path)


# 全域實例
cloud_sync_manager = GoogleDriveSyncManager()
