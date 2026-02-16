# main.py
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import os
from pathlib import Path
from datetime import datetime

from routers import auth, overview, task_manager, inventory, logistics, reports, mechanic

# Initialize FastAPI app
app = FastAPI(
    title="PDI Control Center",
    description="Vehicle Tracking and PDI Operations Management System",
    version="1.0.6"
)

# Add session middleware
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production-please")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Create static directory if it doesn't exist
Path("static/css").mkdir(parents=True, exist_ok=True)
Path("static/js").mkdir(parents=True, exist_ok=True)
Path("static/icons").mkdir(parents=True, exist_ok=True)


# Serve manifest.json at root level
@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(
        "static/manifest.json",
        media_type="application/manifest+json",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*"
        }
    )


# Serve service worker at root level
@app.get("/sw.js")
async def get_service_worker():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
            "Access-Control-Allow-Origin": "*"
        }
    )


# Serve icons directly (backup route if static mount fails)
@app.get("/static/icons/{icon_name}")
async def get_icon(icon_name: str):
    icon_path = f"static/icons/{icon_name}"
    if os.path.exists(icon_path):
        return FileResponse(
            icon_path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=31536000",
                "Access-Control-Allow-Origin": "*"
            }
        )
    return JSONResponse({"error": "Icon not found"}, status_code=404)


# Offline fallback page
@app.get("/offline", response_class=HTMLResponse)
async def offline_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Offline - PDI Control Center</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-50 min-h-screen flex items-center justify-center p-4">
        <div class="text-center">
            <div class="text-6xl mb-4">📡</div>
            <h1 class="text-2xl font-bold text-gray-900 mb-2">You're Offline</h1>
            <p class="text-gray-600 mb-6">Please check your internet connection</p>
            <button onclick="window.location.reload()" class="bg-blue-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-blue-700">
                Try Again
            </button>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth.router)
app.include_router(overview.router)
app.include_router(task_manager.router)
app.include_router(inventory.router)
app.include_router(logistics.router)
app.include_router(reports.router)
app.include_router(mechanic.router)


# Root redirect
@app.get("/")
async def root(request: Request):
    """Redirect to overview if logged in, otherwise to login"""
    if request.session.get("logged_in"):
        return RedirectResponse(url="/overview")
    return RedirectResponse(url="/login")


# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app": "PDI Control Center",
        "version": "1.0.6",
        "timestamp": datetime.now().isoformat()
    }


# PWA status check endpoint
@app.get("/pwa-status")
async def pwa_status():
    manifest_exists = os.path.exists("static/manifest.json")
    sw_exists = os.path.exists("static/sw.js")
    icons_exist = os.path.exists("static/icons/icon-192x192.png")

    return {
        "pwa_ready": manifest_exists and sw_exists and icons_exist,
        "manifest": manifest_exists,
        "service_worker": sw_exists,
        "icons": icons_exist,
        "version": "1.0.6"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
