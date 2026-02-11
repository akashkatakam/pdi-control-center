# routers/logistics.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from services import stock_service

router = APIRouter(prefix="/logistics", tags=["logistics"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request):
    if not request.session.get("logged_in"):
        return False
    return True


@router.get("/receive", response_class=HTMLResponse)
async def receive_inward(request: Request, db: Session = Depends(get_db)):
    """Receive Inward - Handle incoming shipments"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    branch_id = request.session.get("branch_id")
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")
    
    # Get pending loads
    pending_loads = stock_service.get_pending_loads(db, branch_id)
    
    return templates.TemplateResponse(
        "logistics_receive.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "pending_loads": pending_loads,
            "current_page": "logistics"
        }
    )


@router.post("/receive-load")
async def receive_load_action(
    request: Request,
    load_reference: str = Form(...),
    db: Session = Depends(get_db)
):
    """Receive a specific load"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    branch_id = request.session.get("branch_id")
    
    # Use existing service
    success, message = stock_service.receive_load(db, branch_id, load_reference)
    
    return RedirectResponse(url="/logistics/receive", status_code=303)


@router.get("/transfer", response_class=HTMLResponse)
async def transfer_outward(request: Request, db: Session = Depends(get_db)):
    """Transfer/Outward - Transfer stock to other branches"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")
    
    return templates.TemplateResponse(
        "logistics_transfer.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "current_page": "logistics"
        }
    )
