# routers/task_manager.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from services import branch_service
from models import SalesRecord, VehicleMaster, User, Branch

router = APIRouter(prefix="/task-manager", tags=["task_manager"])
templates = Jinja2Templates(directory="templates")


def check_auth(request: Request):
    if not request.session.get("logged_in"):
        return False
    return True


@router.get("", response_class=HTMLResponse)
async def task_manager_page(request: Request, db: Session = Depends(get_db)):
    """Task Manager - Assign PDI tasks to mechanics"""
    
    if not check_auth(request):
        return RedirectResponse(url="/login")
    
    branch_id = request.session.get("branch_id")
    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_name = request.session.get("branch_name")
    
    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]
    
    # Get mechanics in the branch
    mechanics = db.query(User).filter(
        User.Branch_ID.in_(branch_ids),
        User.role == "Mechanic"
    ).all()
    
    # Get pending sales (PDI Pending)
    pending_sales = db.query(
        SalesRecord, VehicleMaster, Branch
    ).join(
        VehicleMaster, SalesRecord.Chassis_No == VehicleMaster.chassis_no
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI Pending"
    ).all()
    
    # Get in-progress tasks (monitoring)
    in_progress_tasks = db.query(
        SalesRecord, VehicleMaster, Branch, User
    ).join(
        VehicleMaster, SalesRecord.Chassis_No == VehicleMaster.chassis_no
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).outerjoin(
        User, SalesRecord.Assigned_Mechanic_ID == User.id
    ).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI In Progress"
    ).all()
    
    # Format data
    sales_list = [
        {
            "id": sale.id,
            "dc_number": vehicle.dc_number or "N/A",
            "customer": sale.Customer_Name,
            "chassis": sale.Chassis_No,
            "model": vehicle.model,
            "branch": branch.Branch_Name
        } for sale, vehicle, branch in pending_sales
    ]
    
    monitoring_list = [
        {
            "customer": sale.Customer_Name,
            "chassis": sale.Chassis_No,
            "model": vehicle.model,
            "mechanic": user.username if user else "Unassigned",
            "branch": branch.Branch_Name,
            "status": sale.fulfillment_status
        } for sale, vehicle, branch, user in in_progress_tasks
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
            "current_page": "task_manager"
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
    
    # Update sale record
    sale = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()
    if sale:
        sale.Assigned_Mechanic_ID = mechanic_id
        sale.fulfillment_status = "PDI In Progress"
        db.commit()
    
    return RedirectResponse(url="/task-manager", status_code=303)
