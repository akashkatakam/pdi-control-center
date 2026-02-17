# services/report_service.py
from typing import Dict, Any, List

from sqlalchemy.orm import Session, aliased
from sqlalchemy import func
import models
from models import IST_TIMEZONE, TransactionType,InventoryTransaction, Branch, VehicleMaster
import pandas as pd
from datetime import date, datetime, timedelta


def get_stock_aging_report(db: Session, branch_id: str = None) -> pd.DataFrame:
    """Calculates stock age buckets."""
    query = db.query(
        models.VehicleMaster.chassis_no,
        models.VehicleMaster.model,
        models.VehicleMaster.variant,
        models.VehicleMaster.color,
        models.VehicleMaster.date_received,
        models.Branch.Branch_Name
    ).join(models.Branch, models.VehicleMaster.current_branch_id == models.Branch.Branch_ID) \
        .filter(models.VehicleMaster.status == 'In Stock')

    if branch_id:
        query = query.filter(models.VehicleMaster.current_branch_id == branch_id)

    df = pd.read_sql(query.statement, db.get_bind())

    if df.empty: return pd.DataFrame()

    now = datetime.now(IST_TIMEZONE)
    df['date_received'] = pd.to_datetime(df['date_received'])

    if df['date_received'].dt.tz is None:
        df['date_received'] = df['date_received'].dt.tz_localize(IST_TIMEZONE)
    else:
        df['date_received'] = df['date_received'].dt.tz_convert(IST_TIMEZONE)

    df['Days_Old'] = (now - df['date_received']).dt.days

    bins = [0, 30, 60, 90, 9999]
    labels = ['0-30 Days', '31-60 Days', '61-90 Days', '90+ Days (Critical)']
    df['Age_Bucket'] = pd.cut(df['Days_Old'], bins=bins, labels=labels, right=False)

    return df



def get_oem_inward_summary(db: Session, branch_id: str, start_date: date, end_date: date) -> pd.DataFrame:
    query = (
        db.query(
            models.InventoryTransaction.Model,
            models.InventoryTransaction.Variant,
            models.InventoryTransaction.Color,
            func.sum(models.InventoryTransaction.Quantity).label("Total_Received")
        )
        .filter(
            models.InventoryTransaction.Transaction_Type == TransactionType.INWARD_OEM,
            models.InventoryTransaction.Current_Branch_ID == branch_id,
            models.InventoryTransaction.Date >= start_date,
            models.InventoryTransaction.Date <= end_date
        )
        .group_by(models.InventoryTransaction.Model, models.InventoryTransaction.Variant,
                  models.InventoryTransaction.Color)
        .order_by(models.InventoryTransaction.Model, models.InventoryTransaction.Variant)
    )
    return pd.read_sql(query.statement, db.get_bind())



def get_daily_summary(db: Session, date_val: date) -> pd.DataFrame:
    """Returns a summary of Sales and Transfers for the given date, grouped by Branch."""
    query = (
        db.query(
            models.Branch.Branch_Name,
            models.InventoryTransaction.Transaction_Type,
            func.count(models.InventoryTransaction.id).label("Count")
        )
        .join(models.Branch, models.InventoryTransaction.Current_Branch_ID == models.Branch.Branch_ID)
        .filter(
            models.InventoryTransaction.Date == date_val,
            models.InventoryTransaction.Transaction_Type.in_([
                models.TransactionType.SALE,
                models.TransactionType.OUTWARD_TRANSFER
            ])
        )
        .group_by(models.Branch.Branch_Name, models.InventoryTransaction.Transaction_Type)
    )

    return pd.read_sql(query.statement, db.get_bind())


def get_sales_report(db: Session, start_date: date, end_date: date) -> Dict[str, Dict[str, int]]:
    """
    Get sales report for all branches within date range.
    Returns: {
        'Branch Name': {
            'Model1-Variant1': quantity,
            'Model1-Variant2': quantity,
            'Model2-Variant1': quantity,
            'TOTAL': total_quantity
        }
    }
    """
    try:
        # Query sales transactions with variant
        sales = db.query(
            Branch.Branch_Name,
            InventoryTransaction.Model,
            InventoryTransaction.Variant,
            func.sum(InventoryTransaction.Quantity).label('total_quantity')
        ).join(
            Branch, Branch.Branch_ID == InventoryTransaction.Current_Branch_ID
        ).filter(
            InventoryTransaction.Transaction_Type == "SALE",
            InventoryTransaction.Date >= start_date,
            InventoryTransaction.Date <= end_date
        ).group_by(
            Branch.Branch_Name,
            InventoryTransaction.Model,
            InventoryTransaction.Variant
        ).all()

        if not sales:
            print("[REPORT SERVICE] No sales data found")
            return {}

        # Build nested dictionary structure
        sales_dict = {}
        for branch_name, model, variant, quantity in sales:
            if branch_name not in sales_dict:
                sales_dict[branch_name] = {}

            # Combine model and variant as key
            model_variant_key = f"{model}-{variant}"
            sales_dict[branch_name][model_variant_key] = int(quantity) if quantity else 0

        # Add TOTAL for each branch
        for branch_name in sales_dict:
            sales_dict[branch_name]['TOTAL'] = sum(sales_dict[branch_name].values())

        print(f"[REPORT SERVICE] Sales data for {len(sales_dict)} branches")
        for branch, data in sales_dict.items():
            print(f"  - {branch}: {data}")

        return sales_dict

    except Exception as e:
        print(f"[REPORT SERVICE ERROR - Sales] {str(e)}")
        import traceback
        traceback.print_exc()
        return {}


def get_branch_transfer_summary(db: Session, from_branch_id: int, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Get transfer summary for outward transfers from a specific branch.
    Returns: {
        'destinations': {
            'Destination Branch': {
                'Model1-Variant1': quantity,
                'Model2-Variant2': quantity,
                'TOTAL': total_quantity
            }
        },
        'model_variants': ['Model1-Variant1', 'Model2-Variant2', ...]
    }
    """
    ToBranch = aliased(models.Branch)
    try:
        # Query outward transfers
        transfers = db.query(
            ToBranch.Branch_Name.label("Destination_Branch"),
            models.InventoryTransaction.Model,
            models.InventoryTransaction.Variant,
            func.sum(models.InventoryTransaction.Quantity).label("Total_Quantity")
        ).join(
            ToBranch, models.InventoryTransaction.To_Branch_ID == ToBranch.Branch_ID
        ).filter(
            models.InventoryTransaction.Transaction_Type == TransactionType.OUTWARD_TRANSFER,
            models.InventoryTransaction.Current_Branch_ID == from_branch_id,
            models.InventoryTransaction.Date >= start_date,
            models.InventoryTransaction.Date <= end_date
        ).group_by(
            ToBranch.Branch_Name,
            InventoryTransaction.Model,
            InventoryTransaction.Variant
        ).all()

        if not transfers:
            print(f"[REPORT SERVICE] No transfers from branch {from_branch_id}")
            return {'destinations': {}, 'model_variants': []}

        # Build nested dictionary structure
        destinations = {}
        model_variants_set = set()

        for dest_branch, model, variant, quantity in transfers:
            if dest_branch not in destinations:
                destinations[dest_branch] = {}

            model_variant_key = f"{model}-{variant}"
            model_variants_set.add(model_variant_key)
            destinations[dest_branch][model_variant_key] = int(quantity) if quantity else 0

        # Add TOTAL for each destination
        for dest_branch in destinations:
            destinations[dest_branch]['TOTAL'] = sum(destinations[dest_branch].values())

        # Sort model variants
        model_variants = sorted(list(model_variants_set))

        print(f"[REPORT SERVICE] Transfers to {len(destinations)} destinations")

        return {
            'destinations': destinations,
            'model_variants': model_variants
        }

    except Exception as e:
        print(f"[REPORT SERVICE ERROR - Transfers] {str(e)}")
        import traceback
        traceback.print_exc()
        return {'destinations': {}, 'model_variants': []}



def get_oem_inward_by_load(db: Session, branch_id: str, start_date: date, end_date: date) -> pd.DataFrame:
    """Get OEM inward details grouped by load number"""
    query = (
        db.query(
            models.InventoryTransaction.Date,
            models.InventoryTransaction.Load_Number,
            models.InventoryTransaction.Model,
            models.InventoryTransaction.Variant,
            models.InventoryTransaction.Color,
            models.InventoryTransaction.Quantity,
            models.InventoryTransaction.Remarks
        )
        .filter(
            models.InventoryTransaction.Transaction_Type == "INWARD",
            models.InventoryTransaction.Current_Branch_ID == branch_id,
            models.InventoryTransaction.Date >= start_date,
            models.InventoryTransaction.Date <= end_date,
            models.InventoryTransaction.Remarks.like('%HMSI%')
        )
        .order_by(models.InventoryTransaction.Date.desc())
    )

    df = pd.read_sql(query.statement, db.get_bind())
    return df


def get_oem_inward_daily_trend(db: Session, branch_id: str, start_date: date, end_date: date) -> pd.DataFrame:
    """Get daily trend of OEM inward"""
    query = (
        db.query(
            models.InventoryTransaction.Date,
            func.count(func.distinct(models.InventoryTransaction.Load_Number)).label("Loads"),
            func.sum(models.InventoryTransaction.Quantity).label("Total_Vehicles")
        )
        .filter(
            models.InventoryTransaction.Transaction_Type == models.TransactionType.INWARD_OEM,
            models.InventoryTransaction.Current_Branch_ID == branch_id,
            models.InventoryTransaction.Date >= start_date,
            models.InventoryTransaction.Date <= end_date,
            models.InventoryTransaction.Remarks.like('%HMSI%')
        )
        .group_by(models.InventoryTransaction.Date)
        .order_by(models.InventoryTransaction.Date)
    )

    df = pd.read_sql(query.statement, db.get_bind())
    return df


