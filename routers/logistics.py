# routers/logistics.py - Clean Receive and Transfer functionality
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from database import get_db
from models import VehicleMaster, Branch, InventoryTransaction
from services import branch_service, email_service
from routers.overview import get_active_context, get_context_data, check_auth

router = APIRouter(prefix="/logistics", tags=["logistics"])
templates = Jinja2Templates(directory="templates")


@router.get("/receive", response_class=HTMLResponse)
async def receive_inward(
        request: Request,
        db: Session = Depends(get_db)
):
    """Receive Inward - Email-based load management"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Get pending loads from in-transit vehicles
    pending_loads = email_service.get_pending_loads_for_branch(db, active_branch_id)

    # Calculate totals
    total_expected = sum(load['vehicle_count'] for load in pending_loads)

    # Get today's receipts
    today = datetime.now().date()
    today_received = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID == active_branch_id,
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date == today
    ).count()

    # Get recent receipts (vehicles received in last 7 days)
    recent_date = datetime.now() - timedelta(days=7)
    recent_receipts = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID == active_branch_id,
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date >= recent_date.date()
    ).group_by(InventoryTransaction.Load_Number).all()

    recent_data = []
    for receipt in recent_receipts:
        if receipt.Load_Number:
            vehicle_count = db.query(InventoryTransaction).filter(
                InventoryTransaction.Load_Number == receipt.Load_Number,
                InventoryTransaction.Current_Branch_ID == active_branch_id
            ).count()

            recent_data.append({
                "load_reference": receipt.Load_Number,
                "vehicle_count": vehicle_count,
                "received_at": receipt.Date.strftime("%Y-%m-%d")
            })

    # Format loads for display
    loads_data = []
    for load in pending_loads:
        loads_data.append({
            "load_reference": load['load_reference'],
            "source_branch": load['source_branch'],
            "expected_date": datetime.now().strftime("%Y-%m-%d"),
            "vehicle_count": load['vehicle_count'],
            "all_received": False,
            "vehicles": load['vehicles']
        })

    return templates.TemplateResponse(
        "logistics_receive.html",
        {
            "request": request,
            **context,
            "pending_loads": loads_data,
            "total_expected": total_expected,
            "today_received": today_received,
            "recent_receipts": recent_data[:5],
            "unprocessed_emails": 0,  # Could track this
            "current_page": "logistics"
        }
    )


@router.post("/receive/receive-load")
async def receive_load_action(
        request: Request,
        db: Session = Depends(get_db)
):
    """Process receiving a load - Update VehicleMaster and create INWARD transaction"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        load_number = form_data.get("load_number")

        if not load_number:
            return JSONResponse({"success": False, "message": "Load number is required"})

        context = get_context_data(request, db)
        receiving_branch_id = context["active_context"]

        if not receiving_branch_id:
            return JSONResponse({"success": False, "message": "Branch information not found"})

        # Get all pending OUTWARD transactions for this load to this branch
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
            # Update the outward transaction status
            txn.Status = "Completed"

            # Find and update vehicle in VehicleMaster
            if txn.chassis_no:
                vehicle = db.query(VehicleMaster).filter(
                    VehicleMaster.chassis_no == txn.chassis_no
                ).first()

                if vehicle:
                    vehicle.current_branch_id = receiving_branch_id
                    vehicle.status = "In Stock"
                    received_count += 1

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
                Remarks=f"Received from Branch {txn.From_Branch_ID}"
            )
            db.add(inward_txn)

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
        "logistics_transfer.html",
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
    """Create a new transfer - Only creates OUTWARD transaction"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        to_branch_id = form_data.get("to_branch_id")

        # Validate to_branch_id
        if not to_branch_id:
            return JSONResponse({
                "success": False,
                "message": "Destination branch is required"
            })

        to_branch_id = int(to_branch_id)
        chassis_numbers = form_data.get("chassis_numbers", "").split(",")
        chassis_numbers = [c.strip() for c in chassis_numbers if c.strip()]

        if not chassis_numbers:
            return JSONResponse({
                "success": False,
                "message": "At least one chassis number is required"
            })

        context = get_context_data(request, db)
        from_branch_id = context["active_context"]

        if not from_branch_id:
            return JSONResponse({
                "success": False,
                "message": "Source branch information not found"
            })

        # Generate load number
        load_number = f"LOAD{datetime.now().strftime('%Y%m%d%H%M%S')}"

        transferred_count = 0

        for chassis_no in chassis_numbers:
            # Get vehicle from VehicleMaster (verify and get details)
            vehicle = db.query(VehicleMaster).filter(
                VehicleMaster.chassis_no == chassis_no,
                VehicleMaster.current_branch_id == from_branch_id,
                VehicleMaster.status == "In Stock"
            ).first()

            if not vehicle:
                continue

            # Create outward transaction ONLY - do NOT update VehicleMaster
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

            transferred_count += 1

        if transferred_count == 0:
            db.rollback()
            return JSONResponse({
                "success": False,
                "message": "No valid vehicles found for transfer. Please check chassis numbers."
            })

        db.commit()

        return JSONResponse({
            "success": True,
            "message": f"Successfully created transfer with {transferred_count} vehicle(s). Load: {load_number}"
        })

    except ValueError as e:
        return JSONResponse({
            "success": False,
            "message": "Invalid branch ID format"
        }, status_code=400)
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Error creating transfer: {str(e)}"
        }, status_code=500)
