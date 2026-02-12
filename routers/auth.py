# routers/auth.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display login page"""
    # If already logged in, redirect to overview
    if request.session.get("logged_in"):
        return RedirectResponse(url="/overview")

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None
        }
    )


@router.post("/login")
async def login(
        request: Request,
        phone_number: str = Form(...),
        db: Session = Depends(get_db)
):
    """Handle login form submission"""

    # Find user by phone number
    user = db.query(User).filter(User.phone_number == phone_number).first()

    # Verify user exists
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Phone number not found. Please contact administrator."
            }
        )

    # Check if user has proper role
    if user.role not in ["Owner", "PDI", "Back Office"]:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "You don't have permission to access this application"
            }
        )

    # Set session data
    request.session["logged_in"] = True
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["user_role"] = user.role
    request.session["branch_id"] = user.Branch_ID
    request.session["branch_name"] = user.branch.Branch_Name if user.branch else "N/A"

    # Redirect to overview
    return RedirectResponse(url="/overview", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Handle logout"""
    request.session.clear()
    return RedirectResponse(url="/login")
