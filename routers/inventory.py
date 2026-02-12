# routers/inventory.py
from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services import branch_service, stock_service
from models import VehicleMaster, Branch

router = APIRouter(prefix="/inventory", tags=["inventory"])
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


@router.get("/stock-levels", response_class=HTMLResponse)
async def stock_levels(request: Request, db: Session = Depends(get_db)):
    """Stock Levels - Grouped by model/variant/color"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    username = request.session.get("username")
    user_role = request.session.get("user_role")

    # Get active context
    active_branch_id = get_active_context(request, db)
    active_branch = db.query(Branch).filter(Branch.Branch_ID == active_branch_id).first()
    branch_name = active_branch.Branch_Name if active_branch else "N/A"

    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get stock grouped by model using pandas (your existing service)
    stock_df = stock_service.get_multi_branch_stock(db, branch_ids)

    # Group by model for display
    stock_by_model = {}
    if not stock_df.empty:
        for _, row in stock_df.iterrows():
            model = row['model']
            if model not in stock_by_model:
                stock_by_model[model] = []
            stock_by_model[model].append({
                'branch': row['Branch_Name'],
                'variant': row['variant'],
                'color': row['color'],
                'stock': row['Stock']
            })

    # Calculate total count
    total_vehicles = sum([
        sum([item['stock'] for item in items])
        for items in stock_by_model.values()
    ])

    total_models = len(stock_by_model)
    branch_count = len(managed_branches)

    return templates.TemplateResponse(
        "inventory_stock_levels.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "stock_by_model": stock_by_model,
            "total_vehicles": total_vehicles,
            "total_models": total_models,
            "branch_count": branch_count,
            "managed_branches": managed_branches,
            "current_page": "inventory"
        }
    )


@router.get("/locator", response_class=HTMLResponse)
async def vehicle_locator(request: Request, db: Session = Depends(get_db)):
    """Vehicle Locator - Search by attributes or chassis"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    username = request.session.get("username")
    user_role = request.session.get("user_role")

    # Get active context
    active_branch_id = get_active_context(request, db)
    active_branch = db.query(Branch).filter(Branch.Branch_ID == active_branch_id).first()
    branch_name = active_branch.Branch_Name if active_branch else "N/A"

    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get master data for dropdowns
    master_data = stock_service.get_vehicle_master_data(db)

    return templates.TemplateResponse(
        "inventory_locator.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "master_data": master_data,
            "current_page": "inventory"
        }
    )


@router.post("/locator/search")
async def search_vehicles(
        request: Request,
        search_mode: str = Form(...),
        chassis: Optional[str] = Form(None),
        model: Optional[str] = Form(None),
        variant: Optional[str] = Form(None),
        color: Optional[str] = Form(None),
        db: Session = Depends(get_db)
):
    """Search vehicles by chassis or attributes"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    username = request.session.get("username")
    user_role = request.session.get("user_role")

    # Get active context
    active_branch_id = get_active_context(request, db)
    active_branch = db.query(Branch).filter(Branch.Branch_ID == active_branch_id).first()
    branch_name = active_branch.Branch_Name if active_branch else "N/A"

    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Use existing service to search
    if search_mode == "chassis":
        results_df = stock_service.search_vehicles(db, chassis=chassis)
    else:
        results_df = stock_service.search_vehicles(db, model=model, variant=variant, color=color)

    # Filter results to only show vehicles in managed branches
    if not results_df.empty:
        results_df = results_df[results_df['current_branch_id'].isin(branch_ids)]

    results = results_df.to_dict('records') if not results_df.empty else []
    master_data = stock_service.get_vehicle_master_data(db)

    return templates.TemplateResponse(
        "inventory_locator.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch_name,
            "master_data": master_data,
            "results": results,
            "current_page": "inventory"
        }
    )
