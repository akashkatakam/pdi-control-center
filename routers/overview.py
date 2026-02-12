# routers/overview.py
from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database import get_db
from services import branch_service, stock_service
from models import VehicleMaster, SalesRecord, Branch

router = APIRouter(prefix="/overview", tags=["overview"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request):
    """Check if user is authenticated"""
    if not request.session.get("logged_in"):
        return False
    return True


def get_active_context(request: Request, db: Session):
    """Get the active branch context for the user"""
    user_branch_id = request.session.get("branch_id")

    if user_branch_id:
        return user_branch_id

    active_context = request.session.get("active_context")
    if not active_context:
        head_branches = branch_service.get_head_branches(db)
        if head_branches:
            active_context = head_branches[0].Branch_ID
            request.session["active_context"] = active_context

    return active_context


def get_greeting():
    """Get time-appropriate greeting"""
    hour = datetime.now().hour
    if hour < 12:
        return "Good Morning"
    elif hour < 18:
        return "Good Afternoon"
    else:
        return "Good Evening"


def get_context_data(request: Request, db: Session):
    """Get common context data for all views"""
    original_branch_id = request.session.get("branch_id")
    active_branch_id = get_active_context(request, db)
    active_branch = db.query(Branch).filter(Branch.Branch_ID == active_branch_id).first()

    context = {
        "username": request.session.get("username"),
        "user_role": request.session.get("user_role"),
        "branch_name": active_branch.Branch_Name if active_branch else "N/A",
        "is_owner": original_branch_id is None,
        "active_context": active_branch_id,
        "greeting": get_greeting()
    }

    if original_branch_id is None:
        context["head_branches"] = branch_service.get_head_branches(db)

    return context


@router.post("/switch-context")
async def switch_context(
        request: Request,
        branch_id: str = Form(...),
        db: Session = Depends(get_db)
):
    """Switch owner's active branch context"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    if request.session.get("branch_id") is not None:
        return RedirectResponse(url="/overview")

    request.session["active_context"] = branch_id
    branch = db.query(Branch).filter(Branch.Branch_ID == branch_id).first()
    if branch:
        request.session["active_context_name"] = branch.Branch_Name

    # Get the referer to redirect back to the same page
    referer = request.headers.get("referer", "/overview")
    return RedirectResponse(url=referer, status_code=303)


@router.get("", response_class=HTMLResponse)
async def overview_page(request: Request, db: Session = Depends(get_db)):
    """Overview Dashboard - Main landing page"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get statistics
    pdi_pending = db.query(SalesRecord).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI Pending"
    ).count()

    pdi_in_progress = db.query(SalesRecord).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI In Progress"
    ).count()

    in_transit = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Transit"
    ).count()

    stock_on_hand = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).count()

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            **context,
            "pdi_pending": pdi_pending,
            "pdi_in_progress": pdi_in_progress,
            "in_transit": in_transit,
            "stock_on_hand": stock_on_hand,
            "current_page": "overview"
        }
    )


@router.get("/search", response_class=JSONResponse)
async def universal_search(
        request: Request,
        query: str = Query(...),
        db: Session = Depends(get_db)
):
    """Universal search - chassis, customer name, or DC number"""

    if not check_auth(request):
        return {"error": "Unauthorized"}

    active_branch_id = get_active_context(request, db)
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    vehicles = db.query(VehicleMaster, Branch).join(
        Branch, VehicleMaster.current_branch_id == Branch.Branch_ID
    ).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        (VehicleMaster.chassis_no.ilike(f"%{query}%")) |
        (VehicleMaster.dc_number.ilike(f"%{query}%"))
    ).limit(10).all()

    sales = db.query(SalesRecord, VehicleMaster, Branch).join(
        VehicleMaster, SalesRecord.Chassis_No == VehicleMaster.chassis_no
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        (SalesRecord.Customer_Name.ilike(f"%{query}%")) |
        (SalesRecord.Chassis_No.ilike(f"%{query}%"))
    ).limit(10).all()

    results = {
        "vehicles": [
            {
                "chassis_no": v.chassis_no,
                "model": v.model,
                "branch": b.Branch_Name,
                "status": v.status
            } for v, b in vehicles
        ],
        "sales": [
            {
                "customer": s.Customer_Name,
                "chassis_no": s.Chassis_No,
                "branch": b.Branch_Name,
                "pdi_status": s.fulfillment_status
            } for s, v, b in sales
        ]
    }

    return results
