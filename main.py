# main.py
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import os
from pathlib import Path

from routers import auth, overview, task_manager, inventory, logistics, reports

# Initialize FastAPI app
app = FastAPI(
    title="PDI Control Center",
    description="Vehicle Tracking and PDI Operations Management System",
    version="1.0.0"
)

# Add session middleware
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production-please")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Create static directory if it doesn't exist
Path("static/css").mkdir(parents=True, exist_ok=True)
Path("static/js").mkdir(parents=True, exist_ok=True)

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
    return {"status": "healthy", "app": "PDI Control Center"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
