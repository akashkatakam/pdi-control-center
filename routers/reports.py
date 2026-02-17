# routers/reports.py - Complete version with all reports
import pandas as pd
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct,or_
from datetime import datetime, timedelta
import io
import csv

from database import get_db
from services import branch_service, report_service
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


# ==================== STOCK MOVEMENT REPORT (REDESIGNED) ====================
@router.get("/stock-movement", response_class=HTMLResponse)
async def stock_movement_report(
        request: Request,
        from_date: str = Query(None),
        to_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """Stock Movement Report - Branch Transfer Summary"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    if not from_date:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").date()

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # ===== SINGLE DB CALL: Fetch all transactions =====
    query = db.query(
        InventoryTransaction.Date,
        InventoryTransaction.Transaction_Type,
        InventoryTransaction.Current_Branch_ID,
        InventoryTransaction.From_Branch_ID,
        InventoryTransaction.To_Branch_ID,
        InventoryTransaction.Model,
        InventoryTransaction.Variant,
        InventoryTransaction.Color,
        InventoryTransaction.Quantity,
        InventoryTransaction.Load_Number
    ).filter(
        InventoryTransaction.Date >= from_dt,
        InventoryTransaction.Date <= to_dt,
        or_(
            InventoryTransaction.Current_Branch_ID.in_(branch_ids),
            InventoryTransaction.From_Branch_ID.in_(branch_ids),
            InventoryTransaction.To_Branch_ID.in_(branch_ids)
        )
    )

    df = pd.read_sql(query.statement, db.get_bind())

    if df.empty:
        return templates.TemplateResponse(
            "reports_stock_movement.html",
            {
                "request": request,
                **context,
                "from_date": from_date,
                "to_date": to_date,
                "summary": {'total_sent': 0, 'total_received': 0, 'unique_branches': 0, 'unique_models': 0},
                "branch_transfers": [],
                "model_transfers": [],
                "transfer_matrix": [],
                "current_page": "reports"
            }
        )

    # Get all branches (including external ones)
    all_branch_ids = set(df['Current_Branch_ID'].dropna()) | set(df['From_Branch_ID'].dropna()) | set(
        df['To_Branch_ID'].dropna())
    all_branches = db.query(Branch).filter(Branch.Branch_ID.in_(all_branch_ids)).all()
    branch_map = {b.Branch_ID: b.Branch_Name for b in all_branches}

    # Add branch names
    df['Current_Branch_Name'] = df['Current_Branch_ID'].map(branch_map)
    df['From_Branch_Name'] = df['From_Branch_ID'].map(branch_map)
    df['To_Branch_Name'] = df['To_Branch_ID'].map(branch_map)

    # Separate inward and outward
    outward_df = df[df['Transaction_Type'] == 'OUTWARD'].copy()
    inward_df = df[df['Transaction_Type'] == 'INWARD'].copy()

    # ===== SUMMARY METRICS =====
    summary = {
        'total_sent': int(outward_df['Quantity'].sum()) if not outward_df.empty else 0,
        'total_received': int(inward_df['Quantity'].sum()) if not inward_df.empty else 0,
        'unique_branches': len(all_branch_ids),
        'unique_models': df['Model'].nunique()
    }

    # ===== BRANCH-TO-BRANCH TRANSFER SUMMARY =====
    branch_transfers = []

    if not outward_df.empty:
        # For OUTWARD transactions:
        # - Source = Current_Branch_ID (where the transfer originates)
        # - Destination = To_Branch_ID (where it's going)

        # Use Current_Branch as the "From" for outward transactions
        outward_df['Source_Branch'] = outward_df['Current_Branch_Name']
        outward_df['Dest_Branch'] = outward_df['To_Branch_Name']

        # Group by Source → Destination
        transfer_summary = outward_df.groupby(['Source_Branch', 'Dest_Branch']).agg({
            'Quantity': 'sum',
            'Load_Number': 'nunique',
            'Model': lambda x: x.value_counts().to_dict()
        }).reset_index()

        for _, row in transfer_summary.iterrows():
            source_branch = row['Source_Branch']
            dest_branch = row['Dest_Branch']

            # Skip if both are NaN
            if pd.isna(source_branch) and pd.isna(dest_branch):
                continue

            total_qty = int(row['Quantity'])
            loads = int(row['Load_Number'])
            model_breakdown = row['Model']

            # Format model breakdown
            models_list = [
                {'model': k, 'qty': int(v)}
                for k, v in sorted(model_breakdown.items(), key=lambda x: x[1], reverse=True)
            ]

            branch_transfers.append({
                'from_branch': source_branch if pd.notna(source_branch) else 'Unknown',
                'to_branch': dest_branch if pd.notna(dest_branch) else 'Unknown',
                'total_quantity': total_qty,
                'loads': loads,
                'models': models_list
            })

        # Sort by quantity descending
        branch_transfers = sorted(branch_transfers, key=lambda x: x['total_quantity'], reverse=True)

    # ===== MODEL-WISE TRANSFER SUMMARY =====
    model_transfers = []

    if not outward_df.empty:
        # Group by Model and aggregate destinations
        model_summary = outward_df.groupby('Model').agg({
            'Quantity': 'sum',
            'To_Branch_Name': lambda x: x.value_counts().to_dict(),
            'Variant': lambda x: x.value_counts().to_dict()
        }).reset_index()

        for _, row in model_summary.iterrows():
            model = row['Model']
            total_qty = int(row['Quantity'])
            destinations = row['To_Branch_Name']
            variants = row['Variant']

            # Top destinations
            top_destinations = [
                {'branch': k, 'qty': int(v)}
                for k, v in sorted(destinations.items(), key=lambda x: x[1], reverse=True)[:3]
            ]

            # Variant breakdown
            variant_list = [
                {'variant': k, 'qty': int(v)}
                for k, v in sorted(variants.items(), key=lambda x: x[1], reverse=True)
            ]

            model_transfers.append({
                'model': model,
                'total_quantity': total_qty,
                'destinations': top_destinations,
                'variants': variant_list
            })

        # Sort by quantity descending
        model_transfers = sorted(model_transfers, key=lambda x: x['total_quantity'], reverse=True)

    # ===== TRANSFER MATRIX (Source x Destination) =====
    transfer_matrix = []

    if not outward_df.empty:
        # Create pivot table: From Branch (rows) x To Branch (columns)
        pivot = outward_df.pivot_table(
            values='Quantity',
            index='From_Branch_Name',
            columns='To_Branch_Name',
            aggfunc='sum',
            fill_value=0
        )

        for from_branch in pivot.index:
            row_data = {
                'from_branch': from_branch if pd.notna(from_branch) else 'External',
                'destinations': []
            }

            for to_branch in pivot.columns:
                qty = int(pivot.loc[from_branch, to_branch])
                if qty > 0:
                    row_data['destinations'].append({
                        'branch': to_branch if pd.notna(to_branch) else 'External',
                        'quantity': qty
                    })

            if row_data['destinations']:
                transfer_matrix.append(row_data)

    return templates.TemplateResponse(
        "reports_stock_movement.html",
        {
            "request": request,
            **context,
            "from_date": from_date,
            "to_date": to_date,
            "summary": summary,
            "branch_transfers": branch_transfers,
            "model_transfers": model_transfers,
            "transfer_matrix": transfer_matrix,
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


@router.get("/daily-sales-transfers", response_class=HTMLResponse)
async def daily_sales_transfers(
        request: Request,
        start_date: str = Query(None),
        end_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """Daily Sales and Transfers Report"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Default date range: last 7 days
    if not start_date or not end_date:
        end_d = datetime.now().date()
        start_d = end_d - timedelta(days=7)
    else:
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()

    print(f"\n{'=' * 60}")
    print(f"[REPORT] Date Range: {start_d} to {end_d}")
    print(f"[REPORT] Active Branch ID: {active_branch_id}")

    # Get head branches
    head_branches = branch_service.get_head_branches(db)

    # Build head_map
    head_map = {}
    active_branch_obj = db.query(Branch).filter(Branch.Branch_ID == active_branch_id).first()
    is_head_branch = any(hb.Branch_ID == active_branch_id for hb in head_branches)

    if is_head_branch:
        head_map[active_branch_obj.Branch_Name] = active_branch_id
        print(f"[REPORT] User is at HEAD branch: {active_branch_obj.Branch_Name}")
    else:
        from models import BranchHierarchy
        parent = db.query(BranchHierarchy).filter(
            BranchHierarchy.Sub_Branch_ID == active_branch_id
        ).first()

        if parent:
            parent_branch = db.query(Branch).filter(Branch.Branch_ID == parent.Parent_Branch_ID).first()
            if parent_branch:
                head_map[parent_branch.Branch_Name] = parent.Parent_Branch_ID
                print(f"[REPORT] User at sub-branch, parent HEAD: {parent_branch.Branch_Name}")
        else:
            head_map[active_branch_obj.Branch_Name] = active_branch_id
            print(f"[REPORT] No parent found, using active branch: {active_branch_obj.Branch_Name}")

    print(f"[REPORT] Head Map: {head_map}")

    # --- GET SALES DATA ---
    all_sales = report_service.get_sales_report(db, start_d, end_d)
    print(f"[REPORT] Total branches with sales: {len(all_sales)}")
    print(f"[REPORT] Sales branches: {list(all_sales.keys())}")

    # --- PROCESS SALES BY TERRITORY ---
    sales_data = {}

    for head_name, head_id in head_map.items():
        managed_branches = branch_service.get_managed_branches(db, str(head_id))
        branch_names = [b.Branch_Name for b in managed_branches]

        print(f"[REPORT] {head_name} manages {len(branch_names)} branches: {branch_names}")

        # Collect all model-variants across all branches
        all_model_variants = set()
        territory_branches = []

        for branch_name in branch_names:
            if branch_name in all_sales:
                branch_data = all_sales[branch_name]
                territory_branches.append({
                    'name': branch_name,
                    'data': branch_data
                })
                # Collect all model-variants (excluding TOTAL)
                all_model_variants.update([k for k in branch_data.keys() if k != 'TOTAL'])
                print(f"  ✓ {branch_name}: {sum([v for k, v in branch_data.items() if k != 'TOTAL'])} sales")

        if territory_branches:
            sales_data[head_name] = {
                'branches': territory_branches,
                'models': sorted(list(all_model_variants)) + ['TOTAL'],  # Add TOTAL at end
                'has_total': True
            }
            print(
                f"[REPORT] Territory {head_name}: {len(territory_branches)} branches, {len(all_model_variants)} model-variants")

    # --- GET TRANSFER DATA ---
    transfer_data = {}

    for head_name, head_id in head_map.items():
        transfer_summary = report_service.get_branch_transfer_summary(db, head_id, start_d, end_d)

        print(f"[REPORT] Transfers from {head_name}: {len(transfer_summary['destinations'])} destinations")

        if transfer_summary['destinations']:
            destinations = []

            for dest_name, dest_data in transfer_summary['destinations'].items():
                quantities = []
                for mv in transfer_summary['model_variants']:
                    quantities.append(dest_data.get(mv, 0))

                destinations.append({
                    'name': dest_name,
                    'quantities': quantities,
                    'total': dest_data.get('TOTAL', 0)
                })
                print(f"  → {dest_name}: {dest_data.get('TOTAL', 0)} units")

            transfer_data[head_name] = {
                'destinations': destinations,
                'model_variants': transfer_summary['model_variants']
            }

    print(f"\n[REPORT] FINAL RESULTS:")
    print(f"  - Sales Territories: {list(sales_data.keys())}")
    print(f"  - Transfer Sources: {list(transfer_data.keys())}")
    print(f"{'=' * 60}\n")

    return templates.TemplateResponse(
        "reports_daily_sales_transfers.html",
        {
            "request": request,
            **context,
            "start_date": start_d.strftime("%Y-%m-%d"),
            "end_date": end_d.strftime("%Y-%m-%d"),
            "start_date_display": start_d.strftime("%d-%b-%Y"),
            "end_date_display": end_d.strftime("%d-%b-%Y"),
            "sales_data": sales_data,
            "transfer_data": transfer_data,
            "current_page": "reports"
        }
    )


@router.get("/debug-sales-data")
async def debug_sales_data(
        request: Request,
        start_date: str = Query(None),
        end_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """Debug endpoint to check raw sales data"""

    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not start_date or not end_date:
        end_d = datetime.now().date()
        start_d = end_d - timedelta(days=30)
    else:
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Get sales data using service
    sales_data = report_service.get_sales_report(db, start_d, end_d)

    # Get raw transaction counts
    from sqlalchemy import func

    txn_counts = db.query(
        InventoryTransaction.Transaction_Type,
        func.count(InventoryTransaction.id).label('count'),
        func.sum(InventoryTransaction.Quantity).label('total_qty')
    ).filter(
        InventoryTransaction.Date >= start_d,
        InventoryTransaction.Date <= end_d
    ).group_by(
        InventoryTransaction.Transaction_Type
    ).all()

    # Get date range of available data
    date_range_check = db.query(
        func.min(InventoryTransaction.Date).label('min_date'),
        func.max(InventoryTransaction.Date).label('max_date'),
        func.count(InventoryTransaction.id).label('total_count')
    ).first()

    return JSONResponse({
        "requested_date_range": f"{start_d} to {end_d}",
        "database_date_range": {
            "min_date": str(date_range_check.min_date) if date_range_check.min_date else None,
            "max_date": str(date_range_check.max_date) if date_range_check.max_date else None,
            "total_transactions": date_range_check.total_count
        },
        "sales_by_branch": sales_data,
        "transaction_counts": {
            txn_type: {
                "count": count,
                "total_quantity": int(qty) if qty else 0
            }
            for txn_type, count, qty in txn_counts
        },
        "total_branches_with_sales": len(sales_data)
    })


# ==================== STOCK SUMMARY REPORT (OPTIMIZED WITH MODEL-VARIANT) ====================
@router.get("/stock-summary", response_class=HTMLResponse)
async def stock_summary_report(
        request: Request,
        db: Session = Depends(get_db)
):
    """Current Stock Summary Report - Optimized with Model-Variant Breakdown"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Create branch mapping (already loaded, no extra query)
    branch_map = {b.Branch_ID: b.Branch_Name for b in managed_branches}

    # ===== SINGLE DB CALL: Fetch all vehicles at once =====
    query = db.query(
        VehicleMaster.current_branch_id,
        VehicleMaster.model,
        VehicleMaster.variant,
        VehicleMaster.color,
        VehicleMaster.chassis_no
    ).filter(
        VehicleMaster.current_branch_id.in_(branch_ids),
        VehicleMaster.status == "In Stock"
    )

    # Load into DataFrame (single DB call)
    df = pd.read_sql(query.statement, db.get_bind())

    if df.empty:
        return templates.TemplateResponse(
            "reports_stock_summary.html",
            {
                "request": request,
                **context,
                "total_stock": 0,
                "branch_stock": [],
                "models": [],
                "colors": [],
                "variants": [],
                "model_variant_summary": [],
                "current_page": "reports"
            }
        )

    # Add branch names
    df['branch_name'] = df['current_branch_id'].map(branch_map)

    total_stock = len(df)

    # ===== BRANCH-WISE SUMMARY (in-memory) =====
    branch_stock = []

    branch_grouped = df.groupby('branch_name')
    for branch_name, branch_df in branch_grouped:
        # Model counts for this branch
        model_counts = branch_df['model'].value_counts().to_dict()

        branch_stock.append({
            'name': branch_name,
            'total': len(branch_df),
            'models': [
                {'name': k, 'count': int(v)}
                for k, v in sorted(model_counts.items(), key=lambda x: x[1], reverse=True)
            ]
        })

    # Sort by total stock descending
    branch_stock = sorted(branch_stock, key=lambda x: x['total'], reverse=True)

    # ===== OVERALL MODEL SUMMARY (in-memory) =====
    model_counts = df['model'].value_counts().to_dict()
    models = [
        {
            'name': k,
            'count': int(v),
            'percentage': round((v / total_stock * 100), 1)
        }
        for k, v in model_counts.items()
    ]
    models = sorted(models, key=lambda x: x['count'], reverse=True)

    # ===== COLOR SUMMARY (in-memory) =====
    color_counts = df['color'].value_counts().to_dict()
    colors = [
        {
            'name': k,
            'count': int(v),
            'percentage': round((v / total_stock * 100), 1)
        }
        for k, v in color_counts.items()
    ]
    colors = sorted(colors, key=lambda x: x['count'], reverse=True)

    # ===== VARIANT SUMMARY (in-memory) =====
    variant_counts = df['variant'].value_counts().to_dict()
    variants = [
        {
            'name': k,
            'count': int(v),
            'percentage': round((v / total_stock * 100), 1)
        }
        for k, v in variant_counts.items()
    ]
    variants = sorted(variants, key=lambda x: x['count'], reverse=True)

    # ===== MODEL-VARIANT BREAKDOWN (in-memory) =====
    model_variant_summary = []

    model_grouped = df.groupby('model')
    for model, model_df in model_grouped:
        # Variant breakdown for this model
        variant_counts = model_df['variant'].value_counts().to_dict()

        # Color breakdown for this model
        color_counts = model_df['color'].value_counts().to_dict()

        # Branch-wise breakdown for this model
        branch_counts = model_df['branch_name'].value_counts().to_dict()

        model_total = len(model_df)
        model_percentage = round((model_total / total_stock * 100), 1)

        model_variant_summary.append({
            'model': model,
            'total': model_total,
            'percentage': model_percentage,
            'variants': [
                {
                    'name': k,
                    'count': int(v),
                    'percentage': round((v / model_total * 100), 1)
                }
                for k, v in sorted(variant_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            'colors': [
                {
                    'name': k,
                    'count': int(v),
                    'percentage': round((v / model_total * 100), 1)
                }
                for k, v in sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            'branches': [
                {
                    'name': k,
                    'count': int(v)
                }
                for k, v in sorted(branch_counts.items(), key=lambda x: x[1], reverse=True)
            ]
        })

    # Sort by total descending
    model_variant_summary = sorted(model_variant_summary, key=lambda x: x['total'], reverse=True)

    return templates.TemplateResponse(
        "reports_stock_summary.html",
        {
            "request": request,
            **context,
            "total_stock": total_stock,
            "branch_stock": branch_stock,
            "models": models,
            "colors": colors,
            "variants": variants,
            "model_variant_summary": model_variant_summary,
            "current_page": "reports"
        }
    )


# ==================== HMSI INWARD REPORT ====================
@router.get("/hmsi-inward", response_class=HTMLResponse)
async def hmsi_inward_report(
        request: Request,
        from_date: str = Query(None),
        to_date: str = Query(None),
        db: Session = Depends(get_db)
):
    """HMSI Inward Report - OEM Stock Receipts"""

    if not check_auth(request):
        return RedirectResponse(url="/login")

    context = get_context_data(request, db)
    active_branch_id = context["active_context"]

    # Set default date range (last 30 days)
    if not from_date:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = datetime.now().strftime("%Y-%m-%d")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").date()

    # Get managed branches
    managed_branches = branch_service.get_managed_branches(db, active_branch_id)
    branch_ids = [branch.Branch_ID for branch in managed_branches]

    # Aggregate data across all managed branches
    all_summary_data = []
    all_load_data = []
    all_daily_data = []

    for branch_id in branch_ids:
        # Get summary data
        summary_df = report_service.get_oem_inward_summary(db, branch_id, from_dt, to_dt)
        if not summary_df.empty:
            summary_df['Branch_ID'] = branch_id
            all_summary_data.append(summary_df)

        # Get load data
        load_df = report_service.get_oem_inward_by_load(db, branch_id, from_dt, to_dt)
        if not load_df.empty:
            load_df['Branch_ID'] = branch_id
            all_load_data.append(load_df)

        # Get daily trend
        daily_df = report_service.get_oem_inward_daily_trend(db, branch_id, from_dt, to_dt)
        if not daily_df.empty:
            daily_df['Branch_ID'] = branch_id
            all_daily_data.append(daily_df)

    # Combine all data
    summary_df = pd.concat(all_summary_data) if all_summary_data else pd.DataFrame()
    load_df = pd.concat(all_load_data) if all_load_data else pd.DataFrame()
    daily_df = pd.concat(all_daily_data) if all_daily_data else pd.DataFrame()

    # Calculate summary metrics
    total_received = int(summary_df['Total_Received'].sum()) if not summary_df.empty else 0
    total_loads = len(load_df['Load_Number'].unique()) if not load_df.empty else 0

    # Today's count
    today = datetime.now().date()
    today_received = int(daily_df[daily_df['Date'] == today]['Total_Vehicles'].sum()) if not daily_df.empty else 0

    # This week's count
    week_start = today - timedelta(days=today.weekday())
    week_received = int(daily_df[daily_df['Date'] >= week_start]['Total_Vehicles'].sum()) if not daily_df.empty else 0

    summary_metrics = {
        'total_received': total_received,
        'total_loads': total_loads,
        'today_received': today_received,
        'week_received': week_received,
        'branches_count': len(branch_ids)
    }

    # Format summary data for template (grouped by Model)
    model_summary = []
    if not summary_df.empty:
        for model in summary_df['Model'].unique():
            model_data = summary_df[summary_df['Model'] == model]

            variants = []
            for _, row in model_data.iterrows():
                # Get branch name
                branch = db.query(Branch).filter(Branch.Branch_ID == row['Branch_ID']).first()
                branch_name = branch.Branch_Name if branch else 'Unknown'

                variants.append({
                    'variant': row['Variant'],
                    'color': row['Color'],
                    'quantity': int(row['Total_Received']),
                    'branch': branch_name
                })

            model_total = int(model_data['Total_Received'].sum())
            model_percentage = round((model_total / total_received * 100), 1) if total_received > 0 else 0

            model_summary.append({
                'name': model,
                'total': model_total,
                'percentage': model_percentage,
                'variants': variants
            })

        # Sort by total descending
        model_summary = sorted(model_summary, key=lambda x: x['total'], reverse=True)

    # Format load details for template
    load_details = []
    if not load_df.empty:
        # Group by load number
        for load_num in load_df['Load_Number'].unique():
            load_data = load_df[load_df['Load_Number'] == load_num]

            # Get first record for date and branch
            first_record = load_data.iloc[0]
            branch = db.query(Branch).filter(Branch.Branch_ID == first_record['Branch_ID']).first()

            # Get vehicles in this load
            vehicles = []
            for _, row in load_data.iterrows():
                vehicles.append({
                    'model': row['Model'],
                    'variant': row['Variant'],
                    'color': row['Color'],
                    'quantity': int(row['Quantity'])
                })

            load_details.append({
                'date': first_record['Date'].strftime("%d %b %Y"),
                'load_number': load_num,
                'branch': branch.Branch_Name if branch else 'Unknown',
                'total_vehicles': int(load_data['Quantity'].sum()),
                'vehicles': vehicles
            })

        # Sort by date descending
        load_details = sorted(load_details, key=lambda x: x['date'], reverse=True)

    # Format daily trend for chart
    daily_trend = []
    if not daily_df.empty:
        # Group by date and sum
        daily_grouped = daily_df.groupby('Date').agg({
            'Loads': 'sum',
            'Total_Vehicles': 'sum'
        }).reset_index()

        max_vehicles = daily_grouped['Total_Vehicles'].max()

        for _, row in daily_grouped.iterrows():
            percentage = round((row['Total_Vehicles'] / max_vehicles * 100)) if max_vehicles > 0 else 0
            daily_trend.append({
                'date': row['Date'].strftime("%d %b"),
                'loads': int(row['Loads']),
                'vehicles': int(row['Total_Vehicles']),
                'percentage': percentage
            })

    return templates.TemplateResponse(
        "reports_hmsi_inward.html",
        {
            "request": request,
            **context,
            "from_date": from_date,
            "to_date": to_date,
            "summary_metrics": summary_metrics,
            "model_summary": model_summary,
            "load_details": load_details,
            "daily_trend": daily_trend[-14:],  # Last 14 days
            "current_page": "reports"
        }
    )
