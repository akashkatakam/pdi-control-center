# routers/overview.py
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services import branch_service
from models import VehicleMaster, SalesRecord, Branch

router = APIRouter(prefix="/overview", tags=["overview"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request):
    """Check if user is authenticated"""
    if not request.session.get("logged_in"):
        return False
    return True


@router.get("", response_class=HTMLResponse)
async def overview_page(request: Request, db: Session = Depends(get_db)):
    """Overview Dashboard - Main landing page"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    branch_id = request.session.get("branch_id")
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")
    
    # Get all managed branches
    managed_branches = branch_service.get_managed_branches(db, branch_id)
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
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
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
    
    branch_id = request.session.get("branch_id")
    managed_branches = branch_service.get_managed_branches(db, branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]
    
    # Search in VehicleMaster
    vehicles = db.query(VehicleMaster, Branch).join(
        Branch, VehicleMaster.current_branch_id == Branch.Branch_ID
    ).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        (VehicleMaster.chassis_no.ilike(f"%{query}%")) |
        (VehicleMaster.dc_number.ilike(f"%{query}%"))
    ).limit(10).all()
    
    # Search in SalesRecord
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
