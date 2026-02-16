# routers/logistics.py - Clean Receive and Transfer functionality
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

import models
from database import get_db
from models import VehicleMaster, Branch, InventoryTransaction
from services import branch_service, email_service, stock_service
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

    # Get pending loads using stock_service
    pending_load_refs = stock_service.get_pending_loads(db, str(active_branch_id))

    # Build loads data with vehicle details
    loads_data = []
    for load_ref in pending_load_refs:
        # Use stock_service to get vehicles in this load
        vehicles_df = stock_service.get_vehicles_in_load(
            db=db,
            branch_id=str(active_branch_id),
            load_reference=load_ref
        )

        if not vehicles_df.empty:
            vehicles_list = vehicles_df.to_dict('records')
            loads_data.append({
                "load_reference": load_ref,
                "source_branch": "HMSI",  # or get from somewhere
                "expected_date": datetime.now().strftime("%Y-%m-%d"),
                "vehicle_count": len(vehicles_list),
                "all_received": False,
                "vehicles": vehicles_list
            })

    total_expected = sum(load['vehicle_count'] for load in loads_data)

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

    return templates.TemplateResponse(
        "logistics_receive.html",
        {
            "request": request,
            **context,
            "pending_loads": loads_data,
            "total_expected": total_expected,
            "today_received": today_received,
            "recent_receipts": recent_data[:5],
            "unprocessed_emails": 0,
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
            InventoryTransaction.Transaction_Type == "OUTWARD"
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
                Model=txn.Model,
                Variant=txn.Variant,
                Color=txn.Color,
                Transaction_Type="INWARD",
                From_Branch_ID=txn.From_Branch_ID,
                To_Branch_ID=None,
                Current_Branch_ID=receiving_branch_id,
                Quantity=txn.Quantity,
                Load_Number=load_number,
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
    branches = branch_service.get_all_branches(db)

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
            'vehicles': txn.Quantity
        })

    return templates.TemplateResponse(
        "logistics_transfer.html",
        {
            "request": request,
            **context,
            "branches": branches,
            "available_vehicles": available_vehicles,
            "recent_transfers": transfers,
            "current_page": "logistics"
        }
    )


@router.get("/manual-sale", response_class=HTMLResponse)
async def manual_sale_page(
        request: Request,
        db: Session = Depends(get_db)
):
    """Manual Sale Logging - For sub-branches without DC generation"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Get available stock
    available_vehicles = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id == active_branch_id,
        VehicleMaster.status == "In Stock"
    ).all()

    # Recent manual sales
    recent_sales = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID == active_branch_id,
        InventoryTransaction.Transaction_Type == "SALE",
        InventoryTransaction.Remarks.like("%Manual Sale%")
    ).order_by(InventoryTransaction.Date.desc()).limit(10).all()

    return templates.TemplateResponse(
        "logistics_manual_sale.html",
        {
            "request": request,
            **context,
            "available_vehicles": available_vehicles,
            "recent_sales": recent_sales,
            "current_page": "logistics"
        }
    )


@router.post("/manual-sale/create")
async def create_manual_sale(
        request: Request,
        db: Session = Depends(get_db)
):
    """Process manual sale from sub-branches"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        form_data = await request.form()
        chassis_numbers = form_data.get("chassis_numbers", "").split(",")
        chassis_numbers = [c.strip() for c in chassis_numbers if c.strip()]

        sale_date_str = form_data.get("sale_date")
        remarks = form_data.get("remarks", "Manual Sale - Sub Branch")

        if not chassis_numbers:
            return JSONResponse({
                "success": False,
                "message": "At least one chassis number is required"
            })

        context = get_context_data(request, db)
        branch_id = context["active_context"]

        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d").date() if sale_date_str else datetime.now().date()

        sold_count = 0

        for chassis_no in chassis_numbers:
            # Get vehicle from VehicleMaster
            vehicle = db.query(VehicleMaster).filter(
                VehicleMaster.chassis_no == chassis_no,
                VehicleMaster.current_branch_id == branch_id,
                VehicleMaster.status == "In Stock"
            ).first()

            if not vehicle:
                continue

            # Update vehicle status to Sold
            vehicle.status = "Sold"

            # Create SALE transaction
            sale_txn = InventoryTransaction(
                Date=sale_date,
                chassis_no=chassis_no,
                Model=vehicle.model,
                Variant=vehicle.variant,
                Color=vehicle.color,
                Transaction_Type="SALE",
                From_Branch_ID=None,
                To_Branch_ID=None,
                Current_Branch_ID=branch_id,
                Quantity=1,
                Load_Number=None,
                Status="Completed",
                Remarks=f"Manual Sale: {remarks}"
            )
            db.add(sale_txn)

            sold_count += 1

        if sold_count == 0:
            db.rollback()
            return JSONResponse({
                "success": False,
                "message": "No valid vehicles found. Please check chassis numbers."
            })

        db.commit()

        return JSONResponse({
            "success": True,
            "message": f"Successfully logged {sold_count} manual sale(s)"
        })

    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Error logging manual sale: {str(e)}"
        }, status_code=500)


@router.post("/sync-emails")
async def sync_emails(
        request: Request,
        db: Session = Depends(get_db)
):
    """Manually trigger email sync to fetch new loads from S08 attachments"""

    if not check_auth(request):
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    try:
        context = get_context_data(request, db)
        active_branch_id = context["active_context"]

        # Email configurations for different branches
        email_configs = {
            "1": {  # Khammam
                'name': 'Khammam',
                'host': 'imap.gmail.com',
                'user': 'katkammotors@gmail.com',
                'password': 'prkv wpwl wohd fmzp',
                'sender_filter': 'katkamhonda@rediffmail.com'
            },
            "3": {  # Kothagudem
                'name': 'Kothagudem',
                'host': 'imap.gmail.com',
                'user': 'saikatakamhonda@gmail.com',
                'password': 'aqff aows ptuv wdob',
                'sender_filter': 'sap.admin@honda2wheelersindia.com'
            }
        }

        # Get the email config for the active branch
        email_config = email_configs.get(active_branch_id)

        if not email_config:
            return JSONResponse({
                "success": False,
                "error": f"Email sync is not configured for this branch (ID: {active_branch_id}). Only available for Khammam and Kothagudem branches.",
                "new_loads": 0
            })

        # Optional: Load color mappings from database if needed
        color_map = {}

        # Fetch and process emails
        vehicle_data_list, logs = email_service.fetch_and_process_emails(
            db=db,
            branch_id=str(active_branch_id),
            email_config=email_config,
            color_map=color_map
        )

        # Create vehicles from parsed data
        if vehicle_data_list:
            loads_created = email_service.create_vehicles_from_email_data(
                db=db,
                vehicle_data_list=vehicle_data_list,
                branch_id=str(active_branch_id)
            )

            total_vehicles = len(vehicle_data_list)
            total_loads = len(loads_created)

            return JSONResponse({
                "success": True,
                "message": f"Successfully synced {total_loads} load(s) with {total_vehicles} vehicle(s)",
                "new_loads": total_loads,  # This is what your frontend expects
                "vehicles_count": total_vehicles,
                "branch_name": email_config['name'],
                "logs": logs[-10:]
            })
        else:
            return JSONResponse({
                "success": True,
                "message": f"No new emails found for {email_config['name']}",
                "new_loads": 0,  # This is what your frontend expects
                "vehicles_count": 0,
                "branch_name": email_config['name'],
                "logs": logs[-10:] if logs else ["No new emails found"]
            })

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[EMAIL SYNC ERROR] {error_detail}")

        return JSONResponse({
            "success": False,
            "error": f"Error syncing emails: {str(e)}",
            "new_loads": 0
        })


@router.post("/receive-load")
async def receive_load_form(
        request: Request,
        db: Session = Depends(get_db)
):
    """Process receiving a load from the modal form - Uses stock_service"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    try:
        form_data = await request.form()
        load_reference = form_data.get("load_reference")

        if not load_reference:
            return RedirectResponse(
                url="/logistics/receive?error=load_required",
                status_code=303
            )

        context = get_context_data(request, db)
        receiving_branch_id = context["active_context"]

        if not receiving_branch_id:
            return RedirectResponse(
                url="/logistics/receive?error=no_branch",
                status_code=303
            )

        # Use stock_service to receive the load
        success, message = stock_service.receive_load(
            db=db,
            branch_id=str(receiving_branch_id),
            load_reference=load_reference
        )

        if success:
            # Redirect back to receive page with success message
            return RedirectResponse(
                url="/logistics/receive?success=true",
                status_code=303
            )
        else:
            # Redirect with error message
            return RedirectResponse(
                url=f"/logistics/receive?error=receive_failed&message={message[:100]}",
                status_code=303
            )

    except Exception as e:
        db.rollback()
        print(f"[RECEIVE LOAD ERROR] {str(e)}")
        return RedirectResponse(
            url="/logistics/receive?error=server_error",
            status_code=303
        )


@router.get("/vehicle-details")
async def get_vehicle_details(
        chassis_no: str,
        request: Request,
        db: Session = Depends(get_db)
):
    """Get vehicle details by chassis number"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    try:
        # Query the vehicle from VehicleMaster
        vehicle = db.query(VehicleMaster).filter(
            VehicleMaster.chassis_no == chassis_no
        ).first()

        if not vehicle:
            return JSONResponse({
                "success": False,
                "message": f"Vehicle with chassis number {chassis_no} not found"
            }, status_code=404)

        # Get branch information
        branch = db.query(Branch).filter(
            Branch.Branch_ID == vehicle.current_branch_id
        ).first()

        # Get recent transactions for this vehicle

        # Build response
        vehicle_data = {
            "success": True,
            "chassis_no": vehicle.chassis_no,
            "engine_no": vehicle.engine_no,
            "model": vehicle.model,
            "variant": vehicle.variant,
            "color": vehicle.color,
            "status": vehicle.status,
            "current_branch": branch.Branch_Name if branch else "Unknown",
            "current_branch_id": vehicle.current_branch_id,
            "load_reference_number": vehicle.load_reference_number
        }

        return JSONResponse(vehicle_data)

    except Exception as e:
        return JSONResponse({
            "success": False,
            "message": f"Error fetching vehicle details: {str(e)}"
        }, status_code=500)


@router.post("/transfer-batch")
async def transfer_batch(
        request: Request,
        db: Session = Depends(get_db)
):
    """Batch transfer with QR scanning - Uses stock_service for transfer logic"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    try:
        form_data = await request.form()
        destination_branch = form_data.get("destination_branch")
        dc_number = form_data.get("dc_number", "").strip().upper()  # Capitalize DC number
        chassis_numbers = form_data.get("chassis_numbers", "").split(",")
        chassis_numbers = [c.strip() for c in chassis_numbers if c.strip()]

        # Validate inputs
        if not destination_branch:
            return RedirectResponse(
                url="/logistics/transfer?error=destination_required",
                status_code=303
            )

        if not dc_number:
            return RedirectResponse(
                url="/logistics/transfer?error=dc_required",
                status_code=303
            )

        if not chassis_numbers:
            return RedirectResponse(
                url="/logistics/transfer?error=no_vehicles",
                status_code=303
            )

        destination_branch = int(destination_branch)

        context = get_context_data(request, db)
        from_branch_id = context["active_context"]

        if not from_branch_id:
            return RedirectResponse(
                url="/logistics/transfer?error=no_branch",
                status_code=303
            )

        # Prevent transfer to same branch
        if from_branch_id == destination_branch:
            return RedirectResponse(
                url="/logistics/transfer?error=same_branch",
                status_code=303
            )

        transfer_date = datetime.now().date()

        # Use stock_service to handle the transfer
        try:
            stock_service.log_bulk_transfer_master(
                db=db,
                from_branch_id=str(from_branch_id),
                to_branch_id=str(destination_branch),
                date_val=transfer_date,
                remarks=dc_number,  # DC number used as remarks
                chassis_list=chassis_numbers
            )

            # Success - redirect with success parameters
            return RedirectResponse(
                url=f"/logistics/transfer?success=true&count={len(chassis_numbers)}&dc={dc_number}",
                status_code=303
            )

        except Exception as transfer_error:
            # If stock_service raises an exception, show error
            print(f"[TRANSFER ERROR] {str(transfer_error)}")
            return RedirectResponse(
                url=f"/logistics/transfer?error=transfer_failed&message={str(transfer_error)[:100]}",
                status_code=303
            )

    except ValueError as e:
        return RedirectResponse(
            url="/logistics/transfer?error=invalid_data",
            status_code=303
        )
    except Exception as e:
        db.rollback()
        import traceback
        error_detail = traceback.format_exc()
        print(f"[TRANSFER BATCH ERROR] {error_detail}")

        return RedirectResponse(
            url="/logistics/transfer?error=server_error",
            status_code=303
        )
