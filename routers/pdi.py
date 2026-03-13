# routers/pdi.py
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services import branch_service
from models import VehicleMaster, SalesRecord, Branch

router = APIRouter(prefix="/pdi", tags=["pdi"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request, allowed_roles: list = ['Owner', 'PDI']):
    """Check if user is authenticated and has correct role"""
    if not request.session.get("logged_in"):
        return False
    if request.session.get("user_role") not in allowed_roles:
        return False
    return True


@router.get("/dashboard", response_class=HTMLResponse)
async def pdi_dashboard(
        request: Request,
        db: Session = Depends(get_db),
        status_filter: Optional[str] = Query(None)
):
    """PDI Dashboard - Main view for PDI and Owner roles"""

    # Check authentication
    if not check_auth(request):
        return RedirectResponse(url="/login")

    # Get user data from session
    branch_id = request.session.get("branch_id")
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")

    # Get all managed branches (head branch + sub-branches)
    managed_branches = branch_service.get_managed_branches(db, branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get statistics across all managed branches
    # PDI counts from SalesRecord table
    pending_pdi = db.query(SalesRecord).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI Pending"
    ).count()

    in_progress = db.query(SalesRecord).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI In Progress"
    ).count()

    # Inventory counts from VehicleMaster table
    in_transit = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Transit"
    ).count()

    in_stock = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).count()

    # Query sales records with vehicle details based on filter
    sales_query = db.query(
        SalesRecord,
        VehicleMaster,
        Branch
    ).join(
        VehicleMaster, SalesRecord.chassis_no == VehicleMaster.chassis_no
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.Branch_ID.in_(branch_ids)
    )

    # Apply filter if provided
    if status_filter == "PDI Pending":
        sales_query = sales_query.filter(SalesRecord.fulfillment_status == "PDI Pending")
    elif status_filter == "PDI In Progress":
        sales_query = sales_query.filter(SalesRecord.fulfillment_status == "PDI In Progress")
    elif status_filter == "PDI Complete":
        sales_query = sales_query.filter(SalesRecord.fulfillment_status == "PDI Complete")

    sales_records = sales_query.all()

    # Format data for template
    vehicles = []
    for sale, vehicle, branch in sales_records:
        vehicles.append({
            'sale_id': sale.id,
            'branch_name': branch.Branch_Name,
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color,
            'customer_name': sale.Customer_Name,
            'pdi_status': sale.fulfillment_status,
            'vehicle_status': vehicle.status,
            'sale_date': sale.Timestamp
        })

    return templates.TemplateResponse(
        "pdi_dashboard.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "vehicles": vehicles,
            "pending_pdi": pending_pdi,
            "in_progress": in_progress,
            "in_transit": in_transit,
            "in_stock": in_stock,
            "status_filter": status_filter,
            "managed_branches": managed_branches,
            "branch_count": len(managed_branches)
        }
    )


@router.post("/vehicle/update-pdi-status")
async def update_pdi_status(
        request: Request,
        sale_id: int = Form(...),
        new_status: str = Form(...),
        db: Session = Depends(get_db)
):
    """Update PDI status in SalesRecord"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    # Find and update sale record
    sale = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()

    if sale:
        sale.fulfillment_status = new_status
        db.commit()

    return RedirectResponse(url="/pdi/dashboard", status_code=303)


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_view(
        request: Request,
        db: Session = Depends(get_db),
        status_filter: Optional[str] = Query(None)
):
    """Inventory view - shows VehicleMaster records"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    branch_id = request.session.get("branch_id")
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")

    # Get all managed branches
    managed_branches = branch_service.get_managed_branches(db, branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Query vehicles
    vehicles_query = db.query(
        VehicleMaster,
        Branch
    ).join(
        Branch, VehicleMaster.current_branch_id == Branch.Branch_ID
    ).filter(
        VehicleMaster.current_branch_id.in_(branch_ids)
    )

    # Apply filter
    if status_filter:
        vehicles_query = vehicles_query.filter(VehicleMaster.status == status_filter)

    vehicles_data = vehicles_query.all()

    # Format for template
    vehicles = []
    for vehicle, branch in vehicles_data:
        vehicles.append({
            'branch_name': branch.Branch_Name,
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color,
            'status': vehicle.status,
            'date_received': vehicle.date_received,
            'load_reference': vehicle.load_reference_number
        })

    return templates.TemplateResponse(
        "inventory_view.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "vehicles": vehicles,
            "status_filter": status_filter
        }
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
        request: Request,
        db: Session = Depends(get_db)
):
    """Reports page"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    branch_id = request.session.get("branch_id")

    # Placeholder for reports
    report_data = {}

    return templates.TemplateResponse(
        "pdi_reports.html",
        {
            "request": request,
            "report_data": report_data
        }
    )
