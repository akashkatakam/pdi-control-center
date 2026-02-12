# routers/logistics.py - Complete file with Receive functionality
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta

from database import get_db
from models import VehicleMaster, Branch, InventoryTransaction
from services import branch_service
from routers.overview import get_active_context, get_context_data, check_auth

router = APIRouter(prefix="/logistics", tags=["logistics"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def logistics_dashboard(
        request: Request,
        db: Session = Depends(get_db)
):
    """Logistics Dashboard - Main landing page"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Calculate stats
    total_stock = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).count()

    in_transit = db.query(VehicleMaster).filter(
        VehicleMaster.status == "In Transit"
    ).count()

    # Pending transfers
    pending_transfers = db.query(InventoryTransaction).filter(
        InventoryTransaction.From_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "OUTWARD"
    ).count()

    # Today's movements
    today = datetime.now().date()
    today_movements = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Date == today
    ).count()

    # Recent activities
    recent_transactions = db.query(InventoryTransaction, Branch).join(
        Branch, InventoryTransaction.Current_Branch_ID == Branch.Branch_ID
    ).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids)
    ).order_by(InventoryTransaction.Date.desc()).limit(10).all()

    activities = []
    for txn, branch in recent_transactions:
        activities.append({
            'type': txn.Transaction_Type,
            'model': txn.Model,
            'branch': branch.Branch_Name,
            'date': txn.Date.strftime("%d %b %Y"),
            'quantity': txn.Quantity,
            'load_number': txn.Load_Number
        })

    return templates.TemplateResponse(
        "logistics.html",
        {
            "request": request,
            **context,
            "total_stock": total_stock,
            "in_transit": in_transit,
            "today_movements": today_movements,
            "recent_activities": activities,
            "current_page": "logistics"
        }
    )


@router.get("/receive", response_class=HTMLResponse)
async def receive_inward(
        request: Request,
        db: Session = Depends(get_db)
):
    """Receive Inward - Show pending loads for CURRENT BRANCH ONLY"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    user_data = request.session.get("user")

    # Determine the specific branch to show loads for
    if user_data.get("role") == "Owner":
        # For Owner, use the active context branch
        current_branch_id = context["active_context"]
    else:
        # For PDI/Manager users, use their specific branch
        current_branch_id = user_data.get("branch_id")

    # Get the current branch details
    current_branch = db.query(Branch).filter(Branch.Branch_ID == current_branch_id).first()
    if not current_branch:
        return RedirectResponse(url="/overview")

    # Get pending loads ONLY for this specific branch
    pending_transactions = db.query(InventoryTransaction).filter(
        InventoryTransaction.To_Branch_ID == current_branch_id,  # Loads coming TO this branch
        InventoryTransaction.Transaction_Type == "OUTWARD",
        InventoryTransaction.Status == "Pending"
    ).order_by(InventoryTransaction.Date.desc()).all()

    # Group by Load Number
    load_groups = {}
    for txn in pending_transactions:
        load_num = txn.Load_Number
        if not load_num:
            continue

        if load_num not in load_groups:
            from_branch = db.query(Branch).filter(Branch.Branch_ID == txn.From_Branch_ID).first()

            load_groups[load_num] = {
                'load_number': load_num,
                'from_branch': from_branch.Branch_Name if from_branch else 'Unknown',
                'from_branch_id': txn.From_Branch_ID,
                'sent_date': txn.Date.strftime("%d %b %Y"),
                'sent_datetime': txn.Date,
                'total_vehicles': 0,
                'models': set(),
                'chassis_numbers': []
            }

        load_groups[load_num]['total_vehicles'] += txn.Quantity
        if txn.Model:
            load_groups[load_num]['models'].add(txn.Model)
        if txn.chassis_no:
            load_groups[load_num]['chassis_numbers'].append(txn.chassis_no)

    # Calculate days in transit
    for load_data in load_groups.values():
        days_in_transit = (datetime.now().date() - load_data['sent_datetime'].date()).days
        load_data['days_in_transit'] = days_in_transit
        load_data['is_urgent'] = days_in_transit > 5
        load_data['models_list'] = ', '.join(load_data['models'])

    pending_loads = sorted(load_groups.values(), key=lambda x: x['sent_datetime'], reverse=True)

    # Recent receipts for this branch
    recent_receipts = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID == current_branch_id,
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Status == "Completed"
    ).order_by(InventoryTransaction.Date.desc()).limit(10).all()

    recent_list = []
    for receipt in recent_receipts:
        from_branch = None
        if receipt.From_Branch_ID:
            from_branch = db.query(Branch).filter(Branch.Branch_ID == receipt.From_Branch_ID).first()

        recent_list.append({
            'load_number': receipt.Load_Number or 'N/A',
            'from_branch': from_branch.Branch_Name if from_branch else receipt.Remarks or 'Unknown',
            'received_date': receipt.Date.strftime("%d %b %Y"),
            'vehicles': receipt.Quantity,
            'model': receipt.Model,
            'received_by': receipt.Remarks or 'System'
        })

    # Stats for current branch only
    pending_count = len(pending_loads)
    pending_vehicles = sum(load['total_vehicles'] for load in pending_loads)
    urgent_loads = sum(1 for load in pending_loads if load.get('is_urgent', False))

    # Today's receipts
    today = datetime.now().date()
    today_receipts = db.query(func.sum(InventoryTransaction.Quantity)).filter(
        InventoryTransaction.Current_Branch_ID == current_branch_id,
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date == today
    ).scalar() or 0

    return templates.TemplateResponse(
        "receive_inward.html",
        {
            "request": request,
            **context,
            "current_branch_name": current_branch.Branch_Name,
            "current_branch_id": current_branch_id,
            "pending_loads": pending_loads,
            "recent_receipts": recent_list,
            "pending_count": pending_count,
            "pending_vehicles": pending_vehicles,
            "urgent_loads": urgent_loads,
            "today_receipts": int(today_receipts),
            "current_page": "logistics"
        }
    )


@router.post("/receive/receive-load")
async def receive_load_action(
        request: Request,
        db: Session = Depends(get_db)
):
    """Process receiving a load - Update to use current branch"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        load_number = form_data.get("load_number")

        if not load_number:
            return JSONResponse({"success": False, "message": "Load number is required"})

        user_data = request.session.get("user")

        # Determine the receiving branch
        if user_data.get("role") == "Owner":
            context = get_context_data(request, db)
            receiving_branch_id = context["active_context"]
        else:
            receiving_branch_id = user_data.get("branch_id")

        # Get all pending transactions for this load TO this specific branch
        pending_transactions = db.query(InventoryTransaction).filter(
            InventoryTransaction.Load_Number == load_number,
            InventoryTransaction.To_Branch_ID == receiving_branch_id,
            InventoryTransaction.Transaction_Type == "OUTWARD",
            InventoryTransaction.Status == "Pending"
        ).all()

        if not pending_transactions:
            return JSONResponse({
                "success": False,
                "message": "No pending transactions found for this load at your branch"
            })

        received_count = 0

        for txn in pending_transactions:
            # Update transaction status
            txn.Status = "Completed"

            # Create inward transaction
            inward_txn = InventoryTransaction(
                Date=datetime.now().date(),
                chassis_no=txn.chassis_no,
                Model=txn.Model,
                Variant=txn.Variant,
                Color=txn.Color,
                Transaction_Type="INWARD",
                From_Branch_ID=txn.From_Branch_ID,
                To_Branch_ID=None,
                Current_Branch_ID=receiving_branch_id,
                Quantity=txn.Quantity,
                Load_Number=load_number,
                Status="Completed",
                Remarks=f"Received from {txn.From_Branch_ID}"
            )
            db.add(inward_txn)

            # Update vehicles if chassis exists
            if txn.chassis_no:
                vehicles = db.query(VehicleMaster).filter(
                    VehicleMaster.chassis_no == txn.chassis_no
                ).all()

                for vehicle in vehicles:
                    vehicle.current_branch_id = receiving_branch_id
                    vehicle.status = "In Stock"
                    vehicle.load_reference_number = load_number
                    received_count += 1

        db.commit()

        return JSONResponse({
            "success": True,
            "message": f"Successfully received {received_count} vehicle(s) from load {load_number}"
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Error receiving load: {str(e)}"
        }, status_code=500)


@router.get("/transfer", response_class=HTMLResponse)
async def transfer_stock(
        request: Request,
        db: Session = Depends(get_db)
):
    """Transfer Stock between branches"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Get managed branches for transfer options
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)

    # Get available stock at active branch
    available_vehicles = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id == active_branch_id,
        VehicleMaster.status == "In Stock"
    ).all()

    # Recent transfers
    recent_transfers = db.query(InventoryTransaction).filter(
        InventoryTransaction.From_Branch_ID == active_branch_id,
        InventoryTransaction.Transaction_Type == "OUTWARD"
    ).order_by(InventoryTransaction.Date.desc()).limit(10).all()

    transfers = []
    for txn in recent_transfers:
        to_branch = db.query(Branch).filter(Branch.Branch_ID == txn.To_Branch_ID).first()
        transfers.append({
            'load_number': txn.Load_Number,
            'to_branch': to_branch.Branch_Name if to_branch else 'Unknown',
            'date': txn.Date.strftime("%d %b %Y"),
            'vehicles': txn.Quantity,
            'status': txn.Status
        })

    return templates.TemplateResponse(
        "transfer_stock.html",
        {
            "request": request,
            **context,
            "branches": managed_branches,
            "available_vehicles": available_vehicles,
            "recent_transfers": transfers,
            "current_page": "logistics"
        }
    )


@router.post("/transfer/create")
async def create_transfer(
        request: Request,
        db: Session = Depends(get_db)
):
    """Create a new transfer"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        to_branch_id = int(form_data.get("to_branch_id"))
        chassis_numbers = form_data.get("chassis_numbers", "").split(",")
        chassis_numbers = [c.strip() for c in chassis_numbers if c.strip()]

        if not to_branch_id or not chassis_numbers:
            return JSONResponse({
                "success": False,
                "message": "Destination branch and chassis numbers are required"
            })

        context = get_context_data(request, db)
        from_branch_id = context["active_context"]

        # Generate load number
        load_number = f"LOAD{datetime.now().strftime('%Y%m%d%H%M%S')}"

        transferred_count = 0

        for chassis_no in chassis_numbers:
            # Get vehicle
            vehicle = db.query(VehicleMaster).filter(
                VehicleMaster.chassis_no == chassis_no,
                VehicleMaster.current_branch_id == from_branch_id,
                VehicleMaster.status == "In Stock"
            ).first()

            if not vehicle:
                continue

            # Create outward transaction
            outward_txn = InventoryTransaction(
                Date=datetime.now().date(),
                chassis_no=chassis_no,
                Model=vehicle.model,
                Variant=vehicle.variant,
                Color=vehicle.color,
                Transaction_Type="OUTWARD",
                From_Branch_ID=from_branch_id,
                To_Branch_ID=to_branch_id,
                Current_Branch_ID=from_branch_id,
                Quantity=1,
                Load_Number=load_number,
                Status="Pending",
                Remarks=f"Transfer to branch {to_branch_id}"
            )
            db.add(outward_txn)

            # Update vehicle status
            vehicle.status = "In Transit"
            vehicle.load_reference_number = load_number

            transferred_count += 1

        db.commit()

        return JSONResponse({
            "success": True,
            "message": f"Successfully created transfer with {transferred_count} vehicle(s). Load: {load_number}"
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Error creating transfer: {str(e)}"
        }, status_code=500)


@router.get("/track", response_class=HTMLResponse)
async def track_vehicles(
        request: Request,
        db: Session = Depends(get_db)
):
    """Track vehicles in transit"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)

    # Get all in-transit vehicles
    in_transit_vehicles = db.query(VehicleMaster).filter(
        VehicleMaster.status == "In Transit"
    ).all()

    # Group by load number
    load_groups = {}
    for vehicle in in_transit_vehicles:
        load_num = vehicle.load_reference_number or "NO_LOAD"

        if load_num not in load_groups:
            load_groups[load_num] = {
                'load_number': load_num,
                'vehicles': [],
                'count': 0,
                'sent_date': vehicle.created_at.strftime("%d %b %Y") if vehicle.created_at else 'Unknown'
            }

        load_groups[load_num]['vehicles'].append({
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color
        })
        load_groups[load_num]['count'] += 1

    loads = list(load_groups.values())

    return templates.TemplateResponse(
        "track_vehicles.html",
        {
            "request": request,
            **context,
            "loads": loads,
            "total_in_transit": len(in_transit_vehicles),
            "current_page": "logistics"
        }
    )
