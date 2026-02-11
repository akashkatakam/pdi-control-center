# routers/reports.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime

from database import get_db

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request):
    if not request.session.get("logged_in"):
        return False
    return True


@router.get("", response_class=HTMLResponse)
async def reports_page(request: Request, db: Session = Depends(get_db)):
    """Reports & Summaries"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")
    
    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "current_page": "reports"
        }
    )


@router.post("/generate")
async def generate_report(
    request: Request,
    report_type: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    source_branch: str = Form(None),
    db: Session = Depends(get_db)
):
    """Generate selected report"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    # Convert dates
    start = datetime.strptime(start_date, "%Y/%m/%d").date()
    end = datetime.strptime(end_date, "%Y/%m/%d").date()
    
    # Use existing report service based on report type
    # This would call your existing report_service functions
    
    return RedirectResponse(url="/reports", status_code=303)
