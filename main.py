# main.py
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="PDI Control Center",
    description="Vehicle tracking and PDI operations management system",
    version="1.0.0"
)

# Add session middleware for authentication
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
)

# Mount static files (CSS, JS) - Will be created
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    # Static directory doesn't exist yet
    pass

# Setup Jinja2 templates - Will be created
templates = Jinja2Templates(directory="templates")

# TODO: Include routers once created
# from routers import auth, pdi, mechanic
# app.include_router(auth.router)
# app.include_router(pdi.router)
# app.include_router(mechanic.router)

# Root endpoint
@app.get("/")
async def root():
    """Redirect to login page"""
    return RedirectResponse(url="/login")

@app.get("/health")
async def health_check():
    """Health check endpoint for deployment"""
    return {"status": "healthy", "service": "PDI Control Center"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
