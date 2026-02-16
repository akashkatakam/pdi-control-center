# routers/logistics.py - Clean Receive and Transfer functionality with caching
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import time

import models
from database import get_db
from models import VehicleMaster, Branch, InventoryTransaction
from services import branch_service, email_service, stock_service
from routers.overview import get_active_context, get_context_data, check_auth

router = APIRouter(prefix="/logistics", tags=["logistics"])
templates = Jinja2Templates(directory="templates")

# Cache for available vehicles
_vehicle_cache = {}
_vehicle_details_cache = {}
_cache_timestamp = {}
CACHE_TTL = 300  # 5 minutes cache


def get_cached_available_vehicles(db: Session, branch_ids: list) -> list:
    """Get available vehicles with caching"""
    cache_key = ",".join(sorted(branch_ids))
    current_time = time.time()

    # Check if cache exists and is still valid
    if cache_key in _vehicle_cache and cache_key in _cache_timestamp:
        if current_time - _cache_timestamp[cache_key] < CACHE_TTL:
            return _vehicle_cache[cache_key]

    # Fetch fresh data
    available_vehicles_query = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).all()

    # Convert to serializable dictionaries with branch info
    available_vehicles = []
    for vehicle in available_vehicles_query:
        branch = db.query(Branch).filter(Branch.Branch_ID == vehicle.current_branch_id).first()
        available_vehicles.append({
            'chassis_no': vehicle.chassis_no,
            'engine_no': vehicle.engine_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color,
            'status': vehicle.status,
            'current_branch_id': vehicle.current_branch_id,
            'current_branch': {
                'Branch_ID': branch.Branch_ID,
                'Branch_Name': branch.Branch_Name
            } if branch else None
        })

    # Update cache
    _vehicle_cache[cache_key] = available_vehicles
    _cache_timestamp[cache_key] = current_time

    return available_vehicles


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
                "source_branch": "HMSI",
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
            return RedirectResponse(
                url="/logistics/receive?success=true",
                status_code=303
            )
        else:
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
        dc_number = form_data.get("dc_number", "").strip().upper()
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
                remarks=dc_number,
                chassis_list=chassis_numbers
            )

            # Success - redirect with success parameters
            return RedirectResponse(
                url=f"/logistics/transfer?success=true&count={len(chassis_numbers)}&dc={dc_number}",
                status_code=303
            )

        except Exception as transfer_error:
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

    # Get all managed branches (head branch + sub-branches)
    managed_branches = branch_service.get_managed_branches(db, str(active_branch_id))
    managed_branch_ids = [branch.Branch_ID for branch in managed_branches if branch.Branch_ID != active_branch_id]


    # Get cached available vehicles
    available_vehicles = get_cached_available_vehicles(db, managed_branch_ids)

    # Recent manual sales from ALL managed branches
    recent_sales = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID.in_(managed_branch_ids),
        InventoryTransaction.Transaction_Type == "SALE"
    ).order_by(InventoryTransaction.Date.desc()).limit(10).all()

    # Get branch names for display in recent sales
    branch_map = {branch.Branch_ID: branch.Branch_Name for branch in managed_branches}

    # Enhance recent sales with branch names
    recent_sales_with_branches = []
    for sale in recent_sales:
        recent_sales_with_branches.append({
            'date': sale.Date,
            'model': sale.Model,
            'variant': sale.Variant,
            'color': sale.Color,
            'quantity': sale.Quantity,
            'remarks': sale.Remarks,
            'branch_name': branch_map.get(sale.Current_Branch_ID, 'Unknown')
        })

    return templates.TemplateResponse(
        "logistics_manual_sale.html",
        {
            "request": request,
            **context,
            "available_vehicles": available_vehicles,
            "recent_sales": recent_sales_with_branches,
            "managed_branches": managed_branches,
            "current_page": "logistics",
            "datetime": datetime
        }
    )


@router.post("/manual-sale/create")
async def create_manual_sale(
        request: Request,
        db: Session = Depends(get_db)
):
    """Process manual sale from sub-branches"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    try:
        form_data = await request.form()
        chassis_numbers = form_data.get("chassis_numbers", "").split(",")
        chassis_numbers = [c.strip() for c in chassis_numbers if c.strip()]

        sale_date_str = form_data.get("sale_date")
        remarks = form_data.get("remarks", "Manual Sale - Sub Branch")

        if not chassis_numbers:
            return RedirectResponse(
                url="/logistics/manual-sale?error=no_vehicles",
                status_code=303
            )

        context = get_context_data(request, db)
        active_branch_id = context["active_context"]

        # Validate that all chassis numbers belong to managed branches
        managed_branches = branch_service.get_managed_branches(db, str(active_branch_id))
        managed_branch_ids = [branch.Branch_ID for branch in managed_branches]

        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d").date() if sale_date_str else datetime.now().date()

        # Validate all chassis numbers first
        for chassis_no in chassis_numbers:
            vehicle = db.query(VehicleMaster).filter(
                VehicleMaster.chassis_no == chassis_no,
                VehicleMaster.status == "In Stock"
            ).first()

            if not vehicle:
                return RedirectResponse(
                    url=f"/logistics/manual-sale?error=vehicle_not_found&chassis={chassis_no}",
                    status_code=303
                )

            # Check if vehicle belongs to a managed branch
            if vehicle.current_branch_id not in managed_branch_ids:
                branch = db.query(Branch).filter(Branch.Branch_ID == vehicle.current_branch_id).first()
                branch_name = branch.Branch_Name if branch else vehicle.current_branch_id
                return RedirectResponse(
                    url=f"/logistics/manual-sale?error=unmanaged_branch&chassis={chassis_no}&branch={branch_name}",
                    status_code=303
                )

        # Use stock_service to process the sales
        try:
            success, message = stock_service.log_bulk_manual_sub_branch_sale(
                db=db,
                chassis_list=chassis_numbers,
                sale_date=sale_date,
                remarks=remarks
            )

            if success:
                return RedirectResponse(
                    url=f"/logistics/manual-sale?success=true&count={len(chassis_numbers)}",
                    status_code=303
                )
            else:
                return RedirectResponse(
                    url=f"/logistics/manual-sale?error=sale_failed&message={message[:100]}",
                    status_code=303
                )

        except Exception as sale_error:
            return RedirectResponse(
                url=f"/logistics/manual-sale?error=sale_failed&message={str(sale_error)[:100]}",
                status_code=303
            )

    except Exception as e:
        db.rollback()
        import traceback
        error_detail = traceback.format_exc()
        print(f"[MANUAL SALE ERROR] {error_detail}")

        return RedirectResponse(
            url="/logistics/manual-sale?error=server_error",
            status_code=303
        )


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
            "1": {
                'name': 'Khammam',
                'host': 'imap.gmail.com',
                'user': 'katkammotors@gmail.com',
                'password': 'prkv wpwl wohd fmzp',
                'sender_filter': 'katkamhonda@rediffmail.com'
            },
            "3": {
                'name': 'Kothagudem',
                'host': 'imap.gmail.com',
                'user': 'saikatakamhonda@gmail.com',
                'password': 'aqff aows ptuv wdob',
                'sender_filter': 'sap.admin@honda2wheelersindia.com'
            }
        }

        email_config = email_configs.get(active_branch_id)

        if not email_config:
            return JSONResponse({
                "success": False,
                "error": f"Email sync is not configured for this branch (ID: {active_branch_id})",
                "new_loads": 0
            })

        color_map = {}

        vehicle_data_list, logs = email_service.fetch_and_process_emails(
            db=db,
            branch_id=str(active_branch_id),
            email_config=email_config,
            color_map=color_map
        )

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
                "new_loads": total_loads,
                "vehicles_count": total_vehicles,
                "branch_name": email_config['name'],
                "logs": logs[-10:]
            })
        else:
            return JSONResponse({
                "success": True,
                "message": f"No new emails found for {email_config['name']}",
                "new_loads": 0,
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


_vehicle_details_cache = {}

@router.get("/vehicle-details")
async def get_vehicle_details(
        chassis_no: str,
        request: Request,
        db: Session = Depends(get_db)
):
    """Get vehicle details by chassis number"""

    if not check_auth(request):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)

    # Check cache first
    if chassis_no in _vehicle_details_cache:
        cache_time = _vehicle_details_cache[chassis_no].get('_cached_at', 0)
        if time.time() - cache_time < 300:  # 5 minute cache
            return JSONResponse(_vehicle_details_cache[chassis_no])

    try:
        vehicle = db.query(VehicleMaster).filter(
            VehicleMaster.chassis_no == chassis_no
        ).first()

        if not vehicle:
            return JSONResponse({
                "success": False,
                "message": f"Vehicle with chassis number {chassis_no} not found"
            }, status_code=404)

        branch = db.query(Branch).filter(
            Branch.Branch_ID == vehicle.current_branch_id
        ).first()

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
            "load_reference_number": vehicle.load_reference_number,
            "_cached_at": time.time()
        }

        # Cache the result
        _vehicle_details_cache[chassis_no] = vehicle_data

        return JSONResponse(vehicle_data)

    except Exception as e:
        return JSONResponse({
            "success": False,
            "message": f"Error fetching vehicle details: {str(e)}"
        }, status_code=500)

