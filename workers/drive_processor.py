"""
Background Drive processor.
Polls a Google Drive folder for new invoices, processes them via OpenAI,
and pushes results to Google Sheets.
"""
import asyncio
import os
import uuid
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from dotenv import load_dotenv
load_dotenv()

from services.drive_watcher import GoogleDriveWatcher
from services.openai_extractor import OpenAIExtractor
from services.sheets_service import GoogleSheetsService
from utils.credentials_helper import get_credentials_path

class DriveProcessor:
    def __init__(self):
        self.poll_interval = int(os.getenv("DRIVE_POLL_INTERVAL", "10"))
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._processed_ids: Set[str] = set()
        self._stats = {
            "started_at": None,
            "last_poll": None,
            "files_processed": 0,
            "files_failed": 0,
        }

        # Initialize services
        creds_path = get_credentials_path()
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
        
        self.drive = GoogleDriveWatcher(
            credentials_path=creds_path,
            folder_id=folder_id
        )
        self.extractor = OpenAIExtractor(
            api_key=os.getenv("OPENAI_API_KEY"),
            org_id=os.getenv("OPENAI_ORG_ID"),
            project_id=os.getenv("OPENAI_PROJECT_ID")
        )
        self.sheets = GoogleSheetsService(
            credentials_path=creds_path,
            spreadsheet_id=os.getenv("GOOGLE_SHEET_ID")
        )
        self.folder_id = folder_id

        print(f"[DriveProcessor] Initialized. Watching folder: {folder_id}")

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self):
        """Start the background polling loop."""
        if self.is_running:
            return
        self.is_running = True
        self._stats["started_at"] = datetime.now().isoformat()
        self._task = asyncio.create_task(self._poll_loop())
        print(f"[DriveProcessor] Started polling every {self.poll_interval}s")

    async def stop(self):
        """Stop the background polling loop."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[DriveProcessor] Stopped")

    def get_status(self) -> dict:
        return {
            "is_running": self.is_running,
            "folder_id": self.folder_id,
            "poll_interval_seconds": self.poll_interval,
            "tracked_file_count": len(self._processed_ids),
            **self._stats
        }

    # ── Core Loop ───────────────────────────────────────────────

    async def _poll_loop(self):
        """Main polling loop. Runs in background."""
        while self.is_running:
            try:
                await self._poll_once()
            except Exception as e:
                print(f"[DriveProcessor] Poll error: {e}")
                traceback.print_exc()
            
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self):
        """Single poll iteration: list files → process new ones."""
        self._stats["last_poll"] = datetime.now().isoformat()
        
        # Run Drive API call in thread pool (it's blocking)
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(None, self.drive.list_new_files)
        
        if not files:
            return

        new_files = [f for f in files if f['id'] not in self._processed_ids]
        if not new_files:
            return

        print(f"[DriveProcessor] Found {len(new_files)} new file(s)")

        for file_info in new_files:
            await loop.run_in_executor(
                None, self._process_file, file_info
            )

    # ── File Processing ─────────────────────────────────────────

    def _process_file(self, file_info: dict):
        """Download, extract, push to Sheets, move file."""
        file_id = file_info['id']
        file_name = file_info['name']
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"[DriveProcessor] [{timestamp}] Processing: {file_name}")

        # Create temp file for download
        suffix = Path(file_name).suffix or ".tmp"
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="invoice_")
        os.close(tmp_fd)

        try:
            # 1. Download
            self.drive.download_file(file_id, tmp_path)
            print(f"[DriveProcessor]   Downloaded to {tmp_path}")

            # 2. Extract via OpenAI
            # Passing 'sales_invoice' as a default doc_type, pending multi-folder routing update.
            if file_name.lower().endswith(".pdf"):
                result = self.extractor.extract_from_pdf(tmp_path, doc_type="sales_invoice")
            else:
                result = self.extractor.extract_from_image(tmp_path, doc_type="sales_invoice")
            
            print(f"[DriveProcessor]   Extracted: {result.supplier_name} / {result.invoice_number}")

            # 3. Check duplicates
            if os.getenv("DUPLICATE_CHECK_ENABLED", "true").lower() == "true":
                is_dup = self.sheets.check_duplicate(
                    result.invoice_number, result.supplier_name
                )
                if is_dup:
                    result.notes = (result.notes or "") + " [DUPLICATE DETECTED]"
                    print(f"[DriveProcessor]   ⚠ Duplicate detected")

            # 4. Push to Sheets
            internal_id = str(uuid.uuid4())
            self.sheets.append_invoice(result.dict(), internal_id, file_name)
            print(f"[DriveProcessor]   Pushed to Google Sheets")

            # 5. Move to Processed
            self.drive.move_to_processed(file_id)
            print(f"[DriveProcessor]   ✓ Moved to Processed")

            self._stats["files_processed"] += 1

        except Exception as e:
            print(f"[DriveProcessor]   ✗ FAILED: {e}")
            traceback.print_exc()
            
            # Move to Failed folder
            try:
                self.drive.move_to_failed(file_id)
                print(f"[DriveProcessor]   Moved to Failed folder")
            except Exception as move_err:
                print(f"[DriveProcessor]   Could not move to Failed: {move_err}")
            
            self._stats["files_failed"] += 1

        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            
            # Track this file ID regardless of outcome
            self._processed_ids.add(file_id)
