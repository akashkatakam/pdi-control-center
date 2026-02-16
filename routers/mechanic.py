# routers/mechanic.py
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from services import sales_service
from models import SalesRecord, VehicleMaster, Branch
from routers.overview import check_auth, get_context_data

router = APIRouter(prefix="/mechanic", tags=["mechanic"])
templates = Jinja2Templates(directory="templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def mechanic_dashboard(
        request: Request,
        db: Session = Depends(get_db)
):
    """Mechanic Dashboard - View assigned PDI work"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)

    # Get mechanic username from session
    mechanic_username = request.session.get("username")
    branch_id = str(context["active_context"])

    # Get branch name
    branch = db.query(Branch).filter(Branch.Branch_ID == int(branch_id)).first()
    branch_name = branch.Branch_Name if branch else "Unknown"

    # Get pending sales records assigned to this mechanic (now returns list of dicts)
    pending_records = sales_service.get_sales_records_for_mechanic(db, mechanic_username, branch_id)

    # Transform to template format
    pending_tasks = []
    for record in pending_records:
        pending_tasks.append({
            'id': record['id'],
            'dc_number': record.get('dc_number') or 'N/A',
            'chassis': record.get('chassis_no') or 'Not Scanned',
            'engine': record.get('engine_no') or 'N/A',
            'customer': record.get('customer_name') or 'N/A',
            'model': record.get('model') or 'N/A',
            'variant': record.get('variant') or 'N/A',
            'color': record.get('color') or 'N/A',
        })

    # Get completed records (last 48 hours, now returns list of dicts)
    completed_records = sales_service.get_completed_sales_last_48h(db, branch_id)

    # Filter for this mechanic's completed work
    completed_tasks = []
    for record in completed_records:
        if record.get('pdi_assigned_to') == mechanic_username and record.get('pdi_completion_date'):
            completion_date = record['pdi_completion_date']
            if isinstance(completion_date, datetime):
                formatted_date = completion_date.strftime('%d-%b-%Y %I:%M %p')
            else:
                formatted_date = str(completion_date)

            completed_tasks.append({
                'dc_number': record.get('dc_number') or 'N/A',
                'chassis': record.get('chassis_no') or 'N/A',
                'engine': record.get('engine_no') or 'N/A',
                'model': record.get('model') or 'N/A',
                'completion_date': formatted_date
            })

    # Stats
    total_pending = len(pending_tasks)
    total_completed = len(completed_tasks)

    return templates.TemplateResponse(
        "mechanic_dashboard.html",
        {
            "request": request,
            **context,
            "pending_tasks": pending_tasks,
            "completed_tasks": completed_tasks,
            "total_pending": total_pending,
            "total_completed": total_completed,
            "branch_name": branch_name,
            "current_page": "mechanic"
        }
    )


@router.get("/pdi/{sale_id}", response_class=HTMLResponse)
async def pdi_work_form(
        request: Request,
        sale_id: int,
        db: Session = Depends(get_db)
):
    """PDI Completion Form"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)

    # Get sales record
    sales_record: SalesRecord = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()

    if not sales_record:
        return RedirectResponse(url="/mechanic/dashboard?error=Record not found")

    # Verify this record is assigned to the logged-in mechanic
    mechanic_username = request.session.get("username")
    if sales_record.pdi_assigned_to != mechanic_username:
        return RedirectResponse(url="/mechanic/dashboard?error=Not authorized for this task")

    # Get available vehicles for this branch matching model/variant/color
    available_vehicles = db.query(VehicleMaster).filter(
        VehicleMaster.status == 'In Stock',
        VehicleMaster.current_branch_id == sales_record.Branch_ID,
        VehicleMaster.model == sales_record.Model,
        VehicleMaster.variant == sales_record.Variant,
        VehicleMaster.color == sales_record.Paint_Color
    ).all()

    # Also get all in-stock vehicles at this branch (fallback)
    all_available = db.query(VehicleMaster).filter(
        VehicleMaster.status == 'In Stock',
        VehicleMaster.current_branch_id == sales_record.Branch_ID
    ).all()

    return templates.TemplateResponse(
        "mechanic_pdi_form.html",
        {
            "request": request,
            **context,
            "sales_record": sales_record,
            "available_vehicles": available_vehicles,
            "current_page": "mechanic",
            "error": request.query_params.get("error"),
            "success": request.query_params.get("success")
        }
    )


@router.post("/pdi/complete")
async def complete_pdi_work(
        request: Request,
        sale_id: int = Form(...),
        chassis_no: str = Form(...),
        engine_no: str = Form(None),
        dc_number: str = Form(None),
        db: Session = Depends(get_db)
):
    """Complete PDI using existing service function"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    # Verify mechanic owns this task
    mechanic_username = request.session.get("username")
    sales_record = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()

    if not sales_record or sales_record.pdi_assigned_to != mechanic_username:
        return RedirectResponse(
            url="/mechanic/dashboard?error=Not authorized",
            status_code=303
        )

    # Use existing complete_pdi function
    success, message = sales_service.complete_pdi(
        db=db,
        sale_id=sale_id,
        chassis_no=chassis_no.strip().upper(),
        engine_no=engine_no.strip().upper() if engine_no else None,
        dc_number=dc_number.strip() if dc_number else None
    )

    if success:
        return RedirectResponse(
            url=f"/mechanic/dashboard?success={message}",
            status_code=303
        )
    else:
        return RedirectResponse(
            url=f"/mechanic/pdi/{sale_id}?error={message}",
            status_code=303
        )
