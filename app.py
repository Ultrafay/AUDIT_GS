from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form, Path as FastPath
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from contextlib import asynccontextmanager
import uvicorn
import shutil
import os
import uuid
import base64
import requests as http_requests
from pathlib import Path
import ocr_engine
from typing import Optional
from dotenv import set_key
from fastapi.middleware.cors import CORSMiddleware

# ── Drive Processor (lazy init) ──────────────────────────────

drive_processor = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Drive watcher on startup, stop on shutdown."""
    global drive_processor
    
    folder_id = os.getenv("DRIVE_FOLDER_INBOX")
    if folder_id:
        try:
            from workers.drive_processor import DriveProcessor
            drive_processor = DriveProcessor()
            await drive_processor.start()
        except Exception as e:
            print(f"[App] Drive watcher failed to start: {e}")
            import traceback
            traceback.print_exc()
            drive_processor = None
    else:
        print("[App] DRIVE_FOLDER_INBOX not set — Drive watcher disabled")
    
    yield  # App is running
    
    # Shutdown
    if drive_processor:
        await drive_processor.stop()


app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "*"  # To be restricted in real production to Vercel/Railway frontend domains
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create directories if they don't exist
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@app.get("/")
async def read_index():
    return JSONResponse(content={"message": "Go to /static/index.html for the UI"})

@app.get("/health")
async def health_check():
    """Health check endpoint for Railway deployment"""
    return JSONResponse(status_code=200, content={"status": "ok"})

@app.get("/launch", response_class=HTMLResponse)
async def launch_page():
    """Landing page"""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Launch - ATH by Solvevia</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f3f4f6; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .card { background: white; padding: 2.5rem; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); text-align: center; max-width: 450px; width: 100%; }
            h1 { color: #111827; margin-bottom: 0.5rem; font-size: 1.8rem; }
            p { color: #6b7280; margin-bottom: 2rem; }
            .btn { display: inline-block; background-color: #2563eb; color: white; padding: 0.75rem 2rem; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 1.1rem; transition: background-color 0.2s, transform 0.1s; border: none; cursor: pointer; }
            .btn:hover { background-color: #1d4ed8; }
            .btn:active { transform: scale(0.98); }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Welcome to ATH</h1>
            <p>Powered by Solvevia</p>
            <a href="/static/index.html" class="btn">Go to Dashboard</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/extract/{doc_type}")
async def extract_document(
    doc_type: str = FastPath(..., description="sales_order, sales_invoice, or gdn"),
    file: UploadFile = File(...),
    sample_number: int = Form(..., ge=1, le=20),
):
    if doc_type not in ("sales_order", "sales_invoice", "gdn"):
        raise HTTPException(400, f"Invalid doc_type: {doc_type}")

    file_id = str(uuid.uuid4())
    filename = f"{file_id}_{file.filename}"
    file_path = UPLOAD_DIR / filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = ocr_engine.process_document(file_path, file_id, doc_type, sample_number)
        return JSONResponse(content=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.get("/api/drive-watcher/status")
async def drive_watcher_status():
    """Get Drive watcher status"""
    if not drive_processor:
        return JSONResponse(content={
            "is_running": False,
            "message": "Drive watcher not configured. Set DRIVE_FOLDER_INBOX in .env"
        })
    return JSONResponse(content=drive_processor.get_status())

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)