# routers/task_manager.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from services import branch_service
from models import SalesRecord, VehicleMaster, User, Branch

router = APIRouter(prefix="/task-manager", tags=["task_manager"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request):
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


@router.get("", response_class=HTMLResponse)
async def task_manager_page(request: Request, db: Session = Depends(get_db)):
    """Task Manager - Assign PDI tasks to mechanics"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    username = request.session.get("username")
    user_role = request.session.get("user_role")
    original_branch_id = request.session.get("branch_id")

    # Get active context
    active_branch_id = get_active_context(request, db)
    active_branch = db.query(Branch).filter(Branch.Branch_ID == active_branch_id).first()
    branch_name = active_branch.Branch_Name if active_branch else "N/A"

    # For PDI Manager: ONLY show their own branch (not sub-branches)
    # For Owner: Show only the active context branch (not sub-branches)
    branch_ids = [active_branch_id]  # ONLY the head branch itself

    # Get mechanics in THIS branch only
    mechanics = db.query(User).filter(
        User.Branch_ID == active_branch_id,
        User.role == "Mechanic"
    ).all()

    # Get pending sales (PDI Pending) - ONLY from this branch
    pending_sales = db.query(
        SalesRecord, VehicleMaster, Branch
    ).join(
        VehicleMaster, SalesRecord.chassis_no == VehicleMaster.chassis_no, isouter=True
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.Branch_ID == active_branch_id,  # Only this branch
        SalesRecord.fulfillment_status == "PDI Pending"
    ).all()

    # Get in-progress tasks (monitoring) - ONLY from this branch
    in_progress_tasks = db.query(
        SalesRecord, VehicleMaster, Branch, User
    ).join(
        VehicleMaster, SalesRecord.chassis_no == VehicleMaster.chassis_no, isouter=True
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).outerjoin(
        User, SalesRecord.pdi_assigned_to == User.username
    ).filter(
        SalesRecord.Branch_ID == active_branch_id,  # Only this branch
        SalesRecord.fulfillment_status == "PDI In Progress"
    ).all()

    # Get PDI completed in last 24 hours
    twenty_four_hours_ago = datetime.now() - timedelta(hours=24)
    completed_last_24h = db.query(
        SalesRecord, VehicleMaster, Branch
    ).join(
        VehicleMaster, SalesRecord.chassis_no == VehicleMaster.chassis_no, isouter=True
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.Branch_ID == active_branch_id,  # Only this branch
        SalesRecord.fulfillment_status == "PDI Complete",
        SalesRecord.pdi_completion_date >= twenty_four_hours_ago
    ).order_by(SalesRecord.pdi_completion_date.desc()).all()

    # Format data
    sales_list = [
        {
            "id": sale.id,
            "dc_number": sale.DC_Number,
            "customer": sale.Customer_Name,
            "chassis": sale.chassis_no or "Not Assigned",
            "model": sale.Model,
            "variant": sale.Variant,
            "branch": branch.Branch_Name
        } for sale, vehicle, branch in pending_sales
    ]

    monitoring_list = [
        {
            "id": sale.id,
            "dc_number": sale.DC_Number,
            "customer": sale.Customer_Name,
            "chassis": sale.chassis_no or "Not Assigned",
            "model": sale.Model,
            "variant": sale.Variant,
            "mechanic": user.username if user else sale.pdi_assigned_to or "Unassigned",
            "branch": branch.Branch_Name,
            "status": sale.fulfillment_status
        } for sale, vehicle, branch, user in in_progress_tasks
    ]

    completed_list = [
        {
            "dc_number": sale.DC_Number,
            "chassis": sale.chassis_no or "N/A",
            "model": sale.Model,
            "variant": sale.Variant,
            "color": sale.Paint_Color,
            "pdi_assigned_to": sale.pdi_assigned_to or "N/A",
            "completion_date": sale.pdi_completion_date,
            "branch": branch.Branch_Name
        } for sale, vehicle, branch in completed_last_24h
    ]

    return templates.TemplateResponse(
        "task_manager.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "mechanics": mechanics,
            "sales_list": sales_list,
            "monitoring_list": monitoring_list,
            "completed_list": completed_list,
            "current_page": "task_manager",
            "is_owner": original_branch_id is None
        }
    )


@router.post("/assign")
async def assign_task(
        request: Request,
        mechanic_id: int = Form(...),
        sale_id: int = Form(...),
        db: Session = Depends(get_db)
):
    """Assign a PDI task to a mechanic"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    # Get mechanic username
    mechanic = db.query(User).filter(User.id == mechanic_id).first()
    if not mechanic:
        return RedirectResponse(url="/task-manager", status_code=303)

    # Update sale record
    sale = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()
    if sale:
        sale.pdi_assigned_to = mechanic.username
        sale.fulfillment_status = "PDI In Progress"
        db.commit()

    return RedirectResponse(url="/task-manager", status_code=303)
