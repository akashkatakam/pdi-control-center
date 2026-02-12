# routers/reports.py - Complete version with all reports
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct
from datetime import datetime, timedelta
import io
import csv

from database import get_db
from services import branch_service
from models import VehicleMaster, SalesRecord, InventoryTransaction, Branch
from routers.overview import get_active_context, get_context_data, check_auth

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def reports_dashboard(
        request: Request,
        from_date: str = Query(None),
        to_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """Reports Dashboard - Main landing page"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Set default date range (last 30 days)
    if not from_date:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Calculate key metrics
    metrics = calculate_key_metrics(db, branch_ids, from_dt, to_dt)

    # Get branch stats
    branch_stats = get_branch_statistics(db, branch_ids)

    # Get recent activities
    recent_activities = get_recent_activities(db, branch_ids, limit=10)

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            **context,
            "from_date": from_date,
            "to_date": to_date,
            "metrics": metrics,
            "branch_stats": branch_stats,
            "recent_activities": recent_activities,
            "current_page": "reports"
        }
    )


def calculate_key_metrics(db: Session, branch_ids: list, from_dt: datetime, to_dt: datetime):
    """Calculate key performance metrics"""

    # Total PDI completed in period
    total_pdi_completed = db.query(SalesRecord).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI Completed",
        SalesRecord.Timestamp >= from_dt.date(),
        SalesRecord.Timestamp <= to_dt.date()
    ).count()

    # Average PDI time (in hours)
    avg_pdi_time = 24  # Placeholder
    target_pdi_time = 48

    # Vehicles received in period
    vehicles_received = db.query(InventoryTransaction).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date()
    ).count()

    # Count unique loads
    loads_received = db.query(func.count(distinct(InventoryTransaction.Load_Number))).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date(),
        InventoryTransaction.Load_Number.isnot(None)
    ).scalar() or 0

    # Current stock
    current_stock = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).count()

    return {
        "total_pdi_completed": total_pdi_completed,
        "pdi_completion_change": 15,  # Placeholder
        "avg_pdi_time": avg_pdi_time,
        "target_pdi_time": target_pdi_time,
        "vehicles_received": vehicles_received,
        "loads_received": loads_received,
        "current_stock": current_stock,
        "branches_count": len(branch_ids)
    }


def get_branch_statistics(db: Session, branch_ids: list):
    """Get statistics for each branch"""

    stats = []

    for branch_id in branch_ids:
        branch = db.query(Branch).filter(Branch.Branch_ID == branch_id).first()
        if not branch:
            continue

        stock = db.query(VehicleMaster).filter(
            VehicleMaster.current_branch_id == branch_id,
            VehicleMaster.status == "In Stock"
        ).count()

        pdi_pending = db.query(SalesRecord).filter(
            SalesRecord.Branch_ID == branch_id,
            SalesRecord.fulfillment_status == "PDI Pending"
        ).count()

        pdi_in_progress = db.query(SalesRecord).filter(
            SalesRecord.Branch_ID == branch_id,
            SalesRecord.fulfillment_status == "PDI In Progress"
        ).count()

        pdi_completed = db.query(SalesRecord).filter(
            SalesRecord.Branch_ID == branch_id,
            SalesRecord.fulfillment_status == "PDI Completed"
        ).count()

        stats.append({
            "name": branch.Branch_Name,
            "stock": stock,
            "pdi_pending": pdi_pending,
            "pdi_in_progress": pdi_in_progress,
            "pdi_completed": pdi_completed,
            "avg_time": 28
        })

    return stats


def get_recent_activities(db: Session, branch_ids: list, limit: int = 10):
    """Get recent activities across branches"""

    activities = []

    # Recent PDI completions
    recent_pdi = db.query(SalesRecord, Branch).join(
        Branch, SalesRecord.Branch_ID == Branch.Branch_ID
    ).filter(
        SalesRecord.Branch_ID.in_(branch_ids),
        SalesRecord.fulfillment_status == "PDI Completed"
    ).order_by(SalesRecord.Timestamp.desc()).limit(5).all()

    for sale, branch in recent_pdi:
        activities.append({
            "icon": "✅",
            "color": "green",
            "title": "PDI Completed",
            "description": f"{sale.Customer_Name} - {sale.chassis_no}",
            "time": sale.Timestamp.strftime("%d %b, %Y"),
            "branch": branch.Branch_Name
        })

    # Recent stock receipts
    recent_receipts = db.query(InventoryTransaction, Branch).join(
        Branch, InventoryTransaction.Current_Branch_ID == Branch.Branch_ID
    ).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "INWARD"
    ).order_by(InventoryTransaction.Date.desc()).limit(5).all()

    for receipt, branch in recent_receipts:
        activities.append({
            "icon": "📦",
            "color": "blue",
            "title": "Stock Received",
            "description": f"{receipt.Model} - {receipt.Variant} ({receipt.Quantity} units)",
            "time": receipt.Date.strftime("%d %b %Y"),
            "branch": branch.Branch_Name
        })

    return activities[:limit]


# ==================== STOCK MOVEMENT REPORT ====================
@router.get("/stock-movement", response_class=HTMLResponse)
async def stock_movement_report(
        request: Request,
        from_date: str = Query(None),
        to_date: str = Query(None),
        transaction_type: str = Query("all"),
        db: Session = Depends(get_db)
):
    """Stock Movement Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    if not from_date:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Query transactions
    query = db.query(InventoryTransaction, Branch).join(
        Branch, InventoryTransaction.Current_Branch_ID == Branch.Branch_ID
    ).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date()
    )

    if transaction_type == "inward":
        query = query.filter(InventoryTransaction.Transaction_Type == "INWARD")
    elif transaction_type == "outward":
        query = query.filter(InventoryTransaction.Transaction_Type == "OUTWARD")

    transactions_data = query.order_by(InventoryTransaction.Date.desc()).all()

    # Calculate summary
    total_inward = db.query(func.sum(InventoryTransaction.Quantity)).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date()
    ).scalar() or 0

    total_outward = db.query(func.sum(InventoryTransaction.Quantity)).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "OUTWARD",
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date()
    ).scalar() or 0

    inward_loads = db.query(func.count(distinct(InventoryTransaction.Load_Number))).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date(),
        InventoryTransaction.Load_Number.isnot(None)
    ).scalar() or 0

    outward_loads = db.query(func.count(distinct(InventoryTransaction.Load_Number))).filter(
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Transaction_Type == "OUTWARD",
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date(),
        InventoryTransaction.Load_Number.isnot(None)
    ).scalar() or 0

    summary = {
        'total_inward': int(total_inward),
        'total_outward': int(total_outward),
        'net_movement': int(total_inward - total_outward),
        'inward_loads': inward_loads,
        'outward_loads': outward_loads,
        'branches_count': len(branch_ids)
    }

    # Format transactions
    transactions = []
    for txn, branch in transactions_data:
        from_branch_obj = None
        if txn.From_Branch_ID:
            from_branch_obj = db.query(Branch).filter(Branch.Branch_ID == txn.From_Branch_ID).first()

        transactions.append({
            'date': txn.Date.strftime("%d %b %Y"),
            'type': txn.Transaction_Type,
            'from_branch': from_branch_obj.Branch_Name if from_branch_obj else None,
            'to_branch': branch.Branch_Name,
            'model': txn.Model,
            'variant': txn.Variant,
            'quantity': txn.Quantity,
            'load_number': txn.Load_Number
        })

    # Daily summary
    daily_summary = []
    current_date = from_dt.date()
    max_daily = 0

    while current_date <= to_dt.date():
        inward = db.query(func.sum(InventoryTransaction.Quantity)).filter(
            InventoryTransaction.Current_Branch_ID.in_(branch_ids),
            InventoryTransaction.Transaction_Type == "INWARD",
            InventoryTransaction.Date == current_date
        ).scalar() or 0

        outward = db.query(func.sum(InventoryTransaction.Quantity)).filter(
            InventoryTransaction.Current_Branch_ID.in_(branch_ids),
            InventoryTransaction.Transaction_Type == "OUTWARD",
            InventoryTransaction.Date == current_date
        ).scalar() or 0

        max_daily = max(max_daily, int(inward), int(outward))

        daily_summary.append({
            'date': current_date.strftime("%d %b"),
            'inward': int(inward),
            'outward': int(outward),
            'inward_percent': 0,
            'outward_percent': 0
        })

        current_date += timedelta(days=1)

    # Calculate percentages
    for day in daily_summary:
        if max_daily > 0:
            day['inward_percent'] = round((day['inward'] / max_daily) * 100)
            day['outward_percent'] = round((day['outward'] / max_daily) * 100)

    return templates.TemplateResponse(
        "reports_stock_movement.html",
        {
            "request": request,
            **context,
            "from_date": from_date,
            "to_date": to_date,
            "transaction_type": transaction_type,
            "summary": summary,
            "transactions": transactions,
            "daily_summary": daily_summary[-14:],  # Last 14 days
            "current_page": "reports"
        }
    )


# ==================== MODEL-WISE REPORT ====================
@router.get("/model-wise", response_class=HTMLResponse)
async def model_wise_report(
        request: Request,
        model: str = Query("all"),
        db: Session = Depends(get_db)
):
    """Model-wise Inventory Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get all available models
    available_models = db.query(distinct(VehicleMaster.model)).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).order_by(VehicleMaster.model).all()
    available_models = [m[0] for m in available_models if m[0]]

    # Query for models
    if model == "all":
        model_list = available_models
    else:
        model_list = [model]

    total_stock = db.query(VehicleMaster).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).count()

    models = []
    for model_name in model_list:
        model_vehicles = db.query(VehicleMaster).filter(
            VehicleMaster.model == model_name,
            VehicleMaster.current_branch_id.in_(branch_ids),
            VehicleMaster.status == "In Stock"
        ).all()

        if not model_vehicles:
            continue

        total_units = len(model_vehicles)
        percentage = round((total_units / total_stock * 100) if total_stock > 0 else 0, 1)

        # Get variants
        variant_counts = {}
        color_counts = {}

        for v in model_vehicles:
            variant_counts[v.variant] = variant_counts.get(v.variant, 0) + 1
            color_counts[v.color] = color_counts.get(v.color, 0) + 1

        variants = []
        for variant_name, count in sorted(variant_counts.items(), key=lambda x: x[1], reverse=True):
            variant_percentage = round((count / total_units * 100), 1)

            # Branch-wise for this variant
            branches = []
            for branch_id in branch_ids:
                branch = db.query(Branch).filter(Branch.Branch_ID == branch_id).first()
                if not branch:
                    continue

                branch_count = db.query(VehicleMaster).filter(
                    VehicleMaster.model == model_name,
                    VehicleMaster.variant == variant_name,
                    VehicleMaster.current_branch_id == branch_id,
                    VehicleMaster.status == "In Stock"
                ).count()

                if branch_count > 0:
                    branches.append({
                        'name': branch.Branch_Name,
                        'count': branch_count
                    })

            variants.append({
                'name': variant_name,
                'units': count,
                'percentage': variant_percentage,
                'branches': branches
            })

        # Colors
        colors = []
        for color_name, count in sorted(color_counts.items(), key=lambda x: x[1], reverse=True):
            color_percentage = round((count / total_units * 100), 1)
            colors.append({
                'name': color_name,
                'count': count,
                'percentage': color_percentage
            })

        # Vehicle details with age
        vehicles = []
        for v in model_vehicles[:50]:  # Limit to 50 for performance
            branch = db.query(Branch).filter(Branch.Branch_ID == v.current_branch_id).first()
            age_days = (datetime.now().date() - v.date_received.date()).days if v.date_received else 0

            vehicles.append({
                'chassis_no': v.chassis_no,
                'variant': v.variant,
                'color': v.color,
                'branch': branch.Branch_Name if branch else 'Unknown',
                'status': v.status,
                'age_days': age_days
            })

        models.append({
            'name': model_name,
            'total_units': total_units,
            'percentage': percentage,
            'variants': variants,
            'colors': colors,
            'vehicles': vehicles
        })

    return templates.TemplateResponse(
        "reports_model_wise.html",
        {
            "request": request,
            **context,
            "selected_model": model,
            "available_models": available_models,
            "models": models,
            "current_page": "reports"
        }
    )


# ==================== AGING INVENTORY REPORT ====================
@router.get("/aging-inventory", response_class=HTMLResponse)
async def aging_inventory_report(
        request: Request,
        db: Session = Depends(get_db)
):
    """Aging Inventory Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get all stock vehicles with age
    vehicles = db.query(VehicleMaster, Branch).join(
        Branch, VehicleMaster.current_branch_id == Branch.Branch_ID
    ).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    ).all()

    # Age buckets
    age_buckets = {
        'days_0_30': 0,
        'days_31_60': 0,
        'days_61_90': 0,
        'days_91_120': 0,
        'days_120_plus': 0
    }

    all_stock = []
    critical_stock = []
    model_age_data = {}

    for vehicle, branch in vehicles:
        age_days = (datetime.now().date() - vehicle.date_received.date()).days if vehicle.date_received else 0

        # Categorize
        if age_days <= 30:
            age_buckets['days_0_30'] += 1
        elif age_days <= 60:
            age_buckets['days_31_60'] += 1
        elif age_days <= 90:
            age_buckets['days_61_90'] += 1
        elif age_days <= 120:
            age_buckets['days_91_120'] += 1
        else:
            age_buckets['days_120_plus'] += 1
            critical_stock.append({
                'chassis_no': vehicle.chassis_no,
                'model': vehicle.model,
                'variant': vehicle.variant,
                'color': vehicle.color,
                'branch': branch.Branch_Name,
                'age_days': age_days
            })

        all_stock.append({
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color,
            'branch': branch.Branch_Name,
            'age_days': age_days
        })

        # Track model ages
        if vehicle.model not in model_age_data:
            model_age_data[vehicle.model] = {'total_age': 0, 'count': 0}
        model_age_data[vehicle.model]['total_age'] += age_days
        model_age_data[vehicle.model]['count'] += 1

    # Calculate average age by model
    model_ages = []
    for model_name, data in model_age_data.items():
        avg_age = round(data['total_age'] / data['count']) if data['count'] > 0 else 0
        model_ages.append({
            'name': model_name,
            'avg_age': avg_age,
            'count': data['count']
        })

    model_ages.sort(key=lambda x: x['avg_age'], reverse=True)

    return templates.TemplateResponse(
        "reports_aging_inventory.html",
        {
            "request": request,
            **context,
            "age_buckets": age_buckets,
            "model_ages": model_ages,
            "critical_stock": sorted(critical_stock, key=lambda x: x['age_days'], reverse=True),
            "all_stock": sorted(all_stock, key=lambda x: x['age_days'], reverse=True),
            "current_page": "reports"
        }
    )


# ==================== TRANSFER REPORT ====================
@router.get("/transfers", response_class=HTMLResponse)
async def transfers_report(
        request: Request,
        from_date: str = Query(None),
        to_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """Transfer Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    if not from_date:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get outward transactions (transfers)
    transfers_data = db.query(InventoryTransaction).filter(
        InventoryTransaction.Transaction_Type == "OUTWARD",
        InventoryTransaction.From_Branch_ID.in_(branch_ids),
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date()
    ).order_by(InventoryTransaction.Date.desc()).all()

    # Group by load number
    load_groups = {}
    for txn in transfers_data:
        if not txn.Load_Number:
            continue

        if txn.Load_Number not in load_groups:
            load_groups[txn.Load_Number] = {
                'load_number': txn.Load_Number,
                'date': txn.Date,
                'from_branch_id': txn.From_Branch_ID,
                'to_branch_id': txn.To_Branch_ID,
                'vehicle_count': 0
            }
        load_groups[txn.Load_Number]['vehicle_count'] += txn.Quantity

    # Format transfers
    transfers = []
    for load_data in load_groups.values():
        from_branch = db.query(Branch).filter(Branch.Branch_ID == load_data['from_branch_id']).first()
        to_branch = db.query(Branch).filter(Branch.Branch_ID == load_data['to_branch_id']).first()

        # Check if received
        received_vehicles = db.query(VehicleMaster).filter(
            VehicleMaster.load_reference_number == load_data['load_number'],
            VehicleMaster.status == "In Stock"
        ).count()

        status = "Received" if received_vehicles >= load_data['vehicle_count'] else "In Transit"

        transfers.append({
            'date': load_data['date'].strftime("%d %b %Y"),
            'load_number': load_data['load_number'],
            'from_branch': from_branch.Branch_Name if from_branch else 'Unknown',
            'to_branch': to_branch.Branch_Name if to_branch else 'Unknown',
            'vehicle_count': load_data['vehicle_count'],
            'status': status
        })

    # Summary
    total_transfers = len(load_groups)
    vehicles_moved = sum(t['vehicle_count'] for t in transfers)
    in_transit = sum(1 for t in transfers if t['status'] == "In Transit")

    summary = {
        'total_transfers': total_transfers,
        'vehicles_moved': vehicles_moved,
        'in_transit': in_transit,
        'avg_transit_time': 3  # Placeholder
    }

    # Transfer flows
    transfer_flows = []
    flow_map = {}

    for txn in transfers_data:
        if not txn.From_Branch_ID or not txn.To_Branch_ID:
            continue

        key = f"{txn.From_Branch_ID}-{txn.To_Branch_ID}"
        if key not in flow_map:
            from_branch = db.query(Branch).filter(Branch.Branch_ID == txn.From_Branch_ID).first()
            to_branch = db.query(Branch).filter(Branch.Branch_ID == txn.To_Branch_ID).first()

            flow_map[key] = {
                'from_branch': from_branch.Branch_Name if from_branch else 'Unknown',
                'to_branch': to_branch.Branch_Name if to_branch else 'Unknown',
                'count': 0
            }
        flow_map[key]['count'] += txn.Quantity

    transfer_flows = sorted(flow_map.values(), key=lambda x: x['count'], reverse=True)[:10]

    return templates.TemplateResponse(
        "reports_transfers.html",
        {
            "request": request,
            **context,
            "from_date": from_date,
            "to_date": to_date,
            "summary": summary,
            "transfers": transfers,
            "transfer_flows": transfer_flows,
            "current_page": "reports"
        }
    )


# ==================== RECEIVING REPORT ====================
@router.get("/receiving", response_class=HTMLResponse)
async def receiving_report(
        request: Request,
        from_date: str = Query(None),
        to_date: str = Query(None),
        source: str = Query("all"),
        db: Session = Depends(get_db)
):
    """Receiving Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    if not from_date:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get inward transactions
    query = db.query(InventoryTransaction).filter(
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Current_Branch_ID.in_(branch_ids),
        InventoryTransaction.Date >= from_dt.date(),
        InventoryTransaction.Date <= to_dt.date()
    )

    # Get all sources
    sources = db.query(distinct(InventoryTransaction.Remarks)).filter(
        InventoryTransaction.Transaction_Type == "INWARD",
        InventoryTransaction.Current_Branch_ID.in_(branch_ids)
    ).all()
    sources = [s[0] for s in sources if s[0]]

    if source != "all":
        query = query.filter(InventoryTransaction.Remarks.contains(source))

    receipts_data = query.order_by(InventoryTransaction.Date.desc()).all()

    # Summary
    total_received = sum(r.Quantity for r in receipts_data)
    loads_received = len(set(r.Load_Number for r in receipts_data if r.Load_Number))

    today = datetime.now().date()
    today_received = sum(r.Quantity for r in receipts_data if r.Date == today)

    week_start = today - timedelta(days=today.weekday())
    week_received = sum(r.Quantity for r in receipts_data if r.Date >= week_start)

    summary = {
        'total_received': total_received,
        'loads_received': loads_received,
        'today_received': today_received,
        'week_received': week_received
    }

    # Daily trend
    daily_data = {}
    for receipt in receipts_data:
        date_str = receipt.Date.strftime("%d %b")
        if date_str not in daily_data:
            daily_data[date_str] = {'count': 0, 'loads': set()}
        daily_data[date_str]['count'] += receipt.Quantity
        if receipt.Load_Number:
            daily_data[date_str]['loads'].add(receipt.Load_Number)

    max_count = max([d['count'] for d in daily_data.values()]) if daily_data else 1

    daily_trend = []
    for date_str, data in list(daily_data.items())[-14:]:  # Last 14 days
        daily_trend.append({
            'date': date_str,
            'count': data['count'],
            'loads': len(data['loads']),
            'percentage': round((data['count'] / max_count * 100))
        })

    # Source breakdown
    source_data = {}
    for receipt in receipts_data:
        src = receipt.Remarks or 'Unknown'
        if src not in source_data:
            source_data[src] = {'vehicles': 0, 'loads': set()}
        source_data[src]['vehicles'] += receipt.Quantity
        if receipt.Load_Number:
            source_data[src]['loads'].add(receipt.Load_Number)

    source_breakdown = []
    for src, data in source_data.items():
        percentage = round((data['vehicles'] / total_received * 100) if total_received > 0 else 0, 1)
        source_breakdown.append({
            'name': src,
            'vehicles': data['vehicles'],
            'loads': len(data['loads']),
            'percentage': percentage
        })

    source_breakdown.sort(key=lambda x: x['vehicles'], reverse=True)

    # Model breakdown
    model_data = {}
    for receipt in receipts_data:
        model = receipt.Model
        if model not in model_data:
            model_data[model] = {'count': 0, 'variants': {}, 'colors': {}}
        model_data[model]['count'] += receipt.Quantity

        variant = receipt.Variant
        if variant:
            model_data[model]['variants'][variant] = model_data[model]['variants'].get(variant, 0) + receipt.Quantity

        color = receipt.Color
        if color:
            model_data[model]['colors'][color] = model_data[model]['colors'].get(color, 0) + receipt.Quantity

    model_breakdown = []
    for model_name, data in model_data.items():
        top_variant = max(data['variants'].items(), key=lambda x: x[1])[0] if data['variants'] else 'N/A'
        top_color = max(data['colors'].items(), key=lambda x: x[1])[0] if data['colors'] else 'N/A'
        percentage = round((data['count'] / total_received * 100) if total_received > 0 else 0, 1)

        model_breakdown.append({
            'name': model_name,
            'count': data['count'],
            'percentage': percentage,
            'top_variant': top_variant,
            'top_color': top_color
        })

    model_breakdown.sort(key=lambda x: x['count'], reverse=True)

    # Receipt details
    receipts = []
    for receipt in receipts_data[:100]:  # Limit to 100
        # Try to get chassis from vehicles with this load
        chassis_no = 'N/A'
        if receipt.Load_Number:
            vehicle = db.query(VehicleMaster).filter(
                VehicleMaster.load_reference_number == receipt.Load_Number
            ).first()
            if vehicle:
                chassis_no = vehicle.chassis_no

        receipts.append({
            'date': receipt.Date.strftime("%d %b %Y"),
            'load_number': receipt.Load_Number or 'N/A',
            'source': receipt.Remarks or 'Unknown',
            'chassis_no': chassis_no,
            'model': receipt.Model,
            'variant': receipt.Variant,
            'color': receipt.Color,
            'received_by': None  # Placeholder
        })

    return templates.TemplateResponse(
        "reports_receiving.html",
        {
            "request": request,
            **context,
            "from_date": from_date,
            "to_date": to_date,
            "source": source,
            "sources": sources,
            "summary": summary,
            "daily_trend": daily_trend,
            "source_breakdown": source_breakdown,
            "model_breakdown": model_breakdown,
            "receipts": receipts,
            "current_page": "reports"
        }
    )


# ==================== IN-TRANSIT VEHICLES REPORT ====================
@router.get("/in-transit", response_class=HTMLResponse)
async def in_transit_report(
        request: Request,
        db: Session = Depends(get_db)
):
    """In-Transit Vehicles Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)

    # Get all in-transit vehicles
    vehicles = db.query(VehicleMaster).filter(
        VehicleMaster.status == "In Transit"
    ).all()

    # Group by load
    load_groups = {}
    for vehicle in vehicles:
        load_num = vehicle.load_reference_number or 'UNKNOWN'
        if load_num not in load_groups:
            load_groups[load_num] = {
                'load_number': load_num,
                'destination': 'Unknown',  # Would need additional field
                'vehicle_count': 0,
                'vehicles': [],
                'sent_date': vehicle.date_received.strftime("%d %b %Y") if vehicle.date_received else 'Unknown',
                'days_in_transit': (datetime.now() - vehicle.date_received).days if vehicle.date_received else 0
            }

        load_groups[load_num]['vehicle_count'] += 1
        load_groups[load_num]['vehicles'].append({
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color
        })

    # Calculate is_delayed
    for load_data in load_groups.values():
        load_data['is_delayed'] = load_data['days_in_transit'] > 7

    loads = sorted(load_groups.values(), key=lambda x: x['days_in_transit'], reverse=True)

    # Summary
    total_in_transit = len(vehicles)
    active_loads = len(load_groups)
    on_time = sum(1 for l in loads if not l['is_delayed'])
    delayed = sum(1 for l in loads if l['is_delayed'])

    summary = {
        'total_in_transit': total_in_transit,
        'active_loads': active_loads,
        'on_time': on_time,
        'delayed': delayed
    }

    # All vehicles
    all_vehicles = []
    for vehicle in vehicles:
        all_vehicles.append({
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'from_branch': vehicle.current_branch_id or 'Unknown',
            'to_branch': 'Unknown',
            'load_number': vehicle.load_reference_number or 'N/A',
            'sent_date': vehicle.date_received.strftime("%d %b") if vehicle.date_received else 'N/A',
            'days_in_transit': (datetime.now() - vehicle.date_received).days if vehicle.date_received else 0
        })

    return templates.TemplateResponse(
        "reports_in_transit.html",
        {
            "request": request,
            **context,
            "summary": summary,
            "loads": loads,
            "all_vehicles": all_vehicles,
            "current_page": "reports"
        }
    )


# ==================== LOAD TRACKING REPORT ====================
@router.get("/load-tracking", response_class=HTMLResponse)
async def load_tracking_report(
        request: Request,
        load_number: str = Query(None),
        db: Session = Depends(get_db)
):
    """Load Tracking Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)

    load_data = None

    if load_number:
        # Get vehicles for this load
        vehicles = db.query(VehicleMaster).filter(
            VehicleMaster.load_reference_number == load_number
        ).all()

        if vehicles:
            first_vehicle = vehicles[0]

            # Determine status
            all_received = all(v.status == "In Stock" for v in vehicles)
            status = "Delivered" if all_received else "In Transit"

            # Build timeline
            timeline = [
                {
                    'title': 'Load Created',
                    'description': f'Load {load_number} created with {len(vehicles)} vehicles',
                    'timestamp': first_vehicle.date_received.strftime(
                        "%d %b %Y, %I:%M %p") if first_vehicle.date_received else None,
                    'location': first_vehicle.current_branch_id,
                    'completed': True
                },
                {
                    'title': 'In Transit',
                    'description': 'Vehicles are being transported',
                    'timestamp': None,
                    'location': None,
                    'completed': True
                },
                {
                    'title': 'Delivery',
                    'description': 'Vehicles delivered to destination',
                    'timestamp': None,
                    'location': None,
                    'completed': all_received
                }
            ]

            load_data = {
                'load_number': load_number,
                'from_branch': first_vehicle.current_branch_id or 'Unknown',
                'to_branch': 'Destination',  # Would need additional field
                'sent_date': first_vehicle.date_received.strftime("%d %b %Y") if first_vehicle.date_received else 'Unknown',
                'vehicle_count': len(vehicles),
                'status': status,
                'timeline': timeline,
                'vehicles': [{
                    'chassis_no': v.chassis_no,
                    'model': v.model,
                    'variant': v.variant,
                    'color': v.color,
                    'status': v.status
                } for v in vehicles]
            }

    # Recent loads
    recent_vehicles = db.query(VehicleMaster).filter(
        VehicleMaster.load_reference_number.isnot(None)
    ).order_by(VehicleMaster.date_received.desc()).limit(100).all()

    recent_load_map = {}
    for v in recent_vehicles:
        load_num = v.load_reference_number
        if load_num not in recent_load_map:
            recent_load_map[load_num] = {
                'load_number': load_num,
                'from_branch': v.current_branch_id or 'Unknown',
                'to_branch': 'Destination',
                'vehicle_count': 0,
                'date': v.date_received.strftime("%d %b %Y") if v.date_received else 'Unknown',
                'status': 'In Transit'
            }
        recent_load_map[load_num]['vehicle_count'] += 1

    recent_loads = list(recent_load_map.values())[:10]

    return templates.TemplateResponse(
        "reports_load_tracking.html",
        {
            "request": request,
            **context,
            "load_number": load_number,
            "load_data": load_data,
            "recent_loads": recent_loads,
            "current_page": "reports"
        }
    )


@router.get("/export")
async def export_report(
        request: Request,
        format: str = Query("csv"),
        from_date: str = Query(None),
        to_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """Export reports in various formats"""

    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    active_branch_id = get_active_context(request, db)
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Get branch stats
    branch_stats = get_branch_statistics(db, branch_ids)

    if format == "csv":
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(['Branch', 'Stock', 'PDI Pending', 'PDI In Progress', 'PDI Completed', 'Avg Time'])
        for stat in branch_stats:
            writer.writerow([
                stat['name'],
                stat['stock'],
                stat['pdi_pending'],
                stat['pdi_in_progress'],
                stat['pdi_completed'],
                f"{stat['avg_time']}h"
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=branch_report_{datetime.now().strftime('%Y%m%d')}.csv"}
        )

    return JSONResponse({"error": "Format not supported yet"}, status_code=400)
