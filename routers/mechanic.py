# routers/mechanic.py - Mechanic PDI Interface
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from models import SalesRecord, VehicleMaster, User, Branch
from routers.overview import check_auth, get_context_data

router = APIRouter(prefix="/mechanic", tags=["mechanic"])
templates = Jinja2Templates(directory="templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def mechanic_dashboard(
        request: Request,
        db: Session = Depends(get_db)
):
    """Mechanic Dashboard - Show assigned PDI tasks"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    username = request.session.get("username")
    user_role = request.session.get("user_role")
    branch_id = request.session.get("branch_id")

    # Only mechanics can access
    if user_role != "Mechanic":
        return RedirectResponse(url="/overview")

    # Get mechanic's assigned tasks
    assigned_tasks = db.query(
        SalesRecord, VehicleMaster, Branch
    ).join(
        VehicleMaster, SalesRecord.chassis_no == VehicleMaster.chassis_no, isouter=True
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.pdi_assigned_to == username,
        SalesRecord.fulfillment_status == "PDI In Progress"
    ).all()

    # Get completed tasks (last 7 days)
    seven_days_ago = datetime.now() - timedelta(days=7)
    completed_tasks = db.query(
        SalesRecord, VehicleMaster, Branch
    ).join(
        VehicleMaster, SalesRecord.chassis_no == VehicleMaster.chassis_no, isouter=True
    ).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.pdi_assigned_to == username,
        SalesRecord.fulfillment_status == "PDI Complete",
        SalesRecord.pdi_completion_date >= seven_days_ago
    ).order_by(SalesRecord.pdi_completion_date.desc()).all()

    # Format tasks
    pending_list = []
    for sale, vehicle, branch in assigned_tasks:
        pending_list.append({
            "id": sale.id,
            "dc_number": sale.DC_Number,
            "customer": sale.Customer_Name,
            "chassis": sale.chassis_no or "Not Scanned",
            "engine": sale.engine_no or "Not Scanned",
            "model": sale.Model,
            "variant": sale.Variant,
            "color": sale.Paint_Color,
            "branch": branch.Branch_Name,
            "vehicle_available": vehicle is not None
        })

    completed_list = []
    for sale, vehicle, branch in completed_tasks:
        completed_list.append({
            "dc_number": sale.DC_Number,
            "chassis": sale.chassis_no,
            "engine": sale.engine_no,
            "model": sale.Model,
            "completion_date": sale.pdi_completion_date.strftime(
                "%d %b %Y %I:%M %p") if sale.pdi_completion_date else "N/A"
        })

    # Get branch info
    branch = db.query(Branch).filter(Branch.Branch_ID == branch_id).first()

    return templates.TemplateResponse(
        "mechanic_dashboard.html",
        {
            "request": request,
            "username": username,
            "user_role": user_role,
            "branch_name": branch.Branch_Name if branch else "N/A",
            "pending_tasks": pending_list,
            "completed_tasks": completed_list,
            "total_pending": len(pending_list),
            "total_completed": len(completed_list),
            "current_page": "mechanic"
        }
    )


@router.get("/pdi/{sale_id}", response_class=HTMLResponse)
async def pdi_checklist(
        request: Request,
        sale_id: int,
        db: Session = Depends(get_db)
):
    """PDI Checklist page for a specific sale"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    username = request.session.get("username")
    user_role = request.session.get("user_role")

    # Only mechanics can access
    if user_role != "Mechanic":
        return RedirectResponse(url="/overview")

    # Get sale record
    sale = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()

    if not sale:
        return RedirectResponse(url="/mechanic/dashboard")

    # Verify this task is assigned to this mechanic
    if sale.pdi_assigned_to != username:
        return RedirectResponse(url="/mechanic/dashboard")

    # Get vehicle if exists
    vehicle = None
    if sale.chassis_no:
        vehicle = db.query(VehicleMaster).filter(
            VehicleMaster.chassis_no == sale.chassis_no
        ).first()

    # Get branch info
    branch = db.query(Branch).filter(Branch.Branch_ID == sale.Branch_ID).first()

    return templates.TemplateResponse(
        "mechanic_pdi_checklist.html",
        {
            "request": request,
            "username": username,
            "sale": sale,
            "vehicle": vehicle,
            "branch_name": branch.Branch_Name if branch else "N/A",
            "current_page": "mechanic"
        }
    )


@router.post("/scan-qr")
async def scan_qr_code(
        request: Request,
        db: Session = Depends(get_db)
):
    """Scan QR code to identify vehicle and link to sale"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        sale_id = int(form_data.get("sale_id"))
        qr_data = form_data.get("qr_data", "").strip()

        if not qr_data:
            return JSONResponse({"success": False, "message": "No QR data provided"})

        # QR data should contain chassis number
        # Format could be: CHASSIS:ME4KF19H5NK123456 or just the chassis number
        chassis_no = qr_data
        if ":" in qr_data:
            parts = qr_data.split(":")
            chassis_no = parts[-1].strip()

        # Find vehicle in VehicleMaster
        vehicle = db.query(VehicleMaster).filter(
            VehicleMaster.chassis_no == chassis_no
        ).first()

        if not vehicle:
            return JSONResponse({
                "success": False,
                "message": f"Vehicle with chassis {chassis_no} not found in inventory"
            })

        # Get sale record
        sale = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()

        if not sale:
            return JSONResponse({"success": False, "message": "Sale record not found"})

        # Update sale with vehicle details
        sale.chassis_no = vehicle.chassis_no
        sale.engine_no = vehicle.engine_no

        # Update vehicle status
        vehicle.status = "Allotted"
        vehicle.sale_id = sale_id
        vehicle.dc_number = sale.DC_Number

        db.commit()

        return JSONResponse({
            "success": True,
            "message": "Vehicle scanned successfully",
            "chassis_no": vehicle.chassis_no,
            "engine_no": vehicle.engine_no,
            "model": vehicle.model,
            "variant": vehicle.variant,
            "color": vehicle.color
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Error scanning QR: {str(e)}"
        }, status_code=500)


@router.post("/complete-pdi")
async def complete_pdi(
        request: Request,
        db: Session = Depends(get_db)
):
    """Mark PDI as complete"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        sale_id = int(form_data.get("sale_id"))

        # Get sale record
        sale = db.query(SalesRecord).filter(SalesRecord.id == sale_id).first()

        if not sale:
            return JSONResponse({"success": False, "message": "Sale record not found"})

        # Verify chassis and engine are filled
        if not sale.chassis_no or not sale.engine_no:
            return JSONResponse({
                "success": False,
                "message": "Please scan vehicle QR code first"
            })

        # Update sale status
        sale.fulfillment_status = "PDI Complete"
        sale.pdi_completion_date = datetime.now()

        db.commit()

        return JSONResponse({
            "success": True,
            "message": f"PDI completed for DC {sale.DC_Number}"
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Error completing PDI: {str(e)}"
        }, status_code=500)
